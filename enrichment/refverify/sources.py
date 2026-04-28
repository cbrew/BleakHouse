"""Two source APIs for citation verification: OpenAlex and Wikipedia.

Both return rich metadata that the agent uses to compose a listener-facing
reading-list entry — title, authors, year, description, publisher, type,
cite count. The agent never invents these fields; everything visible to
the listener was returned by one of these two APIs.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = (
    "BleakHouse-RefVerifier/2.0 "
    "(https://github.com/cbrew/BleakHouse; brewc@cbrew.com)"
)
TIMEOUT = 15.0
TOP_N = 5

_YEAR_RE = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b")


# ---------- HTTP helper ------------------------------------------------------

def _retrying_get(url: str, *, params: dict, headers: dict,
                  timeout: float = TIMEOUT, retries: int = 3) -> httpx.Response | None:
    """GET with retry on 429 / 5xx / transient errors. Returns None on
    permanent failure (caller should treat as no candidates)."""
    for attempt in range(retries):
        try:
            r = httpx.get(url, params=params, headers=headers, timeout=timeout)
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            logger.warning("GET %s attempt %d raised: %s", url, attempt + 1, exc)
            if attempt + 1 == retries:
                return None
            time.sleep(0.5 * (2 ** attempt))
            continue
        if r.status_code == 429:
            wait = float(r.headers.get("Retry-After", 2.0)) or 2.0
            logger.info("GET %s 429; backing off %.1fs", url, wait)
            time.sleep(min(wait, 5.0))
            continue
        if r.status_code >= 500:
            time.sleep(0.5 * (2 ** attempt))
            continue
        return r
    return None


# ---------- Citation parsing -------------------------------------------------

def parse_citation(raw: str) -> dict[str, Any]:
    """Heuristic parse: pull author surname (first capitalized run before
    first comma), the year (4-digit between 1500–2099), and a candidate
    title. Best-effort — used to seed the deterministic match gate."""
    raw = raw.strip()
    # Take the LAST year — citations often have "Title 1830-1864 (1995)"
    # and we want 1995 (the publication year), not 1830 (in the title).
    yr_matches = list(_YEAR_RE.finditer(raw))
    year = int(yr_matches[-1].group(1)) if yr_matches else None

    quoted = re.search(r"['\"]([^'\"]{8,})['\"]", raw)
    quoted_title = quoted.group(1) if quoted else None

    pre_comma = raw.split(",")[0].strip()
    pre_comma = re.sub(r"^(Dr|Prof|Sir|Mr|Mrs|Ms|Lord|Lady)\.?\s+", "", pre_comma)
    author = pre_comma if len(pre_comma.split()) <= 4 else None

    title_chunk = raw[len(pre_comma) + 1:].strip().lstrip(",").strip()
    if year and str(year) in title_chunk:
        title_chunk = title_chunk[: title_chunk.find(str(year))].rstrip(" ,(")
    title_chunk = re.sub(r"\s*\([^)]*\)\s*$", "", title_chunk).strip()
    title = quoted_title or title_chunk or raw

    return {"author": author, "title": title, "year": year}


# ---------- OpenAlex ---------------------------------------------------------

def _invert_abstract(inv: dict[str, list[int]] | None) -> str:
    """Reconstruct an abstract from OpenAlex's inverted index."""
    if not inv:
        return ""
    word_at: dict[int, str] = {}
    for word, positions in inv.items():
        for p in positions:
            word_at[p] = word
    return " ".join(word_at[i] for i in sorted(word_at) if i in word_at)


def openalex_search(query: str) -> list[dict[str, Any]]:
    """Search OpenAlex. Returns up to TOP_N candidates with rich metadata
    suitable for composing a reading-list entry."""
    if not query.strip():
        return []
    r = _retrying_get(
        "https://api.openalex.org/works",
        params={"search": query[:200], "per_page": TOP_N},
        headers={"User-Agent": USER_AGENT, "mailto": "brewc@cbrew.com"},
    )
    if r is None or r.status_code != 200:
        return []
    out = []
    for w in r.json().get("results", [])[:TOP_N]:
        title = w.get("display_name") or ""
        authors = [
            (a.get("author") or {}).get("display_name", "")
            for a in (w.get("authorships") or [])[:8]
        ]
        year = w.get("publication_year")
        doi = w.get("doi")
        url = doi if (doi and doi.startswith("http")) else (
            f"https://doi.org/{doi.replace('https://doi.org/', '')}"
            if doi else (w.get("id") or "")
        )
        host_venue = w.get("host_venue") or {}
        primary_loc = w.get("primary_location") or {}
        venue_source = primary_loc.get("source") or {}
        publisher = (host_venue.get("publisher")
                     or venue_source.get("host_organization_name")
                     or venue_source.get("publisher")
                     or "")
        venue_name = host_venue.get("display_name") or venue_source.get("display_name") or ""
        abstract = _invert_abstract(w.get("abstract_inverted_index"))
        out.append({
            "title": title,
            "authors": [a for a in authors if a],
            "year": year,
            "type": w.get("type") or "",
            "publisher": publisher,
            "venue": venue_name,
            "abstract": abstract,
            "cited_by": w.get("cited_by_count") or 0,
            "url": url,
            "doi": doi,
            "source": "openalex",
        })
    return out


# ---------- Wikipedia --------------------------------------------------------

def wikipedia_search(query: str) -> list[dict[str, Any]]:
    """Search English Wikipedia. Uses generator=search to combine ranked
    matches with plain-text intro extracts in a single request."""
    if not query.strip():
        return []
    r = _retrying_get(
        "https://en.wikipedia.org/w/api.php",
        params={
            "action": "query",
            "generator": "search",
            "gsrsearch": query[:300],
            "gsrlimit": TOP_N,
            "prop": "extracts|info",
            "exintro": "1",
            "explaintext": "1",
            "exchars": "800",
            "inprop": "url",
            "format": "json",
            "redirects": "1",
        },
        headers={"User-Agent": USER_AGENT},
    )
    if r is None or r.status_code != 200:
        return []
    pages = (r.json().get("query") or {}).get("pages") or {}
    # Preserve search rank from the index field
    items = sorted(pages.values(), key=lambda p: p.get("index", 999))
    out: list[dict[str, Any]] = []
    for p in items[:TOP_N]:
        title = p.get("title") or ""
        extract = p.get("extract") or ""
        url = p.get("fullurl") or f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
        out.append({
            "title": title,
            "authors": [],
            "year": None,
            "type": "wikipedia_article",
            "publisher": "Wikipedia",
            "venue": "Wikipedia",
            "abstract": extract,
            "cited_by": None,
            "url": url,
            "doi": None,
            "source": "wikipedia",
        })
    return out
