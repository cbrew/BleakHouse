"""Inverted-index axis store: forward and reverse lookups, AND/OR semantics,
N-axis extensibility (BleakHouse-g3hj acceptance)."""
from __future__ import annotations

from pathlib import Path

import pytest

from enrichment.axis_store import AxisStore, declare_default_axes, uuid7
from enrichment.expdb.store import Store


@pytest.fixture
def populated(tmp_db_path: Path) -> tuple[Store, AxisStore]:
    """A store with three episodes covering the canonical axes."""
    store = Store(tmp_db_path)
    store.init_schema()
    store.upsert_episode(
        novel="bleak_house", panel="literary", pipeline="transport",
        hostprep=True, generator="anthropic_sonnet_4_6", ref_tools=False,
        label="bh_lit_trn", length="long",
    )
    store.upsert_episode(
        novel="bleak_house", panel="alternatives", pipeline="embedding",
        hostprep=False, generator="anthropic_sonnet_4_6", ref_tools=False,
        label="bh_alt_emb", length="long",
    )
    store.upsert_episode(
        novel="wuthering_heights", panel="literary", pipeline="transport",
        hostprep=True, generator="anthropic_sonnet_4_6", ref_tools=False,
        label="wh_lit_trn", length="short",
    )
    return store, AxisStore(tmp_db_path)


# ---- uuid7 ----


def test_uuid7_is_sortable() -> None:
    """Sequential UUIDv7s are lexically ordered by time."""
    import time
    a = uuid7()
    time.sleep(0.002)
    b = uuid7()
    assert a < b
    assert len(a) == 36
    # Version nibble at position 14 must be '7'
    assert a[14] == "7"


# ---- forward / reverse ----


def test_axes_for_returns_canonical_values(populated) -> None:
    store, axis_store = populated
    eps = store.list_episodes()
    bh_lit = next(e for e in eps if e.label == "bh_lit_trn")
    axes = axis_store.axes_for(bh_lit.id)
    assert axes["novel"] == "bleak_house"
    assert axes["pipeline"] == "transport"
    assert axes["hostprep"] == "true"
    assert axes["length"] == "long"


def test_query_and_across_axes(populated) -> None:
    _, axis_store = populated
    ids = axis_store.query({"novel": "bleak_house", "pipeline": "transport"})
    assert len(ids) == 1
    axes = axis_store.axes_for(next(iter(ids)))
    assert axes["panel"] == "literary"


def test_query_or_within_axis(populated) -> None:
    _, axis_store = populated
    ids = axis_store.query({"novel": {"bleak_house", "wuthering_heights"}})
    assert len(ids) == 3


def test_query_accepts_short_codes_via_canonicalization(populated) -> None:
    """Legacy callers passing 'bh' / 'trn' get the right answer."""
    _, axis_store = populated
    ids_short = axis_store.query({"novel": "bh", "pipeline": "trn"})
    ids_long = axis_store.query({"novel": "bleak_house", "pipeline": "transport"})
    assert ids_short == ids_long
    assert len(ids_short) == 1


def test_query_with_no_constraints_returns_all(populated) -> None:
    _, axis_store = populated
    ids = axis_store.query()
    assert len(ids) == 3


def test_query_empty_when_no_match(populated) -> None:
    _, axis_store = populated
    ids = axis_store.query({"novel": "bleak_house", "pipeline": "rag"})
    assert ids == set()


def test_opaque_id_round_trip(populated) -> None:
    store, axis_store = populated
    eps = store.list_episodes()
    bh_lit = next(e for e in eps if e.label == "bh_lit_trn")
    # opaque_id is on the row; AxisStore exposes it via axes_for_opaque
    import sqlite3
    with sqlite3.connect(store.path) as c:
        opaque = c.execute(
            "SELECT opaque_id FROM episode WHERE id=?", (bh_lit.id,)
        ).fetchone()[0]
    assert opaque is not None
    assert axis_store.axes_for_opaque(opaque) == axis_store.axes_for(bh_lit.id)


# ---- N-axis extensibility (acceptance criterion) ----


def test_adding_a_hypothetical_axis_works_without_table_changes(
    populated, monkeypatch
) -> None:
    """Stage a fake 'render_engine' axis in AXES, classify episodes, and query
    — no schema migration, no webapp file edits required (this test imports
    nothing from webapp/)."""
    from enrichment import axes as axes_mod

    fake_axis = axes_mod.Axis(
        name="render_engine",
        canonical_values=frozenset({"gemini", "qwen"}),
        aliases={"GEMINI": "gemini"},
    )
    # Patch the registry for this test only
    monkeypatch.setattr(
        axes_mod, "AXES", (*axes_mod.AXES, fake_axis), raising=True,
    )
    monkeypatch.setattr(
        axes_mod, "AXIS_BY_NAME",
        {**axes_mod.AXIS_BY_NAME, fake_axis.name: fake_axis},
        raising=True,
    )

    store, axis_store = populated
    eps = store.list_episodes()
    axis_store.declare_axis("render_engine")
    # Tag two episodes with different render engines
    bh_lit = next(e for e in eps if e.label == "bh_lit_trn")
    wh_lit = next(e for e in eps if e.label == "wh_lit_trn")
    # set_axes replaces all axes, so re-set including the existing ones
    existing = axis_store.axes_for(bh_lit.id)
    axis_store.set_axes(bh_lit.id, {**existing, "render_engine": "gemini"})
    existing = axis_store.axes_for(wh_lit.id)
    axis_store.set_axes(wh_lit.id, {**existing, "render_engine": "qwen"})

    assert axis_store.query({"render_engine": "gemini"}) == {bh_lit.id}
    assert axis_store.query({"render_engine": "qwen"}) == {wh_lit.id}
    # And aliases still work
    assert axis_store.query({"render_engine": "GEMINI"}) == {bh_lit.id}


# ---- declare_default_axes ----


def test_declare_default_axes_idempotent(tmp_db_path: Path) -> None:
    Store(tmp_db_path).init_schema()
    axis_store = AxisStore(tmp_db_path)
    declare_default_axes(axis_store)
    declare_default_axes(axis_store)  # twice
    import sqlite3
    with sqlite3.connect(tmp_db_path) as c:
        names = {r[0] for r in c.execute("SELECT name FROM axis").fetchall()}
    from enrichment.axes import AXES
    assert {a.name for a in AXES} <= names


def test_set_axes_rejects_unknown_axis(populated) -> None:
    store, axis_store = populated
    eps = store.list_episodes()
    with pytest.raises(ValueError, match="unknown axis"):
        axis_store.set_axes(eps[0].id, {"not_a_real_axis": "x"})
