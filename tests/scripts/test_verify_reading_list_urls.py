"""Unit tests for the pure parts of scripts/verify_reading_list_urls.py.

Focus is the entry → CandidateReference translation, which has a
subtle re-run hazard: on the second pass the entry's `url` field
already holds the *previous* cascade result, not the original
pre-backfill URL. Feeding that back in as raw_url would short-
circuit the cascade through the raw_url HEAD-check step and
re-admit any URL that still HEAD-200s — defeating any tightening
of the OpenAlex landing-page policy.
"""
from __future__ import annotations

from scripts.verify_reading_list_urls import (  # pyright: ignore[reportMissingImports]
    _entry_to_candidate,
)


def test_first_pass_uses_url_as_raw_url() -> None:
    """Before any backfill, entries don't have a `raw_url` field;
    the original URL lives in `url`."""
    entry = {
        "title": "Charles Dickens: A Life",
        "authors": ["Claire Tomalin"],
        "year": 2011,
        "url": "wiki-fr:https://en.wikipedia.org/wiki/David_Copperfield",
    }
    ref = _entry_to_candidate(entry)
    assert ref.raw_url == "wiki-fr:https://en.wikipedia.org/wiki/David_Copperfield"
    assert ref.title == "Charles Dickens: A Life"
    assert ref.authors == ("Claire Tomalin",)
    assert ref.year == 2011


def test_rerun_prefers_preserved_raw_url_over_resolved_url() -> None:
    """After backfill, `url` is the previous cascade *result* and
    `raw_url` holds the original. The candidate must carry the
    original, not the previous result — otherwise the raw_url
    cascade step admits previously-resolved bad URLs on re-runs."""
    entry = {
        "title": "Charles Dickens: A Life",
        "authors": ["Claire Tomalin"],
        "year": 2011,
        # previous cascade resolved to a soft-404 foreign catalog
        "url": "http://bvbr.bib-bvb.de:8991/F?doc_number=024476258",
        # the original pre-backfill URL was a synthetic wiki-fr scheme
        "raw_url": "wiki-fr:https://en.wikipedia.org/wiki/David_Copperfield",
        "resolution_status": "resolved",
        "resolution_source": "openalex",
    }
    ref = _entry_to_candidate(entry)
    # Synthetic wiki-fr: gets rejected downstream by _is_real_url,
    # so the cascade falls through to OpenAlex (the desired path).
    # The previously-resolved bvbr URL must NOT appear as raw_url.
    assert ref.raw_url == "wiki-fr:https://en.wikipedia.org/wiki/David_Copperfield"
    assert "bvbr.bib-bvb.de" not in ref.raw_url


def test_empty_raw_url_falls_back_to_url() -> None:
    """If raw_url is empty but url is set, use url. Covers the
    legacy-schema path where backfill never wrote raw_url and the
    entry only has the original `url`."""
    entry = {
        "title": "x",
        "raw_url": "",
        "url": "https://example.com/paper",
    }
    ref = _entry_to_candidate(entry)
    assert ref.raw_url == "https://example.com/paper"


def test_isbn_and_source_trusted_propagate_for_wikipedia_entries() -> None:
    """Entries from Wikipedia further-reading sections must carry
    isbn + source_trusted=True so the cascade can use the ISBN
    branch with the trust-admit policy (CLAUDE.md)."""
    entry = {
        "title": "Charles Dickens: A Life",
        "authors": ["Claire Tomalin"],
        "year": 2011,
        "isbn": "9780670917679",
        "source": "wikipedia_further_reading",
    }
    ref = _entry_to_candidate(entry)
    assert ref.isbn == "9780670917679"
    assert ref.source_trusted is True


def test_source_trusted_false_for_non_wikipedia_entries() -> None:
    """Non-Wikipedia entries must NOT get the trust flag. The strict
    HEAD-verify rule still applies to OpenAlex-sourced citations,
    LLM-tool-call citations, etc."""
    entry = {
        "title": "x",
        "isbn": "9780670917679",
        "source": "openalex",
    }
    ref = _entry_to_candidate(entry)
    assert ref.isbn == "9780670917679"
    assert ref.source_trusted is False
