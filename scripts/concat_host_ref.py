"""Concatenate N varied Host clips into one long ref wav for Qwen3-TTS.

The hypothesis: Qwen's speaker encoder (extract_speaker_embedding -> (D,))
integrates over the full ref audio, so a longer ref made of diverse Host
content produces a more accent-stable embedding than a single 15 s opening
monologue.

Usage:
    uv run python scripts/concat_host_ref.py \\
        --manifest data/tts_finetune/host_v1/manifest.json \\
        --n 5 --out /tmp/host_long_ref.wav
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf

# Pick clips with diverse first words so the concatenated ref captures
# different prosodic contexts: opener, question, summary, disagreement,
# closing. We just match against the start of each clip's text.
CONTENT_TYPES = [
    "welcome",       # opener
    "edmund",        # question / address
    "rebecca",       # interdisciplinary address
    "and that",      # synthesis
    "so what",       # pivot
]


def pick_diverse_clips(items: list[dict], n: int) -> list[dict]:
    chosen: list[dict] = []
    used_ids: set[str] = set()
    # First pass: try to find a clip matching each content_type in order.
    for hint in CONTENT_TYPES[:n]:
        best = None
        for r in items:
            if r["audio_file"] in used_ids:
                continue
            if r["text"].lower().startswith(hint):
                best = r
                break
        if best is not None:
            chosen.append(best)
            used_ids.add(best["audio_file"])
    # Fill remaining slots with the next-longest unused clips.
    for r in sorted(items, key=lambda x: -x["duration_s"]):
        if len(chosen) >= n:
            break
        if r["audio_file"] in used_ids:
            continue
        chosen.append(r)
        used_ids.add(r["audio_file"])
    return chosen[:n]


def concat(clips: list[dict], gap_ms: int = 200) -> tuple[np.ndarray, int, list[str]]:
    audios: list[np.ndarray] = []
    sr_used: int = 24000
    texts: list[str] = []
    gap = np.zeros(int(gap_ms / 1000 * sr_used), dtype=np.float32)
    for r in clips:
        y, sr = sf.read(r["audio_file"])
        if sr != sr_used:
            raise SystemExit(f"sample rate mismatch: {sr} != {sr_used} on {r['audio_file']}")
        audios.append(np.asarray(y, dtype=np.float32))
        audios.append(gap)
        texts.append(r["text"])
    if audios:
        audios = audios[:-1]  # drop trailing gap
    full = np.concatenate(audios) if audios else np.zeros(0, dtype=np.float32)
    return full, sr_used, texts


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", required=True, type=Path)
    p.add_argument("--n", type=int, default=5)
    p.add_argument("--gap-ms", type=int, default=200)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()

    manifest = json.loads(args.manifest.read_text())
    items = manifest["items"]
    chosen = pick_diverse_clips(items, args.n)
    if not chosen:
        raise SystemExit("no clips picked")
    audio, sr, texts = concat(chosen, gap_ms=args.gap_ms)
    sf.write(str(args.out), audio, sr)
    text_combined = " ".join(t.rstrip() for t in texts)
    text_path = args.out.with_suffix(".txt")
    text_path.write_text(text_combined + "\n")
    print(f"wrote {args.out}: {len(audio)/sr:.1f}s @ {sr}Hz, {len(chosen)} clips")
    for c in chosen:
        print(f"  {c['duration_s']:5.1f}s  {Path(c['audio_file']).name}  {c['text'][:60]}")
    print(f"transcript at {text_path}")


if __name__ == "__main__":
    main()
