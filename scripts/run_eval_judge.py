"""LLM-as-judge pass over saved per-input candidate results.

Reads data/eval/<run-id>/<candidate>/listener_pick.json for each
candidate, re-builds the fixture (so we can recover the
candidate_list_text the judge needs to see), runs the judge on each
input × candidate pair, persists judge results.

The candidate generations stay fixed — we don't re-call them. Only
the judge (Haiku) makes new API calls. ~32 judge calls for 4
candidates × 8 inputs ≈ ~$0.04.

Run:
    uv run python scripts/run_eval_judge.py
    uv run python scripts/run_eval_judge.py --run-id stage2_tier_s_listener_pick --seed 42 --n 8
    uv run python scripts/run_eval_judge.py --candidates haiku,llama
"""
from __future__ import annotations

import argparse
import logging
import statistics
import sys
import time
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from enrichment.llm.eval.judge import judge_listener_pick  # noqa: E402
from enrichment.llm.eval.storage import save_results, load_results  # noqa: E402
from scripts.run_eval_listener_pick import build_fixture  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("eval-judge")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-id", type=str, default="stage2_tier_s_listener_pick")
    p.add_argument("--n", type=int, default=8)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--candidates", type=str,
        default="haiku,llama,nemotron,gemma3",
        help="comma-separated candidate names",
    )
    args = p.parse_args()

    load_dotenv()

    candidates = [c.strip() for c in args.candidates.split(",") if c.strip()]

    log.info("rebuilding fixture (same seed) to recover input texts: n=%d seed=%d",
             args.n, args.seed)
    fixture = build_fixture(n=args.n, seed=args.seed)
    # Map fixture inputs by id so we can join with saved per-input results.
    by_id = {inp.id: inp for inp in fixture.inputs}

    per_candidate_judge: dict[str, list[dict]] = {}

    for cand_name in candidates:
        log.info("=== judging candidate: %s ===", cand_name)
        try:
            saved = load_results(f"{args.run_id}/{cand_name}", "listener_pick")
        except FileNotFoundError:
            log.warning("  no saved results for %s; skipping", cand_name)
            continue

        judgements: list[dict] = []
        t0 = time.time()
        for per_input in saved.get("per_input", []):
            inp_id = per_input["id"]
            cand_text = per_input.get("text") or ""
            fix_inp = by_id.get(inp_id)
            if fix_inp is None:
                log.warning("  no fixture input matching id=%s; skipping", inp_id)
                continue
            novel_title = (fix_inp.baseline or {}).get("novel", "(unknown novel)")
            result = judge_listener_pick(
                input_id=inp_id,
                novel_title=novel_title,
                candidate_list_text=fix_inp.user,
                candidate_output_text=cand_text,
            )
            log.info(
                "  %s rating=%s justification=%r",
                inp_id[:30], result.rating, result.justification[:80],
            )
            judgements.append(asdict(result))

        elapsed = time.time() - t0
        ratings = [j["rating"] for j in judgements if j["rating"] != -1]
        parse_failures = sum(1 for j in judgements if j["rating"] == -1)
        per_candidate_judge[cand_name] = judgements

        mean = statistics.mean(ratings) if ratings else None
        log.info(
            "  → %d inputs judged, %d parse_failures, mean_rating=%s elapsed=%.1fs",
            len(judgements), parse_failures,
            f"{mean:.2f}" if mean else "n/a",
            elapsed,
        )

        save_results(
            f"{args.run_id}/{cand_name}",
            "judge",
            {
                "n_inputs": len(judgements),
                "parse_failures": parse_failures,
                "mean_rating": mean,
                "judgements": judgements,
            },
        )

    # Summary across all candidates.
    log.info("=" * 60)
    log.info("JUDGE SUMMARY")
    summary: dict[str, dict] = {}
    for cand_name, judgements in per_candidate_judge.items():
        ratings = [j["rating"] for j in judgements if j["rating"] != -1]
        mean = statistics.mean(ratings) if ratings else None
        median = statistics.median(ratings) if ratings else None
        dist = {r: ratings.count(r) for r in (1, 2, 3, 4, 5)}
        summary[cand_name] = {
            "n": len(judgements),
            "parse_failures": sum(1 for j in judgements if j["rating"] == -1),
            "mean": mean,
            "median": median,
            "distribution_1_2_3_4_5": [dist[r] for r in (1, 2, 3, 4, 5)],
        }
        log.info(
            "  %-10s n=%d failures=%d mean=%s median=%s dist=%s",
            cand_name,
            len(judgements),
            summary[cand_name]["parse_failures"],
            f"{mean:.2f}" if mean else "n/a",
            f"{median:.1f}" if median is not None else "n/a",
            summary[cand_name]["distribution_1_2_3_4_5"],
        )

    save_results(args.run_id, "judge_summary", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
