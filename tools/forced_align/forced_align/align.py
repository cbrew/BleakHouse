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
    """CUDA on Linux GPU, CPU otherwise.

    We deliberately do NOT use MPS on Apple silicon: WhisperX's
    wav2vec2 alignment model uses F.conv1d, which has no MPS kernel
    in current PyTorch — `NotImplementedError: convolution_overrideable
    not implemented` mid-alignment. CPU is slower (30–60 min per
    100-min mp3 vs 10–15 on MPS) but always works. Override with
    FORCED_ALIGN_DEVICE=mps if you want to try anyway.
    """
    import os
    override = os.environ.get("FORCED_ALIGN_DEVICE")
    if override:
        return override
    try:
        import torch
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
    chunk_words: int = 1000,
    overlap_s: float = 10.0,
) -> list[AlignedWord]:
    """Force-align the words list against audio_path.

    Splits the script into chunks of ~chunk_words and feeds each as a
    separate segment to WhisperX. Per-segment memory is bounded — a
    single 100-min episode passed as one segment OOMs the wav2vec2
    activations on CPU. With chunk_words=1000 each chunk is ~7 minutes
    audio, comfortably under 1 GB peak.

    Each chunk's audio window is computed proportionally from the
    total mp3 duration; small overlap_s on each side absorbs the
    rough-proportional approximation. Words that align within an
    overlap region get deduped by script_index in the merge.

    Returns one AlignedWord per word that WhisperX successfully
    aligned, with script_index populated so callers can detect which
    words got dropped.
    """
    import whisperx
    model, metadata = _load_align_model(language=language)
    device = _detect_device()

    audio = whisperx.load_audio(str(audio_path))
    total_s = len(audio) / 16000.0
    n_words = len(words)
    if n_words == 0:
        return []

    # Build chunks with proportional time brackets and a small overlap.
    segments: list[dict] = []
    chunk_word_ranges: list[tuple[int, int]] = []  # (first_idx, last_idx) inclusive
    i = 0
    while i < n_words:
        j = min(i + chunk_words, n_words)
        # Proportional audio bracket for this word range.
        chunk_start_s = max(0.0, (i / n_words) * total_s - overlap_s)
        chunk_end_s = min(total_s, (j / n_words) * total_s + overlap_s)
        segments.append({
            "text": " ".join(words[i:j]),
            "start": chunk_start_s,
            "end": chunk_end_s,
        })
        chunk_word_ranges.append((i, j - 1))
        i = j

    logger.info(
        "aligning %d words in %d chunks (total %.1f s, ~%.1f s/chunk)",
        n_words, len(segments), total_s,
        total_s / max(1, len(segments)),
    )

    result = whisperx.align(
        segments, model, metadata, audio, device,
        return_char_alignments=False,
    )

    # Merge per-chunk alignments back to a single AlignedWord list.
    # Walk each chunk's aligned words and match against the chunk's
    # known script-word range so script_index lands in the right place
    # even when some chunks dropped words.
    out: list[AlignedWord] = []
    seen_script_idx: set[int] = set()
    for chunk_idx, seg in enumerate(result.get("segments", [])):
        first, last = chunk_word_ranges[chunk_idx]
        local_idx = first  # cursor into the script for this chunk
        for w in seg.get("words", []):
            if "start" not in w or "end" not in w:
                continue
            wtext = _normalise(w.get("word", ""))
            while local_idx <= last and _normalise(words[local_idx]) != wtext:
                local_idx += 1
            if local_idx > last:
                logger.debug(
                    "chunk %d: ran past end while matching '%s'",
                    chunk_idx, wtext,
                )
                break
            if local_idx not in seen_script_idx:
                out.append(AlignedWord(
                    word=w.get("word", ""),
                    start_s=float(w["start"]),
                    end_s=float(w["end"]),
                    script_index=local_idx,
                ))
                seen_script_idx.add(local_idx)
            local_idx += 1
    out.sort(key=lambda aw: aw.script_index or 0)
    return out
