"""Tests for enrichment/reference_verify.py.

The verifier talks to four external services (DOI resolver,
OpenAlex, OpenLibrary, Wikipedia). All HTTP is faked via FakeSession
— recorded-shape responses, no live network. Each cascade branch
has at least one test that exercises it; the all-fail path has one
too. The cache is exercised by checking that a second call doesn't
re-hit the fake session.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from enrichment.reference_verify import (
    CandidateReference,
    ReferenceVerifier,
    ResolverResult,
    _author_overlaps,
    _is_real_url,
    _normalize_doi,
    _title_similar,
)


# ── Fake HTTP session ─────────────────────────────────────────────


@dataclass
class FakeResponse:
    status_code: int
    body: Any = None

    def json(self) -> Any:
        return self.body if self.body is not None else {}


class FakeSession:
    """Minimal stand-in for requests.Session. Routes GET/HEAD by URL
    prefix; records every request for assertions."""

    def __init__(self) -> None:
        # url-prefix → FakeResponse
        self.get_routes: dict[str, FakeResponse] = {}
        self.head_routes: dict[str, FakeResponse] = {}
        self.get_log: list[tuple[str, dict | None]] = []
        self.head_log: list[str] = []

    # programmatic setup
    def set_get(self, url_prefix: str, status: int, body: Any) -> None:
        self.get_routes[url_prefix] = FakeResponse(status, body)

    def set_head(self, url_prefix: str, status: int) -> None:
        self.head_routes[url_prefix] = FakeResponse(status)

    # the surface used by ReferenceVerifier
    def get(
        self,
        url: str,
        *,
        params: dict | None = None,
        headers: dict | None = None,
        timeout: float | None = None,
    ) -> FakeResponse:
        self.get_log.append((url, params))
        for prefix, resp in self.get_routes.items():
            if url.startswith(prefix):
                return resp
        return FakeResponse(404, {})

    def head(
        self,
        url: str,
        *,
        allow_redirects: bool = True,
        headers: dict | None = None,
        timeout: float | None = None,
    ) -> FakeResponse:
        self.head_log.append(url)
        for prefix, resp in self.head_routes.items():
            if url.startswith(prefix):
                return resp
        return FakeResponse(404)


@pytest.fixture
def verifier(tmp_path: Path) -> tuple[ReferenceVerifier, FakeSession]:
    """A fresh verifier with a per-test sqlite cache and fake session."""
    sess = FakeSession()
    v = ReferenceVerifier(
        cache_path=tmp_path / "cache.sqlite3",
        session=sess,
        contact_email="test@example.com",
    )
    return v, sess


# ── Helpers: pure functions ──────────────────────────────────────


def test_is_real_url_accepts_http_and_https() -> None:
    assert _is_real_url("http://example.com")
    assert _is_real_url("https://example.com")
    assert _is_real_url("HTTPS://EXAMPLE.COM")


def test_is_real_url_rejects_synthetic_schemes_and_empty() -> None:
    assert not _is_real_url("")
    assert not _is_real_url("wiki-fr:https://en.wikipedia.org/wiki/X")
    assert not _is_real_url("doi:10.1234/abc")
    assert not _is_real_url("ftp://example.com")
    assert not _is_real_url("just some text")


def test_normalize_doi_strips_prefixes() -> None:
    assert _normalize_doi("10.1234/abc") == "10.1234/abc"
    assert _normalize_doi("https://doi.org/10.1234/abc") == "10.1234/abc"
    assert _normalize_doi("http://dx.doi.org/10.1234/abc") == "10.1234/abc"
    assert _normalize_doi("doi:10.1234/abc") == "10.1234/abc"
    assert _normalize_doi("  10.1234/abc  ") == "10.1234/abc"


def test_title_similar_substring_and_jaccard() -> None:
    assert _title_similar("Bleak House", "Bleak House")
    assert _title_similar(
        "London: The Biography",
        "London The Biography",  # punctuation stripped
    )
    assert _title_similar(
        "Bleak House",
        "Bleak House: A Novel",  # substring
    )
    assert not _title_similar(
        "Bleak House",
        "Charles Dickens as a Legal Historian",
    )
    assert not _title_similar("", "Bleak House")


def test_author_overlaps_by_surname() -> None:
    assert _author_overlaps(("Peter Ackroyd",), ["Ackroyd, Peter"])
    assert _author_overlaps(("Peter Ackroyd",), ["Peter Ackroyd"])
    assert not _author_overlaps(("Peter Ackroyd",), ["Charles Dickens"])
    # Empty ref-authors: no constraint
    assert _author_overlaps((), ["Whoever"])


# ── DOI branch ───────────────────────────────────────────────────


def test_resolves_via_doi_when_head_ok(verifier) -> None:
    v, sess = verifier
    sess.set_head("https://doi.org/10.1234/abc", 200)
    r = v.resolve(CandidateReference(
        title="Some Paper", doi="10.1234/abc",
    ))
    assert r.resolved
    assert r.source == "doi"
    assert r.url == "https://doi.org/10.1234/abc"
    assert r.attempted == ("doi",)


def test_doi_with_full_url_prefix(verifier) -> None:
    v, sess = verifier
    sess.set_head("https://doi.org/10.1234/abc", 200)
    r = v.resolve(CandidateReference(
        title="x", doi="https://doi.org/10.1234/abc",
    ))
    assert r.url == "https://doi.org/10.1234/abc"


def test_invalid_doi_form_falls_through(verifier) -> None:
    v, sess = verifier
    # Not a real DOI; cascade should move past it
    r = v.resolve(CandidateReference(title="x", doi="not-a-doi"))
    assert not r.resolved  # nothing else routed
    assert "doi" not in r.attempted  # we never attempt invalid DOIs


# ── raw_url branch ───────────────────────────────────────────────


def test_real_raw_url_verified_head(verifier) -> None:
    v, sess = verifier
    sess.set_head("https://example.com/paper.pdf", 200)
    r = v.resolve(CandidateReference(
        title="x", raw_url="https://example.com/paper.pdf",
    ))
    assert r.resolved
    assert r.source == "raw_url"


def test_synthetic_raw_url_skipped(verifier) -> None:
    """wiki-fr: and the like are not attempted as raw_url at all."""
    v, sess = verifier
    r = v.resolve(CandidateReference(
        title="x", raw_url="wiki-fr:https://en.wikipedia.org/wiki/X",
    ))
    assert "raw_url" not in r.attempted


def test_raw_url_4xx_falls_through(verifier) -> None:
    v, sess = verifier
    sess.set_head("https://example.com/dead", 404)
    r = v.resolve(CandidateReference(
        title="x", raw_url="https://example.com/dead",
    ))
    assert "raw_url" in r.attempted
    assert r.source != "raw_url"


# ── OpenAlex branch ──────────────────────────────────────────────


def _openalex_result(*, title, authors, year, doi=None):
    return {
        "display_name": title,
        "publication_year": year,
        "doi": doi,
        "authorships": [
            {"author": {"display_name": a}} for a in authors
        ],
    }


def test_openalex_resolves_via_doi(verifier) -> None:
    v, sess = verifier
    sess.set_get("https://api.openalex.org/works", 200, {
        "results": [_openalex_result(
            title="London: The Biography",
            authors=["Peter Ackroyd"],
            year=2000,
            doi="https://doi.org/10.5555/lon",
        )],
    })
    sess.set_head("https://doi.org/10.5555/lon", 200)
    r = v.resolve(CandidateReference(
        title="London: The Biography",
        authors=("Peter Ackroyd",),
        year=2000,
    ))
    assert r.resolved
    assert r.source == "openalex"
    assert r.url == "https://doi.org/10.5555/lon"
    assert r.attempted == ("openalex",)  # no doi/raw_url tried


def test_openalex_skips_when_title_mismatch(verifier) -> None:
    v, sess = verifier
    sess.set_get("https://api.openalex.org/works", 200, {
        "results": [_openalex_result(
            title="Totally Different Work",
            authors=["Peter Ackroyd"],
            year=2000,
            doi="https://doi.org/10.5555/x",
        )],
    })
    # OpenAlex returns something, but title doesn't match → fall through
    r = v.resolve(CandidateReference(
        title="London: The Biography",
        authors=("Peter Ackroyd",),
    ))
    assert r.source != "openalex"


def test_openalex_skips_when_author_mismatch(verifier) -> None:
    v, sess = verifier
    sess.set_get("https://api.openalex.org/works", 200, {
        "results": [_openalex_result(
            title="London: The Biography",
            authors=["Some Other Author"],
            year=2000,
            doi="https://doi.org/10.5555/x",
        )],
    })
    r = v.resolve(CandidateReference(
        title="London: The Biography",
        authors=("Peter Ackroyd",),
    ))
    assert r.source != "openalex"


def test_openalex_year_filter(verifier) -> None:
    v, sess = verifier
    sess.set_get("https://api.openalex.org/works", 200, {
        "results": [_openalex_result(
            title="London: The Biography",
            authors=["Peter Ackroyd"],
            year=1950,
            doi="https://doi.org/10.5555/x",
        )],
    })
    # Requested year 2000; result is 1950 (Δ > 2) → reject
    r = v.resolve(CandidateReference(
        title="London: The Biography",
        authors=("Peter Ackroyd",),
        year=2000,
    ))
    assert r.source != "openalex"


# ── OpenLibrary branch ───────────────────────────────────────────


def test_openlibrary_resolves_book(verifier) -> None:
    v, sess = verifier
    # OpenAlex returns nothing
    sess.set_get("https://api.openalex.org/works", 200, {"results": []})
    sess.set_get("https://openlibrary.org/search.json", 200, {
        "docs": [{
            "title": "London: The Biography",
            "author_name": ["Peter Ackroyd"],
            "key": "/works/OL12345W",
        }],
    })
    sess.set_head("https://openlibrary.org/works/OL12345W", 200)
    r = v.resolve(CandidateReference(
        title="London: The Biography",
        authors=("Peter Ackroyd",),
    ))
    assert r.resolved
    assert r.source == "openlibrary"
    assert r.url == "https://openlibrary.org/works/OL12345W"
    assert r.attempted == ("openalex", "openlibrary")


def test_openlibrary_ignores_non_works_keys(verifier) -> None:
    v, sess = verifier
    sess.set_get("https://api.openalex.org/works", 200, {"results": []})
    sess.set_get("https://openlibrary.org/search.json", 200, {
        "docs": [{
            "title": "London: The Biography",
            "author_name": ["Peter Ackroyd"],
            "key": "/authors/OL999A",  # not /works/
        }],
    })
    r = v.resolve(CandidateReference(
        title="London: The Biography",
        authors=("Peter Ackroyd",),
    ))
    assert r.source != "openlibrary"


# ── Wikipedia branch ─────────────────────────────────────────────


def test_wikipedia_resolves_with_close_title(verifier) -> None:
    v, sess = verifier
    sess.set_get("https://api.openalex.org/works", 200, {"results": []})
    sess.set_get("https://openlibrary.org/search.json", 200, {"docs": []})
    sess.set_get("https://en.wikipedia.org/w/api.php", 200, {
        "query": {"pages": {
            "12345": {
                "pageid": 12345,
                "title": "London: The Biography",
            },
        }},
    })
    sess.set_head(
        "https://en.wikipedia.org/wiki/London", 200,  # matches "London:_The_Biography"-quoted
    )
    r = v.resolve(CandidateReference(
        title="London: The Biography",
        authors=("Peter Ackroyd",),
    ))
    assert r.resolved
    assert r.source == "wikipedia"


def test_wikipedia_rejected_when_title_mismatch(verifier) -> None:
    v, sess = verifier
    sess.set_get("https://api.openalex.org/works", 200, {"results": []})
    sess.set_get("https://openlibrary.org/search.json", 200, {"docs": []})
    # Wikipedia returns an article whose title doesn't match the work.
    # This is the old bug: "Charles Dickens as a Legal Historian"
    # lookup landing on the /wiki/Bleak_House article. Must NOT resolve.
    sess.set_get("https://en.wikipedia.org/w/api.php", 200, {
        "query": {"pages": {
            "1": {"pageid": 1, "title": "Bleak House"},
        }},
    })
    r = v.resolve(CandidateReference(
        title="Charles Dickens as a Legal Historian",
        authors=("Some Author",),
    ))
    assert r.source != "wikipedia"
    assert not r.resolved


def test_wikipedia_skips_missing_article(verifier) -> None:
    v, sess = verifier
    sess.set_get("https://api.openalex.org/works", 200, {"results": []})
    sess.set_get("https://openlibrary.org/search.json", 200, {"docs": []})
    sess.set_get("https://en.wikipedia.org/w/api.php", 200, {
        "query": {"pages": {
            "-1": {"pageid": -1, "title": "Doesnotexist", "missing": ""},
        }},
    })
    r = v.resolve(CandidateReference(title="Doesnotexist"))
    assert not r.resolved


# ── All-fail path ────────────────────────────────────────────────


def test_unresolved_records_full_attempted_list(verifier) -> None:
    v, sess = verifier
    # Default routes return 404; cascade should run every step and fail.
    sess.set_get("https://api.openalex.org/works", 200, {"results": []})
    sess.set_get("https://openlibrary.org/search.json", 200, {"docs": []})
    sess.set_get("https://en.wikipedia.org/w/api.php", 200, {
        "query": {"pages": {}},
    })
    r = v.resolve(CandidateReference(
        title="Some Nonexistent Work",
        authors=("Nobody",),
        doi="not-a-doi",
        raw_url="wiki-fr:https://en.wikipedia.org/wiki/X",
    ))
    assert not r.resolved
    assert r.url is None
    assert r.source is None
    assert r.reason == "no_match"
    # No DOI (invalid form) and no raw_url (synthetic prefix) were
    # attempted; the three search strategies were.
    assert r.attempted == ("openalex", "openlibrary", "wikipedia")


# ── Cache ────────────────────────────────────────────────────────


def test_cache_short_circuits_second_call(verifier) -> None:
    v, sess = verifier
    sess.set_head("https://doi.org/10.1234/abc", 200)
    ref = CandidateReference(title="x", doi="10.1234/abc")

    r1 = v.resolve(ref)
    head_calls_after_first = len(sess.head_log)
    get_calls_after_first = len(sess.get_log)

    r2 = v.resolve(ref)
    assert r1 == r2
    # Second call must not have made any new HTTP requests.
    assert len(sess.head_log) == head_calls_after_first
    assert len(sess.get_log) == get_calls_after_first


def test_cache_survives_restart(tmp_path: Path) -> None:
    """Resolve once with one verifier, then construct a fresh verifier
    pointing at the same cache file and confirm it returns the cached
    result without HTTP."""
    cache = tmp_path / "cache.sqlite3"

    sess1 = FakeSession()
    sess1.set_head("https://doi.org/10.1234/x", 200)
    v1 = ReferenceVerifier(cache_path=cache, session=sess1)
    ref = CandidateReference(title="x", doi="10.1234/x")
    r1 = v1.resolve(ref)
    assert r1.resolved

    # New verifier, fresh fake session that has no routes. If the
    # cache is reused, no HTTP is needed.
    sess2 = FakeSession()
    v2 = ReferenceVerifier(cache_path=cache, session=sess2)
    r2 = v2.resolve(ref)

    assert r2 == r1
    assert sess2.head_log == []
    assert sess2.get_log == []


# ── ResolverResult ergonomics ────────────────────────────────────


def test_resolver_result_resolved_property() -> None:
    r1 = ResolverResult(url="https://x", source="doi", attempted=("doi",))
    assert r1.resolved
    r2 = ResolverResult(url=None, source=None, attempted=("doi",), reason="no_match")
    assert not r2.resolved
