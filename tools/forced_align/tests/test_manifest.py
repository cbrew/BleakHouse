"""Tests for manifest.py — emit shards.json (matches rwv schema) and
audio/manifest.json (audio-measured per-turn timing)."""
import hashlib
import json
from pathlib import Path

from forced_align.boundaries import ShardBoundary
from forced_align.manifest import write_manifests


def _make_shard_files(audio_dir: Path, count: int) -> list[Path]:
    """Stand-in for real mp3 files: known bytes for stable md5 in tests."""
    out = []
    for i in range(count):
        p = audio_dir / "shards" / "classic" / f"{i:04d}.mp3"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(f"shard-{i}".encode())
        out.append(p)
    return out


def test_writes_both_manifests(tmp_path: Path):
    audio_dir = tmp_path
    _make_shard_files(audio_dir, 2)
    episode = {
        "title": "Bleak House Unpacked",
        "experts": [{"name": "Eleanor Hartley", "role": "expert"}],
        "segments": [
            {"title": "Opening", "segment_type": "opening", "turns": [
                {"speaker": "Host", "role": "host",
                 "utterances": [{"text": "Welcome.",
                                 "sentence_type": "intro",
                                 "is_quote": False,
                                 "quote_mode": None,
                                 "passage_ref": None}]},
                {"speaker": "Eleanor Hartley", "role": "expert",
                 "utterances": [{"text": "Hello.",
                                 "sentence_type": "default",
                                 "is_quote": False,
                                 "quote_mode": None,
                                 "passage_ref": None}]},
            ]},
        ],
    }
    boundaries = [
        ShardBoundary(0, 0, 0.0, 2.5),
        ShardBoundary(0, 1, 2.5, 5.0),
    ]
    write_manifests(audio_dir=audio_dir, episode=episode,
                    boundaries=boundaries, profile="classic")

    shards = json.loads((audio_dir / "shards.json").read_text())
    assert shards["schema_version"] == 1
    assert shards["profile"] == "classic"
    assert shards["episode_title"] == "Bleak House Unpacked"
    assert shards["experts"] == [{"name": "Eleanor Hartley", "role": "expert"}]
    assert len(shards["shards"]) == 2
    assert shards["shards"][0]["file"] == "0000.mp3"
    assert shards["shards"][0]["kind"] == "turn"
    assert shards["shards"][0]["segment_index"] == 0
    assert shards["shards"][0]["turn_index"] == 0
    assert shards["shards"][0]["speaker"] == "Host"
    assert shards["shards"][0]["role"] == "host"
    assert shards["shards"][0]["utterances"] == [{
        "text": "Welcome.", "sentence_type": "intro",
        "is_quote": False, "quote_mode": None, "passage_ref": None,
    }]
    expected_md5 = hashlib.md5(b"shard-0").hexdigest()
    assert shards["shards"][0]["md5"] == expected_md5

    audio_manifest = json.loads((audio_dir / "manifest.json").read_text())
    assert audio_manifest["title"] == "Bleak House Unpacked"
    assert audio_manifest["total_duration_ms"] == 5000
    assert len(audio_manifest["segments"]) == 1
    seg0 = audio_manifest["segments"][0]
    assert seg0["start_ms"] == 0
    assert seg0["turns"][0]["start_ms"] == 0
    assert seg0["turns"][0]["end_ms"] == 2500
    assert seg0["turns"][1]["start_ms"] == 2500
    assert seg0["turns"][1]["end_ms"] == 5000
