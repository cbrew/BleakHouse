"""End-to-end CLI test: monkeypatch align_transcript so we don't run
WhisperX in CI, then run the CLI on the synthetic 3-turn fixture +
a synthetic phase3_episode.json."""
import json
import shutil
import sys
from pathlib import Path

import pytest


FIXTURE_MP3 = Path(__file__).parent / "fixtures" / "synthetic_3turn.mp3"


def _make_synthetic_run(root: Path, mp3_src: Path) -> Path:
    """Build a fake data/runs/<run>/ matching what the CLI expects."""
    run_dir = root / "data" / "runs" / "synth_test"
    audio_dir = run_dir / "audio"
    audio_dir.mkdir(parents=True)
    shutil.copy(mp3_src, audio_dir / "podcast.mp3")
    episode = {
        "title": "Synthetic Test",
        "experts": [{"name": "Speaker A", "role": "expert"}],
        "segments": [
            {"title": "Only", "segment_type": "opening", "turns": [
                {"speaker": "Host", "role": "host",
                 "utterances": [{"text": "alpha",
                                 "sentence_type": "default",
                                 "is_quote": False, "quote_mode": None,
                                 "passage_ref": None}]},
                {"speaker": "Speaker A", "role": "expert",
                 "utterances": [{"text": "bravo",
                                 "sentence_type": "default",
                                 "is_quote": False, "quote_mode": None,
                                 "passage_ref": None}]},
                {"speaker": "Host", "role": "host",
                 "utterances": [{"text": "charlie",
                                 "sentence_type": "default",
                                 "is_quote": False, "quote_mode": None,
                                 "passage_ref": None}]},
            ]},
        ],
    }
    (run_dir / "phase3_episode.json").write_text(json.dumps(episode))
    return run_dir


def test_cli_run_synth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    run_dir = _make_synthetic_run(tmp_path, FIXTURE_MP3)
    from forced_align.boundaries import AlignedWord
    fake_alignments = [
        AlignedWord(word="alpha", start_s=0.5, end_s=2.0, script_index=0),
        AlignedWord(word="bravo", start_s=2.5, end_s=4.0, script_index=1),
        AlignedWord(word="charlie", start_s=4.5, end_s=6.0, script_index=2),
    ]
    # Patch where align_transcript is *imported by* __main__, not where defined.
    import forced_align.__main__ as main_mod
    monkeypatch.setattr(main_mod, "align_transcript",
                        lambda audio_path, words, **kw: fake_alignments)

    monkeypatch.setattr(sys, "argv", [
        "forced_align", "--data-dir", str(tmp_path / "data"),
        "--run", "synth_test",
    ])
    rc = main_mod.main()
    assert rc == 0

    audio_dir = run_dir / "audio"
    assert (audio_dir / "shards.json").exists()
    assert (audio_dir / "manifest.json").exists()
    shards = json.loads((audio_dir / "shards.json").read_text())
    assert len(shards["shards"]) == 3
    shard_files = sorted((audio_dir / "shards" / "classic").glob("*.mp3"))
    assert [f.name for f in shard_files] == ["0000.mp3", "0001.mp3", "0002.mp3"]
