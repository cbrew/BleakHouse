"""Unit tests for scripts.run_status (the pure formatting/aggregation parts).

The dvc-status integration is covered by manual smoke runs; here we
exercise the formatting logic against synthetic inputs.
"""
from __future__ import annotations

from scripts.run_status import _format_text  # pyright: ignore[reportMissingImports]


def test_format_text_fresh_run() -> None:
    report = {
        "run_id": "bh_trn_literary",
        "run_dir": "/repo/data/runs/bh_trn_literary",
        "verdict": "FRESH",
        "stages": [
            {"phase": "phase0_segments", "state": "FRESH",
             "files_present": ["phase0_segments.json"], "files_missing": [], "reasons": []},
            {"phase": "phase4_audio", "state": "FRESH",
             "files_present": ["audio/podcast.mp3"], "files_missing": [], "reasons": []},
        ],
    }
    text = _format_text(report)
    assert "run: bh_trn_literary" in text
    assert "phase0_segments" in text
    assert "FRESH" in text
    assert "VERDICT: FRESH" in text


def test_format_text_stale_run() -> None:
    report = {
        "run_id": "bh_trn_literary",
        "run_dir": "/repo/data/runs/bh_trn_literary",
        "verdict": "STALE",
        "stages": [
            {"phase": "phase4_audio", "state": "STALE",
             "files_present": ["audio/podcast.mp3"], "files_missing": [],
             "reasons": [{"changed deps": ["enrichment/render_audio.py"]}]},
        ],
    }
    text = _format_text(report)
    assert "STALE" in text
    assert "VERDICT: STALE" in text


def test_format_text_missing_files() -> None:
    report = {
        "run_id": "bh_trn_literary",
        "run_dir": "/repo/data/runs/bh_trn_literary",
        "verdict": "INCOMPLETE",
        "stages": [
            {"phase": "phase4_post", "state": "PARTIAL",
             "files_present": ["manifest.json"],
             "files_missing": ["report.html", "report.txt"],
             "reasons": [{"missing_files": ["report.html", "report.txt"]}]},
        ],
    }
    text = _format_text(report)
    assert "PARTIAL" in text
    assert "missing: report.html, report.txt" in text
    assert "VERDICT: INCOMPLETE" in text
