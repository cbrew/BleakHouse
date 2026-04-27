"""ICL vs x-vector-only A/B for Qwen3-TTS accent retention.

Renders the same 5 diagnostic sentences for two speakers (Host, Blackstone)
in two modes:
    A) x_vector_only_mode=True       (current production path)
    B) x_vector_only_mode=False      (full ICL with ref_text)

Outputs 20 wavs + a results.json with per-call wall time and any errors.

The "EOS-stall" the production code dodges with x_vector_only=True will, if
still present, manifest as either (a) a render that hits max_new_tokens and
produces a longer-than-expected wav, or (b) a runtime error.

Usage (on pop-os):
    BLEAKHOUSE=/home/cbrew/bleakhouse-qwen-tts
    cd $BLEAKHOUSE
    .venv/bin/python -m experiments.qwen_tts.icl_ab \\
        --refs /var/lib/qwen-tts-server/jobs/<job_id>/refs \\
        --out  /tmp/qwen_icl_ab
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from .render import DEFAULT_MODEL, _load_model

logger = logging.getLogger(__name__)


# Diagnostic sentences. Picked for British/American accent contrast:
# rhotic R (precision, careful, surgical, twenty, character),
# trap-bath split (Chancery, masterpiece),
# specific vowels (fog, thick, twenty).
TEST_SENTENCES: list[tuple[str, str]] = [
    ("01_chancery", "Chancery is a system that consumes people, slowly and methodically."),
    ("02_remarkable", "What's remarkable is the surgical precision of Dickens's prose."),
    ("03_welcome", "Welcome back to Bleak House Unpacked, a careful reading of a Victorian masterpiece."),
    ("04_chapter", "Today we examine chapter twenty, and what stands out is the central irony."),
    ("05_fog", "Dickens shows us a fog so thick it blurs the line between buildings and air."),
]

SPEAKERS = ["Host", "James_Blackstone"]


def render_one(
    wrapper: Any,
    text: str,
    ref_audio: str,
    ref_text: str,
    *,
    x_vector_only: bool,
    max_new_tokens: int = 2048,
) -> tuple[np.ndarray, int, float]:
    t0 = time.perf_counter()
    audio_list, sr = wrapper.generate_voice_clone(
        text=text,
        language="english",
        ref_audio=ref_audio,
        ref_text=ref_text if not x_vector_only else None,
        x_vector_only_mode=x_vector_only,
        max_new_tokens=max_new_tokens,
    )
    elapsed = time.perf_counter() - t0
    if not audio_list:
        raise RuntimeError("empty audio_list")
    return np.asarray(audio_list[0], dtype=np.float32), sr, elapsed


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--refs", required=True, type=Path, help="Refs dir with {Speaker}.wav + .json")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--max-new-tokens", type=int, default=2048)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    args.out.mkdir(parents=True, exist_ok=True)

    # Load each speaker's ref + sidecar.
    speakers: dict[str, dict[str, Any]] = {}
    for spk in SPEAKERS:
        sc = args.refs / f"{spk}.json"
        if not sc.exists():
            raise FileNotFoundError(sc)
        meta = json.loads(sc.read_text())
        wav = args.refs / meta["wav"]
        if not wav.exists():
            raise FileNotFoundError(wav)
        speakers[spk] = {"ref_wav": str(wav), "ref_text": meta["ref_text"]}
        logger.info("loaded ref for %s: %s (%d chars ref_text)", spk, wav.name, len(meta["ref_text"]))

    logger.info("loading model %s", DEFAULT_MODEL)
    wrapper = _load_model(DEFAULT_MODEL)

    results: list[dict[str, Any]] = []
    for spk, ref in speakers.items():
        for sentence_id, text in TEST_SENTENCES:
            for x_vec_only in (True, False):
                tag = f"{spk.lower()}_{sentence_id}_xvec{int(x_vec_only)}"
                row: dict[str, Any] = {
                    "tag": tag,
                    "speaker": spk,
                    "sentence_id": sentence_id,
                    "x_vector_only": x_vec_only,
                    "text": text,
                }
                try:
                    audio, sr, elapsed = render_one(
                        wrapper,
                        text=text,
                        ref_audio=ref["ref_wav"],
                        ref_text=ref["ref_text"],
                        x_vector_only=x_vec_only,
                        max_new_tokens=args.max_new_tokens,
                    )
                    out_path = args.out / f"{tag}.wav"
                    sf.write(str(out_path), audio, sr)
                    audio_s = len(audio) / sr
                    rt = audio_s / elapsed if elapsed > 0 else None
                    row.update({
                        "ok": True,
                        "elapsed_s": round(elapsed, 2),
                        "audio_s": round(audio_s, 2),
                        "rt_ratio": round(rt, 3) if rt else None,
                        "wav": out_path.name,
                    })
                    # Heuristic stall flag: rendered audio much longer than expected
                    # for a 1-line sentence (>20 s).
                    if audio_s > 20:
                        row["likely_stall"] = True
                    print(f"  {tag}: ok ({elapsed:.1f}s -> {audio_s:.1f}s audio, rt {rt:.2f}x)")
                except Exception as exc:
                    row.update({"ok": False, "error": str(exc)})
                    print(f"  {tag}: FAIL {exc}")
                results.append(row)

    (args.out / "results.json").write_text(json.dumps(results, indent=2))
    print()
    ok = sum(1 for r in results if r.get("ok"))
    fail = sum(1 for r in results if not r.get("ok"))
    stall = sum(1 for r in results if r.get("likely_stall"))
    print(f"DONE: {ok} ok, {fail} failed, {stall} likely-stall")
    print(f"  out: {args.out}")


if __name__ == "__main__":
    main()
