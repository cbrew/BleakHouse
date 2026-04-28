from __future__ import annotations

from pathlib import Path

import pytest

from enrichment.expdb.store import Store


@pytest.fixture
def store(tmp_db_path: Path) -> Store:
    s = Store(tmp_db_path)
    s.init_schema()
    return s


GEN = "anthropic_sonnet_4_6"


def test_upsert_episode_returns_id(store: Store) -> None:
    eid = store.upsert_episode(novel="bh", panel="literary", pipeline="trn",
                                hostprep=False, generator=GEN,
                                label="bh_trn_literary")
    assert eid >= 1


def test_upsert_episode_is_idempotent(store: Store) -> None:
    a = store.upsert_episode(novel="bh", panel="literary", pipeline="trn",
                              hostprep=False, generator=GEN,
                              label="bh_trn_literary")
    b = store.upsert_episode(novel="bh", panel="literary", pipeline="trn",
                              hostprep=False, generator=GEN,
                              label="bh_trn_literary")
    assert a == b


def test_get_episode_round_trips(store: Store) -> None:
    eid = store.upsert_episode(novel="bh", panel="literary", pipeline="trn",
                                hostprep=False, generator=GEN,
                                label="bh_trn_literary")
    ep = store.get_episode(eid)
    assert ep is not None
    assert ep.novel == "bh"
    assert ep.panel == "literary"
    assert ep.pipeline == "trn"
    assert ep.hostprep is False
    assert ep.generator == GEN
    assert ep.label == "bh_trn_literary"


def test_list_episodes_filters_by_novel(store: Store) -> None:
    store.upsert_episode(novel="bh",   panel="literary",      pipeline="trn",
                          hostprep=False, generator=GEN, label="bh_trn_literary")
    store.upsert_episode(novel="bh",   panel="alternatives",  pipeline="trn",
                          hostprep=False, generator=GEN, label="bh_trn_alternatives")
    store.upsert_episode(novel="motf", panel="literary",      pipeline="trn",
                          hostprep=False, generator=GEN, label="motf_trn_literary")
    bh = store.list_episodes(novel="bh")
    assert sorted(e.label for e in bh) == ["bh_trn_alternatives", "bh_trn_literary"]


def test_generator_is_part_of_episode_key(store: Store) -> None:
    """Same axes tuple, different generators → distinct episodes."""
    a = store.upsert_episode(novel="bh", panel="alternatives", pipeline="trn",
                              hostprep=True, generator="anthropic_sonnet_4_6",
                              label="bh_trn_alternatives_hostprep")
    b = store.upsert_episode(novel="bh", panel="alternatives", pipeline="trn",
                              hostprep=True, generator="cerebras_qwen",
                              label="bh_trn_alternatives_hostprep_cerebras_qwen")
    c = store.upsert_episode(novel="bh", panel="alternatives", pipeline="trn",
                              hostprep=True, generator="cerebras_zai_glm",
                              label="bh_trn_alternatives_hostprep_cerebras_zai_glm")
    assert len({a, b, c}) == 3
