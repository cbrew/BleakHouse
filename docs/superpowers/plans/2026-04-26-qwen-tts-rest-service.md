# Qwen TTS REST Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `scripts/render_qwen_remote.sh` (a long-lived ssh wrapper that breaks when the connection flaps) with a FastAPI service on `pop-os.local` that owns the GPU and a thin local HTTP client that can drop the connection without losing work.

**Architecture:**
- Server: FastAPI app on pop-os bound to `127.0.0.1:8765` (Tailscale or LAN-routable later), single in-process worker thread that pulls jobs from SQLite and calls the existing `experiments.qwen_tts.{extract_refs,render_episode}` modules. Model loaded once. State + uploads under `/var/lib/qwen-tts-server/`. Runs under systemd.
- Client: Python CLI (`scripts/render_qwen_via_http.py`) that POSTs the per-run inputs, polls job state, downloads results. Bash wrapper (`scripts/render_qwen_remote.sh`) becomes a thin shim around the Python client to preserve the existing call site.
- Idempotency: sha256 of (manifest.json, phase3_episode.json, ref source mp3, qwen-renderer git rev). POSTing the same hash returns the existing job id instead of starting a new render.
- Auth: shared bearer token from `/etc/qwen-tts-server/token` (server) and `~/.config/qwen-tts/token` or `$QWEN_TTS_TOKEN` (client).

**Tech Stack:** FastAPI, uvicorn (already in deps), httpx (add), python-multipart (add), sqlite3 stdlib, systemd.

---

## File structure

**Server (lives in repo, deployed to pop-os):**
- Create `experiments/qwen_tts_server/__init__.py`
- Create `experiments/qwen_tts_server/config.py` — paths, port, token loader
- Create `experiments/qwen_tts_server/hashing.py` — idempotency hash
- Create `experiments/qwen_tts_server/storage.py` — per-job dir layout
- Create `experiments/qwen_tts_server/db.py` — sqlite job store
- Create `experiments/qwen_tts_server/auth.py` — bearer dependency
- Create `experiments/qwen_tts_server/schemas.py` — pydantic request/response
- Create `experiments/qwen_tts_server/worker.py` — background queue runner
- Create `experiments/qwen_tts_server/main.py` — FastAPI app + endpoints
- Create `experiments/qwen_tts_server/__main__.py` — `python -m experiments.qwen_tts_server` entrypoint
- Create `experiments/qwen_tts_server/qwen-tts-server.service` — systemd unit
- Create `experiments/qwen_tts_server/install.sh` — installer script
- Create `experiments/qwen_tts_server/README.md` — operations doc

**Tests (run locally on the Mac, no GPU needed — worker is stubbed):**
- Create `tests/qwen_tts_server/__init__.py`
- Create `tests/qwen_tts_server/test_hashing.py`
- Create `tests/qwen_tts_server/test_storage.py`
- Create `tests/qwen_tts_server/test_db.py`
- Create `tests/qwen_tts_server/test_auth.py`
- Create `tests/qwen_tts_server/test_api_render.py`
- Create `tests/qwen_tts_server/test_api_results.py`
- Create `tests/qwen_tts_server/test_idempotency.py`

**Client:**
- Create `scripts/render_qwen_via_http.py` — Python HTTP client (rich progress, retry-safe poll)
- Modify `scripts/render_qwen_remote.sh` — replace ssh body with a single call to the Python client

**Deps (modify):**
- Modify `pyproject.toml` — add `httpx>=0.27`, `python-multipart>=0.0.18`

---

## Task 1: Project skeleton + dependencies

**Files:**
- Create: `experiments/qwen_tts_server/__init__.py`
- Create: `experiments/qwen_tts_server/config.py`
- Create: `tests/qwen_tts_server/__init__.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dependencies**

In `pyproject.toml`, add to the `dependencies` list (alphabetical position):

```toml
    "httpx>=0.27",
    "python-multipart>=0.0.18",
```

- [ ] **Step 2: Run uv lock**

```bash
uv lock
uv sync
```

Expected: lockfile updates, no errors.

- [ ] **Step 3: Create package skeleton**

Write `experiments/qwen_tts_server/__init__.py`:

```python
"""FastAPI service that owns the pop-os GPU and runs Qwen3-TTS renders.

See docs/superpowers/plans/2026-04-26-qwen-tts-rest-service.md.
"""
```

Write `tests/qwen_tts_server/__init__.py` (empty).

- [ ] **Step 4: Write config module**

Write `experiments/qwen_tts_server/config.py`:

```python
"""Server config: paths, port, token loader.

Defaults match the systemd-managed install layout. Override via env for tests.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    state_dir: Path     # /var/lib/qwen-tts-server
    jobs_dir: Path      # /var/lib/qwen-tts-server/jobs
    db_path: Path       # /var/lib/qwen-tts-server/jobs.db
    token_path: Path    # /etc/qwen-tts-server/token
    bind_host: str      # 0.0.0.0 in prod, 127.0.0.1 in tests
    bind_port: int      # 8765
    code_rev_path: Path | None  # optional: file holding git rev of the renderer

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
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock experiments/qwen_tts_server/ tests/qwen_tts_server/
git commit -m "feat(qwen-tts-server): package skeleton + config"
```

---

## Task 2: Idempotency hash

**Files:**
- Create: `experiments/qwen_tts_server/hashing.py`
- Create: `tests/qwen_tts_server/test_hashing.py`

- [ ] **Step 1: Write the failing test**

Write `tests/qwen_tts_server/test_hashing.py`:

```python
"""Idempotency hash is stable and depends on every input."""
from __future__ import annotations

from pathlib import Path

import pytest

from experiments.qwen_tts_server.hashing import job_hash


@pytest.fixture
def two_files(tmp_path: Path) -> tuple[Path, Path]:
    a = tmp_path / "a.json"
    b = tmp_path / "b.mp3"
    a.write_bytes(b"alpha")
    b.write_bytes(b"bravo")
    return a, b


def test_hash_is_deterministic(two_files: tuple[Path, Path]) -> None:
    a, b = two_files
    h1 = job_hash([a, b], code_rev="rev1")
    h2 = job_hash([a, b], code_rev="rev1")
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex


def test_hash_changes_on_content_change(two_files: tuple[Path, Path], tmp_path: Path) -> None:
    a, b = two_files
    h1 = job_hash([a, b], code_rev="rev1")
    a.write_bytes(b"alpha-changed")
    h2 = job_hash([a, b], code_rev="rev1")
    assert h1 != h2


def test_hash_changes_on_code_rev_change(two_files: tuple[Path, Path]) -> None:
    a, b = two_files
    assert job_hash([a, b], code_rev="rev1") != job_hash([a, b], code_rev="rev2")


def test_hash_is_order_sensitive(two_files: tuple[Path, Path]) -> None:
    a, b = two_files
    assert job_hash([a, b], code_rev="rev1") != job_hash([b, a], code_rev="rev1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/qwen_tts_server/test_hashing.py -v`
Expected: FAIL with `ModuleNotFoundError: experiments.qwen_tts_server.hashing`.

- [ ] **Step 3: Write minimal implementation**

Write `experiments/qwen_tts_server/hashing.py`:

```python
"""Idempotency hash over input files + renderer code rev."""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path


def job_hash(files: Sequence[Path], *, code_rev: str, chunk: int = 1 << 20) -> str:
    """sha256 over (each file's bytes, in given order) + code_rev sentinel.

    Order matters: `[a, b]` and `[b, a]` produce different hashes so callers
    must canonicalize the file list before passing it in.
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/qwen_tts_server/test_hashing.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add experiments/qwen_tts_server/hashing.py tests/qwen_tts_server/test_hashing.py
git commit -m "feat(qwen-tts-server): job hash for idempotency"
```

---

## Task 3: Storage layer (per-job directories)

**Files:**
- Create: `experiments/qwen_tts_server/storage.py`
- Create: `tests/qwen_tts_server/test_storage.py`

Layout per job:
```
<jobs_dir>/<job_id>/
    inputs/
        manifest.json
        phase3_episode.json
        ref_source.mp3
    refs/                 (filled by extract_refs)
    out/                  (filled by render_episode: episode.wav, episode.json, segment_NN.wav, utterances/)
    log.txt
```

- [ ] **Step 1: Write the failing test**

Write `tests/qwen_tts_server/test_storage.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from experiments.qwen_tts_server.storage import JobStorage


@pytest.fixture
def jobs_dir(tmp_path: Path) -> Path:
    d = tmp_path / "jobs"
    d.mkdir()
    return d


def test_paths_are_under_job_dir(jobs_dir: Path) -> None:
    s = JobStorage(jobs_dir, "abc123")
    assert s.root == jobs_dir / "abc123"
    assert s.inputs == s.root / "inputs"
    assert s.refs == s.root / "refs"
    assert s.out == s.root / "out"
    assert s.log == s.root / "log.txt"


def test_create_makes_subdirs(jobs_dir: Path) -> None:
    s = JobStorage(jobs_dir, "abc123")
    s.create()
    assert s.inputs.is_dir()
    assert s.refs.is_dir()
    assert s.out.is_dir()


def test_save_input_writes_bytes(jobs_dir: Path) -> None:
    s = JobStorage(jobs_dir, "abc123")
    s.create()
    s.save_input("manifest.json", b'{"hello": 1}')
    assert (s.inputs / "manifest.json").read_bytes() == b'{"hello": 1}'


def test_result_path_resolves_within_out(jobs_dir: Path) -> None:
    s = JobStorage(jobs_dir, "abc123")
    s.create()
    (s.out / "episode.wav").write_bytes(b"RIFF...")
    assert s.result_path("episode.wav").read_bytes() == b"RIFF..."


def test_result_path_rejects_traversal(jobs_dir: Path) -> None:
    s = JobStorage(jobs_dir, "abc123")
    s.create()
    with pytest.raises(ValueError):
        s.result_path("../../etc/passwd")
    with pytest.raises(ValueError):
        s.result_path("/etc/passwd")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/qwen_tts_server/test_storage.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Write minimal implementation**

Write `experiments/qwen_tts_server/storage.py`:

```python
"""Per-job filesystem layout under <jobs_dir>/<job_id>/."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
        # name is a fixed kind ("manifest.json", etc.) — never user-controlled.
        path = self.inputs / name
        path.write_bytes(data)
        return path

    def result_path(self, name: str) -> Path:
        # name comes from the URL; resolve and confine to self.out.
        candidate = (self.out / name).resolve()
        out_resolved = self.out.resolve()
        if not str(candidate).startswith(str(out_resolved) + "/") and candidate != out_resolved:
            raise ValueError(f"path escapes out dir: {name!r}")
        return candidate
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/qwen_tts_server/test_storage.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add experiments/qwen_tts_server/storage.py tests/qwen_tts_server/test_storage.py
git commit -m "feat(qwen-tts-server): per-job filesystem storage with traversal guard"
```

---

## Task 4: SQLite job store

**Files:**
- Create: `experiments/qwen_tts_server/db.py`
- Create: `tests/qwen_tts_server/test_db.py`

Schema:
```sql
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    hash TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL,
    status TEXT NOT NULL,         -- queued|running|succeeded|failed|cancelled
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL,
    error TEXT,
    progress TEXT                 -- arbitrary JSON blob for "5/120 utterances"
);
CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_created_at ON jobs(created_at);
```

- [ ] **Step 1: Write the failing test**

Write `tests/qwen_tts_server/test_db.py`:

```python
from __future__ import annotations

import time
from pathlib import Path

import pytest

from experiments.qwen_tts_server.db import JobStore, JobStatus


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    s = JobStore(tmp_path / "jobs.db")
    s.init_schema()
    return s


def test_create_and_get(store: JobStore) -> None:
    job = store.create(job_id="j1", hash_="h1", run_id="run_x")
    assert job.id == "j1"
    assert job.status == JobStatus.QUEUED
    assert store.get("j1") == job


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
    assert store.get("j1").status == JobStatus.RUNNING
    store.mark_succeeded("j1")
    assert store.get("j1").status == JobStatus.SUCCEEDED


def test_mark_failed_records_error(store: JobStore) -> None:
    store.create(job_id="j1", hash_="h1", run_id="run_x")
    store.mark_failed("j1", "boom")
    j = store.get("j1")
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
    # popping marks running, so the next call returns j2
    j = store.pop_next_queued()
    assert j is not None and j.id == "j2"
    j = store.pop_next_queued()
    assert j is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/qwen_tts_server/test_db.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Write minimal implementation**

Write `experiments/qwen_tts_server/db.py`:

```python
"""SQLite-backed job store. Single-writer; thread-safe via per-call connections."""
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
            c.execute(
                "UPDATE jobs SET status=?, started_at=? WHERE id=?",
                (JobStatus.RUNNING.value, time.time(), row["id"]),
            )
            c.execute("COMMIT")
        job = _row_to_job(row)
        job.status = JobStatus.RUNNING
        job.started_at = time.time()
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
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/qwen_tts_server/test_db.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add experiments/qwen_tts_server/db.py tests/qwen_tts_server/test_db.py
git commit -m "feat(qwen-tts-server): sqlite job store with status transitions"
```

---

## Task 5: Bearer token auth dependency

**Files:**
- Create: `experiments/qwen_tts_server/auth.py`
- Create: `tests/qwen_tts_server/test_auth.py`

- [ ] **Step 1: Write the failing test**

Write `tests/qwen_tts_server/test_auth.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from experiments.qwen_tts_server.auth import bearer_auth_factory


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    token_file = tmp_path / "token"
    token_file.write_text("s3cret\n")
    auth = bearer_auth_factory(token_file)
    app = FastAPI()

    @app.get("/ping")
    def _ping(_: str = Depends(auth)) -> dict[str, str]:
        return {"ok": "yes"}

    return app


def test_missing_header_is_401(app: FastAPI) -> None:
    r = TestClient(app).get("/ping")
    assert r.status_code == 401


def test_wrong_token_is_403(app: FastAPI) -> None:
    r = TestClient(app).get("/ping", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 403


def test_correct_token_passes(app: FastAPI) -> None:
    r = TestClient(app).get("/ping", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/qwen_tts_server/test_auth.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Write the implementation**

Write `experiments/qwen_tts_server/auth.py`:

```python
"""Bearer token dependency factory.

Loads the expected token once from `token_path` at factory time. The factory
returns a FastAPI dependency that compares the request's bearer to the
expected token in constant time.
"""
from __future__ import annotations

import hmac
from collections.abc import Callable
from pathlib import Path

from fastapi import Header, HTTPException, status


def bearer_auth_factory(token_path: Path) -> Callable[[str | None], str]:
    expected = token_path.read_text().strip()
    if not expected:
        raise RuntimeError(f"empty auth token at {token_path}")

    def _dep(authorization: str | None = Header(default=None)) -> str:
        if authorization is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing Authorization header")
        if not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="expected Bearer scheme")
        provided = authorization[7:].strip()
        if not hmac.compare_digest(provided, expected):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid token")
        return provided

    return _dep
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/qwen_tts_server/test_auth.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add experiments/qwen_tts_server/auth.py tests/qwen_tts_server/test_auth.py
git commit -m "feat(qwen-tts-server): bearer token auth dependency"
```

---

## Task 6: Pydantic schemas

**Files:**
- Create: `experiments/qwen_tts_server/schemas.py`

- [ ] **Step 1: Write schemas**

Write `experiments/qwen_tts_server/schemas.py`:

```python
"""Request/response schemas. Aligned with the JobStore.Job dataclass."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class JobView(BaseModel):
    id: str
    hash: str
    run_id: str
    status: str
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None
    progress: dict[str, Any] = Field(default_factory=dict)


class CreateJobResponse(BaseModel):
    job: JobView
    existing: bool  # True if this was an idempotency hit


class JobListResponse(BaseModel):
    jobs: list[JobView]
```

(No test — schemas are exercised in the API tests below.)

- [ ] **Step 2: Commit**

```bash
git add experiments/qwen_tts_server/schemas.py
git commit -m "feat(qwen-tts-server): pydantic request/response schemas"
```

---

## Task 7: FastAPI app + POST /render with idempotency

**Files:**
- Create: `experiments/qwen_tts_server/main.py`
- Create: `tests/qwen_tts_server/test_api_render.py`

- [ ] **Step 1: Write the failing test**

Write `tests/qwen_tts_server/test_api_render.py`:

```python
from __future__ import annotations

import json
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
        state_dir=state, jobs_dir=state / "jobs", db_path=state / "jobs.db",
        token_path=token, bind_host="127.0.0.1", bind_port=0, code_rev_path=None,
    )
    cfg.ensure_dirs()
    app = build_app(cfg, run_worker=False)
    return app, cfg


def _post_render(client: TestClient, **files):
    return client.post(
        "/render",
        headers={"Authorization": "Bearer s3cret"},
        data={"run_id": files.get("run_id", "run_x")},
        files=[
            ("manifest", ("manifest.json", files.get("manifest", b'{"a":1}'), "application/json")),
            ("phase3", ("phase3_episode.json", files.get("phase3", b'{"b":2}'), "application/json")),
            ("ref_source", ("podcast.mp3", files.get("ref_source", b"ID3..."), "audio/mpeg")),
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
    r2 = _post_render(client)  # identical bytes
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/qwen_tts_server/test_api_render.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Write the implementation**

Write `experiments/qwen_tts_server/main.py`:

```python
"""FastAPI app: POST /render, GET /jobs, GET /jobs/{id}, GET result, DELETE."""
from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse

from .auth import bearer_auth_factory
from .config import Config
from .db import JobStatus, JobStore
from .hashing import job_hash
from .schemas import CreateJobResponse, JobListResponse, JobView
from .storage import JobStorage
from .worker import Worker

logger = logging.getLogger(__name__)


def _job_to_view(job) -> JobView:
    return JobView(
        id=job.id, hash=job.hash, run_id=job.run_id, status=job.status.value,
        created_at=job.created_at, started_at=job.started_at, finished_at=job.finished_at,
        error=job.error, progress=job.progress,
    )


def build_app(cfg: Config, *, run_worker: bool = True) -> FastAPI:
    cfg.ensure_dirs()
    store = JobStore(cfg.db_path)
    store.init_schema()
    auth = bearer_auth_factory(cfg.token_path)

    worker = Worker(cfg=cfg, store=store)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if run_worker:
            worker.start()
        try:
            yield
        finally:
            if run_worker:
                worker.stop()

    app = FastAPI(title="qwen-tts-server", lifespan=lifespan)

    @app.post("/render", response_model=CreateJobResponse, status_code=201)
    async def render(
        manifest: Annotated[UploadFile, File()],
        phase3: Annotated[UploadFile, File()],
        ref_source: Annotated[UploadFile, File()],
        run_id: Annotated[str, Form()],
        _: Annotated[str, Depends(auth)],
    ) -> Response:
        manifest_bytes = await manifest.read()
        phase3_bytes = await phase3.read()
        ref_bytes = await ref_source.read()

        # Stage to a temp dir to compute the hash, then move into place if new.
        tmp_id = uuid.uuid4().hex
        tmp_storage = JobStorage(cfg.jobs_dir, f"_staging_{tmp_id}")
        tmp_storage.create()
        tmp_storage.save_input("manifest.json", manifest_bytes)
        tmp_storage.save_input("phase3_episode.json", phase3_bytes)
        tmp_storage.save_input("ref_source.mp3", ref_bytes)

        h = job_hash(
            [
                tmp_storage.inputs / "manifest.json",
                tmp_storage.inputs / "phase3_episode.json",
                tmp_storage.inputs / "ref_source.mp3",
            ],
            code_rev=cfg.code_rev(),
        )

        existing = store.get_by_hash(h)
        if existing is not None:
            # Drop the staging dir; a job for these inputs already exists.
            _rmtree(tmp_storage.root)
            return _json_response(CreateJobResponse(job=_job_to_view(existing), existing=True), 200)

        # Promote the staging dir to the real job dir.
        job_id = uuid.uuid4().hex
        final = JobStorage(cfg.jobs_dir, job_id)
        tmp_storage.root.rename(final.root)

        job = store.create(job_id=job_id, hash_=h, run_id=run_id)
        worker.notify()
        return _json_response(CreateJobResponse(job=_job_to_view(job), existing=False), 201)

    @app.get("/jobs", response_model=JobListResponse)
    def list_jobs(_: Annotated[str, Depends(auth)]) -> JobListResponse:
        return JobListResponse(jobs=[_job_to_view(j) for j in store.list_jobs()])

    @app.get("/jobs/{job_id}", response_model=JobView)
    def get_job(job_id: str, _: Annotated[str, Depends(auth)]) -> JobView:
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return _job_to_view(job)

    @app.get("/jobs/{job_id}/result/{name}")
    def get_result(job_id: str, name: str, _: Annotated[str, Depends(auth)]):
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        if job.status != JobStatus.SUCCEEDED:
            raise HTTPException(status_code=409, detail=f"job status is {job.status.value}")
        storage = JobStorage(cfg.jobs_dir, job_id)
        try:
            path = storage.result_path(name)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid result name")
        if not path.exists():
            raise HTTPException(status_code=404, detail="result file not found")
        return FileResponse(path)

    @app.get("/jobs/{job_id}/log", response_class=Response)
    def get_log(job_id: str, _: Annotated[str, Depends(auth)]) -> Response:
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        log_path = JobStorage(cfg.jobs_dir, job_id).log
        if not log_path.exists():
            return Response(content="", media_type="text/plain")
        return Response(content=log_path.read_text(), media_type="text/plain")

    @app.delete("/jobs/{job_id}", status_code=204)
    def delete_job(job_id: str, _: Annotated[str, Depends(auth)]) -> Response:
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
            store.mark_cancelled(job_id)
            worker.cancel(job_id)
        else:
            storage = JobStorage(cfg.jobs_dir, job_id)
            _rmtree(storage.root)
            store.delete(job_id)
        return Response(status_code=204)

    return app


def _json_response(model, status_code: int) -> Response:
    return Response(content=model.model_dump_json(), status_code=status_code, media_type="application/json")


def _rmtree(path: Path) -> None:
    import shutil
    if path.exists():
        shutil.rmtree(path)
```

- [ ] **Step 4: Stub the worker (placeholder for Task 9)**

Write `experiments/qwen_tts_server/worker.py`:

```python
"""Background worker — placeholder; real impl in Task 9."""
from __future__ import annotations

import logging

from .config import Config
from .db import JobStore

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, *, cfg: Config, store: JobStore) -> None:
        self.cfg = cfg
        self.store = store

    def start(self) -> None:
        logger.info("worker.start (stub)")

    def stop(self) -> None:
        logger.info("worker.stop (stub)")

    def notify(self) -> None:
        # Will wake the worker thread to drain the queue.
        pass

    def cancel(self, job_id: str) -> None:
        # Signals the running job to stop; no-op for stub.
        pass
```

- [ ] **Step 5: Run the API tests**

Run: `uv run pytest tests/qwen_tts_server/test_api_render.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add experiments/qwen_tts_server/main.py experiments/qwen_tts_server/worker.py \
        tests/qwen_tts_server/test_api_render.py
git commit -m "feat(qwen-tts-server): POST /render with idempotency + GET/DELETE handlers"
```

---

## Task 8: Result download tests

**Files:**
- Create: `tests/qwen_tts_server/test_api_results.py`

- [ ] **Step 1: Write tests**

Write `tests/qwen_tts_server/test_api_results.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from experiments.qwen_tts_server.config import Config
from experiments.qwen_tts_server.db import JobStatus, JobStore
from experiments.qwen_tts_server.main import build_app
from experiments.qwen_tts_server.storage import JobStorage


@pytest.fixture
def env(tmp_path: Path):
    state = tmp_path / "state"
    token = tmp_path / "token"
    token.write_text("s3cret")
    cfg = Config(
        state_dir=state, jobs_dir=state / "jobs", db_path=state / "jobs.db",
        token_path=token, bind_host="127.0.0.1", bind_port=0, code_rev_path=None,
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
    r = TestClient(app).get(f"/jobs/{job_id}/result/episode.wav", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200
    assert r.content == b"WAV"


def test_get_result_404_for_unknown_file(env: Config) -> None:
    job_id = _seed_succeeded_job(env)
    app = build_app(env, run_worker=False)
    r = TestClient(app).get(f"/jobs/{job_id}/result/nope.wav", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 404


def test_get_result_blocks_traversal(env: Config) -> None:
    job_id = _seed_succeeded_job(env)
    app = build_app(env, run_worker=False)
    r = TestClient(app).get(f"/jobs/{job_id}/result/..%2F..%2Fetc%2Fpasswd",
                            headers={"Authorization": "Bearer s3cret"})
    assert r.status_code in (400, 404)


def test_get_result_409_when_not_succeeded(env: Config) -> None:
    store = JobStore(env.db_path)
    store.init_schema()
    store.create(job_id="J2", hash_="h2", run_id="r")
    JobStorage(env.jobs_dir, "J2").create()
    app = build_app(env, run_worker=False)
    r = TestClient(app).get("/jobs/J2/result/episode.wav", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 409


def test_delete_finished_job_removes_files(env: Config) -> None:
    job_id = _seed_succeeded_job(env)
    app = build_app(env, run_worker=False)
    r = TestClient(app).delete(f"/jobs/{job_id}", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 204
    assert not (env.jobs_dir / job_id).exists()


def test_get_log_returns_empty_when_missing(env: Config) -> None:
    store = JobStore(env.db_path)
    store.init_schema()
    store.create(job_id="JLOG", hash_="hl", run_id="r")
    JobStorage(env.jobs_dir, "JLOG").create()
    app = build_app(env, run_worker=False)
    r = TestClient(app).get("/jobs/JLOG/log", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200
    assert r.text == ""
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/qwen_tts_server/test_api_results.py -v`
Expected: 6 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/qwen_tts_server/test_api_results.py
git commit -m "test(qwen-tts-server): result download + log + delete coverage"
```

---

## Task 9: Worker thread (real implementation)

**Files:**
- Modify: `experiments/qwen_tts_server/worker.py`

The worker is single-threaded (one GPU) and:
1. Owns one Python thread that loops on `pop_next_queued()`.
2. For each job: writes log file, runs `extract_refs(...)` then `render_episode(...)` from the existing modules in `experiments.qwen_tts.*`.
3. On success: `store.mark_succeeded`. On exception: `store.mark_failed(err)`.
4. `notify()` wakes the loop via a `threading.Event`. `stop()` sets a stop event.
5. `cancel(job_id)` sets a per-job cancel flag — checked between segments (best-effort; not preemptive).

Worker tests use a fake render function injected via `Worker(..., render_fn=...)`.

- [ ] **Step 1: Add a worker test** — `tests/qwen_tts_server/test_worker.py`

```python
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from experiments.qwen_tts_server.config import Config
from experiments.qwen_tts_server.db import JobStatus, JobStore
from experiments.qwen_tts_server.storage import JobStorage
from experiments.qwen_tts_server.worker import Worker


@pytest.fixture
def env(tmp_path: Path):
    state = tmp_path / "state"
    token = tmp_path / "token"
    token.write_text("s3cret")
    cfg = Config(
        state_dir=state, jobs_dir=state / "jobs", db_path=state / "jobs.db",
        token_path=token, bind_host="127.0.0.1", bind_port=0, code_rev_path=None,
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


def test_worker_runs_queued_job_and_marks_succeeded(env) -> None:
    cfg, store = env
    _seed_job(cfg, store, "J1", "h1")

    def fake_render(*, run_dir: Path, refs_dir: Path, out_dir: Path, ref_source: Path,
                    log_file: Path, cancel_check):
        # Worker passes us paths; produce a dummy episode.wav.
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "episode.wav").write_bytes(b"WAVDATA")
        (out_dir / "episode.json").write_bytes(b'{"ok":true}')
        log_file.write_text("rendered\n")

    worker = Worker(cfg=cfg, store=store, render_fn=fake_render)
    worker.start()
    worker.notify()
    deadline = time.time() + 5
    while time.time() < deadline:
        if store.get("J1").status == JobStatus.SUCCEEDED:
            break
        time.sleep(0.05)
    worker.stop()
    assert store.get("J1").status == JobStatus.SUCCEEDED
    assert (cfg.jobs_dir / "J1" / "out" / "episode.wav").read_bytes() == b"WAVDATA"


def test_worker_marks_failed_on_exception(env) -> None:
    cfg, store = env
    _seed_job(cfg, store, "J2", "h2")

    def bad_render(**kwargs):
        raise RuntimeError("kaboom")

    worker = Worker(cfg=cfg, store=store, render_fn=bad_render)
    worker.start()
    worker.notify()
    deadline = time.time() + 5
    while time.time() < deadline:
        j = store.get("J2")
        if j.status == JobStatus.FAILED:
            break
        time.sleep(0.05)
    worker.stop()
    j = store.get("J2")
    assert j.status == JobStatus.FAILED
    assert j.error and "kaboom" in j.error
```

- [ ] **Step 2: Run test (will fail)**

Run: `uv run pytest tests/qwen_tts_server/test_worker.py -v`
Expected: FAIL — Worker doesn't accept `render_fn`.

- [ ] **Step 3: Implement the worker**

Replace `experiments/qwen_tts_server/worker.py`:

```python
"""Single-GPU background worker. Runs render jobs sequentially."""
from __future__ import annotations

import logging
import threading
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import Config
from .db import JobStore
from .storage import JobStorage

logger = logging.getLogger(__name__)


# Signature of the render function the worker calls. Default impl in this
# module imports the existing experiments.qwen_tts modules; tests inject a
# stub so they don't load the GPU model.
RenderFn = Callable[..., None]


def _default_render(
    *,
    run_dir: Path,
    refs_dir: Path,
    out_dir: Path,
    ref_source: Path,
    log_file: Path,
    cancel_check: Callable[[], bool],
) -> None:
    """Real renderer: extract refs, then render the episode.

    Imports the heavy modules lazily so unit tests don't pay for them.
    """
    from experiments.qwen_tts.extract_refs import extract_refs
    from experiments.qwen_tts.render_episode import render_episode

    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a") as lf:
        lf.write("=== extract_refs ===\n")
        lf.flush()
        extract_refs(run_dir=run_dir, out_dir=refs_dir, audio_path=ref_source)
        lf.write("=== render_episode ===\n")
        lf.flush()
        if cancel_check():
            lf.write("cancelled before render_episode\n")
            return
        render_episode(run_dir=run_dir, refs_dir=refs_dir, out_dir=out_dir)


class Worker:
    def __init__(self, *, cfg: Config, store: JobStore, render_fn: RenderFn | None = None) -> None:
        self.cfg = cfg
        self.store = store
        self._render_fn = render_fn or _default_render
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._cancelled: set[str] = set()
        self._cancel_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="qwen-tts-worker", daemon=True)
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def notify(self) -> None:
        self._wake.set()

    def cancel(self, job_id: str) -> None:
        with self._cancel_lock:
            self._cancelled.add(job_id)

    def _is_cancelled(self, job_id: str) -> bool:
        with self._cancel_lock:
            return job_id in self._cancelled

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = self.store.pop_next_queued()
            if job is None:
                self._wake.wait(timeout=2.0)
                self._wake.clear()
                continue
            self._run_one(job.id)

    def _run_one(self, job_id: str) -> None:
        storage = JobStorage(self.cfg.jobs_dir, job_id)
        try:
            self._render_fn(
                run_dir=storage.inputs,
                refs_dir=storage.refs,
                out_dir=storage.out,
                ref_source=storage.inputs / "ref_source.mp3",
                log_file=storage.log,
                cancel_check=lambda: self._is_cancelled(job_id),
            )
            if self._is_cancelled(job_id):
                # Status was already moved to cancelled by the API; don't
                # overwrite. But if the API only flagged us, mark cancelled
                # ourselves.
                self.store.mark_cancelled(job_id)
            else:
                self.store.mark_succeeded(job_id)
        except Exception as exc:
            tb = traceback.format_exc()
            try:
                with storage.log.open("a") as lf:
                    lf.write(f"\nERROR: {exc}\n{tb}\n")
            except OSError:
                pass
            self.store.mark_failed(job_id, str(exc))
            logger.exception("job %s failed", job_id)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/qwen_tts_server/test_worker.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/qwen_tts_server/ -v`
Expected: all green.

Run: `uv run ruff check experiments/qwen_tts_server tests/qwen_tts_server`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add experiments/qwen_tts_server/worker.py tests/qwen_tts_server/test_worker.py
git commit -m "feat(qwen-tts-server): single-GPU background worker"
```

---

## Task 10: CLI entrypoint + systemd unit + install script

**Files:**
- Create: `experiments/qwen_tts_server/__main__.py`
- Create: `experiments/qwen_tts_server/qwen-tts-server.service`
- Create: `experiments/qwen_tts_server/install.sh`
- Create: `experiments/qwen_tts_server/README.md`

- [ ] **Step 1: Write the entrypoint**

Write `experiments/qwen_tts_server/__main__.py`:

```python
"""Run with: python -m experiments.qwen_tts_server"""
from __future__ import annotations

import logging

import uvicorn

from .config import Config
from .main import build_app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    cfg = Config.from_env()
    app = build_app(cfg, run_worker=True)
    uvicorn.run(app, host=cfg.bind_host, port=cfg.bind_port, log_level="info")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write the systemd unit**

Write `experiments/qwen_tts_server/qwen-tts-server.service`:

```ini
[Unit]
Description=Qwen TTS render service (BleakHouse)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=cbrew
Group=cbrew
WorkingDirectory=/home/cbrew/bleakhouse-qwen-tts
Environment=QWEN_TTS_STATE_DIR=/var/lib/qwen-tts-server
Environment=QWEN_TTS_TOKEN_PATH=/etc/qwen-tts-server/token
Environment=QWEN_TTS_HOST=0.0.0.0
Environment=QWEN_TTS_PORT=8765
Environment=QWEN_TTS_CODE_REV=/var/lib/qwen-tts-server/code_rev
ExecStart=/home/cbrew/bleakhouse-qwen-tts/.venv/bin/python -m experiments.qwen_tts_server
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Write the install script**

Write `experiments/qwen_tts_server/install.sh`:

```bash
#!/bin/bash
# Install the Qwen TTS service on pop-os. Run with sudo on pop-os; sources
# rsync from a workstation. Idempotent: safe to re-run after each code push.
#
# Usage:
#   sudo bash install.sh
#
# Assumes the repo is already rsynced to /home/cbrew/bleakhouse-qwen-tts/
# and a venv is set up there with `uv sync`.

set -euo pipefail

REPO_DIR="${REPO_DIR:-/home/cbrew/bleakhouse-qwen-tts}"
STATE_DIR="${STATE_DIR:-/var/lib/qwen-tts-server}"
ETC_DIR="${ETC_DIR:-/etc/qwen-tts-server}"
USER_NAME="${USER_NAME:-cbrew}"
SERVICE="${SERVICE:-qwen-tts-server}"

# 1. State + etc dirs
install -d -m 0755 -o "$USER_NAME" -g "$USER_NAME" "$STATE_DIR"
install -d -m 0755 -o "$USER_NAME" -g "$USER_NAME" "$STATE_DIR/jobs"
install -d -m 0750 -o root        -g "$USER_NAME" "$ETC_DIR"

# 2. Generate a token if none exists (caller can set QWEN_TTS_TOKEN to use one)
if [ ! -s "$ETC_DIR/token" ]; then
    if [ -n "${QWEN_TTS_TOKEN:-}" ]; then
        printf '%s' "$QWEN_TTS_TOKEN" > "$ETC_DIR/token"
    else
        head -c 48 /dev/urandom | base64 | tr -d '\n=' > "$ETC_DIR/token"
    fi
    chmod 0640 "$ETC_DIR/token"
    chown root:"$USER_NAME" "$ETC_DIR/token"
    echo "Generated new token at $ETC_DIR/token"
fi

# 3. Code rev pin
sudo -u "$USER_NAME" bash -c "cd '$REPO_DIR' && git rev-parse HEAD" > "$STATE_DIR/code_rev"
chown "$USER_NAME":"$USER_NAME" "$STATE_DIR/code_rev"

# 4. Systemd unit
install -m 0644 "$REPO_DIR/experiments/qwen_tts_server/qwen-tts-server.service" \
        "/etc/systemd/system/${SERVICE}.service"

systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl restart "$SERVICE"

# 5. Wait for healthy
sleep 2
systemctl is-active --quiet "$SERVICE" || { systemctl status "$SERVICE" --no-pager; exit 1; }
echo "OK: $SERVICE is active. Token at $ETC_DIR/token"
```

- [ ] **Step 4: Write the README**

Write `experiments/qwen_tts_server/README.md`:

```markdown
# qwen-tts-server

FastAPI service on pop-os.local that owns the GPU and runs Qwen3-TTS renders.
Replaces the long-lived ssh+python wrapper (`scripts/render_qwen_remote.sh`)
that broke whenever the ssh connection flapped.

## Endpoints

- `POST /render` — multipart upload of (manifest.json, phase3_episode.json,
  ref_source.mp3) + `run_id` form field. Idempotent by sha256 hash of the
  three input files + the renderer code rev. Returns the job record.
- `GET /jobs` — list jobs.
- `GET /jobs/{id}` — job status, progress, error.
- `GET /jobs/{id}/result/{name}` — `episode.wav`, `episode.json`, or
  `segment_NN.wav`.
- `GET /jobs/{id}/log` — captured render log.
- `DELETE /jobs/{id}` — cancel queued/running, or remove a finished record.

All endpoints require `Authorization: Bearer $TOKEN`.

## Deploy

```bash
# from a workstation:
rsync -a --delete --exclude=.venv --exclude=.git /local/repo/ cbrew@pop-os.local:/home/cbrew/bleakhouse-qwen-tts/
ssh cbrew@pop-os.local 'cd /home/cbrew/bleakhouse-qwen-tts && uv sync'
ssh cbrew@pop-os.local 'sudo bash /home/cbrew/bleakhouse-qwen-tts/experiments/qwen_tts_server/install.sh'
```

## Operate

```bash
ssh cbrew@pop-os.local 'sudo journalctl -u qwen-tts-server -f'
ssh cbrew@pop-os.local 'sudo systemctl restart qwen-tts-server'
ssh cbrew@pop-os.local 'sudo cat /etc/qwen-tts-server/token'
```
```

- [ ] **Step 5: Commit**

```bash
chmod +x experiments/qwen_tts_server/install.sh
git add experiments/qwen_tts_server/__main__.py \
        experiments/qwen_tts_server/qwen-tts-server.service \
        experiments/qwen_tts_server/install.sh \
        experiments/qwen_tts_server/README.md
git commit -m "feat(qwen-tts-server): CLI entrypoint, systemd unit, install script"
```

---

## Task 11: Local HTTP client (Python)

**Files:**
- Create: `scripts/render_qwen_via_http.py`

The client owns the user-facing flow:
1. Check inputs exist locally.
2. POST `/render` with multipart payload — server returns job id (or existing job id on idempotency hit).
3. Poll `/jobs/{id}` every 15 s, printing status changes. **No long-lived TCP** — every poll is a separate request, so wifi flaps don't matter.
4. On success, GET each result file (episode.wav, episode.json) and write into `data/runs/<run_id>/audio/`.
5. Convert wav→mp3 locally with ffmpeg.

- [ ] **Step 1: Write the client**

Write `scripts/render_qwen_via_http.py`:

```python
"""Thin HTTP client for the qwen-tts-server on pop-os.local.

Replaces the body of scripts/render_qwen_remote.sh. Ssh isn't held open;
each poll is a fresh request, so wifi/sleep blips can't kill a render.

Usage:
    uv run python scripts/render_qwen_via_http.py <run_id> [--ref-source PATH]
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx


DEFAULT_BASE_URL = os.environ.get("QWEN_TTS_BASE_URL", "http://pop-os.local:8765")
TOKEN_PATH = Path(os.environ.get("QWEN_TTS_TOKEN_FILE", str(Path.home() / ".config/qwen-tts/token")))
POLL_SECONDS = int(os.environ.get("QWEN_TTS_POLL", "15"))
RETRY_SECONDS = int(os.environ.get("QWEN_TTS_RETRY", "10"))
RETRY_ATTEMPTS = int(os.environ.get("QWEN_TTS_RETRY_ATTEMPTS", "30"))


def _load_token() -> str:
    env_token = os.environ.get("QWEN_TTS_TOKEN")
    if env_token:
        return env_token.strip()
    if not TOKEN_PATH.exists():
        sys.exit(f"FAIL: no token at {TOKEN_PATH} (or set QWEN_TTS_TOKEN env var)")
    return TOKEN_PATH.read_text().strip()


def _retrying_request(client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    last_err: Exception | None = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            r = client.request(method, url, **kwargs)
            if r.status_code >= 500:
                raise httpx.HTTPStatusError(f"{r.status_code}", request=r.request, response=r)
            return r
        except (httpx.HTTPError, httpx.TransportError) as exc:
            last_err = exc
            if attempt == RETRY_ATTEMPTS:
                break
            print(f"    {method} {url}: {exc} — retrying in {RETRY_SECONDS}s ({attempt}/{RETRY_ATTEMPTS})", flush=True)
            time.sleep(RETRY_SECONDS)
    raise SystemExit(f"FAIL: {method} {url} unrecoverable after {RETRY_ATTEMPTS} attempts: {last_err}")


def _resolve_ref_source(run_dir: Path, override: Path | None) -> Path:
    p = override or (run_dir / "audio" / "podcast.mp3")
    if not p.exists() and not p.is_symlink():
        sys.exit(f"FAIL: ref source {p} not found")
    return p.resolve()


def render(run_id: str, ref_source: Path | None, base_url: str) -> int:
    repo = Path(__file__).resolve().parent.parent
    run_dir = repo / "data" / "runs" / run_id
    if not run_dir.exists():
        sys.exit(f"FAIL: {run_dir} not found")
    manifest = run_dir / "manifest.json"
    phase3 = run_dir / "phase3_episode.json"
    if not manifest.exists():
        sys.exit(f"FAIL: {manifest} missing")
    if not phase3.exists():
        sys.exit(f"FAIL: {phase3} missing")
    ref_path = _resolve_ref_source(run_dir, ref_source)

    token = _load_token()
    headers = {"Authorization": f"Bearer {token}"}

    print(f"==> POST {base_url}/render  (run_id={run_id})")
    with httpx.Client(timeout=httpx.Timeout(60.0), headers=headers) as client:
        with manifest.open("rb") as mf, phase3.open("rb") as p3, ref_path.open("rb") as rf:
            files = [
                ("manifest", ("manifest.json", mf, "application/json")),
                ("phase3", ("phase3_episode.json", p3, "application/json")),
                ("ref_source", (ref_path.name, rf, "audio/mpeg")),
            ]
            r = _retrying_request(client, "POST", f"{base_url}/render",
                                  data={"run_id": run_id}, files=files)
        if r.status_code not in (200, 201):
            sys.exit(f"FAIL: render returned {r.status_code}: {r.text}")
        body = r.json()
        job_id = body["job"]["id"]
        existing = body["existing"]
        print(f"    job_id={job_id} existing={existing}")

        prev_status = None
        while True:
            r = _retrying_request(client, "GET", f"{base_url}/jobs/{job_id}")
            if r.status_code == 404:
                sys.exit(f"FAIL: job {job_id} disappeared")
            r.raise_for_status()
            j = r.json()
            if j["status"] != prev_status:
                print(f"    [{time.strftime('%H:%M:%S')}] status={j['status']}", flush=True)
                prev_status = j["status"]
            if j["status"] in ("succeeded", "failed", "cancelled"):
                break
            time.sleep(POLL_SECONDS)

        if j["status"] != "succeeded":
            log = _retrying_request(client, "GET", f"{base_url}/jobs/{job_id}/log").text
            print("--- server log ---", file=sys.stderr)
            print(log, file=sys.stderr)
            sys.exit(f"FAIL: job ended in status={j['status']}: {j.get('error') or '(no error)'}")

        audio_dir = run_dir / "audio"
        audio_dir.mkdir(exist_ok=True)
        wav_path = audio_dir / "podcast_qwen.wav"
        manifest_path = audio_dir / "manifest_qwen.json"

        print(f"==> GET episode.wav -> {wav_path}")
        with _retrying_request(client, "GET", f"{base_url}/jobs/{job_id}/result/episode.wav") as r:
            r.raise_for_status()
            wav_path.write_bytes(r.content)

        print(f"==> GET episode.json -> {manifest_path}")
        with _retrying_request(client, "GET", f"{base_url}/jobs/{job_id}/result/episode.json") as r:
            r.raise_for_status()
            manifest_path.write_bytes(r.content)

    mp3_path = audio_dir / "podcast_qwen.mp3"
    print(f"==> ffmpeg wav -> mp3 ({mp3_path})")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path),
         "-b:a", "192k", str(mp3_path)],
        check=True,
    )
    wav_path.unlink()
    print(f"SUCCESS: {run_id} -> {mp3_path}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--ref-source", type=Path, default=None)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    args = parser.parse_args()
    sys.exit(render(args.run_id, args.ref_source, args.base_url))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Replace the bash wrapper body**

Replace the contents of `scripts/render_qwen_remote.sh` (the long body that does ssh+rsync) with a thin shim. Keep the same usage signature so callers don't break:

```bash
#!/bin/bash
# Render a Qwen TTS episode via the qwen-tts-server REST API on pop-os.
#
# This script used to hold an ssh session open for the full ~2h render and
# broke on every wifi flap. It now delegates to the Python HTTP client which
# does discrete polled requests instead.
#
# Usage:
#   scripts/render_qwen_remote.sh <run_id> [--ref-source <path>]
#
# Env (optional):
#   QWEN_TTS_BASE_URL  default http://pop-os.local:8765
#   QWEN_TTS_TOKEN     direct token (otherwise read from ~/.config/qwen-tts/token)

set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run python scripts/render_qwen_via_http.py "$@"
```

- [ ] **Step 3: Smoke-test the client locally without a real server**

Run with a deliberately wrong base URL to confirm graceful failure:

```bash
QWEN_TTS_BASE_URL=http://127.0.0.1:1 \
QWEN_TTS_TOKEN=fake \
QWEN_TTS_RETRY_ATTEMPTS=1 \
uv run python scripts/render_qwen_via_http.py bh_trn_literary || true
```

Expected: prints a clear FAIL with the connection error, exits non-zero.

- [ ] **Step 4: Commit**

```bash
git add scripts/render_qwen_via_http.py scripts/render_qwen_remote.sh
git commit -m "feat(qwen-tts-server): local HTTP client + bash shim replacing ssh wrapper"
```

---

## Task 12: Deploy on pop-os and smoke-test against GPU

**Files:** none (deployment work)

- [ ] **Step 1: Verify pop-os is reachable**

```bash
ssh cbrew@pop-os.local 'echo connected && nvidia-smi -L && uname -a'
```

Expected: prints a CUDA GPU and the kernel banner. If this fails, stop and ask user to wake the box.

- [ ] **Step 2: Rsync repo to pop-os**

```bash
rsync -a --delete --exclude=.venv --exclude=.git --exclude='data/runs' \
      --exclude='reports' --exclude='.dvc' \
      ./ cbrew@pop-os.local:/home/cbrew/bleakhouse-qwen-tts/
```

- [ ] **Step 3: Sync deps on pop-os**

```bash
ssh cbrew@pop-os.local 'cd /home/cbrew/bleakhouse-qwen-tts && uv sync'
```

- [ ] **Step 4: Install the service**

```bash
ssh -t cbrew@pop-os.local 'sudo bash /home/cbrew/bleakhouse-qwen-tts/experiments/qwen_tts_server/install.sh'
```

Expected: `OK: qwen-tts-server is active`.

- [ ] **Step 5: Pull the token to the Mac**

```bash
mkdir -p ~/.config/qwen-tts
ssh cbrew@pop-os.local 'sudo cat /etc/qwen-tts-server/token' > ~/.config/qwen-tts/token
chmod 600 ~/.config/qwen-tts/token
```

- [ ] **Step 6: Hit /jobs from the Mac**

```bash
TOKEN=$(cat ~/.config/qwen-tts/token)
curl -sS -H "Authorization: Bearer $TOKEN" http://pop-os.local:8765/jobs
```

Expected: `{"jobs":[]}`.

- [ ] **Step 7: Drive a real render**

Pick a run that has manifest.json + phase3_episode.json + audio/podcast.mp3.
First check what's available:

```bash
ls data/runs/ | head
ls -la data/runs/bh_trn_literary/manifest.json data/runs/bh_trn_literary/phase3_episode.json data/runs/bh_trn_literary/audio/podcast.mp3
```

Then render via the new path:

```bash
bash scripts/render_qwen_remote.sh bh_trn_literary
```

Expected: prints job_id, polls through running, finishes with `SUCCESS: bh_trn_literary -> .../podcast_qwen.mp3`.

- [ ] **Step 8: Verify resilience to mid-render network blips**

While the render is running, briefly disable wifi (or run `sudo ifconfig en0 down; sleep 30; sudo ifconfig en0 up`). The client should print retry messages and then resume polling. The remote render keeps going regardless.

- [ ] **Step 9: Verify idempotency**

Re-run the same `bash scripts/render_qwen_remote.sh bh_trn_literary` after the first one finishes. Expected: client prints `existing=true` and skips straight to result download.

- [ ] **Step 10: Close the bd issue**

```bash
bd close BleakHouse-5dz BleakHouse-1ud --reason="Replaced ssh wrapper with REST service; 1ud subsumed."
```

Note: 1ud was a smaller version of the same fix (nohup wrapper). Closing both since this supersedes it.

- [ ] **Step 11: Commit + push**

```bash
git status
git push
```

---

## Out of scope (future work)

- TLS/HTTPS in front of the service. Today this is an internal-LAN service; the bearer token over plaintext is acceptable inside the home network. If we ever expose it over Tailscale/internet we add an nginx terminator or a Tailscale Funnel.
- Concurrent renders. Single-GPU box, single-job FIFO. If we ever get a second GPU, add a worker per device and a `device` column.
- Per-segment streaming (server-sent events). Polling is fine at 2h render times.
- Job retention sweep. Add a daily cron to prune `out/utterances/*.wav` for jobs older than 14 days; the issue talks about a known orphan-jobs problem this should fix in itself.
