"""Tests for the BleakHouse-hgws rewrite of read_wikipedia_article.

Covers the new pure helpers (_strip_wikitext, _normalize_isbn,
_extract_year, _extract_authors, _extract_cite_templates), then an
end-to-end test using a small Parsoid-shaped HTML fixture that
exercises the full cite-template-to-CandidateReference pipeline
without HTTP.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from enrichment.reference_tools import (
    CitationRegistry,
    _extract_authors,
    _extract_cite_templates,
    _extract_year,
    _normalize_isbn,
    _strip_wikitext,
    execute_read_wikipedia_article,
)
from enrichment.reference_verify import (
    CandidateReference,
    ResolverResult,
)


# ── _strip_wikitext ──


def test_strip_wikitext_handles_links_and_emphasis() -> None:
    assert _strip_wikitext("''italic''") == "italic"
    assert _strip_wikitext("'''bold'''") == "bold"
    assert _strip_wikitext("[[Bleak House]]") == "Bleak House"
    assert _strip_wikitext("[[Bleak House|the novel]]") == "the novel"
    assert _strip_wikitext("[https://example.com text]") == "text"
    assert _strip_wikitext("") == ""
    assert _strip_wikitext("  plain text  ") == "plain text"


# ── _normalize_isbn ──


def test_normalize_isbn_keeps_valid_lengths() -> None:
    assert _normalize_isbn("978-0-19-953555-9") == "9780199535559"
    assert _normalize_isbn("0-14-043063-9") == "0140430639"
    assert _normalize_isbn("0140430639") == "0140430639"
    assert _normalize_isbn("0-14-X43063-9") == "014X430639"


def test_normalize_isbn_rejects_wrong_length() -> None:
    assert _normalize_isbn("") == ""
    assert _normalize_isbn("12345") == ""
    assert _normalize_isbn("01234567890") == ""  # 11 digits — not 10/13


# ── _extract_year ──


def test_extract_year_finds_4_digit_year() -> None:
    assert _extract_year("1852") == 1852
    assert _extract_year("September 2013") == 2013
    assert _extract_year("9 March 2012") == 2012
    assert _extract_year("c. 1850s") == 1850


def test_extract_year_rejects_out_of_range() -> None:
    assert _extract_year("") is None
    assert _extract_year("1066") is None  # too early
    assert _extract_year("2099") is None  # too future
    assert _extract_year("no digits") is None


# ── _extract_authors ──


def _wt(s: str) -> dict[str, Any]:
    return {"wt": s}


def test_extract_authors_single_author_param() -> None:
    assert _extract_authors({"author": _wt("Charles Dickens")}) == [
        "Charles Dickens",
    ]


def test_extract_authors_multi_authors_param() -> None:
    assert _extract_authors({"authors": _wt("Alice Smith; Bob Jones")}) == [
        "Alice Smith", "Bob Jones",
    ]


def test_extract_authors_last_first_compound() -> None:
    assert _extract_authors({
        "last": _wt("Dickens"), "first": _wt("Charles"),
    }) == ["Charles Dickens"]


def test_extract_authors_numbered_last_first() -> None:
    params = {
        "last1": _wt("Smith"), "first1": _wt("Alice"),
        "last2": _wt("Jones"), "first2": _wt("Bob"),
    }
    assert _extract_authors(params) == ["Alice Smith", "Bob Jones"]


def test_extract_authors_dedupes_overlapping_forms() -> None:
    """If both author=X and last=X first=Y are present, dedupe."""
    params = {
        "author": _wt("Charles Dickens"),
        "last": _wt("Dickens"), "first": _wt("Charles"),
    }
    assert _extract_authors(params) == ["Charles Dickens"]


def test_extract_authors_strips_wikitext_in_values() -> None:
    assert _extract_authors({"author": _wt("[[Charles Dickens]]")}) == [
        "Charles Dickens",
    ]


# ── _extract_cite_templates: minimal HTML fixture ──


# Trimmed Parsoid-shape HTML page with three cite-templates.
# Real Wikipedia HTML emits `about="#mwt<N>"` on the rendered
# elements and stores parameters in the `data-mw` attribute as JSON
# (parsed via ast.literal_eval by the library).
FIXTURE_HTML = """<!DOCTYPE html>
<html><head><title>Test Article</title>
<base href="//en.wikipedia.org/wiki/"/>
</head><body>
<section data-mw-section-id="1"><p>
Holdsworth's lectures on Dickens<sup id="cite_ref-h1" class="mw-ref reference">
<a href="#cite_note-h1"><span>[1]</span></a></sup>.
</p></section>

<section data-mw-section-id="2"><h2 id="Further_reading">Further reading</h2>
<ul>
<li about="#mwt1" typeof="mw:Transclusion" data-mw='{"parts": [{"template": {"target": {"wt": "cite book", "href": "./Template:Cite_book"}, "params": {"last": {"wt": "Holdsworth"}, "first": {"wt": "William S."}, "title": {"wt": "Charles Dickens as a Legal Historian"}, "year": {"wt": "1928"}, "publisher": {"wt": "Yale University Press"}, "url": {"wt": "https://archive.org/details/in.ernet.dli.2015.152260"}, "isbn": {"wt": "0-19-953555-9"}}, "i": 0}}]}'><span>Citation rendering</span></li>
<li about="#mwt2" typeof="mw:Transclusion" data-mw='{"parts": [{"template": {"target": {"wt": "cite journal", "href": "./Template:Cite_journal"}, "params": {"author": {"wt": "Oldham, James"}, "title": {"wt": "A Profusion of Chancery Reform"}, "journal": {"wt": "Law and History Review"}, "date": {"wt": "2004"}, "doi": {"wt": "10.2307/4141691"}}, "i": 0}}]}'><span>Citation rendering</span></li>
<li about="#mwt3" typeof="mw:Transclusion" data-mw='{"parts": [{"template": {"target": {"wt": "cite book", "href": "./Template:Cite_book"}, "params": {"author": {"wt": "Author With No Url"}, "title": {"wt": "Untraceable Work"}, "year": {"wt": "1899"}, "publisher": {"wt": "Obscure Press"}}, "i": 0}}]}'><span>Citation rendering</span></li>
</ul></section>

</body></html>
"""


def test_extract_cite_templates_parses_three_kinds() -> None:
    cands = _extract_cite_templates(FIXTURE_HTML)
    assert len(cands) == 3

    holds = next(c for c in cands if "Holdsworth" in (c.authors[0] if c.authors else ""))
    assert holds.title == "Charles Dickens as a Legal Historian"
    assert holds.authors == ["William S. Holdsworth"]
    assert holds.year == 1928
    assert holds.publisher == "Yale University Press"
    assert holds.url == "https://archive.org/details/in.ernet.dli.2015.152260"
    assert holds.isbn == "0199535559"
    assert holds.cite_kind == "cite book"

    oldham = next(c for c in cands if c.title.startswith("A Profusion"))
    assert oldham.doi == "10.2307/4141691"
    assert oldham.year == 2004
    assert oldham.cite_kind == "cite journal"

    obscure = next(c for c in cands if c.title == "Untraceable Work")
    assert obscure.year == 1899
    assert obscure.url == ""
    assert obscure.doi == ""
    assert obscure.isbn == ""


def test_extract_cite_templates_empty_html() -> None:
    assert _extract_cite_templates("") == []


# ── End-to-end: execute_read_wikipedia_article ──


class _FakeVerifier:
    """ReferenceVerifier stand-in that returns scripted results by
    candidate title. Lets us exercise execute_read_wikipedia_article
    end-to-end without HTTP."""

    def __init__(self, results: dict[str, ResolverResult]) -> None:
        self._results = results
        self.resolved_calls: list[CandidateReference] = []

    def resolve(self, ref: CandidateReference) -> ResolverResult:
        self.resolved_calls.append(ref)
        return self._results.get(
            ref.title,
            ResolverResult(
                url=None, source=None,
                attempted=("openalex", "openlibrary", "wikipedia"),
                reason="no_match",
            ),
        )


@pytest.fixture
def monkeypatched_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace _fetch_wikipedia_html with a fixture loader."""
    from enrichment import reference_tools as rt
    monkeypatch.setattr(
        rt, "_fetch_wikipedia_html",
        lambda title, recorder=None: FIXTURE_HTML,
    )


def test_execute_read_wikipedia_article_registers_resolved_and_unresolved(
    monkeypatched_fetch, tmp_path: Path,
) -> None:
    registry = CitationRegistry()
    parent_tag = registry.register(
        title="Test Article",
        url="https://en.wikipedia.org/wiki/Test_Article",
        source="wikipedia_article",
        type="wikipedia_article",
    )

    fake_verifier = _FakeVerifier({
        "Charles Dickens as a Legal Historian": ResolverResult(
            url="https://archive.org/details/in.ernet.dli.2015.152260",
            source="raw_url",
            attempted=("raw_url",),
        ),
        "A Profusion of Chancery Reform": ResolverResult(
            url="https://doi.org/10.2307/4141691",
            source="doi",
            attempted=("doi",),
        ),
        # 'Untraceable Work' falls through to default = unresolved
    })

    output = execute_read_wikipedia_article(
        parent_tag, registry, verifier=fake_verifier,  # type: ignore[arg-type]
    )

    # The function returned an LLM-facing summary with each tagged item.
    assert "ref-2" in output  # first new candidate
    assert "Holdsworth" in output  # author included
    assert "unresolved" in output  # marker on the unresolved item

    # Registry state
    rs = [r for r in registry.all() if r.parent_tag == parent_tag]
    assert len(rs) == 3
    by_title = {r.title: r for r in rs}

    holds = by_title["Charles Dickens as a Legal Historian"]
    assert holds.resolution_status == "resolved"
    assert holds.resolution_source == "raw_url"
    assert holds.url == "https://archive.org/details/in.ernet.dli.2015.152260"

    oldham = by_title["A Profusion of Chancery Reform"]
    assert oldham.resolution_status == "resolved"
    assert oldham.url == "https://doi.org/10.2307/4141691"

    obscure = by_title["Untraceable Work"]
    assert obscure.resolution_status == "unresolved"
    assert obscure.url == ""
    assert obscure.resolution_reason == "no_match"
    assert "openalex" in obscure.attempted
    # raw_text preserves the structured cite-template for the
    # eventual HTML-comment renderer in ticket 7cgk.
    assert "cite book" in obscure.raw_text
    assert "Untraceable Work" in obscure.raw_text


def test_no_wiki_fr_substrings_anywhere(
    monkeypatched_fetch, tmp_path: Path,
) -> None:
    """The whole point of hgws: zero wiki-fr: URLs after the rewrite."""
    registry = CitationRegistry()
    parent = registry.register(
        title="Test", url="https://en.wikipedia.org/wiki/Test",
        source="wikipedia_article", type="wikipedia_article",
    )
    fake = _FakeVerifier({})  # everything unresolved by default
    execute_read_wikipedia_article(
        parent, registry, verifier=fake,  # type: ignore[arg-type]
    )
    for r in registry.all():
        assert "wiki-fr" not in r.url
        assert "wiki-fr" not in (r.description or "")
        assert "wiki-fr" not in r.raw_text


def test_isbn_only_candidate_builds_openlibrary_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a cite-template has ISBN but no URL, the candidate's
    raw_url is set to https://openlibrary.org/isbn/<isbn> so the
    cascade's raw_url branch picks it up via HEAD."""
    from enrichment import reference_tools as rt

    isbn_only_html = """<html><head>
<base href="//en.wikipedia.org/wiki/"/>
</head><body>
<li about="#mwt1" typeof="mw:Transclusion" data-mw='{"parts": [{"template": {"target": {"wt": "cite book"}, "params": {"title": {"wt": "Some Book"}, "author": {"wt": "X"}, "isbn": {"wt": "978-0-19-953555-9"}}, "i": 0}}]}'></li>
</body></html>"""

    monkeypatch.setattr(
        rt, "_fetch_wikipedia_html",
        lambda title, recorder=None: isbn_only_html,
    )

    seen: list[CandidateReference] = []

    class Recorder:
        def resolve(self, ref: CandidateReference) -> ResolverResult:
            seen.append(ref)
            return ResolverResult(
                url=None, source=None, attempted=(), reason="no_match",
            )

    registry = CitationRegistry()
    parent = registry.register(
        title="X", url="https://en.wikipedia.org/wiki/X",
        source="wikipedia_article", type="wikipedia_article",
    )
    execute_read_wikipedia_article(
        parent, registry, verifier=Recorder(),  # type: ignore[arg-type]
    )

    assert len(seen) == 1
    assert seen[0].raw_url == "https://openlibrary.org/isbn/9780199535559"
