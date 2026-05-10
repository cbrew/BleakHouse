"""Tests for webapp_v2.content read helpers."""
from __future__ import annotations

from pathlib import Path

from webapp_v2.content import (
    get_run_index,
    iter_run_index,
    read_novel_artifact,
    read_panel_artifact,
    read_run_artifact,
)


def test_read_run_artifact_round_trip(fixture_db: Path) -> None:
    seg = read_run_artifact("bh_trn_literary_hostprep", "phase0_segments")
    assert isinstance(seg, list)
    assert seg[0]["name"] == "bleak_house/literary opening"


def test_read_run_artifact_returns_none_for_missing(fixture_db: Path) -> None:
    assert read_run_artifact("nonesuch_run", "phase0_segments") is None
    assert read_run_artifact("bh_trn_literary_hostprep", "nonesuch_kind") is None


def test_read_panel_artifact_returns_real_panels(fixture_db: Path) -> None:
    """Panel artifacts come from Python source, present even with
    a tiny fixture run set."""
    lit = read_panel_artifact("literary")
    assert lit is not None
    assert lit["display"].startswith("Literary")
    names = [e["name"] for e in lit["experts"]]
    assert names == ["Eleanor Hartley", "James Blackstone", "Caroline Woodcourt"]
    assert all("description" in e and e["description"] for e in lit["experts"])


def test_read_novel_artifact_arcs_round_trip(fixture_db: Path) -> None:
    """BH arcs come from Python (transport_podcast._BLEAK_HOUSE_ARCS),
    captured at build time."""
    arcs = read_novel_artifact("bleak_house", "arcs")
    assert isinstance(arcs, list)
    assert any(a["character"] == "Richard Carstone" for a in arcs)


def test_get_run_index_typed(fixture_db: Path) -> None:
    row = get_run_index("wh_trn_literary_short")
    assert row is not None
    assert row.novel == "wuthering_heights"
    assert row.panel == "literary"
    assert row.length == "short"
    assert row.hostprep is True
    assert row.has_audio is True


def test_iter_run_index_filters(fixture_db: Path) -> None:
    audio_only = list(iter_run_index(has_audio=True))
    no_audio = list(iter_run_index(has_audio=False))
    assert len(audio_only) == 4   # 3 audio buckets + 1 extra in bh/alternatives
    assert all(r.has_audio for r in audio_only)
    assert all(not r.has_audio for r in no_audio)

    bh = list(iter_run_index(novel="bleak_house"))
    assert {r.run_id for r in bh} >= {
        "bh_emb_literary", "bh_trn_literary", "bh_trn_literary_hostprep",
        "bh_trn_alternatives", "bh_trn_alternatives_short",
    }
