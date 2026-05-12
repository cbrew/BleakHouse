"""Run Stage 2 of o3ir, Tier S slice: listener_pick benchmark.

Compares 4 candidates on a fixture sampled from real reading-list
data:
- Anthropic Haiku 4.5 (current default, baseline)
- meta-llama/Meta-Llama-3.1-8B-Instruct on DeepInfra
- nvidia/NVIDIA-Nemotron-Nano-9B-v2 on DeepInfra
- google/gemma-3-4b-it on DeepInfra

Sampling: N reading lists with non-empty entries[] (≥5 candidates)
and a sensible recommended[] (3-8 items). Each fixture input
reconstructs the exact listener-pick prompt enrichment/host_prep.py
sends + uses the existing recommended[] as the baseline picks.

Metrics (from BleakHouse-0rtg listener_pick floor):
- schema_validity 1.0 (JSON-with-tags parses).
- set_overlap_jaccard ≥0.85 vs baseline.

Run:
    uv run python scripts/run_eval_listener_pick.py
    uv run python scripts/run_eval_listener_pick.py --n 10
    uv run python scripts/run_eval_listener_pick.py --seed 42
    uv run python scripts/run_eval_listener_pick.py --candidates haiku,llama
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from enrichment.axes import NOVEL_BY_ID, NOVEL_BY_KEY  # noqa: E402
from enrichment.host_prep import _LISTENER_PICK_SYSTEM  # noqa: E402
from enrichment.llm import settings  # noqa: E402
from enrichment.llm.eval import Fixture, FixtureInput, run_fixture  # noqa: E402
from enrichment.llm.types import ModelSpec  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("eval-listener-pick")

RUNS_ROOT = REPO_ROOT / "data" / "runs"
DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"

# Per-candidate ModelSpec for the eval task name (we use a separate
# task name per candidate so settings.register_task can rebind it
# without colliding with the existing 'listener_pick' default).
CANDIDATES: dict[str, ModelSpec] = {
    "haiku": ModelSpec(
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        hosting="anthropic",
    ),
    "llama": ModelSpec(
        provider="openai_compatible",
        model="meta-llama/Meta-Llama-3.1-8B-Instruct",
        hosting="deepinfra",
        base_url=DEEPINFRA_BASE_URL,
    ),
    "nemotron": ModelSpec(
        provider="openai_compatible",
        model="nvidia/NVIDIA-Nemotron-Nano-9B-v2",
        hosting="deepinfra",
        base_url=DEEPINFRA_BASE_URL,
    ),
    "gemma3": ModelSpec(
        provider="openai_compatible",
        model="google/gemma-3-4b-it",
        hosting="deepinfra",
        base_url=DEEPINFRA_BASE_URL,
    ),
}


def _novel_meta(run_dir: Path) -> tuple[str, str] | None:
    """Read run_manifest.json → (title, author). Supports both
    short-key and long-id forms in axes.novel."""
    manifest = run_dir / "run_manifest.json"
    if not manifest.exists():
        return None
    try:
        m = json.loads(manifest.read_text())
    except Exception:
        return None
    key = (m.get("axes") or {}).get("novel")
    if not key:
        return None
    novel = NOVEL_BY_KEY.get(key) or NOVEL_BY_ID.get(key)
    if novel is None:
        return None
    return novel.title, novel.author


def _format_candidates_user_message(entries: list[dict]) -> str:
    """Mirror enrichment/host_prep.py:_select_listener_recommendations
    line-builder so the fixture re-creates the exact prompt the LLM
    saw at host-prep time."""
    lines = [f"Candidates ({len(entries)}):"]
    for e in entries:
        tag = e.get("tag") or "ref-?"
        authors = ", ".join((e.get("authors") or [])[:2]) or "—"
        year = e.get("year") or "?"
        type_ = e.get("type") or "—"
        pub = e.get("publisher") or "—"
        cited = f"cited_by={e['cited_by']}" if e.get("cited_by") else ""
        lines.append(
            f"  [{tag}] {authors}. \"{e.get('title') or '(untitled)'}\" "
            f"({year}) [type={type_}, publisher={pub}] {cited}".rstrip()
        )
        if e.get("description"):
            lines.append(f"    {e['description'][:240]}")
    return "\n".join(lines)


def build_fixture(*, n: int, seed: int) -> Fixture:
    """Sample N reading lists with 'real' shape (≥5 entries, 3-8
    baseline picks) and build a Fixture with reconstructed prompts.
    Resolution_status='resolved' filter applied per the rewinnow
    behaviour."""
    rng = random.Random(seed)
    eligible: list[tuple[Path, dict]] = []
    for f in sorted(RUNS_ROOT.glob("*/phase2_5_reading_list.json")):
        try:
            payload = json.loads(f.read_text())
        except Exception:
            continue
        entries = payload.get("entries") or []
        recommended = payload.get("recommended") or []
        if len(entries) < 5 or not (3 <= len(recommended) <= 8):
            continue
        # The rewinnow pre-filter that sz5m used; mirrors host_prep's
        # post-jcsr setup so the candidate list matches what Haiku
        # would see today.
        resolved = [e for e in entries if e.get("resolution_status") == "resolved"]
        if len(resolved) < 5:
            continue
        eligible.append((f, payload))
    if len(eligible) < n:
        raise SystemExit(
            f"only {len(eligible)} eligible reading lists; "
            f"can't sample {n}"
        )
    sampled = rng.sample(eligible, n)

    inputs: list[FixtureInput] = []
    for path, payload in sampled:
        run_dir = path.parent
        run_id = run_dir.name
        novel = _novel_meta(run_dir)
        if novel is None:
            log.warning("skipping %s: no novel meta", run_id)
            continue
        title, author = novel
        entries = payload.get("entries") or []
        resolved = [e for e in entries if e.get("resolution_status") == "resolved"]
        baseline_tags = [e.get("tag") for e in (payload.get("recommended") or [])]
        baseline_tags = [t for t in baseline_tags if isinstance(t, str)]

        inputs.append(FixtureInput(
            id=f"{run_id}",
            system=_LISTENER_PICK_SYSTEM.format(
                novel_title=title, novel_author=author,
            ),
            user=_format_candidates_user_message(resolved),
            # max_tokens=4096: reasoning models (Nemotron-Nano-9B-v2)
            # emit reasoning_content separately from the answer content.
            # On large candidate lists their reasoning can consume 2k+
            # tokens before producing the JSON answer; 4096 leaves
            # headroom. Non-reasoning models finish at 'stop' long
            # before hitting the limit, so they pay no extra cost.
            max_tokens=4096,
            json_schema=None,   # listener-pick uses free-text JSON; not response_format constrained
            baseline={
                "tags": baseline_tags,
                "novel": title,
                "n_candidates": len(resolved),
            },
        ))

    return Fixture(
        task="listener_pick",
        description=(
            f"Stage 2 Tier S benchmark fixture for o3ir. "
            f"{len(inputs)} reading-list samples; "
            f"seed={seed}; baseline picks are the post-sz5m "
            f"recommended[] from each sampled phase2_5_reading_list.json."
        ),
        inputs=inputs,
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n", type=int, default=8, help="number of inputs in the fixture")
    p.add_argument("--seed", type=int, default=42, help="RNG seed for sampling")
    p.add_argument(
        "--candidates",
        type=str,
        default="haiku,llama,nemotron,gemma3",
        help="comma-separated candidate names from {haiku, llama, nemotron, gemma3}",
    )
    p.add_argument(
        "--run-id",
        type=str,
        default="stage2_tier_s_listener_pick",
        help="data/eval/<run-id>/ destination",
    )
    args = p.parse_args()

    load_dotenv()

    candidates = [c.strip() for c in args.candidates.split(",") if c.strip()]
    unknown = [c for c in candidates if c not in CANDIDATES]
    if unknown:
        raise SystemExit(f"unknown candidates: {unknown}; known: {list(CANDIDATES)}")

    log.info("building fixture: n=%d seed=%d", args.n, args.seed)
    fixture = build_fixture(n=args.n, seed=args.seed)
    log.info("fixture: %d inputs across novels", len(fixture.inputs))

    summary: dict[str, dict] = {}
    for name in candidates:
        spec = CANDIDATES[name]
        log.info("=== candidate %s (provider=%s model=%s hosting=%s) ===",
                 name, spec.provider, spec.model, spec.hosting)
        # Override the listener_pick task's ModelSpec for this candidate's run.
        settings.register_task("listener_pick", spec)
        t0 = time.time()
        try:
            result = run_fixture(
                fixture,
                run_id=f"{args.run_id}/{name}",
            )
            elapsed = time.time() - t0
            log.info(
                "  → outcome=%s schema_validity_mean=%.2f set_overlap_mean=%s cost=%s elapsed=%.1fs",
                result.outcome.value,
                result.schema_validity_mean,
                f"{result.set_overlap_mean:.3f}" if result.set_overlap_mean is not None else "n/a",
                f"${result.total_cost_usd:.4f}" if result.total_cost_usd else "unknown",
                elapsed,
            )
            summary[name] = {
                "outcome": result.outcome.value,
                "schema_validity_mean": result.schema_validity_mean,
                "set_overlap_mean": result.set_overlap_mean,
                "total_cost_usd": result.total_cost_usd,
                "elapsed_seconds": elapsed,
                "outcome_reason": result.outcome_reason,
                "provider": result.provider,
                "model": result.model,
                "hosting": result.hosting,
            }
        except Exception as exc:
            elapsed = time.time() - t0
            log.error("  candidate %s FAILED after %.1fs: %s", name, elapsed, exc)
            summary[name] = {
                "outcome": "error",
                "error": str(exc),
                "elapsed_seconds": elapsed,
            }

    log.info("=" * 60)
    log.info("SUMMARY")
    for name, data in summary.items():
        if "error" in data:
            log.info("  %-10s ERROR: %s", name, data["error"])
        else:
            log.info(
                "  %-10s outcome=%-12s overlap=%s cost=%s elapsed=%.1fs",
                name, data["outcome"],
                f"{data['set_overlap_mean']:.3f}" if data["set_overlap_mean"] is not None else "n/a",
                f"${data['total_cost_usd']:.4f}" if data["total_cost_usd"] else "unknown",
                data["elapsed_seconds"],
            )

    # Persist the summary alongside the per-candidate results.
    from enrichment.llm.eval.storage import save_results
    save_results(
        args.run_id, "summary",
        {
            "n_inputs": len(fixture.inputs),
            "seed": args.seed,
            "candidates": summary,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
