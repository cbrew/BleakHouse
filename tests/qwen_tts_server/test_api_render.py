from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from experiments.qwen_tts_server.config import Config
from experiments.qwen_tts_server.main import build_app


@pytest.fixture
def app_state(tmp_path: Path):
    state = tmp_path / "state"
    token = tmp_path / "token"
    token.write_text("s3cret")
    cfg = Config(
        state_dir=state,
        jobs_dir=state / "jobs",
        db_path=state / "jobs.db",
        token_path=token,
        bind_host="127.0.0.1",
        bind_port=0,
        code_rev_path=None,
    )
    cfg.ensure_dirs()
    app = build_app(cfg, run_worker=False)
    return app, cfg


def _post_render(client: TestClient, **overrides):
    return client.post(
        "/render",
        headers={"Authorization": "Bearer s3cret"},
        data={"run_id": overrides.get("run_id", "run_x")},
        files=[
            ("manifest", ("manifest.json", overrides.get("manifest", b'{"a":1}'), "application/json")),
            ("phase3", ("phase3_episode.json", overrides.get("phase3", b'{"b":2}'), "application/json")),
            ("ref_source", ("podcast.mp3", overrides.get("ref_source", b"ID3..."), "audio/mpeg")),
        ],
    )


def test_render_accepts_files_and_returns_job(app_state) -> None:
    app, _ = app_state
    client = TestClient(app)
    r = _post_render(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["existing"] is False
    assert body["job"]["status"] == "queued"
    assert body["job"]["run_id"] == "run_x"


def test_render_is_idempotent_by_hash(app_state) -> None:
    app, _ = app_state
    client = TestClient(app)
    r1 = _post_render(client)
    r2 = _post_render(client)
    assert r1.status_code == 201
    assert r2.status_code == 200
    assert r2.json()["existing"] is True
    assert r1.json()["job"]["id"] == r2.json()["job"]["id"]


def test_render_creates_new_job_on_content_change(app_state) -> None:
    app, _ = app_state
    client = TestClient(app)
    r1 = _post_render(client, manifest=b'{"a":1}')
    r2 = _post_render(client, manifest=b'{"a":2}')
    assert r1.json()["job"]["id"] != r2.json()["job"]["id"]


def test_render_requires_auth(app_state) -> None:
    app, _ = app_state
    r = TestClient(app).post("/render")
    assert r.status_code == 401


def test_render_inputs_persisted_on_disk(app_state) -> None:
    app, cfg = app_state
    client = TestClient(app)
    r = _post_render(client, manifest=b'{"persist":true}')
    job_id = r.json()["job"]["id"]
    assert (cfg.jobs_dir / job_id / "inputs" / "manifest.json").read_bytes() == b'{"persist":true}'
    assert (cfg.jobs_dir / job_id / "inputs" / "phase3_episode.json").exists()
    assert (cfg.jobs_dir / job_id / "inputs" / "ref_source.mp3").exists()


def test_no_staging_dir_left_behind_on_idempotency_hit(app_state) -> None:
    app, cfg = app_state
    client = TestClient(app)
    _post_render(client)
    _post_render(client)
    leftover = list(cfg.jobs_dir.glob("_staging_*"))
    assert leftover == []
