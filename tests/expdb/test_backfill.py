from __future__ import annotations

import json
from pathlib import Path

from enrichment.expdb.backfill import scan_run_dir
from enrichment.expdb.store import Store


def _make_run_dir(tmp: Path) -> Path:
    rd = tmp / "bh_trn_literary"
    (rd / "audio").mkdir(parents=True)
    (rd / "run_manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "run_id": "bh_trn_literary",
        "axes": {"novel": "bh", "pipeline": "trn", "panel": "literary",
                  "hostprep": False, "generator": "anthropic_sonnet_4_6"},
        "stages": {
            "phase3": {"hash": "abc"},
            "quote_verification": {"verified": 42, "total": 42, "rate": 100.0},
            "phase4_audio": {
                "engine": "gemini-2.0-flash-preview-tts",
                "hash": "ea0b3082baa072eed50612e8fcd68fd8",
                "audio_file": "data/runs/bh_trn_literary/audio/podcast.mp3",
                "audio_manifest": "data/runs/bh_trn_literary/audio/manifest.json",
            },
        },
        "audio_variants": [{
            "name": "classic",
            "engine": "gemini-2.0-flash-preview-tts",
            "stage": "phase4_audio",
            "hash": "ea0b3082baa072eed50612e8fcd68fd8",
            "audio_file": "data/runs/bh_trn_literary/audio/podcast.mp3",
            "audio_manifest": "data/runs/bh_trn_literary/audio/manifest.json",
        }],
        "generated_at": "2026-04-25T10:00:00Z",
        "dvc_lock_sha": "deadbeef",
    }))
    (rd / "phase3_episode.json").write_text(json.dumps({
        "title": "BH literary",
        "segments": [
            {"turns": [
                {"speaker": "Host", "utterances": [{"text": "hi"}, {"text": "yes"}]},
                {"speaker": "James Blackstone", "utterances": [{"text": "indeed"}]},
            ]},
        ],
    }))
    return rd


def test_scan_creates_episode_script_run_audio_eval(tmp_path: Path, tmp_db_path: Path) -> None:
    rd = _make_run_dir(tmp_path)
    s = Store(tmp_db_path)
    s.init_schema()

    out = scan_run_dir(s, rd)

    assert out["episode_id"] is not None
    assert out["script_version_id"] is not None
    assert out["generation_run_id"] is not None
    assert len(out["audio_artifact_ids"]) == 1
    assert out["evaluation_ids"]  # quote_verification recorded

    sv = s.get_script_version(out["script_version_id"])
    assert sv is not None
    assert sv.n_segments == 1
    assert sv.n_turns == 2
    assert sv.n_utterances == 3


def test_scan_is_idempotent(tmp_path: Path, tmp_db_path: Path) -> None:
    rd = _make_run_dir(tmp_path)
    s = Store(tmp_db_path)
    s.init_schema()
    a = scan_run_dir(s, rd)
    b = scan_run_dir(s, rd)
    # The same row IDs are reused for episode/script/run/audio.
    assert a["episode_id"] == b["episode_id"]
    assert a["script_version_id"] == b["script_version_id"]
    assert a["generation_run_id"] == b["generation_run_id"]
    assert a["audio_artifact_ids"] == b["audio_artifact_ids"]
    # Evaluations are recorded once, then suppressed on re-scan.
    assert len(s.list_evaluations_for_script(a["script_version_id"])) == 1
    # No duplicate episodes / scripts / audio.
    assert len(s.list_episodes(novel="bh")) == 1
    assert len(s.list_scripts_for_episode(a["episode_id"])) == 1
    assert len(s.list_audio_for_script(a["script_version_id"])) == 1


def _make_hostprep_run_dir(tmp: Path) -> Path:
    """A hostprep run with phase2_5_interviews/host_briefs/reading_list."""
    rd = tmp / "bh_trn_alternatives_hostprep"
    (rd / "audio").mkdir(parents=True)
    (rd / "run_manifest.json").write_text(json.dumps({
        "schema_version": 1, "run_id": "bh_trn_alternatives_hostprep",
        "axes": {"novel": "bh", "pipeline": "trn", "panel": "alternatives",
                  "hostprep": True, "generator": "anthropic_sonnet_4_6"},
        "stages": {}, "audio_variants": [],
        "generated_at": "2026-04-25T10:00:00Z", "dvc_lock_sha": "x",
    }))
    (rd / "phase3_episode.json").write_text(json.dumps({
        "segments": [{"turns": [
            {"speaker": "Host", "utterances": [{"text": "hi"}]},
        ]}],
    }))
    # 2 segments × 3 experts = 6 interviews
    (rd / "phase2_5_interviews.json").write_text(json.dumps([
        [{"expert_name": "Edmund", "key_points": []},
         {"expert_name": "Daniel", "key_points": []},
         {"expert_name": "Trevelyan", "key_points": []}],
        [{"expert_name": "Edmund", "key_points": []},
         {"expert_name": "Daniel", "key_points": []},
         {"expert_name": "Trevelyan", "key_points": []}],
    ]))
    # 2 segments, 5 questions total
    (rd / "phase2_5_host_briefs.json").write_text(json.dumps([
        {"segment_name": "S1", "questions": [{"q": "a"}, {"q": "b"}, {"q": "c"}]},
        {"segment_name": "S2", "questions": [{"q": "d"}, {"q": "e"}]},
    ]))
    (rd / "phase2_5_reading_list.json").write_text(json.dumps({
        "verification_rate": 0.78,
        "total_proposed": 28,
        "total_verified": 22,
    }))
    return rd


def test_scan_creates_hostprep_when_present(tmp_path: Path, tmp_db_path: Path) -> None:
    rd = _make_hostprep_run_dir(tmp_path)
    s = Store(tmp_db_path)
    s.init_schema()

    out = scan_run_dir(s, rd)

    # Hostprep was created and is linked from the script.
    sv = s.get_script_version(out["script_version_id"])
    assert sv is not None
    assert sv.hostprep_version_id is not None

    hp = s.get_hostprep_version(sv.hostprep_version_id)
    assert hp is not None
    assert hp.n_segments == 2
    assert hp.n_interviews == 6
    assert hp.n_questions == 5

    # Reading-list verification was recorded as an evaluation against the hostprep.
    evals = s.list_evaluations_for_hostprep(hp.id)
    assert len(evals) == 1
    assert evals[0].metric_kind == "reading_list_verification"
    assert evals[0].metric["verification_rate"] == 0.78


def test_scan_hostprep_run_is_idempotent(tmp_path: Path, tmp_db_path: Path) -> None:
    rd = _make_hostprep_run_dir(tmp_path)
    s = Store(tmp_db_path)
    s.init_schema()
    a = scan_run_dir(s, rd)
    scan_run_dir(s, rd)  # second pass

    sv = s.get_script_version(a["script_version_id"])
    assert sv is not None and sv.hostprep_version_id is not None

    # No duplicate hostprep / reading-list evaluation.
    eps = s.list_episodes()
    assert len(eps) == 1
    assert len(s.list_hostprep_for_episode(eps[0].id)) == 1
    assert len(s.list_evaluations_for_hostprep(sv.hostprep_version_id)) == 1


def _make_shards_run_dir(tmp: Path) -> Path:
    """A shards-mode run: empty audio_variants, but audio/shards.json on disk."""
    rd = tmp / "wh_trn_literary_short"
    (rd / "audio").mkdir(parents=True)
    (rd / "run_manifest.json").write_text(json.dumps({
        "schema_version": 1, "run_id": "wh_trn_literary_short",
        "axes": {"novel": "wuthering_heights", "pipeline": "transport",
                  "panel": "literary", "hostprep": True,
                  "generator": "anthropic_sonnet_4_6", "length": "short"},
        "stages": {}, "audio_variants": [],
        "generated_at": "2026-05-09T01:36:55Z", "dvc_lock_sha": "x",
    }))
    (rd / "phase3_episode.json").write_text(json.dumps({
        "segments": [{"turns": [
            {"speaker": "Host", "utterances": [{"text": "hi"}]},
        ]}],
    }))
    (rd / "audio" / "shards.json").write_text(json.dumps({
        "schema_version": 1, "profile": "trevelyan_v2",
        "episode_title": "Wuthering Heights",
        "experts": [{"name": "Eleanor Hartley", "role": "novelist"}],
        "shards": [
            {"file": "0000.mp3", "md5": "deadbeef", "kind": "turn",
             "segment_index": 0, "turn_index": 0,
             "speaker": "Host", "role": "host", "utterances": []},
        ],
    }))
    return rd


def test_scan_shards_mode_creates_audio_artifact(tmp_path: Path, tmp_db_path: Path) -> None:
    """A run with audio/shards.json but empty audio_variants must still
    produce an audio_artifact row, otherwise the consumer JOIN drops it."""
    rd = _make_shards_run_dir(tmp_path)
    s = Store(tmp_db_path)
    s.init_schema()

    out = scan_run_dir(s, rd)
    assert len(out["audio_artifact_ids"]) == 1

    audio = s.list_audio_for_script(out["script_version_id"])
    assert len(audio) == 1
    assert audio[0].name == "shards_trevelyan_v2.json"
    assert audio[0].path.endswith("audio/shards.json")


def test_scan_shards_mode_is_idempotent(tmp_path: Path, tmp_db_path: Path) -> None:
    rd = _make_shards_run_dir(tmp_path)
    s = Store(tmp_db_path)
    s.init_schema()
    a = scan_run_dir(s, rd)
    b = scan_run_dir(s, rd)
    assert a["audio_artifact_ids"] == b["audio_artifact_ids"]
    assert len(s.list_audio_for_script(a["script_version_id"])) == 1


def test_scan_shards_mode_with_total_duration(tmp_path: Path, tmp_db_path: Path) -> None:
    """If shards.json carries total_duration_ms, surface it as duration_s."""
    rd = _make_shards_run_dir(tmp_path)
    shards_path = rd / "audio" / "shards.json"
    shards = json.loads(shards_path.read_text())
    shards["total_duration_ms"] = 5_169_120
    shards_path.write_text(json.dumps(shards))

    s = Store(tmp_db_path)
    s.init_schema()
    out = scan_run_dir(s, rd)
    audio = s.list_audio_for_script(out["script_version_id"])
    assert audio[0].duration_s == 5169.12


def test_scan_legacy_mp3_without_audio_variants(tmp_path: Path, tmp_db_path: Path) -> None:
    """audio/podcast.mp3 + audio/manifest.json on disk but empty
    audio_variants — fall back to disk discovery."""
    rd = tmp_path / "legacy_run"
    (rd / "audio").mkdir(parents=True)
    (rd / "run_manifest.json").write_text(json.dumps({
        "schema_version": 1, "run_id": "legacy_run",
        "axes": {"novel": "bh", "pipeline": "trn", "panel": "literary",
                  "hostprep": False, "generator": "anthropic_sonnet_4_6"},
        "stages": {}, "audio_variants": [],
        "generated_at": "2026-04-25T10:00:00Z", "dvc_lock_sha": "x",
    }))
    (rd / "phase3_episode.json").write_text(json.dumps({
        "segments": [{"turns": [
            {"speaker": "Host", "utterances": [{"text": "hi"}]},
        ]}],
    }))
    (rd / "audio" / "podcast.mp3").write_bytes(b"fake mp3 bytes")
    (rd / "audio" / "manifest.json").write_text(json.dumps({
        "title": "Legacy", "experts": [], "segments": [],
        "total_duration_ms": 1_234_000,
    }))

    s = Store(tmp_db_path)
    s.init_schema()
    out = scan_run_dir(s, rd)
    audio = s.list_audio_for_script(out["script_version_id"])
    assert len(audio) == 1
    assert audio[0].name == "podcast.mp3"
