"""Per-source candidate retrievers for citation verification.

Each function takes a citation's raw text and returns a list of candidate
hits in a uniform shape:
    [{"title": str, "authors": list[str], "year": int | None,
      "url": str, "doi": str | None, "source": str}, ...]
Sources truncate to a small top-N (default 5). Failures (HTTP errors, empty
results) return [].
"""
from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "BleakHouse-RefVerifier/1.0 (https://github.com/cbrew/BleakHouse; brewc@cbrew.com)"
TIMEOUT = 15.0
TOP_N = 5


# Per-host throttle: minimum seconds between consecutive calls to a host.
# Semantic Scholar's free tier is ~1 RPS and aggressively returns 429.
_HOST_MIN_INTERVAL = {
    "api.semanticscholar.org": 1.5,
    "api.search.brave.com": 1.1,  # Brave free tier is 1 RPS
}
_LAST_HOST_CALL: dict[str, float] = {}


def _throttle(url: str) -> None:
    from urllib.parse import urlparse
    host = urlparse(url).netloc
    interval = _HOST_MIN_INTERVAL.get(host)
    if interval is None:
        return
    now = time.monotonic()
    last = _LAST_HOST_CALL.get(host, 0.0)
    wait = interval - (now - last)
    if wait > 0:
        time.sleep(wait)
    _LAST_HOST_CALL[host] = time.monotonic()


def _retrying_get(url: str, *, params: dict, headers: dict,
                  timeout: float = TIMEOUT, retries: int = 3) -> httpx.Response | None:
    """GET with retry on 429 (exponential backoff) and transient errors.
    Returns None on permanent failure (caller should treat as no candidates)."""
    for attempt in range(retries):
        _throttle(url)
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


# ---------- Citation parsing ----------------------------------------------

_YEAR_RE = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b")


def parse_citation(raw: str) -> dict[str, Any]:
    """Heuristic parse: pull author surname (first capitalized run before
    first comma), the year (4-digit between 1500–2099), and a candidate
    title (the first quoted phrase or the longest non-author chunk).

    Best-effort only — verification still has the raw text and the LLM
    judge does the actual matching.
    """
    raw = raw.strip()
    # Year
    yr_match = _YEAR_RE.search(raw)
    year = int(yr_match.group(1)) if yr_match else None

    # First quoted phrase as title hint
    quoted = re.search(r"['\"]([^'\"]{8,})['\"]", raw)
    quoted_title = quoted.group(1) if quoted else None

    # Author: first chunk up to comma, dropping titles
    pre_comma = raw.split(",")[0].strip()
    pre_comma = re.sub(r"^(Dr|Prof|Sir|Mr|Mrs|Ms|Lord|Lady)\.?\s+", "", pre_comma)
    author = pre_comma if len(pre_comma.split()) <= 4 else None

    # Title fallback: text after the first comma, up to year-or-end
    title_chunk = raw[len(pre_comma) + 1:].strip().lstrip(",").strip()
    if year and str(year) in title_chunk:
        title_chunk = title_chunk[: title_chunk.find(str(year))].rstrip(" ,(")
    # Strip trailing publisher-like cruft
    title_chunk = re.sub(r"\s*\([^)]*\)\s*$", "", title_chunk).strip()
    title = quoted_title or title_chunk or raw

    return {"author": author, "title": title, "year": year}


# ---------- Source: CrossRef --------------------------------------------------

def crossref_search(raw: str) -> list[dict[str, Any]]:
    parsed = parse_citation(raw)
    params: dict[str, Any] = {"rows": TOP_N}
    if parsed["author"]:
        params["query.author"] = parsed["author"]
    if parsed["title"]:
        params["query.bibliographic"] = parsed["title"][:200]
    r = _retrying_get(
        "https://api.crossref.org/works",
        params=params,
        headers={"User-Agent": USER_AGENT, "mailto": "brewc@cbrew.com"},
    )
    if r is None or r.status_code != 200:
        return []
    items = r.json().get("message", {}).get("items", [])
    out = []
    for it in items[:TOP_N]:
        title = (it.get("title") or [""])[0]
        authors = [
            f"{a.get('given','')} {a.get('family','')}".strip()
            for a in it.get("author", [])
        ]
        year = None
        for k in ("issued", "published", "published-print", "published-online"):
            parts = it.get(k, {}).get("date-parts", [[None]])
            if parts and parts[0] and parts[0][0]:
                year = int(parts[0][0])
                break
        doi = it.get("DOI")
        url = it.get("URL") or (f"https://doi.org/{doi}" if doi else "")
        out.append({"title": title, "authors": authors, "year": year,
                    "url": url, "doi": doi, "source": "crossref"})
    return out


# ---------- Source: Semantic Scholar -----------------------------------------

def semantic_scholar_search(raw: str) -> list[dict[str, Any]]:
    parsed = parse_citation(raw)
    q_parts = [parsed["author"] or "", parsed["title"][:120]]
    query = " ".join(p for p in q_parts if p).strip()
    if not query:
        return []
    headers = {"User-Agent": USER_AGENT}
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key
    r = _retrying_get(
        "https://api.semanticscholar.org/graph/v1/paper/search",
        params={
            "query": query,
            "limit": TOP_N,
            "fields": "title,authors,year,externalIds,openAccessPdf,url",
        },
        headers=headers,
    )
    if r is None or r.status_code != 200:
        return []
    out = []
    for it in r.json().get("data", []):
        title = it.get("title") or ""
        authors = [a.get("name", "") for a in it.get("authors") or []]
        year = it.get("year")
        ext = it.get("externalIds") or {}
        doi = ext.get("DOI")
        url = it.get("url") or (f"https://doi.org/{doi}" if doi else "")
        out.append({"title": title, "authors": authors, "year": year,
                    "url": url, "doi": doi, "source": "semantic_scholar"})
    return out


# ---------- Source: Fatcat (Internet Archive Scholar) ------------------------

def fatcat_search(raw: str) -> list[dict[str, Any]]:
    """Fatcat (Internet Archive's bibliographic catalog). Their elasticsearch
    endpoint can be slow; we give it a generous timeout."""
    parsed = parse_citation(raw)
    q = parsed["title"][:120]
    if parsed["author"]:
        q = f"{parsed['author']} {q}"
    if not q:
        return []
    r = _retrying_get(
        "https://search.fatcat.wiki/fatcat_release/_search",
        params={"q": q, "size": TOP_N},
        headers={"User-Agent": USER_AGENT},
        timeout=30.0,
        retries=2,
    )
    if r is None or r.status_code != 200:
        return []
    try:
        hits = r.json().get("hits", {}).get("hits", [])
    except ValueError:
        return []
    out = []
    for h in hits[:TOP_N]:
        s = h.get("_source", {})
        title = s.get("title") or ""
        authors = [c.get("raw_name", "") for c in s.get("contribs") or [] if c.get("raw_name")]
        year = s.get("release_year")
        ident = s.get("ident")
        out.append({"title": title, "authors": authors, "year": year,
                    "url": f"https://fatcat.wiki/release/{ident}" if ident else "",
                    "doi": (s.get("ext_ids") or {}).get("doi"),
                    "source": "fatcat"})
    return out


# ---------- Source: HathiTrust ----------------------------------------------

def hathitrust_search(raw: str) -> list[dict[str, Any]]:
    """HathiTrust catalog search — title-only; their public API doesn't
    accept author+title combined queries, so we bias on title."""
    parsed = parse_citation(raw)
    title = parsed["title"][:120]
    if not title:
        return []
    try:
        r = httpx.get(
            "https://catalog.hathitrust.org/Search/Home",
            params={
                "lookfor": title,
                "type": "title",
                "format": "json",
                "limit": TOP_N,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.warning("hathitrust_search failed: %s", exc)
        return []
    # HathiTrust's search response is HTML; we use a different endpoint that
    # returns JSON via the bib API for known IDs. Fall back to empty here —
    # HathiTrust as a fallback source is best-effort.
    # The proper API is per-record via /api/volumes/brief/{id-type}/{id}/json.
    # Without full-text search auth, we can only confirm if an LCCN/OCLC is given.
    return []


# ---------- Source: CiNii (Japan NII) ---------------------------------------

def cinii_search(raw: str) -> list[dict[str, Any]]:
    parsed = parse_citation(raw)
    q = parsed["title"][:120]
    if parsed["author"]:
        q = f"{parsed['author']} {q}"
    r = _retrying_get(
        "https://cir.nii.ac.jp/opensearch/all",
        params={"q": q, "format": "json", "count": TOP_N},
        headers={"User-Agent": USER_AGENT},
    )
    if r is None or r.status_code != 200:
        return []
    try:
        feed = r.json()
    except ValueError:
        return []
    items = feed.get("@graph", [])
    if items and isinstance(items, list):
        items = items[0].get("items", []) if isinstance(items[0], dict) else []
    out = []
    for it in items[:TOP_N]:
        title = it.get("title") or it.get("dc:title") or ""
        creator = it.get("dc:creator") or []
        if isinstance(creator, str):
            creator = [creator]
        authors = [str(c) for c in creator]
        year_str = it.get("prism:publicationDate") or it.get("dc:date") or ""
        year_match = _YEAR_RE.search(str(year_str))
        year = int(year_match.group(1)) if year_match else None
        url = it.get("@id") or it.get("link") or ""
        out.append({"title": title, "authors": authors, "year": year,
                    "url": url, "doi": None, "source": "cinii"})
    return out


# ---------- Source: legislation.gov.uk ---------------------------------------

def legislation_gov_uk_search(raw: str) -> list[dict[str, Any]]:
    """Acts of Parliament. Their search is form-based but each Act has a
    canonical URL like https://www.legislation.gov.uk/<type>/<year>/<chapter>.
    We extract type/year from the citation and try a direct GET; on 200 the
    Act exists.
    """
    # Heuristic: find "(N & M Vict. c. K)" or "Act 1873" in the citation
    m = re.search(r"\b(\d{4})\s*(?:\([^)]*c\.?\s*(\d+)\))?", raw)
    if not m:
        return []
    year = m.group(1)
    chapter = m.group(2)
    if not (1800 <= int(year) <= 2100):
        return []
    candidates = []
    if chapter:
        url = f"https://www.legislation.gov.uk/ukpga/{year}/{chapter}"
        try:
            r = httpx.head(url, headers={"User-Agent": USER_AGENT},
                           timeout=TIMEOUT, follow_redirects=True)
            if r.status_code == 200:
                candidates.append({
                    "title": f"UK Public General Act {year} c. {chapter}",
                    "authors": [], "year": int(year),
                    "url": url, "doi": None, "source": "legislation_gov_uk",
                })
        except httpx.HTTPError as exc:
            logger.warning("legislation_gov_uk HEAD failed: %s", exc)
    return candidates


# ---------- Source: CourtListener (auth via env) -----------------------------

def courtlistener_search(raw: str) -> list[dict[str, Any]]:
    token = os.environ.get("COURTLISTENER_API_KEY")
    if not token:
        return []
    parsed = parse_citation(raw)
    q = parsed["title"][:120]
    if not q:
        return []
    r = _retrying_get(
        "https://www.courtlistener.com/api/rest/v3/search/",
        params={"q": q, "type": "o"},
        headers={"User-Agent": USER_AGENT, "Authorization": f"Token {token}"},
    )
    if r is None or r.status_code != 200:
        return []
    out = []
    for it in r.json().get("results", [])[:TOP_N]:
        title = it.get("caseName") or it.get("caseNameShort") or ""
        year = None
        date_filed = it.get("dateFiled") or ""
        if date_filed:
            ym = _YEAR_RE.search(date_filed)
            if ym:
                year = int(ym.group(1))
        out.append({"title": title, "authors": [],  # cases don't have authors
                    "year": year,
                    "url": "https://www.courtlistener.com" + (it.get("absolute_url") or ""),
                    "doi": None, "source": "courtlistener"})
    return out


# ---------- Source: GovInfo (auth via env) -----------------------------------

def govinfo_search(raw: str) -> list[dict[str, Any]]:
    """US government publications. Search Service API uses POST with a JSON
    body and requires offsetMark='*' to start a new search."""
    key = os.environ.get("GOVINFO_API_KEY")
    if not key:
        return []
    parsed = parse_citation(raw)
    q = parsed["title"][:120]
    if not q:
        return []
    body = {
        "query": q,
        "pageSize": TOP_N,
        "offsetMark": "*",
        "sorts": [{"field": "score", "sortOrder": "DESC"}],
    }
    try:
        r = httpx.post(
            "https://api.govinfo.gov/search",
            json=body,
            headers={
                "User-Agent": USER_AGENT,
                "X-Api-Key": key,
                "Content-Type": "application/json",
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
    except (httpx.HTTPError, httpx.TimeoutException) as exc:
        logger.warning("govinfo_search failed: %s", exc)
        return []
    out = []
    for it in r.json().get("results", [])[:TOP_N]:
        title = it.get("title") or ""
        year_match = _YEAR_RE.search(it.get("dateIssued") or "")
        year = int(year_match.group(1)) if year_match else None
        url = it.get("packageLink") or it.get("download", {}).get("pdfLink") or ""
        out.append({"title": title, "authors": [], "year": year,
                    "url": url, "doi": None, "source": "govinfo"})
    return out


# ---------- Chain registry ---------------------------------------------------

# Full chain. Used as a tests-only fallback; verify_citation() defaults to
# select_sources(raw) which routes by citation type.
DEFAULT_CHAIN = [
    crossref_search,
    semantic_scholar_search,
    fatcat_search,
    cinii_search,
    legislation_gov_uk_search,
    courtlistener_search,
    govinfo_search,
]


# ---------- Routing: pick sources by citation type ---------------------------

_CJK_RE = re.compile(r"[぀-ゟ゠-ヿ一-鿿]")
# Regnal-year UK Act: "33 & 34 Vict. c. 23"
_UK_REGNAL_RE = re.compile(
    r"\d+\s*&\s*\d+\s+(Vict|Geo|Eliz|Edw|Will|Wm|Hen|Anne|Car)\.?\s*c\.?",
    re.IGNORECASE,
)
# Named UK Act: "Married Women's Property Act 1882"
_UK_NAMED_ACT_RE = re.compile(
    r"\b[A-Z][\w'’]*(?:\s+[A-Z][\w'’]*){0,5}\s+Act\s+1[6-9]\d{2}\b"
)
# US legal reporter formats
_US_LEGAL_RE = re.compile(r"\b\d+\s+(U\.S\.|F\.\s*\d*d|S\.\s*Ct\.|F\.\s*Supp)\s+\d+")
# US government / congressional publications
_US_GOVDOC_RE = re.compile(
    r"\b(Senate|House)\s+(Report|Hearing|Bill|Document)\b"
    r"|\bFederal Register\b|\bGAO\b|\bCongressional Record\b"
    r"|\bU\.?S\.?\s+(Department|Bureau)\s+of\b",
)


def select_sources(raw: str) -> list[Any]:
    """Route a citation to the most plausible verification sources.

    Goal: don't waste calls — academic articles shouldn't go to GovInfo,
    UK Acts shouldn't go to CrossRef. Returns a chain to try in order.
    """
    # Lazy-import to avoid loading spaCy on module import.
    from .faculty import faculty_search

    if _CJK_RE.search(raw):
        return [cinii_search, crossref_search, semantic_scholar_search,
                faculty_search]

    if _UK_REGNAL_RE.search(raw) or _UK_NAMED_ACT_RE.search(raw):
        return [legislation_gov_uk_search]

    if _US_LEGAL_RE.search(raw):
        return [courtlistener_search]

    if _US_GOVDOC_RE.search(raw):
        return [govinfo_search, crossref_search]

    # Default scholarly chain. CiNii catches romanized JP authors; faculty
    # pages catch real-but-niche citations the structured APIs miss.
    return [crossref_search, semantic_scholar_search, fatcat_search,
            cinii_search, faculty_search]
