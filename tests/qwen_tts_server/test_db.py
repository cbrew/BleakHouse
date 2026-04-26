from __future__ import annotations

import time
from pathlib import Path

import pytest

from experiments.qwen_tts_server.db import JobStatus, JobStore


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    s = JobStore(tmp_path / "jobs.db")
    s.init_schema()
    return s


def test_create_and_get(store: JobStore) -> None:
    job = store.create(job_id="j1", hash_="h1", run_id="run_x")
    assert job.id == "j1"
    assert job.status == JobStatus.QUEUED
    fetched = store.get("j1")
    assert fetched is not None
    assert fetched.id == "j1"


def test_get_by_hash(store: JobStore) -> None:
    store.create(job_id="j1", hash_="h1", run_id="run_x")
    found = store.get_by_hash("h1")
    assert found is not None
    assert found.id == "j1"
    assert store.get_by_hash("nope") is None


def test_unique_hash_constraint(store: JobStore) -> None:
    store.create(job_id="j1", hash_="h1", run_id="run_x")
    with pytest.raises(Exception):
        store.create(job_id="j2", hash_="h1", run_id="run_y")


def test_status_transitions(store: JobStore) -> None:
    store.create(job_id="j1", hash_="h1", run_id="run_x")
    store.mark_running("j1")
    j = store.get("j1")
    assert j is not None and j.status == JobStatus.RUNNING
    store.mark_succeeded("j1")
    j = store.get("j1")
    assert j is not None and j.status == JobStatus.SUCCEEDED


def test_mark_failed_records_error(store: JobStore) -> None:
    store.create(job_id="j1", hash_="h1", run_id="run_x")
    store.mark_failed("j1", "boom")
    j = store.get("j1")
    assert j is not None
    assert j.status == JobStatus.FAILED
    assert j.error == "boom"


def test_list_orders_by_created_at_desc(store: JobStore) -> None:
    store.create(job_id="j1", hash_="h1", run_id="r1")
    time.sleep(0.01)
    store.create(job_id="j2", hash_="h2", run_id="r2")
    ids = [j.id for j in store.list_jobs()]
    assert ids == ["j2", "j1"]


def test_pop_next_queued_returns_oldest(store: JobStore) -> None:
    store.create(job_id="j1", hash_="h1", run_id="r1")
    time.sleep(0.01)
    store.create(job_id="j2", hash_="h2", run_id="r2")
    j = store.pop_next_queued()
    assert j is not None and j.id == "j1"
    j = store.pop_next_queued()
    assert j is not None and j.id == "j2"
    j = store.pop_next_queued()
    assert j is None
