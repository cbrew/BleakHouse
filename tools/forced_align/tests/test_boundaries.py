"""Tests for boundaries.py — midpoint-split shard boundaries from word
alignments + per-turn word ranges + mp3 duration."""
import pytest
from forced_align.boundaries import (
    AlignedWord,
    ShardBoundary,
    compute_boundaries,
)
from forced_align.transcript import TurnRange


def _aw(word, start, end, script_index=None):
    return AlignedWord(word=word, start_s=start, end_s=end, script_index=script_index)


def test_simple_three_turns():
    # 3 turns, 1 word each. Speech regions: [1,2], [3,4], [5,6].
    # Inter-turn silences at 2-3 and 4-5. mp3 ends at 7.
    words = [_aw("a", 1.0, 2.0), _aw("b", 3.0, 4.0), _aw("c", 5.0, 6.0)]
    ranges = [
        TurnRange(0, 0, 0, 0),
        TurnRange(0, 1, 1, 1),
        TurnRange(0, 2, 2, 2),
    ]
    boundaries = compute_boundaries(words, ranges, mp3_duration_s=7.0)
    # Shard 0: 0.0 → midpoint(2.0, 3.0) = 2.5
    # Shard 1: 2.5 → midpoint(4.0, 5.0) = 4.5
    # Shard 2: 4.5 → 7.0
    assert boundaries == [
        ShardBoundary(segment_index=0, turn_index=0, start_s=0.0, end_s=2.5),
        ShardBoundary(segment_index=0, turn_index=1, start_s=2.5, end_s=4.5),
        ShardBoundary(segment_index=0, turn_index=2, start_s=4.5, end_s=7.0),
    ]


def test_single_turn():
    """One turn → one shard spanning the whole mp3."""
    words = [_aw("hello", 0.5, 1.5)]
    ranges = [TurnRange(0, 0, 0, 0)]
    boundaries = compute_boundaries(words, ranges, mp3_duration_s=2.0)
    assert boundaries == [ShardBoundary(0, 0, 0.0, 2.0)]


def test_zero_silence_between_turns():
    """When the next turn's first word starts at the previous turn's
    last word's end (no silence), the midpoint is the boundary itself."""
    words = [_aw("a", 0.0, 1.0), _aw("b", 1.0, 2.0)]
    ranges = [TurnRange(0, 0, 0, 0), TurnRange(0, 1, 1, 1)]
    boundaries = compute_boundaries(words, ranges, mp3_duration_s=2.0)
    assert boundaries == [
        ShardBoundary(0, 0, 0.0, 1.0),
        ShardBoundary(0, 1, 1.0, 2.0),
    ]


def test_multi_word_turns():
    """Turn 0: words 0..2 (3 words). Turn 1: words 3..4 (2 words)."""
    words = [
        _aw("hello", 0.0, 0.3),
        _aw("there", 0.3, 0.7),
        _aw("friend.", 0.7, 1.2),
        _aw("Yes,", 2.0, 2.3),
        _aw("indeed.", 2.3, 2.8),
    ]
    ranges = [TurnRange(0, 0, 0, 2), TurnRange(0, 1, 3, 4)]
    boundaries = compute_boundaries(words, ranges, mp3_duration_s=3.0)
    # Shard 0: 0.0 → midpoint(1.2, 2.0) = 1.6
    # Shard 1: 1.6 → 3.0
    assert boundaries == [
        ShardBoundary(0, 0, 0.0, 1.6),
        ShardBoundary(0, 1, 1.6, 3.0),
    ]


def test_empty_turn_inherits_zero_width_at_neighbour_boundary():
    """An empty turn (last_word == -1) gets a zero-width shard at the
    boundary between its neighbours. Avoids losing the turn entry but
    also doesn't claim any audio."""
    words = [_aw("a", 0.0, 1.0), _aw("b", 3.0, 4.0)]
    ranges = [
        TurnRange(0, 0, 0, 0),
        TurnRange(0, 1, 0, -1),   # empty
        TurnRange(0, 2, 1, 1),
    ]
    boundaries = compute_boundaries(words, ranges, mp3_duration_s=5.0)
    # Boundary between turn 0 and turn 2: midpoint(1.0, 3.0) = 2.0
    # Empty turn 1 gets zero-width shard at 2.0
    assert boundaries == [
        ShardBoundary(0, 0, 0.0, 2.0),
        ShardBoundary(0, 1, 2.0, 2.0),
        ShardBoundary(0, 2, 2.0, 5.0),
    ]


def test_alignment_misses_some_words():
    """If WhisperX failed to align some script words, we use the first
    and last *aligned* word inside that turn's range. As long as at
    least one word per turn aligned, boundaries are computable. The
    AlignedWord.script_index field tells us which script word each
    aligned entry corresponds to."""
    words_with_index = [
        AlignedWord(word="hello", start_s=0.0, end_s=0.5, script_index=0),
        AlignedWord(word="friend.", start_s=1.0, end_s=1.5, script_index=3),
        AlignedWord(word="yes.", start_s=2.5, end_s=3.0, script_index=4),
    ]
    ranges = [TurnRange(0, 0, 0, 3), TurnRange(0, 1, 4, 4)]
    boundaries = compute_boundaries(words_with_index, ranges, mp3_duration_s=4.0)
    # Turn 0 speech: from word 0 (start 0.0) to word 3 (end 1.5)
    # Turn 1 speech: from word 4 (start 2.5) to word 4 (end 3.0)
    # Boundary: midpoint(1.5, 2.5) = 2.0
    assert boundaries == [
        ShardBoundary(0, 0, 0.0, 2.0),
        ShardBoundary(0, 1, 2.0, 4.0),
    ]


def test_unaligned_turn_raises():
    """If a non-empty turn has zero aligned words, that's a hard
    failure — caller should catch and decide policy."""
    words = [_aw("a", 0.0, 1.0)]
    ranges = [TurnRange(0, 0, 0, 0), TurnRange(0, 1, 1, 5)]   # turn 1 unaligned
    with pytest.raises(ValueError, match="no aligned words"):
        compute_boundaries(words, ranges, mp3_duration_s=5.0)
