"""Build a clean per-speaker clip pool from existing Gemini renders.

Walks `data/runs/bh_*/manifest.json`, picks Host turns of suitable length,
slices clips from `audio/podcast.mp3`, validates F0 to dodge Gemini voice
drift, and writes per-clip wavs + provenance.

Originally written for an F5-TTS fine-tune spike (BleakHouse-ejc, closed),
now used as raw material for designed reference clips per persona
(BleakHouse-9lk).

Output layout:
    <out>/wavs/host_NNNN.wav       (24kHz mono)
    <out>/manifest.json            (per-clip provenance — text, source_run,
                                    source_turn_start_ms, f0_median_hz, ...)
    <out>/metadata.csv             (audio_file|text — kept for compat)

Usage:
    uv run python scripts/build_voice_pool.py \\
        --target-minutes 15 --out data/voice_pools/Host
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Per-speaker F0 ranges. Empirical from bh_trn_literary refs (sidecar JSON
# in the existing extract_refs output). Widened slightly for headroom; clips
# whose pyin median F0 lands outside the range are rejected as Gemini drift.
SPEAKER_F0: dict[str, tuple[float, float]] = {
    "Host":               (195.0, 295.0),
    "Eleanor Hartley":    (180.0, 280.0),
    "Caroline Woodcourt": (180.0, 280.0),
    "James Blackstone":   (95.0,  170.0),
    "Edmund Leigh":       (95.0,  170.0),
    "Daniel Rosen":       (95.0,  170.0),
    "Oliver Trevelyan":   (95.0,  170.0),
    "Sarah Chen":         (180.0, 290.0),
    "Rebecca Martinez":   (180.0, 290.0),
    "Elena Volkov":       (180.0, 290.0),
}

# Clip length window — broad enough to give the speaker encoder material.
MIN_CLIP_S = 4.0
MAX_CLIP_S = 12.0
# Skip first 2 s of each turn (Gemini voice-drift zone, see extract_refs.py).
LEAD_IN_S = 2.0


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")


def _f0_in_range(wav_path: Path, lo: float, hi: float) -> tuple[bool, float]:
    import librosa  # type: ignore[import-not-found]
    import numpy as np
    y, sr = librosa.load(str(wav_path), sr=24000, mono=True)
    f0, voiced, _ = librosa.pyin(y, fmin=60, fmax=400, sr=sr)
    vals = f0[voiced]
    if vals.size == 0:
        return False, 0.0
    med = float(np.nanmedian(vals))
    return lo <= med <= hi, med


def _find_runs(repo: Path, run_glob: str = "*") -> list[Path]:
    runs = sorted((repo / "data" / "runs").glob(f"{run_glob}/manifest.json"))
    out = []
    for r in runs:
        audio = r.parent / "audio" / "podcast.mp3"
        if audio.exists() or audio.is_symlink():
            out.append(r)
    return out


def _speaker_turns(manifest: dict[str, Any], speaker: str) -> list[dict[str, Any]]:
    out = []
    for seg in manifest.get("segments", []):
        for t in seg.get("turns", []):
            if t.get("speaker") != speaker:
                continue
            s, e = t.get("start_ms"), t.get("end_ms")
            if s is None or e is None or e <= s:
                continue
            dur = (e - s) / 1000.0
            # Need at least lead-in + min clip.
            if dur < LEAD_IN_S + MIN_CLIP_S:
                continue
            out.append(t)
    return out


def _trim_text(ref_text: str, frac: float) -> str:
    if frac >= 1.0 or not ref_text:
        return ref_text
    keep = max(0, int(len(ref_text) * frac))
    cut = ref_text.rfind(" ", 0, keep) if keep > 0 else 0
    return ref_text[:cut] if cut > 0 else ref_text


def build(repo: Path, out_dir: Path, target_minutes: float, speaker: str,
          f0_min: float, f0_max: float, run_glob: str = "*") -> dict[str, Any]:
    from pydub import AudioSegment

    out_dir.mkdir(parents=True, exist_ok=True)
    wav_dir = out_dir / "wavs"
    wav_dir.mkdir(exist_ok=True)
    target_s = target_minutes * 60.0

    runs = _find_runs(repo, run_glob)
    rows: list[dict[str, Any]] = []
    rejected = {"f0_out_of_range": 0, "no_text": 0, "audio_load_fail": 0, "too_short": 0}
    total_s = 0.0
    n = 0
    speaker_slug = _slug(speaker).lower()

    for r_path in runs:
        if total_s >= target_s:
            break
        with r_path.open() as f:
            manifest = json.load(f)
        audio_path = (r_path.parent / "audio" / "podcast.mp3").resolve()
        try:
            audio = AudioSegment.from_file(str(audio_path)).set_channels(1).set_frame_rate(24000)
        except Exception as exc:
            logger.warning("audio_load_fail %s: %s", audio_path, exc)
            rejected["audio_load_fail"] += 1
            continue

        for turn in _speaker_turns(manifest, speaker):
            if total_s >= target_s:
                break
            start_ms = int(turn["start_ms"])
            turn_dur_s = (turn["end_ms"] - turn["start_ms"]) / 1000.0
            clip_dur_s = min(turn_dur_s - LEAD_IN_S, MAX_CLIP_S)
            if clip_dur_s < MIN_CLIP_S:
                rejected["too_short"] += 1
                continue

            ref_text = " ".join(u.get("text", "") for u in turn.get("utterances", [])).strip()
            if not ref_text:
                rejected["no_text"] += 1
                continue
            ref_text = _trim_text(ref_text, clip_dur_s / turn_dur_s)

            n += 1
            tag = f"{speaker_slug}_{n:04d}_{_slug(r_path.parent.name)[:30]}"
            wav_path = wav_dir / f"{tag}.wav"
            clip = audio[start_ms + int(LEAD_IN_S * 1000): start_ms + int(LEAD_IN_S * 1000) + int(clip_dur_s * 1000)]
            clip.export(str(wav_path), format="wav")

            ok, med = _f0_in_range(wav_path, f0_min, f0_max)
            if not ok:
                wav_path.unlink()
                rejected["f0_out_of_range"] += 1
                logger.info("  reject f0=%.0fHz %s", med, tag)
                n -= 1
                continue

            rows.append({
                "audio_file": str(wav_path.resolve()),
                "text": ref_text,
                "duration_s": clip_dur_s,
                "f0_median_hz": round(med, 1),
                "source_run": r_path.parent.name,
                "source_turn_start_ms": start_ms,
            })
            total_s += clip_dur_s
            logger.info("  +%s (%.1fs, total %.1f min, f0=%.0fHz)", tag, clip_dur_s, total_s / 60, med)

    # F5-TTS metadata.csv: audio_file|text (header required).
    csv_path = out_dir / "metadata.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f, delimiter="|", quoting=csv.QUOTE_NONE, escapechar="\\")
        w.writerow(["audio_file", "text"])
        for r in rows:
            w.writerow([r["audio_file"], r["text"]])

    summary = {
        "total_clips": len(rows),
        "total_seconds": round(total_s, 1),
        "total_minutes": round(total_s / 60, 2),
        "rejected": rejected,
        "items": rows,
    }
    (out_dir / "manifest.json").write_text(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--speaker", default="Host",
                   help=f"speaker name as it appears in run manifests; one of {sorted(SPEAKER_F0)}")
    p.add_argument("--target-minutes", type=float, default=15.0)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--run-glob", default="*",
                   help="glob pattern for run dirs under data/runs/ (default *: all novels)")
    p.add_argument("--f0-min", type=float, default=None,
                   help="override per-speaker default F0 floor")
    p.add_argument("--f0-max", type=float, default=None,
                   help="override per-speaker default F0 ceiling")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.speaker not in SPEAKER_F0 and (args.f0_min is None or args.f0_max is None):
        raise SystemExit(
            f"unknown speaker {args.speaker!r}; provide --f0-min and --f0-max, "
            f"or pick one of {sorted(SPEAKER_F0)}"
        )
    f0_min = args.f0_min if args.f0_min is not None else SPEAKER_F0[args.speaker][0]
    f0_max = args.f0_max if args.f0_max is not None else SPEAKER_F0[args.speaker][1]

    repo = Path(__file__).resolve().parent.parent
    summary = build(repo, args.out, args.target_minutes, args.speaker, f0_min, f0_max, args.run_glob)
    print()
    print(f"speaker: {args.speaker}  F0 range: [{f0_min}, {f0_max}] Hz")
    print(f"clips: {summary['total_clips']}, audio: {summary['total_minutes']:.1f} min")
    print(f"rejected: {summary['rejected']}")
    print(f"metadata: {args.out / 'metadata.csv'}")


if __name__ == "__main__":
    main()
