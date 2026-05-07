"""Preflight enrichment-completeness smoke test (BleakHouse-t1f5).

Catches the 'data is loadable but unusable' class — the bleak_house bug
where every passage's text/summary/best_quote was the empty string but
the JSON itself loaded fine.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from enrichment.run_pipeline import _preflight_check


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A synthetic data/novels/<novel>/passages_enriched.json factory."""
    from cas import paths as cas_paths
    monkeypatch.setattr(cas_paths, "_DATA_DIR", tmp_path / "data")
    return tmp_path


def _passage(pid: str, *, text: str, summary: str, best_quote: str | None) -> dict:
    """Realistic schema: text top-level; summary + best_quote nested under
    enrichment. best_quote may legitimately be None for digressions."""
    return {
        "passage_id": pid,
        "text": text,
        "enrichment": {"summary": summary, "best_quote": best_quote},
    }


def _write_passages(repo: Path, novel: str, passages: list[dict]) -> None:
    novel_dir = repo / "data" / "novels" / novel
    novel_dir.mkdir(parents=True, exist_ok=True)
    (novel_dir / "passages_enriched.json").write_text(json.dumps(passages))


def test_preflight_passes_when_all_passages_populated(fake_repo: Path) -> None:
    passages = [
        _passage(f"p{i}", text="x", summary="y", best_quote="z")
        for i in range(20)
    ]
    _write_passages(fake_repo, "bleak_house", passages)

    _preflight_check("bleak_house")  # no raise


def test_preflight_passes_with_under_5_percent_empty(fake_repo: Path) -> None:
    """Slack for genuine edge cases like chapter-heading passages."""
    passages = [
        _passage(f"p{i}", text="x", summary="y", best_quote="z")
        for i in range(95)
    ] + [
        _passage(f"e{i}", text="", summary="y", best_quote="z")
        for i in range(4)  # 4 / 99 ≈ 4% — under threshold
    ]
    _write_passages(fake_repo, "bleak_house", passages)

    _preflight_check("bleak_house")  # no raise


def test_preflight_raises_on_10_percent_empty(fake_repo: Path) -> None:
    passages = [
        _passage(f"p{i}", text="x", summary="y", best_quote="z")
        for i in range(90)
    ] + [
        _passage(f"empty{i}", text="", summary="", best_quote="")
        for i in range(10)
    ]
    _write_passages(fake_repo, "bleak_house", passages)

    with pytest.raises(RuntimeError) as excinfo:
        _preflight_check("bleak_house")
    msg = str(excinfo.value)
    assert "bleak_house" in msg
    assert "10/100" in msg or "10 of 100" in msg or "10/" in msg
    # First 5 offending IDs surfaced for triage
    assert "empty0" in msg
    assert "empty4" in msg


def test_preflight_raises_on_empty_file(fake_repo: Path) -> None:
    """Empty passages list — pipeline cannot produce anything useful."""
    _write_passages(fake_repo, "bleak_house", [])

    with pytest.raises(RuntimeError, match="empty"):
        _preflight_check("bleak_house")


def test_preflight_treats_missing_field_as_empty(fake_repo: Path) -> None:
    """A passage without text or enrichment.summary keys is also unusable."""
    passages = [{"passage_id": f"p{i}"} for i in range(15)]
    _write_passages(fake_repo, "bleak_house", passages)

    with pytest.raises(RuntimeError):
        _preflight_check("bleak_house")


def test_preflight_ignores_legitimate_null_best_quote(fake_repo: Path) -> None:
    """Digressions / non-literary passages set best_quote=None; those are
    fine as long as text and summary are populated."""
    passages = [
        _passage(f"p{i}", text="t", summary="s", best_quote=None)
        for i in range(20)
    ]
    _write_passages(fake_repo, "bleak_house", passages)

    _preflight_check("bleak_house")  # no raise
