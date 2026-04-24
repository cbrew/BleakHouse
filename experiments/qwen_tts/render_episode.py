"""Render a complete podcast episode via Qwen3-TTS voice cloning.

Takes:
    - A run directory with phase3_episode.json (the script).
    - A refs directory with {Speaker}.wav + {Speaker}.json per speaker
      (produced by `experiments.qwen_tts.extract_refs`).

For every utterance in every segment:
    1. Pick the speaker's reference clip + transcript.
    2. Call Qwen3TTSModel.generate_voice_clone(text, ref_audio, ref_text).
    3. Prepend `pause_before_ms` of silence, append `pause_after_ms`.
    4. Concatenate into a per-segment WAV and an episode WAV.

Outputs under `<out_dir>/`:
    episode.wav                         - full concatenated episode
    segment_{i:02d}.wav                 - per-segment concatenation
    utterances/seg{i}_turn{j}_utt{k}.wav - per-utterance clips (for debug)
    episode.json                        - manifest of what was rendered

Usage (on the Linux box with CUDA):
    uv run python -m experiments.qwen_tts.render_episode \\
        --run data/runs/bh_trn_literary \\
        --refs /tmp/qwen_refs_literary \\
        --out /tmp/qwen_episode_literary
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

from .render import DEFAULT_MODEL, _load_model  # noqa: E402

SAMPLE_RATE = 24000


def _load_speaker_refs(refs_dir: Path) -> dict[str, dict[str, Any]]:
    """Load sidecar JSONs for each speaker under refs_dir."""
    refs: dict[str, dict[str, Any]] = {}
    for p in sorted(refs_dir.glob("*.json")):
        with open(p) as f:
            data = json.load(f)
        speaker = data.get("speaker")
        if not speaker:
            continue
        wav_path = refs_dir / data["wav"]
        if not wav_path.exists():
            logger.warning("Missing wav for speaker %r: %s", speaker, wav_path)
            continue
        data["wav_path"] = str(wav_path)
        refs[speaker] = data
    return refs


def _silence(ms: int) -> np.ndarray:
    n = max(0, int(ms / 1000 * SAMPLE_RATE))
    return np.zeros(n, dtype=np.float32)


def render_episode(
    run_dir: Path,
    refs_dir: Path,
    out_dir: Path,
    *,
    model_id: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    import soundfile as sf

    ep_path = run_dir / "phase3_episode.json"
    if not ep_path.exists():
        raise FileNotFoundError(f"No phase3_episode.json at {ep_path}")
    with open(ep_path) as f:
        episode = json.load(f)

    refs = _load_speaker_refs(refs_dir)
    if not refs:
        raise RuntimeError(f"No reference clips found under {refs_dir}")
    logger.info("Loaded refs for %d speakers: %s", len(refs), sorted(refs))

    wrapper = _load_model(model_id)

    out_dir.mkdir(parents=True, exist_ok=True)
    utt_dir = out_dir / "utterances"
    utt_dir.mkdir(exist_ok=True)

    episode_audio: list[np.ndarray] = []
    segments_meta: list[dict[str, Any]] = []
    totals = {
        "utterances": 0, "utterances_ok": 0, "utterances_failed": 0,
        "generate_seconds": 0.0, "audio_seconds": 0.0,
    }
    missing_speakers: set[str] = set()
    episode_start_time = time.perf_counter()

    for si, seg in enumerate(episode.get("segments", [])):
        seg_audio: list[np.ndarray] = []
        seg_utts_meta: list[dict[str, Any]] = []
        for ti, turn in enumerate(seg.get("turns", [])):
            speaker = turn.get("speaker", "?")
            ref = refs.get(speaker)
            if ref is None:
                missing_speakers.add(speaker)
                logger.warning("seg%d/turn%d: no ref for speaker %r — skipping", si, ti, speaker)
                continue
            for ui, utt in enumerate(turn.get("utterances", [])):
                totals["utterances"] += 1
                text = utt.get("text") or ""
                pause_before = int(utt.get("pause_before_ms") or 0)
                pause_after = int(utt.get("pause_after_ms") or 0)
                if not text.strip():
                    continue

                if pause_before > 0:
                    seg_audio.append(_silence(pause_before))

                t0 = time.perf_counter()
                try:
                    # x_vector_only_mode=True uses only the speaker embedding
                    # from the ref clip — faster, and avoids an ICL-path
                    # stall we observed on certain (ref_audio, ref_text)
                    # pairings where the code_predictor never emits EOS.
                    # max_new_tokens capped to keep the failure bounded.
                    audio_list, sr = wrapper.generate_voice_clone(
                        text=text,
                        ref_audio=ref["wav_path"],
                        x_vector_only_mode=True,
                        language="english",
                        max_new_tokens=1024,
                    )
                    gen_seconds = time.perf_counter() - t0
                    if not audio_list:
                        raise RuntimeError("empty audio_list")
                    utt_audio = np.asarray(audio_list[0], dtype=np.float32)
                    if sr != SAMPLE_RATE:
                        # The model should return 24 kHz; if not, warn loudly.
                        logger.warning("seg%d/turn%d/utt%d: unexpected sample_rate %d", si, ti, ui, sr)
                except Exception as e:
                    totals["utterances_failed"] += 1
                    logger.error("seg%d/turn%d/utt%d: generation failed: %s", si, ti, ui, e)
                    # Fill the missing utterance with equivalent silence so
                    # downstream timing still makes sense.
                    est = max(1.0, len(text.split()) * 0.35)
                    utt_audio = _silence(int(est * 1000))
                    gen_seconds = time.perf_counter() - t0
                else:
                    totals["utterances_ok"] += 1
                    # Save per-utterance wav for debugging.
                    sf.write(
                        str(utt_dir / f"seg{si}_turn{ti}_utt{ui}.wav"),
                        utt_audio, SAMPLE_RATE,
                    )

                totals["generate_seconds"] += gen_seconds
                totals["audio_seconds"] += len(utt_audio) / SAMPLE_RATE

                seg_audio.append(utt_audio)
                if pause_after > 0:
                    seg_audio.append(_silence(pause_after))

                seg_utts_meta.append({
                    "segment": si, "turn": ti, "utt": ui,
                    "speaker": speaker, "text_chars": len(text),
                    "generate_seconds": gen_seconds,
                    "audio_seconds": len(utt_audio) / SAMPLE_RATE,
                })

        seg_wav = np.concatenate(seg_audio) if seg_audio else np.zeros(0, dtype=np.float32)
        seg_path = out_dir / f"segment_{si:02d}.wav"
        sf.write(str(seg_path), seg_wav, SAMPLE_RATE)

        segments_meta.append({
            "segment_index": si,
            "title": seg.get("title", ""),
            "wav": seg_path.name,
            "audio_seconds": len(seg_wav) / SAMPLE_RATE,
            "utterances": seg_utts_meta,
        })
        episode_audio.append(seg_wav)
        logger.info(
            "seg%d %r: %d utterances, %.1fs audio",
            si, seg.get("title", "?")[:50],
            sum(1 for u in seg_utts_meta),
            len(seg_wav) / SAMPLE_RATE,
        )

    full = np.concatenate(episode_audio) if episode_audio else np.zeros(0, dtype=np.float32)
    episode_path = out_dir / "episode.wav"
    sf.write(str(episode_path), full, SAMPLE_RATE)

    wall_elapsed = time.perf_counter() - episode_start_time
    manifest = {
        "run_dir": str(run_dir),
        "refs_dir": str(refs_dir),
        "model_id": model_id,
        "episode_wav": episode_path.name,
        "episode_audio_seconds": len(full) / SAMPLE_RATE,
        "wall_elapsed_seconds": wall_elapsed,
        "realtime_ratio": (len(full) / SAMPLE_RATE) / wall_elapsed if wall_elapsed > 0 else None,
        "totals": totals,
        "missing_speakers": sorted(missing_speakers),
        "segments": segments_meta,
    }
    with open(out_dir / "episode.json", "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--refs", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    manifest = render_episode(args.run, args.refs, args.out, model_id=args.model)
    print()
    print(f"Episode: {args.out}/episode.wav")
    print(f"  length: {manifest['episode_audio_seconds']:.1f}s")
    print(f"  wall:   {manifest['wall_elapsed_seconds']:.1f}s")
    rt = manifest.get("realtime_ratio")
    if rt is not None:
        print(f"  rt:     {rt:.2f}x")
    t = manifest["totals"]
    print(f"  utts:   {t['utterances_ok']}/{t['utterances']} ok, {t['utterances_failed']} failed")
    if manifest["missing_speakers"]:
        print(f"  missing refs for: {manifest['missing_speakers']}")


if __name__ == "__main__":
    main()
