from __future__ import annotations

from pathlib import Path

import pytest

from enrichment.expdb.store import Store


@pytest.fixture
def populated(tmp_db_path: Path) -> tuple[Store, int, int, int]:
    s = Store(tmp_db_path)
    s.init_schema()
    eid = s.upsert_episode(novel="bh", panel="literary", pipeline="trn",
                            hostprep=False, generator="anthropic_sonnet_4_6",
                            label="bh_trn_literary")
    sid = s.create_script_version(episode_id=eid, path="x.json", dvc_hash="h",
                                    n_segments=1, n_turns=1, n_utterances=1)
    cfg = s.upsert_tts_config(engine="g", profile="p", voice_ref_ver=None, config={})
    aid = s.create_audio_artifact(script_version_id=sid, tts_config_id=cfg,
                                    name="p.mp3", path="p.mp3", dvc_hash=None)
    return s, sid, cfg, aid


def test_record_evaluation_against_script(populated: tuple[Store, int, int, int]) -> None:
    s, sid, _, _ = populated
    s.record_evaluation(script_version_id=sid, audio_artifact_id=None,
                         metric_kind="quote_verification",
                         metric={"verified": 42, "total": 42, "rate": 100.0})
    out = s.list_evaluations_for_script(sid)
    assert len(out) == 1
    assert out[0].metric_kind == "quote_verification"
    assert out[0].metric == {"verified": 42, "total": 42, "rate": 100.0}


def test_record_evaluation_against_audio(populated: tuple[Store, int, int, int]) -> None:
    s, _, _, aid = populated
    s.record_evaluation(script_version_id=None, audio_artifact_id=aid,
                         metric_kind="asr_wer",
                         metric={"wer": 0.083})
    out = s.list_evaluations_for_audio(aid)
    assert len(out) == 1
    assert out[0].metric == {"wer": 0.083}


def test_create_regeneration_request(populated: tuple[Store, int, int, int]) -> None:
    s, _, cfg, aid = populated
    new_cfg = s.upsert_tts_config(engine="g2", profile="p2",
                                    voice_ref_ver=None, config={})
    rid = s.create_regeneration_request(
        audio_artifact_id=aid, new_tts_config_id=new_cfg,
        scope="turn:3:5",
    )
    rr = s.get_regeneration_request(rid)
    assert rr is not None
    assert rr.audio_artifact_id == aid
    assert rr.new_tts_config_id == new_cfg
    assert rr.scope == "turn:3:5"
    assert rr.fulfilled_audio_artifact is None
