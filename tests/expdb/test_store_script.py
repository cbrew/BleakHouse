from __future__ import annotations

from pathlib import Path

import pytest

from enrichment.expdb.store import Store


@pytest.fixture
def store_with_episode(tmp_db_path: Path) -> tuple[Store, int]:
    s = Store(tmp_db_path)
    s.init_schema()
    eid = s.upsert_episode(novel="bh", panel="literary", pipeline="trn",
                            hostprep=False, generator="anthropic_sonnet_4_6",
                            label="bh_trn_literary")
    return s, eid


def test_create_script_returns_id(store_with_episode: tuple[Store, int]) -> None:
    s, eid = store_with_episode
    sid = s.create_script_version(
        episode_id=eid,
        path="data/runs/bh_trn_literary/phase3_episode.json",
        dvc_hash="0889681df9ebc4bb0f6ec85e9f53ef98",
        n_segments=7, n_turns=85, n_utterances=363,
    )
    assert sid >= 1


def test_get_script_round_trips(store_with_episode: tuple[Store, int]) -> None:
    s, eid = store_with_episode
    sid = s.create_script_version(
        episode_id=eid,
        path="x.json", dvc_hash=None,
        n_segments=1, n_turns=1, n_utterances=1,
    )
    sv = s.get_script_version(sid)
    assert sv is not None
    assert sv.episode_id == eid
    assert sv.path == "x.json"
    assert sv.dvc_hash is None
    assert sv.n_segments == 1


def test_list_scripts_for_episode(store_with_episode: tuple[Store, int]) -> None:
    s, eid = store_with_episode
    s.create_script_version(episode_id=eid, path="a.json", dvc_hash="h1",
                             n_segments=1, n_turns=1, n_utterances=1)
    s.create_script_version(episode_id=eid, path="b.json", dvc_hash="h2",
                             n_segments=2, n_turns=2, n_utterances=2)
    out = s.list_scripts_for_episode(eid)
    assert {sv.path for sv in out} == {"a.json", "b.json"}
