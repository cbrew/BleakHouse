"""Extract a per-speaker reference clip from an existing mixed podcast.mp3.

For each speaker that appears in the run's manifest, pick their longest
single turn, slice that time range from the podcast.mp3, and save it as
an 8–15 s reference WAV plus a sidecar JSON carrying the verbatim
transcript of the utterances in that turn (for ICL voice cloning).

Output layout:
    <out_dir>/
        Host.wav                Host.json               (verbatim text)
        Eleanor_Hartley.wav     Eleanor_Hartley.json
        James_Blackstone.wav    James_Blackstone.json
        Caroline_Woodcourt.wav  Caroline_Woodcourt.json

Usage:
    uv run python -m experiments.qwen_tts.extract_refs \\
        --run data/runs/bh_trn_literary \\
        --out /tmp/qwen_refs/literary \\
        --min-seconds 6 --max-seconds 15
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")


def _find_longest_turn_per_speaker(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """For each speaker, return the turn dict with the longest span."""
    best: dict[str, dict[str, Any]] = {}
    for seg in manifest.get("segments", []):
        for t in seg.get("turns", []):
            speaker = t.get("speaker") or "?"
            start = t.get("start_ms")
            end = t.get("end_ms")
            if start is None or end is None or end <= start:
                continue
            span = end - start
            prev = best.get(speaker)
            if prev is None or (prev["end_ms"] - prev["start_ms"]) < span:
                best[speaker] = dict(t)
    return best


def extract_refs(
    run_dir: Path,
    out_dir: Path,
    *,
    min_seconds: float = 6.0,
    max_seconds: float = 15.0,
    audio_path: Path | None = None,
) -> dict[str, Any]:
    """Extract per-speaker reference clips. Returns a metadata dict."""
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"No manifest.json at {manifest_path}")
    with open(manifest_path) as f:
        manifest = json.load(f)

    if audio_path is None:
        audio_path = run_dir / "audio" / "podcast.mp3"
    if not audio_path.exists():
        raise FileNotFoundError(f"No podcast audio at {audio_path}")

    from pydub import AudioSegment

    audio = AudioSegment.from_file(str(audio_path))
    audio = audio.set_channels(1).set_frame_rate(24000)

    out_dir.mkdir(parents=True, exist_ok=True)

    best_by_speaker = _find_longest_turn_per_speaker(manifest)
    out: dict[str, Any] = {
        "run_dir": str(run_dir),
        "audio_path": str(audio_path),
        "manifest_total_duration_ms": manifest.get("total_duration_ms"),
        "speakers": {},
    }

    for speaker, turn in sorted(best_by_speaker.items()):
        start_ms = int(turn["start_ms"])
        end_ms = int(turn["end_ms"])
        span_ms = end_ms - start_ms

        # Cap the clip length. Prefer the beginning of the turn (the model
        # needs only a few seconds of voice; longer doesn't always help and
        # can introduce other speakers at turn boundaries if timing is off).
        clip_ms = min(span_ms, int(max_seconds * 1000))
        if clip_ms < int(min_seconds * 1000):
            logger.warning(
                "  %s: longest turn is only %.1fs (< min_seconds=%.1f); using as-is",
                speaker, span_ms / 1000, min_seconds,
            )

        clip = audio[start_ms:start_ms + clip_ms]

        slug = _slug(speaker)
        wav_path = out_dir / f"{slug}.wav"
        clip.export(str(wav_path), format="wav")

        ref_text = " ".join(
            u.get("text", "") for u in turn.get("utterances", [])
        ).strip()
        # Trim ref_text to roughly match clip_ms proportion of the full turn
        # so the transcript aligns with the audio we actually kept.
        if clip_ms < span_ms and ref_text:
            keep_frac = clip_ms / span_ms
            keep_chars = int(len(ref_text) * keep_frac)
            # Cut on nearest whitespace to avoid mid-word
            cut = ref_text.rfind(" ", 0, keep_chars) if keep_chars > 0 else 0
            if cut > 0:
                ref_text = ref_text[:cut]

        sidecar = {
            "speaker": speaker,
            "role": turn.get("role", ""),
            "source_turn_span_ms": [start_ms, end_ms],
            "clip_ms": clip_ms,
            "ref_text": ref_text,
            "wav": wav_path.name,
        }
        with open(out_dir / f"{slug}.json", "w") as f:
            json.dump(sidecar, f, indent=2)

        out["speakers"][speaker] = sidecar
        logger.info(
            "  %s (%s): %.1fs clip at %d ms (%d chars ref_text)",
            speaker, turn.get("role", ""), clip_ms / 1000, start_ms, len(ref_text),
        )

    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path,
                        help="Run directory with manifest.json + audio/podcast.mp3")
    parser.add_argument("--out", required=True, type=Path,
                        help="Output directory for reference clips + sidecars.")
    parser.add_argument("--audio", type=Path, default=None,
                        help="Override audio source (defaults to <run>/audio/podcast.mp3)")
    parser.add_argument("--min-seconds", type=float, default=6.0)
    parser.add_argument("--max-seconds", type=float, default=15.0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    info = extract_refs(
        args.run, args.out,
        min_seconds=args.min_seconds,
        max_seconds=args.max_seconds,
        audio_path=args.audio,
    )
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
