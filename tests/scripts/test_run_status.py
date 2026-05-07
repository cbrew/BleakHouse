"""Unit tests for scripts.run_status (the pure formatting/aggregation parts).

Post-CAS-migration the DVC stage-status integration is gone; the
script reports purely on file presence. STALE is no longer a
possible verdict — only FRESH and INCOMPLETE.
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


def test_format_text_missing_files() -> None:
    report = {
        "run_id": "bh_trn_literary",
        "run_dir": "/repo/data/runs/bh_trn_literary",
        "verdict": "INCOMPLETE",
        "stages": [
            {"phase": "phase4_post", "state": "PARTIAL",
             "files_present": ["manifest.json"],
             "files_missing": ["report.html"],
             "reasons": [{"missing_files": ["report.html"]}]},
        ],
    }
    text = _format_text(report)
    assert "PARTIAL" in text
    assert "missing: report.html" in text
    assert "VERDICT: INCOMPLETE" in text
