"""Inverted-index axis store backed by SQLite.

Identity is opaque (episode.id INTEGER + episode.opaque_id UUIDv7);
classification is by axes via the (episode_id, axis_name, value) relation
in `episode_axis`. Adding a new axis is a one-place edit in
`enrichment.axes.AXES` plus a backfill call — no schema migration, no
webapp filter rewrites.

Usage:
    from enrichment.axis_store import AxisStore
    store = AxisStore(Path("data/experiments.db"))

    # Forward lookup: id → axes
    axes = store.axes_for(episode_id=42)
    # → {"novel": "bleak_house", "pipeline": "transport", ...}

    # Reverse lookup: axes → ids
    ids = store.query({"novel": "bleak_house", "pipeline": "transport"})

    # OR within an axis: novel ∈ {bleak_house, wuthering_heights}
    ids = store.query({"novel": {"bleak_house", "wuthering_heights"}})

    # Setting axes for a freshly-scanned run
    store.set_axes(episode_id=42, axes={"novel": "bh", "pipeline": "trn", ...})
    # ↑ short codes accepted; canonicalized on the way in.
"""

from __future__ import annotations

import os
import sqlite3
import time
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path

from enrichment import axes as _axes  # late attribute access — supports monkeypatch
from enrichment.axes import canonicalize_value


def uuid7() -> str:
    """RFC 9562 UUIDv7: 48-bit unix_ms timestamp + 4-bit version + 12-bit rand_a
    + 2-bit variant + 62-bit rand_b. Stdlib `uuid` lacks this through Python
    3.13. Prefer over uuid4 for sortability — sequentially generated IDs are
    lexically ordered by time, useful for cursor pagination and bucketing."""
    ts_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand = int.from_bytes(os.urandom(10), "big")  # 80 random bits
    rand_a = (rand >> 64) & 0x0FFF                # 12 bits
    rand_b = rand & ((1 << 62) - 1)               # 62 bits
    n = (
        (ts_ms << 80)
        | (0x7 << 76)        # version 7
        | (rand_a << 64)
        | (0b10 << 62)       # variant 10 (RFC 4122)
        | rand_b
    )
    return str(uuid.UUID(int=n))


class AxisStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        return c

    # ---- Reading ----

    def axes_for(self, episode_id: int) -> dict[str, str]:
        """Return {axis_name: canonical_value} for one episode."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT axis_name, value FROM episode_axis WHERE episode_id=?",
                (episode_id,),
            ).fetchall()
        return {r["axis_name"]: r["value"] for r in rows}

    def axes_for_opaque(self, opaque_id: str) -> dict[str, str]:
        with self._conn() as c:
            row = c.execute(
                "SELECT id FROM episode WHERE opaque_id=?", (opaque_id,)
            ).fetchone()
        if row is None:
            return {}
        return self.axes_for(int(row["id"]))

    def query(
        self, axes: Mapping[str, str | Iterable[str]] | None = None,
    ) -> set[int]:
        """Return the set of episode ids matching the constraints.

        - AND across keys: query({a: x, b: y}) → episodes with a=x AND b=y.
        - OR within a key: query({a: {x, y}}) → episodes with a=x OR a=y.
        - Empty/None: every episode id.
        """
        if not axes:
            with self._conn() as c:
                rows = c.execute("SELECT id FROM episode").fetchall()
            return {int(r["id"]) for r in rows}

        result: set[int] | None = None
        with self._conn() as c:
            for axis_name, raw in axes.items():
                if isinstance(raw, str) or isinstance(raw, bool):
                    values: list[str] = [canonicalize_value(axis_name, raw)]
                else:
                    values = [canonicalize_value(axis_name, v) for v in raw]
                placeholders = ",".join("?" * len(values))
                rows = c.execute(
                    f"SELECT episode_id FROM episode_axis "
                    f"WHERE axis_name=? AND value IN ({placeholders})",
                    (axis_name, *values),
                ).fetchall()
                ids = {int(r["episode_id"]) for r in rows}
                result = ids if result is None else (result & ids)
                if not result:
                    return set()
        return result or set()

    def query_opaque(
        self, axes: Mapping[str, str | Iterable[str]] | None = None,
    ) -> set[str]:
        ids = self.query(axes)
        if not ids:
            return set()
        with self._conn() as c:
            placeholders = ",".join("?" * len(ids))
            rows = c.execute(
                f"SELECT opaque_id FROM episode WHERE id IN ({placeholders})",
                tuple(ids),
            ).fetchall()
        return {r["opaque_id"] for r in rows if r["opaque_id"]}

    # ---- Writing ----

    def declare_axis(self, axis_name: str) -> None:
        """Idempotently record that this axis exists. Values are not constrained
        in the table; canonicalization happens via enrichment.axes.AXES."""
        if axis_name not in _axes.AXIS_BY_NAME:
            raise ValueError(f"unknown axis {axis_name!r} (not in AXES)")
        with self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO axis(name) VALUES(?)", (axis_name,)
            )

    def set_axes(self, episode_id: int, axes: Mapping[str, object]) -> None:
        """Replace this episode's axis classifications. Values are
        canonicalized; unknown axes raise ValueError."""
        rows = [
            (episode_id, name, canonicalize_value(name, value))
            for name, value in axes.items()
        ]
        with self._conn() as c:
            c.execute("BEGIN")
            try:
                # Declare axis names first — episode_axis.axis_name FKs to axis(name).
                for name in {r[1] for r in rows}:
                    c.execute(
                        "INSERT OR IGNORE INTO axis(name) VALUES(?)", (name,)
                    )
                c.execute(
                    "DELETE FROM episode_axis WHERE episode_id=?", (episode_id,)
                )
                c.executemany(
                    "INSERT INTO episode_axis(episode_id, axis_name, value) "
                    "VALUES(?,?,?)",
                    rows,
                )
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise


def declare_default_axes(store: AxisStore) -> None:
    """Declare every axis from enrichment.axes.AXES. Safe to call repeatedly."""
    for a in _axes.AXES:
        store.declare_axis(a.name)
