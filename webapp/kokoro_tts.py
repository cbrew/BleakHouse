"""Kokoro TTS service — lazy-loading, on-demand segment rendering.

Model files live on the fly volume. Downloaded on first use if missing.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

VOLUME_DIR = Path(os.environ.get("KOKORO_MODEL_DIR", "/app/audio_volume/kokoro_model"))
MODEL_FILE = VOLUME_DIR / "kokoro-v1.0.int8.onnx"
VOICES_FILE = VOLUME_DIR / "voices-v1.0.bin"

MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"

_model = None


def get_model():
    """Return the Kokoro model, loading from volume on first call.

    Model files must be pre-loaded onto the volume — we don't download
    at runtime to avoid OOM from the download + load memory spike.
    """
    global _model
    if _model is not None:
        return _model

    if not MODEL_FILE.exists():
        raise RuntimeError(
            f"Kokoro model not found at {MODEL_FILE}. "
            "Upload model files to the fly volume first."
        )

    from kokoro_onnx import Kokoro

    logger.info("Loading Kokoro model from %s", MODEL_FILE)
    _model = Kokoro(str(MODEL_FILE), str(VOICES_FILE))
    logger.info("Kokoro model loaded")
    return _model


def synthesize_turn(text: str, voice: str, speed: float = 1.0) -> tuple:
    """Synthesize a single turn. Returns (samples, sample_rate)."""
    model = get_model()
    samples, sr = model.create(text, voice=voice, speed=speed)
    return samples, sr
