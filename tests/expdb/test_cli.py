from __future__ import annotations

import json
from pathlib import Path

import pytest

from enrichment.expdb.cli import main


def test_cli_scan_then_list_then_show(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "experiments.db"
    runs = tmp_path / "runs"
    rd = runs / "bh_trn_literary" / "audio"
    rd.mkdir(parents=True)
    (rd.parent / "run_manifest.json").write_text(json.dumps({
        "schema_version": 1, "run_id": "bh_trn_literary",
        "axes": {"novel": "bh", "pipeline": "trn", "panel": "literary",
                  "hostprep": False, "generator": "anthropic_sonnet_4_6"},
        "stages": {},
        "audio_variants": [],
        "generated_at": "2026-04-25T10:00:00Z", "dvc_lock_sha": "x",
    }))
    (rd.parent / "phase3_episode.json").write_text(json.dumps({"segments": []}))

    main(["--db", str(db), "scan", "--runs-dir", str(runs)])
    out = capsys.readouterr().out
    assert "scanned: 1" in out

    main(["--db", str(db), "list-episodes"])
    out = capsys.readouterr().out
    assert "bh_trn_literary" in out

    main(["--db", str(db), "show", "bh_trn_literary"])
    out = capsys.readouterr().out
    assert "bh" in out
    assert "literary" in out
