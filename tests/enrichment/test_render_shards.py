"""Tests for shard-based episode rendering (BleakHouse-ec3n).

Replaces the single-mp3 + audio/manifest.json output with per-turn audio
shards, so timing drift between text and audio is structurally impossible.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from pydub import AudioSegment

from enrichment.podcast_types import (
    EpisodeSegment,
    PodcastEpisode,
    SentenceType,
    Turn,
    Utterance,
)
from enrichment.render_audio import (
    render_episode_to_shards,
    silence_ms,
    write_shards,
)
from enrichment.tts_profiles import get_profile


def _mk_utterance(text: str = "Hello world.") -> Utterance:
    return Utterance(
        text=text,
        sentence_type=SentenceType.analysis,
        quote_mode="none",  # type: ignore[arg-type]
        rate=1.0,
        pause_before_ms=0,
        pause_after_ms=300,
        emphasis_words=[],
    )


def _mk_turn(speaker: str, text: str) -> Turn:
    return Turn(
        speaker=speaker,
        role="host" if speaker == "Host" else "guest",
        utterances=[_mk_utterance(text)],
    )


def _mk_episode() -> PodcastEpisode:
    seg1 = EpisodeSegment(
        title="Opening",
        segment_type="opening",
        turns=[
            _mk_turn("Host", "Welcome."),
            _mk_turn("Hartley", "Glad to be here."),
        ],
    )
    seg2 = EpisodeSegment(
        title="Discussion",
        segment_type="thematic",
        turns=[
            _mk_turn("Host", "Let's begin."),
        ],
    )
    return PodcastEpisode(title="Test Episode", segments=[seg1, seg2])


def _short_audio(duration_ms: int = 500) -> AudioSegment:
    return silence_ms(duration_ms)


def test_render_episode_to_shards_returns_one_per_turn_plus_breaks():
    """Each turn produces one shard; each inter-segment gap produces one break shard."""
    episode = _mk_episode()
    profile = get_profile("classic", classic_model_id="gemini-2.5-flash-preview-tts")

    with patch("enrichment.render_audio.render_turn", return_value=_short_audio(500)):
        shards = render_episode_to_shards(
            episode, client=None, profile=profile, concurrency=1  # type: ignore[arg-type]
        )

    # 3 turns + 1 inter-segment break (between seg1 and seg2)
    assert len(shards) == 4
    assert [s.kind for s in shards] == ["turn", "turn", "break", "turn"]
    assert shards[0].speaker == "Host"
    assert shards[0].segment_index == 0 and shards[0].turn_index == 0
    assert shards[1].speaker == "Hartley"
    assert shards[1].segment_index == 0 and shards[1].turn_index == 1
    assert shards[2].speaker is None  # break shard has no speaker
    assert shards[3].speaker == "Host"
    assert shards[3].segment_index == 1 and shards[3].turn_index == 0


def test_render_shards_carry_audio_bytes():
    episode = _mk_episode()
    profile = get_profile("classic", classic_model_id="gemini-2.5-flash-preview-tts")

    with patch("enrichment.render_audio.render_turn", return_value=_short_audio(700)):
        shards = render_episode_to_shards(
            episode, client=None, profile=profile, concurrency=1  # type: ignore[arg-type]
        )

    for s in shards:
        if s.kind == "turn":
            # each turn's mocked render returns 700ms; pauses may extend it
            assert len(s.audio) >= 700
        else:  # break
            assert len(s.audio) > 0


def test_write_shards_produces_files_and_manifest(tmp_path: Path):
    episode = _mk_episode()
    profile = get_profile("classic", classic_model_id="gemini-2.5-flash-preview-tts")

    with patch("enrichment.render_audio.render_turn", return_value=_short_audio(500)):
        shards = render_episode_to_shards(
            episode, client=None, profile=profile, concurrency=1  # type: ignore[arg-type]
        )

    audio_dir = tmp_path / "audio"
    manifest = write_shards(
        shards, episode, audio_dir=audio_dir, profile_name="classic", bitrate="64k"
    )

    # Manifest JSON written
    manifest_path = audio_dir / "shards.json"
    assert manifest_path.exists()
    on_disk = json.loads(manifest_path.read_text())
    assert on_disk == manifest

    # Manifest shape
    assert manifest["schema_version"] == 1
    assert manifest["profile"] == "classic"
    assert manifest["episode_title"] == "Test Episode"
    assert len(manifest["shards"]) == 4

    # Shard files written, named in manifest order
    shard_dir = audio_dir / "shards" / "classic"
    for shard_meta in manifest["shards"]:
        shard_path = shard_dir / shard_meta["file"]
        assert shard_path.exists(), f"missing shard: {shard_path}"
        assert shard_path.stat().st_size > 0

    # No legacy single-mp3 or audio/manifest.json must appear
    assert not (audio_dir / "podcast.mp3").exists()
    assert not (audio_dir / "manifest.json").exists()


def test_write_shards_filenames_are_zero_padded_and_ordered(tmp_path: Path):
    """Filenames sort lexically into manifest order — useful for debug/grep."""
    episode = _mk_episode()
    profile = get_profile("classic", classic_model_id="gemini-2.5-flash-preview-tts")

    with patch("enrichment.render_audio.render_turn", return_value=_short_audio(300)):
        shards = render_episode_to_shards(
            episode, client=None, profile=profile, concurrency=1  # type: ignore[arg-type]
        )

    audio_dir = tmp_path / "audio"
    manifest = write_shards(
        shards, episode, audio_dir=audio_dir, profile_name="classic", bitrate="64k"
    )

    files_in_order = [s["file"] for s in manifest["shards"]]
    assert files_in_order == sorted(files_in_order), \
        "shard filenames should sort lexically into manifest order"


def test_manifest_includes_per_turn_text_and_metadata(tmp_path: Path):
    """shards.json carries the script text per shard so the player can highlight."""
    episode = _mk_episode()
    profile = get_profile("classic", classic_model_id="gemini-2.5-flash-preview-tts")

    with patch("enrichment.render_audio.render_turn", return_value=_short_audio(500)):
        shards = render_episode_to_shards(
            episode, client=None, profile=profile, concurrency=1  # type: ignore[arg-type]
        )

    audio_dir = tmp_path / "audio"
    manifest = write_shards(
        shards, episode, audio_dir=audio_dir, profile_name="classic", bitrate="64k"
    )

    turn_shards = [s for s in manifest["shards"] if s["kind"] == "turn"]
    assert len(turn_shards) == 3

    s0 = turn_shards[0]
    assert s0["speaker"] == "Host"
    assert s0["role"] == "host"
    assert s0["segment_index"] == 0
    assert s0["turn_index"] == 0
    assert len(s0["utterances"]) == 1
    assert s0["utterances"][0]["text"] == "Welcome."

    s2 = turn_shards[2]
    assert s2["speaker"] == "Host"
    assert s2["segment_index"] == 1
    assert s2["turn_index"] == 0


def test_break_shard_has_no_text_metadata(tmp_path: Path):
    episode = _mk_episode()
    profile = get_profile("classic", classic_model_id="gemini-2.5-flash-preview-tts")

    with patch("enrichment.render_audio.render_turn", return_value=_short_audio(500)):
        shards = render_episode_to_shards(
            episode, client=None, profile=profile, concurrency=1  # type: ignore[arg-type]
        )

    audio_dir = tmp_path / "audio"
    manifest = write_shards(
        shards, episode, audio_dir=audio_dir, profile_name="classic", bitrate="64k"
    )

    breaks = [s for s in manifest["shards"] if s["kind"] == "break"]
    assert len(breaks) == 1
    b = breaks[0]
    assert "speaker" not in b or b["speaker"] is None
    assert "utterances" not in b or b["utterances"] is None


def test_each_shard_carries_its_md5(tmp_path: Path):
    """shards.json carries each shard's md5 so the webapp can resolve to R2."""
    import hashlib

    episode = _mk_episode()
    profile = get_profile("classic", classic_model_id="gemini-2.5-flash-preview-tts")

    with patch("enrichment.render_audio.render_turn", return_value=_short_audio(500)):
        shards = render_episode_to_shards(
            episode, client=None, profile=profile, concurrency=1  # type: ignore[arg-type]
        )

    audio_dir = tmp_path / "audio"
    manifest = write_shards(
        shards, episode, audio_dir=audio_dir, profile_name="classic", bitrate="64k"
    )

    shard_dir = audio_dir / "shards" / "classic"
    for shard_meta in manifest["shards"]:
        on_disk = (shard_dir / shard_meta["file"]).read_bytes()
        expected_md5 = hashlib.md5(on_disk).hexdigest()
        assert shard_meta["md5"] == expected_md5, \
            f"shards.json md5 must match the actual mp3 bytes for {shard_meta['file']}"


def test_no_timings_in_manifest(tmp_path: Path):
    """The whole point: NO start_ms/end_ms anywhere. Drift is impossible."""
    episode = _mk_episode()
    profile = get_profile("classic", classic_model_id="gemini-2.5-flash-preview-tts")

    with patch("enrichment.render_audio.render_turn", return_value=_short_audio(500)):
        shards = render_episode_to_shards(
            episode, client=None, profile=profile, concurrency=1  # type: ignore[arg-type]
        )

    audio_dir = tmp_path / "audio"
    manifest = write_shards(
        shards, episode, audio_dir=audio_dir, profile_name="classic", bitrate="64k"
    )

    manifest_text = json.dumps(manifest)
    forbidden = ["start_ms", "end_ms", "total_duration_ms", "duration_ms"]
    for key in forbidden:
        assert key not in manifest_text, f"shards manifest must not contain {key!r}"


def test_experts_collected_from_episode(tmp_path: Path):
    episode = _mk_episode()
    profile = get_profile("classic", classic_model_id="gemini-2.5-flash-preview-tts")

    with patch("enrichment.render_audio.render_turn", return_value=_short_audio(500)):
        shards = render_episode_to_shards(
            episode, client=None, profile=profile, concurrency=1  # type: ignore[arg-type]
        )

    audio_dir = tmp_path / "audio"
    manifest = write_shards(
        shards, episode, audio_dir=audio_dir, profile_name="classic", bitrate="64k"
    )

    expert_names = {e["name"] for e in manifest["experts"]}
    assert "Hartley" in expert_names
    assert "Host" not in expert_names  # Host excluded from experts list


def test_write_shards_puts_bytes_into_cas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """write_shards copies each shard's bytes into the local CAS via cas.put.

    After the call, every shards.json md5 must resolve to a real blob at
    <CAS_ROOT>/files/md5/<prefix>/<rest> with matching bytes.
    """
    cas_root = tmp_path / "cas"
    cas_root.mkdir()
    monkeypatch.setenv("BLEAKHOUSE_CAS_ROOT", str(cas_root))

    episode = _mk_episode()
    profile = get_profile("classic", classic_model_id="gemini-2.5-flash-preview-tts")

    with patch("enrichment.render_audio.render_turn", return_value=_short_audio(500)):
        shards = render_episode_to_shards(
            episode, client=None, profile=profile, concurrency=1  # type: ignore[arg-type]
        )

    audio_dir = tmp_path / "audio"
    manifest = write_shards(
        shards, episode, audio_dir=audio_dir, profile_name="classic", bitrate="64k"
    )

    shard_dir = audio_dir / "shards" / "classic"
    for shard_meta in manifest["shards"]:
        md5 = shard_meta["md5"]
        cas_blob = cas_root / "files" / "md5" / md5[:2] / md5[2:]
        assert cas_blob.is_file(), f"no CAS blob for {shard_meta['file']} (md5={md5})"
        assert cas_blob.read_bytes() == (shard_dir / shard_meta["file"]).read_bytes()


@pytest.mark.parametrize("profile_name", ["classic"])
def test_writes_under_profile_subdir(tmp_path: Path, profile_name: str):
    """Different profiles get separate shard dirs so renders don't collide."""
    episode = _mk_episode()
    profile = get_profile(profile_name, classic_model_id="gemini-2.5-flash-preview-tts")

    with patch("enrichment.render_audio.render_turn", return_value=_short_audio(500)):
        shards = render_episode_to_shards(
            episode, client=None, profile=profile, concurrency=1  # type: ignore[arg-type]
        )

    audio_dir = tmp_path / "audio"
    write_shards(shards, episode, audio_dir=audio_dir,
                 profile_name=profile_name, bitrate="64k")

    assert (audio_dir / "shards" / profile_name).is_dir()
