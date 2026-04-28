"""Re-assess unverified citations in phase2_5_reading_list.json via a
Haiku-driven agent that wraps the source APIs as tools. Writes a sibling
phase2_5_reading_list_v2.json (does NOT modify the original).

The agent (claude-haiku-4-5) decides which tools to call (CrossRef,
Semantic Scholar, Fatcat, CiNii, legislation.gov.uk, CourtListener,
GovInfo, faculty pages) and emits a calibrated odds ratio of "real" vs
"confabulated" for each citation.

Promotion threshold: odds_real_to_confab >= --threshold (default 5.0).
Each entry receives `verification_odds`, `verification_source`,
`verification_url`, and `verification_summary` regardless of promotion.

Usage:
    uv run python scripts/web_verify_references.py --run cran_trn_literary_hostprep_retrofit_20260428T060147Z
    uv run python scripts/web_verify_references.py --all
    uv run python scripts/web_verify_references.py --all --limit 50 --threshold 10
"""
from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import sys
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from enrichment.refverify.agent import (
    DEFAULT_PROMOTE_THRESHOLD,
    Assessment,
    assess_citation,
)

logger = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parent.parent


def lists_to_process(args: argparse.Namespace) -> list[Path]:
    if args.run:
        p = REPO / "data" / "runs" / args.run / "phase2_5_reading_list.json"
        if not p.exists():
            sys.exit(f"FAIL: {p} not found")
        return [p]
    if args.all:
        return sorted((REPO / "data" / "runs").glob("*/phase2_5_reading_list.json"))
    sys.exit("FAIL: pass --run <id> or --all")


def _annotate(entry: dict, a: Assessment, *, promoted: bool) -> dict:
    entry = copy.deepcopy(entry)
    entry["verification_odds"] = a.odds_real_to_confab
    entry["verification_summary"] = a.evidence_summary
    entry["verification_tools_used"] = a.tools_used
    if promoted:
        entry["verified"] = True
        entry["verification_source"] = f"web:{a.matched_source}" if a.matched_source else "web"
        entry["verification_url"] = a.primary_url
    return entry


def reassess_list(
    rl_path: Path,
    client: anthropic.Anthropic,
    limit: int | None,
    threshold: float,
) -> dict:
    rl = json.loads(rl_path.read_text())
    unverified = rl.get("unverified", [])
    if limit:
        unverified = unverified[:limit]
    print(f"\n=== {rl_path.parent.name} ({len(unverified)} unverified) ===")

    promoted: list[dict] = []
    still_unverified: list[dict] = []

    for entry in unverified:
        raw = entry["raw_text"]
        a = assess_citation(raw, client=client)
        is_promoted = a.odds_real_to_confab >= threshold
        annotated = _annotate(entry, a, promoted=is_promoted)
        if is_promoted:
            promoted.append(annotated)
            src = a.matched_source or "?"
            print(f"  [{a.odds_real_to_confab:6.1f}× {src:18s}] {raw[:80]}")
        else:
            still_unverified.append(annotated)
            print(f"  [{a.odds_real_to_confab:6.2f}× — confab     ] {raw[:80]}")

    new_rl = copy.deepcopy(rl)
    new_rl["verified"] = (rl.get("verified", []) or []) + promoted
    new_rl["unverified"] = still_unverified + (rl.get("unverified", [])[len(unverified):] if limit else [])
    new_rl["total_verified"] = len(new_rl["verified"])
    if rl.get("total_proposed"):
        new_rl["verification_rate"] = round(
            new_rl["total_verified"] / rl["total_proposed"], 3
        )
    new_rl["web_verifier"] = {
        "applied_at": time.time(),
        "model": "claude-haiku-4-5",
        "threshold": threshold,
        "promoted": len(promoted),
        "still_unverified": len(still_unverified),
        "limit": limit,
    }

    out_path = rl_path.with_name("phase2_5_reading_list_v2.json")
    out_path.write_text(json.dumps(new_rl, indent=2))
    print(f"  → promoted {len(promoted)}/{len(unverified)} unverified  →  {out_path.name}")
    return {
        "list": rl_path.parent.name,
        "promoted": len(promoted),
        "still_unverified": len(still_unverified),
        "old_rate": rl.get("verification_rate"),
        "new_rate": new_rl.get("verification_rate"),
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", help="re-verify a single run's reading list")
    g.add_argument("--all", action="store_true",
                   help="re-verify every reading list in data/runs/")
    p.add_argument("--limit", type=int, default=None,
                   help="max unverified entries per list (sanity-check small batches)")
    p.add_argument("--threshold", type=float, default=DEFAULT_PROMOTE_THRESHOLD,
                   help=f"odds_real_to_confab threshold for promotion "
                        f"(default {DEFAULT_PROMOTE_THRESHOLD})")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    # Suppress noisy httpx INFO logs from per-tool calls
    logging.getLogger("httpx").setLevel(logging.WARNING)

    load_dotenv()
    if "ANTHROPIC_API_KEY" not in os.environ:
        sys.exit("FAIL: ANTHROPIC_API_KEY not set (Haiku agent needs it)")
    client = anthropic.Anthropic()

    lists = lists_to_process(args)
    summaries = []
    for rl_path in lists:
        summaries.append(reassess_list(rl_path, client, args.limit, args.threshold))

    print("\n=== summary ===")
    for s in summaries:
        old = f"{s['old_rate']:.0%}" if s['old_rate'] is not None else "?"
        new = f"{s['new_rate']:.0%}" if s['new_rate'] is not None else "?"
        print(f"  {s['list']:55s}  promoted={s['promoted']:3d}  rate {old} → {new}")
    total_promoted = sum(s["promoted"] for s in summaries)
    total_remaining = sum(s["still_unverified"] for s in summaries)
    print(f"  TOTAL  promoted={total_promoted}  still_unverified={total_remaining}")


if __name__ == "__main__":
    main()
