# `trevelyan_v2` TTS Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render one alternative audio of `ext_v19_all_swapped_hostprep` using `gemini-3.1-flash-tts-preview` and Google's six-strategy prompt scheme, without disturbing the default (classic) rendering path.

**Architecture:** Extract rendering configuration behind a `TTSProfile` protocol in a new `enrichment/tts_profiles/` package. Current behaviour is preserved as `ClassicProfile`. New `TrevelyanV2Profile` implements the six-strategy prompt, a reduced `pause_scale`, and isolates its cache. `render_audio.py` selects a profile via a new `--profile {classic,trevelyan_v2}` flag, defaulting to `classic`.

**Tech Stack:** Python 3.13, `google-genai`, `pydub`, `pydantic`, `pytest`. No new third-party deps.

**Spec:** [`docs/superpowers/specs/2026-04-17-tts-trevelyan-v2-experiment-design.md`](../specs/2026-04-17-tts-trevelyan-v2-experiment-design.md).

---

## File structure

**Create:**
- `enrichment/tts_profiles/__init__.py` — registry, `get_profile`, `profile_names`
- `enrichment/tts_profiles/base.py` — `TTSProfile` Protocol + `EpisodeContext` dataclass
- `enrichment/tts_profiles/classic.py` — preserves current prompt/voice/pause behaviour
- `enrichment/tts_profiles/trevelyan_v2.py` — new profile
- `tests/enrichment/__init__.py` (empty)
- `tests/enrichment/test_classic_profile.py`
- `tests/enrichment/test_trevelyan_v2_profile.py`
- `tests/enrichment/test_pause_scaling.py`
- `tests/enrichment/test_profile_registry.py`

**Modify:**
- `enrichment/render_audio.py` — add `--profile` flag; delegate prompt building, voice selection, cache namespacing, and pause scaling to the selected profile; suffix output filename when profile ≠ `classic`.

**Unchanged public behaviour:** existing invocations without `--profile` produce the same audio as before (confirmed by the classic profile's prompt-string snapshot test).

---

## Task 1: Create the `tts_profiles` package skeleton (Protocol + context)

**Files:**
- Create: `enrichment/tts_profiles/__init__.py`
- Create: `enrichment/tts_profiles/base.py`
- Create: `tests/enrichment/__init__.py`
- Create: `tests/enrichment/test_profile_registry.py`

- [ ] **Step 1: Write the failing registry test**

Create `tests/enrichment/__init__.py` as an empty file, then create `tests/enrichment/test_profile_registry.py`:

```python
"""Tests for the TTSProfile registry."""
from __future__ import annotations

import pytest

from enrichment.tts_profiles import get_profile, profile_names


def test_profile_names_lists_both_profiles() -> None:
    assert set(profile_names()) == {"classic", "trevelyan_v2"}


def test_get_profile_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown TTS profile"):
        get_profile("does_not_exist")


def test_get_profile_classic_returns_profile_with_expected_attrs() -> None:
    profile = get_profile("classic")
    assert profile.name == "classic"
    assert profile.cache_namespace == "classic"
    assert profile.pause_scale == 1.0
    assert profile.model_id == "gemini-2.5-flash-preview-tts"


def test_get_profile_classic_accepts_pro_model_id() -> None:
    profile = get_profile("classic", classic_model_id="gemini-2.5-pro-preview-tts")
    assert profile.model_id == "gemini-2.5-pro-preview-tts"


def test_get_profile_trevelyan_v2_returns_profile_with_expected_attrs() -> None:
    profile = get_profile("trevelyan_v2")
    assert profile.name == "trevelyan_v2"
    assert profile.cache_namespace == "trevelyan_v2"
    assert profile.pause_scale == 0.5
    assert profile.model_id == "gemini-3.1-flash-tts-preview"
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/enrichment/test_profile_registry.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'enrichment.tts_profiles'`.

- [ ] **Step 3: Create `enrichment/tts_profiles/base.py`**

```python
"""TTSProfile protocol and shared types for render_audio.

A profile bundles everything that varies between different TTS renderings:
model id, voice selection, prompt construction, cache isolation, and
silence scaling. Adding a new profile must not require editing render_audio.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from enrichment.podcast_types import Turn


@dataclass(frozen=True)
class EpisodeContext:
    """Positional context for a turn within its episode."""

    episode_title: str
    segment_title: str
    segment_index: int
    turn_index: int
    previous_turn: Turn | None


class TTSProfile(Protocol):
    """A complete rendering configuration."""

    name: str
    model_id: str
    cache_namespace: str
    pause_scale: float

    def voice_name(self, speaker: str) -> str: ...
    def build_turn_prompt(self, turn: Turn, ctx: EpisodeContext) -> str: ...
```

- [ ] **Step 4: Create `enrichment/tts_profiles/__init__.py` (registry only, classes defined in later tasks)**

```python
"""TTS profile registry."""
from __future__ import annotations

from enrichment.tts_profiles.base import EpisodeContext, TTSProfile

__all__ = ["EpisodeContext", "TTSProfile", "get_profile", "profile_names"]


def profile_names() -> list[str]:
    return ["classic", "trevelyan_v2"]


def get_profile(name: str, *, classic_model_id: str | None = None) -> TTSProfile:
    if name == "classic":
        from enrichment.tts_profiles.classic import ClassicProfile

        return ClassicProfile(model_id=classic_model_id)
    if name == "trevelyan_v2":
        from enrichment.tts_profiles.trevelyan_v2 import TrevelyanV2Profile

        return TrevelyanV2Profile()
    raise ValueError(f"Unknown TTS profile: {name!r}. Known: {profile_names()!r}")
```

- [ ] **Step 5: Run test again**

```
uv run pytest tests/enrichment/test_profile_registry.py -v
```
Expected: still FAIL — `ClassicProfile` and `TrevelyanV2Profile` don't exist yet. That's fine; they're covered in Tasks 2 and 4. Mark these tests xfail-for-now is unnecessary — Tasks 2 and 4 will make them pass.

- [ ] **Step 6: Commit the skeleton (tests red; will go green after Tasks 2 & 4)**

```bash
git add enrichment/tts_profiles/__init__.py enrichment/tts_profiles/base.py tests/enrichment/__init__.py tests/enrichment/test_profile_registry.py
git commit -m "Scaffold tts_profiles package with TTSProfile protocol

Introduces the abstraction that will let render_audio select between
rendering configurations. ClassicProfile and TrevelyanV2Profile follow
in separate commits."
```

---

## Task 2: Extract current behaviour into `ClassicProfile`

**Files:**
- Create: `enrichment/tts_profiles/classic.py`
- Create: `tests/enrichment/test_classic_profile.py`

- [ ] **Step 1: Write the failing behaviour-preservation test**

Create `tests/enrichment/test_classic_profile.py`:

```python
"""Tests for ClassicProfile — guards current rendering behaviour."""
from __future__ import annotations

from enrichment.podcast_types import Turn, Utterance
from enrichment.tts_profiles import EpisodeContext, get_profile


def _mk_turn(speaker: str = "Host") -> Turn:
    return Turn(
        speaker=speaker,
        role="host",
        utterances=[
            Utterance(
                text="Welcome to the programme.",
                sentence_type="intro",
                quote_mode="none",
                rate=1.0,
                pause_before_ms=0,
                pause_after_ms=300,
                emphasis_words=[],
            ),
            Utterance(
                text="Let me read a passage.",
                sentence_type="quote_setup",
                quote_mode="setup",
                rate=1.0,
                pause_before_ms=200,
                pause_after_ms=300,
                emphasis_words=["passage"],
            ),
        ],
    )


def _ctx() -> EpisodeContext:
    return EpisodeContext(
        episode_title="Bleak House",
        segment_title="Opening",
        segment_index=0,
        turn_index=0,
        previous_turn=None,
    )


def test_classic_voice_name_for_known_speaker() -> None:
    profile = get_profile("classic")
    assert profile.voice_name("Host") == "Sulafat"
    assert profile.voice_name("Oliver Trevelyan") == "Achird"


def test_classic_voice_name_fallback() -> None:
    profile = get_profile("classic")
    assert profile.voice_name("Nobody") == "Sulafat"


def test_classic_prompt_starts_with_voice_direction_header() -> None:
    profile = get_profile("classic")
    prompt = profile.build_turn_prompt(_mk_turn(), _ctx())
    assert prompt.startswith("[Voice direction: Host ")
    assert "Energy: medium" in prompt
    assert "Style: presenter_warm" in prompt


def test_classic_prompt_emits_quote_setup_direction() -> None:
    profile = get_profile("classic")
    prompt = profile.build_turn_prompt(_mk_turn(), _ctx())
    assert "Build anticipation" in prompt


def test_classic_prompt_emits_emphasis_direction() -> None:
    profile = get_profile("classic")
    prompt = profile.build_turn_prompt(_mk_turn(), _ctx())
    assert "Give slight emphasis to: passage." in prompt


def test_classic_prompt_no_sample_context_header() -> None:
    """Classic does not use the 3.1 markdown-header scheme."""
    profile = get_profile("classic")
    prompt = profile.build_turn_prompt(_mk_turn(), _ctx())
    assert "### SAMPLE CONTEXT" not in prompt
    assert "#### TRANSCRIPT" not in prompt
```

- [ ] **Step 2: Run test to verify it fails**

```
uv run pytest tests/enrichment/test_classic_profile.py -v
```
Expected: FAIL — `ClassicProfile` not yet importable.

- [ ] **Step 3: Create `enrichment/tts_profiles/classic.py` (verbatim port of current logic)**

```python
"""Classic profile — preserves the rendering behaviour in place before
the 2026-04-17 tts_profiles refactor.

The dicts and helper functions below are moved verbatim from the previous
enrichment/render_audio.py so that existing outputs remain byte-identical
under --profile classic (the default).
"""
from __future__ import annotations

from enrichment.podcast_types import Turn, VoicePolicy
from enrichment.tts_profiles.base import EpisodeContext

SPEAKER_VOICES: dict[str, str] = {
    "Host": "Sulafat",
    "Eleanor Hartley": "Zephyr",
    "James Blackstone": "Sadaltager",
    "Caroline Woodcourt": "Achernar",
    "Narrator": "Schedar",
    "Edmund Leigh": "Algenib",
    "Daniel Rosen": "Alnilam",
    "Oliver Trevelyan": "Achird",
    "Sarah Chen": "Zephyr",
    "Rebecca Martinez": "Achernar",
    "Elena Volkov": "Aoede",
}

SPEAKER_ACCENTS: dict[str, str] = {
    "Host": "speaks with a warm Home Counties accent, like a BBC Radio 4 presenter",
    "Eleanor Hartley": "speaks with a lively Cambridge accent, articulate and precise",
    "James Blackstone": "speaks with a measured Edinburgh accent, dry and authoritative",
    "Caroline Woodcourt": "speaks with a gentle Bristol accent, warm and intimate",
    "Narrator": "speaks with a clear, neutral British accent",
    "Edmund Leigh": "speaks with a patrician Oxford accent, unhurried and precise",
    "Daniel Rosen": "speaks with a clear London accent, purposeful and direct",
    "Oliver Trevelyan": "speaks with a warm, theatrical Home Counties accent, varied and lively",
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
    "Edmund Leigh": VoicePolicy(rate=0.94, energy="medium_low", pause_bias_ms=280, style="patrician_measured"),
    "Daniel Rosen": VoicePolicy(rate=0.99, energy="medium_high", pause_bias_ms=200, style="passionate_precise"),
    "Oliver Trevelyan": VoicePolicy(rate=1.02, energy="medium_high", pause_bias_ms=190, style="raconteur_warm"),
    "Sarah Chen": VoicePolicy(rate=1.01, energy="medium_high", pause_bias_ms=180, style="analytical_clear"),
    "Rebecca Martinez": VoicePolicy(rate=0.96, energy="medium", pause_bias_ms=250, style="contemplative_measured"),
    "Elena Volkov": VoicePolicy(rate=0.98, energy="medium", pause_bias_ms=210, style="engaged_analytical"),
}


def _rate_direction(rate: float, speaker_base: float) -> str:
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
    if not words:
        return ""
    return f"Give slight emphasis to: {', '.join(words)}."


class ClassicProfile:
    """Current-behaviour profile. Default when no --profile flag is passed."""

    name = "classic"
    cache_namespace = "classic"
    pause_scale = 1.0

    def __init__(self, model_id: str | None = None) -> None:
        self.model_id = model_id or "gemini-2.5-flash-preview-tts"

    def voice_name(self, speaker: str) -> str:
        return SPEAKER_VOICES.get(speaker, "Sulafat")

    def build_turn_prompt(self, turn: Turn, ctx: EpisodeContext) -> str:
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
```

- [ ] **Step 4: Run tests**

```
uv run pytest tests/enrichment/test_classic_profile.py tests/enrichment/test_profile_registry.py::test_get_profile_classic_returns_profile_with_expected_attrs tests/enrichment/test_profile_registry.py::test_get_profile_classic_accepts_pro_model_id -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add enrichment/tts_profiles/classic.py tests/enrichment/test_classic_profile.py
git commit -m "Add ClassicProfile preserving current render_audio behaviour

Verbatim port of the SPEAKER_VOICES/ACCENTS/POLICIES dicts and prompt
builder from render_audio.py. render_audio.py still imports the old
symbols; refactor to use ClassicProfile comes in the next commit."
```

---

## Task 3: Refactor `render_audio.py` to use profiles

**Files:**
- Modify: `enrichment/render_audio.py`

- [ ] **Step 1: Read the current `render_audio.py` end-to-end**

```
uv run cat enrichment/render_audio.py
```

Note: Bash `cat` may be blocked; use the Read tool instead if executing this plan via Claude. Goal is to reload the current structure into working memory before editing.

- [ ] **Step 2: Replace `render_audio.py` with the profile-driven version**

Overwrite `enrichment/render_audio.py` with:

```python
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

PODCAST_AUDIO_DIR = Path(
    os.environ.get("PODCAST_AUDIO_DIR", "/Volumes/Crucial X9/bleakhouse_audio")
)

CLASSIC_MODEL_IDS = {
    "flash": "gemini-2.5-flash-preview-tts",
    "pro": "gemini-2.5-pro-preview-tts",
}


def pcm_to_segment(pcm_data: bytes, sample_rate: int = 24000) -> AudioSegment:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    buf.seek(0)
    return AudioSegment.from_wav(buf)


def silence_ms(duration_ms: int) -> AudioSegment:
    return AudioSegment.silent(duration=max(0, duration_ms))


def _cache_key(text: str, voice: str, model: str) -> str:
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

    if args.run and args.output == "podcast.mp3":
        audio_dir = PODCAST_AUDIO_DIR / args.run
        audio_dir.mkdir(parents=True, exist_ok=True)
        seg_suffix = f"_segment_{args.segment}" if args.segment is not None else ""
        profile_suffix = f"_{profile.name}" if profile.name != "classic" else ""
        output_path = audio_dir / f"podcast{profile_suffix}{seg_suffix}.mp3"
    else:
        profile_suffix = f"_{profile.name}" if profile.name != "classic" else ""
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
```

Key changes from the previous file:
- Imports `TTSProfile`, `EpisodeContext`, `get_profile`, `profile_names` from `enrichment.tts_profiles`.
- `SPEAKER_VOICES`, `SPEAKER_ACCENTS`, `SPEAKER_VOICE_POLICIES`, `build_turn_prompt`, `_rate_direction`, `_quote_direction`, `_emphasis_direction`, `MODEL_IDS` all removed (now in `classic.py`; classic CLI flag maps to `CLASSIC_MODEL_IDS`).
- `render_turn` takes `profile` + `ctx` instead of `model_id`.
- `render_episode` takes `profile` and builds an `EpisodeContext` per turn (with `previous_turn`).
- `apply_turn_pauses` renamed from `_apply_turn_pauses` (now called from `render_turn` after cache hit too) and takes `pause_scale`.
- `_cache_path` namespaces the cache dir per `profile.cache_namespace`.
- Inter-segment silence multiplied by `profile.pause_scale`.
- Output path appends `_<profile>` suffix when the profile is not classic.

- [ ] **Step 3: Run existing tests to confirm no regressions**

```
uv run pytest tests/ -v
```
Expected: all existing `tests/test_transport_podcast.py` tests PASS; new classic + registry tests PASS; `trevelyan_v2` registry test still fails (implementation in Task 4).

- [ ] **Step 4: Run lint and type checks on changed files**

```
uv run ruff check enrichment/render_audio.py enrichment/tts_profiles/
uv run pyright enrichment/render_audio.py enrichment/tts_profiles/
```
Expected: no new errors. If the pyright run surfaces pre-existing errors unrelated to this change, note them but do not fix them here; the user's policy is zero pre-existing ruff errors (run `uv run ruff check .` and fix any).

- [ ] **Step 5: Commit**

```bash
git add enrichment/render_audio.py
git commit -m "Rewire render_audio to use TTSProfile

--profile flag selects behaviour. Classic remains the default and
continues to use the old prompt shape and voices via ClassicProfile.
Cache is now namespaced per profile; output path appends the profile
name when non-classic."
```

---

## Task 4: Implement `TrevelyanV2Profile`

**Files:**
- Create: `enrichment/tts_profiles/trevelyan_v2.py`
- Create: `tests/enrichment/test_trevelyan_v2_profile.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/enrichment/test_trevelyan_v2_profile.py`:

```python
"""Tests for TrevelyanV2Profile — the experimental 3.1 profile."""
from __future__ import annotations

import pytest

from enrichment.podcast_types import Turn, Utterance
from enrichment.tts_profiles import EpisodeContext, get_profile


def _mk_utterance(
    text: str = "Hello.",
    quote_mode: str = "none",
    rate: float = 1.0,
    pause_before_ms: int = 0,
    pause_after_ms: int = 300,
    emphasis_words: list[str] | None = None,
    sentence_type: str = "analysis",
) -> Utterance:
    return Utterance(
        text=text,
        sentence_type=sentence_type,  # type: ignore[arg-type]
        quote_mode=quote_mode,  # type: ignore[arg-type]
        rate=rate,
        pause_before_ms=pause_before_ms,
        pause_after_ms=pause_after_ms,
        emphasis_words=emphasis_words or [],
    )


def _mk_turn(speaker: str, utterances: list[Utterance] | None = None) -> Turn:
    return Turn(
        speaker=speaker,
        role="host" if speaker == "Host" else "guest",
        utterances=utterances or [_mk_utterance()],
    )


def _ctx(previous_turn: Turn | None = None, segment_title: str = "Opening") -> EpisodeContext:
    return EpisodeContext(
        episode_title="Bleak House",
        segment_title=segment_title,
        segment_index=0,
        turn_index=0 if previous_turn is None else 1,
        previous_turn=previous_turn,
    )


@pytest.fixture
def profile():
    return get_profile("trevelyan_v2")


def test_attributes(profile) -> None:
    assert profile.name == "trevelyan_v2"
    assert profile.model_id == "gemini-3.1-flash-tts-preview"
    assert profile.cache_namespace == "trevelyan_v2"
    assert profile.pause_scale == 0.5


def test_all_six_headers_present_when_previous_turn_given(profile) -> None:
    previous = _mk_turn("Edmund Leigh", [_mk_utterance("I would begin with Chapter 1.")])
    turn = _mk_turn("Oliver Trevelyan")
    prompt = profile.build_turn_prompt(turn, _ctx(previous_turn=previous))
    for header in ("# AUDIO PROFILE", "## THE SCENE", "### DIRECTOR'S NOTES", "### SAMPLE CONTEXT", "#### TRANSCRIPT"):
        assert header in prompt, f"missing header: {header}"


def test_sample_context_omitted_when_no_previous_turn(profile) -> None:
    turn = _mk_turn("Host")
    prompt = profile.build_turn_prompt(turn, _ctx(previous_turn=None))
    assert "### SAMPLE CONTEXT" not in prompt


def test_sample_context_quotes_previous_speaker_verbatim(profile) -> None:
    previous = _mk_turn(
        "Daniel Rosen",
        [_mk_utterance("The novel's economics are brutal.")],
    )
    turn = _mk_turn("Oliver Trevelyan")
    prompt = profile.build_turn_prompt(turn, _ctx(previous_turn=previous))
    assert "You are responding to Daniel Rosen" in prompt
    assert "\"The novel's economics are brutal.\"" in prompt


def test_trevelyan_audio_profile_contains_user_specified_facts(profile) -> None:
    turn = _mk_turn("Oliver Trevelyan")
    prompt = profile.build_turn_prompt(turn, _ctx())
    assert "Uppingham" in prompt
    assert "late 1950s" in prompt
    assert "Received Pronunciation" in prompt
    assert "Cambridge" in prompt


def test_host_audio_profile_contains_user_specified_facts(profile) -> None:
    turn = _mk_turn("Host")
    prompt = profile.build_turn_prompt(turn, _ctx())
    assert "around 80" in prompt
    assert "northern English" in prompt or "Northern English" in prompt
    assert "Cambridge" in prompt


def test_quote_reading_gets_serious_tag_and_note(profile) -> None:
    turn = _mk_turn(
        "Oliver Trevelyan",
        [_mk_utterance("'Fog everywhere.'", quote_mode="reading")],
    )
    prompt = profile.build_turn_prompt(turn, _ctx())
    assert "[serious] 'Fog everywhere.'" in prompt
    assert "direct literary quotation" in prompt.lower()


def test_quote_setup_gets_curious_tag(profile) -> None:
    turn = _mk_turn(
        "Oliver Trevelyan",
        [_mk_utterance("Listen to this:", quote_mode="setup")],
    )
    prompt = profile.build_turn_prompt(turn, _ctx())
    assert "[curious] Listen to this:" in prompt


def test_hesitantly_tag_never_appears(profile) -> None:
    turn = _mk_turn(
        "Edmund Leigh",
        [_mk_utterance("A thought.", pause_before_ms=800)],
    )
    prompt = profile.build_turn_prompt(turn, _ctx())
    assert "[hesitantly]" not in prompt


def test_emphasis_words_emitted_as_directors_note_not_inline_tag(profile) -> None:
    turn = _mk_turn(
        "Daniel Rosen",
        [_mk_utterance("That is the point.", emphasis_words=["point"])],
    )
    prompt = profile.build_turn_prompt(turn, _ctx())
    assert "[point]" not in prompt
    assert "light emphasis" in prompt.lower()
    assert "point" in prompt


def test_unknown_speaker_gets_fallback_audio_profile(profile) -> None:
    turn = _mk_turn("Unknown Guest")
    prompt = profile.build_turn_prompt(turn, _ctx())
    assert "# AUDIO PROFILE: Unknown Guest" in prompt


def test_mid_range_rate_emits_no_special_pace_line(profile) -> None:
    turn = _mk_turn(
        "Daniel Rosen",
        [_mk_utterance(rate=1.0)],  # Rosen base 0.99 → effective 0.99, inside mid-range
    )
    prompt = profile.build_turn_prompt(turn, _ctx())
    assert "slower" not in prompt.lower()
    assert "brisker" not in prompt.lower()


def test_voice_names_match_classic(profile) -> None:
    assert profile.voice_name("Host") == "Sulafat"
    assert profile.voice_name("Oliver Trevelyan") == "Achird"
    assert profile.voice_name("Nobody") == "Sulafat"
```

- [ ] **Step 2: Run the tests to verify they fail**

```
uv run pytest tests/enrichment/test_trevelyan_v2_profile.py -v
```
Expected: all FAIL with ImportError / attribute errors — `TrevelyanV2Profile` does not exist.

- [ ] **Step 3: Create `enrichment/tts_profiles/trevelyan_v2.py`**

```python
"""Experimental TTS profile using gemini-3.1-flash-tts-preview and the
six-strategy prompting scheme documented at
https://ai.google.dev/gemini-api/docs/speech-generation#prompting-strategies.

Spec: docs/superpowers/specs/2026-04-17-tts-trevelyan-v2-experiment-design.md
"""
from __future__ import annotations

from collections.abc import Iterable

from enrichment.podcast_types import Turn, Utterance, VoicePolicy
from enrichment.tts_profiles.base import EpisodeContext
from enrichment.tts_profiles.classic import (
    SPEAKER_ACCENTS,
    SPEAKER_VOICE_POLICIES,
    SPEAKER_VOICES,
)

MODEL_ID = "gemini-3.1-flash-tts-preview"

SCENE = """\
## THE SCENE
A BBC Radio 4 studio, early evening. Four participants seated at a round oak
table, each with a boom-mounted microphone. Soft foam acoustic panels; the
faint hum of studio gear. The tone is In Our Time — measured, literary,
unhurried, but the conversation flows: participants pick up each other's
threads with minimal dead air and the host treats silence as a tool, not a
default. The red RECORD light is on; the host has just wrapped the
introduction."""

AUDIO_PROFILES: dict[str, str] = {
    "Host": """\
# AUDIO PROFILE: Host / "The chair"
A veteran BBC Radio 4 presenter, around 80 years old. Educated RP with
northern English colouring — grammar-school in the West Riding, then
Cambridge. Low, generous timbre; the voice of someone who has interviewed
everyone and is still curious. Treats questions as invitations. Never hurries
a guest, but never leaves dead air either.""",
    "Oliver Trevelyan": """\
# AUDIO PROFILE: Oliver Trevelyan / "The reader-performer"
An English actor and audiobook artist, male, born in the late 1950s.
Educated at Uppingham School and Cambridge. Received Pronunciation of that
generation: resonant lower register, theatrical timing, a touch of avuncular
warmth. A man who has read Dickens aloud for a living and relishes a good
anecdote. Never hurried; always moving forward.""",
    "Edmund Leigh": """\
# AUDIO PROFILE: Edmund Leigh / "The don"
Emeritus Oxford don, late 60s, Victorianist. Patrician RP with faint
pre-war inflections. Dry, aphoristic, allergic to cliché. His pauses do as
much work as his sentences — but those pauses are chosen, not habitual.""",
    "Daniel Rosen": """\
# AUDIO PROFILE: Daniel Rosen / "The critic"
London-based critic, early 40s, trained between New York and UCL. Clear
London cadence with American emphasis patterns. Direct, argumentative,
intellectually quick; tends to press a point hard, then soften it with a
joke. Forward momentum is his default.""",
}

FALLBACK_AUDIO_PROFILE_TEMPLATE = """\
# AUDIO PROFILE: {speaker}
A thoughtful, well-spoken guest on a literary radio programme. Educated RP,
conversational, forward-flowing."""

STYLE_PHRASES: dict[str, str] = {
    "presenter_warm": "warm, generous presenter — draws guests out",
    "analytic_bright": "bright, analytic, excited by craft",
    "measured_dry": "measured, dry authority grounded in evidence",
    "reflective_intimate": "reflective, intimate, emotionally engaged",
    "neutral": "neutral narration",
    "patrician_measured": "patrician, unhurried, aphoristic",
    "passionate_precise": "passionate but precise; argument-driven",
    "raconteur_warm": "warm raconteur with theatrical relish",
    "analytical_clear": "analytical, precise, direct",
    "contemplative_measured": "contemplative, unhurried, hypothesis-driven",
    "engaged_analytical": "engaged, analytical, historically informed",
}

DEFAULT_POLICY = VoicePolicy(
    rate=1.0, energy="medium", pause_bias_ms=200, style="neutral"
)


def _audio_profile(speaker: str) -> str:
    return AUDIO_PROFILES.get(
        speaker, FALLBACK_AUDIO_PROFILE_TEMPLATE.format(speaker=speaker)
    )


def _pacing_line(avg_rate: float, speaker_base: float) -> str:
    effective = avg_rate * speaker_base
    base = (
        "Prefer forward momentum; let sentences connect without settling. "
        "Pauses only where a thought genuinely demands one."
    )
    if effective < 0.92:
        return f"Noticeably slower than default. {base}"
    if effective > 1.06:
        return f"Noticeably brisker than default. {base}"
    return base


def _articulation_line(energy: str, emphasis_present: bool) -> str:
    base = {
        "medium_low": "clean articulation, unhurried",
        "medium": "clean articulation, natural energy",
        "medium_high": "clean articulation, slightly forward energy",
    }.get(energy, "clean articulation")
    if emphasis_present:
        base += "; lift the marked words slightly"
    return base


def _breathing_line(utterances: Iterable[Utterance]) -> str | None:
    if any(u.pause_before_ms > 600 for u in utterances):
        return (
            "Take a clear breath before the turn's longer pauses; otherwise "
            "breathe between clauses, not at commas."
        )
    return None


def _accent_for(speaker: str) -> str:
    return SPEAKER_ACCENTS.get(speaker, "neutral British")


def _director_notes(turn: Turn) -> str:
    policy = SPEAKER_VOICE_POLICIES.get(turn.speaker, DEFAULT_POLICY)
    lines = ["### DIRECTOR'S NOTES"]
    style_phrase = STYLE_PHRASES.get(policy.style, policy.style)
    lines.append(f"Style: {policy.style} — {style_phrase}.")

    rates = [u.rate for u in turn.utterances] or [1.0]
    avg_rate = sum(rates) / len(rates)
    lines.append(f"Pacing: {_pacing_line(avg_rate, policy.rate)}")

    emphasis_present = any(u.emphasis_words for u in turn.utterances)
    lines.append(
        f"Articulation: {_articulation_line(policy.energy, emphasis_present)}."
    )

    if turn.speaker == "Oliver Trevelyan":
        lines.append("Accent: as described in the Audio Profile.")
    else:
        lines.append(f"Accent: {_accent_for(turn.speaker)}.")

    breathing = _breathing_line(turn.utterances)
    if breathing:
        lines.append(f"Breathing: {breathing}")

    if any(u.quote_mode == "reading" for u in turn.utterances):
        lines.append(
            "Quotation: read any marked quotation as a direct literary "
            "quotation; slower, savoured."
        )

    emphasis_words = sorted(
        {w for u in turn.utterances for w in u.emphasis_words}
    )
    if emphasis_words:
        lines.append(
            f"Emphasis: give light emphasis to: {', '.join(emphasis_words)}."
        )

    return "\n".join(lines)


def _audio_tag(quote_mode: str) -> str:
    if quote_mode == "setup":
        return "[curious] "
    if quote_mode == "reading":
        return "[serious] "
    return ""


def _transcript(turn: Turn) -> str:
    lines = ["#### TRANSCRIPT"]
    for utt in turn.utterances:
        lines.append(f"{_audio_tag(utt.quote_mode)}{utt.text}")
    return "\n".join(lines)


def _sample_context(ctx: EpisodeContext) -> str | None:
    prev = ctx.previous_turn
    if prev is None or not prev.utterances:
        return None
    last_text = prev.utterances[-1].text.strip()
    return (
        "### SAMPLE CONTEXT\n"
        f"You are responding to {prev.speaker}. They have just said:\n"
        f"\"{last_text}\"\n"
        f"The segment is \"{ctx.segment_title}\"."
    )


class TrevelyanV2Profile:
    """Experimental 3.1 profile — see module docstring."""

    name = "trevelyan_v2"
    model_id = MODEL_ID
    cache_namespace = "trevelyan_v2"
    pause_scale = 0.5

    def voice_name(self, speaker: str) -> str:
        return SPEAKER_VOICES.get(speaker, "Sulafat")

    def build_turn_prompt(self, turn: Turn, ctx: EpisodeContext) -> str:
        sections: list[str] = [
            _audio_profile(turn.speaker),
            SCENE,
            _director_notes(turn),
        ]
        sample = _sample_context(ctx)
        if sample is not None:
            sections.append(sample)
        sections.append(_transcript(turn))
        return "\n\n".join(sections)
```

- [ ] **Step 4: Run the trevelyan_v2 tests + registry**

```
uv run pytest tests/enrichment/test_trevelyan_v2_profile.py tests/enrichment/test_profile_registry.py -v
```
Expected: all PASS.

- [ ] **Step 5: Lint and type check**

```
uv run ruff check enrichment/tts_profiles/trevelyan_v2.py tests/enrichment/test_trevelyan_v2_profile.py
uv run pyright enrichment/tts_profiles/trevelyan_v2.py tests/enrichment/test_trevelyan_v2_profile.py
```
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add enrichment/tts_profiles/trevelyan_v2.py tests/enrichment/test_trevelyan_v2_profile.py
git commit -m "Add TrevelyanV2Profile using gemini-3.1-flash-tts-preview

Six-strategy prompt (Audio Profile / Scene / Director's Notes / Sample
Context / Transcript / Audio Tags), flow-tuned pacing, pause_scale=0.5,
isolated cache namespace."
```

---

## Task 5: Verify pause scaling

**Files:**
- Create: `tests/enrichment/test_pause_scaling.py`

- [ ] **Step 1: Write the failing pause-scaling test**

```python
"""Tests for apply_turn_pauses under different profile pause_scale values."""
from __future__ import annotations

from pydub import AudioSegment

from enrichment.podcast_types import Turn, Utterance
from enrichment.render_audio import apply_turn_pauses


def _mk_turn(pause_before: int, pause_after: int) -> Turn:
    return Turn(
        speaker="Host",
        role="host",
        utterances=[
            Utterance(
                text="Speak.",
                sentence_type="intro",  # type: ignore[arg-type]
                quote_mode="none",
                rate=1.0,
                pause_before_ms=pause_before,
                pause_after_ms=pause_after,
                emphasis_words=[],
            )
        ],
    )


def test_pause_scale_one_matches_raw_pause_values() -> None:
    audio = AudioSegment.silent(duration=1000)
    turn = _mk_turn(pause_before=400, pause_after=900)
    result = apply_turn_pauses(audio, turn, pause_scale=1.0)
    # leading 400 + audio 1000 + trailing (900 - 300) = 400 + 1000 + 600 = 2000
    assert len(result) == 2000


def test_pause_scale_half_halves_leading_and_extra_trailing() -> None:
    audio = AudioSegment.silent(duration=1000)
    turn = _mk_turn(pause_before=400, pause_after=900)
    result = apply_turn_pauses(audio, turn, pause_scale=0.5)
    # leading 200 + audio 1000 + trailing (900 - 300) * 0.5 = 200 + 1000 + 300 = 1500
    assert len(result) == 1500


def test_pause_scale_zero_removes_all_added_silence() -> None:
    audio = AudioSegment.silent(duration=1000)
    turn = _mk_turn(pause_before=500, pause_after=2000)
    result = apply_turn_pauses(audio, turn, pause_scale=0.0)
    assert len(result) == 1000


def test_pause_after_at_or_below_300_adds_nothing() -> None:
    audio = AudioSegment.silent(duration=1000)
    turn = _mk_turn(pause_before=0, pause_after=300)
    result = apply_turn_pauses(audio, turn, pause_scale=1.0)
    assert len(result) == 1000
```

- [ ] **Step 2: Run tests to verify they fail or pass correctly**

```
uv run pytest tests/enrichment/test_pause_scaling.py -v
```
Expected: all PASS (the `apply_turn_pauses` function was already implemented in Task 3 with `pause_scale` as a parameter — this task confirms the contract).

- [ ] **Step 3: Commit**

```bash
git add tests/enrichment/test_pause_scaling.py
git commit -m "Test pause scaling under ClassicProfile (1.0) and TrevelyanV2Profile (0.5)"
```

---

## Task 6: Full-suite check, ruff sweep, integration smoke test

- [ ] **Step 1: Run all tests**

```
uv run pytest tests/ -v
```
Expected: all PASS — 4 test files in `tests/enrichment/` plus the existing `test_transport_podcast.py`.

- [ ] **Step 2: Run ruff over the whole repo**

```
uv run ruff check .
```
Expected: zero errors. If any pre-existing errors surface, fix them as part of this task (project policy: zero-tolerance for lingering ruff errors).

- [ ] **Step 3: Run pyright over the changed modules**

```
uv run pyright enrichment/render_audio.py enrichment/tts_profiles tests/enrichment
```
Expected: zero errors.

- [ ] **Step 4: Manual integration smoke test — render a single segment**

This step requires a live Gemini API call. It is manual; do not put it in CI.

```
uv run python -m enrichment.render_audio \
    --run ext_v19_all_swapped_hostprep \
    --profile trevelyan_v2 \
    --segment 0 \
    --concurrency 2
```

Expected: an MP3 is written to `/Volumes/Crucial X9/bleakhouse_audio/ext_v19_all_swapped_hostprep/podcast_trevelyan_v2_segment_0.mp3`. Listen to it. If it sounds wrong in a structural way (e.g. headers being read aloud, audio tags being read as literal words), open a follow-up issue — do not redesign in this branch.

- [ ] **Step 5: If smoke test is clean, render the full episode**

```
uv run python -m enrichment.render_audio \
    --run ext_v19_all_swapped_hostprep \
    --profile trevelyan_v2
```

Expected: `/Volumes/Crucial X9/bleakhouse_audio/ext_v19_all_swapped_hostprep/podcast_trevelyan_v2.mp3` exists. Note its duration and compare qualitatively to the existing `podcast.mp3` (classic) in the same directory.

- [ ] **Step 6: Commit any ruff fixes from Step 2 separately, then push**

```bash
git status
# If any files were modified by the ruff sweep:
git add <those files>
git commit -m "Resolve lingering ruff findings touched by tts_profiles work"
git push
```

---

## Self-review notes

**Spec coverage check** (against `docs/superpowers/specs/2026-04-17-tts-trevelyan-v2-experiment-design.md`):

| Spec item | Task |
|---|---|
| `TTSProfile` protocol + `EpisodeContext` | Task 1 |
| `ClassicProfile` preserves behaviour | Task 2 |
| `--profile` CLI flag, default `classic` | Task 3 |
| Cache namespaced per profile | Task 3 |
| Output suffix `_trevelyan_v2` | Task 3 |
| Pause scaling (`pause_scale=0.5`) | Task 3 (impl) + Task 5 (tests) |
| Inter-segment silence scaled | Task 3 |
| Model id `gemini-3.1-flash-tts-preview` | Task 4 |
| All six header sections | Task 4 |
| Host persona: ~80, northern English | Task 4 |
| Trevelyan persona: Uppingham + late 1950s | Task 4 |
| Sample Context verbatim quotation of previous turn | Task 4 |
| Audio tags: `[serious]` for reading, `[curious]` for setup | Task 4 |
| `[hesitantly]` removed | Task 4 |
| Emphasis → Director's Note, not inline tag | Task 4 |
| Style→phrase table for all 11 speakers' style ids | Task 4 |
| Unit tests for prompt, pause, cache isolation | Tasks 1, 2, 4, 5 |
| ruff / pyright / mypy clean | Task 6 |
| Manual smoke test on `ext_v19_all_swapped_hostprep` | Task 6 |

No gaps identified.

**Things explicitly deferred (per spec, not a plan gap):**
- Two-speaker `MultiSpeakerVoiceConfig` pairing for Host↔panellist turns.
- Auto-migrating the pre-refactor cache into the new per-profile directory (re-generation on demand is acceptable).
- Revising voice selection (prebuilt voice names).
- `mypy` is listed in the spec's acceptance. Task 6 runs `pyright`; also run `uv run mypy enrichment/tts_profiles` if the project keeps mypy green. If mypy is not in current CI-equivalent flow, pyright suffices for this work.
