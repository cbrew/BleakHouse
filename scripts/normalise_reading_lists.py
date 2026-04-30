"""Normalise phase2_5_reading_list.json files to a uniform shape.

Three states of legacy data observed (audit 2026-04-30):

  A. clean (string, n=3-8)
     Already winnowed by enrichment.host_prep._select_listener_recommendations.
     `recommended` is a list of preformatted citation strings.
     ACTION: leave alone.

  B. unwinnowed (dict, n=27-82)
     Retrofit dirs that wrote `entries[]` and `recommended[]` containing
     the full unwinnowed candidate set. The listener-friendly Haiku
     filter never ran (or ran on an empty entries list and no-op'd).
     ACTION: run the winnower; replace `recommended` with the picked
     subset (still dict-shape so the webapp's existing renderer handles it).

  C. refusal-prose (string, looks like prose, no year markers)
     The Haiku refused to pick any candidates and its prose response
     leaked into `recommended[]` as multiple sentences.
     ACTION: collapse the prose into a `winnower_note` field; set
     `recommended` to []. The webapp renders the note instead of bullets.

Idempotent. Re-run after the next host-prep refresh.

Usage:
    uv run python scripts/normalise_reading_lists.py --all
    uv run python scripts/normalise_reading_lists.py --run <run_id>
    uv run python scripts/normalise_reading_lists.py --all --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "data" / "runs"
READING_LIST_NAME = "phase2_5_reading_list.json"
YEAR_RE = re.compile(r"\b(1[5-9]|20)\d{2}\b")


def _detect_state(payload: dict[str, Any]) -> str:
    recs = payload.get("recommended") or []
    if not recs:
        return "empty"
    first = recs[0]
    if isinstance(first, dict):
        return "dict-unwinnowed" if len(recs) > 8 else "dict-clean"
    if isinstance(first, str):
        looks_like_citation = sum(
            1 for r in recs
            if isinstance(r, str) and YEAR_RE.search(r) and len(r) <= 240
        )
        return "string-clean" if looks_like_citation >= len(recs) // 2 else "refusal-prose"
    return "unknown"


def _config_for_run(run_dir: Path) -> tuple[str, str]:
    cfg_path = run_dir / "config.json"
    if not cfg_path.exists():
        return ("Unknown", "Unknown")
    cfg = json.loads(cfg_path.read_text())
    novel_id = cfg.get("novel", "")
    from enrichment import axes  # noqa: PLC0415  pyright: ignore[reportMissingImports]
    novel = axes.NOVEL_BY_ID.get(novel_id) or axes.NOVEL_BY_KEY.get(novel_id)
    if novel is not None:
        return (novel.title, novel.author)
    return (novel_id or "Unknown", "Unknown")


def _winnow_dict_list(
    client: anthropic.Anthropic,
    candidates: list[dict[str, Any]],
    novel_title: str,
    novel_author: str,
) -> list[str]:
    """Run the host_prep listener filter on dict-shape candidates."""
    from enrichment.host_prep import _select_listener_recommendations  # noqa: PLC0415  pyright: ignore[reportMissingImports]
    from enrichment.reference_tools import CitationRecord  # noqa: PLC0415  pyright: ignore[reportMissingImports]

    records = []
    for c in candidates:
        try:
            records.append(CitationRecord(**c))
        except TypeError:
            # Fall back to skipping malformed entries.
            continue
    return _select_listener_recommendations(
        client, records, novel_title, novel_author,
    )


def normalise_run(
    run_id: str,
    client: anthropic.Anthropic | None,
    *, dry_run: bool = False,
) -> str:
    """Normalise one run's reading list. Returns the action taken."""
    run_dir = RUNS_DIR / run_id
    rl_path = run_dir / READING_LIST_NAME
    if not rl_path.exists():
        return "no-file"
    payload = json.loads(rl_path.read_text())
    state = _detect_state(payload)

    if state in ("empty", "string-clean", "dict-clean"):
        return f"skip-{state}"

    if state == "refusal-prose":
        prose = "\n".join(s for s in payload["recommended"] if isinstance(s, str))
        payload["recommended"] = []
        payload["winnower_note"] = prose.strip()
        if not dry_run:
            rl_path.write_text(json.dumps(payload, indent=2))
        return "rewrite-refusal"

    if state == "dict-unwinnowed":
        if client is None:
            return "skip-dry-no-client"
        novel_title, novel_author = _config_for_run(run_dir)
        candidates = payload["recommended"]
        picked_tags = _winnow_dict_list(client, candidates, novel_title, novel_author)
        pick_set = set(picked_tags)
        new_recommended = [c for c in candidates if c.get("tag") in pick_set]
        # Preserve full list in entries[] for audit if it isn't already there.
        if not payload.get("entries"):
            payload["entries"] = candidates
        payload["recommended"] = new_recommended
        if not dry_run:
            rl_path.write_text(json.dumps(payload, indent=2))
        return f"winnow-{len(candidates)}->{len(new_recommended)}"

    return f"unknown-{state}"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", help="single run-id")
    g.add_argument("--all", action="store_true", help="normalise every run dir")
    parser.add_argument("--dry-run", action="store_true",
                        help="report actions without writing")
    args = parser.parse_args()

    if args.run:
        runs = [args.run]
    else:
        runs = sorted(
            p.name for p in RUNS_DIR.iterdir()
            if p.is_dir() and p.name != "_archive"
            and (p / READING_LIST_NAME).exists()
        )

    client = None
    if not args.dry_run:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    counts: dict[str, int] = {}
    for r in runs:
        action = normalise_run(r, client, dry_run=args.dry_run)
        counts[action] = counts.get(action, 0) + 1
        if not action.startswith("skip"):
            logger.info("  %s %s", action, r)
        time.sleep(0.2)
    label = "would do" if args.dry_run else "did"
    logger.info("%s:", label)
    for k, n in sorted(counts.items()):
        logger.info("  %5d %s", n, k)


if __name__ == "__main__":
    main()
