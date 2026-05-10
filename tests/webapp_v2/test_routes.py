"""Phase B route tests for webapp_v2.app.

Exercises the landing and listen routes against the fixture content.db
built by tests/webapp_v2/conftest.py. The fixture has three audio
buckets (bh literary, bh alternatives, wh literary) and one without
audio (oliver_twist literary).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webapp_v2.app import app


@pytest.fixture
def client(fixture_db: Path) -> TestClient:
    """TestClient pinned to the fixture content.db (configured by
    conftest before app reads happen)."""
    return TestClient(app)


def test_landing_lists_audio_bearing_episodes(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    # bh literary, bh alternatives, wh literary all surface.
    assert "/listen/bleak_house/literary" in body
    assert "/listen/bleak_house/alternatives" in body
    assert "/listen/wuthering_heights/literary" in body
    # No audio for oliver_twist — must not be linked.
    assert "/listen/oliver_twist/" not in body


def test_landing_shows_novel_title_and_author(client: TestClient) -> None:
    r = client.get("/")
    body = r.text
    assert "Bleak House" in body
    assert "Wuthering Heights" in body
    # Authors come from enrichment.axes.NOVELS metadata.
    assert "Dickens" in body
    assert "Bront" in body  # Brontë; ASCII match avoids encoding fragility


def test_listen_returns_200_for_audio_bearing_episode(client: TestClient) -> None:
    r = client.get("/listen/wuthering_heights/literary")
    assert r.status_code == 200
    body = r.text
    assert "Wuthering Heights" in body
    # transcript wrapper is present
    assert 'class="transcript"' in body
    # Each turn carries the data attrs Phase C will read for click-to-seek.
    assert "data-segment-idx=" in body
    assert "data-turn-idx=" in body
    # back-link to landing
    assert 'href="/"' in body


def test_listen_404s_for_no_audio_episode(client: TestClient) -> None:
    r = client.get("/listen/oliver_twist/literary")
    assert r.status_code == 404


def test_listen_404s_for_unknown_novel(client: TestClient) -> None:
    r = client.get("/listen/nonesuch_novel/literary")
    assert r.status_code == 404


def test_listen_picks_short_over_long_invisibly(client: TestClient) -> None:
    """bh alternatives has both _trn_alternatives (long) and
    _trn_alternatives_short. The short run wins; the listen page reads
    *its* phase3_episode. data-run-id on the transcript wrapper proves
    which run was chosen — the URL itself stays length-free."""
    r = client.get("/listen/bleak_house/alternatives")
    assert r.status_code == 200
    # Short run was selected (invisible to the URL).
    assert 'data-run-id="bh_trn_alternatives_short"' in r.text
    assert "?length=" not in r.text


def test_static_styles_served(client: TestClient) -> None:
    r = client.get("/static/styles.css")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/css")
    assert "--bg" in r.text  # CSS variables present
