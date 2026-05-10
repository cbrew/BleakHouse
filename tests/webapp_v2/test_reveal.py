"""TestClient unit tests for the v2 turn-level passage-reveal route.

The reveal endpoint takes a (run_id, segment_idx, turn_idx) and
returns an HTML fragment with all of the turn's referenced passages
stacked. One handle per turn (not per utterance) — matches v1's UX
of keeping the conversation flow intact.

Source data: passages_contextual when available, falling back to
passages_enriched.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webapp_v2.app import app


def _seed_passages(db: Path, novel: str, kind: str, passages: list[dict]) -> None:
    text = json.dumps(passages, indent=2) + "\n"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO novel_artifact"
            "(novel, kind, payload, md5, bytes, imported_at)"
            " VALUES(?,?,?,?,?,0.0)"
            " ON CONFLICT(novel, kind) DO UPDATE SET payload=excluded.payload",
            (novel, kind, text, "x", len(text.encode("utf-8"))),
        )


def _seed_episode_with_refs(
    db: Path, run_id: str, refs: list[list[str]],
) -> None:
    """Replace a run's phase3_episode with one segment whose turns have
    the supplied passage_ref lists. refs[i] is the list for turn i."""
    episode = {
        "title": "synthetic",
        "segments": [{
            "title": "synthetic segment",
            "segment_type": "deep_dive",
            "turns": [
                {
                    "speaker": f"Speaker {i}",
                    "role": "expert",
                    "utterances": [
                        {"text": f"u{j}", "is_quote": False,
                         "passage_ref": ref}
                        for j, ref in enumerate(turn_refs)
                    ],
                }
                for i, turn_refs in enumerate(refs)
            ],
        }],
    }
    text = json.dumps(episode, indent=2) + "\n"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE run_artifact SET payload=? "
            "WHERE run_id=? AND kind='phase3_episode'",
            (text, run_id),
        )


@pytest.fixture
def client(fixture_db: Path) -> TestClient:
    return TestClient(app)


def test_reveal_returns_fragment_for_turn(fixture_db: Path) -> None:
    _seed_passages(fixture_db, "bleak_house", "passages_enriched", [
        {"passage_id": "c1:p0", "chapter_title": "London",
         "text": "Fog everywhere.", "context": None,
         "enrichment": {"characters_present": ["Esther"],
                        "themes": ["fog"], "emotional_register": "ominous"}},
    ])
    _seed_episode_with_refs(fixture_db, "bh_trn_literary_hostprep",
                            refs=[["c1:p0"]])
    client = TestClient(app)
    r = client.get("/reveal/bh_trn_literary_hostprep/0/0")
    assert r.status_code == 200
    body = r.text
    assert "<!DOCTYPE" not in body
    assert 'class="reveal"' in body
    assert "Fog everywhere." in body
    assert "Esther" in body
    assert "fog" in body
    assert "ominous" in body
    # Per-card structure
    assert 'class="reveal-passage-card"' in body
    assert 'class="reveal-card-ref"' in body
    assert "c1:p0" in body


def test_reveal_stacks_multiple_passages_in_one_panel(fixture_db: Path) -> None:
    """A turn that references several passages should produce one
    .reveal containing one card per passage (deduped, occurrence
    order)."""
    _seed_passages(fixture_db, "bleak_house", "passages_enriched", [
        {"passage_id": "c1:p0", "text": "First.", "context": None,
         "enrichment": {}},
        {"passage_id": "c2:p3", "text": "Second.", "context": None,
         "enrichment": {}},
    ])
    _seed_episode_with_refs(
        fixture_db, "bh_trn_literary_hostprep",
        # Same ref repeated must dedupe; order preserved.
        refs=[["c1:p0", "c2:p3", "c1:p0"]],
    )
    client = TestClient(app)
    r = client.get("/reveal/bh_trn_literary_hostprep/0/0")
    assert r.status_code == 200
    body = r.text
    # Two cards (deduped from three utterance refs)
    assert body.count('class="reveal-passage-card') == 2
    # First card is c1:p0; second has the stacked modifier class
    assert body.find("First.") < body.find("Second.")
    assert "reveal-passage-card-stacked" in body


def test_reveal_prefers_contextual_over_enriched(fixture_db: Path) -> None:
    _seed_passages(fixture_db, "bleak_house", "passages_enriched", [
        {"passage_id": "c1:p0", "text": "T", "context": None,
         "enrichment": {}},
    ])
    _seed_passages(fixture_db, "bleak_house", "passages_contextual", [
        {"passage_id": "c1:p0", "text": "T",
         "context": "LLM context here.", "enrichment": {}},
    ])
    _seed_episode_with_refs(fixture_db, "bh_trn_literary_hostprep",
                            refs=[["c1:p0"]])
    client = TestClient(app)
    r = client.get("/reveal/bh_trn_literary_hostprep/0/0")
    assert r.status_code == 200
    assert "LLM context here." in r.text
    assert 'class="reveal-context"' in r.text


def test_reveal_404_for_unknown_run(client: TestClient) -> None:
    assert client.get("/reveal/nonesuch_run/0/0").status_code == 404


def test_reveal_404_for_out_of_range_segment(fixture_db: Path) -> None:
    _seed_episode_with_refs(fixture_db, "bh_trn_literary_hostprep",
                            refs=[["c1:p0"]])
    client = TestClient(app)
    assert client.get("/reveal/bh_trn_literary_hostprep/9/0").status_code == 404


def test_reveal_404_for_out_of_range_turn(fixture_db: Path) -> None:
    _seed_episode_with_refs(fixture_db, "bh_trn_literary_hostprep",
                            refs=[["c1:p0"]])
    client = TestClient(app)
    assert client.get("/reveal/bh_trn_literary_hostprep/0/9").status_code == 404


def test_reveal_404_for_turn_with_no_passage_refs(fixture_db: Path) -> None:
    _seed_episode_with_refs(fixture_db, "bh_trn_literary_hostprep",
                            refs=[[""]])  # utterance with empty ref
    client = TestClient(app)
    assert client.get("/reveal/bh_trn_literary_hostprep/0/0").status_code == 404


def test_listen_emits_one_handle_per_turn_not_per_utterance(
    client: TestClient,
) -> None:
    """v2's clumsy UX was a button per utterance. The fix is one
    handle per turn next to the speaker."""
    r = client.get("/listen/bleak_house/literary")
    assert r.status_code == 200
    body = r.text
    # No more per-utterance ref buttons.
    assert 'class="passage-ref"' not in body
    # Single .passage-handle per turn that has any refs.
    handle_count = body.count('class="passage-handle"')
    slot_count = body.count('class="reveal-slot"')
    assert handle_count == slot_count
    assert handle_count >= 1
    # Handles target the turn's slot via id (no selector gymnastics).
    assert "#reveal-slot-" in body
    # htmx is loaded.
    assert "htmx.org" in body
