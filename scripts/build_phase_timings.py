"""Snapshot phase-timing computations to data/runs/<run>/phase_timings.json.

The runtime computation in webapp.app:_phase_timings_from_mtimes() reads
file mtimes to derive Phase 0 / 1 / 2 / 2.5 / 3 durations. Those mtimes
survive on the host filesystem but get reset to image-build time when
files pass through Podman's COPY layer, so the matrix histograms render
empty on Fly.

This snapshotter freezes the mtime-derived numbers into a per-run JSON
file at pipeline time. The webapp prefers that file at read time, so the
durations stay correct regardless of how the run dir reaches the server.

Idempotent. Re-run after a re-render to refresh.

Usage:
    uv run python scripts/build_phase_timings.py --all
    uv run python scripts/build_phase_timings.py --run bh_trn_literary_hostprep
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from webapp.app import _phase_timings_from_mtimes  # pyright: ignore[reportMissingImports]

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "data" / "runs"
SNAPSHOT_NAME = "phase_timings.json"


def snapshot_run(run_id: str) -> bool:
    """Compute and write phase_timings.json for one run. Returns True if
    a non-empty snapshot was written."""
    rd = RUNS_DIR / run_id
    if not rd.is_dir():
        logger.warning("missing run dir: %s", run_id)
        return False
    timings = _phase_timings_from_mtimes(rd)
    if not timings:
        return False
    out = rd / SNAPSHOT_NAME
    out.write_text(json.dumps(timings, indent=2, sort_keys=True))
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", help="single run-id")
    g.add_argument("--all", action="store_true", help="snapshot every run dir")
    args = parser.parse_args()

    if args.run:
        runs = [args.run]
    else:
        runs = sorted(
            p.name for p in RUNS_DIR.iterdir()
            if p.is_dir() and p.name != "_archive"
        )

    written = 0
    for r in runs:
        if snapshot_run(r):
            written += 1
    logger.info("snapshotted %d / %d runs", written, len(runs))


if __name__ == "__main__":
    main()
