"""Stateful surface: config, sqlite store, per-job filesystem layout, idempotency hash.

All the parts that a future smoke test or admin tool needs to import without
pulling in FastAPI.
"""
from __future__ import annotations

import enum
import hashlib
import json
import os
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------- Config -------------------------------------------------------

@dataclass(frozen=True)
class Config:
    state_dir: Path
    jobs_dir: Path
    db_path: Path
    token_path: Path
    bind_host: str
    bind_port: int
    code_rev_path: Path | None

    @classmethod
    def from_env(cls) -> "Config":
        state = Path(os.environ.get("QWEN_TTS_STATE_DIR", "/var/lib/qwen-tts-server"))
        return cls(
            state_dir=state,
            jobs_dir=state / "jobs",
            db_path=state / "jobs.db",
            token_path=Path(os.environ.get("QWEN_TTS_TOKEN_PATH", "/etc/qwen-tts-server/token")),
            bind_host=os.environ.get("QWEN_TTS_HOST", "0.0.0.0"),
            bind_port=int(os.environ.get("QWEN_TTS_PORT", "8765")),
            code_rev_path=Path(os.environ["QWEN_TTS_CODE_REV"]) if "QWEN_TTS_CODE_REV" in os.environ else None,
        )

    def ensure_dirs(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def load_token(self) -> str:
        return self.token_path.read_text().strip()

    def code_rev(self) -> str:
        if self.code_rev_path and self.code_rev_path.exists():
            return self.code_rev_path.read_text().strip()
        return "unknown"


# ---------- Idempotency hash --------------------------------------------

def job_hash(files: Sequence[Path], *, code_rev: str, chunk: int = 1 << 20) -> str:
    """sha256 over (each file's bytes, in given order) + code_rev sentinel.

    Order matters: callers must canonicalise the file list.
    """
    h = hashlib.sha256()
    for path in files:
        with path.open("rb") as f:
            while True:
                buf = f.read(chunk)
                if not buf:
                    break
                h.update(buf)
        h.update(b"\x00FILEBOUNDARY\x00")
    h.update(b"\x00CODEREV\x00")
    h.update(code_rev.encode())
    return h.hexdigest()


# ---------- Per-job filesystem layout -----------------------------------

@dataclass(frozen=True)
class JobStorage:
    jobs_dir: Path
    job_id: str

    @property
    def root(self) -> Path:
        return self.jobs_dir / self.job_id

    @property
    def inputs(self) -> Path:
        return self.root / "inputs"

    @property
    def refs(self) -> Path:
        return self.root / "refs"

    @property
    def out(self) -> Path:
        return self.root / "out"

    @property
    def log(self) -> Path:
        return self.root / "log.txt"

    def create(self) -> None:
        for d in (self.inputs, self.refs, self.out):
            d.mkdir(parents=True, exist_ok=True)

    def save_input(self, name: str, data: bytes) -> Path:
        # `name` is a fixed kind chosen by the server, never user-controlled.
        path = self.inputs / name
        path.write_bytes(data)
        return path

    def result_path(self, name: str) -> Path:
        # `name` is taken from the request URL — confine to self.out.
        candidate = (self.out / name).resolve()
        try:
            candidate.relative_to(self.out.resolve())
        except ValueError as exc:
            raise ValueError(f"path escapes out dir: {name!r}") from exc
        return candidate


# ---------- SQLite job store --------------------------------------------

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
