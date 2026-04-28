from __future__ import annotations

from pathlib import Path

import pytest

from enrichment.expdb.store import Store


@pytest.fixture
def store_with_script(tmp_db_path: Path) -> tuple[Store, int]:
    s = Store(tmp_db_path)
    s.init_schema()
    eid = s.upsert_episode(novel="bh", panel="literary", pipeline="trn",
                            hostprep=False, label="bh_trn_literary")
    sid = s.create_script_version(episode_id=eid, path="x.json", dvc_hash="h",
                                    n_segments=1, n_turns=1, n_utterances=1)
    return s, sid


def test_create_run_returns_id(store_with_script: tuple[Store, int]) -> None:
    s, sid = store_with_script
    rid = s.create_generation_run(
        script_version_id=sid,
        generator="anthropic_sonnet_4_6",
        git_commit="abc123",
        dvc_rev="def456",
        config={"temperature": 0.7},
        finished_at=1700000000.0,
    )
    assert rid >= 1


def test_get_run_returns_parsed_config(store_with_script: tuple[Store, int]) -> None:
    s, sid = store_with_script
    rid = s.create_generation_run(
        script_version_id=sid, generator="cerebras_qwen",
        git_commit=None, dvc_rev=None,
        config={"model": "qwen-3-235b"},
        finished_at=1700000000.0,
    )
    run = s.get_generation_run(rid)
    assert run is not None
    assert run.generator == "cerebras_qwen"
    assert run.config == {"model": "qwen-3-235b"}


def test_list_runs_for_script(store_with_script: tuple[Store, int]) -> None:
    s, sid = store_with_script
    s.create_generation_run(script_version_id=sid, generator="g1",
                              git_commit="c1", dvc_rev=None, config={},
                              finished_at=1700000000.0)
    s.create_generation_run(script_version_id=sid, generator="g2",
                              git_commit="c2", dvc_rev=None, config={},
                              finished_at=1700000001.0)
    out = s.list_runs_for_script(sid)
    assert {r.generator for r in out} == {"g1", "g2"}
