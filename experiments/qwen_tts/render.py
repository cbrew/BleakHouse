"""Qwen3-TTS voice-clone experiment.

Uses the dedicated `qwen-tts` package (pip install qwen-tts) — NOT
Qwen2.5-Omni. The Base model supports zero-shot voice cloning from a
short reference WAV + its transcript; this is what we want for matching
a Gemini voice in an existing podcast.

Workflow:
    1. Extract a ~8s reference clip from an existing podcast.mp3 (helper below).
    2. Transcribe it (manually, for now — automation is a separate task).
    3. Pass (text, ref_audio, ref_text) to Qwen3TTSModel.generate_voice_clone.
    4. Save the output WAV.

Usage:
    # Extract a reference clip from an existing render:
    uv run python -m experiments.qwen_tts.render extract-ref \\
        --in data/runs/bh_trn_literary/audio/podcast.mp3 \\
        --start 0 --duration 8 \\
        --out /tmp/ref_clip.wav

    # Synthesize new text in that voice:
    uv run python -m experiments.qwen_tts.render clone \\
        --text "Welcome back to Bleak House Unpacked." \\
        --ref-audio /tmp/ref_clip.wav \\
        --ref-text "Welcome to Bleak House Unpacked, a close reading of..." \\
        --out /tmp/cloned.wav

License: qwen-tts is Apache 2.0 (commercial-ok).

Known gotchas on this platform (M1 Pro / MPS):
  - `sox` binary isn't required for basic inference but prints a warning
    at import time — ignore it.
  - flash-attn isn't available on MPS; runs on the PyTorch path, slower
    but functional. That's fine for single-utterance experiments.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"  # smaller of the two Base variants

_MODEL: Any = None  # cached across calls in one process


def _load_model(model_id: str = DEFAULT_MODEL) -> Any:
    """Load the Qwen3 TTS Base model once; return wrapper."""
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    import torch
    from qwen_tts import Qwen3TTSModel

    if torch.cuda.is_available():
        device_map = "cuda"
        dtype = torch.bfloat16
    elif torch.backends.mps.is_available():
        device_map = "mps"
        # fp16 on MPS produces inf/nan in the TTS code_predictor's softmax;
        # the multinomial sampler then crashes. fp32 is slower but correct.
        dtype = torch.float32
    else:
        device_map = "cpu"
        dtype = torch.float32

    logger.info("Loading %s onto %s (first run downloads weights)", model_id, device_map)
    t0 = time.perf_counter()
    _MODEL = Qwen3TTSModel.from_pretrained(
        model_id, device_map=device_map, dtype=dtype,
    )
    logger.info("Load complete in %.1fs", time.perf_counter() - t0)
    return _MODEL


def extract_reference_clip(
    src: Path,
    out: Path,
    *,
    start_seconds: float = 0.0,
    duration_seconds: float = 8.0,
) -> dict[str, Any]:
    """Slice a WAV/MP3 file into a reference clip for voice cloning."""
    from pydub import AudioSegment

    src_ext = src.suffix.lower().lstrip(".")
    audio = AudioSegment.from_file(str(src), format=src_ext or None)
    start_ms = int(start_seconds * 1000)
    end_ms = start_ms + int(duration_seconds * 1000)
    clip = audio[start_ms:end_ms]
    # Normalise: mono, 24 kHz — model-agnostic, works for most TTS cloners.
    clip = clip.set_channels(1).set_frame_rate(24000)
    out.parent.mkdir(parents=True, exist_ok=True)
    clip.export(str(out), format="wav")
    return {
        "src": str(src),
        "out": str(out),
        "start_seconds": start_seconds,
        "duration_seconds": len(clip) / 1000,
        "sample_rate": 24000,
        "channels": 1,
    }


def clone_and_synthesize(
    text: str,
    ref_audio_path: Path,
    output_path: Path,
    *,
    ref_text: str | None = None,
    language: str = "english",
    model_id: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Voice-clone: speak `text` in the voice from `ref_audio_path`.

    `ref_text` must be the verbatim transcript of the reference clip
    (ICL / in-context learning mode). If omitted, falls back to
    x-vector-only mode — less faithful but doesn't need transcript.
    """
    import soundfile as sf

    wrapper = _load_model(model_id)

    t0 = time.perf_counter()
    audio_list, sample_rate = wrapper.generate_voice_clone(
        text=text,
        ref_audio=str(ref_audio_path),
        ref_text=ref_text,
        x_vector_only_mode=(ref_text is None),
        language=language,
    )
    elapsed = time.perf_counter() - t0

    if not audio_list:
        raise RuntimeError("Qwen3TTS returned empty audio list")
    audio = audio_list[0]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_path), audio, samplerate=sample_rate)
    audio_seconds = len(audio) / sample_rate

    return {
        "model_id": model_id,
        "text": text,
        "ref_audio": str(ref_audio_path),
        "ref_text": ref_text,
        "x_vector_only_mode": ref_text is None,
        "language": language,
        "output_path": str(output_path),
        "sample_rate": int(sample_rate),
        "elapsed_seconds": elapsed,
        "audio_seconds": audio_seconds,
        "realtime_ratio": audio_seconds / elapsed if elapsed > 0 else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_ext = sub.add_parser("extract-ref",
                           help="Slice a reference clip from an existing audio file.")
    p_ext.add_argument("--in", dest="src", required=True, type=Path)
    p_ext.add_argument("--out", required=True, type=Path)
    p_ext.add_argument("--start", dest="start_seconds", type=float, default=0.0)
    p_ext.add_argument("--duration", dest="duration_seconds", type=float, default=8.0)

    p_clone = sub.add_parser("clone",
                             help="Synthesize text using a reference voice.")
    p_clone.add_argument("--text", required=True)
    p_clone.add_argument("--ref-audio", required=True, type=Path)
    p_clone.add_argument("--ref-text", default=None,
                         help="Transcript of the reference clip; strongly recommended.")
    p_clone.add_argument("--language", default="english",
                         help="Qwen3-TTS language name (english/chinese/french/...). Default: english.")
    p_clone.add_argument("--model", default=DEFAULT_MODEL)
    p_clone.add_argument("--out", required=True, type=Path)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    # Silence the noisy sox import warning on CLI runs — we don't use sox.
    os.environ.setdefault("PYTHONWARNINGS", "ignore")

    if args.command == "extract-ref":
        info = extract_reference_clip(
            args.src, args.out,
            start_seconds=args.start_seconds,
            duration_seconds=args.duration_seconds,
        )
        print(json.dumps(info, indent=2))
    elif args.command == "clone":
        info = clone_and_synthesize(
            args.text, args.ref_audio, args.out,
            ref_text=args.ref_text, language=args.language, model_id=args.model,
        )
        print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
