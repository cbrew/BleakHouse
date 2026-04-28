"""Re-verify unverified citations in phase2_5_reading_list.json files via a
multi-source web verifier. Writes a sibling phase2_5_reading_list_v2.json
(does NOT modify the original).

Free no-auth sources: CrossRef, Semantic Scholar, Fatcat, CiNii,
legislation.gov.uk. Auth-optional: CourtListener, GovInfo (read from .env).

LLM judge biased toward NO MATCH: we'd rather miss a real citation than
fake-verify a pastiche. High precision is the primary requirement.

Usage:
    uv run python scripts/web_verify_references.py --run cran_trn_literary_hostprep_retrofit_20260428T060147Z
    uv run python scripts/web_verify_references.py --all
    uv run python scripts/web_verify_references.py --all --limit 50
"""
from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from enrichment.refverify.verify import verify_citation

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


def reverify_list(rl_path: Path, client: anthropic.Anthropic, limit: int | None) -> dict:
    rl = json.loads(rl_path.read_text())
    unverified = rl.get("unverified", [])
    if limit:
        unverified = unverified[:limit]
    print(f"\n=== {rl_path.parent.name} ({len(unverified)} unverified) ===")

    new_rl = copy.deepcopy(rl)
    promoted: list[dict] = []
    still_unverified: list[dict] = []

    for entry in unverified:
        raw = entry["raw_text"]
        result = verify_citation(raw, client=client)
        if result.verified:
            entry = copy.deepcopy(entry)
            entry["verified"] = True
            entry["verification_source"] = f"web:{result.source}"
            entry["verification_url"] = result.url
            promoted.append(entry)
            print(f"  [{result.source:18s}] {raw[:90]}")
        else:
            still_unverified.append(entry)
        time.sleep(0.3)  # be polite to free APIs

    new_rl["verified"] = (rl.get("verified", []) or []) + promoted
    new_rl["unverified"] = still_unverified + (rl.get("unverified", [])[len(unverified):] if limit else [])
    new_rl["total_verified"] = len(new_rl["verified"])
    if rl.get("total_proposed"):
        new_rl["verification_rate"] = round(
            new_rl["total_verified"] / rl["total_proposed"], 3
        )
    new_rl["web_verifier"] = {
        "applied_at": time.time(),
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
    g.add_argument("--all", action="store_true", help="re-verify every reading list in data/runs/")
    p.add_argument("--limit", type=int, default=None,
                   help="max unverified entries per list (sanity-check small batches)")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    load_dotenv()
    import os
    if "ANTHROPIC_API_KEY" not in os.environ:
        sys.exit("FAIL: ANTHROPIC_API_KEY not set (judge needs it)")
    client = anthropic.Anthropic()

    lists = lists_to_process(args)
    summaries = []
    for rl_path in lists:
        summaries.append(reverify_list(rl_path, client, args.limit))

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
