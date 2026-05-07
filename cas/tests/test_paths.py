"""Tests for cas.paths — centralised path resolution helpers."""
from __future__ import annotations

from pathlib import Path

import pytest

from cas import paths


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Synthetic data/ tree under tmp_path; cas.paths resolves under it."""
    monkeypatch.setattr(paths, "_DATA_DIR", tmp_path / "data")
    (tmp_path / "data" / "novels" / "bleak_house").mkdir(parents=True)
    (tmp_path / "data" / "novels" / "bleak_house" / "passages_enriched.json").write_text("[]")
    (tmp_path / "data" / "novels" / "bleak_house" / "clusters_literary.json").write_text("{}")
    (tmp_path / "data" / "novels" / "bleak_house" / "clusters_characters.json").write_text("{}")
    (tmp_path / "data" / "runs" / "bh_trn_literary").mkdir(parents=True)
    return tmp_path


def test_passages_enriched_resolves_under_novel_dir(fake_repo: Path) -> None:
    p = paths.passages_enriched("bleak_house")
    assert p == fake_repo / "data" / "novels" / "bleak_house" / "passages_enriched.json"


def test_passages_enriched_raises_when_novel_dir_missing(fake_repo: Path) -> None:
    with pytest.raises(FileNotFoundError, match="novel 'nonexistent' not registered"):
        paths.passages_enriched("nonexistent")


def test_clusters_literary_resolves_under_novel_dir(fake_repo: Path) -> None:
    p = paths.clusters_literary("bleak_house")
    assert p == fake_repo / "data" / "novels" / "bleak_house" / "clusters_literary.json"


def test_clusters_characters_resolves_under_novel_dir(fake_repo: Path) -> None:
    p = paths.clusters_characters("bleak_house")
    assert p == fake_repo / "data" / "novels" / "bleak_house" / "clusters_characters.json"


def test_clusters_literary_raises_when_novel_dir_missing(fake_repo: Path) -> None:
    with pytest.raises(FileNotFoundError, match="novel 'nope' not registered"):
        paths.clusters_literary("nope")


def test_assignments_resolves_under_run_dir(fake_repo: Path) -> None:
    p = paths.assignments("bh_trn_literary")
    assert p == fake_repo / "data" / "runs" / "bh_trn_literary" / "phase1_assignments.json"


def test_reading_list_resolves_under_run_dir(fake_repo: Path) -> None:
    p = paths.reading_list("bh_trn_literary")
    assert p == fake_repo / "data" / "runs" / "bh_trn_literary" / "phase2_5_reading_list.json"


def test_episode_resolves_under_run_dir(fake_repo: Path) -> None:
    p = paths.episode("bh_trn_literary")
    assert p == fake_repo / "data" / "runs" / "bh_trn_literary" / "phase3_episode.json"


def test_shards_manifest_resolves_under_audio_subdir(fake_repo: Path) -> None:
    p = paths.shards_manifest("bh_trn_literary")
    assert p == fake_repo / "data" / "runs" / "bh_trn_literary" / "audio" / "shards.json"


def test_audio_assets_resolves_under_audio_subdir(fake_repo: Path) -> None:
    p = paths.audio_assets("bh_trn_literary")
    assert p == fake_repo / "data" / "runs" / "bh_trn_literary" / "audio" / "assets.json"


def test_run_helper_raises_when_run_dir_missing(fake_repo: Path) -> None:
    with pytest.raises(FileNotFoundError, match="run 'no_such_run' not found"):
        paths.assignments("no_such_run")
