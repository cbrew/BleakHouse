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
    chunk_audio_brackets: list[tuple[float, float]] = []  # (start_s, end_s)
    i = 0
    while i < n_words:
        j = min(i + chunk_words, n_words)
        chunk_start_s = max(0.0, (i / n_words) * total_s - overlap_s)
        chunk_end_s = min(total_s, (j / n_words) * total_s + overlap_s)
        segments.append({
            "text": " ".join(words[i:j]),
            "start": chunk_start_s,
            "end": chunk_end_s,
        })
        chunk_word_ranges.append((i, j - 1))
        chunk_audio_brackets.append((chunk_start_s, chunk_end_s))
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

    # WhisperX may return more output segments than input chunks (it
    # subdivides at internal silences). Bucket each output segment to
    # its input chunk by start-time, then walk per-chunk so script-index
    # matching stays bounded to that chunk's word range. Overlap dups
    # at chunk boundaries get filtered via seen_script_idx.
    output_segments = result.get("segments", [])

    def _chunk_for_start(t: float) -> int:
        for ci, (a, b) in enumerate(chunk_audio_brackets):
            if a <= t <= b:
                return ci
        # Fall through (segment slightly outside any bracket): pick closest.
        return min(
            range(len(chunk_audio_brackets)),
            key=lambda ci: min(
                abs(t - chunk_audio_brackets[ci][0]),
                abs(t - chunk_audio_brackets[ci][1]),
            ),
        )

    # Bucket each individual word (not segment) into its chunk by start
    # time, so a word near a chunk boundary lands in the chunk whose
    # script range it belongs to. WhisperX subdivides chunks at internal
    # silences, so a single output segment's words can span both sides
    # of a chunk boundary — bucketing at word granularity is the only
    # robust split.
    all_words: list[dict] = []
    for seg in output_segments:
        for w in seg.get("words", []):
            if "start" in w and "end" in w:
                all_words.append(w)

    chunk_words_out: list[list[dict]] = [[] for _ in chunk_word_ranges]
    for w in all_words:
        ci = _chunk_for_start(float(w["start"]))
        chunk_words_out[ci].append(w)
    for bucket in chunk_words_out:
        bucket.sort(key=lambda x: float(x["start"]))

    # Greedy matching corrupts the script cursor when WhisperX emits a
    # noise/hallucination word that doesn't appear anywhere in this
    # chunk's script range — the cursor walks past `last` searching, and
    # every subsequent word in the chunk is dropped. Use a bounded
    # forward window: search up to `match_window` ahead of local_idx;
    # if no match, skip the aligned word and leave the cursor put.
    match_window = 50
    out: list[AlignedWord] = []
    seen_script_idx: set[int] = set()
    for chunk_idx, (first, last) in enumerate(chunk_word_ranges):
        local_idx = first
        unmatched = 0
        for w in chunk_words_out[chunk_idx]:
            wtext = _normalise(w.get("word", ""))
            if not wtext:
                continue
            found = -1
            search_end = min(last + 1, local_idx + match_window)
            for probe in range(local_idx, search_end):
                if _normalise(words[probe]) == wtext:
                    found = probe
                    break
            if found < 0:
                unmatched += 1
                continue
            if found not in seen_script_idx:
                out.append(AlignedWord(
                    word=w.get("word", ""),
                    start_s=float(w["start"]),
                    end_s=float(w["end"]),
                    script_index=found,
                ))
                seen_script_idx.add(found)
            local_idx = found + 1
        if unmatched:
            logger.debug(
                "chunk %d: %d aligned words didn't match within window",
                chunk_idx, unmatched,
            )
    out.sort(key=lambda aw: aw.script_index or 0)
    return out
