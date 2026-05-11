"""Backfill every existing phase2_5_reading_list.json through the
verification cascade from BleakHouse-5ccr.

Distinct from scripts/backfill_reading_lists.py, which generates
reading lists for runs that didn't get host-prep. This script
modifies in place: every entry in every existing reading list is
run through the cascade so the `url` field is either a HEAD-
verified link or '' with resolution_status='unresolved' + the
attempted-list preserved.

Per run:
  1. Walk the `entries` array (new schema) or `verified` (legacy
     schema; same shape modulo field names).
  2. For each item, build a CandidateReference. The wiki-fr: URLs
     the pre-hgws pipeline minted are rejected by the cascade's
     _is_real_url precondition; existing identifiers (DOI, real
     URL, ISBN via openlibrary.org/isbn/) feed the cascade's fast
     paths.
  3. Record either a verified url + resolution_source, or
     resolution_status='unresolved' with attempted + reason.
  4. Filter the existing `recommended` list to resolved survivors.
     Top up to 5 from other resolved entries in their original
     order (cheaper than re-running the LLM winnower, and the
     pipeline's original ordering already reflects considered choice).
  5. Write the file back atomically.

Restartable: re-running on an already-backfilled run is fast
(verification cache hits) and idempotent. The sqlite cache at
data/reference_verify_cache.sqlite3 amortises duplicate references
across runs (many novels share Wikipedia bibliography entries).

Run:
    uv run python scripts/verify_reading_list_urls.py
    uv run python scripts/verify_reading_list_urls.py --runs bh_trn_literary_hostprep
    uv run python scripts/verify_reading_list_urls.py --workers 12
    uv run python scripts/verify_reading_list_urls.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from enrichment.reference_verify import (  # noqa: E402
    CandidateReference, ReferenceVerifier, ResolverResult,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("verify-rls")

RUNS_ROOT = REPO_ROOT / "data" / "runs"


# ── per-item conversion ───────────────────────────────────────────────


def _entry_to_candidate(entry: dict) -> CandidateReference:
    """Translate a reading-list entry into a CandidateReference.

    Handles both new-schema (title/authors/year/doi/url) and legacy
    (raw_text/openalex_*). The cascade's preconditions reject wiki-fr:
    and other synthetic schemes via _is_real_url; we pass whatever
    the entry has and let the cascade decide.
    """
    title = (entry.get("title") or "").strip()
    authors = entry.get("authors") or []

    # Legacy schema fallbacks
    if not title:
        title = (entry.get("openalex_title") or "").strip()
    if not authors:
        authors = entry.get("openalex_authors") or []
    if not title:
        title = (entry.get("raw_text") or "").strip()

    year = entry.get("year") or entry.get("openalex_year")
    if isinstance(year, str):
        try:
            year = int(year)
        except ValueError:
            year = None
    if not isinstance(year, int):
        year = None

    doi = (entry.get("doi") or entry.get("openalex_doi") or "").strip()
    # On re-runs, prefer the preserved pre-backfill URL (raw_url) over
    # the current url, which is the *result* of a previous cascade run.
    # Feeding the previous result back as raw_url would short-circuit
    # the cascade through the raw_url step and re-admit any URL that
    # still HEAD-200s — including foreign-catalog soft-404 pages.
    raw_url = (entry.get("raw_url") or entry.get("url") or "").strip()
    publisher = entry.get("publisher") or None

    return CandidateReference(
        title=title,
        authors=tuple(a for a in authors if isinstance(a, str) and a),
        year=year,
        publisher=publisher,
        raw_url=raw_url,
        doi=doi,
    )


def _apply_result(entry: dict, result: ResolverResult) -> dict:
    """Merge a verification result into the entry, preserving the
    textual metadata and stashing the pre-backfill URL for the
    HTML-comment renderer."""
    out = dict(entry)
    out["resolution_status"] = "resolved" if result.resolved else "unresolved"
    out["resolution_source"] = result.source
    out["attempted"] = list(result.attempted)
    out["resolution_reason"] = result.reason
    if "raw_url" not in out:
        out["raw_url"] = entry.get("url", "") or ""
    if result.resolved and result.url:
        out["url"] = result.url
    else:
        out["url"] = ""
    return out


# ── per-run backfill ──────────────────────────────────────────────────


@dataclass
class RunStats:
    run_id: str
    entries: int = 0
    resolved: int = 0
    unresolved: int = 0
    recommended_before: int = 0
    recommended_after: int = 0
    skipped: bool = False
    reason: str = ""


def _entry_identity(entry: dict) -> tuple:
    """Stable identity for matching entries across lists.

    Prefer `tag` (deterministic from the original pipeline); fall
    back to (normalised title, year). Both schemas surface enough
    to make a reliable key."""
    tag = entry.get("tag")
    if isinstance(tag, str) and tag:
        return ("tag", tag)
    title = (entry.get("title") or "").strip().lower()
    year = entry.get("year")
    return ("title-year", title, year)


def _atomic_write_json(path: Path, data: dict) -> None:
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
        mode="w", delete=False, encoding="utf-8",
    ) as f:
        tmp = Path(f.name)
        f.write(payload)
    os.replace(tmp, path)


def _backfill_run(
    rl_path: Path,
    verifier: ReferenceVerifier,
    dry_run: bool,
) -> RunStats:
    run_id = rl_path.parent.name
    stats = RunStats(run_id=run_id)
    try:
        data = json.loads(rl_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        stats.skipped = True
        stats.reason = f"unreadable: {exc}"
        return stats
    if not isinstance(data, dict):
        stats.skipped = True
        stats.reason = "top-level not a dict"
        return stats

    legacy = False
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        legacy_entries = data.get("verified")
        if isinstance(legacy_entries, list) and legacy_entries:
            entries = legacy_entries
            legacy = True
        else:
            stats.skipped = True
            stats.reason = "no entries/verified array"
            return stats

    new_entries: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ref = _entry_to_candidate(entry)
        if not ref.title:
            new_entries.append(_apply_result(
                entry, ResolverResult(
                    url=None, source=None, attempted=(), reason="no_title",
                ),
            ))
            stats.unresolved += 1
            continue
        result = verifier.resolve(ref)
        new_entries.append(_apply_result(entry, result))
        if result.resolved:
            stats.resolved += 1
        else:
            stats.unresolved += 1

    stats.entries = len(new_entries)
    data["entries"] = new_entries
    if legacy:
        data["verified"] = new_entries

    # Re-winnow `recommended`: keep tags that resolved; top up from
    # other resolved entries in their original order.
    resolved_entries = [
        e for e in new_entries if e.get("resolution_status") == "resolved"
    ]
    resolved_by_key = {_entry_identity(e): e for e in resolved_entries}

    old_rec = data.get("recommended") or []
    stats.recommended_before = len(
        [r for r in old_rec if isinstance(r, dict)],
    )

    surviving: list[dict] = []
    seen_keys: set[tuple] = set()
    for r in old_rec:
        if not isinstance(r, dict):
            continue
        key = _entry_identity(r)
        if key in resolved_by_key and key not in seen_keys:
            surviving.append(resolved_by_key[key])
            seen_keys.add(key)

    for e in resolved_entries:
        if len(surviving) >= 5:
            break
        key = _entry_identity(e)
        if key in seen_keys:
            continue
        surviving.append(e)
        seen_keys.add(key)

    data["recommended"] = surviving
    stats.recommended_after = len(surviving)

    if not dry_run:
        _atomic_write_json(rl_path, data)
    return stats


# ── batch ─────────────────────────────────────────────────────────────


def _all_reading_list_paths(runs: list[str] | None) -> list[Path]:
    if runs:
        return [
            RUNS_ROOT / r / "phase2_5_reading_list.json" for r in runs
        ]
    return sorted(RUNS_ROOT.glob("*/phase2_5_reading_list.json"))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runs", nargs="*", help="Subset of run IDs to process")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--cache", type=Path,
                   help="Override default verifier cache path")
    args = p.parse_args()

    paths = _all_reading_list_paths(args.runs)
    log.info("Verifying %d reading lists, %d workers, dry_run=%s",
             len(paths), args.workers, args.dry_run)

    verifier = ReferenceVerifier(cache_path=args.cache)
    started = time.time()
    all_stats: list[RunStats] = []

    # Per-run concurrency: each run processes its entries serially
    # within a worker, multiple runs run in parallel. The verifier's
    # requests.Session and sqlite cache are both thread-safe.
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {
            ex.submit(_backfill_run, path, verifier, args.dry_run): path
            for path in paths if path.exists()
        }
        done = 0
        for f in as_completed(futures):
            try:
                stats = f.result()
            except Exception as exc:
                path = futures[f]
                log.error("FAIL %s: %s", path.parent.name, exc)
                continue
            all_stats.append(stats)
            done += 1
            if stats.skipped:
                log.info("[%d/%d] %s SKIPPED (%s)",
                         done, len(futures), stats.run_id, stats.reason)
            else:
                log.info(
                    "[%d/%d] %s entries=%d resolved=%d unresolved=%d "
                    "recommended %d→%d",
                    done, len(futures), stats.run_id,
                    stats.entries, stats.resolved, stats.unresolved,
                    stats.recommended_before, stats.recommended_after,
                )

    elapsed = time.time() - started
    total_entries = sum(s.entries for s in all_stats)
    total_resolved = sum(s.resolved for s in all_stats)
    total_unresolved = sum(s.unresolved for s in all_stats)
    total_rec_before = sum(s.recommended_before for s in all_stats)
    total_rec_after = sum(s.recommended_after for s in all_stats)
    skipped = sum(1 for s in all_stats if s.skipped)
    log.info("=" * 60)
    log.info("Done in %.1f sec", elapsed)
    log.info("  runs:        %d (skipped %d)", len(all_stats), skipped)
    log.info("  entries:     %d  (resolved %d / unresolved %d)",
             total_entries, total_resolved, total_unresolved)
    if total_entries:
        log.info("               resolution rate: %.1f%%",
                 100.0 * total_resolved / total_entries)
    log.info("  recommended: %d → %d", total_rec_before, total_rec_after)
    log.info("  dry-run:     %s", args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
