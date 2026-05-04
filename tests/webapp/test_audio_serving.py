"""Audio routes: mp3s 302-redirect to R2 (CDN-edged); audio JSON
manifests served locally from disk. R2 URLs are sourced from dvc.lock
at app import time."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Webapp wired to a tmp data dir + a synthetic R2 URL map for two runs."""
    runs = tmp_path / "data" / "runs" / "test_run" / "audio"
    runs.mkdir(parents=True)
    (runs / "manifest.json").write_text('{"segments": []}')
    (runs / "shards.json").write_text('{"shards": []}')

    import webapp.app as appmod

    monkeypatch.setattr(appmod, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(appmod, "R2_PUBLIC_URL", "https://r2.example.test")
    # Synthesise an R2 URL map: same shape _build_audio_r2_map() produces.
    monkeypatch.setattr(appmod, "_AUDIO_R2_URLS", {
        "data/runs/test_run/audio/podcast.mp3":
            "https://r2.example.test/files/md5/aa/bbccdd",
        "data/runs/test_run/audio/podcast_qwen.mp3":
            "https://r2.example.test/files/md5/11/223344",
    })
    return TestClient(appmod.app)


def test_audio_mp3_redirects_to_r2(client: TestClient) -> None:
    """GET /audio/<run>/podcast.mp3 returns a 302 with R2 URL."""
    resp = client.get("/audio/test_run/podcast.mp3", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://r2.example.test/files/md5/aa/bbccdd"


def test_audio_qwen_variant_also_redirects(client: TestClient) -> None:
    """Variant mp3s use the same lookup."""
    resp = client.get("/audio/test_run/podcast_qwen.mp3", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://r2.example.test/files/md5/11/223344"


def test_audio_mp3_unknown_file_404s(client: TestClient) -> None:
    """An mp3 not in the dvc.lock-derived map returns 404 (not a stale URL)."""
    resp = client.get("/audio/test_run/podcast_nonexistent.mp3", follow_redirects=False)
    assert resp.status_code == 404


def test_audio_manifest_json_served_locally(client: TestClient) -> None:
    """JSON manifests stay local — no R2 round-trip for ms-of-text data."""
    resp = client.get("/audio/test_run/manifest.json", follow_redirects=False)
    assert resp.status_code == 200
    assert b"segments" in resp.content


def test_shards_json_served_locally(client: TestClient) -> None:
    """The shards index is small JSON, served from local cache."""
    resp = client.get("/audio/test_run/shards.json", follow_redirects=False)
    assert resp.status_code == 200
    assert b"shards" in resp.content


def test_shard_audio_redirects_to_r2(tmp_path, monkeypatch) -> None:
    """Shard mp3 requests resolve via shards.json md5 → R2 URL."""
    runs = tmp_path / "data" / "runs" / "shard_run" / "audio" / "shards" / "trevelyan_v2"
    runs.mkdir(parents=True)
    shards_path = tmp_path / "data" / "runs" / "shard_run" / "audio" / "shards.json"
    shards_path.write_text(
        '{"shards": ['
        '{"file": "0000.mp3", "md5": "abcd1234ef567890"},'
        '{"file": "0001.mp3", "md5": "9876543210fedcba"}'
        ']}'
    )

    import webapp.app as appmod

    monkeypatch.setattr(appmod, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(appmod, "R2_PUBLIC_URL", "https://r2.example.test")
    c = TestClient(appmod.app)

    r = c.get("/audio/shard_run/shards/trevelyan_v2/0000.mp3", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "https://r2.example.test/files/md5/ab/cd1234ef567890"

    r = c.get("/audio/shard_run/shards/trevelyan_v2/missing.mp3", follow_redirects=False)
    assert r.status_code == 404


def test_path_traversal_rejected(client: TestClient) -> None:
    # FastAPI normalises %2F-encoded slashes at the routing layer before the
    # handler runs; the request never reaches serve_audio. The handler also
    # checks for ".." in run_id / filename for raw-".." cases. Either way
    # the server rejects the request — 400 or 404, not 200.
    resp = client.get("/audio/test_run/..%2Fconfig.json", follow_redirects=False)
    assert resp.status_code in (400, 404)
    assert resp.status_code != 200


def test_audio_unknown_run_404s(client: TestClient) -> None:
    resp = client.get("/audio/nonexistent_run/podcast.mp3", follow_redirects=False)
    assert resp.status_code == 404
