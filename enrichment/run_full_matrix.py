"""Orchestrate the full 180-run experiment matrix.

15 novels × 2 panels × 3 pipelines (transport, embedding, no-passages)
× 2 host-prep settings = 180 runs.

For transport and embedding: Phases 0-2 are shared between hostprep and
non-hostprep for the same novel × panel × pipeline combo.
Hostprep runs copy Phase 0-2 outputs from the corresponding non-hostprep
run and use --resume-from 3 --host-prep.

For no-passages: each run is self-contained (Phases 1+2 are trivially
empty). Hostprep runs copy Phase 0 from the corresponding non-hostprep
run and use --resume-from 3 --host-prep.

Usage:
    uv run python -m enrichment.run_full_matrix --dry-run
    uv run python -m enrichment.run_full_matrix
    uv run python -m enrichment.run_full_matrix --only-missing
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from enrichment.axes import NOVEL_BY_ID, RunAxes

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = BASE_DIR / "data" / "runs"

# Novels in the matrix (by axes.Novel.id).
NOVELS: list[str] = [n.id for n in NOVEL_BY_ID.values()]

# Canonical panels sweep by this matrix. Expansion to 'interdisciplinary'
# would go here if/when we run that panel across all novels.
PANELS: list[str] = ["literary", "alternatives"]

PANEL_REPLACEMENTS: dict[str, list[str]] = {
    "literary": [],
    "alternatives": [
        "Eleanor Hartley=trevelyan",
        "James Blackstone=sir_edmund",
        "Caroline Woodcourt=dr_rosen",
    ],
}

PIPELINES = ["transport", "embedding", "no_passages"]

# Map human-readable pipeline labels used by this matrix to axes ids.
# All transport runs now use 'trn' — the legacy 'ext' Bleak-House-only
# alias is gone with the axis migration.
PIPELINE_TO_AXES: dict[str, str] = {
    "transport":   "trn",
    "embedding":   "emb",
    "no_passages": "nop",
}

PHASE_FILES = ["phase0_segments.json", "phase1_assignments.json", "phase2_plan.json"]


def run_name(novel_key: str, pipeline: str, panel: str, hostprep: bool) -> str:
    """Canonical run directory name via axes.RunAxes."""
    if novel_key not in NOVEL_BY_ID:
        raise ValueError(f"unknown novel {novel_key!r}")
    return RunAxes(
        novel=NOVEL_BY_ID[novel_key].key,
        pipeline=PIPELINE_TO_AXES[pipeline],
        panel=panel,
        hostprep=hostprep,
    ).dir_name()


def has_episode(name: str) -> bool:
    return (RUNS_DIR / name / "phase3_episode.json").exists()


def has_phases_0_2(name: str) -> bool:
    run_dir = RUNS_DIR / name
    return all((run_dir / f).exists() for f in PHASE_FILES)


def copy_phases_0_2(src_name: str, dst_name: str) -> None:
    """Copy Phase 0-2 outputs from src run to dst run."""
    src_dir = RUNS_DIR / src_name
    dst_dir = RUNS_DIR / dst_name
    dst_dir.mkdir(parents=True, exist_ok=True)
    for f in PHASE_FILES:
        shutil.copy2(src_dir / f, dst_dir / f)
    logger.info("Copied Phase 0-2 from %s → %s", src_name, dst_name)


def run_pipeline(
    novel_key: str,
    pipeline: str,
    panel: str,
    hostprep: bool,
    resume_from: int | None = None,
) -> None:
    """Execute a single pipeline run."""
    name = run_name(novel_key, pipeline, panel, hostprep)

    pipeline_arg = "no-passages" if pipeline == "no_passages" else pipeline
    cmd = [
        sys.executable, "-m", "enrichment.run_pipeline",
        "--name", name,
        "--novel", novel_key,
        "--pipeline", pipeline_arg,
        "--prompt-version", "2",
    ]

    for replacement in PANEL_REPLACEMENTS[panel]:
        cmd.extend(["--replace-expert", replacement])

    if hostprep:
        cmd.append("--host-prep")

    if resume_from is not None:
        cmd.extend(["--resume-from", str(resume_from)])

    env = {**os.environ, "BLEAKHOUSE_NOVEL": novel_key}

    logger.info("RUN: %s", name)
    subprocess.run(cmd, env=env, check=True)


def build_matrix() -> list[dict]:
    """Build the full 180-run matrix with dependency info."""
    matrix = []
    for novel_key in NOVELS:
        for panel in PANELS:
            for pipeline in PIPELINES:
                base_name = run_name(novel_key, pipeline, panel, hostprep=False)
                hp_name = run_name(novel_key, pipeline, panel, hostprep=True)

                matrix.append({
                    "novel": novel_key,
                    "panel": panel,
                    "pipeline": pipeline,
                    "hostprep": False,
                    "name": base_name,
                    "depends_on": None,
                })
                matrix.append({
                    "novel": novel_key,
                    "panel": panel,
                    "pipeline": pipeline,
                    "hostprep": True,
                    "name": hp_name,
                    "depends_on": base_name,
                })

    return matrix


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the full 180-condition experiment matrix"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be run without executing",
    )
    parser.add_argument(
        "--only-missing", action="store_true",
        help="Only run conditions that don't have phase3_episode.json yet",
    )
    parser.add_argument(
        "--novel", type=str, default=None,
        help="Limit to a single novel",
    )
    parser.add_argument(
        "--pipeline", type=str, default=None, choices=PIPELINES,
        help="Limit to a single pipeline type",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
    )

    matrix = build_matrix()

    # Apply filters
    if args.novel:
        matrix = [r for r in matrix if r["novel"] == args.novel]
    if args.pipeline:
        matrix = [r for r in matrix if r["pipeline"] == args.pipeline]

    # Separate into non-hostprep (run first) and hostprep (run second)
    base_runs = [r for r in matrix if not r["hostprep"]]
    hp_runs = [r for r in matrix if r["hostprep"]]

    if args.dry_run:
        print(f"{'Name':<45} {'Status':<12} {'Action'}")
        print("-" * 80)

    done = 0
    skipped = 0
    failed = 0

    # Phase A: non-hostprep runs (produce Phase 0-2 + Phase 3)
    for run in base_runs:
        name = run["name"]
        if args.only_missing and has_episode(name):
            if args.dry_run:
                print(f"{name:<45} {'exists':<12} skip")
            skipped += 1
            continue

        if args.dry_run:
            print(f"{name:<45} {'missing':<12} run full pipeline")
            continue

        try:
            run_pipeline(run["novel"], run["pipeline"], run["panel"], hostprep=False)
            done += 1
        except subprocess.CalledProcessError:
            logger.error("FAILED: %s", name)
            failed += 1

    # Phase B: hostprep runs (copy Phase 0-2 from base, run Phase 2.5 + 3)
    for run in hp_runs:
        name = run["name"]
        base = run["depends_on"]

        if args.only_missing and has_episode(name):
            if args.dry_run:
                print(f"{name:<45} {'exists':<12} skip")
            skipped += 1
            continue

        if not has_phases_0_2(base):
            if args.dry_run:
                print(f"{name:<45} {'blocked':<12} waiting on {base}")
            else:
                logger.warning("SKIP %s: base run %s has no Phase 0-2 outputs", name, base)
            skipped += 1
            continue

        if args.dry_run:
            print(f"{name:<45} {'missing':<12} copy P0-2 from {base}, run P2.5+3")
            continue

        try:
            copy_phases_0_2(base, name)
            run_pipeline(
                run["novel"], run["pipeline"], run["panel"],
                hostprep=True, resume_from=3,
            )
            done += 1
        except subprocess.CalledProcessError:
            logger.error("FAILED: %s", name)
            failed += 1

    if args.dry_run:
        total = len(base_runs) + len(hp_runs)
        existing = sum(1 for r in matrix if has_episode(r["name"]))
        print(f"\nTotal: {total} runs, {existing} exist, {total - existing} to do")
    else:
        logger.info("Done: %d succeeded, %d skipped, %d failed", done, skipped, failed)


if __name__ == "__main__":
    main()
