"""Render a structured podcast episode to audio via Gemini TTS.

Reads podcast_episode.json, renders each turn with appropriate voice and
delivery annotations, inserts silence for pauses, and concatenates into
a single MP3 file.

Usage:
    uv run python -m enrichment.render_audio [--model flash] [--output podcast.mp3]
    uv run python -m enrichment.render_audio --model pro --output podcast_pro.mp3
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
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
    VoicePolicy,
)

load_dotenv()

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "tts_cache"

# Authoritative location for rendered podcast audio.
PODCAST_AUDIO_DIR = Path(
    os.environ.get("PODCAST_AUDIO_DIR", "/Volumes/Crucial X9/bleakhouse_audio")
)

# NOTE (2026-04-17): The SPEAKER_VOICES/ACCENTS/POLICIES dicts and the
# build_turn_prompt / _rate_direction / _quote_direction / _emphasis_direction
# helpers below are duplicated in enrichment/tts_profiles/classic.py as
# ClassicProfile. They are removed from this file in the Task 3 refactor.
# Until then, any edit here MUST be mirrored in classic.py (or vice versa).
# ---------------------------------------------------------------------------
# Voice configuration
# ---------------------------------------------------------------------------

MODEL_IDS = {
    "flash": "gemini-2.5-flash-preview-tts",
    "pro": "gemini-2.5-pro-preview-tts",
}

# Voice assignments — chosen for tonal contrast in a literary roundtable.
# British accent is directed via prompt, not voice selection.
SPEAKER_VOICES: dict[str, str] = {
    "Host": "Sulafat",               # Warm female — suited for a presenter
    "Eleanor Hartley": "Zephyr",     # Bright female — suits intellectual excitement
    "James Blackstone": "Sadaltager",  # Knowledgeable male — suits measured authority
    "Caroline Woodcourt": "Achernar",  # Soft female — suits reflective intimacy
    "Narrator": "Schedar",           # Even male — neutral narration
    # Alternative experts (all male)
    "Edmund Leigh": "Algenib",       # Gravelly male — suits patrician gravitas
    "Daniel Rosen": "Alnilam",       # Firm male — suits passionate precision
    "Oliver Trevelyan": "Achird",    # Friendly male — suits warm raconteur
    # American interdisciplinary panel
    "Sarah Chen": "Zephyr",          # Bright female — suits precise clarity
    "Rebecca Martinez": "Achernar",  # Soft female — suits contemplative warmth
    "Elena Volkov": "Aoede",         # Firm female — suits engaged analysis
}

# Accent directions per speaker, embedded in the prompt
SPEAKER_ACCENTS: dict[str, str] = {
    "Host": "speaks with a warm Home Counties accent, like a BBC Radio 4 presenter",
    "Eleanor Hartley": "speaks with a lively Cambridge accent, articulate and precise",
    "James Blackstone": "speaks with a measured Edinburgh accent, dry and authoritative",
    "Caroline Woodcourt": "speaks with a gentle Bristol accent, warm and intimate",
    "Narrator": "speaks with a clear, neutral British accent",
    # Alternative experts
    "Edmund Leigh": "speaks with a patrician Oxford accent, unhurried and precise",
    "Daniel Rosen": "speaks with a clear London accent, purposeful and direct",
    "Oliver Trevelyan": "speaks with a warm, theatrical Home Counties accent, varied and lively",
    # American interdisciplinary panel
    "Sarah Chen": "speaks with a clear California accent, precise and direct, like a tech professional giving a talk",
    "Rebecca Martinez": "speaks with a soft American Southwest accent, unhurried and thoughtful, with occasional pauses for emphasis",
    "Elena Volkov": "speaks with a crisp American East Coast accent, the cadence of someone trained at Juilliard and Columbia, intellectually sharp",
}

SPEAKER_VOICE_POLICIES: dict[str, VoicePolicy] = {
    "Host": VoicePolicy(rate=0.98, energy="medium", pause_bias_ms=220, style="presenter_warm"),
    "Eleanor Hartley": VoicePolicy(rate=1.01, energy="medium_high", pause_bias_ms=170, style="analytic_bright"),
    "James Blackstone": VoicePolicy(rate=0.96, energy="medium_low", pause_bias_ms=260, style="measured_dry"),
    "Caroline Woodcourt": VoicePolicy(rate=0.97, energy="medium", pause_bias_ms=240, style="reflective_intimate"),
    "Narrator": VoicePolicy(rate=1.0, energy="medium", pause_bias_ms=200, style="neutral"),
    # Alternative experts
    "Edmund Leigh": VoicePolicy(rate=0.94, energy="medium_low", pause_bias_ms=280, style="patrician_measured"),
    "Daniel Rosen": VoicePolicy(rate=0.99, energy="medium_high", pause_bias_ms=200, style="passionate_precise"),
    "Oliver Trevelyan": VoicePolicy(rate=1.02, energy="medium_high", pause_bias_ms=190, style="raconteur_warm"),
    # American interdisciplinary panel
    "Sarah Chen": VoicePolicy(rate=1.01, energy="medium_high", pause_bias_ms=180, style="analytical_clear"),
    "Rebecca Martinez": VoicePolicy(rate=0.96, energy="medium", pause_bias_ms=250, style="contemplative_measured"),
    "Elena Volkov": VoicePolicy(rate=0.98, energy="medium", pause_bias_ms=210, style="engaged_analytical"),
}


# ---------------------------------------------------------------------------
# Delivery annotation → natural language stage directions
# ---------------------------------------------------------------------------


def _rate_direction(rate: float, speaker_base: float) -> str:
    """Convert rate multiplier to a natural language pace direction."""
    effective = rate * speaker_base
    if effective < 0.93:
        return "Speak slowly and deliberately."
    if effective < 0.96:
        return "Speak at a measured, unhurried pace."
    if effective > 1.04:
        return "Speak with brisk energy."
    if effective > 1.01:
        return "Speak with a slightly quicker pace."
    return ""


def _quote_direction(quote_mode: str) -> str:
    """Convert quote_mode to delivery direction."""
    if quote_mode == "setup":
        return "Build anticipation — this leads into a literary quotation."
    if quote_mode == "reading":
        return (
            "Read this as a direct literary quotation with weight and relish. "
            "Slower pace, savor the words."
        )
    if quote_mode == "commentary":
        return "Resume normal conversational pace after the quotation."
    return ""


def _emphasis_direction(words: list[str]) -> str:
    """Convert emphasis_words to delivery direction."""
    if not words:
        return ""
    return f"Give slight emphasis to: {', '.join(words)}."


def build_turn_prompt(turn: Turn) -> str:
    """Build a natural-language TTS prompt for a complete turn.

    Embeds delivery annotations as stage directions that the Gemini TTS
    model interprets for prosody control.
    """
    speaker = turn.speaker
    accent = SPEAKER_ACCENTS.get(speaker, "speaks with a British accent")
    policy = SPEAKER_VOICE_POLICIES.get(
        speaker,
        VoicePolicy(rate=1.0, energy="medium", pause_bias_ms=200, style="neutral"),
    )

    lines: list[str] = [
        f"[Voice direction: {speaker} {accent}. "
        f"Energy: {policy.energy}. Style: {policy.style}.]",
        "",
    ]

    for utt in turn.utterances:
        directions: list[str] = []

        rate_dir = _rate_direction(utt.rate, policy.rate)
        if rate_dir:
            directions.append(rate_dir)

        quote_dir = _quote_direction(utt.quote_mode)
        if quote_dir:
            directions.append(quote_dir)

        emph_dir = _emphasis_direction(utt.emphasis_words)
        if emph_dir:
            directions.append(emph_dir)

        if directions:
            lines.append(f"({' '.join(directions)})")
        lines.append(utt.text)
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# PCM → AudioSegment conversion
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


def _cache_key(text: str, voice: str, model: str) -> str:
    """Generate a stable cache key for a TTS call."""
    h = hashlib.sha256(f"{model}:{voice}:{text}".encode()).hexdigest()[:16]
    return h


def _load_cached(key: str) -> AudioSegment | None:
    """Load cached audio if it exists."""
    path = CACHE_DIR / f"{key}.wav"
    if path.exists():
        return AudioSegment.from_wav(str(path))
    return None


def _save_cache(key: str, audio: AudioSegment) -> None:
    """Save audio to cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{key}.wav"
    audio.export(str(path), format="wav")


# ---------------------------------------------------------------------------
# TTS rendering
# ---------------------------------------------------------------------------


def render_turn(
    turn: Turn,
    client: genai.Client,
    model_id: str,
) -> AudioSegment:
    """Render a single turn to audio, with pause insertion."""
    speaker = turn.speaker
    voice_name = SPEAKER_VOICES.get(speaker, "Sulafat")
    prompt = build_turn_prompt(turn)

    # Check cache for the whole turn
    cache_key = _cache_key(prompt, voice_name, model_id)
    cached = _load_cached(cache_key)
    if cached is not None:
        logger.info("  Cache hit for %s turn (%d chars)", speaker, len(prompt))
        return _apply_turn_pauses(cached, turn)

    logger.info(
        "  Rendering %s turn (%d utterances, %d chars)",
        speaker,
        len(turn.utterances),
        len(prompt),
    )

    audio: AudioSegment | None = None
    for attempt in range(4):
        try:
            response = client.models.generate_content(
                model=model_id,
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

    _save_cache(cache_key, audio)

    return _apply_turn_pauses(audio, turn)


def _apply_turn_pauses(audio: AudioSegment, turn: Turn) -> AudioSegment:
    """Add leading pause (from first utterance's pause_before_ms) and
    trailing pause (from last utterance's pause_after_ms)."""
    result = AudioSegment.empty()

    # Leading pause
    first = turn.utterances[0] if turn.utterances else None
    if first and first.pause_before_ms > 0:
        result += silence_ms(first.pause_before_ms)

    result += audio

    # Trailing pause
    last = turn.utterances[-1] if turn.utterances else None
    if last and last.pause_after_ms > 300:
        # Add extra beyond the normal 300ms sentence gap
        result += silence_ms(last.pause_after_ms - 300)

    return result


def render_episode(
    episode: PodcastEpisode,
    client: genai.Client,
    model_id: str,
    concurrency: int = 1,
) -> AudioSegment:
    """Render all segments and turns into a single audio track.

    When concurrency > 1, turns within each segment are rendered in
    parallel via a thread pool, then assembled in order.
    """
    full_audio = AudioSegment.empty()

    for seg_idx, seg in enumerate(episode.segments):
        logger.info(
            "Segment %d/%d: '%s' (%d turns, concurrency=%d)",
            seg_idx + 1,
            len(episode.segments),
            seg.title,
            len(seg.turns),
            concurrency,
        )

        if concurrency <= 1:
            # Sequential path (original behaviour)
            for turn_idx, turn in enumerate(seg.turns):
                turn_audio = render_turn(turn, client, model_id)
                full_audio += turn_audio
                logger.info(
                    "    Turn %d/%d [%s]: %.1fs",
                    turn_idx + 1,
                    len(seg.turns),
                    turn.speaker,
                    len(turn_audio) / 1000,
                )
        else:
            # Parallel path — render turns concurrently, assemble in order
            turn_audios: list[AudioSegment | None] = [None] * len(seg.turns)

            def _render_one(idx: int, turn: Turn) -> tuple[int, AudioSegment]:
                audio = render_turn(turn, client, model_id)
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

        # Segment break — longer pause between segments
        if seg_idx < len(episode.segments) - 1:
            full_audio += silence_ms(2000)

    return full_audio


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Render podcast episode to audio")
    parser.add_argument(
        "--model",
        choices=["flash", "pro"],
        default="flash",
        help="Gemini TTS model tier (default: flash)",
    )
    parser.add_argument(
        "--output",
        default="podcast.mp3",
        help="Output filename (default: podcast.mp3)",
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

    # Resolve episode path
    if args.run:
        episode_path = DATA_DIR / "runs" / args.run / "phase3_episode.json"
    elif args.episode:
        episode_path = Path(args.episode)
    else:
        episode_path = DATA_DIR / "podcast_episode.json"

    # Load episode
    with open(episode_path) as f:
        episode = PodcastEpisode.model_validate(json.load(f))

    logger.info(
        "Loaded episode: %d segments, %d total turns",
        len(episode.segments),
        sum(len(s.turns) for s in episode.segments),
    )

    # Optionally filter to one segment
    if args.segment is not None:
        seg = episode.segments[args.segment]
        episode = PodcastEpisode(
            title=episode.title,
            segments=[seg],
            metadata=episode.metadata,
        )
        logger.info("Rendering only segment %d: '%s'", args.segment, seg.title)

    model_id = MODEL_IDS[args.model]
    logger.info("Using model: %s", model_id)

    client = genai.Client()

    audio = render_episode(episode, client, model_id, concurrency=args.concurrency)

    # Export — save to authoritative audio dir if --run is set
    if args.run and args.output == "podcast.mp3":
        audio_dir = PODCAST_AUDIO_DIR / args.run
        audio_dir.mkdir(parents=True, exist_ok=True)
        seg_suffix = f"_segment_{args.segment}" if args.segment is not None else ""
        output_path = audio_dir / f"podcast{seg_suffix}.mp3"
    else:
        output_path = BASE_DIR / args.output
    logger.info(
        "Exporting %.1f minutes of audio to %s",
        len(audio) / 60000,
        output_path,
    )
    audio.export(str(output_path), format="mp3", bitrate=args.bitrate)
    logger.info("Done: %s (%.1f MB)", output_path, output_path.stat().st_size / 1e6)


if __name__ == "__main__":
    main()
