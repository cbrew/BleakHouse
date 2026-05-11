"""Backfill `isbn` and `doi` fields into existing reading-list entries
by re-fetching their source Wikipedia articles.

Context: BleakHouse-jcsr. The 222 phase2_5_reading_list.json files
predate the BleakHouse-hgws upstream that started extracting ISBNs
from cite-book templates. As a result, 0 of 15,575 entries carry an
ISBN — even though the source Wikipedia articles contain ISBNs in
their {{cite book}} templates. Without ISBN, the verification
cascade (BleakHouse-htfr/-2qs0) has no hard identifier to use, and
falls back to fuzzy title+author search through OpenAlex.

This script:
  1. Walks every wiki-fr-typed entry across all 222 reading lists.
  2. Extracts the source Wikipedia article from the entry's
     `raw_url` (which has the form 'wiki-fr:https://en.wikipedia.org/
     wiki/<article>#<anchor>').
  3. Fetches each unique source article once (≈52 articles in the
     current corpus) via enrichment.reference_tools._fetch_wikipedia_html.
  4. Parses cite templates via _extract_cite_templates.
  5. For each entry, finds the matching cite candidate by
     title similarity + first-author surname overlap, and populates
     entry['isbn'] and entry['doi'] from it.
  6. Writes each modified file atomically.

After this script runs, scripts/verify_reading_list_urls.py should
be re-run on the affected files. The verifier's ISBN cascade step
(BleakHouse-2qs0) will admit openlibrary.org/isbn/<isbn> URLs under
the Wikipedia-trust policy (CLAUDE.md), eliminating the bvbr-style
OpenAlex landings.

Policy — low match rates on plain-text bibliographies are expected:
    Match rates vary substantially across source articles. Articles
    whose Further Reading sections use {{cite book}}/{{cite journal}}
    templates (e.g. /wiki/David_Copperfield, /wiki/Charles_Dickens,
    /wiki/Victorian_era) match well — typically 40-60% of their wiki-fr
    entries gain an ISBN. Articles whose Further Reading sections use
    plain prose ("Chase, Karen (1984). 'The Literal Heroine,' ...")
    match at 0% because mwparserfromhtml's cite-template extractor
    only sees template-formatted entries, not free text.

    This is acceptable. The original pre-hgws upstream that minted
    the wiki-fr URLs used a more lenient parser that picked up the
    plain-text items as candidates; we're not regressing those
    entries by failing to enrich them — they keep their existing
    title/authors/year metadata and flow through the verification
    cascade's OpenAlex/OpenLibrary/Wikipedia branches as before. The
    only effect of a non-match here is that the entry doesn't gain
    the hard-identity ISBN/DOI fastpath; it's still verified, just
    via the same fuzzy search that always handled it.

    Parsing plain-text bibliography prose is a separate problem
    (out of scope for jcsr) and the resulting identifiers would not
    enjoy the Wikipedia-trust policy anyway, since they were never
    in a cite template that an editor curated.

Run:
    uv run python scripts/enrich_reading_lists_with_isbn.py
    uv run python scripts/enrich_reading_lists_with_isbn.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
import time
import urllib.parse
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from enrichment.reference_tools import (  # noqa: E402
    _CiteCandidate,
    _extract_cite_templates,
    _fetch_wikipedia_html,
)
from enrichment.reference_verify import (  # noqa: E402
    _author_overlaps,
    _title_similar,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("enrich-isbn")

RUNS_ROOT = REPO_ROOT / "data" / "runs"
WIKI_FR_PREFIX = "wiki-fr:"


def _source_article(raw_url: str) -> str:
    """Extract the Wikipedia article path from a wiki-fr raw_url.

    Input shape: 'wiki-fr:https://en.wikipedia.org/wiki/<title>#<anchor>'
    Output: '<title>' (URL-decoded, anchor stripped). '' on parse failure.
    """
    if not raw_url.startswith(WIKI_FR_PREFIX):
        return ""
    actual = raw_url[len(WIKI_FR_PREFIX):]
    try:
        parsed = urllib.parse.urlparse(actual)
    except ValueError:
        return ""
    path = parsed.path
    if not path.startswith("/wiki/"):
        return ""
    return urllib.parse.unquote(path[len("/wiki/"):])


def _entry_authors(entry: dict) -> list[str]:
    """Pull the author list, accommodating legacy (openalex_authors)
    and new (authors) schemas."""
    a = entry.get("authors") or entry.get("openalex_authors") or []
    return [s for s in a if isinstance(s, str) and s]


def _entry_title(entry: dict) -> str:
    return (
        entry.get("title")
        or entry.get("openalex_title")
        or entry.get("raw_text", "").strip()
    )


def _find_match(
    entry: dict, candidates: list[_CiteCandidate],
) -> _CiteCandidate | None:
    """Return the cite candidate whose title and authors best match
    the entry. Title similarity is the gate; author overlap is the
    tiebreaker. None if no candidate passes the title gate."""
    title = _entry_title(entry)
    if not title:
        return None
    entry_authors = _entry_authors(entry)
    best: _CiteCandidate | None = None
    for cand in candidates:
        if not _title_similar(cand.title, title):
            continue
        if entry_authors and not _author_overlaps(
            tuple(entry_authors), cand.authors,
        ):
            continue
        # First title+author match wins. Cite-template lists rarely
        # have near-duplicates within the same article; if they do,
        # this favours the first one in document order, which matches
        # Wikipedia's editorial sequence.
        best = cand
        break
    return best


def _atomic_write_json(path: Path, data: dict) -> None:
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp",
        mode="w", delete=False, encoding="utf-8",
    ) as f:
        tmp = Path(f.name)
        f.write(payload)
    os.replace(tmp, path)


def _collect_wiki_fr_entries() -> dict[str, list[tuple[Path, int]]]:
    """Walk all reading-list files and return a mapping
    article_path → list of (run_file, entry_index) tuples."""
    out: dict[str, list[tuple[Path, int]]] = defaultdict(list)
    for f in sorted(RUNS_ROOT.glob("*/phase2_5_reading_list.json")):
        try:
            d = json.loads(f.read_text())
        except Exception as exc:
            log.warning("skip %s: %s", f, exc)
            continue
        entries = d.get("entries") or []
        for i, e in enumerate(entries):
            ru = e.get("raw_url") or ""
            article = _source_article(ru)
            if article:
                out[article].append((f, i))
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true",
                   help="report counts without writing files")
    p.add_argument("--articles", nargs="*",
                   help="restrict to specific Wikipedia article paths "
                   "(useful for testing)")
    args = p.parse_args()

    t0 = time.time()
    article_index = _collect_wiki_fr_entries()
    log.info(
        "found %d wiki-fr entries across %d source articles",
        sum(len(v) for v in article_index.values()), len(article_index),
    )

    if args.articles:
        article_index = {
            a: v for a, v in article_index.items() if a in args.articles
        }
        log.info("restricted to %d articles", len(article_index))

    # Fetch + parse each unique article exactly once.
    cite_index: dict[str, list[_CiteCandidate]] = {}
    for article in sorted(article_index):
        html = _fetch_wikipedia_html(article)
        if not html:
            log.warning("no HTML for %s; skipping", article)
            cite_index[article] = []
            continue
        cites = _extract_cite_templates(html)
        with_isbn = sum(1 for c in cites if c.isbn)
        with_doi = sum(1 for c in cites if c.doi)
        log.info(
            "  %s: %d cite-templates (%d with isbn, %d with doi), "
            "%d entries to enrich",
            article, len(cites), with_isbn, with_doi,
            len(article_index[article]),
        )
        cite_index[article] = cites

    # Match + enrich. Track modifications per file so we write each
    # file once at the end.
    modifications: dict[Path, dict] = {}
    enriched_isbn = 0
    enriched_doi = 0
    matched_no_identifier = 0
    no_match = 0
    already_had = 0
    for article, occurrences in article_index.items():
        cands = cite_index.get(article, [])
        if not cands:
            no_match += len(occurrences)
            continue
        for f, idx in occurrences:
            if f not in modifications:
                modifications[f] = json.loads(f.read_text())
            payload = modifications[f]
            entries = payload.get("entries") or []
            if idx >= len(entries):
                continue  # defensive — schema drift
            entry = entries[idx]
            had_isbn = bool(entry.get("isbn"))
            had_doi = bool(entry.get("doi"))
            if had_isbn and had_doi:
                already_had += 1
                continue
            match = _find_match(entry, cands)
            if match is None:
                no_match += 1
                continue
            gained = False
            if match.isbn and not had_isbn:
                entry["isbn"] = match.isbn
                enriched_isbn += 1
                gained = True
            if match.doi and not had_doi:
                entry["doi"] = match.doi
                enriched_doi += 1
                gained = True
            if not gained:
                # Matched a cite-template but it had no usable
                # identifier (e.g., an old book published before
                # ISBN, or a journal cite without DOI). Common —
                # report so we know how many entries are still
                # forced through the fuzzy OpenAlex path.
                matched_no_identifier += 1

    log.info("=" * 60)
    log.info("enrichment results:")
    log.info("  entries enriched with isbn:    %d", enriched_isbn)
    log.info("  entries enriched with doi:     %d", enriched_doi)
    log.info("  entries already complete:      %d", already_had)
    log.info("  entries matched, no isbn/doi:  %d", matched_no_identifier)
    log.info("  entries with no cite-match:    %d", no_match)
    log.info("  files to write:                %d", len(modifications))

    if args.dry_run:
        log.info("dry-run: not writing files")
        log.info("done in %.1f sec", time.time() - t0)
        return 0

    for path, payload in modifications.items():
        _atomic_write_json(path, payload)
    log.info("wrote %d files", len(modifications))
    log.info("done in %.1f sec", time.time() - t0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
