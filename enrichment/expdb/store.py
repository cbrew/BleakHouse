"""Experiment ledger Store — SQLite, stdlib only."""
from __future__ import annotations

import sqlite3
import time
from importlib.resources import files
from pathlib import Path

from .models import Episode

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
                return
            c.executescript(_schema_sql())
            c.execute(f"PRAGMA user_version = {EXPECTED_USER_VERSION}")

    # ---- Episode ----

    def upsert_episode(self, *, novel: str, panel: str, pipeline: str,
                       hostprep: bool, label: str) -> int:
        with self._conn() as c:
            row = c.execute(
                "SELECT id FROM episode WHERE novel=? AND panel=? AND pipeline=? AND hostprep=?",
                (novel, panel, pipeline, int(hostprep)),
            ).fetchone()
            if row is not None:
                return int(row["id"])
            cur = c.execute(
                "INSERT INTO episode(novel, panel, pipeline, hostprep, label, created_at) "
                "VALUES(?,?,?,?,?,?)",
                (novel, panel, pipeline, int(hostprep), label, time.time()),
            )
            assert cur.lastrowid is not None
            return int(cur.lastrowid)

    def get_episode(self, episode_id: int) -> Episode | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM episode WHERE id=?", (episode_id,)).fetchone()
        return _row_to_episode(row) if row else None

    def list_episodes(self, *, novel: str | None = None) -> list[Episode]:
        sql = "SELECT * FROM episode"
        params: tuple = ()
        if novel is not None:
            sql += " WHERE novel=?"
            params = (novel,)
        sql += " ORDER BY id"
        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [_row_to_episode(r) for r in rows]


def _row_to_episode(row: sqlite3.Row) -> Episode:
    return Episode(
        id=int(row["id"]),
        novel=row["novel"],
        panel=row["panel"],
        pipeline=row["pipeline"],
        hostprep=bool(row["hostprep"]),
        label=row["label"],
        created_at=float(row["created_at"]),
    )
