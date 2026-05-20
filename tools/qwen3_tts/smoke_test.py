"""Smoke test: load Qwen3-TTS-12Hz-1.7B-VoiceDesign + synthesise one sample.

Verifies that the model loads on the local GPU within VRAM, produces
audible English from a textual voice description, and returns a usable
sample rate / wav array shape. Tracks BleakHouse-el1j.4.

Run from the qwen3_tts venv:
    uv run --directory tools/qwen3_tts python smoke_test.py
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel


MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
DEFAULT_TEXT = (
    "Welcome to Bleak House Unpacked. Today we begin not with the famous "
    "first sentence, but with the fog that rises from it — the fog that "
    "doesn't just obscure London, but obscures agency, responsibility, "
    "causality itself."
)
DEFAULT_INSTRUCT = (
    "Warm female voice in her early forties with a polished Home Counties "
    "accent — a BBC Radio 4 presenter's measured cadence. Calm, "
    "conversational, with the unhurried authority of someone who has "
    "hosted many literary panels."
)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="smoke_test.wav",
                   help="Output wav path (default: %(default)s)")
    p.add_argument("--text", default=DEFAULT_TEXT)
    p.add_argument("--instruct", default=DEFAULT_INSTRUCT)
    p.add_argument("--attn", default="sdpa",
                   choices=["sdpa", "flash_attention_2", "eager"],
                   help="Attention backend (default: %(default)s — sdpa is the "
                        "safe fallback on Turing sm_75 where FA2 builds are flaky)")
    args = p.parse_args()

    if not torch.cuda.is_available():
        print("CUDA not available — refusing to run on CPU at 1.7B", file=sys.stderr)
        return 2

    dev = torch.cuda.get_device_name(0)
    free, total = torch.cuda.mem_get_info(0)
    print(f"device: {dev}  free_vram={free/1e9:.2f} GB / total={total/1e9:.2f} GB")
    print(f"loading {MODEL_ID}  attn_implementation={args.attn} ...")

    t0 = time.monotonic()
    model = Qwen3TTSModel.from_pretrained(
        MODEL_ID,
        device_map="cuda:0",
        dtype=torch.bfloat16,
        attn_implementation=args.attn,
    )
    load_s = time.monotonic() - t0
    after_load_free, _ = torch.cuda.mem_get_info(0)
    used_for_weights = free - after_load_free
    print(f"loaded in {load_s:.1f}s — weights use {used_for_weights/1e9:.2f} GB VRAM")

    print(f"generating  text={args.text!r}\n            instruct={args.instruct!r}")
    t0 = time.monotonic()
    wavs, sr = model.generate_voice_design(
        text=args.text,
        language="English",
        instruct=args.instruct,
    )
    gen_s = time.monotonic() - t0

    if wavs is None or len(wavs) == 0:
        print("ERROR: no wav returned", file=sys.stderr)
        return 3

    wav = wavs[0]
    print(f"generated in {gen_s:.1f}s")
    print(f"  sample_rate: {sr}")
    print(f"  wav shape: {getattr(wav, 'shape', None)}")
    print(f"  wav dtype: {getattr(wav, 'dtype', None)}")
    duration = (len(wav) / sr) if sr else 0
    print(f"  duration: {duration:.2f}s")
    print(f"  realtime factor: {duration/gen_s:.2f}x (>1 = faster than real-time)")

    out_path = Path(args.out).resolve()
    sf.write(str(out_path), wav, sr)
    print(f"wrote {out_path}")

    after_gen_free, _ = torch.cuda.mem_get_info(0)
    peak_used = free - after_gen_free
    print(f"peak VRAM used: {peak_used/1e9:.2f} GB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
