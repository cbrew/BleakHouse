"""Batch render all demo runs via Kokoro TTS (GPU or CPU).

Designed to run on a machine with an NVIDIA GPU for ~30-40x realtime.
Renders each run's segments, concatenates, and exports MP3.

Usage:
    # On the GPU machine, from the repo root:
    pip install kokoro-onnx soundfile numpy pydub
    # For PyTorch GPU (faster): pip install kokoro torch

    # Download model files:
    mkdir -p data/tts_models
    wget -O data/tts_models/kokoro-v1.0.onnx \
        https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
    wget -O data/tts_models/voices-v1.0.bin \
        https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

    # Render all runs (skip those with Gemini audio):
    python scripts/batch_render_kokoro.py --output-dir data/kokoro_audio --bitrate 64k

    # Render a single run:
    python scripts/batch_render_kokoro.py --run cran_trn_v01_baseline --output-dir data/kokoro_audio
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = BASE_DIR / "data" / "runs"
MODEL_DIR = Path(os.environ.get("KOKORO_MODEL_DIR", str(BASE_DIR / "data" / "tts_models")))

# Voice mapping (duplicated from webapp/kokoro_voices.py to avoid import issues)
KOKORO_VOICES = {
    "Host": ("bf_emma", "b"),
    "Narrator": ("bm_lewis", "b"),
    "Eleanor Hartley": ("bf_lily", "b"),
    "James Blackstone": ("bm_george", "b"),
    "Caroline Woodcourt": ("bf_isabella", "b"),
    "Edmund Leigh": ("bm_lewis", "b"),
    "Daniel Rosen": ("bm_daniel", "b"),
    "Oliver Trevelyan": ("bm_fable", "b"),
    "Sarah Chen": ("af_sarah", "a"),
    "Rebecca Martinez": ("af_bella", "a"),
    "Elena Volkov": ("af_nova", "a"),
}
DEFAULT_VOICE = ("bf_emma", "b")

# Runs that already have Gemini audio — skip these
GEMINI_RUNS = {
    "ext_v01_baseline",
    "ext_v01_baseline_hostprep",
    "ext_v19_all_swapped",
    "ext_v19_all_swapped_hostprep",
    "interdisciplinary_trn_hostprep",
    "motf_ext_v01_baseline",
    "motf_ext_v19_all_swapped",
    "motf_nop_v19_all_swapped",
    "nop_v19_all_swapped",
}

# Demo runs (180 tracker grid + 3 interdisciplinary)
def get_demo_names() -> set[str]:
    try:
        from enrichment.run_full_matrix import build_matrix
        grid = {r["name"] for r in build_matrix()}
    except ImportError:
        # Fallback: find all runs with phase3_episode.json
        grid = {d.name for d in RUNS_DIR.iterdir() if (d / "phase3_episode.json").exists()}
    inter = {"interdisciplinary_trn_hostprep", "interdisciplinary_emb_hostprep", "interdisciplinary_nop_hostprep"}
    return grid | inter


def load_model():
    """Load Kokoro model — tries full fp32 first (best quality on GPU)."""
    from kokoro_onnx import Kokoro

    # Prefer full model on GPU, int8 on CPU
    for model_name in ["kokoro-v1.0.onnx", "kokoro-v1.0.int8.onnx"]:
        model_path = MODEL_DIR / model_name
        if model_path.exists():
            logger.info("Loading %s", model_path)
            return Kokoro(str(model_path), str(MODEL_DIR / "voices-v1.0.bin"))

    raise FileNotFoundError(f"No Kokoro model found in {MODEL_DIR}")


def render_run(model, run_id: str, output_dir: Path, bitrate: str) -> Path | None:
    """Render one run to MP3. Returns output path or None on failure."""
    ep_path = RUNS_DIR / run_id / "phase3_episode.json"
    if not ep_path.exists():
        logger.warning("No episode for %s", run_id)
        return None

    out_path = output_dir / run_id / "podcast.mp3"
    if out_path.exists():
        logger.info("Already rendered: %s", run_id)
        return out_path

    with open(ep_path) as f:
        episode = json.load(f)

    sample_rate = 24000
    all_samples = []
    total_turns = sum(len(seg.get("turns", [])) for seg in episode.get("segments", []))
    done = 0
    run_start = time.time()

    for seg_idx, seg in enumerate(episode.get("segments", [])):
        for turn in seg.get("turns", []):
            speaker = turn.get("speaker", "Host")
            voice, _lang = KOKORO_VOICES.get(speaker, DEFAULT_VOICE)
            text = " ".join(u.get("text", "") for u in turn.get("utterances", []))
            if not text.strip():
                done += 1
                continue

            rate = 1.0
            if turn.get("utterances"):
                rate = turn["utterances"][0].get("rate", 1.0)

            try:
                samples, sr = model.create(text, voice=voice, speed=rate)
                if sr != sample_rate:
                    samples = np.interp(
                        np.linspace(0, len(samples), int(len(samples) * sample_rate / sr)),
                        np.arange(len(samples)), samples
                    ).astype(np.float32)
                all_samples.append(samples)
            except Exception as e:
                logger.warning("  Turn failed (%s): %s", speaker, e)

            # Inter-turn pause
            all_samples.append(np.zeros(int(sample_rate * 0.2), dtype=np.float32))
            done += 1

        # Inter-segment pause (2s)
        all_samples.append(np.zeros(int(sample_rate * 2.0), dtype=np.float32))

        elapsed = time.time() - run_start
        logger.info("  %s: segment %d/%d done (%d/%d turns, %.0fs)",
                     run_id, seg_idx + 1, len(episode["segments"]), done, total_turns, elapsed)

    if not all_samples:
        logger.warning("No audio for %s", run_id)
        return None

    combined = np.concatenate(all_samples)
    duration = len(combined) / sample_rate

    # Save as WAV first, then convert to MP3
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wav_path = out_path.with_suffix(".wav")
    sf.write(str(wav_path), combined, sample_rate)

    # Convert to MP3 using pydub (requires ffmpeg)
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_wav(str(wav_path))
        audio.export(str(out_path), format="mp3", bitrate=bitrate)
        wav_path.unlink()  # remove WAV after MP3 conversion
    except Exception as e:
        logger.warning("MP3 conversion failed for %s: %s (keeping WAV)", run_id, e)
        out_path = wav_path

    elapsed = time.time() - run_start
    rtf = duration / elapsed if elapsed > 0 else 0
    size_mb = out_path.stat().st_size / 1048576
    logger.info("  %s: %.0f min audio, rendered in %.0fs (%.1fx RT), %.1f MB",
                run_id, duration / 60, elapsed, rtf, size_mb)

    return out_path


def main():
    parser = argparse.ArgumentParser(description="Batch render Kokoro TTS for all demo runs")
    parser.add_argument("--output-dir", type=Path, default=BASE_DIR / "data" / "kokoro_audio")
    parser.add_argument("--bitrate", default="64k", help="MP3 bitrate (default: 64k)")
    parser.add_argument("--run", type=str, default=None, help="Render a single run")
    parser.add_argument("--include-gemini", action="store_true", help="Re-render runs with Gemini audio")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
    )

    model = load_model()

    if args.run:
        runs = [args.run]
    else:
        demo = get_demo_names()
        runs = sorted(d.name for d in RUNS_DIR.iterdir()
                       if d.name in demo and (d / "phase3_episode.json").exists())
        if not args.include_gemini:
            runs = [r for r in runs if r not in GEMINI_RUNS]

    logger.info("Rendering %d runs to %s (bitrate: %s)", len(runs), args.output_dir, args.bitrate)
    total_start = time.time()
    success = 0
    failed = 0

    for i, run_id in enumerate(runs):
        logger.info("[%d/%d] %s", i + 1, len(runs), run_id)
        result = render_run(model, run_id, args.output_dir, args.bitrate)
        if result:
            success += 1
        else:
            failed += 1

    total_elapsed = time.time() - total_start
    logger.info("Done: %d succeeded, %d failed in %.0f minutes",
                success, failed, total_elapsed / 60)


if __name__ == "__main__":
    main()
