"""Re-run the listener-pick LLM winnower across all reading lists.

Context: BleakHouse-sz5m. After BleakHouse-jcsr re-enriched the
existing reading lists with ISBN/DOI and re-ran the verification
cascade with the new ISBN step + Wikipedia-trust policy, the
consumer-facing `recommended[]` short list was still the output
of the simple top-up in verify_reading_list_urls.py:

  - keep original LLM picks where they still resolve
  - top up to 5 from other resolved entries in their original order

That preserves the original selection but doesn't reflect the new
admission outcomes. The original picks were chosen pre-verification
on the unfiltered candidate set; some now resolve cleanly via the
ISBN cascade while others have moved (or stayed unresolved).

This script re-runs the Haiku-driven listener-pick LLM
(`_select_listener_recommendations` in enrichment/host_prep.py)
on every reading list and writes a fresh `recommended[]` reflecting
the current admission outcomes.

Cost: 222 Haiku calls. Per-call ≈ 6k input + 80 output tokens.
At Claude Haiku 4.5 pricing ($1/M input, $5/M output), the full
sweep is ≈ $1.50.

Run:
    uv run python scripts/rewinnow_recommended.py
    uv run python scripts/rewinnow_recommended.py --runs dc_emb_literary
    uv run python scripts/rewinnow_recommended.py --workers 12
    uv run python scripts/rewinnow_recommended.py --dry-run
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
from dataclasses import dataclass, fields
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import anthropic  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from enrichment.axes import NOVEL_BY_ID, NOVEL_BY_KEY  # noqa: E402
from enrichment.host_prep import (  # noqa: E402
    _select_listener_recommendations,  # pyright: ignore[reportPrivateUsage]
)
from enrichment.reference_tools import CitationRecord  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("rewinnow")

RUNS_ROOT = REPO_ROOT / "data" / "runs"

# Listener-pick promises 3-8 picks. If the model returns more (or
# the fallback returns the full candidate list because it couldn't
# parse the response), we cap at this number to avoid blowing up
# recommended[]. The post-jcsr backfill produced 5 per run as the
# median; 10 leaves plenty of headroom for an aggressive pick
# without being a runaway.
RECOMMENDED_CAP = 10

# Set of valid CitationRecord field names — used to strip entry
# dict keys (e.g. 'raw_url', added by BleakHouse-7cgk) that aren't
# part of the dataclass.
_RECORD_FIELDS: set[str] = {f.name for f in fields(CitationRecord)}


@dataclass
class RunStats:
    run_id: str
    before: int = 0
    after: int = 0
    skipped: bool = False
    reason: str = ""


def _novel_meta(run_dir: Path) -> tuple[str, str] | None:
    """Read run_manifest.json to find (novel_title, novel_author).

    Returns None if the manifest is missing or the novel key is
    unrecognised. The novel key lives in `axes.novel` and maps via
    enrichment.axes.NOVEL_BY_KEY to the canonical title + author.
    Using the explicit manifest avoids parsing run IDs by name
    (per the axis-identity policy — BleakHouse-0wn7/g3hj/5of2).
    """
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        return None
    try:
        m = json.loads(manifest_path.read_text())
    except Exception:
        return None
    key = (m.get("axes") or {}).get("novel")
    if not key:
        return None
    # axes.novel uses the short key ('dc') in most manifests but the
    # long ID ('david_copperfield') in 5 retrofit/short-variant runs.
    # Accept either.
    novel = NOVEL_BY_KEY.get(key) or NOVEL_BY_ID.get(key)
    if novel is None:
        return None
    return novel.title, novel.author


def _entry_to_record(entry: dict, *, fallback_tag: str = "") -> CitationRecord:
    """Build a CitationRecord from an entry dict.

    Two robustness fixes for the heterogeneous on-disk schema:

    1. Strip non-dataclass keys (e.g. 'raw_url' from BleakHouse-7cgk's
       renderer-support fields; 'expert_name', 'segment_name',
       'verification_source' from legacy reading-list entries).
    2. Fill in `tag` from `fallback_tag` and `title` from
       `openalex_title` or `raw_text` for legacy entries that
       pre-date the tagging convention (15 of 222 runs across
       64 of 11,486 resolved entries — 0.6% of the corpus).
    """
    cleaned = {k: v for k, v in entry.items() if k in _RECORD_FIELDS}
    if not cleaned.get("tag"):
        cleaned["tag"] = fallback_tag
    if not cleaned.get("title"):
        cleaned["title"] = (
            entry.get("openalex_title")
            or (entry.get("raw_text") or "").strip()[:120]
            or "(untitled)"
        )
    if not cleaned.get("authors"):
        cleaned["authors"] = entry.get("openalex_authors") or []
    if not cleaned.get("year"):
        cleaned["year"] = entry.get("openalex_year")
    return CitationRecord(**cleaned)


def _atomic_write_json(path: Path, data: dict) -> None:
    """Tmp + rename. The upstream filter_reading_list_recommended
    writes non-atomically; with a ThreadPoolExecutor this risks a
    torn file on crash."""
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
        mode="w", delete=False, encoding="utf-8",
    ) as f:
        tmp = Path(f.name)
        f.write(payload)
    os.replace(tmp, path)


def _rewinnow_one(
    client: anthropic.Anthropic, reading_list_path: Path,
) -> RunStats:
    run_id = reading_list_path.parent.name
    meta = _novel_meta(reading_list_path.parent)
    if meta is None:
        return RunStats(run_id, skipped=True, reason="no_novel_meta")
    title, author = meta

    try:
        payload = json.loads(reading_list_path.read_text())
    except Exception as exc:
        return RunStats(run_id, skipped=True, reason=f"read_failed: {exc}")

    entries_dicts: list[dict] = payload.get("entries") or []
    if not entries_dicts:
        return RunStats(run_id, skipped=True, reason="no_entries")

    before = len(payload.get("recommended") or [])

    # Only resolved entries make sense as listener picks. The
    # original host_prep flow ran this filter on the full proposed
    # list, but with the verification cascade in place we should
    # narrow to resolved upfront — picking an unresolved entry as
    # 'recommended' would just produce an HTML comment in the
    # rendered template.
    resolved = [
        e for e in entries_dicts
        if e.get("resolution_status") == "resolved"
    ]
    if not resolved:
        # No resolved entries — clear recommended rather than
        # leaving stale picks pointing at now-unresolved items.
        payload["recommended"] = []
        _atomic_write_json(reading_list_path, payload)
        return RunStats(run_id, before=before, after=0)

    # Synthesize tags for legacy-schema entries that pre-date the
    # tagging convention. We do this in-memory only — the entry
    # dicts on disk keep their original (untagged) shape — but we
    # need them tagged so the LLM has something to refer to and we
    # can map picks back to entries by index.
    synthesized: list[tuple[dict, str]] = []
    for idx, e in enumerate(resolved):
        tag = e.get("tag") or f"ref-{idx + 1}"
        synthesized.append((e, tag))

    candidates = [
        _entry_to_record(e, fallback_tag=tag) for e, tag in synthesized
    ]
    picks = _select_listener_recommendations(
        client, candidates, title, author, recorder=None,
    )

    pick_set = set(picks)
    new_recommended = [e for e, tag in synthesized if tag in pick_set]
    if len(new_recommended) > RECOMMENDED_CAP:
        log.warning(
            "  %s: %d picks > cap %d; trimming",
            run_id, len(new_recommended), RECOMMENDED_CAP,
        )
        new_recommended = new_recommended[:RECOMMENDED_CAP]

    payload["recommended"] = new_recommended
    _atomic_write_json(reading_list_path, payload)
    return RunStats(run_id, before=before, after=len(new_recommended))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runs", nargs="*", help="restrict to specific run IDs")
    p.add_argument(
        "--workers", type=int, default=4,
        help=(
            "Concurrent in-flight Haiku calls. Default 4 to stay under "
            "the 450k-input-tokens/min rate limit (each call ≈ 6k input "
            "tokens; 4 workers × 1 call/sec ≈ 24k/sec → 1.44M/min, safely "
            "below limit). Anthropic SDK retries on 429 with backoff so "
            "occasional bursts are absorbed."
        ),
    )
    p.add_argument("--dry-run", action="store_true",
                   help="list what would be done; no HTTP, no writes")
    args = p.parse_args()

    load_dotenv()
    if not args.dry_run and not os.environ.get("ANTHROPIC_API_KEY"):
        log.error("ANTHROPIC_API_KEY not set")
        return 1

    files = sorted(RUNS_ROOT.glob("*/phase2_5_reading_list.json"))
    if args.runs:
        wanted = set(args.runs)
        files = [f for f in files if f.parent.name in wanted]
    log.info(
        "processing %d reading lists with %d workers", len(files), args.workers,
    )

    if args.dry_run:
        for f in files[:5]:
            meta = _novel_meta(f.parent)
            try:
                d = json.loads(f.read_text())
            except Exception:
                d = {}
            entries = d.get("entries") or []
            resolved = sum(
                1 for e in entries if e.get("resolution_status") == "resolved"
            )
            log.info(
                "  [dry] %s: novel=%s entries=%d resolved=%d recommended=%d",
                f.parent.name, meta, len(entries), resolved,
                len(d.get("recommended") or []),
            )
        log.info("dry-run: would process %d files", len(files))
        return 0

    # max_retries=10 enables the SDK's built-in exponential backoff
    # on 429 (rate-limit) and 5xx errors. Combined with workers=4 it
    # absorbs the rare burst that exceeds the per-minute token budget.
    client = anthropic.Anthropic(max_retries=10)
    t0 = time.time()
    stats: list[RunStats] = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(_rewinnow_one, client, f): f for f in files}
        for i, fut in enumerate(as_completed(futures), 1):
            s = fut.result()
            stats.append(s)
            if s.skipped:
                log.info(
                    "  [%d/%d] %s SKIPPED (%s)",
                    i, len(files), s.run_id, s.reason,
                )
            else:
                log.info(
                    "  [%d/%d] %s recommended %d→%d",
                    i, len(files), s.run_id, s.before, s.after,
                )

    log.info("=" * 60)
    log.info("done in %.1f sec", time.time() - t0)
    processed = sum(1 for s in stats if not s.skipped)
    skipped = sum(1 for s in stats if s.skipped)
    before_total = sum(s.before for s in stats)
    after_total = sum(s.after for s in stats)
    log.info("  runs processed: %d", processed)
    log.info("  runs skipped:   %d", skipped)
    log.info("  recommended:    %d → %d", before_total, after_total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
