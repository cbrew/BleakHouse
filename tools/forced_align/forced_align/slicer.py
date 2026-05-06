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
