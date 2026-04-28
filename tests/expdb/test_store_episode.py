from __future__ import annotations

from pathlib import Path

import pytest

from enrichment.expdb.store import Store


@pytest.fixture
def store(tmp_db_path: Path) -> Store:
    s = Store(tmp_db_path)
    s.init_schema()
    return s


def test_upsert_episode_returns_id(store: Store) -> None:
    eid = store.upsert_episode(novel="bh", panel="literary", pipeline="trn",
                                hostprep=False, label="bh_trn_literary")
    assert eid >= 1


def test_upsert_episode_is_idempotent(store: Store) -> None:
    a = store.upsert_episode(novel="bh", panel="literary", pipeline="trn",
                              hostprep=False, label="bh_trn_literary")
    b = store.upsert_episode(novel="bh", panel="literary", pipeline="trn",
                              hostprep=False, label="bh_trn_literary")
    assert a == b


def test_get_episode_round_trips(store: Store) -> None:
    eid = store.upsert_episode(novel="bh", panel="literary", pipeline="trn",
                                hostprep=False, label="bh_trn_literary")
    ep = store.get_episode(eid)
    assert ep is not None
    assert ep.novel == "bh"
    assert ep.panel == "literary"
    assert ep.pipeline == "trn"
    assert ep.hostprep is False
    assert ep.label == "bh_trn_literary"


def test_list_episodes_filters_by_novel(store: Store) -> None:
    store.upsert_episode(novel="bh",   panel="literary",      pipeline="trn",
                          hostprep=False, label="bh_trn_literary")
    store.upsert_episode(novel="bh",   panel="alternatives",  pipeline="trn",
                          hostprep=False, label="bh_trn_alternatives")
    store.upsert_episode(novel="motf", panel="literary",      pipeline="trn",
                          hostprep=False, label="motf_trn_literary")
    bh = store.list_episodes(novel="bh")
    assert sorted(e.label for e in bh) == ["bh_trn_alternatives", "bh_trn_literary"]
