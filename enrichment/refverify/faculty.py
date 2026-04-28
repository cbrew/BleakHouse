"""Search public faculty / personal academic pages for citation evidence.

Pipeline:
  1. spaCy NER pulls PERSON entities from the raw citation.
  2. Brave Search API (free tier, key in BRAVE_SEARCH_API_KEY) for
     "<author>" "<title>" filtered to academic domains.
  3. Precision gate: the citation's title (or a substantial prefix) must
     appear in Brave's own result title/description. Page fetch is skipped
     because many .edu sites bot-block; the snippet match is enough textual
     evidence to pass to the LLM judge, which still has the final say.

This source is for citations that fail the structured scholarly APIs. Many
real-but-niche references show up only on author CVs / dept pages, and the
existing OpenAlex+CrossRef+S2 chain misses them.

If BRAVE_SEARCH_API_KEY is not set, faculty_search gracefully returns [].
"""
from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

import spacy
from spacy.language import Language

from .sources import TOP_N, USER_AGENT, _retrying_get, parse_citation

logger = logging.getLogger(__name__)

# Domains we trust as bibliographic / academic evidence. Broader than just
# faculty pages — Project MUSE, JSTOR, Cambridge, archive.org book records,
# hathitrust catalog pages all surface real-but-niche citations.
_ACADEMIC_DOMAIN_RE = re.compile(
    r"(\.edu|\.ac\.[a-z]{2,3}|academia\.edu|orcid\.org|"
    r"researchgate\.net|muse\.jhu\.edu|cambridge\.org|oup\.com|"
    r"tandfonline\.com|jstor\.org|mhra\.org\.uk|"
    r"semanticscholar\.org|archive\.org|hathitrust\.org|"
    r"openlibrary\.org|books\.google\.com|degruyter\.com|"
    r"\.gov(\.[a-z]{2,3})?)$",
    re.IGNORECASE,
)


def _surname(name: str) -> str:
    """Last whitespace-separated token from a person name.
    'P.W.J. Bartrip' -> 'Bartrip', 'Mariko Kondo' -> 'Kondo'."""
    parts = [p for p in re.split(r"\s+", name) if p]
    return parts[-1] if parts else name


@lru_cache(maxsize=1)
def _nlp() -> Language:
    return spacy.load("en_core_web_sm")


def extract_person_names(raw: str) -> list[str]:
    """PERSON entities via spaCy. Falls back to the comma-prefix heuristic
    when NER finds nothing usable."""
    doc = _nlp()(raw)
    names = [ent.text.strip() for ent in doc.ents if ent.label_ == "PERSON"]
    seen: set[str] = set()
    unique: list[str] = []
    for n in names:
        # spaCy sometimes returns sub-spans; require at least firstname+surname
        if len(n.split()) < 2:
            continue
        if n not in seen:
            seen.add(n)
            unique.append(n)
    if unique:
        return unique
    pre = raw.split(",")[0].strip()
    pre = re.sub(r"^(Dr|Prof|Sir|Mr|Mrs|Ms|Lord|Lady)\.?\s+", "", pre)
    if 2 <= len(pre.split()) <= 4:
        return [pre]
    return []


def _brave_search(query: str) -> list[dict[str, Any]]:
    """Brave Search Web API. Returns up to ~12 results, each with
    title/description/url. Throttled — free tier is 1 RPS.
    """
    key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if not key:
        return []
    r = _retrying_get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": 12},
        headers={
            "X-Subscription-Token": key,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    if r is None or r.status_code != 200:
        return []
    try:
        data = r.json()
    except ValueError:
        return []
    results = (data.get("web") or {}).get("results") or []
    out = []
    for it in results:
        url = it.get("url") or ""
        if not url:
            continue
        out.append({
            "url": url,
            "title": it.get("title") or "",
            "description": it.get("description") or "",
        })
    return out


def _normalize(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def faculty_search(raw: str) -> list[dict[str, Any]]:
    """Surface citation candidates by searching faculty / academic web pages.

    Precision gate: the citation's title (or a substantial prefix) must appear
    in the search-result title or description as returned by Brave. This avoids
    fetching the page (many academic sites bot-block) while still requiring
    textual evidence the citation exists at the URL.
    """
    parsed = parse_citation(raw)
    title = parsed["title"] or ""
    if len(title) < 12:
        return []
    names = extract_person_names(raw)
    if not names:
        return []

    primary = names[0]
    surname = _surname(primary)
    # Two-pass query strategy. Strict first (quoted full name + full title) for
    # precision; if it whiffs, fall back to a more lenient surname + quoted
    # title-prefix query (handles names with stops like "P.W.J." that quoted
    # phrase-match doesn't tolerate well).
    queries = [
        f'"{primary}" "{title[:80]}"',
        f'{surname} "{title[:60]}"',
    ]
    results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for q in queries:
        for r in _brave_search(q):
            if r["url"] in seen_urls:
                continue
            seen_urls.add(r["url"])
            results.append(r)
        if results:
            break  # first query that returned anything wins
    if not results:
        return []
    results = [r for r in results
               if _ACADEMIC_DOMAIN_RE.search(urlparse(r["url"]).netloc or "")]

    norm_title = _normalize(title)
    title_prefix = norm_title[:50]
    out: list[dict[str, Any]] = []
    emitted_urls: set[str] = set()
    for r in results:
        if r["url"] in emitted_urls:
            continue
        haystack = _normalize(r["title"] + " " + r["description"])
        if title_prefix and (title_prefix in haystack or norm_title in haystack):
            emitted_urls.add(r["url"])
            out.append({
                "title": title,
                "authors": names,
                "year": parsed["year"],
                "url": r["url"],
                "doi": None,
                "source": "faculty_page",
            })
            if len(out) >= TOP_N:
                break
    return out
