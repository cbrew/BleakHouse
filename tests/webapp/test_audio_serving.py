"""Audio routes: mp3s 302-redirect to R2 (CDN-edged); audio JSON
manifests served locally from disk. R2 URLs are sourced from per-run
audio/assets.json (legacy non-shard mp3s) at app import time, and from
audio/shards.json (per-turn mp3s) on each request."""
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

    monkeypatch.setenv("BLEAKHOUSE_R2_PUBLIC_URL", "https://r2.example.test")
    import webapp.app as appmod

    monkeypatch.setattr(appmod, "DATA_DIR", tmp_path / "data")
    # Synthesise the R2 URL map directly: shape matches what
    # _build_audio_r2_map() produces by walking audio/assets.json.
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


def test_shards_json_injects_r2_urls(tmp_path, monkeypatch) -> None:
    """The shards index served by the webapp injects per-shard R2 URLs."""
    audio = tmp_path / "data" / "runs" / "shard_run" / "audio"
    audio.mkdir(parents=True)
    (audio / "shards.json").write_text(
        '{"shards": ['
        '{"file": "0000.mp3", "md5": "abcd1234ef567890"}'
        ']}'
    )

    monkeypatch.setenv("BLEAKHOUSE_R2_PUBLIC_URL", "https://r2.example.test")
    import webapp.app as appmod

    monkeypatch.setattr(appmod, "DATA_DIR", tmp_path / "data")
    c = TestClient(appmod.app)

    resp = c.get("/audio/shard_run/shards.json", follow_redirects=False)
    assert resp.status_code == 200
    body = resp.json()
    assert body["shards"][0]["url"] == \
        "https://r2.example.test/files/md5/ab/cd1234ef567890"


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

    monkeypatch.setenv("BLEAKHOUSE_R2_PUBLIC_URL", "https://r2.example.test")
    import webapp.app as appmod

    monkeypatch.setattr(appmod, "DATA_DIR", tmp_path / "data")
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


# ---------------------------------------------------------------------------
# _build_audio_r2_map — walks audio/assets.json (replaces dvc.lock parser)
# ---------------------------------------------------------------------------


def test_build_audio_r2_map_walks_assets_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per-run audio/assets.json populates _AUDIO_R2_URLS with cas.url() values."""
    runs = tmp_path / "data" / "runs"
    (runs / "run_a" / "audio").mkdir(parents=True)
    (runs / "run_a" / "audio" / "assets.json").write_text(
        '{"schema_version": 1, "assets": '
        '{"podcast.mp3": "aaaa1111bbbb2222cccc3333dddd4444"}}'
    )
    (runs / "run_b" / "audio").mkdir(parents=True)
    (runs / "run_b" / "audio" / "assets.json").write_text(
        '{"schema_version": 1, "assets": '
        '{"podcast.mp3": "1111aaaa2222bbbb3333cccc4444dddd",'
        ' "podcast_qwen.mp3": "ffff1111ffff2222ffff3333ffff4444"}}'
    )

    monkeypatch.setenv("BLEAKHOUSE_R2_PUBLIC_URL", "https://r2.example.test")
    import webapp.app as appmod

    audio_map, health = appmod._build_audio_r2_map(tmp_path / "data")

    assert audio_map == {
        "data/runs/run_a/audio/podcast.mp3":
            "https://r2.example.test/files/md5/aa/aa1111bbbb2222cccc3333dddd4444",
        "data/runs/run_b/audio/podcast.mp3":
            "https://r2.example.test/files/md5/11/11aaaa2222bbbb3333cccc4444dddd",
        "data/runs/run_b/audio/podcast_qwen.mp3":
            "https://r2.example.test/files/md5/ff/ff1111ffff2222ffff3333ffff4444",
    }
    assert health == []


def test_build_audio_r2_map_skips_runs_without_assets_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Runs with no assets.json contribute zero entries (hard-binary visibility)."""
    runs = tmp_path / "data" / "runs"
    (runs / "no_audio_run" / "audio").mkdir(parents=True)
    # Note: no assets.json. Directory exists; in-progress run.

    monkeypatch.setenv("BLEAKHOUSE_R2_PUBLIC_URL", "https://r2.example.test")
    import webapp.app as appmod

    audio_map, health = appmod._build_audio_r2_map(tmp_path / "data")

    assert audio_map == {}
    assert health == []


def test_build_audio_r2_map_flags_malformed_assets_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed assets.json → drop, log to data_health, do not crash startup."""
    runs = tmp_path / "data" / "runs"
    (runs / "broken_run" / "audio").mkdir(parents=True)
    (runs / "broken_run" / "audio" / "assets.json").write_text(
        "not valid json {{{"
    )

    monkeypatch.setenv("BLEAKHOUSE_R2_PUBLIC_URL", "https://r2.example.test")
    import webapp.app as appmod

    audio_map, health = appmod._build_audio_r2_map(tmp_path / "data")

    assert audio_map == {}
    assert len(health) == 1
    assert health[0]["run_id"] == "broken_run"
    assert health[0]["manifest"] == "audio/assets.json"
    assert "json" in health[0]["error"].lower()


def test_build_audio_r2_map_flags_wrong_schema_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """schema_version != 1 → flag in data_health, not in map."""
    runs = tmp_path / "data" / "runs"
    (runs / "future_run" / "audio").mkdir(parents=True)
    (runs / "future_run" / "audio" / "assets.json").write_text(
        '{"schema_version": 99, "assets": {"podcast.mp3": "aa' + '0' * 30 + '"}}'
    )

    monkeypatch.setenv("BLEAKHOUSE_R2_PUBLIC_URL", "https://r2.example.test")
    import webapp.app as appmod

    audio_map, health = appmod._build_audio_r2_map(tmp_path / "data")

    assert audio_map == {}
    assert len(health) == 1
    assert health[0]["run_id"] == "future_run"
    assert "schema_version" in health[0]["error"]
