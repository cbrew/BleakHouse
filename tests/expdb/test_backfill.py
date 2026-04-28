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
