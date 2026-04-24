"""Render a structured podcast episode to audio via a selectable TTS profile.

Reads podcast_episode.json, renders each turn through the chosen profile's
prompt builder and voice, inserts silence scaled by the profile, and
concatenates into a single MP3 file.

Usage:
    uv run python -m enrichment.render_audio [--profile classic] [--model flash] [--output podcast.mp3]
    uv run python -m enrichment.render_audio --profile trevelyan_v2 --run ext_v19_all_swapped_hostprep
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import time
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydub import AudioSegment

from enrichment.podcast_types import (  # pyright: ignore[reportMissingImports]
    PodcastEpisode,
    Turn,
)
from enrichment.tts_profiles import (
    EpisodeContext,
    TTSProfile,
    get_profile,
    profile_names,
)

load_dotenv()

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "tts_cache"

CLASSIC_MODEL_IDS = {
    "flash": "gemini-2.5-flash-preview-tts",
    "pro": "gemini-2.5-pro-preview-tts",
}


def pcm_to_segment(pcm_data: bytes, sample_rate: int = 24000) -> AudioSegment:
    """Convert raw PCM bytes (16-bit mono) to a pydub AudioSegment."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    buf.seek(0)
    return AudioSegment.from_wav(buf)


def silence_ms(duration_ms: int) -> AudioSegment:
    """Create a silent AudioSegment of the given duration."""
    return AudioSegment.silent(duration=max(0, duration_ms))


def _cache_key(text: str, voice: str, model: str) -> str:
    """Generate a stable cache key for a TTS call."""
    return hashlib.sha256(f"{model}:{voice}:{text}".encode()).hexdigest()[:16]


def _cache_path(profile: TTSProfile, key: str) -> Path:
    return CACHE_DIR / profile.cache_namespace / f"{key}.wav"


def _load_cached(profile: TTSProfile, key: str) -> AudioSegment | None:
    path = _cache_path(profile, key)
    if path.exists():
        return AudioSegment.from_wav(str(path))
    return None


def _save_cache(profile: TTSProfile, key: str, audio: AudioSegment) -> None:
    path = _cache_path(profile, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    audio.export(str(path), format="wav")


def apply_turn_pauses(audio: AudioSegment, turn: Turn, pause_scale: float) -> AudioSegment:
    """Add leading + trailing silence around the rendered turn, scaled by the profile."""
    result = AudioSegment.empty()
    first = turn.utterances[0] if turn.utterances else None
    if first and first.pause_before_ms > 0:
        result += silence_ms(int(first.pause_before_ms * pause_scale))
    result += audio
    last = turn.utterances[-1] if turn.utterances else None
    if last and last.pause_after_ms > 300:
        extra = int((last.pause_after_ms - 300) * pause_scale)
        result += silence_ms(extra)
    return result


def render_turn(
    turn: Turn,
    ctx: EpisodeContext,
    client: genai.Client,
    profile: TTSProfile,
) -> AudioSegment:
    """Render a single turn to audio, with pause insertion."""
    speaker = turn.speaker
    voice_name = profile.voice_name(speaker)
    prompt = profile.build_turn_prompt(turn, ctx)

    cache_key = _cache_key(prompt, voice_name, profile.model_id)
    cached = _load_cached(profile, cache_key)
    if cached is not None:
        logger.info("  Cache hit for %s turn (%d chars)", speaker, len(prompt))
        return apply_turn_pauses(cached, turn, profile.pause_scale)

    logger.info(
        "  Rendering %s turn (%d utterances, %d chars, profile=%s)",
        speaker,
        len(turn.utterances),
        len(prompt),
        profile.name,
    )

    audio: AudioSegment | None = None
    for attempt in range(4):
        try:
            response = client.models.generate_content(
                model=profile.model_id,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=voice_name,
                            )
                        )
                    ),
                ),
            )
        except Exception as exc:
            logger.warning("TTS attempt %d failed for %s: %s", attempt + 1, speaker, exc)
            if attempt < 3:
                time.sleep(2 ** attempt)
                continue
            return silence_ms(500)

        candidate = response.candidates[0] if response.candidates else None
        if candidate is None or candidate.content is None:
            logger.warning("No audio returned for %s turn (attempt %d)", speaker, attempt + 1)
            if attempt < 3:
                time.sleep(2 ** attempt)
                continue
            return silence_ms(500)
        part = candidate.content.parts[0] if candidate.content.parts else None
        if part is None or part.inline_data is None or part.inline_data.data is None:
            logger.warning("No audio data for %s turn (attempt %d)", speaker, attempt + 1)
            if attempt < 3:
                time.sleep(2 ** attempt)
                continue
            return silence_ms(500)
        audio = pcm_to_segment(part.inline_data.data)
        break

    if audio is None:
        return silence_ms(500)

    _save_cache(profile, cache_key, audio)
    return apply_turn_pauses(audio, turn, profile.pause_scale)


def render_episode(
    episode: PodcastEpisode,
    client: genai.Client,
    profile: TTSProfile,
    concurrency: int = 1,
) -> AudioSegment:
    """Render all segments and turns into a single audio track.

    When concurrency > 1, turns within each segment are rendered in
    parallel via a thread pool, then assembled in order.
    """
    full_audio = AudioSegment.empty()
    inter_segment_ms = int(2000 * profile.pause_scale)

    for seg_idx, seg in enumerate(episode.segments):
        logger.info(
            "Segment %d/%d: '%s' (%d turns, concurrency=%d, profile=%s)",
            seg_idx + 1,
            len(episode.segments),
            seg.title,
            len(seg.turns),
            concurrency,
            profile.name,
        )

        def _ctx(turn_idx: int) -> EpisodeContext:
            return EpisodeContext(
                episode_title=episode.title,
                segment_title=seg.title,
                segment_index=seg_idx,
                turn_index=turn_idx,
                previous_turn=seg.turns[turn_idx - 1] if turn_idx > 0 else None,
            )

        if concurrency <= 1:
            for turn_idx, turn in enumerate(seg.turns):
                turn_audio = render_turn(turn, _ctx(turn_idx), client, profile)
                full_audio += turn_audio
                logger.info(
                    "    Turn %d/%d [%s]: %.1fs",
                    turn_idx + 1,
                    len(seg.turns),
                    turn.speaker,
                    len(turn_audio) / 1000,
                )
        else:
            turn_audios: list[AudioSegment | None] = [None] * len(seg.turns)

            def _render_one(idx: int, turn: Turn) -> tuple[int, AudioSegment]:
                audio = render_turn(turn, _ctx(idx), client, profile)
                return idx, audio

            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = {
                    pool.submit(_render_one, i, turn): i
                    for i, turn in enumerate(seg.turns)
                }
                for future in as_completed(futures):
                    idx, audio = future.result()
                    turn_audios[idx] = audio
                    logger.info(
                        "    Turn %d/%d [%s]: %.1fs",
                        idx + 1,
                        len(seg.turns),
                        seg.turns[idx].speaker,
                        len(audio) / 1000,
                    )

            for audio in turn_audios:
                assert audio is not None
                full_audio += audio

        if seg_idx < len(episode.segments) - 1:
            full_audio += silence_ms(inter_segment_ms)

    return full_audio


def main() -> None:
    parser = argparse.ArgumentParser(description="Render podcast episode to audio")
    parser.add_argument(
        "--profile",
        choices=profile_names(),
        default="classic",
        help="TTS profile to use (default: classic)",
    )
    parser.add_argument(
        "--model",
        choices=["flash", "pro"],
        default="flash",
        help="Gemini TTS model tier for the classic profile (ignored for other profiles)",
    )
    parser.add_argument(
        "--output",
        default="podcast.mp3",
        help="Output filename (default: podcast.mp3; profile name is appended for non-classic)",
    )
    parser.add_argument(
        "--run",
        default=None,
        help="Load episode from a named run (data/runs/{name}/phase3_episode.json)",
    )
    parser.add_argument(
        "--episode",
        default=None,
        help="Path to podcast_episode.json (default: data/podcast_episode.json)",
    )
    parser.add_argument(
        "--segment",
        type=int,
        default=None,
        help="Render only this segment index (0-based), for testing",
    )
    parser.add_argument(
        "--bitrate",
        default="192k",
        help="MP3 bitrate (default: 192k)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Number of concurrent TTS API calls per segment (default: 4)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    if args.run:
        episode_path = DATA_DIR / "runs" / args.run / "phase3_episode.json"
    elif args.episode:
        episode_path = Path(args.episode)
    else:
        episode_path = DATA_DIR / "podcast_episode.json"

    with open(episode_path) as f:
        episode = PodcastEpisode.model_validate(json.load(f))

    logger.info(
        "Loaded episode: %d segments, %d total turns",
        len(episode.segments),
        sum(len(s.turns) for s in episode.segments),
    )

    if args.segment is not None:
        seg = episode.segments[args.segment]
        episode = PodcastEpisode(
            title=episode.title,
            segments=[seg],
            metadata=episode.metadata,
        )
        logger.info("Rendering only segment %d: '%s'", args.segment, seg.title)

    classic_model_id = CLASSIC_MODEL_IDS[args.model] if args.profile == "classic" else None
    profile = get_profile(args.profile, classic_model_id=classic_model_id)
    logger.info("Using profile: %s (model=%s)", profile.name, profile.model_id)

    client = genai.Client()

    audio = render_episode(episode, client, profile, concurrency=args.concurrency)

    profile_suffix = f"_{profile.name}" if profile.name != "classic" else ""
    if args.run and args.output == "podcast.mp3":
        # Audio lands at the DVC-tracked path so `dvc status` can see it
        # and the DVC cache (pointed at the external volume by config)
        # manages the actual blob. No PODCAST_AUDIO_DIR redirection.
        audio_dir = DATA_DIR / "runs" / args.run / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        seg_suffix = f"_segment_{args.segment}" if args.segment is not None else ""
        output_path = audio_dir / f"podcast{profile_suffix}{seg_suffix}.mp3"
    else:
        stem = Path(args.output).stem
        ext = Path(args.output).suffix or ".mp3"
        output_path = BASE_DIR / f"{stem}{profile_suffix}{ext}"
    logger.info(
        "Exporting %.1f minutes of audio to %s",
        len(audio) / 60000,
        output_path,
    )
    audio.export(str(output_path), format="mp3", bitrate=args.bitrate)
    logger.info("Done: %s (%.1f MB)", output_path, output_path.stat().st_size / 1e6)


if __name__ == "__main__":
    main()
