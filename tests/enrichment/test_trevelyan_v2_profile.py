"""Tests for TrevelyanV2Profile — the experimental 3.1 profile."""
from __future__ import annotations

import pytest

from enrichment.llm.schemas import (
    SentenceType,
    Turn,
    Utterance,
)
from enrichment.tts_profiles import EpisodeContext, get_profile


def _mk_utterance(
    text: str = "Hello.",
    quote_mode: str = "none",
    rate: float = 1.0,
    pause_before_ms: int = 0,
    pause_after_ms: int = 300,
    emphasis_words: list[str] | None = None,
    sentence_type: SentenceType = SentenceType.analysis,
) -> Utterance:
    return Utterance(
        text=text,
        sentence_type=sentence_type,
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
        [_mk_utterance("'Fog everywhere.'", quote_mode="reading", sentence_type=SentenceType.quote_reading)],
    )
    prompt = profile.build_turn_prompt(turn, _ctx())
    assert "[serious] 'Fog everywhere.'" in prompt
    assert "direct literary quotation" in prompt.lower()


def test_quote_setup_gets_curious_tag(profile) -> None:
    turn = _mk_turn(
        "Oliver Trevelyan",
        [_mk_utterance("Listen to this:", quote_mode="setup", sentence_type=SentenceType.quote_setup)],
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


def test_host_accent_line_points_to_audio_profile(profile) -> None:
    turn = _mk_turn("Host")
    prompt = profile.build_turn_prompt(turn, _ctx())
    assert "Accent: as described in the Audio Profile." in prompt
    # Classic's Host accent string must NOT leak in via _accent_for:
    assert "warm Home Counties accent" not in prompt


def test_leigh_accent_line_uses_classic_accent_string(profile) -> None:
    """Non-Host / non-Trevelyan speakers still get the classic accent string."""
    turn = _mk_turn("Edmund Leigh")
    prompt = profile.build_turn_prompt(turn, _ctx())
    assert "Accent: speaks with a patrician Oxford accent" in prompt
