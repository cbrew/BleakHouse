"""Byte-identical parity between render_audio's legacy build_turn_prompt
and ClassicProfile.build_turn_prompt, guarding the Task 3 deletion.

This file is DELETED in Task 3 once the legacy symbol is removed.
"""
from __future__ import annotations

import pytest

from enrichment.podcast_types import SentenceType, Turn, Utterance
from enrichment.render_audio import build_turn_prompt as legacy_build_turn_prompt
from enrichment.tts_profiles import EpisodeContext, get_profile


def _ctx() -> EpisodeContext:
    return EpisodeContext(
        episode_title="Bleak House",
        segment_title="Opening",
        segment_index=0,
        turn_index=0,
        previous_turn=None,
    )


def _turn(
    speaker: str,
    texts: list[tuple[str, str, float, int, list[str]]],
) -> Turn:
    """Build a Turn from (text, quote_mode, rate, pause_before_ms, emphasis_words) tuples."""
    mode_to_sentence_type = {
        "none": SentenceType.analysis,
        "setup": SentenceType.quote_setup,
        "reading": SentenceType.quote_reading,
        "commentary": SentenceType.analysis,
    }
    return Turn(
        speaker=speaker,
        role="host" if speaker == "Host" else "guest",
        utterances=[
            Utterance(
                text=t,
                sentence_type=mode_to_sentence_type[qm],
                quote_mode=qm,  # type: ignore[arg-type]
                rate=rate,
                pause_before_ms=pause_before,
                pause_after_ms=300,
                emphasis_words=emph,
            )
            for (t, qm, rate, pause_before, emph) in texts
        ],
    )


PARITY_CASES = [
    pytest.param(
        _turn(
            "Host",
            [
                ("Welcome to the programme.", "none", 1.0, 0, []),
                ("Let me read a passage.", "setup", 1.0, 200, ["passage"]),
            ],
        ),
        id="host-setup-with-emphasis",
    ),
    pytest.param(
        _turn(
            "Oliver Trevelyan",
            [
                ("'Fog everywhere.'", "reading", 0.92, 400, []),
                ("A marvellous opening.", "commentary", 1.05, 0, []),
            ],
        ),
        id="trevelyan-quote-reading-then-commentary",
    ),
    pytest.param(
        _turn(
            "Edmund Leigh",
            [
                ("A measured observation.", "none", 1.0, 0, ["observation"]),
            ],
        ),
        id="leigh-single-utterance-with-emphasis",
    ),
    pytest.param(
        _turn(
            "Unknown Guest",
            [("Who am I?", "none", 1.0, 0, [])],
        ),
        id="unknown-speaker-fallback",
    ),
    pytest.param(
        _turn(
            "Daniel Rosen",
            [
                ("Slow rate boundary.", "none", 0.93, 0, []),
                ("Fast rate boundary.", "none", 1.05, 0, []),
            ],
        ),
        id="rate-direction-boundaries",
    ),
]


@pytest.mark.parametrize("turn", PARITY_CASES)
def test_classic_profile_matches_legacy_build_turn_prompt(turn: Turn) -> None:
    legacy = legacy_build_turn_prompt(turn)
    classic = get_profile("classic").build_turn_prompt(turn, _ctx())
    assert classic == legacy
