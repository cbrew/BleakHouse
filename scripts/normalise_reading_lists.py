"""Normalise phase2_5_reading_list.json files to a uniform shape.

Canonical shape: every entry in `recommended` is a dict with at least
{title, authors, year}. The webapp renders dicts only; no string-vs-dict
branching at the view layer.

Four states of legacy data observed (audit 2026-04-30):

  A. clean-string (string, n=3-8, has year markers)
     Pre-schema-version-2 producer that emitted preformatted citation
     strings ('Authors, Title (Year)').
     ACTION: parse each string into a {title, authors, year} dict.

  B. clean-dict (dict, n<=8)
     Schema-v2 producer's output, possibly already filtered.
     ACTION: leave alone.

  C. unwinnowed (dict, n>8)
     Retrofit dirs that wrote `entries[]` and `recommended[]` containing
     the full unwinnowed candidate set. The listener-friendly Haiku
     filter never ran (or ran on an empty entries list and no-op'd).
     ACTION: run the winnower; replace `recommended` with the picked
     subset.

  D. refusal-prose (string, looks like prose, no year markers)
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


def lookup_in_verified(
    raw_text: str, verified: list[dict[str, Any]]
) -> dict[str, Any]:
    """Convert a recommended-string into a citation dict by reaching back into
    `verified[]`. Each verified entry carries the source raw_text plus optional
    openalex metadata; we use the metadata where it exists, fall back to the
    raw_text for display.
    """
    match = next((v for v in verified if v.get("raw_text") == raw_text), None)
    if match is None:
        return {"display": raw_text, "url": None}
    title = match.get("openalex_title") or ""
    authors = match.get("openalex_authors") or []
    year = match.get("openalex_year")
    doi = (match.get("openalex_doi") or "").strip()
    url = f"https://doi.org/{doi}" if doi else None
    return {
        "display": raw_text,
        "title": title or None,
        "authors": authors,
        "year": year,
        "url": url,
        "verification_source": match.get("verification_source"),
    }


def to_display_dict(rec: dict[str, Any]) -> dict[str, Any]:
    """Reduce a CitationRecord-style dict to the uniform display shape.

    Keeps title/authors/year/url; drops noise fields (description, type,
    publisher, parent_tag, audience). URL is gated to http(s) only — some
    legacy entries carried 'wiki-fr:https://...' tag-prefixes that aren't
    navigable.
    """
    title = rec.get("title")
    authors = rec.get("authors") or []
    year = rec.get("year")
    url = rec.get("url") or ""
    if url and not (url.startswith("http://") or url.startswith("https://")):
        url = ""
    parts: list[str] = []
    if authors:
        parts.append(", ".join(authors[:3]))
    if title:
        parts.append(title)
    head = ", ".join(parts) if parts else (title or "")
    if year:
        head = f"{head} ({year})"
    return {
        "display": head,
        "title": title,
        "authors": authors,
        "year": year,
        "url": url or None,
    }


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
        records, novel_title, novel_author,
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

    if state == "empty":
        return "skip-empty"

    if state == "dict-clean":
        # Re-shape to the uniform display schema {display, title, authors, year, url}.
        # Already-dict entries lose their description / type / publisher / etc.
        # (noise) but keep their structured fields.
        sample = payload["recommended"][0]
        if "display" in sample:
            return "skip-dict-clean"
        payload["recommended"] = [to_display_dict(r) for r in payload["recommended"]]
        if not dry_run:
            rl_path.write_text(json.dumps(payload, indent=2))
        return f"reshape-dict-{len(payload['recommended'])}"

    if state == "string-clean":
        # Look up each string in verified[] for openalex enrichment; fall
        # back to raw_text only if no match. Either way the canonical
        # display is the original citation string the expert wrote.
        verified = payload.get("verified") or []
        payload["recommended"] = [
            lookup_in_verified(s, verified) for s in payload["recommended"]
        ]
        if not dry_run:
            rl_path.write_text(json.dumps(payload, indent=2))
        return f"upstream-lookup-{len(payload['recommended'])}"

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
