"""Tests for apply_turn_pauses under different profile pause_scale values."""
from __future__ import annotations

from pydub import AudioSegment

from enrichment.llm.schemas import (
    SentenceType,
    Turn,
    Utterance,
)
from enrichment.render_audio import apply_turn_pauses


def _mk_turn(pause_before: int, pause_after: int) -> Turn:
    return Turn(
        speaker="Host",
        role="host",
        utterances=[
            Utterance(
                text="Speak.",
                sentence_type=SentenceType.intro,
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
