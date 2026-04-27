"""Render accent-diagnostic test sentences with Qwen3-TTS for a given ref clip.

Used to A/B different reference strategies (single 15 s clip, 60 s concat,
designed slot-covered ref). Test sentences are loaded from a JSON file —
the canonical held-out set lives at data/voice_refs/v1/test_sentences.json
and is verified content-disjoint from the ref by scripts/check_test_overlap.py.

Run on the GPU host (pop-os). qwen-tts-server must be stopped first to free
GPU memory.

Usage:
    cd /home/cbrew/bleakhouse-qwen-tts
    .venv/bin/python -m scripts.render_qwen_diagnostic \\
        --ref       /tmp/host_ref_v1.wav \\
        --sentences /tmp/test_sentences.json \\
        --out       /tmp/qwen_designed_ref_out
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from experiments.qwen_tts.render import DEFAULT_MODEL, _load_model

logger = logging.getLogger(__name__)


def load_sentences(path: Path) -> list[tuple[str, str]]:
    data = json.loads(path.read_text())
    return [(s["id"], s["text"]) for s in data["sentences"]]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ref", required=True, type=Path, help="ref wav")
    p.add_argument("--sentences", required=True, type=Path,
                   help="JSON file with {sentences: [{id, text, ...}, ...]}")
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    SENTENCES = load_sentences(args.sentences)
    print(f"loaded {len(SENTENCES)} test sentences from {args.sentences}")

    args.out.mkdir(parents=True, exist_ok=True)
    if not args.ref.exists():
        raise SystemExit(f"ref not found: {args.ref}")

    logger.info("loading %s", DEFAULT_MODEL)
    wrapper = _load_model(DEFAULT_MODEL)

    results = []
    for tag, text in SENTENCES:
        t0 = time.perf_counter()
        try:
            audio_list, sr = wrapper.generate_voice_clone(
                text=text,
                language="english",
                ref_audio=str(args.ref),
                x_vector_only_mode=True,
                max_new_tokens=2048,
            )
            elapsed = time.perf_counter() - t0
            if not audio_list:
                raise RuntimeError("empty audio_list")
            audio = np.asarray(audio_list[0], dtype=np.float32)
            sf.write(str(args.out / f"{tag}.wav"), audio, sr)
            audio_s = len(audio) / sr
            print(f"  {tag}: ok ({elapsed:.1f}s -> {audio_s:.2f}s audio)")
            results.append({"tag": tag, "ok": True, "elapsed_s": round(elapsed, 2),
                            "audio_s": round(audio_s, 2)})
        except Exception as exc:
            print(f"  {tag}: FAIL {exc}")
            results.append({"tag": tag, "ok": False, "error": str(exc)})

    (args.out / "results.json").write_text(json.dumps(results, indent=2))
    print(f"\nout: {args.out}")


if __name__ == "__main__":
    main()
