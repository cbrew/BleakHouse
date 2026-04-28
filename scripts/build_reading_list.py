"""Build a listener-facing reading list from a run's proposed citations.

For each proposed citation, the agent (clean → OpenAlex+Wikipedia → judge,
plus a third Haiku call to mine Wikipedia further-reading sections when
the match lands on Wikipedia) produces a rich entry with title, authors,
year, type, publisher, description, audience tag, URL, and any
further-reading items the article itself cites.

Input:  data/runs/<id>/phase2_5_reading_list.json — we recover the
        proposed-citation set from its union of verified[] + unverified[]
        and re-run the agent on every entry.
Output: data/runs/<id>/reading_list.json — the listener artefact.

Usage:
    uv run python scripts/build_reading_list.py --run <run-id>
    uv run python scripts/build_reading_list.py --all
    uv run python scripts/build_reading_list.py --all --limit 5
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import os
import sys
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from enrichment.refverify import ReadingListEntry, assess_citation

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


def _entry_payload(e: ReadingListEntry) -> dict:
    return {
        "raw_text": e.raw_text,
        "title": e.title,
        "authors": e.authors,
        "year": e.year,
        "type": e.type,
        "publisher": e.publisher,
        "description": e.description,
        "cited_by": e.cited_by,
        "url": e.url,
        "source": e.source,
        "audience": e.audience,
        "further_reading": e.further_reading,
    }


def build_for_list(
    rl_path: Path,
    client: anthropic.Anthropic,
    limit: int | None,
) -> dict:
    """Build a reading_list.json for a single run directory."""
    rl = json.loads(rl_path.read_text())
    # Recover the proposed-citation set from the legacy output's union.
    proposed = list(rl.get("verified", []) or []) + list(rl.get("unverified", []) or [])
    # Deduplicate by raw_text (legacy may have stored the same citation
    # under both buckets if it was re-checked).
    seen: set[str] = set()
    unique: list[dict] = []
    for entry in proposed:
        raw = entry.get("raw_text")
        if not raw or raw in seen:
            continue
        seen.add(raw)
        unique.append(entry)

    if limit:
        unique = unique[:limit]

    print(f"\n=== {rl_path.parent.name} ({len(unique)} citations) ===")

    entries: list[dict] = []
    dropped: list[dict] = []
    total_in = 0
    total_out = 0
    total_calls = 0
    started = time.monotonic()

    for entry in unique:
        raw = entry["raw_text"]
        t0 = time.monotonic()
        e = assess_citation(raw, client=client)
        dt = time.monotonic() - t0
        total_in += e.input_tokens
        total_out += e.output_tokens
        total_calls += e.haiku_calls
        if e.verified:
            entries.append(_entry_payload(e))
            print(
                f"  [{e.audience or '?':9s} {e.source or '?':10s}] "
                f"({dt:4.1f}s, {e.haiku_calls}c, ${e.cost_usd:.4f})  "
                f"{(e.title or '')[:70]}"
            )
        else:
            dropped.append({"raw_text": raw})
            print(
                f"  [drop                            ] "
                f"({dt:4.1f}s, {e.haiku_calls}c, ${e.cost_usd:.4f})  "
                f"{raw[:70]}"
            )

    elapsed = time.monotonic() - started
    cost = (total_in * 1.00 + total_out * 5.00) / 1_000_000

    out = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "model": "claude-haiku-4-5",
        "sources": ["openalex", "wikipedia"],
        "stats": {
            "total_proposed": len(unique),
            "total_verified": len(entries),
            "total_dropped": len(dropped),
            "haiku_calls": total_calls,
            "input_tokens": total_in,
            "output_tokens": total_out,
            "cost_usd": round(cost, 4),
            "elapsed_seconds": round(elapsed, 1),
        },
        "entries": entries,
        "dropped": dropped,
    }
    out_path = rl_path.with_name("reading_list.json")
    out_path.write_text(json.dumps(out, indent=2))
    print(
        f"  → {len(entries)}/{len(unique)} verified "
        f"({elapsed:.1f}s, {total_calls} haiku calls, "
        f"{total_in + total_out:,} tok, ${cost:.3f})  →  {out_path.name}"
    )
    return {
        "list": rl_path.parent.name,
        "verified": len(entries),
        "dropped": len(dropped),
        "total": len(unique),
        "input_tokens": total_in,
        "output_tokens": total_out,
        "haiku_calls": total_calls,
        "cost_usd": cost,
        "elapsed_seconds": elapsed,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", help="build a single run's reading list")
    g.add_argument("--all", action="store_true",
                   help="build a reading list for every run in data/runs/")
    p.add_argument("--limit", type=int, default=None,
                   help="cap citations per list (sanity-check small batches)")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    load_dotenv()
    if "ANTHROPIC_API_KEY" not in os.environ:
        sys.exit("FAIL: ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic()

    lists = lists_to_process(args)
    summaries = [build_for_list(rl_path, client, args.limit) for rl_path in lists]

    print("\n=== summary ===")
    for s in summaries:
        rate = s["verified"] / s["total"] if s["total"] else 0.0
        print(
            f"  {s['list']:55s}  {s['verified']:3d}/{s['total']:<3d} ({rate:.0%})  "
            f"({s['elapsed_seconds']:5.1f}s, ${s['cost_usd']:.3f})"
        )
    t_verified = sum(s["verified"] for s in summaries)
    t_total = sum(s["total"] for s in summaries)
    t_in = sum(s["input_tokens"] for s in summaries)
    t_out = sum(s["output_tokens"] for s in summaries)
    t_calls = sum(s["haiku_calls"] for s in summaries)
    t_cost = sum(s["cost_usd"] for s in summaries)
    t_time = sum(s["elapsed_seconds"] for s in summaries)
    rate = t_verified / t_total if t_total else 0.0
    print(
        f"  TOTAL  {t_verified}/{t_total} verified ({rate:.0%}, "
        f"{t_total - t_verified} dropped)"
    )
    print(
        f"  COST   {t_calls} haiku calls, "
        f"{t_in:,} in + {t_out:,} out tok, "
        f"${t_cost:.3f} ({t_time:.1f}s)"
    )
    if t_total:
        print(
            f"  AVG    ${t_cost / t_total:.4f}/citation, "
            f"{(t_in + t_out) / t_total:,.0f} tok/citation, "
            f"{t_time / t_total:.1f}s/citation"
        )


if __name__ == "__main__":
    main()
