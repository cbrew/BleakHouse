"""Reference verification — resolve a candidate citation to a verified URL.

This is the foundation module for the reading-list verification work
(BleakHouse-5ccr). It takes a candidate reference (title, optional
authors / year / publisher / DOI / raw_url) and runs it through a
fixed cascade of resolution strategies. The first strategy that
produces an HTTP-200 URL wins; if none does, the result is marked
unresolved with the full `attempted` list preserved for inspection
and future-resolver passes.

Cascade order (each step short-circuits on first success):

    1. doi         doi.org/<doi>; HEAD-verify
    2. raw_url     if it looks like a real http(s):// URL; HEAD-verify
    3. openalex    title+author search; prefer DOI, then landing page
    4. openlibrary title+author search for books; openlibrary.org/works/...
    5. wikipedia   article-by-title; require close title match (we
                   want Wikipedia's article ABOUT the work, not a
                   related article that mentions it)

Wikipedia is a legitimate citation target per user direction —
both topic articles and pages about specific works. The strict
title match prevents the previous bug (linking a work's citation
to a tangentially-related Wikipedia page).

Library code only — this ticket has no callers; pipeline integration
is BleakHouse-hgws and backfill is BleakHouse-7cgk.

Cache:
    A small sqlite cache (data/reference_verify_cache.sqlite3) stores
    one row per resolved query so re-runs are fast. The full
    ResolverResult is JSON-encoded per row. Delete the file to
    force re-resolution.

Rate limiting:
    The module makes one HTTP call per cascade step, sequentially.
    For batch backfills, the caller is expected to parallelize across
    candidates (e.g. via ThreadPoolExecutor with bounded workers).
    OpenAlex's free tier is ≈10 req/s; OpenLibrary and Wikipedia are
    more lenient. A worker count of 8 stays comfortably under all
    three.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import requests

logger = logging.getLogger(__name__)

_TIMEOUT_SEC = 15
_USER_AGENT = (
    "BleakHouseRefVerify/1.0 "
    "(academic research; https://github.com/cbrew/BleakHouse)"
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CACHE_PATH = _REPO_ROOT / "data" / "reference_verify_cache.sqlite3"


@dataclass(frozen=True)
class CandidateReference:
    """A candidate citation to resolve.

    Only `title` is required. The verification cascade uses everything
    else for disambiguation: authors narrow the search, year filters
    near-matches, doi short-circuits the cascade, raw_url is HEAD-tested
    if it's a real http(s) URL (synthetic schemes like 'wiki-fr:' are
    rejected by `_is_real_url`).
    """

    title: str
    authors: tuple[str, ...] = ()
    year: int | None = None
    publisher: str | None = None
    raw_url: str = ""
    doi: str = ""


@dataclass(frozen=True)
class ResolverResult:
    """Outcome of resolving a CandidateReference.

    Resolved: `url` is set, `source` identifies the winning strategy,
    `attempted` lists every strategy run (in order, including the
    winner), `reason` is None.

    Unresolved: `url` is None, `source` is None, `attempted` lists
    every strategy run, `reason` is 'no_match'.
    """

    url: str | None
    source: str | None
    attempted: tuple[str, ...]
    reason: str | None = None

    @property
    def resolved(self) -> bool:
        return self.url is not None


class _HttpClient(Protocol):
    """The slice of requests.Session we actually use. Lets tests pass
    a recorded-response fake without monkey-patching."""

    def get(  # noqa: D401
        self,
        url: str,
        *,
        params: dict[str, Any] | None = ...,
        headers: dict[str, str] | None = ...,
        timeout: float | None = ...,
    ) -> Any: ...

    def head(
        self,
        url: str,
        *,
        allow_redirects: bool = ...,
        headers: dict[str, str] | None = ...,
        timeout: float | None = ...,
    ) -> Any: ...


# Strategies run in this fixed order. The names also appear in
# ResolverResult.attempted so callers can audit what was tried.
_CASCADE = ("doi", "raw_url", "openalex", "openlibrary", "wikipedia")


class ReferenceVerifier:
    """Resolves CandidateReference through the verification cascade.

    Stateful only in that it owns an HTTP session, a cache connection,
    and a contact email. A single instance is safe to use across many
    threads — sqlite3 handles concurrent reads/writes; requests.Session
    is thread-safe per docs.
    """

    def __init__(
        self,
        cache_path: Path | None = None,
        session: _HttpClient | None = None,
        contact_email: str | None = None,
    ):
        self._cache_path = cache_path or _DEFAULT_CACHE_PATH
        self._session: _HttpClient = (
            session if session is not None else requests.Session()
        )
        self._contact = contact_email or os.environ.get(
            "BLEAKHOUSE_CONTACT_EMAIL", "brewc@cbrew.com"
        )
        self._init_cache()

    def _init_cache(self) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._cache_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS resolve_cache ("
                " key TEXT PRIMARY KEY,"
                " result_json TEXT NOT NULL,"
                " attempted_at REAL NOT NULL"
                ")"
            )

    @staticmethod
    def _candidate_key(ref: CandidateReference) -> str:
        """Stable hash over the fields that determine a unique query."""
        parts = (
            ref.title.strip().lower(),
            "|".join(sorted(a.strip().lower() for a in ref.authors if a)),
            str(ref.year or ""),
            ref.doi.strip().lower(),
            ref.raw_url.strip().lower(),
        )
        h = hashlib.sha256("\0".join(parts).encode("utf-8"))
        return h.hexdigest()[:16]

    def _cache_get(self, key: str) -> ResolverResult | None:
        with sqlite3.connect(self._cache_path) as conn:
            row = conn.execute(
                "SELECT result_json FROM resolve_cache WHERE key=?", (key,),
            ).fetchone()
        if not row:
            return None
        try:
            d = json.loads(row[0])
        except json.JSONDecodeError:
            return None
        return ResolverResult(
            url=d.get("url"),
            source=d.get("source"),
            attempted=tuple(d.get("attempted") or ()),
            reason=d.get("reason"),
        )

    def _cache_put(self, key: str, result: ResolverResult) -> None:
        payload = json.dumps({
            "url": result.url,
            "source": result.source,
            "attempted": list(result.attempted),
            "reason": result.reason,
        })
        with sqlite3.connect(self._cache_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO resolve_cache"
                "(key, result_json, attempted_at) VALUES (?,?,?)",
                (key, payload, time.time()),
            )

    def resolve(self, ref: CandidateReference) -> ResolverResult:
        """Run the cascade. Returns a cached result if present."""
        key = self._candidate_key(ref)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        result = self._run_cascade(ref)
        self._cache_put(key, result)
        return result

    def _run_cascade(self, ref: CandidateReference) -> ResolverResult:
        # `attempted` only records strategies that ran HTTP calls.
        # An input that's rejected by the strategy's own preconditions
        # (malformed DOI, synthetic raw_url scheme) doesn't count.
        attempted: list[str] = []

        if ref.doi:
            normalized = _normalize_doi(ref.doi)
            if re.match(r"^10\.\d+/", normalized):
                attempted.append("doi")
                url = f"https://doi.org/{normalized}"
                if self._head_ok(url):
                    return ResolverResult(url, "doi", tuple(attempted))

        if ref.raw_url and _is_real_url(ref.raw_url):
            attempted.append("raw_url")
            if self._head_ok(ref.raw_url):
                return ResolverResult(
                    ref.raw_url, "raw_url", tuple(attempted),
                )

        attempted.append("openalex")
        url = self._search_openalex(ref)
        if url:
            return ResolverResult(url, "openalex", tuple(attempted))

        attempted.append("openlibrary")
        url = self._search_openlibrary(ref)
        if url:
            return ResolverResult(url, "openlibrary", tuple(attempted))

        attempted.append("wikipedia")
        url = self._search_wikipedia(ref)
        if url:
            return ResolverResult(url, "wikipedia", tuple(attempted))

        return ResolverResult(None, None, tuple(attempted), "no_match")

    # ── HEAD ──

    def _head_ok(self, url: str) -> bool:
        try:
            resp = self._session.head(
                url,
                allow_redirects=True,
                headers={"User-Agent": _USER_AGENT},
                timeout=_TIMEOUT_SEC,
            )
            return getattr(resp, "status_code", 0) == 200
        except Exception as exc:
            logger.debug("HEAD %s failed: %s", url, exc)
            return False

    # ── OpenAlex ──

    def _search_openalex(self, ref: CandidateReference) -> str | None:
        params: dict[str, Any] = {"search": ref.title, "per_page": 5}
        api_key = os.environ.get("OPENALEX_API_KEY")
        if api_key:
            params["api_key"] = api_key
        else:
            params["mailto"] = self._contact
        results = self._safe_json_get(
            "https://api.openalex.org/works", params,
        ).get("results", [])
        best = self._pick_best_openalex(results, ref)
        if best is None:
            return None
        doi = best.get("doi") or ""
        if doi:
            url = doi if doi.startswith("http") else f"https://doi.org/{doi}"
        else:
            # No DOI: prefer the OpenAlex work page (always a valid
            # citation surface) over primary_location.landing_page_url
            # unless the landing page is on a trusted full-text host.
            # Many landing pages are foreign library catalogs that
            # soft-404 (HTTP 200 + 'record not found' body), which
            # HEAD verification can't detect.
            primary_loc = best.get("primary_location") or {}
            landing = primary_loc.get("landing_page_url") or ""
            work_url = best.get("id") or ""
            if landing and _is_trusted_landing(landing):
                url = landing
            else:
                url = work_url or landing
        return url if (url and self._head_ok(url)) else None

    def _pick_best_openalex(
        self, results: list[dict], ref: CandidateReference,
    ) -> dict | None:
        for w in results:
            cand_title = w.get("display_name") or w.get("title") or ""
            if not _title_similar(cand_title, ref.title):
                continue
            cand_authors = [
                (a.get("author") or {}).get("display_name", "")
                for a in (w.get("authorships") or [])
            ]
            if not _author_overlaps(ref.authors, cand_authors):
                continue
            if ref.year and w.get("publication_year") is not None:
                if abs(int(w["publication_year"]) - int(ref.year)) > 2:
                    continue
            return w
        return None

    # ── OpenLibrary ──

    def _search_openlibrary(self, ref: CandidateReference) -> str | None:
        params: dict[str, Any] = {"title": ref.title, "limit": 5}
        if ref.authors:
            params["author"] = ref.authors[0]
        docs = self._safe_json_get(
            "https://openlibrary.org/search.json", params,
        ).get("docs", [])
        for d in docs:
            if not _title_similar(d.get("title") or "", ref.title):
                continue
            if not _author_overlaps(ref.authors, d.get("author_name") or []):
                continue
            key = d.get("key") or ""
            if not key.startswith("/works/"):
                continue
            url = f"https://openlibrary.org{key}"
            if self._head_ok(url):
                return url
        return None

    # ── Wikipedia ──

    def _search_wikipedia(self, ref: CandidateReference) -> str | None:
        """Look up a Wikipedia article whose title closely matches the
        citation title.

        We require a strong title match — the goal is to find the
        article ABOUT the work, not a related article that mentions
        it. (That conflation was the original wiki-fr bug.) Topic
        citations (e.g. 'Chancery Court') match by the same rule
        when the citation title is the topic itself.
        """
        data = self._safe_json_get(
            "https://en.wikipedia.org/w/api.php",
            {
                "action": "query",
                "format": "json",
                "titles": ref.title,
                "redirects": 1,
                "prop": "info",
            },
        )
        pages = (data.get("query") or {}).get("pages") or {}
        for page in pages.values():
            if not isinstance(page, dict):
                continue
            pageid = page.get("pageid")
            page_title = page.get("title", "")
            if not pageid or pageid < 0:
                continue  # missing article
            if not _title_similar(page_title, ref.title):
                continue
            url = (
                "https://en.wikipedia.org/wiki/"
                + urllib.parse.quote(page_title.replace(" ", "_"))
            )
            if self._head_ok(url):
                return url
        return None

    # ── HTTP helper ──

    def _safe_json_get(
        self, url: str, params: dict[str, Any] | None = None,
    ) -> dict:
        try:
            resp = self._session.get(
                url,
                params=params,
                headers={"User-Agent": _USER_AGENT},
                timeout=_TIMEOUT_SEC,
            )
            status = getattr(resp, "status_code", 200)
            if status != 200:
                return {}
            data = resp.json()
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.debug("GET %s failed: %s", url, exc)
            return {}


# ── helpers (module-private but tested directly) ──


_DOI_PREFIXES = (
    "https://doi.org/", "http://doi.org/",
    "https://dx.doi.org/", "http://dx.doi.org/",
    "doi:",
)


def _normalize_doi(doi: str) -> str:
    doi = doi.strip()
    for prefix in _DOI_PREFIXES:
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
            break
    return doi


def _is_real_url(url: str) -> bool:
    """True for http(s):// URLs; False for synthetic schemes like
    'wiki-fr:' or empty strings. Case-insensitive."""
    return bool(re.match(r"^https?://", url, re.IGNORECASE))


# Hosts whose landing pages are direct full-text or otherwise stable
# citation targets. Anything outside this list (foreign library
# catalogs, handle resolvers, institutional admin URLs) gets bypassed
# in favour of the canonical OpenAlex work page.
_TRUSTED_OPENALEX_LANDING_HOSTS = (
    "archive.org",
    "muse.jhu.edu",
    "jstor.org",
    "oapen.org",
    "persee.fr",
)


def _is_trusted_landing(url: str) -> bool:
    """True iff `url`'s host equals (or is a subdomain of) one of the
    trusted full-text hosts."""
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    return any(
        host == h or host.endswith("." + h)
        for h in _TRUSTED_OPENALEX_LANDING_HOSTS
    )


def _normalize_text(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _title_similar(a: str, b: str, *, jaccard_min: float = 0.6) -> bool:
    """Loose title match.

    Either the shorter normalized title is a substring of the longer,
    or their word-set Jaccard overlap is ≥ jaccard_min. Default 0.6
    accepts moderate phrasing differences while rejecting unrelated
    titles. Empty/whitespace-only titles never match.
    """
    na, nb = _normalize_text(a), _normalize_text(b)
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    ta, tb = set(na.split()), set(nb.split())
    if not ta or not tb:
        return False
    return (len(ta & tb) / len(ta | tb)) >= jaccard_min


def _surname(name: str) -> str:
    """Surname extractor that handles both 'Given Surname' (default in
    OpenAlex / OpenLibrary results) and 'Surname, Given' (common in
    Wikipedia bibliographies). Empty input returns ''."""
    name = name.strip()
    if not name:
        return ""
    if "," in name:
        # 'Ackroyd, Peter' → 'Ackroyd'
        return name.split(",", 1)[0].strip().lower()
    tokens = name.split()
    return tokens[-1].lower() if tokens else ""


def _author_overlaps(
    ref_authors: tuple[str, ...] | list[str],
    result_authors: list[str],
) -> bool:
    """At least one surname appears in both lists. Empty ref_authors
    is treated as 'no constraint' and matches anything."""
    refs = [a for a in ref_authors if a]
    if not refs:
        return True
    ref_surnames = {_surname(a) for a in refs}
    ref_surnames.discard("")
    for ra in result_authors:
        s = _surname(ra)
        if s and s in ref_surnames:
            return True
    return False


# ── module-level convenience function (shared verifier) ──

_DEFAULT_VERIFIER: ReferenceVerifier | None = None


def resolve(
    ref: CandidateReference,
    *,
    verifier: ReferenceVerifier | None = None,
) -> ResolverResult:
    """Resolve a candidate reference.

    Uses a module-level shared verifier (lazily created) by default.
    Pass `verifier` for tests or for callers that want a private
    cache.
    """
    global _DEFAULT_VERIFIER
    if verifier is not None:
        return verifier.resolve(ref)
    if _DEFAULT_VERIFIER is None:
        _DEFAULT_VERIFIER = ReferenceVerifier()
    return _DEFAULT_VERIFIER.resolve(ref)
