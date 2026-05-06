"""Parse phase3_episode.json into a flat word list + per-turn ranges.

The flat word list is what we hand to WhisperX in force-align mode;
the per-turn ranges let us project word-level timestamps back to the
script's turn structure.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TurnRange:
    """Inclusive [first_word, last_word] indices into the flat word list.
    last_word == -1 signals an empty turn (no utterances)."""
    segment_index: int
    turn_index: int
    first_word: int
    last_word: int


def parse_episode(episode: dict) -> tuple[list[str], list[TurnRange]]:
    """Flatten an episode dict into (words, turn_ranges).

    Words are split on whitespace from each utterance.text, joined in
    script order across all segments and turns. The turn_ranges list
    has one entry per turn, recording where that turn's words live in
    the flat list. Empty turns get last_word = -1.
    """
    words: list[str] = []
    turn_ranges: list[TurnRange] = []
    for seg_idx, segment in enumerate(episode.get("segments", [])):
        for turn_idx, turn in enumerate(segment.get("turns", [])):
            first = len(words)
            for utterance in turn.get("utterances", []):
                text = utterance.get("text", "")
                words.extend(text.split())
            last = len(words) - 1
            turn_ranges.append(TurnRange(
                segment_index=seg_idx,
                turn_index=turn_idx,
                first_word=first,
                last_word=last if last >= first else -1,
            ))
    return words, turn_ranges
