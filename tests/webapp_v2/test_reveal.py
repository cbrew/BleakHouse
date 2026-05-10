"""TestClient unit tests for the v2 passage-reveal route.

The reveal endpoint returns an HTML fragment (no <html>/<body>)
suitable for an htmx swap. Source data: passages_contextual when
available, falling back to passages_enriched.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webapp_v2.app import app


def _seed_passages(db: Path, novel: str, kind: str, passages: list[dict]) -> None:
    """Drop a novel_artifact row directly into the fixture DB."""
    text = json.dumps(passages, indent=2) + "\n"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO novel_artifact"
            "(novel, kind, payload, md5, bytes, imported_at)"
            " VALUES(?,?,?,?,?,0.0)"
            " ON CONFLICT(novel, kind) DO UPDATE SET payload=excluded.payload",
            (novel, kind, text, "x", len(text.encode("utf-8"))),
        )


@pytest.fixture
def client(fixture_db: Path) -> TestClient:
    return TestClient(app)


def test_reveal_returns_html_fragment(fixture_db: Path) -> None:
    _seed_passages(fixture_db, "bleak_house", "passages_enriched", [
        {
            "passage_id": "c1:p0",
            "chapter_title": "London",
            "text": "Fog everywhere.",
            "context": None,
            "enrichment": {
                "characters_present": ["Esther"],
                "themes": ["fog", "law"],
                "emotional_register": "ominous",
            },
        },
    ])
    client = TestClient(app)
    r = client.get("/reveal/bh_trn_literary_hostprep/c1:p0")
    assert r.status_code == 200
    body = r.text
    # Fragment, not a full page.
    assert "<!DOCTYPE" not in body
    assert "<html" not in body
    # Has the right shape.
    assert 'class="reveal"' in body
    assert "Fog everywhere." in body
    assert "Esther" in body
    assert "fog" in body
    assert "ominous" in body


def test_reveal_prefers_contextual_when_present(fixture_db: Path) -> None:
    """When both passages_contextual and passages_enriched exist, the
    contextual variant wins (it carries the LLM-generated context
    string)."""
    _seed_passages(fixture_db, "bleak_house", "passages_enriched", [
        {"passage_id": "c1:p0", "text": "T", "context": None,
         "enrichment": {}},
    ])
    _seed_passages(fixture_db, "bleak_house", "passages_contextual", [
        {"passage_id": "c1:p0", "text": "T", "context": "Has context.",
         "enrichment": {}},
    ])
    client = TestClient(app)
    r = client.get("/reveal/bh_trn_literary_hostprep/c1:p0")
    assert r.status_code == 200
    assert "Has context." in r.text
    assert 'class="reveal-context"' in r.text


def test_reveal_falls_back_to_enriched(fixture_db: Path) -> None:
    """BH and Room With a View only have passages_enriched (context=null).
    The route must still serve a fragment; it just lacks the context block."""
    _seed_passages(fixture_db, "bleak_house", "passages_enriched", [
        {"passage_id": "c1:p0", "text": "Just text.", "context": None,
         "enrichment": {}},
    ])
    client = TestClient(app)
    r = client.get("/reveal/bh_trn_literary_hostprep/c1:p0")
    assert r.status_code == 200
    assert "Just text." in r.text
    assert 'class="reveal-context"' not in r.text


def test_reveal_404_for_unknown_run(client: TestClient) -> None:
    r = client.get("/reveal/nonesuch_run/c1:p0")
    assert r.status_code == 404


def test_reveal_404_for_missing_passage(fixture_db: Path) -> None:
    _seed_passages(fixture_db, "bleak_house", "passages_enriched", [
        {"passage_id": "c1:p0", "text": "T", "context": None,
         "enrichment": {}},
    ])
    client = TestClient(app)
    r = client.get("/reveal/bh_trn_literary_hostprep/c99:p99")
    assert r.status_code == 404


def test_listen_emits_reveal_buttons(client: TestClient) -> None:
    """Each utterance with a passage_ref renders a passage-ref button
    plus an adjacent .reveal-slot for htmx to swap into."""
    r = client.get("/listen/bleak_house/literary")
    assert r.status_code == 200
    body = r.text
    assert 'hx-get="/reveal/' in body
    assert 'class="reveal-slot"' in body
    assert 'hx-target="next .reveal-slot"' in body
    # htmx is loaded.
    assert "htmx.org" in body
