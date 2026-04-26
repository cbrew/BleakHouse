"""SQLite-backed job store. Per-call connections; WAL for safe concurrent reads."""
from __future__ import annotations

import enum
import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    id: str
    hash: str
    run_id: str
    status: JobStatus
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None
    progress: dict[str, Any] = field(default_factory=dict)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    hash TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL,
    error TEXT,
    progress TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);
"""


class JobStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def create(self, *, job_id: str, hash_: str, run_id: str) -> Job:
        now = time.time()
        with self._conn() as c:
            c.execute(
                "INSERT INTO jobs(id,hash,run_id,status,created_at,progress) VALUES(?,?,?,?,?,?)",
                (job_id, hash_, run_id, JobStatus.QUEUED.value, now, "{}"),
            )
        return Job(id=job_id, hash=hash_, run_id=run_id, status=JobStatus.QUEUED, created_at=now)

    def get(self, job_id: str) -> Job | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    def get_by_hash(self, hash_: str) -> Job | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM jobs WHERE hash=?", (hash_,)).fetchone()
        return _row_to_job(row) if row else None

    def list_jobs(self) -> list[Job]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
        return [_row_to_job(r) for r in rows]

    def mark_running(self, job_id: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE jobs SET status=?, started_at=? WHERE id=?",
                (JobStatus.RUNNING.value, time.time(), job_id),
            )

    def mark_succeeded(self, job_id: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE jobs SET status=?, finished_at=? WHERE id=?",
                (JobStatus.SUCCEEDED.value, time.time(), job_id),
            )

    def mark_failed(self, job_id: str, error: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE jobs SET status=?, finished_at=?, error=? WHERE id=?",
                (JobStatus.FAILED.value, time.time(), error, job_id),
            )

    def mark_cancelled(self, job_id: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE jobs SET status=?, finished_at=? WHERE id=? AND status IN (?,?)",
                (JobStatus.CANCELLED.value, time.time(), job_id,
                 JobStatus.QUEUED.value, JobStatus.RUNNING.value),
            )

    def update_progress(self, job_id: str, progress: dict[str, Any]) -> None:
        with self._conn() as c:
            c.execute("UPDATE jobs SET progress=? WHERE id=?", (json.dumps(progress), job_id))

    def pop_next_queued(self) -> Job | None:
        # Atomic: pick oldest queued job and mark running in one transaction.
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT * FROM jobs WHERE status=? ORDER BY created_at ASC LIMIT 1",
                (JobStatus.QUEUED.value,),
            ).fetchone()
            if row is None:
                c.execute("COMMIT")
                return None
            now = time.time()
            c.execute(
                "UPDATE jobs SET status=?, started_at=? WHERE id=?",
                (JobStatus.RUNNING.value, now, row["id"]),
            )
            c.execute("COMMIT")
        job = _row_to_job(row)
        job.status = JobStatus.RUNNING
        job.started_at = now
        return job

    def delete(self, job_id: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM jobs WHERE id=?", (job_id,))


def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"],
        hash=row["hash"],
        run_id=row["run_id"],
        status=JobStatus(row["status"]),
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error=row["error"],
        progress=json.loads(row["progress"] or "{}"),
    )
