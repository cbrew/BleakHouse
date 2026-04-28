from __future__ import annotations

from pathlib import Path

import pytest

from enrichment.expdb.store import Store


@pytest.fixture
def fixture(tmp_db_path: Path) -> tuple[Store, int]:
    s = Store(tmp_db_path)
    s.init_schema()
    eid = s.upsert_episode(novel="bh", panel="literary", pipeline="trn",
                            hostprep=False, generator="anthropic_sonnet_4_6",
                            label="bh_trn_literary")
    sid = s.create_script_version(episode_id=eid, path="x.json", dvc_hash="h",
                                    n_segments=1, n_turns=1, n_utterances=1)
    return s, sid


def test_upsert_tts_config_dedupes(fixture: tuple[Store, int]) -> None:
    s, _ = fixture
    a = s.upsert_tts_config(engine="qwen3-tts-12hz", profile="qwen_designed_v1",
                             voice_ref_ver="v1", config={"x_vector_only": True})
    b = s.upsert_tts_config(engine="qwen3-tts-12hz", profile="qwen_designed_v1",
                             voice_ref_ver="v1", config={"x_vector_only": True})
    assert a == b


def test_create_audio_artifact_records_path_and_hash(fixture: tuple[Store, int]) -> None:
    s, sid = fixture
    cfg_id = s.upsert_tts_config(engine="gemini-2.0-flash", profile="classic",
                                  voice_ref_ver=None, config={})
    aid = s.create_audio_artifact(
        script_version_id=sid, tts_config_id=cfg_id,
        name="podcast.mp3",
        path="data/runs/bh_trn_literary/audio/podcast.mp3",
        dvc_hash="ea0b3082baa072eed50612e8fcd68fd8",
        duration_s=2606.0,
        audio_manifest_path="data/runs/bh_trn_literary/audio/manifest.json",
    )
    a = s.get_audio_artifact(aid)
    assert a is not None
    assert a.dvc_hash == "ea0b3082baa072eed50612e8fcd68fd8"
    assert a.duration_s == 2606.0


def test_list_audio_for_script_returns_all_variants(fixture: tuple[Store, int]) -> None:
    s, sid = fixture
    classic = s.upsert_tts_config(engine="gemini-2.0-flash", profile="classic",
                                   voice_ref_ver=None, config={})
    qwen   = s.upsert_tts_config(engine="qwen3-tts-12hz", profile="qwen_designed_v1",
                                  voice_ref_ver="v1", config={})
    s.create_audio_artifact(script_version_id=sid, tts_config_id=classic,
                              name="podcast.mp3", path="a.mp3", dvc_hash=None)
    s.create_audio_artifact(script_version_id=sid, tts_config_id=qwen,
                              name="podcast_qwen.mp3", path="b.mp3", dvc_hash=None)
    out = s.list_audio_for_script(sid)
    assert {a.name for a in out} == {"podcast.mp3", "podcast_qwen.mp3"}
