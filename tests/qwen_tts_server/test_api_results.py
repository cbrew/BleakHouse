from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from experiments.qwen_tts_server.config import Config
from experiments.qwen_tts_server.db import JobStore
from experiments.qwen_tts_server.main import build_app
from experiments.qwen_tts_server.storage import JobStorage


@pytest.fixture
def env(tmp_path: Path) -> Config:
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
    return cfg


def _seed_succeeded_job(cfg: Config, *, content: bytes = b"WAVDATA") -> str:
    store = JobStore(cfg.db_path)
    store.init_schema()
    store.create(job_id="JJJ", hash_="hhh", run_id="r")
    store.mark_succeeded("JJJ")
    storage = JobStorage(cfg.jobs_dir, "JJJ")
    storage.create()
    (storage.out / "episode.wav").write_bytes(content)
    return "JJJ"


def test_get_result_returns_file(env: Config) -> None:
    job_id = _seed_succeeded_job(env, content=b"WAV")
    app = build_app(env, run_worker=False)
    r = TestClient(app).get(
        f"/jobs/{job_id}/result/episode.wav",
        headers={"Authorization": "Bearer s3cret"},
    )
    assert r.status_code == 200
    assert r.content == b"WAV"


def test_get_result_404_for_unknown_file(env: Config) -> None:
    job_id = _seed_succeeded_job(env)
    app = build_app(env, run_worker=False)
    r = TestClient(app).get(
        f"/jobs/{job_id}/result/nope.wav",
        headers={"Authorization": "Bearer s3cret"},
    )
    assert r.status_code == 404


def test_get_result_blocks_traversal(env: Config) -> None:
    job_id = _seed_succeeded_job(env)
    app = build_app(env, run_worker=False)
    r = TestClient(app).get(
        f"/jobs/{job_id}/result/..%2F..%2Fetc%2Fpasswd",
        headers={"Authorization": "Bearer s3cret"},
    )
    assert r.status_code in (400, 404)


def test_get_result_409_when_not_succeeded(env: Config) -> None:
    store = JobStore(env.db_path)
    store.init_schema()
    store.create(job_id="J2", hash_="h2", run_id="r")
    JobStorage(env.jobs_dir, "J2").create()
    app = build_app(env, run_worker=False)
    r = TestClient(app).get(
        "/jobs/J2/result/episode.wav",
        headers={"Authorization": "Bearer s3cret"},
    )
    assert r.status_code == 409


def test_delete_finished_job_removes_files(env: Config) -> None:
    job_id = _seed_succeeded_job(env)
    app = build_app(env, run_worker=False)
    r = TestClient(app).delete(
        f"/jobs/{job_id}",
        headers={"Authorization": "Bearer s3cret"},
    )
    assert r.status_code == 204
    assert not (env.jobs_dir / job_id).exists()


def test_get_log_returns_empty_when_missing(env: Config) -> None:
    store = JobStore(env.db_path)
    store.init_schema()
    store.create(job_id="JLOG", hash_="hl", run_id="r")
    JobStorage(env.jobs_dir, "JLOG").create()
    app = build_app(env, run_worker=False)
    r = TestClient(app).get(
        "/jobs/JLOG/log",
        headers={"Authorization": "Bearer s3cret"},
    )
    assert r.status_code == 200
    assert r.text == ""


def test_list_jobs(env: Config) -> None:
    _seed_succeeded_job(env)
    app = build_app(env, run_worker=False)
    r = TestClient(app).get("/jobs", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["jobs"]) == 1
    assert body["jobs"][0]["id"] == "JJJ"
