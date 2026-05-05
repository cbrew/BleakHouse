# Forced-Alignment Shard Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Beads issues track each task — claim with `bd update <id> --claim`, close with `bd close <id>`.

**Goal:** Migrate the 32 legacy `podcast.mp3` audio runs to the per-turn shards format used by `room_with_a_view`, fixing click-to-jump alignment by forced-aligning each rendered mp3 against its script.

**Architecture:** Self-contained tool at `tools/forced_align/` with its own uv project (heavy WhisperX/torch deps stay out of main). Pipeline: parse `phase3_episode.json` → WhisperX force-align against `podcast.mp3` → midpoint-split shard boundaries → ffmpeg `-c copy` slice → write `shards.json` + audio-measured `audio/manifest.json` matching the rwv schema. Webapp picks up shards mode automatically via existing `loadRun` logic; no webapp changes.

**Tech Stack:** Python 3.12, uv (separate project), WhisperX (faster-whisper backend), ffmpeg (subprocess), pydub (only for tests, not runtime). Lives on the `feature/forced-alignment-shards` branch and is never deployed to Fly.

**Spec:** `docs/superpowers/specs/2026-05-05-forced-alignment-shards-design.md`

---

## File Structure

Files to create (all under `tools/forced_align/` unless noted):

| Path | Responsibility |
|---|---|
| `pyproject.toml` | Separate uv project; declares whisperx + ffmpeg-python + pytest |
| `forced_align/__init__.py` | Empty package marker |
| `forced_align/transcript.py` | Parse `phase3_episode.json` → flat word list + per-turn word ranges |
| `forced_align/align.py` | WhisperX wrapper (force-align provided transcript to mp3) |
| `forced_align/boundaries.py` | Pure logic: alignment + word ranges + duration → shard boundaries |
| `forced_align/slicer.py` | ffmpeg subprocess wrapper for mp3 slicing (`-c copy`) |
| `forced_align/manifest.py` | Emit `shards.json` and audio-measured `audio/manifest.json` |
| `forced_align/__main__.py` | CLI: `--run <id>`, `--all`, `--force` |
| `tests/test_transcript.py` | Unit tests for transcript.py |
| `tests/test_boundaries.py` | Unit tests for boundaries.py (the pure-logic core) |
| `tests/test_slicer.py` | Integration test: slice a tiny synthetic mp3 |
| `tests/test_manifest.py` | Unit tests for manifest writers |
| `tests/test_cli.py` | Integration test: end-to-end CLI on synthetic fixture |
| `tests/fixtures/build_fixture.py` | One-shot: builds the 3-turn synthetic mp3 used by integration tests |
| `tests/fixtures/synthetic_3turn.mp3` | Generated fixture (committed) |
| `tests/fixtures/synthetic_3turn.json` | Generated fixture transcript (committed) |

---

## Task 1: Project skeleton + separate uv venv

**Beads:** create one issue for this task, claim it, work the steps below, close.

**Files:**
- Create: `tools/forced_align/pyproject.toml`
- Create: `tools/forced_align/forced_align/__init__.py`
- Create: `tools/forced_align/forced_align/__main__.py`
- Create: `tools/forced_align/.python-version`
- Create: `tools/forced_align/README.md`

- [ ] **Step 1: Create the directory and pyproject**

```bash
mkdir -p tools/forced_align/forced_align
mkdir -p tools/forced_align/tests/fixtures
echo "3.12" > tools/forced_align/.python-version
```

`tools/forced_align/pyproject.toml`:

```toml
[project]
name = "forced-align"
version = "0.1.0"
description = "Forced-alignment migration: legacy podcast.mp3 runs → per-turn shards. Never deployed to Fly."
requires-python = ">=3.12"
dependencies = [
    "whisperx>=3.1.0",
    "torch>=2.1.0",
    "torchaudio>=2.1.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pydub>=0.25",  # only for building the synthetic test fixture
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`tools/forced_align/forced_align/__init__.py`:

```python
"""Forced-alignment migration tool. See docs/superpowers/specs/2026-05-05-forced-alignment-shards-design.md."""
```

`tools/forced_align/forced_align/__main__.py`:

```python
"""CLI entry point. Real implementation lands in Task 7."""
import sys

def main() -> int:
    print("forced-align tool — see --help (not implemented yet)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

`tools/forced_align/README.md`:

````markdown
# forced_align

One-shot migration tool: cuts legacy `podcast.mp3` runs into per-turn shards by forced-aligning the rendered audio against the script in `phase3_episode.json`. See `docs/superpowers/specs/2026-05-05-forced-alignment-shards-design.md`.

## Setup

Has its own venv (heavy torch deps; never deployed to Fly):

```bash
cd tools/forced_align
uv sync --all-extras
```

## Usage

```bash
uv run -m forced_align --run bh_trn_literary_hostprep
uv run -m forced_align --all
uv run -m forced_align --run X --force   # overwrite existing shards
```
````

- [ ] **Step 2: Bootstrap the separate venv and sanity-check**

```bash
cd tools/forced_align && uv sync --all-extras 2>&1 | tail -10
```

Expected: completes with no errors. Initial sync downloads ~2GB of torch wheels. WhisperX may pull a CUDA-tagged torch on Linux; on macOS/MPS it picks the right backend automatically.

- [ ] **Step 3: Run the stub**

```bash
cd tools/forced_align && uv run -m forced_align
```

Expected output: `forced-align tool — see --help (not implemented yet)`

- [ ] **Step 4: Add to .gitignore**

Append to root `.gitignore`:
```
# forced_align tool's separate venv (do not deploy to Fly)
tools/forced_align/.venv/
tools/forced_align/uv.lock
```

We don't commit `uv.lock` for this tool because the torch ABI varies by host and lock pinning would constantly drift. The version constraints in `pyproject.toml` are what we standardise on.

- [ ] **Step 5: Commit**

```bash
git add tools/forced_align/ .gitignore
git commit -m "forced_align: project skeleton + separate venv (Task 1)"
```

---

## Task 2: Transcript parser

**Files:**
- Create: `tools/forced_align/forced_align/transcript.py`
- Create: `tools/forced_align/tests/test_transcript.py`

- [ ] **Step 1: Write the failing test**

`tools/forced_align/tests/test_transcript.py`:

```python
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
    assert turn_ranges[0].last_word == -1   # signals empty
    assert turn_ranges[1].first_word == 0
    assert turn_ranges[1].last_word == 0
```

- [ ] **Step 2: Run the test to confirm failure**

```bash
cd tools/forced_align && uv run pytest tests/test_transcript.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'forced_align.transcript'`.

- [ ] **Step 3: Implement transcript.py**

`tools/forced_align/forced_align/transcript.py`:

```python
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
```

- [ ] **Step 4: Run the test to confirm pass**

```bash
cd tools/forced_align && uv run pytest tests/test_transcript.py -v
```
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tools/forced_align/forced_align/transcript.py tools/forced_align/tests/test_transcript.py
git commit -m "forced_align: transcript parser (Task 2)"
```

---

## Task 3: Boundary computation (the pure-logic core)

**Files:**
- Create: `tools/forced_align/forced_align/boundaries.py`
- Create: `tools/forced_align/tests/test_boundaries.py`

This is the most carefully-tested module: it's pure logic, easy to cover exhaustively, and a wrong boundary computation breaks every shard.

- [ ] **Step 1: Write the failing tests**

`tools/forced_align/tests/test_boundaries.py`:

```python
"""Tests for boundaries.py — midpoint-split shard boundaries from word
alignments + per-turn word ranges + mp3 duration."""
import pytest
from forced_align.boundaries import (
    AlignedWord,
    ShardBoundary,
    compute_boundaries,
)
from forced_align.transcript import TurnRange


def _aw(word, start, end):
    return AlignedWord(word=word, start_s=start, end_s=end)


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
    # Shard 2: 4.5 → 7.0 (last turn extends to mp3 end)
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
    """If WhisperX failed to align some words inside a turn, we use the
    first/last *aligned* word in that turn's range. As long as at least
    one word per turn aligned, boundaries are computable."""
    # Turn 0 has words 0..3 in the script, but WhisperX only aligned 0 and 3.
    words = [
        _aw("hello", 0.0, 0.5),     # script word 0
        # script words 1, 2 didn't align — not in the list
        _aw("friend.", 1.0, 1.5),    # script word 3
        _aw("yes.", 2.5, 3.0),       # script word 4
    ]
    # Map: AlignedWord.script_index tells us which script word it was.
    # We need the original_index field for this — see implementation.
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
```

- [ ] **Step 2: Run the tests to confirm failure**

```bash
cd tools/forced_align && uv run pytest tests/test_boundaries.py -v
```
Expected: ImportError on `forced_align.boundaries`.

- [ ] **Step 3: Implement boundaries.py**

`tools/forced_align/forced_align/boundaries.py`:

```python
"""Compute per-turn shard boundaries from word-level alignment.

Slicing rule (per design spec): midpoint-split. Shard N covers
[midpoint(prev_speech_end, this_speech_start),
 midpoint(this_speech_end, next_speech_start)],
clamped at the mp3 boundaries (0 for first, mp3_duration for last).

This module is pure logic — no I/O, no audio. Fully unit-tested.
"""
from __future__ import annotations

from dataclasses import dataclass, field

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
        return None  # empty turn
    # Build script_index lookup: if alignment provided script_index, use it;
    # else assume one-to-one (i-th aligned word == i-th script word).
    matching = []
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
    # First pass: compute speech regions per turn (or None for empty turns).
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

    # Second pass: midpoint boundaries between consecutive non-empty turns.
    boundaries: list[ShardBoundary] = []
    for i, turn in enumerate(turn_ranges):
        # Find the previous non-empty turn's speech end (or 0.0 if first).
        prev_end: float | None = None
        for j in range(i - 1, -1, -1):
            if speech_regions[j] is not None:
                prev_end = speech_regions[j][1]
                break
        # Find the next non-empty turn's speech start (or mp3 end if last).
        next_start: float | None = None
        for j in range(i + 1, len(turn_ranges)):
            if speech_regions[j] is not None:
                next_start = speech_regions[j][0]
                break
        # This turn's own speech (or None for empty).
        this = speech_regions[i]

        if this is None:
            # Empty turn → zero-width shard at the boundary between
            # previous and next non-empty turns.
            point = (
                (prev_end + next_start) / 2 if prev_end is not None and next_start is not None
                else (prev_end if prev_end is not None
                      else (next_start if next_start is not None else 0.0))
            )
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
```

- [ ] **Step 4: Run the tests to confirm pass**

```bash
cd tools/forced_align && uv run pytest tests/test_boundaries.py -v
```
Expected: 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add tools/forced_align/forced_align/boundaries.py tools/forced_align/tests/test_boundaries.py
git commit -m "forced_align: midpoint-split boundary computation (Task 3)"
```

---

## Task 4: mp3 slicer (ffmpeg subprocess)

**Files:**
- Create: `tools/forced_align/forced_align/slicer.py`
- Create: `tools/forced_align/tests/fixtures/build_fixture.py`
- Create: `tools/forced_align/tests/fixtures/synthetic_3turn.mp3`
- Create: `tools/forced_align/tests/test_slicer.py`

- [ ] **Step 1: Build the test fixture (one-shot script)**

`tools/forced_align/tests/fixtures/build_fixture.py`:

```python
"""One-shot: build a 3-turn synthetic mp3 fixture for slicer tests.

Generates 3 short tones at distinct frequencies + silence between
them, encoded as mp3. Run once; commit the output mp3.
"""
from pathlib import Path

from pydub import AudioSegment
from pydub.generators import Sine


def build() -> Path:
    sr = 44100
    silence = AudioSegment.silent(duration=500)  # 0.5s
    tone_a = Sine(440).to_audio_segment(duration=1500)   # 1.5s @ 440Hz
    tone_b = Sine(660).to_audio_segment(duration=1500)   # 1.5s @ 660Hz
    tone_c = Sine(880).to_audio_segment(duration=1500)   # 1.5s @ 880Hz
    audio = (
        silence + tone_a + silence
        + tone_b + silence
        + tone_c + silence
    )
    out = Path(__file__).parent / "synthetic_3turn.mp3"
    audio.export(str(out), format="mp3", bitrate="128k")
    return out


if __name__ == "__main__":
    p = build()
    print(f"wrote {p} ({p.stat().st_size} bytes)")
```

```bash
cd tools/forced_align && uv run python tests/fixtures/build_fixture.py
```
Expected: prints `wrote .../synthetic_3turn.mp3 (NN bytes)`.

- [ ] **Step 2: Write the failing test**

`tools/forced_align/tests/test_slicer.py`:

```python
"""Integration test: slice the synthetic 3-turn fixture and check the
output files exist + are within tolerance of the requested durations."""
import subprocess
from pathlib import Path

import pytest
from forced_align.slicer import slice_mp3

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_3turn.mp3"


def _ffprobe_duration(path: Path) -> float:
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(path),
    ]).decode().strip()
    return float(out)


def test_slice_three_segments(tmp_path: Path):
    """Boundaries pulled from build_fixture: silence-tone-silence-tone-...
    Tone A at [0.5, 2.0]; tone B at [2.5, 4.0]; tone C at [4.5, 6.0]; tail [6.0, 6.5].
    Midpoint shards: [0, 2.25), [2.25, 4.25), [4.25, 6.5]."""
    boundaries = [
        (0.0, 2.25, "0000.mp3"),
        (2.25, 4.25, "0001.mp3"),
        (4.25, 6.5, "0002.mp3"),
    ]
    out_dir = tmp_path / "shards"
    out_dir.mkdir()
    for start, end, fname in boundaries:
        slice_mp3(FIXTURE, out_dir / fname, start_s=start, end_s=end)
    # Each output file exists and has roughly the expected duration.
    files = sorted(out_dir.glob("*.mp3"))
    assert [f.name for f in files] == ["0000.mp3", "0001.mp3", "0002.mp3"]
    durations = [_ffprobe_duration(f) for f in files]
    assert durations[0] == pytest.approx(2.25, abs=0.05)
    assert durations[1] == pytest.approx(2.0, abs=0.05)
    assert durations[2] == pytest.approx(2.25, abs=0.05)
```

```bash
cd tools/forced_align && uv run pytest tests/test_slicer.py -v
```
Expected: ImportError for `forced_align.slicer`.

- [ ] **Step 3: Implement slicer.py**

`tools/forced_align/forced_align/slicer.py`:

```python
"""Slice an mp3 with ffmpeg's stream-copy mode — no re-encode.

Stream-copy is fast (no audio decoding) and bit-identical for the
copied range, which is what we want for a migration: the audio bytes
that listeners hear must not change.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


class SliceError(RuntimeError):
    pass


def slice_mp3(
    source: Path,
    destination: Path,
    *,
    start_s: float,
    end_s: float,
) -> None:
    """Cut [start_s, end_s] from source mp3 into destination.

    Uses ffmpeg `-c copy` (stream copy). `-avoid_negative_ts make_zero`
    rewrites timestamps so the output starts at 0. Overwrites
    destination if it exists. Raises SliceError on ffmpeg non-zero exit.
    """
    if end_s <= start_s:
        raise SliceError(
            f"slice has non-positive duration: start={start_s} end={end_s}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-loglevel", "error",
        "-ss", f"{start_s:.3f}",
        "-to", f"{end_s:.3f}",
        "-i", str(source),
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        str(destination),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SliceError(
            f"ffmpeg failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )
```

- [ ] **Step 4: Run the test to confirm pass**

```bash
cd tools/forced_align && uv run pytest tests/test_slicer.py -v
```
Expected: 1 test passes. Tolerance is 50ms because mp3 stream-copy snaps to frame boundaries (~26ms at 128k mono).

- [ ] **Step 5: Commit**

```bash
git add tools/forced_align/forced_align/slicer.py tools/forced_align/tests/fixtures/ tools/forced_align/tests/test_slicer.py
git commit -m "forced_align: ffmpeg stream-copy slicer (Task 4)"
```

---

## Task 5: Manifest writers (shards.json + audio/manifest.json)

**Files:**
- Create: `tools/forced_align/forced_align/manifest.py`
- Create: `tools/forced_align/tests/test_manifest.py`

- [ ] **Step 1: Write the failing tests**

`tools/forced_align/tests/test_manifest.py`:

```python
"""Tests for manifest.py — emit shards.json (matches rwv schema) and
audio/manifest.json (audio-measured per-turn timing)."""
import hashlib
import json
from pathlib import Path

from forced_align.boundaries import ShardBoundary
from forced_align.manifest import write_manifests


def _make_shard_files(tmp_path: Path, count: int) -> list[Path]:
    """Stand-in for real mp3 files: known bytes for stable md5 in tests."""
    out = []
    for i in range(count):
        p = tmp_path / "shards" / "classic" / f"{i:04d}.mp3"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(f"shard-{i}".encode())
        out.append(p)
    return out


def test_writes_both_manifests(tmp_path: Path):
    audio_dir = tmp_path
    _make_shard_files(audio_dir, 2)
    episode = {
        "title": "Bleak House Unpacked",
        "experts": [{"name": "Eleanor Hartley", "role": "expert"}],
        "segments": [
            {"title": "Opening", "segment_type": "opening", "turns": [
                {"speaker": "Host", "role": "host",
                 "utterances": [{"text": "Welcome.",
                                 "sentence_type": "intro",
                                 "is_quote": False,
                                 "quote_mode": None,
                                 "passage_ref": None}]},
                {"speaker": "Eleanor Hartley", "role": "expert",
                 "utterances": [{"text": "Hello.",
                                 "sentence_type": "default",
                                 "is_quote": False,
                                 "quote_mode": None,
                                 "passage_ref": None}]},
            ]},
        ],
    }
    boundaries = [
        ShardBoundary(0, 0, 0.0, 2.5),
        ShardBoundary(0, 1, 2.5, 5.0),
    ]
    write_manifests(audio_dir=audio_dir, episode=episode,
                    boundaries=boundaries, profile="classic")

    shards = json.loads((audio_dir / "shards.json").read_text())
    assert shards["schema_version"] == 1
    assert shards["profile"] == "classic"
    assert shards["episode_title"] == "Bleak House Unpacked"
    assert shards["experts"] == [{"name": "Eleanor Hartley", "role": "expert"}]
    assert len(shards["shards"]) == 2
    assert shards["shards"][0]["file"] == "0000.mp3"
    assert shards["shards"][0]["kind"] == "turn"
    assert shards["shards"][0]["segment_index"] == 0
    assert shards["shards"][0]["turn_index"] == 0
    assert shards["shards"][0]["speaker"] == "Host"
    assert shards["shards"][0]["role"] == "host"
    assert shards["shards"][0]["utterances"] == [{
        "text": "Welcome.", "sentence_type": "intro",
        "is_quote": False, "quote_mode": None, "passage_ref": None,
    }]
    # md5 of the mp3 bytes
    expected_md5 = hashlib.md5(b"shard-0").hexdigest()
    assert shards["shards"][0]["md5"] == expected_md5

    audio_manifest = json.loads((audio_dir / "manifest.json").read_text())
    assert audio_manifest["title"] == "Bleak House Unpacked"
    assert audio_manifest["total_duration_ms"] == 5000
    assert len(audio_manifest["segments"]) == 1
    seg0 = audio_manifest["segments"][0]
    assert seg0["start_ms"] == 0
    assert seg0["turns"][0]["start_ms"] == 0
    assert seg0["turns"][0]["end_ms"] == 2500
    assert seg0["turns"][1]["start_ms"] == 2500
    assert seg0["turns"][1]["end_ms"] == 5000
```

```bash
cd tools/forced_align && uv run pytest tests/test_manifest.py -v
```
Expected: ImportError.

- [ ] **Step 2: Implement manifest.py**

`tools/forced_align/forced_align/manifest.py`:

```python
"""Write shards.json (matches rwv schema) and audio/manifest.json
(audio-measured per-turn timing). Both files live alongside the
shards/<profile>/*.mp3 files in <run>/audio/."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from forced_align.boundaries import ShardBoundary


def _md5(path: Path) -> str:
    h = hashlib.md5()
    h.update(path.read_bytes())
    return h.hexdigest()


def write_manifests(
    *,
    audio_dir: Path,
    episode: dict,
    boundaries: list[ShardBoundary],
    profile: str,
) -> None:
    """Write shards.json + manifest.json into audio_dir.

    Assumes the per-shard mp3 files already exist at
    audio_dir/shards/<profile>/{0000,0001,...}.mp3.
    """
    shards_dir = audio_dir / "shards" / profile
    shards_entries = []
    audio_manifest_segments: list[dict] = []
    current_seg_idx: int | None = None
    seg_dict: dict | None = None

    # Walk turns in order so we can emit both manifests in lock-step.
    flat_turns: list[tuple[int, int, dict]] = []
    for seg_idx, segment in enumerate(episode.get("segments", [])):
        for turn_idx, turn in enumerate(segment.get("turns", [])):
            flat_turns.append((seg_idx, turn_idx, turn))

    assert len(flat_turns) == len(boundaries), (
        f"boundary count {len(boundaries)} != turn count {len(flat_turns)}"
    )

    for shard_idx, ((seg_idx, turn_idx, turn), boundary) in enumerate(
        zip(flat_turns, boundaries, strict=True)
    ):
        mp3_path = shards_dir / f"{shard_idx:04d}.mp3"
        # shards.json entry
        shards_entries.append({
            "file": f"{shard_idx:04d}.mp3",
            "md5": _md5(mp3_path),
            "kind": "turn",
            "segment_index": seg_idx,
            "turn_index": turn_idx,
            "speaker": turn.get("speaker", ""),
            "role": turn.get("role", ""),
            "utterances": turn.get("utterances", []),
        })

        # audio/manifest.json: lazily open a new segment when seg_idx changes
        if seg_idx != current_seg_idx:
            seg_dict = {
                "title": episode["segments"][seg_idx].get("title", ""),
                "segment_type": episode["segments"][seg_idx].get("segment_type", ""),
                "start_ms": int(boundary.start_s * 1000),
                "turns": [],
            }
            audio_manifest_segments.append(seg_dict)
            current_seg_idx = seg_idx
        assert seg_dict is not None
        seg_dict["turns"].append({
            "speaker": turn.get("speaker", ""),
            "role": turn.get("role", ""),
            "start_ms": int(boundary.start_s * 1000),
            "end_ms": int(boundary.end_s * 1000),
            "utterances": turn.get("utterances", []),
        })

    total_duration_ms = (
        int(boundaries[-1].end_s * 1000) if boundaries else 0
    )
    shards_doc = {
        "schema_version": 1,
        "profile": profile,
        "episode_title": episode.get("title", ""),
        "experts": episode.get("experts", []),
        "shards": shards_entries,
    }
    audio_manifest_doc = {
        "title": episode.get("title", ""),
        "experts": episode.get("experts", []),
        "segments": audio_manifest_segments,
        "total_duration_ms": total_duration_ms,
    }

    (audio_dir / "shards.json").write_text(json.dumps(shards_doc, indent=2))
    (audio_dir / "manifest.json").write_text(
        json.dumps(audio_manifest_doc, indent=2)
    )
```

- [ ] **Step 3: Run the test to confirm pass**

```bash
cd tools/forced_align && uv run pytest tests/test_manifest.py -v
```
Expected: 1 test passes.

- [ ] **Step 4: Commit**

```bash
git add tools/forced_align/forced_align/manifest.py tools/forced_align/tests/test_manifest.py
git commit -m "forced_align: shards.json + audio/manifest.json writers (Task 5)"
```

---

## Task 6: WhisperX align wrapper

**Files:**
- Create: `tools/forced_align/forced_align/align.py`

WhisperX has external state (downloads models on first run, GPU/CPU detection, etc.) that's painful to mock in unit tests. The integration test in Task 8 (the pilot run) is the validation gate for this module. We do write a smoke test that verifies the function signature and runs against the synthetic fixture, without asserting alignment quality.

- [ ] **Step 1: Implement align.py**

`tools/forced_align/forced_align/align.py`:

```python
"""WhisperX wrapper: force-align a known transcript against an mp3,
returning per-word (start, end) timestamps.

This module loads the WhisperX alignment model on first call and
caches it on the module. WhisperX's design separates 'transcribe'
(slow, model-heavy) from 'align' (forced alignment given transcript).
We use the latter exclusively — we already know the transcript.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from forced_align.boundaries import AlignedWord

logger = logging.getLogger(__name__)

_align_model: Any = None
_align_metadata: Any = None


def _detect_device() -> str:
    """MPS on Apple-silicon, CUDA on Linux GPU, CPU fallback."""
    try:
        import torch
        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
    except Exception:  # noqa: BLE001
        pass
    return "cpu"


def _load_align_model(language: str = "en") -> tuple[Any, Any]:
    """Lazy-load the WhisperX alignment model. Cached for process lifetime."""
    global _align_model, _align_metadata
    if _align_model is None:
        import whisperx
        device = _detect_device()
        logger.info("loading WhisperX alignment model (device=%s)", device)
        _align_model, _align_metadata = whisperx.load_align_model(
            language_code=language, device=device,
        )
    return _align_model, _align_metadata


def align_transcript(
    audio_path: Path,
    words: list[str],
    *,
    language: str = "en",
) -> list[AlignedWord]:
    """Force-align the words list against audio_path.

    Returns one AlignedWord per word that WhisperX successfully aligned.
    The output's `script_index` is set to the input's index so callers
    can detect which words got dropped.
    """
    import whisperx
    model, metadata = _load_align_model(language=language)
    device = _detect_device()

    audio = whisperx.load_audio(str(audio_path))
    # WhisperX align takes "segments" — each segment is a transcript chunk
    # to align as a unit. We pass the whole transcript as one segment;
    # WhisperX handles its own internal chunking.
    text = " ".join(words)
    segments = [{"text": text, "start": 0.0, "end": len(audio) / 16000.0}]
    result = whisperx.align(
        segments, model, metadata, audio, device,
        return_char_alignments=False,
    )

    out: list[AlignedWord] = []
    aligned_words = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            aligned_words.append(w)

    # WhisperX returns aligned words in order. Match each back to its
    # script index by walking both lists; words WhisperX dropped (no
    # 'start' key — alignment failed for that word) are skipped.
    script_idx = 0
    for w in aligned_words:
        if "start" not in w or "end" not in w:
            continue
        # Advance the script cursor to this word. WhisperX's word may
        # differ in punctuation/case; do a loose match by stripping
        # punctuation and lowercasing.
        wtext = _normalise(w.get("word", ""))
        while script_idx < len(words) and _normalise(words[script_idx]) != wtext:
            script_idx += 1
        if script_idx >= len(words):
            logger.debug("ran past end of script while matching '%s'", wtext)
            break
        out.append(AlignedWord(
            word=w.get("word", ""),
            start_s=float(w["start"]),
            end_s=float(w["end"]),
            script_index=script_idx,
        ))
        script_idx += 1
    return out


def _normalise(s: str) -> str:
    """Strip punctuation, lowercase. Used for loose matching of aligned
    words back to script words (WhisperX may strip 'word.' to 'word')."""
    return "".join(c for c in s.lower() if c.isalnum())
```

- [ ] **Step 2: Smoke-test the import (no model load yet)**

```bash
cd tools/forced_align && uv run python -c "from forced_align.align import align_transcript, _detect_device; print('device:', _detect_device())"
```
Expected: prints `device: mps` on Apple-silicon (or `cuda` / `cpu`). No errors.

- [ ] **Step 3: Commit**

```bash
git add tools/forced_align/forced_align/align.py
git commit -m "forced_align: WhisperX align wrapper (Task 6)"
```

---

## Task 7: CLI

**Files:**
- Modify: `tools/forced_align/forced_align/__main__.py` (replace stub)
- Create: `tools/forced_align/tests/test_cli.py`

- [ ] **Step 1: Write the failing integration test**

`tools/forced_align/tests/test_cli.py`:

```python
"""End-to-end CLI test: monkeypatch align_transcript so we don't run
WhisperX in CI, then run the CLI on the synthetic 3-turn fixture +
a synthetic phase3_episode.json."""
import json
import shutil
import sys
from pathlib import Path

import pytest


FIXTURE_MP3 = Path(__file__).parent / "fixtures" / "synthetic_3turn.mp3"


def _make_synthetic_run(root: Path, mp3_src: Path) -> Path:
    """Build a fake data/runs/<run>/ matching what the CLI expects."""
    run_dir = root / "data" / "runs" / "synth_test"
    audio_dir = run_dir / "audio"
    audio_dir.mkdir(parents=True)
    shutil.copy(mp3_src, audio_dir / "podcast.mp3")
    episode = {
        "title": "Synthetic Test",
        "experts": [{"name": "Speaker A", "role": "expert"}],
        "segments": [
            {"title": "Only", "segment_type": "opening", "turns": [
                {"speaker": "Host", "role": "host",
                 "utterances": [{"text": "alpha",
                                 "sentence_type": "default",
                                 "is_quote": False, "quote_mode": None,
                                 "passage_ref": None}]},
                {"speaker": "Speaker A", "role": "expert",
                 "utterances": [{"text": "bravo",
                                 "sentence_type": "default",
                                 "is_quote": False, "quote_mode": None,
                                 "passage_ref": None}]},
                {"speaker": "Host", "role": "host",
                 "utterances": [{"text": "charlie",
                                 "sentence_type": "default",
                                 "is_quote": False, "quote_mode": None,
                                 "passage_ref": None}]},
            ]},
        ],
    }
    (run_dir / "phase3_episode.json").write_text(json.dumps(episode))
    return run_dir


def test_cli_run_synth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    run_dir = _make_synthetic_run(tmp_path, FIXTURE_MP3)
    # Patch align_transcript to return synthetic timestamps matching the fixture.
    from forced_align.boundaries import AlignedWord
    fake_alignments = [
        AlignedWord(word="alpha", start_s=0.5, end_s=2.0, script_index=0),
        AlignedWord(word="bravo", start_s=2.5, end_s=4.0, script_index=1),
        AlignedWord(word="charlie", start_s=4.5, end_s=6.0, script_index=2),
    ]
    import forced_align.align as align_mod
    monkeypatch.setattr(align_mod, "align_transcript",
                        lambda audio_path, words, **kw: fake_alignments)

    # Invoke CLI
    from forced_align.__main__ import main
    monkeypatch.setattr(sys, "argv", [
        "forced_align", "--data-dir", str(tmp_path / "data"),
        "--run", "synth_test",
    ])
    rc = main()
    assert rc == 0

    audio_dir = run_dir / "audio"
    assert (audio_dir / "shards.json").exists()
    assert (audio_dir / "manifest.json").exists()
    shards = json.loads((audio_dir / "shards.json").read_text())
    assert len(shards["shards"]) == 3
    shard_files = sorted((audio_dir / "shards" / "classic").glob("*.mp3"))
    assert [f.name for f in shard_files] == ["0000.mp3", "0001.mp3", "0002.mp3"]
```

```bash
cd tools/forced_align && uv run pytest tests/test_cli.py -v
```
Expected: ImportError or AttributeError.

- [ ] **Step 2: Implement the CLI**

Replace `tools/forced_align/forced_align/__main__.py`:

```python
"""CLI entry point for the forced-alignment migration."""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

from forced_align.align import align_transcript
from forced_align.boundaries import compute_boundaries
from forced_align.manifest import write_manifests
from forced_align.slicer import slice_mp3
from forced_align.transcript import parse_episode

logger = logging.getLogger(__name__)


def _ffprobe_duration(path: Path) -> float:
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(path),
    ]).decode().strip()
    return float(out)


def process_run(data_dir: Path, run_id: str, *, force: bool = False) -> int:
    run_dir = data_dir / "runs" / run_id
    audio_dir = run_dir / "audio"
    podcast = audio_dir / "podcast.mp3"
    episode_path = run_dir / "phase3_episode.json"
    shards_json = audio_dir / "shards.json"

    if not podcast.exists():
        logger.error("%s: no podcast.mp3", run_id)
        return 1
    if not episode_path.exists():
        logger.error("%s: no phase3_episode.json", run_id)
        return 1
    if shards_json.exists() and not force:
        logger.warning("%s: shards.json already exists (use --force)", run_id)
        return 0

    episode = json.loads(episode_path.read_text())
    words, turn_ranges = parse_episode(episode)
    logger.info("%s: %d words across %d turns", run_id, len(words), len(turn_ranges))

    try:
        aligned = align_transcript(podcast, words)
    except Exception as exc:  # noqa: BLE001
        logger.exception("%s: alignment failed", run_id)
        (audio_dir / "align_error.txt").write_text(repr(exc))
        return 1

    duration_s = _ffprobe_duration(podcast)
    try:
        boundaries = compute_boundaries(aligned, turn_ranges, duration_s)
    except ValueError as exc:
        logger.error("%s: boundary computation failed: %s", run_id, exc)
        (audio_dir / "align_error.txt").write_text(str(exc))
        return 1

    # Slice
    shards_dir = audio_dir / "shards" / "classic"
    if shards_dir.exists() and force:
        for old in shards_dir.glob("*.mp3"):
            old.unlink()
    shards_dir.mkdir(parents=True, exist_ok=True)
    for i, b in enumerate(boundaries):
        if b.end_s <= b.start_s:
            # Empty turn — skip the slice; manifest still records it but
            # shards.json md5 needs a file. Emit a 1-frame mp3 (~26ms).
            slice_mp3(podcast, shards_dir / f"{i:04d}.mp3",
                      start_s=max(0.0, b.start_s - 0.013),
                      end_s=min(duration_s, b.start_s + 0.013))
        else:
            slice_mp3(podcast, shards_dir / f"{i:04d}.mp3",
                      start_s=b.start_s, end_s=b.end_s)

    write_manifests(audio_dir=audio_dir, episode=episode,
                    boundaries=boundaries, profile="classic")
    logger.info("%s: wrote %d shards", run_id, len(boundaries))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="forced_align")
    parser.add_argument("--run", help="single run id")
    parser.add_argument("--all", action="store_true",
                        help="process every run with podcast.mp3 and no shards.json")
    parser.add_argument("--force", action="store_true",
                        help="overwrite existing shards.json")
    parser.add_argument("--data-dir", type=Path,
                        default=Path("data"),
                        help="root data directory")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
    )

    if not args.run and not args.all:
        parser.error("specify --run <id> or --all")

    if args.run:
        return process_run(args.data_dir, args.run, force=args.force)

    # --all: every run with podcast.mp3 and no shards.json
    runs_root = args.data_dir / "runs"
    targets = []
    for run_dir in sorted(runs_root.iterdir()):
        if not run_dir.is_dir():
            continue
        if not (run_dir / "audio" / "podcast.mp3").exists():
            continue
        if (run_dir / "audio" / "shards.json").exists() and not args.force:
            continue
        targets.append(run_dir.name)
    logger.info("processing %d runs", len(targets))
    failures = []
    for run_id in targets:
        rc = process_run(args.data_dir, run_id, force=args.force)
        if rc != 0:
            failures.append(run_id)
    if failures:
        logger.error("failed runs: %s", failures)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run the CLI test to confirm pass**

```bash
cd tools/forced_align && uv run pytest tests/test_cli.py -v
```
Expected: 1 test passes.

- [ ] **Step 4: Run all tests**

```bash
cd tools/forced_align && uv run pytest -v
```
Expected: 12 tests pass (3 transcript + 7 boundaries + 1 slicer + 1 manifest + 1 CLI).

- [ ] **Step 5: Commit**

```bash
git add tools/forced_align/forced_align/__main__.py tools/forced_align/tests/test_cli.py
git commit -m "forced_align: CLI entry point with --run / --all / --force (Task 7)"
```

---

## Task 8: Pilot run on bh_trn_literary_hostprep

**Files:**
- Modify: `data/runs/bh_trn_literary_hostprep/audio/` (write shards + manifests)

This is the validation gate. **Do not deploy** until manual listen-test passes.

- [ ] **Step 1: Run the tool on the pilot**

From the repo root:
```bash
cd tools/forced_align && uv run -m forced_align --run bh_trn_literary_hostprep --data-dir ../../data --verbose 2>&1 | tee /tmp/forced_align_pilot.log | tail -30
```

Expected: log lines for word count, "loading WhisperX alignment model", per-segment progress, and `wrote N shards` at the end. Wall time: ~10–15 minutes on M-series MPS.

- [ ] **Step 2: Sanity-check the outputs**

```bash
ls -1 data/runs/bh_trn_literary_hostprep/audio/shards/classic/ | head
cat data/runs/bh_trn_literary_hostprep/audio/shards.json | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('schema_version:', d['schema_version'])
print('profile:', d['profile'])
print('shard count:', len(d['shards']))
"
python3 -c "
import json
m = json.load(open('data/runs/bh_trn_literary_hostprep/audio/manifest.json'))
print('total_duration_ms:', m['total_duration_ms'])
"
```

Expected: `schema_version: 1`, `profile: classic`, ~100+ shards, `total_duration_ms` close to 6,454,944 (the actual mp3 duration).

- [ ] **Step 3: Listen-test from the consumer site**

Start the dev server:
```bash
uv run uvicorn webapp.app:app --host 127.0.0.1 --port 8765 --log-level warning &
```

Open `http://127.0.0.1:8765/listen/bleak_house/literary` in a browser. The player should detect `shards.json` and switch to shards mode.

Click 10+ paragraphs across all segments and verify each one plays the speaker the player highlighted. Specifically:
- A turn at the start (segment 0, turn 0): should play "Welcome to Bleak House Unpacked..."
- The Blackstone "I'd push back on the word machinery" turn (your original test case)
- A turn deep in the middle of the episode (segment 4 or 5)
- The last turn of the episode

If any click consistently mis-plays, investigate (likely a forced-alignment quality issue) before moving to Task 9.

- [ ] **Step 4: Stop the dev server, decide go/no-go**

```bash
pkill -f "uvicorn webapp.app"
```

If listen-test is clean: proceed to Task 9. If not: file findings as a separate beads issue, fix, and re-run Task 8 with `--force`.

- [ ] **Step 5: Commit pilot outputs**

```bash
git add data/runs/bh_trn_literary_hostprep/audio/
git commit -m "forced_align: pilot run on bh_trn_literary_hostprep (Task 8)"
```

(Do NOT `dvc push` yet — wait until bulk run is also done so we have one push.)

---

## Task 9: Bulk run on the remaining 31

**Files:**
- Modify: `data/runs/<all-other-audio-runs>/audio/`

- [ ] **Step 1: Identify the bulk targets**

```bash
for d in data/runs/*/audio; do
  run=$(basename "$(dirname "$d")")
  [ -e "$d/podcast.mp3" ] || continue
  [ -e "$d/shards.json" ] && continue
  echo "$run"
done | tee /tmp/bulk_targets.txt | wc -l
```

Expected: 31 (the pilot already has its shards from Task 8).

- [ ] **Step 2: Run the bulk job**

```bash
cd tools/forced_align && uv run -m forced_align --all --data-dir ../../data --verbose 2>&1 | tee /tmp/forced_align_bulk.log | tail -50 &
```

Expected wall time: ~4–8 hours. Run unattended (e.g. overnight). The CLI continues past per-run failures and prints a summary.

- [ ] **Step 3: Inventory the results**

When the bulk run finishes:
```bash
echo "successful runs:"
for d in data/runs/*/audio; do
  run=$(basename "$(dirname "$d")")
  [ -e "$d/shards.json" ] && [ -e "$d/podcast.mp3" ] && echo "  $run"
done | wc -l

echo "failed runs (have align_error.txt):"
for f in data/runs/*/audio/align_error.txt; do
  echo "  $(basename $(dirname $(dirname $f))): $(head -1 $f)"
done
```

Expected: 32 successful (1 pilot + 31 bulk), 0 failed in the happy path. If any failures, file follow-up beads issues; the legacy mp3 still serves them via player.js fallback.

- [ ] **Step 4: Spot-check 3 random runs**

Pick 3 random successful runs (e.g. `cran_trn_alternatives_hostprep`, `pti_trn_interdisciplinary_hostprep`, `mid_nop_alternatives_hostprep`). For each:
- `/listen/<novel>/<panel>` in the consumer player.
- Click the first turn — should play opening Host monologue.
- Click a mid-episode turn — should play the highlighted speaker.

If all three pass, the bulk migration is good. If any fails, file beads, do not deploy.

- [ ] **Step 5: DVC track + push**

```bash
for d in data/runs/*/audio/shards; do
  [ -d "$d" ] || continue
  uv run dvc add "$d" 2>&1 | tail -2
done
uv run dvc push -r r2 2>&1 | tail -10
```

Expected: ~32 `.dvc` files created (one per run's shards dir), R2 push completes successfully. ~2GB transferred.

- [ ] **Step 6: Commit**

```bash
git add data/runs/*/audio/shards.json data/runs/*/audio/manifest.json data/runs/*/audio/shards.dvc data/runs/*/audio/.gitignore
git commit -m "forced_align: bulk-run shards for 31 audio runs (Task 9)"
```

---

## Task 10: Merge feature branch + deploy

- [ ] **Step 1: Pre-merge checks**

```bash
uv run pytest tests/webapp/ -q
cd tools/forced_align && uv run pytest -q && cd ../..
uv run ruff check webapp/ tools/forced_align/
```

All green.

- [ ] **Step 2: Merge to main**

```bash
git checkout main
git merge --no-ff feature/forced-alignment-shards -m "merge: forced-alignment migration of legacy podcast.mp3 to shards"
```

- [ ] **Step 3: Deploy**

```bash
bash scripts/deploy_demo.sh
```

Expected: deploy succeeds, healthcheck passes.

- [ ] **Step 4: Live verification**

```bash
# Confirm a previously-broken run now serves shards
curl -s -o /dev/null -w '%{http_code}\n' https://bleakhouse-demo.fly.dev/audio/bh_trn_literary_hostprep/shards.json
curl -s https://bleakhouse-demo.fly.dev/audio/bh_trn_literary_hostprep/shards.json | python3 -c "import json,sys; d=json.load(sys.stdin); print('shards:', len(d['shards']))"
```

Expected: `200` and a shard count. Click a turn on https://bleakhouse-demo.fly.dev/listen/bleak_house/literary and confirm Blackstone's "I'd push back on the word machinery" plays the right speaker — the original bug report is resolved.

- [ ] **Step 5: Close the umbrella beads issue with a summary linking the resolved bug.**

---

## Self-review checklist

- [x] Spec coverage: every spec section has a corresponding task (project skeleton/Task 1, sources of truth/Tasks 2 + 6, modules/Tasks 2-7, schema match/Task 5, edge cases/Task 3 tests, error handling/Task 7 process_run, idempotency/Task 7 --force, pilot/Task 8, bulk/Task 9, performance/Task 9 wall time).
- [x] Placeholder scan: no TODO/TBD/"add error handling" stubs. Every step has executable content.
- [x] Type consistency: `AlignedWord`, `TurnRange`, `ShardBoundary` defined in transcript.py / boundaries.py and used identically in tests + CLI. `compute_boundaries`, `align_transcript`, `slice_mp3`, `write_manifests`, `parse_episode` — names match across the plan.
