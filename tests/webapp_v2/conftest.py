"""Shared fixtures for webapp_v2 tests.

Each test gets a freshly-built content.db populated from a synthetic
fixture tree. webapp_v2.content.configure() points the read helpers at
the fixture DB; the per-test cleanup resets state.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterator

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_content_db as bcd  # noqa: E402

from webapp_v2 import content as v2_content  # noqa: E402


def _write_run(
    runs: Path,
    run_id: str,
    *,
    novel: str,
    panel: str,
    pipeline: str = "transport",
    length: str = "long",
    hostprep: bool = False,
    ref_tools: bool = True,
    generator: str = "anthropic_sonnet_4_6",
    has_audio: bool = False,
) -> None:
    """Materialise the minimum file set v2 selection logic needs."""
    rd = runs / run_id
    rd.mkdir()
    config = {
        "axes": {
            "novel": novel,
            "pipeline": pipeline,
            "panel": panel,
            "hostprep": hostprep,
            "generator": generator,
            "length": length,
        },
    }
    (rd / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    (rd / "phase0_segments.json").write_text(
        json.dumps([{"name": f"{novel}/{panel} opening"}], indent=2) + "\n"
    )
    (rd / "phase1_assignments.json").write_text("[]\n")
    (rd / "phase2_plan.json").write_text("{}\n")
    # Realistic-shaped phase3_episode: one segment, two turns, three
    # utterances total. Enough to exercise the transcript template's
    # nested loops and data-segment-idx / data-turn-idx attributes.
    (rd / "phase3_episode.json").write_text(json.dumps({
        "title": f"{run_id} title",
        "segments": [{
            "title": f"{novel}/{panel} opening",
            "segment_type": "opening",
            "turns": [
                {
                    "speaker": "Host",
                    "role": "host",
                    "utterances": [{
                        "text": f"Welcome to {novel}.",
                        "is_quote": False,
                        "passage_ref": "",
                    }],
                },
                {
                    "speaker": "Eleanor Hartley",
                    "role": "novelist_and_craft_teacher",
                    "utterances": [
                        {"text": "A craft observation.",
                         "is_quote": False, "passage_ref": "c1:p3"},
                        {"text": "And a quoted line.",
                         "is_quote": True, "passage_ref": "c1:p3"},
                    ],
                },
            ],
        }],
    }, indent=2) + "\n")
    if ref_tools:
        (rd / "phase2_5_reading_list.json").write_text("{}\n")
    if has_audio:
        (rd / "audio").mkdir()
        (rd / "audio" / "shards.json").write_text(
            json.dumps({
                "schema_version": 1, "profile": "trevelyan_v2",
                "episode_title": run_id, "experts": [],
                "shards": [{"file": "0000.mp3", "md5": "abc", "kind": "turn",
                            "segment_index": 0, "turn_index": 0,
                            "speaker": "Host", "role": "host", "utterances": []}],
            }, indent=2) + "\n"
        )


@pytest.fixture
def fixture_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Build a tiny content.db with a coverage cross-section.

    Two novels × two panels with audio; one (novel, panel) bucket gets
    multiple runs to exercise the selection ranking. Plus one
    audio-less run to verify it's filtered out.
    """
    runs = tmp_path / "runs"
    novels = tmp_path / "novels"
    runs.mkdir()
    novels.mkdir()

    # bleak_house literary: three runs, only one with audio (transport+hostprep)
    _write_run(runs, "bh_emb_literary", novel="bleak_house", panel="literary",
               pipeline="embedding", has_audio=False)
    _write_run(runs, "bh_trn_literary", novel="bleak_house", panel="literary",
               pipeline="transport", has_audio=False)
    _write_run(runs, "bh_trn_literary_hostprep", novel="bleak_house",
               panel="literary", pipeline="transport", hostprep=True,
               has_audio=True)

    # bleak_house alternatives: two runs with audio — short should win.
    _write_run(runs, "bh_trn_alternatives", novel="bleak_house",
               panel="alternatives", pipeline="transport", has_audio=True)
    _write_run(runs, "bh_trn_alternatives_short", novel="bleak_house",
               panel="alternatives", pipeline="transport", length="short",
               has_audio=True)

    # wuthering_heights literary: one run with audio.
    _write_run(runs, "wh_trn_literary_short", novel="wuthering_heights",
               panel="literary", pipeline="transport", hostprep=True,
               length="short", has_audio=True)

    # No audio at all — should not appear in canonical episodes.
    _write_run(runs, "ot_trn_literary", novel="oliver_twist", panel="literary",
               has_audio=False)

    # Per-novel artifacts (sparse — character_arcs only for some).
    (novels / "bleak_house").mkdir()
    (novels / "bleak_house" / "passages_enriched.json").write_text("[]\n")
    (novels / "bleak_house" / "clusters_characters.json").write_text("{}\n")
    (novels / "bleak_house" / "clusters_literary.json").write_text("{}\n")

    monkeypatch.setattr(bcd, "RUNS_DIR", runs)
    monkeypatch.setattr(bcd, "NOVELS_DIR", novels)
    # The full Python-arcs and Python-panels imports work fine in tests
    # against the real enrichment package, so leave them connected.

    db = tmp_path / "content.db"
    bcd.build(db)
    v2_content.configure(db)

    yield db

    # Reset module-level state so a later test gets a clean slate.
    v2_content.configure(v2_content.DEFAULT_DB_PATH)
