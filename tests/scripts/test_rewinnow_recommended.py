"""Unit tests for the pure parts of scripts/rewinnow_recommended.py.

The HTTP-driven part (`_rewinnow_one`) is exercised by smoke-testing
on a single run before the full sweep. These tests cover the
defensive bits: the entry→CitationRecord conversion that strips
non-dataclass keys (added by BleakHouse-7cgk's renderer-support
fields), and the novel-meta lookup from run_manifest.json.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.rewinnow_recommended import (  # pyright: ignore[reportMissingImports]
    _entry_to_record,
    _novel_meta,
)


def test_entry_to_record_strips_unknown_keys() -> None:
    """Entries on disk carry raw_url (added by 7cgk) which is not a
    CitationRecord field. Conversion must succeed by silently
    dropping the extra key, not by raising TypeError."""
    entry = {
        "tag": "ref-1",
        "title": "Charles Dickens: A Life",
        "authors": ["Claire Tomalin"],
        "year": 2011,
        "publisher": "Viking",
        "url": "https://openlibrary.org/isbn/9780670917679",
        "isbn": "9780670917679",
        "source": "wikipedia_further_reading",
        "resolution_status": "resolved",
        "resolution_source": "isbn",
        "head_verified": True,
        # Fields added in later tickets that aren't on CitationRecord:
        "raw_url": "wiki-fr:https://en.wikipedia.org/wiki/David_Copperfield",
        "novel_arc": "ignored-extra-field",
    }
    rec = _entry_to_record(entry)
    assert rec.tag == "ref-1"
    assert rec.title == "Charles Dickens: A Life"
    assert rec.isbn == "9780670917679"
    assert rec.head_verified is True
    # Unknown keys are silently dropped (don't raise).


def test_entry_to_record_handles_minimal_entry() -> None:
    """Some entries have only the required fields. Must not crash."""
    rec = _entry_to_record({"tag": "ref-9", "title": "Just a Title"})
    assert rec.tag == "ref-9"
    assert rec.title == "Just a Title"


def test_entry_to_record_legacy_schema_fallbacks() -> None:
    """15 of 222 runs (0.6% of resolved entries) carry the pre-7cgk
    legacy schema: openalex_title / openalex_authors / openalex_year /
    raw_text instead of title / authors / year, and no tag. The
    function must synthesize a usable record so these entries can
    be picked by the listener-pick LLM."""
    legacy_entry = {
        "openalex_title": "Distant Reading",
        "openalex_authors": ["Franco Moretti"],
        "openalex_year": 2013,
        "raw_text": "Franco Moretti, Distant Reading (2013)",
        "url": "https://example.org/x",
        "resolution_status": "resolved",
    }
    rec = _entry_to_record(legacy_entry, fallback_tag="ref-42")
    assert rec.tag == "ref-42"
    assert rec.title == "Distant Reading"
    assert rec.authors == ["Franco Moretti"]
    assert rec.year == 2013


def test_entry_to_record_legacy_falls_back_to_raw_text() -> None:
    """If openalex_title is empty too, fall back to raw_text."""
    legacy_entry = {
        "openalex_title": "",
        "raw_text": "Edmund Burke, Reflections on the Revolution (1790)",
    }
    rec = _entry_to_record(legacy_entry, fallback_tag="ref-1")
    assert rec.title == "Edmund Burke, Reflections on the Revolution (1790)"


def test_novel_meta_returns_title_and_author(tmp_path: Path) -> None:
    """run_manifest.json's axes.novel maps to a Novel via
    NOVEL_BY_KEY; the function should pull (title, author)."""
    run_dir = tmp_path / "dc_emb_literary"
    run_dir.mkdir()
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"axes": {"novel": "dc"}})
    )
    meta = _novel_meta(run_dir)
    assert meta == ("David Copperfield", "Dickens")


def test_novel_meta_accepts_long_form_id(tmp_path: Path) -> None:
    """5 of 222 manifests use the long ID ('wuthering_heights') in
    axes.novel instead of the short key ('wh'). Both must resolve."""
    run_dir = tmp_path / "wh_trn_literary_short"
    run_dir.mkdir()
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"axes": {"novel": "wuthering_heights"}})
    )
    assert _novel_meta(run_dir) == ("Wuthering Heights", "Brontë")


def test_novel_meta_returns_none_when_manifest_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / "some_run"
    run_dir.mkdir()
    assert _novel_meta(run_dir) is None


def test_novel_meta_returns_none_when_novel_key_unknown(tmp_path: Path) -> None:
    """Defensive: an unrecognised novel key (e.g. an experimental
    run for a novel not in axes.NOVELS) must not crash — we skip
    instead so the operator can decide what to do."""
    run_dir = tmp_path / "exp_run"
    run_dir.mkdir()
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"axes": {"novel": "ZZ_not_a_key"}})
    )
    assert _novel_meta(run_dir) is None


def test_novel_meta_returns_none_when_manifest_corrupt(tmp_path: Path) -> None:
    run_dir = tmp_path / "bad_run"
    run_dir.mkdir()
    (run_dir / "run_manifest.json").write_text("not valid json")
    assert _novel_meta(run_dir) is None
