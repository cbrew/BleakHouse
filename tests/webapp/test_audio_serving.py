"""Audio routes serve files locally — no R2 redirects in our code path."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Webapp wired to a tmp data dir with a synthetic run."""
    runs = tmp_path / "data" / "runs" / "test_run" / "audio"
    runs.mkdir(parents=True)
    (runs / "podcast.mp3").write_bytes(b"FAKE_MP3_BYTES")
    (runs / "podcast_qwen.mp3").write_bytes(b"FAKE_QWEN_BYTES")
    (runs / "manifest.json").write_text('{"segments": []}')

    import webapp.app as appmod

    monkeypatch.setattr(appmod, "DATA_DIR", tmp_path / "data")
    return TestClient(appmod.app)


def test_audio_mp3_served_locally_not_redirected(client: TestClient) -> None:
    """GET /audio/<run>/podcast.mp3 returns the bytes directly, not a 302."""
    resp = client.get("/audio/test_run/podcast.mp3", follow_redirects=False)
    assert resp.status_code == 200
    assert resp.content == b"FAKE_MP3_BYTES"
    assert "location" not in resp.headers


def test_audio_qwen_variant_served_locally(client: TestClient) -> None:
    """Variant filenames are passed through as ordinary file paths."""
    resp = client.get("/audio/test_run/podcast_qwen.mp3", follow_redirects=False)
    assert resp.status_code == 200
    assert resp.content == b"FAKE_QWEN_BYTES"


def test_path_traversal_rejected(client: TestClient) -> None:
    # FastAPI normalises %2F-encoded slashes at the routing layer before the
    # handler runs; the request never reaches serve_audio and gets a 404.
    # Our handler additionally checks for ".." in run_id / filename for the
    # case where a raw ".." appears (which FastAPI passes through).
    # Either way the server rejects the request — 400 or 404, not 200.
    resp = client.get("/audio/test_run/..%2Fconfig.json", follow_redirects=False)
    assert resp.status_code in (400, 404)
    assert resp.status_code != 200


def test_404_for_missing_audio(client: TestClient) -> None:
    resp = client.get("/audio/nonexistent_run/podcast.mp3", follow_redirects=False)
    assert resp.status_code == 404
