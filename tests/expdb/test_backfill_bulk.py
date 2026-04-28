from __future__ import annotations

import json
from pathlib import Path

from enrichment.expdb.backfill import scan_runs_dir
from enrichment.expdb.store import Store


def _make_run(parent: Path, label: str, novel: str, panel: str) -> None:
    rd = parent / label
    (rd / "audio").mkdir(parents=True)
    (rd / "run_manifest.json").write_text(json.dumps({
        "schema_version": 1, "run_id": label,
        "axes": {"novel": novel, "pipeline": "trn", "panel": panel,
                  "hostprep": False, "generator": "anthropic_sonnet_4_6"},
        "stages": {}, "audio_variants": [],
        "generated_at": "2026-04-25T10:00:00Z", "dvc_lock_sha": "x",
    }))
    (rd / "phase3_episode.json").write_text(json.dumps({"segments": []}))


def test_scan_runs_dir_processes_all(tmp_path: Path, tmp_db_path: Path) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    _make_run(runs, "bh_trn_literary",     "bh",   "literary")
    _make_run(runs, "bh_trn_alternatives", "bh",   "alternatives")
    _make_run(runs, "motf_trn_literary",   "motf", "literary")

    s = Store(tmp_db_path)
    s.init_schema()
    summary = scan_runs_dir(s, runs)

    assert summary["scanned"] == 3
    assert summary["episodes_inserted"] == 3
    assert summary["scripts_inserted"] == 3
    assert summary["errors"] == []


def test_scan_runs_dir_skips_dirs_missing_required_files(tmp_path: Path, tmp_db_path: Path) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    _make_run(runs, "ok_run", "bh", "literary")
    (runs / "broken").mkdir()
    # No manifests inside broken/.

    s = Store(tmp_db_path)
    s.init_schema()
    summary = scan_runs_dir(s, runs)

    assert summary["scanned"] == 1
    assert summary["skipped"] == 1
