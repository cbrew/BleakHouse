"""Tests for transcript.py — extract a flat word list with per-turn ranges
from phase3_episode.json."""
from forced_align.transcript import parse_episode, TurnRange


def test_simple_episode():
    episode = {
        "title": "Test",
        "experts": [{"name": "Eleanor Hartley", "role": "expert"}],
        "segments": [
            {"title": "Opening", "turns": [
                {"speaker": "Host", "role": "host",
                 "utterances": [{"text": "Hello world."}]},
                {"speaker": "Eleanor Hartley", "role": "expert",
                 "utterances": [{"text": "Yes indeed."}]},
            ]},
        ],
    }
    words, turn_ranges = parse_episode(episode)
    assert words == ["Hello", "world.", "Yes", "indeed."]
    assert turn_ranges == [
        TurnRange(segment_index=0, turn_index=0, first_word=0, last_word=1),
        TurnRange(segment_index=0, turn_index=1, first_word=2, last_word=3),
    ]


def test_multiple_segments_and_utterances():
    episode = {
        "title": "Test",
        "experts": [],
        "segments": [
            {"title": "S1", "turns": [
                {"speaker": "A", "role": "host",
                 "utterances": [{"text": "One two."}, {"text": "Three."}]},
            ]},
            {"title": "S2", "turns": [
                {"speaker": "B", "role": "expert",
                 "utterances": [{"text": "Four five six."}]},
            ]},
        ],
    }
    words, turn_ranges = parse_episode(episode)
    assert words == ["One", "two.", "Three.", "Four", "five", "six."]
    assert turn_ranges == [
        TurnRange(segment_index=0, turn_index=0, first_word=0, last_word=2),
        TurnRange(segment_index=1, turn_index=0, first_word=3, last_word=5),
    ]


def test_empty_turn_skipped():
    """A turn with empty utterances is allowed (host filler) — gets a
    zero-width range so it's still tracked but consumes no words."""
    episode = {
        "title": "Test",
        "experts": [],
        "segments": [
            {"title": "S", "turns": [
                {"speaker": "A", "role": "host", "utterances": []},
                {"speaker": "B", "role": "expert",
                 "utterances": [{"text": "Hi."}]},
            ]},
        ],
    }
    words, turn_ranges = parse_episode(episode)
    assert words == ["Hi."]
    assert turn_ranges[0].first_word == 0
    assert turn_ranges[0].last_word == -1
    assert turn_ranges[1].first_word == 0
    assert turn_ranges[1].last_word == 0
