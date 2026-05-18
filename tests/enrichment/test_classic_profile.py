"""Tests for ClassicProfile — guards current rendering behaviour."""
from __future__ import annotations

from enrichment.llm.schemas import (
    SentenceType,
    Turn,
    Utterance,
)
from enrichment.tts_profiles import EpisodeContext, get_profile


def _mk_turn(speaker: str = "Host") -> Turn:
    return Turn(
        speaker=speaker,
        role="host",
        utterances=[
            Utterance(
                text="Welcome to the programme.",
                sentence_type=SentenceType.intro,
                quote_mode="none",
                rate=1.0,
                pause_before_ms=0,
                pause_after_ms=300,
                emphasis_words=[],
            ),
            Utterance(
                text="Let me read a passage.",
                sentence_type=SentenceType.quote_setup,
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
