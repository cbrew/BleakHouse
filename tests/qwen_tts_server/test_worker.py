from __future__ import annotations

import time
from pathlib import Path

import pytest

from experiments.qwen_tts_server.config import Config
from experiments.qwen_tts_server.db import JobStatus, JobStore
from experiments.qwen_tts_server.storage import JobStorage
from experiments.qwen_tts_server.worker import Worker


@pytest.fixture
def env(tmp_path: Path) -> tuple[Config, JobStore]:
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
    store = JobStore(cfg.db_path)
    store.init_schema()
    return cfg, store


def _seed_job(cfg: Config, store: JobStore, job_id: str, hash_: str) -> None:
    storage = JobStorage(cfg.jobs_dir, job_id)
    storage.create()
    (storage.inputs / "manifest.json").write_bytes(b'{"segments": []}')
    (storage.inputs / "phase3_episode.json").write_bytes(b"{}")
    (storage.inputs / "ref_source.mp3").write_bytes(b"ID3")
    store.create(job_id=job_id, hash_=hash_, run_id="r")


def _wait_for_status(store: JobStore, job_id: str, expected: JobStatus, timeout: float = 5.0) -> JobStatus:
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = store.get(job_id)
        if j is not None and j.status == expected:
            return j.status
        time.sleep(0.05)
    j = store.get(job_id)
    return j.status if j else JobStatus.QUEUED


def test_worker_runs_queued_job_and_marks_succeeded(env: tuple[Config, JobStore]) -> None:
    cfg, store = env
    _seed_job(cfg, store, "J1", "h1")

    def fake_render(*, run_dir, refs_dir, out_dir, ref_source, log_file, cancel_check):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "episode.wav").write_bytes(b"WAVDATA")
        (out_dir / "episode.json").write_bytes(b'{"ok":true}')
        log_file.write_text("rendered\n")

    worker = Worker(cfg=cfg, store=store, render_fn=fake_render)
    worker.start()
    try:
        worker.notify()
        status = _wait_for_status(store, "J1", JobStatus.SUCCEEDED)
        assert status == JobStatus.SUCCEEDED
        assert (cfg.jobs_dir / "J1" / "out" / "episode.wav").read_bytes() == b"WAVDATA"
    finally:
        worker.stop()


def test_worker_marks_failed_on_exception(env: tuple[Config, JobStore]) -> None:
    cfg, store = env
    _seed_job(cfg, store, "J2", "h2")

    def bad_render(**kwargs):
        raise RuntimeError("kaboom")

    worker = Worker(cfg=cfg, store=store, render_fn=bad_render)
    worker.start()
    try:
        worker.notify()
        status = _wait_for_status(store, "J2", JobStatus.FAILED)
        assert status == JobStatus.FAILED
        j = store.get("J2")
        assert j is not None
        assert j.error and "kaboom" in j.error
    finally:
        worker.stop()


def test_worker_processes_jobs_sequentially(env: tuple[Config, JobStore]) -> None:
    cfg, store = env
    _seed_job(cfg, store, "A", "ha")
    time.sleep(0.01)
    _seed_job(cfg, store, "B", "hb")

    started: list[str] = []

    def fake_render(*, run_dir, refs_dir, out_dir, ref_source, log_file, cancel_check):
        # Recover the job id from run_dir = <jobs_dir>/<job_id>/inputs.
        job_id = run_dir.parent.name
        started.append(job_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "episode.wav").write_bytes(b"x")

    worker = Worker(cfg=cfg, store=store, render_fn=fake_render)
    worker.start()
    try:
        worker.notify()
        _wait_for_status(store, "B", JobStatus.SUCCEEDED, timeout=5.0)
    finally:
        worker.stop()

    assert started == ["A", "B"]
