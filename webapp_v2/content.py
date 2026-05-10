"""content.db read helpers for the v2 webapp.

content.db is the single read source for everything except audio bytes
(which live in R2, addressed by md5). Connections are opened read-only
and reused per process. JSON payloads are decoded lazily.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = _REPO_ROOT / "data" / "content.db"

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_db_path: Path = DEFAULT_DB_PATH


def configure(db_path: Path) -> None:
    """Override the content.db path. Must be called before the first read."""
    global _db_path, _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None
        _db_path = db_path


def _connection() -> sqlite3.Connection:
    """Lazily open a read-only shared connection to content.db.

    Read-only mode (mode=ro via URI) so a misuse can't write to the DB
    from a request handler. WAL stays enabled — writes happen in
    build_content_db.py, reads here are concurrent with builds.
    """
    global _conn
    with _lock:
        if _conn is None:
            uri = f"file:{_db_path}?mode=ro"
            _conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
        return _conn


@dataclass(frozen=True)
class RunIndex:
    """One row of the derived run_index table."""
    run_id: str
    novel: str
    panel: str
    pipeline: str
    length: str
    hostprep: bool
    ref_tools: bool
    generator: str
    has_audio: bool


def _row_to_run_index(row: sqlite3.Row) -> RunIndex:
    return RunIndex(
        run_id=row["run_id"],
        novel=row["novel"],
        panel=row["panel"],
        pipeline=row["pipeline"],
        length=row["length"],
        hostprep=bool(row["hostprep"]),
        ref_tools=bool(row["ref_tools"]),
        generator=row["generator"],
        has_audio=bool(row["has_audio"]),
    )


def read_run_artifact(run_id: str, kind: str) -> Any | None:
    """Return the parsed JSON payload for a (run_id, kind), or None."""
    row = _connection().execute(
        "SELECT payload FROM run_artifact WHERE run_id=? AND kind=?",
        (run_id, kind),
    ).fetchone()
    return json.loads(row["payload"]) if row else None


def read_novel_artifact(novel: str, kind: str) -> Any | None:
    """Return the parsed JSON payload for a (novel, kind), or None."""
    row = _connection().execute(
        "SELECT payload FROM novel_artifact WHERE novel=? AND kind=?",
        (novel, kind),
    ).fetchone()
    return json.loads(row["payload"]) if row else None


def read_panel_artifact(panel_id: str) -> dict | None:
    """Return the parsed panel persona payload, or None."""
    row = _connection().execute(
        "SELECT payload FROM panel_artifact WHERE panel_id=?",
        (panel_id,),
    ).fetchone()
    return json.loads(row["payload"]) if row else None


def get_run_index(run_id: str) -> RunIndex | None:
    row = _connection().execute(
        "SELECT * FROM run_index WHERE run_id=?", (run_id,),
    ).fetchone()
    return _row_to_run_index(row) if row else None


def iter_run_index(
    *,
    has_audio: bool | None = None,
    novel: str | None = None,
    panel: str | None = None,
) -> Iterator[RunIndex]:
    """Stream rows from run_index, optionally filtered."""
    sql = "SELECT * FROM run_index WHERE 1=1"
    params: list[Any] = []
    if has_audio is not None:
        sql += " AND has_audio=?"
        params.append(int(has_audio))
    if novel is not None:
        sql += " AND novel=?"
        params.append(novel)
    if panel is not None:
        sql += " AND panel=?"
        params.append(panel)
    sql += " ORDER BY novel, panel, run_id"
    for row in _connection().execute(sql, params):
        yield _row_to_run_index(row)
