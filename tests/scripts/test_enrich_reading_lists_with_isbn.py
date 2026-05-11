"""Unit tests for the pure parts of scripts/enrich_reading_lists_with_isbn.py.

The script's I/O surface is covered by integration smoke (the
dry-run output is reported in commit messages); these tests cover
the pure functions where a regression would be silent: source-
article extraction from wiki-fr URLs, and the title+author
matching between reading-list entries and Wikipedia cite-templates.
"""
from __future__ import annotations

from enrichment.reference_tools import _CiteCandidate  # pyright: ignore[reportPrivateUsage]
from scripts.enrich_reading_lists_with_isbn import (  # pyright: ignore[reportMissingImports]
    _find_match,
    _source_article,
)


def test_source_article_extracts_path_from_wiki_fr_url() -> None:
    assert _source_article(
        "wiki-fr:https://en.wikipedia.org/wiki/David_Copperfield"
        "#charles_dickens:_a_life"
    ) == "David_Copperfield"


def test_source_article_handles_url_encoded_titles() -> None:
    assert _source_article(
        "wiki-fr:https://en.wikipedia.org/wiki/North_and_South_"
        "(Gaskell_novel)#some_anchor"
    ) == "North_and_South_(Gaskell_novel)"


def test_source_article_returns_empty_for_non_wiki_fr() -> None:
    assert _source_article("") == ""
    assert _source_article("https://en.wikipedia.org/wiki/x") == ""
    assert _source_article("wiki-fr:https://example.com/x") == ""


def _cite(
    *, title, authors=(), isbn="", doi="", year=None, publisher="",
):
    return _CiteCandidate(
        title=title, authors=list(authors), year=year, publisher=publisher,
        url="", doi=doi, isbn=isbn, cite_kind="cite book", raw_text="",
    )


def test_find_match_returns_cite_with_isbn_when_title_and_author_match() -> None:
    """The Tomalin case: entry with title+author matches the cite-
    template that carries the ISBN."""
    entry = {
        "title": "Charles Dickens: A Life",
        "authors": ["Claire Tomalin"],
        "year": 2011,
    }
    candidates = [
        _cite(title="Some Other Book", authors=["Whoever"], isbn="123"),
        _cite(
            title="Charles Dickens: A Life",
            authors=["Claire Tomalin"],
            isbn="9780670917679",
            year=2011,
        ),
    ]
    match = _find_match(entry, candidates)
    assert match is not None
    assert match.isbn == "9780670917679"


def test_find_match_returns_none_when_no_title_match() -> None:
    entry = {"title": "Charles Dickens: A Life", "authors": ["Tomalin"]}
    candidates = [
        _cite(title="The Great Gatsby", authors=["Fitzgerald"], isbn="x"),
    ]
    assert _find_match(entry, candidates) is None


def test_find_match_returns_none_when_no_author_match() -> None:
    """Title alone isn't enough — different works can share titles
    (or close ones). Author surname overlap is required."""
    entry = {"title": "London: The Biography", "authors": ["Peter Ackroyd"]}
    candidates = [
        _cite(
            title="London: The Biography",
            authors=["Some Different Person"],
            isbn="x",
        ),
    ]
    assert _find_match(entry, candidates) is None


def test_find_match_empty_entry_authors_skips_author_gate() -> None:
    """Some legacy entries have no author list. We then require only
    title similarity (consistent with _author_overlaps' empty-ref
    semantics in reference_verify)."""
    entry = {"title": "London: The Biography", "authors": []}
    candidates = [
        _cite(
            title="London: The Biography",
            authors=["Peter Ackroyd"],
            isbn="9999",
        ),
    ]
    match = _find_match(entry, candidates)
    assert match is not None
    assert match.isbn == "9999"


def test_find_match_uses_openalex_title_fallback_for_legacy_schema() -> None:
    """Legacy-schema entries have openalex_title, not title."""
    entry = {
        "title": "",
        "openalex_title": "Charles Dickens: A Life",
        "openalex_authors": ["Claire Tomalin"],
    }
    candidates = [
        _cite(
            title="Charles Dickens: A Life",
            authors=["Tomalin, Claire"],
            isbn="9780670917679",
        ),
    ]
    match = _find_match(entry, candidates)
    assert match is not None
    assert match.isbn == "9780670917679"


def test_find_match_returns_none_when_entry_has_no_title() -> None:
    entry = {"title": "", "authors": []}
    candidates = [_cite(title="x", isbn="y")]
    assert _find_match(entry, candidates) is None
