"""SQLite-backed cache for source-tool results.

Keyed on (tool_name, canonical_json(input)). Stores only successful results
— transient failures must retry on the next call.

Path is `<project>/.cache/refverify.sqlite` by default; override via the
REFVERIFY_CACHE env var. Pruned by TTL (default 30 days) on read.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TTL_SECONDS = 30 * 24 * 3600  # 30 days


def default_cache_path() -> Path:
    override = os.environ.get("REFVERIFY_CACHE")
    if override:
        return Path(override).expanduser()
    repo = Path(__file__).resolve().parent.parent.parent
    return repo / ".cache" / "refverify.sqlite"


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tool_cache ("
        "  tool TEXT NOT NULL,"
        "  input_json TEXT NOT NULL,"
        "  result_json TEXT NOT NULL,"
        "  cached_at REAL NOT NULL,"
        "  PRIMARY KEY (tool, input_json)"
        ")"
    )
    return conn


def _key(tool_input: dict[str, Any]) -> str:
    return json.dumps(tool_input, sort_keys=True, default=str)


def get(tool: str, tool_input: dict[str, Any], *,
        path: Path | None = None) -> list[Any] | None:
    """Return cached result list, or None if absent/expired."""
    p = path or default_cache_path()
    if not p.exists():
        return None
    key = _key(tool_input)
    try:
        with _connect(p) as conn:
            row = conn.execute(
                "SELECT result_json, cached_at FROM tool_cache "
                "WHERE tool = ? AND input_json = ?",
                (tool, key),
            ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("cache read failed: %s", exc)
        return None
    if row is None:
        return None
    result_json, cached_at = row
    if time.time() - cached_at > _TTL_SECONDS:
        return None
    try:
        return json.loads(result_json)
    except json.JSONDecodeError:
        return None


def put(tool: str, tool_input: dict[str, Any], result: list[Any], *,
        path: Path | None = None) -> None:
    p = path or default_cache_path()
    key = _key(tool_input)
    try:
        with _connect(p) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO tool_cache "
                "(tool, input_json, result_json, cached_at) "
                "VALUES (?, ?, ?, ?)",
                (tool, key, json.dumps(result, default=str), time.time()),
            )
    except sqlite3.Error as exc:
        logger.warning("cache write failed: %s", exc)


def stats(*, path: Path | None = None) -> dict[str, Any]:
    p = path or default_cache_path()
    if not p.exists():
        return {"path": str(p), "entries": 0}
    with _connect(p) as conn:
        total = conn.execute("SELECT COUNT(*) FROM tool_cache").fetchone()[0]
        per_tool = dict(conn.execute(
            "SELECT tool, COUNT(*) FROM tool_cache GROUP BY tool ORDER BY 2 DESC"
        ).fetchall())
    return {"path": str(p), "entries": total, "per_tool": per_tool}
