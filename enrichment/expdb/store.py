"""Experiment ledger Store — SQLite, stdlib only."""
from __future__ import annotations

import sqlite3
from importlib.resources import files
from pathlib import Path

EXPECTED_USER_VERSION = 1


def _schema_sql() -> str:
    return (files("enrichment.expdb") / "schema.sql").read_text()


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        return c

    def init_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            current = c.execute("PRAGMA user_version").fetchone()[0]
            if current >= EXPECTED_USER_VERSION:
                return  # already initialised at this version or later
            c.executescript(_schema_sql())
            c.execute(f"PRAGMA user_version = {EXPECTED_USER_VERSION}")
