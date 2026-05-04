"""Run both contexts paths on the same novel slice; emit metrics + heuristic.

Used for Task 3 (single-chapter sanity check on bleak_house) and Task 4
(full Oliver Twist measurement) of BleakHouse-1kg7.

Both paths run on the same input but write to separate files
(passages_contextual.{C,D}.json) so neither overwrites the other and
the comparison can be done after the fact.

The equivalence heuristic produces three metrics. **They are reported
as data, not a verdict** — the user reads the table and decides whether
to call it equivalent.

  1. Schema match: same JSON shape, same passage_ids in same order.
  2. Length ratio per passage: min/max char count of the two contexts.
  3. Cosine similarity on N sample passages, via OpenAI
     text-embedding-3-small (already a project dep; a few cents).

Usage:
    uv run python scripts/compare_context_paths.py --novel bleak_house --chapters c1
    uv run python scripts/compare_context_paths.py --novel oliver_twist
    uv run python scripts/compare_context_paths.py --novel bleak_house --skip-runs
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
EMBED_MODEL = "text-embedding-3-small"


def _run_C(novel: str, chapters: str | None) -> float:
    """Run path C (sync + cache); returns wall-clock seconds."""
    novel_dir = DATA_DIR / "novels" / novel
    out_path = novel_dir / "passages_contextual.json"
    out_path_C = novel_dir / "passages_contextual.C.json"
    if out_path.exists():
        out_path.unlink()
    cmd = ["uv", "run", "python", "-m", "enrichment.generate_contexts", "--novel", novel]
    if chapters:
        cmd.extend(["--chapters", chapters])
    logger.info("=== Path C: %s", " ".join(cmd))
    t0 = time.time()
    subprocess.run(cmd, check=True)
    elapsed = time.time() - t0
    if not out_path.exists():
        raise FileNotFoundError(f"Path C did not produce {out_path}")
    shutil.move(str(out_path), str(out_path_C))
    logger.info("Path C wrote %s in %.1fs", out_path_C, elapsed)
    return elapsed


def _run_D(novel: str, chapters: str | None) -> float:
    """Run path D (batch submit + collect); returns total wall-clock seconds."""
    novel_dir = DATA_DIR / "novels" / novel
    out_path = novel_dir / "passages_contextual.json"
    out_path_D = novel_dir / "passages_contextual.D.json"
    manifest_path = novel_dir / "context_batch_manifest.json"
    for stale in (out_path, out_path_D, manifest_path):
        if stale.exists():
            stale.unlink()

    submit_cmd = ["uv", "run", "python", "-m", "enrichment.submit_context_batch", "--novel", novel]
    if chapters:
        submit_cmd.extend(["--chapters", chapters])
    collect_cmd = ["uv", "run", "python", "-m", "enrichment.collect_context_batch", "--novel", novel]

    logger.info("=== Path D submit: %s", " ".join(submit_cmd))
    t0 = time.time()
    subprocess.run(submit_cmd, check=True)

    # Anthropic batches typically complete in a few minutes; poll-by-collect
    # until passages_contextual.json appears.
    logger.info("=== Path D collect (polling every 30s until batch ends): %s", " ".join(collect_cmd))
    while True:
        subprocess.run(collect_cmd, check=True)
        if out_path.exists():
            break
        # collect_context_batch logs a warning + early-returns if the batch
        # isn't complete; sleep and retry.
        time.sleep(30)
    elapsed = time.time() - t0
    shutil.move(str(out_path), str(out_path_D))
    logger.info("Path D wrote %s in %.1fs", out_path_D, elapsed)
    return elapsed


def _embed(client: OpenAI, texts: list[str]) -> np.ndarray:
    """Return an (N, D) array of L2-normalised embeddings."""
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    arr = np.array([d.embedding for d in resp.data], dtype=np.float64)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    return arr / np.where(norms == 0, 1, norms)


def _equivalence_heuristic(novel: str, sample_n: int) -> dict:
    """Schema match + length ratios + cosine similarity. No verdict; data only."""
    novel_dir = DATA_DIR / "novels" / novel
    c = json.loads((novel_dir / "passages_contextual.C.json").read_text())
    d = json.loads((novel_dir / "passages_contextual.D.json").read_text())

    if not isinstance(c, list) or not isinstance(d, list):
        return {"schema_match": False, "reason": "expected JSON arrays"}
    if len(c) != len(d):
        return {"schema_match": False, "reason": f"length mismatch: C={len(c)} D={len(d)}"}

    # Schema check: same passage_ids in the same order, both have non-empty `context` field.
    # Skip passages where neither has a context (they were filtered out of the run by --chapters).
    pairs = [
        (ci, di) for ci, di in zip(c, d, strict=True)
        if ci.get("context") or di.get("context")
    ]
    schema_ok = sum(
        1 for ci, di in pairs
        if ci.get("passage_id") == di.get("passage_id")
        and ci.get("context") and di.get("context")
    )
    schema_match = schema_ok == len(pairs)

    # Length ratio per pair
    length_ratios: list[float] = []
    for ci, di in pairs:
        cl = len(ci.get("context", ""))
        dl = len(di.get("context", ""))
        if max(cl, dl) > 0:
            length_ratios.append(min(cl, dl) / max(cl, dl))
    median_length_ratio = float(np.median(length_ratios)) if length_ratios else 0.0
    within_20pct = sum(1 for r in length_ratios if r >= 0.8)

    # Cosine similarity on a sample
    n_actual = min(sample_n, len(pairs))
    if n_actual == 0:
        return {
            "schema_match": False,
            "reason": "no comparable passages (both contexts empty)",
        }
    indices = np.linspace(0, len(pairs) - 1, n_actual, dtype=int)
    sample = [pairs[int(i)] for i in indices]

    load_dotenv()
    client = OpenAI()
    c_texts = [s[0]["context"] for s in sample]
    d_texts = [s[1]["context"] for s in sample]
    c_emb = _embed(client, c_texts)
    d_emb = _embed(client, d_texts)
    cos_sims = [float(np.dot(c_emb[i], d_emb[i])) for i in range(n_actual)]

    return {
        "schema_match": schema_match,
        "schema_pairs": f"{schema_ok}/{len(pairs)}",
        "length_within_20pct": f"{within_20pct}/{len(length_ratios)}",
        "length_median_ratio": round(median_length_ratio, 3),
        "cosine_median": round(float(np.median(cos_sims)), 3),
        "cosine_min": round(float(min(cos_sims)), 3),
        "cosine_sample_n": n_actual,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--novel", required=True)
    p.add_argument("--chapters", default=None, help="comma-separated chapter ids; default = whole novel")
    p.add_argument("--skip-runs", action="store_true",
                   help="skip running paths; only run heuristic on existing .C.json/.D.json")
    p.add_argument("--sample-n", type=int, default=10, help="cosine similarity sample size (default: 10)")
    args = p.parse_args()

    if not args.skip_runs:
        c_time = _run_C(args.novel, args.chapters)
        d_time = _run_D(args.novel, args.chapters)
    else:
        c_time = d_time = 0.0

    h = _equivalence_heuristic(args.novel, args.sample_n)

    print()
    print(f"# Comparison results — {args.novel}, chapters: {args.chapters or 'ALL'}")
    print()
    print("|             | C (sync+cache) | D (batch) |")
    print("|-------------|----------------|-----------|")
    print(f"| wall-clock  | {c_time:.1f}s          | {d_time:.1f}s     |")
    print()
    print("## Equivalence heuristic (C vs D)")
    for k, v in h.items():
        print(f"- {k}: {v}")


if __name__ == "__main__":
    main()
