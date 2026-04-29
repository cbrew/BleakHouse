"""Keep `data/experiments.db` in sync with `data/runs/`.

The contract: callers (the webapp, the deploy script, anything that reads
the DB) can call `ensure_db_current()` and trust the returned DB reflects
the current state of `data/runs/`. The implementation is a cheap mtime
check + on-demand re-scan; we don't rope DVC into this because the scan
is fast (< 30s for the full corpus) and DVC's directory dependencies
would drag the whole upstream pipeline into every "is the DB current?"
question.

Usage:
    from enrichment.expdb.refresh import ensure_db_current
    ensure_db_current()                 # uses default paths
    ensure_db_current(force=True)       # rescan even if mtimes look fresh
"""

from __future__ import annotations

import logging
from pathlib import Path

from .backfill import scan_runs_dir
from .store import Store

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB = _REPO / "data" / "experiments.db"
_DEFAULT_RUNS = _REPO / "data" / "runs"


def _newest_run_artefact_mtime(runs_dir: Path) -> float:
    """Return the latest mtime among files the scanner reads. Cheaper than
    walking every byte under data/runs — we only care about files that
    drive the DB (config.json, run_manifest.json, phase3_episode.json,
    phase2_5_reading_list.json). Missing dirs return 0."""
    if not runs_dir.is_dir():
        return 0.0
    targets = (
        "config.json",
        "run_manifest.json",
        "phase3_episode.json",
        "phase2_5_reading_list.json",
    )
    newest = 0.0
    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir():
            continue
        for name in targets:
            p = run_dir / name
            try:
                m = p.stat().st_mtime
            except FileNotFoundError:
                continue
            if m > newest:
                newest = m
    return newest


def ensure_db_current(
    db_path: Path | None = None,
    runs_dir: Path | None = None,
    *,
    force: bool = False,
) -> bool:
    """Re-scan if the DB is stale relative to data/runs/.

    Returns True if a scan ran, False if the DB was already current.
    """
    db_path = db_path or _DEFAULT_DB
    runs_dir = runs_dir or _DEFAULT_RUNS

    if not force and db_path.exists():
        # SQLite WAL mode means writes can land in <db>-wal before being
        # checkpointed to the main file, so the cluster's actual "last
        # written" time is the max mtime across .db / .db-wal / .db-shm.
        db_mtime = max(
            (p.stat().st_mtime
             for p in (db_path, db_path.with_suffix(".db-wal"),
                       db_path.with_suffix(".db-shm"))
             if p.exists()),
            default=0.0,
        )
        newest_run = _newest_run_artefact_mtime(runs_dir)
        if db_mtime >= newest_run:
            return False

    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = Store(db_path)
    summary = scan_runs_dir(store, runs_dir)
    # Idempotent scans don't write to the file, so the cluster's mtime
    # wouldn't reflect "we just verified the DB is current as of now".
    # Touch the main file to make subsequent ensure_db_current calls
    # see the DB as fresh.
    db_path.touch()
    logger.info(
        "expdb refresh: scanned=%d skipped=%d episodes_inserted=%d "
        "scripts_inserted=%d",
        summary.get("scanned", 0),
        summary.get("skipped", 0),
        summary.get("episodes_inserted", 0),
        summary.get("scripts_inserted", 0),
    )
    return True
