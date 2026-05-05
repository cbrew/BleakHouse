"""best_episodes_for_consumer() ranks per (novel, panel) and drops pairs
without rendered audio."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


def _build_fixture_db(db_path: Path, rows: list[dict]) -> None:
    """Create a minimal experiments DB with episode/script_version/audio_artifact
    populated from the given rows. Each row is a single (episode, script,
    [audio]) bundle; pass audio_duration=None to omit the audio_artifact."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE episode (
            id INTEGER PRIMARY KEY, novel TEXT, panel TEXT, pipeline TEXT,
            hostprep INTEGER, generator TEXT, ref_tools INTEGER,
            label TEXT, created_at REAL
        );
        CREATE TABLE script_version (
            id INTEGER PRIMARY KEY, episode_id INTEGER,
            hostprep_version_id INTEGER, path TEXT, dvc_hash TEXT,
            n_segments INTEGER, n_turns INTEGER, n_utterances INTEGER,
            created_at REAL
        );
        CREATE TABLE audio_artifact (
            id INTEGER PRIMARY KEY, script_version_id INTEGER,
            tts_config_id INTEGER, name TEXT, path TEXT, dvc_hash TEXT,
            duration_s REAL, audio_manifest_path TEXT, created_at REAL
        );
    """)
    for i, r in enumerate(rows, start=1):
        conn.execute(
            "INSERT INTO episode (id, novel, panel, pipeline, hostprep, ref_tools, label, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (i, r["novel"], r["panel"], r["pipeline"], r["hostprep"],
             r.get("ref_tools", 0), r["label"], r.get("episode_created", 1000.0 + i)),
        )
        conn.execute(
            "INSERT INTO script_version (id, episode_id, n_segments, n_turns, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (i, i, r.get("n_segments", 7), r.get("n_turns", 100),
             r.get("script_created", 2000.0 + i)),
        )
        if r.get("audio_duration") is not None:
            conn.execute(
                "INSERT INTO audio_artifact (script_version_id, duration_s, created_at)"
                " VALUES (?, ?, ?)",
                (i, r["audio_duration"], 3000.0 + i),
            )
    conn.commit()
    conn.close()


@pytest.fixture
def fixture_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build a fixture DB and point webapp.db at it."""
    db_path = tmp_path / "experiments.db"
    monkeypatch.setenv("BLEAKHOUSE_DB_READONLY", "1")
    import webapp.db as dbmod
    monkeypatch.setattr(dbmod, "_DB_PATH", db_path)
    return db_path


def test_picks_trn_hostprep_refs_within_a_bucket(fixture_db: Path, tmp_path: Path) -> None:
    """Within (bh, literary) the row with trn+hostprep+ref_tools must win."""
    _build_fixture_db(fixture_db, [
        {"novel": "bh", "panel": "literary", "pipeline": "emb",
         "hostprep": 1, "ref_tools": 1, "label": "bh_emb_lit_hp_rt", "audio_duration": 100},
        {"novel": "bh", "panel": "literary", "pipeline": "trn",
         "hostprep": 0, "ref_tools": 0, "label": "bh_trn_lit", "audio_duration": 100},
        {"novel": "bh", "panel": "literary", "pipeline": "trn",
         "hostprep": 1, "ref_tools": 1, "label": "bh_trn_lit_hp_rt", "audio_duration": 100},
        {"novel": "bh", "panel": "literary", "pipeline": "trn",
         "hostprep": 1, "ref_tools": 0, "label": "bh_trn_lit_hp", "audio_duration": 100},
    ])
    from webapp.consumer import best_episodes_for_consumer
    rows = best_episodes_for_consumer(data_dir=tmp_path)
    assert len(rows) == 1
    assert rows[0]["run_id"] == "bh_trn_lit_hp_rt"
    assert rows[0]["novel_title"] == "Bleak House"
    assert rows[0]["author"] == "Dickens"


def test_one_card_per_novel_panel_pair(fixture_db: Path, tmp_path: Path) -> None:
    """Two novels × two panels with audio = 4 cards. A panel without audio
    contributes nothing; a novel where every panel lacks audio drops out."""
    _build_fixture_db(fixture_db, [
        # Bleak House — three panels, two with audio
        {"novel": "bh", "panel": "literary", "pipeline": "trn",
         "hostprep": 1, "ref_tools": 1, "label": "bh_lit", "audio_duration": 100},
        {"novel": "bh", "panel": "alternatives", "pipeline": "trn",
         "hostprep": 1, "ref_tools": 0, "label": "bh_alt", "audio_duration": 100},
        {"novel": "bh", "panel": "interdisciplinary", "pipeline": "trn",
         "hostprep": 1, "ref_tools": 0, "label": "bh_int_no_audio", "audio_duration": None},
        # Hester — two panels with audio
        {"novel": "hest", "panel": "literary", "pipeline": "emb",
         "hostprep": 0, "ref_tools": 0, "label": "hest_lit", "audio_duration": 50},
        {"novel": "hest", "panel": "alternatives", "pipeline": "trn",
         "hostprep": 0, "ref_tools": 0, "label": "hest_alt", "audio_duration": 50},
        # Cranford — one episode, no audio: drops out entirely
        {"novel": "cran", "panel": "literary", "pipeline": "trn",
         "hostprep": 1, "ref_tools": 1, "label": "cran_lit_no_audio", "audio_duration": None},
    ])
    from webapp.consumer import best_episodes_for_consumer
    rows = best_episodes_for_consumer(data_dir=tmp_path)
    pairs = {(r["novel"], r["panel"]) for r in rows}
    assert pairs == {
        ("bh", "literary"), ("bh", "alternatives"),
        ("hest", "literary"), ("hest", "alternatives"),
    }


def test_transport_alias_ranks_with_trn(fixture_db: Path, tmp_path: Path) -> None:
    """Some legacy episode rows store the pipeline as 'transport' instead
    of 'trn'; both should rank above emb."""
    _build_fixture_db(fixture_db, [
        {"novel": "bh", "panel": "literary", "pipeline": "emb",
         "hostprep": 1, "ref_tools": 1, "label": "bh_emb", "audio_duration": 100},
        {"novel": "bh", "panel": "literary", "pipeline": "transport",
         "hostprep": 0, "ref_tools": 0, "label": "bh_trans", "audio_duration": 100},
    ])
    from webapp.consumer import best_episodes_for_consumer
    rows = best_episodes_for_consumer(data_dir=tmp_path)
    assert len(rows) == 1
    assert rows[0]["run_id"] == "bh_trans"


def test_recency_breaks_ties(fixture_db: Path, tmp_path: Path) -> None:
    """When pipeline/hostprep/ref_tools all tie, pick the newer script."""
    _build_fixture_db(fixture_db, [
        {"novel": "bh", "panel": "literary", "pipeline": "trn",
         "hostprep": 1, "ref_tools": 1, "label": "bh_old",
         "audio_duration": 100, "script_created": 1000.0},
        {"novel": "bh", "panel": "literary", "pipeline": "trn",
         "hostprep": 1, "ref_tools": 1, "label": "bh_new",
         "audio_duration": 100, "script_created": 9999.0},
    ])
    from webapp.consumer import best_episodes_for_consumer
    rows = best_episodes_for_consumer(data_dir=tmp_path)
    assert rows[0]["run_id"] == "bh_new"


def test_results_sorted_by_novel_then_panel(fixture_db: Path, tmp_path: Path) -> None:
    """Output ordering: novel title alphabetical, then literary > alternatives
    > interdisciplinary within each novel."""
    _build_fixture_db(fixture_db, [
        {"novel": "hest", "panel": "interdisciplinary", "pipeline": "trn",
         "hostprep": 1, "ref_tools": 0, "label": "hest_int", "audio_duration": 50},
        {"novel": "bh", "panel": "interdisciplinary", "pipeline": "trn",
         "hostprep": 1, "ref_tools": 0, "label": "bh_int", "audio_duration": 100},
        {"novel": "bh", "panel": "literary", "pipeline": "trn",
         "hostprep": 1, "ref_tools": 1, "label": "bh_lit", "audio_duration": 100},
        {"novel": "hest", "panel": "literary", "pipeline": "trn",
         "hostprep": 0, "ref_tools": 0, "label": "hest_lit", "audio_duration": 50},
    ])
    from webapp.consumer import best_episodes_for_consumer
    rows = best_episodes_for_consumer(data_dir=tmp_path)
    assert [(r["novel_title"], r["panel"]) for r in rows] == [
        ("Bleak House", "literary"),
        ("Bleak House", "interdisciplinary"),
        ("Hester", "literary"),
        ("Hester", "interdisciplinary"),
    ]
