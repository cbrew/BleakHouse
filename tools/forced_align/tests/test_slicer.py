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
    files = sorted(out_dir.glob("*.mp3"))
    assert [f.name for f in files] == ["0000.mp3", "0001.mp3", "0002.mp3"]
    durations = [_ffprobe_duration(f) for f in files]
    assert durations[0] == pytest.approx(2.25, abs=0.05)
    assert durations[1] == pytest.approx(2.0, abs=0.05)
    assert durations[2] == pytest.approx(2.25, abs=0.05)
