"""Retrofit hostprep for one source run (BleakHouse-us0).

Creates a sibling dir `<source_run>_retrofit_v1/`, copies phase 0–2
artefacts from the source, then invokes `enrichment.run_pipeline` with
`--host-prep --resume-from 3`. The pipeline loads phases 1+2 from disk
(skipping their cost) and generates phase 2.5 (interviews + briefs)
+ phase 3 (script) fresh. The original source run is untouched.

Usage:
    uv run python scripts/retrofit_hostprep.py <source_run_id> [--dry-run]

Output: data/runs/<source_run_id>_retrofit_v1/ with
    phase2_5_interviews.json
    phase2_5_host_briefs.json
    phase3_episode.json
    retrofit_manifest.json   (provenance: source_run, retrofit_date, models)
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_PHASE_INPUTS = (
    "manifest.json",
    "phase0_segments.json",
    "phase1_assignments.json",
    "phase2_plan.json",
    "config.json",
)


def stage_inputs(source_dir: Path, retrofit_dir: Path) -> None:
    retrofit_dir.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_PHASE_INPUTS:
        src = source_dir / name
        if not src.exists():
            raise SystemExit(f"FAIL: {src} not present in source run")
        shutil.copy2(src, retrofit_dir / name)


def write_retrofit_manifest(source_dir: Path, retrofit_dir: Path) -> None:
    src_run_manifest = json.loads((source_dir / "run_manifest.json").read_text())
    rm = {
        "schema_version": 1,
        "retrofit_of": source_dir.name,
        "retrofit_date": datetime.now(timezone.utc).isoformat(),
        "axes": src_run_manifest.get("axes", {}),
        "source_dvc_lock_sha": src_run_manifest.get("dvc_lock_sha"),
    }
    (retrofit_dir / "retrofit_manifest.json").write_text(json.dumps(rm, indent=2))


def write_run_manifest(source_dir: Path, retrofit_dir: Path,
                       reference_tools: bool) -> None:
    """Write a run_manifest.json so the experiment-DB backfill picks up the
    retrofit. We don't run DVC for retrofits, so this is hand-built from the
    source's axes plus retrofit-specific provenance.
    """
    src_run_manifest = json.loads((source_dir / "run_manifest.json").read_text())
    rm = {
        "schema_version": 1,
        "run_id": retrofit_dir.name,
        "axes": src_run_manifest.get("axes", {}),
        # Retrofit-specific provenance — useful for the DB to know.
        "retrofit_of": source_dir.name,
        "reference_tools": reference_tools,
        "stages": {
            "phase2_5": {"fresh": True},
            "phase3": {"fresh": True},
        },
        "audio_variants": [],   # no audio rendered for retrofits
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (retrofit_dir / "run_manifest.json").write_text(json.dumps(rm, indent=2))


def _novel_to_full_name(short: str) -> str:
    return {
        "bh": "bleak_house", "motf": "mill_on_the_floss", "omf": "our_mutual_friend",
        "nas": "north_and_south", "pti": "passage_to_india", "mid": "middlemarch",
        "dd": "daniel_deronda", "dc": "david_copperfield", "ht": "hard_times",
        "cran": "cranford", "ngs": "new_grub_street", "oddw": "odd_women",
        "noname": "no_name", "mmar": "miss_marjoribanks", "hest": "hester",
    }.get(short, short)


def _pipeline_to_full_name(short: str) -> str:
    return {"trn": "transport", "emb": "embedding", "nop": "no-passages",
            "rag": "rag"}.get(short, short)


def build_pipeline_cmd(retrofit_dir: Path, source_axes: dict,
                        reference_tools: bool) -> list[str]:
    novel = source_axes.get("novel", "bh")
    pipeline = source_axes.get("pipeline", "trn")
    cmd = [
        "uv", "run", "python", "-m", "enrichment.run_pipeline",
        "--novel", _novel_to_full_name(novel),
        "--name", retrofit_dir.name,
        "--pipeline", _pipeline_to_full_name(pipeline),
        "--host-prep",
        "--resume-from", "3",  # load phases 1+2 from disk; run phase 2.5 + 3
    ]
    if reference_tools:
        cmd += ["--reference-tools"]
    # Non-default panels need --replace-expert. Preset keys are shared between
    # ALTERNATIVE_EXPERTS (transport demand profiles) and ALTERNATIVE_PERSONAS
    # (script-time personae) in podcast_types.py / transport_podcast.py.
    panel_replacements = {
        "alternatives":      [("Eleanor Hartley", "sir_edmund"),
                               ("James Blackstone", "dr_rosen"),
                               ("Caroline Woodcourt", "trevelyan")],
        "interdisciplinary": [("Eleanor Hartley", "chen_nlp"),
                               ("James Blackstone", "martinez_astro"),
                               ("Caroline Woodcourt", "volkov_music")],
    }
    for old_name, preset in panel_replacements.get(source_axes.get("panel", ""), []):
        cmd += ["--replace-expert", f"{old_name}={preset}"]
    return cmd


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source_run_id")
    p.add_argument("--dry-run", action="store_true",
                   help="stage inputs + print the pipeline command, but don't invoke it")
    p.add_argument("--no-reference-tools", action="store_true",
                   help="disable OpenAlex/Wikipedia reference search (default: on)")
    args = p.parse_args()
    reference_tools = not args.no_reference_tools

    repo = Path(__file__).resolve().parent.parent
    source_dir = repo / "data" / "runs" / args.source_run_id
    if not source_dir.is_dir():
        sys.exit(f"FAIL: {source_dir} not found")

    # Timestamp-suffixed: the dir name is just an identifier. Treatment
    # metadata (ref_tools, generator, etc.) lives in DB rows, not in the
    # filename. Multiple retrofits of the same source can coexist on disk.
    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    retrofit_dir = source_dir.parent / f"{args.source_run_id}_retrofit_{suffix}"
    if retrofit_dir.exists():
        sys.exit(f"FAIL: {retrofit_dir} already exists (timestamp collision?)")

    src_run_manifest = json.loads((source_dir / "run_manifest.json").read_text())
    if not src_run_manifest.get("axes", {}).get("hostprep"):
        sys.exit("FAIL: source run is not hostprep — nothing to retrofit")

    print(f"==> staging phase 0–2 inputs from {source_dir.name}")
    stage_inputs(source_dir, retrofit_dir)
    write_retrofit_manifest(source_dir, retrofit_dir)

    cmd = build_pipeline_cmd(retrofit_dir, src_run_manifest["axes"], reference_tools)
    print(f"==> reference_tools = {reference_tools}")
    if args.dry_run:
        print("DRY-RUN — pipeline command would be:")
        print("  " + " ".join(cmd))
        print("NOTE: no API calls were made.")
        return

    t0 = time.perf_counter()
    rc = subprocess.run(cmd, cwd=repo, check=False).returncode
    elapsed = time.perf_counter() - t0
    if rc != 0:
        sys.exit(f"FAIL: pipeline returned {rc} ({elapsed:.0f}s wall)")

    print("==> writing run_manifest.json for backfill ingestion")
    write_run_manifest(source_dir, retrofit_dir, reference_tools)
    print(f"OK: retrofit produced at {retrofit_dir} ({elapsed:.0f}s wall)")


if __name__ == "__main__":
    main()
