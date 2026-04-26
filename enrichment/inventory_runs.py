"""Classify every data/runs/*/ into the canonical axes schema.

Emits data/runs/_inventory.json: for each run directory, a record containing
the inferred (novel, pipeline, panel, hostprep, generator) tuple, the
evidence used, a confidence flag, and the proposed target dir name under
the new scheme.

No filesystem changes are made. This is the input to
`enrichment.migration_dry_run` (BleakHouse-bft).

Usage: `uv run python -m enrichment.inventory_runs`
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from enrichment.axes import (
    DEFAULT_GENERATOR,
    NOVEL_BY_ID,
    NOVEL_KEYS,
    RunAxes,
    panel_for_experts,
)

BASE_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = BASE_DIR / "data" / "runs"

# Historical pipeline-prefix aliases (legacy dir-name tokens → canonical pipeline).
# Multiple aliases for transport reflect the 4 different flavours run over time
# (ext, arc, hia, trn) — all collapse to a single canonical "trn".
PIPELINE_ALIAS: dict[str, str] = {
    "trn": "trn",
    "ext": "trn",
    "arc": "trn",
    "hia": "trn",
    "emb": "emb",
    "nop": "nop",
    "rag": "rag",
    # "rand" deliberately omitted — not in canonical PIPELINES; inventory flags these for review.
}

# Prefixes in the dir name that historically implied Bleak House (no novel prefix).
BH_IMPLYING_DIR_PREFIXES: frozenset[str] = frozenset({
    "arc", "ext", "hia", "trn",
    "emb", "nop", "rag", "rand",
    "interdisciplinary",
})

# Map legacy config.json pipeline strings to canonical ones.
CONFIG_PIPELINE_MAP: dict[str, str] = {
    "transport": "trn",
    "embedding": "emb",
    "no-passages": "nop",
    "no_passages": "nop",
    "rag": "rag",
    "trn": "trn",
    "emb": "emb",
    "nop": "nop",
}

logger = logging.getLogger(__name__)


def _load_config(run_dir: Path) -> dict[str, Any] | None:
    p = run_dir / "config.json"
    if not p.exists():
        return None
    try:
        with open(p) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError as e:
        logger.warning("%s: bad config.json (%s)", run_dir.name, e)
        return None


def _infer_novel(cfg: dict[str, Any] | None, dir_name: str) -> tuple[str | None, str]:
    """Return (novel_key, evidence)."""
    if cfg and cfg.get("novel"):
        nid = str(cfg["novel"])
        if nid in NOVEL_BY_ID:
            return NOVEL_BY_ID[nid].key, "config.novel"
        return None, f"config.novel={nid!r} not in NOVEL_BY_ID"
    first = dir_name.split("_", 1)[0]
    if first in NOVEL_KEYS:
        return first, "dir_name_prefix"
    if first in BH_IMPLYING_DIR_PREFIXES:
        return "bh", f"dir_name_prefix={first!r} implies bh"
    return None, f"cannot derive novel from dir_name first-token {first!r}"


def _infer_pipeline(cfg: dict[str, Any] | None, dir_name: str,
                    novel_evidence: str) -> tuple[str | None, str]:
    """Return (pipeline, evidence)."""
    if cfg and cfg.get("pipeline"):
        p = str(cfg["pipeline"])
        if p in CONFIG_PIPELINE_MAP:
            return CONFIG_PIPELINE_MAP[p], f"config.pipeline={p!r}"
        return None, f"config.pipeline={p!r} unrecognised"

    # Fall back to dir-name. For novel-prefixed names (cran_emb_v01_baseline),
    # pipeline is token[1]; for BH-implying prefixes (emb_v01_baseline), it's token[0].
    tokens = dir_name.split("_")
    candidate = tokens[1] if novel_evidence == "dir_name_prefix" else tokens[0]
    # "interdisciplinary_trn_hostprep" — pipeline is tokens[1]
    if tokens[0] == "interdisciplinary" and len(tokens) >= 2:
        candidate = tokens[1]

    if candidate in PIPELINE_ALIAS:
        return PIPELINE_ALIAS[candidate], f"dir_name_token={candidate!r}"
    if candidate == "rand":
        return None, "pipeline=rand not in canonical PIPELINES"
    return None, f"dir_name_token={candidate!r} not a recognised pipeline"


def _infer_hostprep(cfg: dict[str, Any] | None, run_dir: Path) -> tuple[bool, str]:
    """Hostprep is true if any of: config.host_prep, phase2_5_host_briefs.json exists,
    dir name ends with _hostprep. Returns (value, evidence)."""
    reasons: list[str] = []
    if cfg and cfg.get("host_prep"):
        reasons.append("config.host_prep=true")
    if (run_dir / "phase2_5_host_briefs.json").exists():
        reasons.append("phase2_5_host_briefs.json exists")
    if run_dir.name.endswith("_hostprep"):
        reasons.append("dir_name_suffix=_hostprep")
    return bool(reasons), "; ".join(reasons) if reasons else "no evidence"


def _infer_panel(cfg: dict[str, Any] | None) -> tuple[str | None, str, list[str]]:
    """Return (panel_id, evidence, experts_list)."""
    if not cfg:
        return None, "no config.json", []
    experts = [e.get("name", "") for e in cfg.get("experts", []) if isinstance(e, dict)]
    experts = [e for e in experts if e]
    if not experts:
        return None, "config.experts is empty", []
    panel = panel_for_experts(experts)
    if panel:
        return panel, f"experts_match_{panel}", experts
    return None, "experts do not match any canonical panel (archive candidate)", experts


def classify(run_dir: Path) -> dict[str, Any]:
    """Classify one run directory. Never raises; encodes problems in the dict."""
    name = run_dir.name
    cfg = _load_config(run_dir)

    novel, novel_ev = _infer_novel(cfg, name)
    pipeline, pipeline_ev = _infer_pipeline(cfg, name, novel_ev)
    panel, panel_ev, experts = _infer_panel(cfg)
    hostprep, hostprep_ev = _infer_hostprep(cfg, run_dir)
    generator = DEFAULT_GENERATOR  # every existing run predates multi-generator support

    prompt_version: int | None = None
    if cfg and isinstance(cfg.get("prompt_version"), int):
        prompt_version = int(cfg["prompt_version"])

    notes: list[str] = []
    if cfg is None:
        notes.append("no config.json")
    if novel is None:
        notes.append(f"novel: {novel_ev}")
    if pipeline is None:
        notes.append(f"pipeline: {pipeline_ev}")
    if panel is None:
        notes.append(f"panel: {panel_ev}")

    # Build target if all axes were derivable.
    target_name: str | None = None
    target_axes: dict[str, Any] | None = None
    if novel and pipeline and panel:
        try:
            axes = RunAxes(novel=novel, pipeline=pipeline, panel=panel,
                           hostprep=hostprep, generator=generator)
            target_name = axes.dir_name()
            target_axes = axes.to_dict()
        except ValueError as e:
            notes.append(f"RunAxes construction failed: {e}")

    if target_name is not None and notes:
        confidence = "inferred"
    elif target_name is not None:
        confidence = "exact"
    else:
        confidence = "ambiguous"

    # Archive recommendation: the run has valid data but doesn't fit the
    # canonical axes. Almost all of these are expert-swap experiments
    # (panel != literary|interdisciplinary|alternatives) or legacy pipeline
    # variants (pipeline=rand).
    archive_recommended = confidence == "ambiguous" and (
        (panel is None and len(experts) >= 2)
        or pipeline is None
    )

    resolution: str
    if confidence == "exact":
        resolution = "canonical"  # may be upgraded to "collision" in build_inventory
    elif archive_recommended:
        resolution = "archive"
    elif confidence == "inferred":
        resolution = "canonical"  # may be upgraded to "collision"
    else:
        resolution = "review"

    return {
        "run_dir": name,
        "confidence": confidence,
        "resolution": resolution,
        "target_dir_name": target_name,
        "target_axes": target_axes,
        "archive_recommended": archive_recommended,
        "evidence": {
            "novel": novel_ev,
            "pipeline": pipeline_ev,
            "panel": panel_ev,
            "hostprep": hostprep_ev,
            "generator": "default (anthropic_sonnet_4_6)",
        },
        "experts": experts,
        "prompt_version": prompt_version,
        "has_config": cfg is not None,
        "notes": notes,
    }


def build_inventory() -> dict[str, Any]:
    if not RUNS_DIR.exists():
        raise RuntimeError(f"{RUNS_DIR} not found")

    records: list[dict[str, Any]] = []
    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir():
            continue
        if run_dir.name.startswith("_"):
            continue  # already-archived or metadata
        records.append(classify(run_dir))

    # Collisions: multiple old dirs mapping to the same new name.
    target_counts: dict[str, list[str]] = defaultdict(list)
    for r in records:
        if r["target_dir_name"]:
            target_counts[r["target_dir_name"]].append(r["run_dir"])
    collisions = {k: v for k, v in target_counts.items() if len(v) > 1}

    # Upgrade colliding canonicals to resolution="collision"
    colliding = {old for olds in collisions.values() for old in olds}
    for r in records:
        if r["run_dir"] in colliding:
            r["resolution"] = "collision"

    by_confidence: dict[str, int] = defaultdict(int)
    for r in records:
        by_confidence[r["confidence"]] += 1
    by_resolution: dict[str, int] = defaultdict(int)
    for r in records:
        by_resolution[r["resolution"]] += 1

    archive_count = sum(1 for r in records if r["archive_recommended"])

    return {
        "version": "1",
        "generated_from": "enrichment.inventory_runs",
        "runs_dir": str(RUNS_DIR.relative_to(BASE_DIR)),
        "summary": {
            "total": len(records),
            "by_confidence": dict(by_confidence),
            "by_resolution": dict(by_resolution),
            "archive_recommended": archive_count,
            "collisions": collisions,
        },
        "runs": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=RUNS_DIR / "_inventory.json",
                        help="Where to write the inventory JSON.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    inv = build_inventory()
    args.output.write_text(json.dumps(inv, indent=2))

    s = inv["summary"]
    print(f"Inventoried {s['total']} run directories")
    print("  by_confidence:")
    for k, v in sorted(s["by_confidence"].items()):
        print(f"    {k:12s} {v}")
    print("  by_resolution:")
    for k, v in sorted(s["by_resolution"].items()):
        print(f"    {k:12s} {v}")
    print(f"  collisions (same target_dir_name): {len(s['collisions'])}")
    if s["collisions"]:
        for new, olds in sorted(s["collisions"].items())[:5]:
            print(f"    {new}  <-  {olds}")
        if len(s["collisions"]) > 5:
            print(f"    ... and {len(s['collisions']) - 5} more")
    print(f"\nWrote {args.output}")


if __name__ == "__main__":
    main()
