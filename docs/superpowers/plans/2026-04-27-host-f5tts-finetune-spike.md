# Host F5-TTS Fine-Tune Spike (Modal) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-utterance zero-shot voice cloning with a Host-specific fine-tune that locks in accent + timbre. Spike scope only: Host alone, ~20 min training audio, A/B against the Qwen baseline. If quality wins, *then* plan a multi-speaker rollout.

**Architecture:**
- **Data prep on the Mac:** mine `data/runs/bh_*/manifest.json` for Host turns, slice from `audio/podcast.mp3`, filter for clean clips (≥4 s, F0 stable in expected female range, no overlap drift), assemble ~20 min of (wav, transcript) pairs.
- **Training on Modal:** F5-TTS fine-tune on a single L4 (~$0.80/h). All Modal artefacts live in `experiments/modal_tts/`. Persist base model + dataset + checkpoints in a Modal volume so retraining is cheap.
- **Inference path:** a Modal `synthesize(text)` endpoint we can call from the Mac to produce one wav per test sentence, then human A/B against the matching utterance from `bh_trn_literary` Qwen output.

**Tech Stack:** F5-TTS (Hugging Face SWivid/F5-TTS), Modal, Python 3.12 inside the Modal image, soundfile/pydub locally, ffmpeg.

**Budget:** $5 hard cap. Stop and reconsider if any single Modal run trends past $3.

**Beads:** [BleakHouse-ejc](../../../) tracks this.

---

## File structure

**Locally created/modified:**
- Create `scripts/build_host_dataset.py` — the data-prep pipeline (Mac)
- Create `data/tts_finetune/host_v1/manifest.json` — `[{"wav":"...", "text":"...", "duration_s":...}, ...]`
- Create `data/tts_finetune/host_v1/wavs/host_NNN.wav` — 24 kHz mono clips
- Create `experiments/modal_tts/__init__.py`
- Create `experiments/modal_tts/app.py` — Modal app (image, volume, train/synth functions)
- Create `experiments/modal_tts/train_f5.py` — pure F5-TTS training entrypoint (called from inside the container)
- Create `experiments/modal_tts/synthesize_f5.py` — pure inference entrypoint
- Create `experiments/modal_tts/cli.py` — local CLI (`upload-dataset`, `train`, `synthesize`, `download-checkpoint`)
- Create `experiments/modal_tts/README.md`
- Create `tests/modal_tts/test_dataset_builder.py`

**Out of scope for this spike:**
- Multi-speaker training
- Production wiring through the existing `qwen-tts-server` REST API
- Cost-tracking dashboards
- Any LoRA / full-finetune choice; we'll go with whatever the F5-TTS repo recommends as the default fine-tune recipe

---

## Task 1: Survey + select Host source runs

**Files:**
- Create: `scripts/build_host_dataset.py` (initial scaffold; selection logic only)

The job: pick which `bh_*` runs to draw from, based on whether Gemini kept the Host voice consistent. We have 23 candidate runs (336 min total). Bad runs have Host turns with F0 outside ~200–290 Hz (Sulafat range) or with detected_gender != female — these are voice-drift artefacts.

- [ ] **Step 1: Write the selection script**

Write `scripts/build_host_dataset.py`:

```python
"""Build a Host fine-tune dataset from clean Gemini renders.

Phase 1 of the F5-TTS spike. Walks all `data/runs/bh_*/manifest.json`,
picks Host turns whose audio passes an F0 sanity check, slices from
`audio/podcast.mp3`, and writes a manifest + 24kHz mono wavs.

Usage:
    uv run python scripts/build_host_dataset.py --target-minutes 20 \\
        --out data/tts_finetune/host_v1
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Gemini's Sulafat voice for Host. Empirically observed F0 range from the
# bh_trn_literary ref clip: 247 Hz median. Real RP female voices land 180–
# 280 Hz; widen slightly for headroom.
HOST_F0_MIN = 200
HOST_F0_MAX = 290
HOST_MIN_TURN_S = 4.0
HOST_MAX_TURN_S = 25.0


def find_candidate_runs(repo: Path) -> list[Path]:
    runs = sorted((repo / "data" / "runs").glob("bh_*/manifest.json"))
    return [p for p in runs if (p.parent / "audio" / "podcast.mp3").exists()
            or (p.parent / "audio" / "podcast.mp3").is_symlink()]


def host_turns(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for seg in manifest.get("segments", []):
        for t in seg.get("turns", []):
            if t.get("speaker") != "Host":
                continue
            s, e = t.get("start_ms"), t.get("end_ms")
            if s is None or e is None or e <= s:
                continue
            dur = (e - s) / 1000.0
            if dur < HOST_MIN_TURN_S or dur > HOST_MAX_TURN_S:
                continue
            out.append(t)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-minutes", type=float, default=20.0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    repo = Path(__file__).resolve().parent.parent
    runs = find_candidate_runs(repo)
    print(f"survey: {len(runs)} candidate runs with podcast.mp3")
    total = 0.0
    for r in runs:
        with r.open() as f:
            m = json.load(f)
        turns = host_turns(m)
        secs = sum((t["end_ms"] - t["start_ms"]) / 1000 for t in turns)
        total += secs
        print(f"  {r.parent.name:55s} {len(turns):3d} turns  {secs/60:5.1f} min")
    print(f"total: {total/60:.0f} min")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the survey**

```bash
uv run python scripts/build_host_dataset.py --target-minutes 20 --out /tmp/preview
```

Expected: prints a per-run breakdown. We just want to confirm the survey logic agrees with the earlier ad-hoc count (~336 min, 23 runs).

- [ ] **Step 3: Commit**

```bash
git add scripts/build_host_dataset.py
git commit -m "spike(f5tts): host dataset surveyor (no extraction yet)"
```

---

## Task 2: Extract clips with F0 sanity check

**Files:**
- Modify: `scripts/build_host_dataset.py`
- Create: `tests/modal_tts/test_dataset_builder.py`

For each candidate turn:
1. Slice `[start_ms + 2000, start_ms + 2000 + min(turn_dur - 2, 12)]` from podcast.mp3 (skip first 2 s to avoid Gemini drift-zone, cap at 12 s — F5-TTS likes shorter clips and we want diversity).
2. Resample to 24 kHz mono.
3. Run F0 check — librosa.pyin median must be in [HOST_F0_MIN, HOST_F0_MAX].
4. Take the verbatim text from the turn's utterances, joined.
5. Truncate text to match the clip duration proportion (same logic as `extract_refs.py`).
6. Stop once total duration reaches `--target-minutes`.

- [ ] **Step 1: Write a small test that exercises the F0 guard on a synthetic clip**

Write `tests/modal_tts/__init__.py` (empty), then `tests/modal_tts/test_dataset_builder.py`:

```python
"""F0 guard rejects out-of-range clips."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from scripts.build_host_dataset import f0_in_range, HOST_F0_MIN, HOST_F0_MAX


def _sine(hz: float, sr: int = 24000, dur_s: float = 1.0) -> np.ndarray:
    t = np.arange(int(sr * dur_s)) / sr
    # Add a tiny harmonic so pyin can detect F0 instead of returning unvoiced.
    return (0.6 * np.sin(2 * np.pi * hz * t)
            + 0.2 * np.sin(2 * np.pi * 2 * hz * t)).astype(np.float32)


def _write(path: Path, hz: float) -> None:
    sf.write(str(path), _sine(hz), 24000)


def test_f0_in_host_range_accepts(tmp_path: Path) -> None:
    p = tmp_path / "ok.wav"
    _write(p, 240.0)
    assert f0_in_range(p, HOST_F0_MIN, HOST_F0_MAX) is True


def test_f0_too_low_rejected(tmp_path: Path) -> None:
    p = tmp_path / "low.wav"
    _write(p, 130.0)  # male range
    assert f0_in_range(p, HOST_F0_MIN, HOST_F0_MAX) is False


def test_f0_too_high_rejected(tmp_path: Path) -> None:
    p = tmp_path / "high.wav"
    _write(p, 350.0)
    assert f0_in_range(p, HOST_F0_MIN, HOST_F0_MAX) is False
```

- [ ] **Step 2: Implement extraction**

Add to `scripts/build_host_dataset.py`:

```python
import re

import numpy as np
import soundfile as sf
from pydub import AudioSegment


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")


def f0_in_range(wav_path: Path, lo: float, hi: float) -> bool:
    """librosa.pyin median F0 lands in [lo, hi]. Returns False on unvoiced."""
    import librosa  # type: ignore[import-not-found]
    y, sr = librosa.load(str(wav_path), sr=24000, mono=True)
    f0, voiced, _ = librosa.pyin(y, fmin=60, fmax=400, sr=sr)
    vals = f0[voiced]
    if vals.size == 0:
        return False
    med = float(np.nanmedian(vals))
    return lo <= med <= hi


def _slice_clip(audio: AudioSegment, start_ms: int, duration_s: float) -> AudioSegment:
    end_ms = start_ms + int(duration_s * 1000)
    return audio[start_ms:end_ms].set_channels(1).set_frame_rate(24000)


def _trim_text(ref_text: str, frac: float) -> str:
    if frac >= 1.0 or not ref_text:
        return ref_text
    keep = int(len(ref_text) * frac)
    cut = ref_text.rfind(" ", 0, keep) if keep > 0 else 0
    return ref_text[:cut] if cut > 0 else ref_text


def extract_dataset(repo: Path, out_dir: Path, target_minutes: float) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    wav_dir = out_dir / "wavs"
    wav_dir.mkdir(exist_ok=True)

    runs = find_candidate_runs(repo)
    items: list[dict[str, Any]] = []
    rejected = {"f0_out_of_range": 0, "no_text": 0, "audio_load_fail": 0}
    total_s = 0.0
    target_s = target_minutes * 60.0

    for r_idx, r_path in enumerate(runs):
        if total_s >= target_s:
            break
        with r_path.open() as f:
            manifest = json.load(f)
        audio_path = (r_path.parent / "audio" / "podcast.mp3").resolve()
        try:
            audio = AudioSegment.from_file(str(audio_path))
        except Exception:
            rejected["audio_load_fail"] += 1
            continue

        for t_idx, t in enumerate(host_turns(manifest)):
            if total_s >= target_s:
                break
            start_ms = int(t["start_ms"])
            turn_dur_s = (t["end_ms"] - t["start_ms"]) / 1000.0
            # Skip the first 2 s of each turn (Gemini voice-drift zone).
            clip_dur_s = min(turn_dur_s - 2.0, 12.0)
            if clip_dur_s < 4.0:
                continue
            clip = _slice_clip(audio, start_ms + 2000, clip_dur_s)

            ref_text = " ".join(u.get("text", "") for u in t.get("utterances", [])).strip()
            if not ref_text:
                rejected["no_text"] += 1
                continue
            ref_text = _trim_text(ref_text, clip_dur_s / turn_dur_s)

            tag = f"{r_path.parent.name}_t{t_idx:03d}"
            wav_path = wav_dir / f"host_{_slug(tag)}.wav"
            clip.export(str(wav_path), format="wav")

            if not f0_in_range(wav_path, HOST_F0_MIN, HOST_F0_MAX):
                wav_path.unlink()
                rejected["f0_out_of_range"] += 1
                continue

            items.append({
                "wav": f"wavs/{wav_path.name}",
                "text": ref_text,
                "duration_s": clip_dur_s,
                "source_run": r_path.parent.name,
                "source_start_ms": start_ms,
            })
            total_s += clip_dur_s
            logger.info("  +%s (%.1fs, total %.1f min)", wav_path.name, clip_dur_s, total_s / 60)

    summary = {
        "total_clips": len(items),
        "total_seconds": total_s,
        "total_minutes": total_s / 60,
        "rejected": rejected,
        "items": items,
    }
    with (out_dir / "manifest.json").open("w") as f:
        json.dump(summary, f, indent=2)
    return summary
```

Update `main()` to call `extract_dataset` and print summary.

- [ ] **Step 3: Run test**

```bash
uv run pytest tests/modal_tts/test_dataset_builder.py -v
```

Expected: 3 passed.

- [ ] **Step 4: Run extraction**

```bash
uv run python scripts/build_host_dataset.py --target-minutes 20 --out data/tts_finetune/host_v1
```

Expected: ~120–180 clips (avg 6–10 s each), `manifest.json` with `total_minutes` ≈ 20, `rejected.f0_out_of_range` likely <30 (Gemini drift instances).

- [ ] **Step 5: Sanity check the manifest**

```bash
uv run python -c "
import json
m = json.load(open('data/tts_finetune/host_v1/manifest.json'))
print(f'clips: {m[\"total_clips\"]}, audio: {m[\"total_minutes\"]:.1f} min, rejected: {m[\"rejected\"]}')"
```

Stop here if `total_minutes < 15` or `rejected.f0_out_of_range > 50` — that means Gemini drift is bad enough that we need a different source strategy before fine-tuning.

- [ ] **Step 6: Commit**

```bash
git add scripts/build_host_dataset.py tests/modal_tts/
# DO NOT commit the wavs themselves — they're DVC-able outputs.
echo "data/tts_finetune/" >> .gitignore
git add .gitignore
git commit -m "spike(f5tts): host dataset extraction with F0 guard"
```

---

## Task 3: Modal app skeleton

**Files:**
- Create: `experiments/modal_tts/__init__.py`
- Create: `experiments/modal_tts/app.py`
- Create: `experiments/modal_tts/cli.py`
- Modify: `pyproject.toml` — add `modal` to deps

- [ ] **Step 1: Add Modal dep**

In `pyproject.toml`, add to `dependencies`:
```toml
    "modal>=0.66.0",
```

Then:
```bash
uv lock && uv sync
```

- [ ] **Step 2: Verify Modal credentials**

```bash
uv run modal token current
```

If "no token configured": run `uv run modal token new` and follow the browser flow. Stop and ask user if Modal account isn't set up.

- [ ] **Step 3: Write Modal app**

Write `experiments/modal_tts/__init__.py`:

```python
"""Modal-hosted F5-TTS fine-tuning + inference for BleakHouse personae.

See docs/superpowers/plans/2026-04-27-host-f5tts-finetune-spike.md.
"""
```

Write `experiments/modal_tts/app.py`:

```python
"""Modal app: F5-TTS train + synth, persisted in a single Modal volume.

Volume layout (`/vol`):
    base/                       F5-TTS base checkpoint cache
    datasets/<name>/            uploaded fine-tune datasets (wavs + manifest.json)
    checkpoints/<name>/         per-speaker fine-tuned checkpoints
    out/<name>/<utt_id>.wav     synthesised audio
"""
from __future__ import annotations

import modal

APP_NAME = "bleakhouse-f5tts"
VOLUME_NAME = "bleakhouse-f5tts-vol"

# F5-TTS lives here: https://github.com/SWivid/F5-TTS
# We pin the package version explicitly so train/synth are reproducible.
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg", "libsndfile1", "git")
    .pip_install(
        "f5-tts==0.3.4",            # CONFIRM: latest tag at plan-execution time
        "torch>=2.1.0",
        "torchaudio>=2.1.0",
        "soundfile>=0.12",
        "librosa>=0.10",
        "huggingface_hub>=0.24",
    )
)

vol = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)
app = modal.App(APP_NAME, image=image)


@app.function(
    gpu="L4",
    volumes={"/vol": vol},
    timeout=60 * 60 * 4,  # 4h hard cap
)
def train(dataset_name: str, ckpt_name: str, *, max_steps: int = 500, lr: float = 1e-5) -> dict:
    """Fine-tune F5-TTS on /vol/datasets/<dataset_name>; write to /vol/checkpoints/<ckpt_name>.

    See experiments/modal_tts/train_f5.py for the actual training loop —
    keep this function thin so we can iterate on training logic without
    rebuilding the Modal image.
    """
    from .train_f5 import run_finetune
    return run_finetune(
        dataset_dir="/vol/datasets/" + dataset_name,
        out_dir="/vol/checkpoints/" + ckpt_name,
        base_dir="/vol/base",
        max_steps=max_steps,
        lr=lr,
    )


@app.function(
    gpu="L4",
    volumes={"/vol": vol},
    timeout=60 * 10,
)
def synthesize(ckpt_name: str, text: str, ref_wav_relpath: str | None = None) -> bytes:
    """Generate one wav of `text` using the named checkpoint. Returns wav bytes."""
    from .synthesize_f5 import run_synth
    return run_synth(
        ckpt_dir="/vol/checkpoints/" + ckpt_name,
        text=text,
        base_dir="/vol/base",
        ref_wav=("/vol/datasets/" + ref_wav_relpath) if ref_wav_relpath else None,
    )


@app.function(volumes={"/vol": vol}, timeout=60 * 30)
def upload_dataset(dataset_name: str, files: dict[str, bytes]) -> dict:
    """Write a dataset into /vol/datasets/<dataset_name>/.

    `files` is a mapping of relative path -> bytes, e.g.
        {"manifest.json": b"...", "wavs/host_001.wav": b"..."}
    """
    from pathlib import Path
    root = Path("/vol/datasets") / dataset_name
    root.mkdir(parents=True, exist_ok=True)
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    vol.commit()
    return {"dataset_name": dataset_name, "n_files": len(files)}


@app.function(volumes={"/vol": vol}, timeout=60 * 5)
def list_volume() -> dict:
    """Quick sanity: list datasets + checkpoints on the volume."""
    from pathlib import Path
    root = Path("/vol")
    out: dict[str, list[str]] = {}
    for sub in ("base", "datasets", "checkpoints", "out"):
        d = root / sub
        out[sub] = sorted([p.name for p in d.iterdir()]) if d.exists() else []
    return out
```

Write `experiments/modal_tts/cli.py`:

```python
"""Local CLI to drive the Modal app from the Mac."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .app import app, list_volume, synthesize, train, upload_dataset


def cmd_upload(args: argparse.Namespace) -> int:
    src = Path(args.dataset_dir)
    if not src.is_dir():
        sys.exit(f"FAIL: {src} is not a directory")
    files = {}
    for p in src.rglob("*"):
        if p.is_file():
            files[str(p.relative_to(src))] = p.read_bytes()
    print(f"uploading {len(files)} files to dataset '{args.name}'")
    with app.run():
        result = upload_dataset.remote(args.name, files)
    print(json.dumps(result, indent=2))
    return 0


def cmd_train(args: argparse.Namespace) -> int:
    with app.run():
        result = train.remote(args.dataset, args.ckpt, max_steps=args.max_steps, lr=args.lr)
    print(json.dumps(result, indent=2))
    return 0


def cmd_synth(args: argparse.Namespace) -> int:
    with app.run():
        wav = synthesize.remote(args.ckpt, args.text, args.ref)
    Path(args.out).write_bytes(wav)
    print(f"wrote {args.out} ({len(wav)} bytes)")
    return 0


def cmd_ls(_args: argparse.Namespace) -> int:
    with app.run():
        result = list_volume.remote()
    print(json.dumps(result, indent=2))
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    u = sub.add_parser("upload", help="upload a local dataset dir to /vol/datasets/<name>")
    u.add_argument("--name", required=True)
    u.add_argument("--dataset-dir", required=True)
    u.set_defaults(fn=cmd_upload)

    t = sub.add_parser("train", help="run F5-TTS fine-tune on Modal")
    t.add_argument("--dataset", required=True)
    t.add_argument("--ckpt", required=True)
    t.add_argument("--max-steps", type=int, default=500)
    t.add_argument("--lr", type=float, default=1e-5)
    t.set_defaults(fn=cmd_train)

    s = sub.add_parser("synth", help="synthesize one wav with a fine-tuned checkpoint")
    s.add_argument("--ckpt", required=True)
    s.add_argument("--text", required=True)
    s.add_argument("--ref", default=None, help="optional reference wav path inside /vol/datasets")
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_synth)

    ls = sub.add_parser("ls", help="list /vol contents")
    ls.set_defaults(fn=cmd_ls)

    args = p.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Smoke-test the Modal harness with `ls`**

```bash
uv run python -m experiments.modal_tts.cli ls
```

Expected: empty dict — `{"base": [], "datasets": [], "checkpoints": [], "out": []}` and a charge of pennies. If this fails, the rest of the plan is blocked; debug Modal auth + image build before continuing.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock experiments/modal_tts/__init__.py experiments/modal_tts/app.py experiments/modal_tts/cli.py
git commit -m "spike(f5tts): modal app skeleton — image, volume, ls/upload/train/synth stubs"
```

---

## Task 4: Implement train_f5.py + synthesize_f5.py

**Files:**
- Create: `experiments/modal_tts/train_f5.py`
- Create: `experiments/modal_tts/synthesize_f5.py`

**Honest caveat at the top of this task:** F5-TTS's exact fine-tune API has been moving. The right move is to **read `f5_tts/train/finetune_cli.py` (or whatever name the version we pin uses)** and call its function directly rather than shelling out — this is the call site we want under our test gate. The pseudocode below is a sketch; consult the F5-TTS repo at the tagged version for the exact symbol names.

- [ ] **Step 1: Read the F5-TTS training entrypoint and confirm signatures**

```bash
# inside the Modal image we'll do this once, but we can also just look at:
# https://github.com/SWivid/F5-TTS/blob/v0.3.4/src/f5_tts/train/finetune_cli.py
# Note the function name(s) and required args.
```

Capture the exact symbol/path here in the plan before writing code:

```
F5-TTS finetune entrypoint: <FILL IN AFTER READING REPO>
Expected dataset format:    <FILL IN — usually JSON manifest with {wav, text, duration} per row>
Base checkpoint:             <FILL IN — typically downloaded via huggingface_hub from SWivid/F5-TTS>
```

If the F5-TTS API doesn't have a clean library entrypoint and only exposes a CLI, fall back to `subprocess.run([...])` from `train_f5.py` — but document the exact command line used and write a smoke test that asserts a non-zero number of training steps actually happened (look at the produced log file).

- [ ] **Step 2: Write `train_f5.py`**

Write `experiments/modal_tts/train_f5.py`. Skeleton — fill in the F5-TTS-specific bits from Step 1:

```python
"""Pure F5-TTS fine-tune entrypoint. Runs inside the Modal container."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def ensure_base_checkpoint(base_dir: Path) -> Path:
    """Download the F5-TTS base checkpoint to `base_dir` if not already there."""
    from huggingface_hub import snapshot_download
    base_dir.mkdir(parents=True, exist_ok=True)
    # SWivid/F5-TTS publishes base ckpts; pin a specific revision for repro.
    local = snapshot_download(
        repo_id="SWivid/F5-TTS",
        local_dir=str(base_dir),
        allow_patterns=["F5TTS_Base/*"],  # CONFIRM filename in repo
    )
    return Path(local)


def run_finetune(
    *,
    dataset_dir: str,
    out_dir: str,
    base_dir: str,
    max_steps: int = 500,
    lr: float = 1e-5,
) -> dict[str, Any]:
    dataset_path = Path(dataset_dir)
    manifest_path = dataset_path / "manifest.json"
    with manifest_path.open() as f:
        manifest = json.load(f)
    n_clips = manifest["total_clips"]
    total_minutes = manifest["total_minutes"]
    logger.info("dataset: %d clips, %.1f min", n_clips, total_minutes)

    base = ensure_base_checkpoint(Path(base_dir))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()

    # === F5-TTS finetune call ===
    # Replace this with the actual library call once Step 1 is done.
    from f5_tts.train.finetune_cli import main as finetune_main  # CONFIRM import path
    finetune_main([
        "--dataset", str(manifest_path),
        "--base", str(base),
        "--out", str(out),
        "--max-steps", str(max_steps),
        "--lr", str(lr),
    ])

    elapsed = time.perf_counter() - t0
    summary = {
        "dataset_dir": dataset_dir,
        "out_dir": out_dir,
        "n_clips": n_clips,
        "total_minutes": total_minutes,
        "max_steps": max_steps,
        "lr": lr,
        "wall_seconds": elapsed,
    }
    (out / "training_summary.json").write_text(json.dumps(summary, indent=2))
    return summary
```

- [ ] **Step 3: Write `synthesize_f5.py`**

```python
"""Pure F5-TTS inference entrypoint. Runs inside the Modal container."""
from __future__ import annotations

import io
import logging
from pathlib import Path

import soundfile as sf

logger = logging.getLogger(__name__)


def run_synth(
    *,
    ckpt_dir: str,
    text: str,
    base_dir: str,
    ref_wav: str | None = None,
) -> bytes:
    """Generate one wav from `text` using the fine-tuned checkpoint.

    F5-TTS still expects a reference wav at inference time (the speaker
    embedding pathway is part of the model). `ref_wav` defaults to
    `<ckpt_dir>/ref.wav` if not given — the training script should drop a
    canonical reference there.
    """
    from f5_tts.infer.utils_infer import (   # CONFIRM imports
        load_model,
        infer_process,
    )

    if ref_wav is None:
        candidate = Path(ckpt_dir) / "ref.wav"
        if not candidate.exists():
            raise FileNotFoundError(f"no ref_wav given and {candidate} missing")
        ref_wav = str(candidate)

    model = load_model(ckpt_dir=ckpt_dir, base_dir=base_dir)
    audio, sr = infer_process(model, ref_wav=ref_wav, text=text)

    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV")
    return buf.getvalue()
```

- [ ] **Step 4: Sanity check that the imports work in the image**

```bash
uv run python -m experiments.modal_tts.cli ls
# Then on the Modal side, exec a tiny smoke:
uv run modal run experiments.modal_tts.app::synthesize --help 2>&1 | head
```

If F5-TTS imports fail inside the Modal image, the most likely cause is a CUDA/torch version mismatch — pin specifically rather than using `>=`.

- [ ] **Step 5: Commit**

```bash
git add experiments/modal_tts/train_f5.py experiments/modal_tts/synthesize_f5.py
git commit -m "spike(f5tts): training + inference entrypoints (with F5-TTS API placeholders to confirm)"
```

---

## Task 5: Upload + train

**Files:** none (pure operation)

- [ ] **Step 1: Upload the dataset**

```bash
uv run python -m experiments.modal_tts.cli upload \
    --name host_v1 \
    --dataset-dir data/tts_finetune/host_v1
```

Expected: prints `{"dataset_name": "host_v1", "n_files": <ish 150>}`. Charge: pennies (small files).

- [ ] **Step 2: Run a tiny training smoke (50 steps)**

```bash
uv run python -m experiments.modal_tts.cli train \
    --dataset host_v1 \
    --ckpt host_v1_smoke \
    --max-steps 50
```

Expected: completes in <10 min, prints a `training_summary.json` with `wall_seconds < 600`. Verifies the F5-TTS API actually works in the image. If this fails, fix Task 4 before doing the real run.

- [ ] **Step 3: Run the real fine-tune (500 steps)**

```bash
uv run python -m experiments.modal_tts.cli train \
    --dataset host_v1 \
    --ckpt host_v1 \
    --max-steps 500
```

Expected: ~30–60 min on L4 (~$0.40–$0.80). Watch the Modal dashboard for the loss curve. Final loss should be lower than initial — if the curve is flat, training isn't doing anything (LR too low, dataset format wrong).

- [ ] **Step 4: Decision gate — was training healthy?**

Pass criteria:
- `training_summary.json` exists.
- Loss decreased.
- Modal cost on this run is under $1.50.

If yes → Task 6. If no → STOP and ask user how to proceed (more steps? higher LR? different dataset?).

---

## Task 6: A/B against Qwen baseline

**Files:**
- Create: `scripts/ab_listen.py` (helper to fetch matched test sentences)
- Create: `data/tts_finetune/host_v1/ab/` (output)

Pick 5 Host utterances from `bh_trn_literary` that are **not in the training set** (different turns from what we extracted), synthesize each via the fine-tune, place side-by-side with the Qwen utterance from `out/utterances/`.

- [ ] **Step 1: Pick test sentences**

Identify Host turns from `data/runs/bh_trn_literary/manifest.json` that were either:
- Excluded by our F0 filter, or
- Came after the 20-min target was reached (i.e., not in `host_v1/manifest.json`'s `items[].source_run` from `bh_trn_literary` for that turn index).

Pick 5 with text that's diagnostic for accent — sentences containing words like *Chancery*, *masterpiece*, *unhurried*, *shocked*, *worldview* — anything where the British/American distinction is audible (rhotic R, vowel quality, schwa).

Save as `data/tts_finetune/host_v1/ab/test_sentences.json`:
```json
[
  {"id": "ab_01", "text": "<sentence>", "qwen_wav": "<path under bh_trn_literary out/utterances/...>"},
  ...
]
```

- [ ] **Step 2: Synthesize each with the fine-tune**

```bash
for id in ab_01 ab_02 ab_03 ab_04 ab_05; do
    text=$(jq -r ".[] | select(.id==\"$id\") | .text" data/tts_finetune/host_v1/ab/test_sentences.json)
    uv run python -m experiments.modal_tts.cli synth \
        --ckpt host_v1 \
        --text "$text" \
        --out "data/tts_finetune/host_v1/ab/${id}_f5.wav"
done
```

- [ ] **Step 3: Pull matching Qwen wavs**

The `bh_trn_literary` job's per-utterance wavs live at:
```
ssh pop-os 'ls /var/lib/qwen-tts-server/jobs/ce969da2d83e411386dbc047fdce64a4/out/utterances/' | head
```

Match them by reading the per-utterance metadata from `data/runs/bh_trn_literary/audio/manifest_qwen.json` (`segments[*].utterances[*]` has `segment`, `turn`, `utt`, `text_chars`). For the closest text match per test sentence, scp:
```bash
scp pop-os:/var/lib/qwen-tts-server/jobs/ce969da2d83e411386dbc047fdce64a4/out/utterances/seg{S}_turn{T}_utt{U}.wav \
    data/tts_finetune/host_v1/ab/${id}_qwen.wav
```

- [ ] **Step 4: Listen**

```bash
open data/tts_finetune/host_v1/ab/
# play <id>_qwen.wav and <id>_f5.wav back to back; rate each on:
#   - accent fidelity (RP / British)
#   - voice match to the original Host
#   - naturalness / artefact-free
```

- [ ] **Step 5: Decision gate — does F5 win on accent?**

Pass criteria (subjective, single-listener — that's fine for a spike):
- Accent: F5 is at least as British as Qwen on ≥4/5 sentences.
- Voice match: F5 is recognisable as Host on ≥4/5 sentences.
- Naturalness: F5 has ≤Qwen artefact rate on ≥4/5 sentences.

- [ ] **Step 6: Write a one-pager findings note**

`docs/superpowers/notes/2026-04-27-host-f5tts-spike-findings.md` — what you did, total cost, what worked, what didn't, recommendation for or against multi-speaker rollout.

- [ ] **Step 7: Close the spike issue**

If pass: `bd close BleakHouse-ejc --reason="F5-TTS Host fine-tune wins A/B vs Qwen baseline on accent. See docs/superpowers/notes/...md. Filing follow-up for multi-speaker rollout."`

If fail: `bd close BleakHouse-ejc --reason="F5-TTS Host fine-tune did NOT win A/B (notes/...md). Next attempt: <RVC pipeline | XTTS-v2 | longer training | different ref-source>."`

Either way push:
```bash
git add docs/superpowers/notes/
git commit -m "spike(f5tts): host fine-tune findings"
git push
```

---

## Out of scope

- Multi-speaker fine-tuning (Eleanor Hartley, Blackstone, Caroline Woodcourt, etc.) — separate plan if this spike succeeds.
- Wiring F5-TTS into the existing `qwen-tts-server` REST API (the path stays Qwen until we have all four expert voices fine-tuned and validated).
- LoRA vs full fine-tune choice — go with whatever the F5-TTS repo recommends as the default. Optimisation comes later.
- Cost dashboards. We have a single $5 budget cap; manual eyeball is fine.
- Selecting the *best* base checkpoint among F5-TTS variants. Use the canonical English-trained one.
