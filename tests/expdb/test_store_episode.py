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


def _ep(store: Store, **overrides) -> int:
    """Default-fill upsert_episode; tests pass only the axes they vary."""
    kwargs: dict = dict(
        novel="bh", panel="literary", pipeline="trn",
        hostprep=False, generator=GEN, ref_tools=False,
        label="bh_trn_literary",
    )
    kwargs.update(overrides)
    return store.upsert_episode(**kwargs)


def test_upsert_episode_returns_id(store: Store) -> None:
    assert _ep(store) >= 1


def test_upsert_episode_is_idempotent(store: Store) -> None:
    a = _ep(store)
    b = _ep(store)
    assert a == b


def test_get_episode_round_trips(store: Store) -> None:
    eid = _ep(store)
    ep = store.get_episode(eid)
    assert ep is not None
    assert ep.novel == "bh"
    assert ep.panel == "literary"
    assert ep.pipeline == "trn"
    assert ep.hostprep is False
    assert ep.generator == GEN
    assert ep.ref_tools is False
    assert ep.label == "bh_trn_literary"


def test_list_episodes_filters_by_novel(store: Store) -> None:
    _ep(store, label="bh_trn_literary")
    _ep(store, panel="alternatives", label="bh_trn_alternatives")
    _ep(store, novel="motf", label="motf_trn_literary")
    bh = store.list_episodes(novel="bh")
    assert sorted(e.label for e in bh) == ["bh_trn_alternatives", "bh_trn_literary"]


def test_generator_is_part_of_episode_key(store: Store) -> None:
    """Same axes, different generators → distinct episodes."""
    a = _ep(store, panel="alternatives", hostprep=True,
             generator="anthropic_sonnet_4_6",
             label="bh_trn_alternatives_hostprep")
    b = _ep(store, panel="alternatives", hostprep=True,
             generator="cerebras_qwen",
             label="bh_trn_alternatives_hostprep_cerebras_qwen")
    c = _ep(store, panel="alternatives", hostprep=True,
             generator="cerebras_zai_glm",
             label="bh_trn_alternatives_hostprep_cerebras_zai_glm")
    assert len({a, b, c}) == 3


def test_ref_tools_is_part_of_episode_key(store: Store) -> None:
    """Same axes, different ref_tools settings → distinct episodes.

    Captures the case where the same hostprep run was generated once
    without --reference-tools and again with it. The two are distinct
    experimental conditions.
    """
    without = _ep(store, hostprep=True, ref_tools=False,
                   label="cran_nop_literary_hostprep")
    with_   = _ep(store, hostprep=True, ref_tools=True,
                   label="cran_nop_literary_hostprep_retrofit_v1")
    assert without != with_
