"""Phase E route tests for the five-tab episode pages.

Each (novel, panel) episode has five sibling URLs; the tab nav is
shared. These tests assert routes return 200, the right tab is
flagged active in the nav, and content shape matches the data
the route was supposed to surface.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webapp_v2.app import app


@pytest.fixture
def client(fixture_db: Path) -> TestClient:
    return TestClient(app)


def _set_artifact(
    db: Path, run_id: str, kind: str, payload: list | dict,
) -> None:
    text = json.dumps(payload, indent=2) + "\n"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO run_artifact"
            "(run_id, kind, payload, md5, bytes, imported_at)"
            " VALUES(?,?,?,?,?,0.0)"
            " ON CONFLICT(run_id, kind) DO UPDATE SET payload=excluded.payload",
            (run_id, kind, text, "x", len(text.encode("utf-8"))),
        )


# ── Tab routes return 200 + correct active tab ─────────────────────

@pytest.mark.parametrize("path,active_label,marker", [
    ("",              "Script",            'class="transcript"'),
    ("/interviews",   "Expert Interviews", "Expert Interviews"),
    ("/profiles",     "Expert Profiles",   "Expert Profiles"),
    ("/arcs",         "Character Arcs",    "Character Arcs"),
    ("/reading-list", "Reading List",      "Reading List"),
])
def test_tab_routes_return_200(
    client: TestClient, path: str, active_label: str, marker: str,
) -> None:
    r = client.get(f"/listen/wuthering_heights/literary{path}")
    assert r.status_code == 200, r.text[:200]
    assert "tab-active" in r.text
    # Active tab is the one with aria-current="page".
    body = r.text
    active_link_segment = body[
        body.find('aria-current="page"') - 200
        : body.find('aria-current="page"') + 100
    ]
    assert active_label in active_link_segment


def test_404_for_unknown_novel_on_any_tab(client: TestClient) -> None:
    for path in ("", "/interviews", "/profiles", "/arcs", "/reading-list"):
        r = client.get(f"/listen/nonsense_novel/literary{path}")
        assert r.status_code == 404


# ── Tab content shape ─────────────────────────────────────────────

def test_profiles_shows_three_panelist_cards(client: TestClient) -> None:
    r = client.get("/listen/wuthering_heights/literary/profiles")
    assert r.status_code == 200
    assert r.text.count('class="profile-card"') == 3
    # Names from panel_artifact
    assert "Eleanor Hartley" in r.text
    assert "James Blackstone" in r.text
    assert "Caroline Woodcourt" in r.text


def test_arcs_shows_curated_arc_list(client: TestClient) -> None:
    """BH arcs are always present in content.db (Python source —
    _BLEAK_HOUSE_ARCS in transport_podcast). The fixture only
    materializes a synth_novel dir, so we test against bleak_house
    which has guaranteed arcs."""
    r = client.get("/listen/bleak_house/literary/arcs")
    assert r.status_code == 200
    assert r.text.count('class="arc-card"') == 3
    assert "Richard Carstone" in r.text  # canonical BH character


def test_reading_list_shows_recommended_items(fixture_db: Path) -> None:
    """Post-7cgk, items render visibly only if resolution_status is
    'resolved' (or the legacy heuristic accepts a usable URL)."""
    _set_artifact(fixture_db, "bh_trn_literary_hostprep",
                  "phase2_5_reading_list", {
                      "recommended": [
                          {"title": "First Pick", "authors": ["A"],
                           "year": 2020, "description": "desc",
                           "url": "https://example.com/first",
                           "resolution_status": "resolved"},
                          {"title": "Second Pick", "authors": ["B"],
                           "year": 2021, "description": "desc",
                           "url": "https://example.com/second",
                           "resolution_status": "resolved"},
                      ],
                  })
    client = TestClient(app)
    r = client.get("/listen/bleak_house/literary/reading-list")
    assert r.status_code == 200
    assert r.text.count('class="reading-item"') == 2
    assert "First Pick" in r.text
    assert "Second Pick" in r.text


def test_reading_list_unresolved_items_become_html_comments(
    fixture_db: Path,
) -> None:
    """Items with resolution_status='unresolved' must not render
    visibly; they appear as HTML comments preserving metadata."""
    _set_artifact(fixture_db, "bh_trn_literary_hostprep",
                  "phase2_5_reading_list", {
                      "recommended": [
                          {"title": "Visible Resolved", "authors": ["A"],
                           "year": 2020, "url": "https://example.com/v",
                           "resolution_status": "resolved"},
                          {"title": "Invisible Unresolved", "authors": ["B"],
                           "year": 2021,
                           "raw_url": "wiki-fr:https://en.wikipedia.org/wiki/X",
                           "url": "",
                           "resolution_status": "unresolved",
                           "attempted": ["openalex", "wikipedia"],
                           "resolution_reason": "no_match"},
                      ],
                  })
    client = TestClient(app)
    r = client.get("/listen/bleak_house/literary/reading-list")
    assert r.status_code == 200
    body = r.text
    # Visible item renders as a list entry
    assert body.count('class="reading-item"') == 1
    assert "Visible Resolved" in body
    # Unresolved item is in source as an HTML comment, not in
    # visible HTML
    import re
    stripped = re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL)
    assert "Invisible Unresolved" not in stripped
    assert "wiki-fr" not in stripped
    # Comment carries full metadata
    assert "<!-- unresolved citation" in body
    assert "Invisible Unresolved" in body  # in the comment
    assert "openalex, wikipedia" in body
    assert "no_match" in body
    assert "wiki-fr:https://en.wikipedia.org/wiki/X" in body


def test_arcs_empty_state(fixture_db: Path) -> None:
    """Replace WH arcs with [] in the fixture; tab shows empty state."""
    with sqlite3.connect(fixture_db) as conn:
        conn.execute(
            "UPDATE novel_artifact SET payload='[]\n' "
            "WHERE novel='wuthering_heights' AND kind='arcs'"
        )
    client = TestClient(app)
    r = client.get("/listen/wuthering_heights/literary/arcs")
    assert r.status_code == 200
    assert "tab-empty" in r.text
    assert 'class="arc-card"' not in r.text


# ── Expert Interviews: schema variants ────────────────────────────

def test_interviews_uses_new_schema_entries(fixture_db: Path) -> None:
    """When phase2_5_reading_list has 'entries', references catalogue
    renders from those entries directly."""
    _set_artifact(fixture_db, "wh_trn_literary_short", "phase2_5_interviews", [
        [{"expert_name": "Eleanor Hartley", "key_points": ["a"],
          "potential_quotes": [], "disagreement_angles": [],
          "strongest_take": "T",
          "proposed_references": ["ref-1"]}],
    ])
    _set_artifact(fixture_db, "wh_trn_literary_short", "phase2_5_reading_list", {
        "schema_version": 2,
        "entries": [
            {"tag": "ref-1", "title": "An Important Work",
             "authors": ["Brontë"], "year": 1847, "description": "d",
             "url": "https://example.com/ref1",
             "resolution_status": "resolved"},
        ],
        "recommended": [],
    })
    client = TestClient(app)
    r = client.get("/listen/wuthering_heights/literary/interviews")
    assert r.status_code == 200
    body = r.text
    assert "An Important Work" in body
    assert "Full reference catalogue" in body
    assert body.count('class="reference-item"') == 1
    # Tag-driven reference inside the expert column
    assert "Brontë" in body


def test_interviews_normalizes_legacy_verified(fixture_db: Path) -> None:
    """Legacy schema: 'verified' rows have raw_text + openalex_*. The
    route should normalize them into the entries shape and render."""
    _set_artifact(fixture_db, "wh_trn_literary_short", "phase2_5_interviews", [
        [{"expert_name": "Eleanor Hartley", "key_points": [],
          "potential_quotes": [], "disagreement_angles": [],
          "strongest_take": None,
          "proposed_references": ["Aristotle, Nicomachean Ethics"]}],
    ])
    _set_artifact(fixture_db, "wh_trn_literary_short", "phase2_5_reading_list", {
        "verified": [
            {"raw_text": "Aristotle, Nicomachean Ethics",
             "openalex_title": "", "openalex_authors": [],
             "openalex_year": None, "openalex_doi": "",
             # The legacy normaliser flattens this to entries; for the
             # visible-rendering test we mark it resolved with a real
             # URL so it appears in the catalogue. The fallback for
             # unresolved (HTML comment) is covered by other tests.
             "url": "https://example.com/aristotle",
             "resolution_status": "resolved"},
        ],
        "recommended": [],
    })
    client = TestClient(app)
    r = client.get("/listen/wuthering_heights/literary/interviews")
    assert r.status_code == 200
    body = r.text
    assert "Aristotle" in body
    # Legacy proposed_references render via the ref-raw fallback
    assert "ref-raw" in body
    # Normalized into the catalogue too
    assert "Full reference catalogue" in body


def test_interviews_dedupes_legacy_verified(fixture_db: Path) -> None:
    """Legacy verified is one row per (expert × segment); same work
    cited by multiple experts must show once in the catalogue.
    Seed interviews too so the catalogue actually renders (it lives
    inside the {% if has_interviews or has_briefs %} block)."""
    _set_artifact(fixture_db, "wh_trn_literary_short", "phase2_5_interviews", [
        [{"expert_name": "Eleanor Hartley", "key_points": [],
          "potential_quotes": [], "disagreement_angles": [],
          "strongest_take": None, "proposed_references": []}],
    ])
    _set_artifact(fixture_db, "wh_trn_literary_short", "phase2_5_reading_list", {
        "verified": [
            {"raw_text": "Same Work", "openalex_title": "Same Work",
             "openalex_authors": ["A"], "openalex_year": 2020,
             "openalex_doi": "", "url": "https://example.com/same",
             "resolution_status": "resolved"},
            {"raw_text": "Same Work", "openalex_title": "Same Work",
             "openalex_authors": ["A"], "openalex_year": 2020,
             "openalex_doi": "", "url": "https://example.com/same",
             "resolution_status": "resolved"},
            {"raw_text": "Other Work", "openalex_title": "Other Work",
             "openalex_authors": [], "openalex_year": 2019,
             "openalex_doi": "", "url": "https://example.com/other",
             "resolution_status": "resolved"},
        ],
        "recommended": [],
    })
    client = TestClient(app)
    r = client.get("/listen/wuthering_heights/literary/interviews")
    assert r.text.count('class="reference-item"') == 2


def test_interviews_falls_back_to_briefs_when_no_interviews(
    fixture_db: Path,
) -> None:
    """phase2_5_interviews missing but briefs present: show questions."""
    _set_artifact(fixture_db, "wh_trn_literary_short", "phase2_5_host_briefs", [
        {"segment_name": "Opening",
         "questions": [
             {"target_expert": "Eleanor Hartley",
              "question": "What stands out?",
              "intent": "warm-up"},
         ]},
    ])
    # Make sure interviews is missing.
    with sqlite3.connect(fixture_db) as conn:
        conn.execute(
            "DELETE FROM run_artifact "
            "WHERE run_id='wh_trn_literary_short' "
            "AND kind='phase2_5_interviews'"
        )
    client = TestClient(app)
    r = client.get("/listen/wuthering_heights/literary/interviews")
    assert r.status_code == 200
    assert "interview-fallback" in r.text
    assert "What stands out?" in r.text
    assert "Eleanor Hartley" in r.text


def test_interviews_empty_when_neither_present(fixture_db: Path) -> None:
    with sqlite3.connect(fixture_db) as conn:
        conn.execute(
            "DELETE FROM run_artifact "
            "WHERE run_id='wh_trn_literary_short' "
            "AND kind IN ('phase2_5_interviews', 'phase2_5_host_briefs')"
        )
    client = TestClient(app)
    r = client.get("/listen/wuthering_heights/literary/interviews")
    assert r.status_code == 200
    assert "tab-empty" in r.text


# ── Tab nav consistency ───────────────────────────────────────────

def test_tab_nav_links_target_same_episode(client: TestClient) -> None:
    """Every tab page links to all five sibling URLs in the nav."""
    paths = ["", "/interviews", "/profiles", "/arcs", "/reading-list"]
    base = "/listen/wuthering_heights/literary"
    for path in paths:
        r = client.get(base + path)
        for sibling in paths:
            target = base + sibling
            assert f'href="{target}"' in r.text, (
                f"on {path}: missing nav link to {target}"
            )
