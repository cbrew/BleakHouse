"""Kokoro TTS service — lazy-loading, on-demand segment rendering.

Model files live on the fly volume. Downloaded on first use if missing.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

VOLUME_DIR = Path(os.environ.get("KOKORO_MODEL_DIR", "/app/audio_volume/kokoro_model"))
MODEL_FILE = VOLUME_DIR / "kokoro-v1.0.onnx"
VOICES_FILE = VOLUME_DIR / "voices-v1.0.bin"

MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"

_model = None


def _download_if_missing() -> None:
    """Download model files to volume if not present."""
    import urllib.request

    VOLUME_DIR.mkdir(parents=True, exist_ok=True)

    for path, url, label in [
        (MODEL_FILE, MODEL_URL, "model (310MB)"),
        (VOICES_FILE, VOICES_URL, "voices (27MB)"),
    ]:
        if not path.exists():
            logger.info("Downloading Kokoro %s to %s...", label, path)
            urllib.request.urlretrieve(url, str(path))
            logger.info("Downloaded %s (%d bytes)", label, path.stat().st_size)


def get_model():
    """Return the Kokoro model, loading/downloading on first call."""
    global _model
    if _model is not None:
        return _model

    _download_if_missing()

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
