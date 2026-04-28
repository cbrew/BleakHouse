from __future__ import annotations

from pathlib import Path

import pytest

from enrichment.expdb.store import Store


@pytest.fixture
def store_with_episode(tmp_db_path: Path) -> tuple[Store, int]:
    s = Store(tmp_db_path)
    s.init_schema()
    eid = s.upsert_episode(
        novel="bh", panel="literary", pipeline="trn", hostprep=True,
        generator="anthropic_sonnet_4_6", ref_tools=False,
        label="bh_trn_literary_hostprep",
    )
    return s, eid


def test_create_hostprep_returns_id(store_with_episode: tuple[Store, int]) -> None:
    s, eid = store_with_episode
    hpv = s.create_hostprep_version(
        episode_id=eid,
        interviews_path="data/runs/bh_trn_literary_hostprep/phase2_5_interviews.json",
        interviews_dvc_hash="hi",
        briefs_path="data/runs/bh_trn_literary_hostprep/phase2_5_host_briefs.json",
        briefs_dvc_hash="hb",
        n_segments=7, n_interviews=21, n_questions=44,
    )
    assert hpv >= 1


def test_get_hostprep_round_trips(store_with_episode: tuple[Store, int]) -> None:
    s, eid = store_with_episode
    hpv_id = s.create_hostprep_version(
        episode_id=eid,
        interviews_path="iv.json", interviews_dvc_hash=None,
        briefs_path="hb.json", briefs_dvc_hash=None,
        n_segments=7, n_interviews=21, n_questions=44,
    )
    hp = s.get_hostprep_version(hpv_id)
    assert hp is not None
    assert hp.episode_id == eid
    assert hp.n_segments == 7
    assert hp.n_interviews == 21
    assert hp.n_questions == 44


def test_script_can_link_to_hostprep(store_with_episode: tuple[Store, int]) -> None:
    s, eid = store_with_episode
    hpv_id = s.create_hostprep_version(
        episode_id=eid,
        interviews_path="iv.json", interviews_dvc_hash=None,
        briefs_path="hb.json", briefs_dvc_hash=None,
        n_segments=7, n_interviews=21, n_questions=44,
    )
    sid = s.create_script_version(
        episode_id=eid, path="phase3.json", dvc_hash=None,
        n_segments=7, n_turns=85, n_utterances=363,
        hostprep_version_id=hpv_id,
    )
    sv = s.get_script_version(sid)
    assert sv is not None
    assert sv.hostprep_version_id == hpv_id


def test_evaluation_can_attach_to_hostprep(store_with_episode: tuple[Store, int]) -> None:
    s, eid = store_with_episode
    hpv_id = s.create_hostprep_version(
        episode_id=eid,
        interviews_path="iv.json", interviews_dvc_hash=None,
        briefs_path="hb.json", briefs_dvc_hash=None,
        n_segments=7, n_interviews=21, n_questions=44,
    )
    s.record_evaluation(
        hostprep_version_id=hpv_id,
        metric_kind="reading_list_verification",
        metric={"verification_rate": 0.78, "total_proposed": 28, "total_verified": 22},
    )
    out = s.list_evaluations_for_hostprep(hpv_id)
    assert len(out) == 1
    assert out[0].metric_kind == "reading_list_verification"
    assert out[0].metric["verification_rate"] == 0.78


def test_record_evaluation_requires_at_least_one_target(store_with_episode: tuple[Store, int]) -> None:
    s, _ = store_with_episode
    with pytest.raises(ValueError):
        s.record_evaluation(metric_kind="orphan", metric={})
