"""Read-only SQLite connection helper for the webapp.

Endpoint code calls `db_conn()` and gets a fresh read-only connection
to `data/experiments.db` for the duration of the request. Connections
are cheap to open in SQLite, so we don't pool — one per request keeps
the threading story simple.

Before opening, we check whether the DB is stale relative to
`data/runs/` (via `enrichment.expdb.refresh.ensure_db_current`) and
re-scan if so. The mtime check is gated by the DB file's mtime against
a process-local cache, so the actual scan only runs when something
real has changed — typical request-path overhead is a single stat()
call.

Usage:

    from webapp.db import db_conn

    with db_conn() as conn:
        rows = conn.execute(
            "SELECT id, novel, panel FROM episode WHERE pipeline = ?",
            ("trn",),
        ).fetchall()
        # rows is list[sqlite3.Row]; access by name or index

The connection is closed when the context manager exits. Writes raise
`sqlite3.OperationalError` because the URI sets `mode=ro`.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from enrichment.expdb.refresh import ensure_db_current  # pyright: ignore[reportMissingImports]

logger = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parent.parent
_DB_PATH = _REPO / "data" / "experiments.db"

# Cache of "the DB mtime we last refreshed against" so we don't call
# ensure_db_current() on every request — only when the DB file's mtime
# differs from what we've already verified.
_last_seen_mtime: float = 0.0
_last_seen_lock = threading.Lock()


def _current_mtime() -> float:
    try:
        return _DB_PATH.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def _maybe_refresh() -> None:
    """Run ensure_db_current() iff the DB has changed since the last
    time we verified it. Cheap fast-path: one stat() call when the DB
    is steady. Thread-safe."""
    global _last_seen_mtime
    with _last_seen_lock:
        mtime = _current_mtime()
        if mtime == _last_seen_mtime and mtime > 0:
            return
        # Either first call (mtime=0 cache vs nonzero file), or DB has
        # been updated on disk by something else (a pipeline run, the
        # deploy script's pre-stage scan, etc).
        ensure_db_current()
        _last_seen_mtime = _current_mtime()


@contextmanager
def db_conn() -> Iterator[sqlite3.Connection]:
    """Yield a read-only connection to the experiments DB.

    The connection has `row_factory = sqlite3.Row` so callers can
    access columns by name. Closes on context exit.
    """
    _maybe_refresh()
    if not _DB_PATH.exists():
        raise FileNotFoundError(f"experiments.db not present at {_DB_PATH}")
    uri = f"file:{_DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
