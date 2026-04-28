"""init_schema creates the seven tables and bumps user_version."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from enrichment.expdb.store import EXPECTED_USER_VERSION, Store


def test_init_schema_creates_seven_tables(tmp_db_path: Path) -> None:
    Store(tmp_db_path).init_schema()
    with sqlite3.connect(tmp_db_path) as c:
        rows = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    names = {r[0] for r in rows}
    assert {"episode", "script_version", "generation_run", "tts_config",
            "audio_artifact", "evaluation", "regeneration_request"} <= names


def test_init_schema_sets_user_version(tmp_db_path: Path) -> None:
    Store(tmp_db_path).init_schema()
    with sqlite3.connect(tmp_db_path) as c:
        v = c.execute("PRAGMA user_version").fetchone()[0]
    assert v == EXPECTED_USER_VERSION


def test_init_schema_is_idempotent(tmp_db_path: Path) -> None:
    s = Store(tmp_db_path)
    s.init_schema()
    s.init_schema()  # second call must not raise
    with sqlite3.connect(tmp_db_path) as c:
        n = c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    assert n >= 7
