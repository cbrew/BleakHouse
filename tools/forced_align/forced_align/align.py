"""WhisperX wrapper: force-align a known transcript against an mp3,
returning per-word (start, end) timestamps.

This module loads the WhisperX alignment model on first call and
caches it on the module. WhisperX's design separates 'transcribe'
(slow, model-heavy) from 'align' (forced alignment given transcript).
We use the latter exclusively — we already know the transcript.
"""
from __future__ import annotations

import logging
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


def _normalise(s: str) -> str:
    """Strip punctuation, lowercase. Used for loose matching of aligned
    words back to script words (WhisperX may strip 'word.' to 'word')."""
    return "".join(c for c in s.lower() if c.isalnum())


def align_transcript(
    audio_path: Path,
    words: list[str],
    *,
    language: str = "en",
) -> list[AlignedWord]:
    """Force-align the words list against audio_path.

    Returns one AlignedWord per word that WhisperX successfully aligned,
    with script_index populated so callers can detect which words got
    dropped.
    """
    import whisperx
    model, metadata = _load_align_model(language=language)
    device = _detect_device()

    audio = whisperx.load_audio(str(audio_path))
    text = " ".join(words)
    segments = [{"text": text, "start": 0.0, "end": len(audio) / 16000.0}]
    result = whisperx.align(
        segments, model, metadata, audio, device,
        return_char_alignments=False,
    )

    aligned_words: list[dict] = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            aligned_words.append(w)

    out: list[AlignedWord] = []
    script_idx = 0
    for w in aligned_words:
        if "start" not in w or "end" not in w:
            continue
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
