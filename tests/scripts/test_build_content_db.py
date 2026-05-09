"""Smoke test for scripts/build_content_db.py.

Builds a tiny content.db from a synthetic two-novel / two-run fixture
tree, then runs the round-trip verifier. Catches the class of bug where
build() and verify() drift out of sync (e.g. a new kind added to one
but not the other, or arc serialization changing on one side only).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_content_db as bcd  # noqa: E402


@pytest.fixture
def fake_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A miniature data/ tree with two runs and one novel."""
    runs = tmp_path / "runs"
    novels = tmp_path / "novels"
    runs.mkdir()
    novels.mkdir()

    rd = runs / "synth_run_a"
    rd.mkdir()
    (rd / "config.json").write_text('{"axes": {"novel": "synth"}}\n')
    (rd / "phase0_segments.json").write_text(
        json.dumps([{"name": "Opening", "segment_type": "opening"}], indent=2) + "\n"
    )
    (rd / "phase1_assignments.json").write_text("[]\n")
    (rd / "phase2_plan.json").write_text("{}\n")
    (rd / "phase2_5_reading_list.json").write_text("{}\n")
    (rd / "phase3_episode.json").write_text(
        json.dumps({"segments": [{"turns": []}]}) + "\n"
    )
    # No phase2_5_interviews / host_briefs / teaser / shards — simulating a
    # sparse run. build() must skip-not-fail for missing kinds.

    nd = novels / "synth_novel"
    nd.mkdir()
    (nd / "character_arcs.json").write_text('{"Foo": ["c1"]}\n')
    (nd / "passages_enriched.json").write_text("[]\n")
    (nd / "clusters_characters.json").write_text("{}\n")
    (nd / "clusters_literary.json").write_text("{}\n")

    monkeypatch.setattr(bcd, "RUNS_DIR", runs)
    monkeypatch.setattr(bcd, "NOVELS_DIR", novels)
    # Skip the Python-arcs path — it imports project modules that aren't
    # parameterised on the fixture tree.
    monkeypatch.setattr(bcd, "_python_arcs", lambda: {})
    return tmp_path


def test_build_then_verify_round_trips(fake_tree: Path, tmp_path: Path) -> None:
    db = tmp_path / "content.db"
    out = bcd.build(db)
    assert out["run_artifacts"] >= 6  # config + phase0..phase3 + reading_list
    assert out["novel_artifacts"] == 4
    assert not out["skipped"]

    result = bcd.verify(db)
    assert result["mismatches"] == [], result["mismatches"]
    assert result["missing_on_disk"] == []
    assert result["checked"] == out["run_artifacts"] + out["novel_artifacts"]


def test_verify_detects_drift(fake_tree: Path, tmp_path: Path) -> None:
    """If a source file changes after import, verify must catch it."""
    db = tmp_path / "content.db"
    bcd.build(db)

    # Corrupt one source file and re-verify.
    (fake_tree / "runs" / "synth_run_a" / "config.json").write_text(
        '{"axes": {"novel": "synth"}, "extra": true}\n'
    )
    result = bcd.verify(db)
    assert any("config" in m and "differs" in m for m in result["mismatches"]), \
        result["mismatches"]


def test_build_is_idempotent(fake_tree: Path, tmp_path: Path) -> None:
    db = tmp_path / "content.db"
    bcd.build(db)
    bcd.build(db)  # second pass — must not duplicate or fail
    with sqlite3.connect(db) as conn:
        n_run = conn.execute("SELECT COUNT(*) FROM run_artifact").fetchone()[0]
        n_novel = conn.execute("SELECT COUNT(*) FROM novel_artifact").fetchone()[0]
    assert n_run == 6
    assert n_novel == 4
