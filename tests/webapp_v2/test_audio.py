"""Tests for the v2 audio endpoint.

Phase C exposes one audio route: /audio/<run_id>/shards.json. Each
shard carries an R2 url built from its md5 via cas.store.url. No
proxy endpoint — the client fetches mp3 bytes directly from R2.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webapp_v2.app import app


@pytest.fixture
def client_with_shards(fixture_db: Path) -> TestClient:
    """The default fixture writes a shards.json for every audio-bearing
    run, but the import only captures `audio/shards.json` if the file
    exists at build time. The fixture's _write_run helper covers that;
    nothing extra needed here."""
    return TestClient(app)


def test_shards_manifest_returns_url_per_shard(
    client_with_shards: TestClient,
) -> None:
    r = client_with_shards.get("/audio/wh_trn_literary_short/shards.json")
    assert r.status_code == 200
    data = r.json()
    assert data["run_id"] == "wh_trn_literary_short"
    assert data["schema_version"] == 1
    assert isinstance(data["shards"], list)
    assert len(data["shards"]) >= 1
    s = data["shards"][0]
    assert s["md5"]
    assert s["url"].startswith("https://")
    # The R2 url path encodes md5 as <prefix>/<rest>; the md5 must
    # round-trip through cas.store.url.
    assert s["md5"][:2] in s["url"]


def test_shards_manifest_404s_for_run_without_shards(
    client_with_shards: TestClient,
) -> None:
    """bh_emb_literary in the fixture has has_audio=False (no
    shards.json on disk → no shards_index in content.db)."""
    r = client_with_shards.get("/audio/bh_emb_literary/shards.json")
    assert r.status_code == 404


def test_shards_manifest_404s_for_unknown_run(
    client_with_shards: TestClient,
) -> None:
    r = client_with_shards.get("/audio/nonesuch_run/shards.json")
    assert r.status_code == 404


def test_shards_manifest_skips_shards_without_md5(
    fixture_db: Path, tmp_path: Path,
) -> None:
    """Missing-md5 shard rows shouldn't crash; they're skipped."""
    # Inject a shard with no md5 directly into content.db.
    import sqlite3
    payload = {
        "schema_version": 1, "profile": "trevelyan_v2",
        "episode_title": "synthetic", "experts": [],
        "shards": [
            {"file": "0000.mp3", "md5": "abc", "kind": "turn",
             "segment_index": 0, "turn_index": 0,
             "speaker": "Host", "role": "host", "utterances": []},
            {"file": "0001.mp3", "kind": "break", "segment_index": 0},  # no md5
        ],
    }
    with sqlite3.connect(fixture_db) as conn:
        conn.execute(
            "UPDATE run_artifact SET payload=? "
            "WHERE run_id='wh_trn_literary_short' AND kind='shards_index'",
            (json.dumps(payload),),
        )
        conn.commit()

    client = TestClient(app)
    r = client.get("/audio/wh_trn_literary_short/shards.json")
    assert r.status_code == 200
    shards = r.json()["shards"]
    assert len(shards) == 1  # break-without-md5 dropped
    assert shards[0]["md5"] == "abc"


def test_listen_page_contains_player_ui(client_with_shards: TestClient) -> None:
    r = client_with_shards.get("/listen/wuthering_heights/literary")
    assert r.status_code == 200
    body = r.text
    assert 'class="player-bar"' in body
    assert 'id="player-audio"' in body
    assert 'id="player-play"' in body
    assert 'id="player-speed"' in body
    assert 'id="player-progress"' in body
    assert 'src="/static/player.js"' in body


def test_static_player_js_served(client_with_shards: TestClient) -> None:
    r = client_with_shards.get("/static/player.js")
    assert r.status_code == 200
    body = r.text
    # Sanity: speed array, the click-to-seek wire-up, and the audio
    # element id are all present.
    assert "SPEEDS" in body
    assert "wireTurnClicks" in body
    assert "player-audio" in body
