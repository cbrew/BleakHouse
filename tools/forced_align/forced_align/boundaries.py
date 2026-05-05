"""Compute per-turn shard boundaries from word-level alignment.

Slicing rule (per design spec): midpoint-split. Shard N covers
[midpoint(prev_speech_end, this_speech_start),
 midpoint(this_speech_end, next_speech_start)],
clamped at the mp3 boundaries (0 for first, mp3_duration for last).

This module is pure logic — no I/O, no audio. Fully unit-tested.
"""
from __future__ import annotations

from dataclasses import dataclass

from forced_align.transcript import TurnRange


@dataclass(frozen=True)
class AlignedWord:
    """One word with its aligned start/end times (seconds).

    script_index: which word index in the script's flat word list this
    aligned word corresponds to. Defaults to None when the alignment
    output is one-to-one with the script — e.g. simple unit tests where
    every script word aligned. When some script words were dropped by
    WhisperX, callers must populate script_index so per-turn lookup
    finds the right speech regions.
    """
    word: str
    start_s: float
    end_s: float
    script_index: int | None = None


@dataclass(frozen=True)
class ShardBoundary:
    """A turn's shard occupies [start_s, end_s] in the source mp3."""
    segment_index: int
    turn_index: int
    start_s: float
    end_s: float


def _turn_speech_region(
    aligned: list[AlignedWord], turn: TurnRange
) -> tuple[float, float] | None:
    """Find this turn's first/last aligned word and return its (start, end).

    Returns None if the turn is empty (last_word == -1) or no aligned
    word fell within its script-index range.
    """
    if turn.last_word < turn.first_word:
        return None
    matching: list[tuple[int, AlignedWord]] = []
    for i, aw in enumerate(aligned):
        idx = aw.script_index if aw.script_index is not None else i
        if turn.first_word <= idx <= turn.last_word:
            matching.append((idx, aw))
    if not matching:
        return None
    matching.sort(key=lambda p: p[0])
    return (matching[0][1].start_s, matching[-1][1].end_s)


def compute_boundaries(
    aligned: list[AlignedWord],
    turn_ranges: list[TurnRange],
    mp3_duration_s: float,
) -> list[ShardBoundary]:
    """Midpoint-split shard boundaries for one episode.

    Raises ValueError if a non-empty turn has no aligned words.
    """
    speech_regions: list[tuple[float, float] | None] = []
    for turn in turn_ranges:
        region = _turn_speech_region(aligned, turn)
        if region is None and turn.last_word >= turn.first_word:
            raise ValueError(
                f"no aligned words for turn (seg={turn.segment_index} "
                f"idx={turn.turn_index}, script-words "
                f"{turn.first_word}..{turn.last_word})"
            )
        speech_regions.append(region)

    boundaries: list[ShardBoundary] = []
    for i, turn in enumerate(turn_ranges):
        prev_end: float | None = None
        for j in range(i - 1, -1, -1):
            region = speech_regions[j]
            if region is not None:
                prev_end = region[1]
                break
        next_start: float | None = None
        for j in range(i + 1, len(turn_ranges)):
            region = speech_regions[j]
            if region is not None:
                next_start = region[0]
                break
        this = speech_regions[i]

        if this is None:
            if prev_end is not None and next_start is not None:
                point = (prev_end + next_start) / 2
            elif prev_end is not None:
                point = prev_end
            elif next_start is not None:
                point = next_start
            else:
                point = 0.0
            start_s = end_s = point
        else:
            start_s = (prev_end + this[0]) / 2 if prev_end is not None else 0.0
            end_s = (this[1] + next_start) / 2 if next_start is not None else mp3_duration_s

        boundaries.append(ShardBoundary(
            segment_index=turn.segment_index,
            turn_index=turn.turn_index,
            start_s=start_s,
            end_s=end_s,
        ))
    return boundaries
