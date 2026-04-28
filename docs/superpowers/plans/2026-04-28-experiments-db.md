# Experiments DB Migration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-run JSON-files-on-disk experiment ledger (`data/runs/<run_id>/run_manifest.json` × ~200 dirs) with a small SQLite-backed experiment database that explicitly represents episodes, scripts, generation runs, TTS configs, audio artefacts, evaluations, and regeneration requests as relational rows. Heavy artefacts (.wav, .mp3, .json scripts) stay on disk under DVC; the DB stores their paths + DVC hashes.

**Architecture:** `data/experiments.db` (SQLite, WAL mode). Pure stdlib `sqlite3` + frozen `@dataclass` row types — same pattern as `experiments/qwen_tts_server/state.py`. Schema versioned via `PRAGMA user_version`. Schema-and-CRUD module under `enrichment/expdb/`. Backfill walks the existing `data/runs/*/` and inserts rows idempotently. Read-only API for the webapp + a small `bd-style` CLI for inspecting the DB. **Production write paths (qwen-tts-server, pipeline) are out of scope here** — they get a follow-up plan once the read side is proven.

**Tech Stack:** Python 3.13 stdlib `sqlite3`, dataclasses, pytest. No SQLAlchemy, no Alembic, no SQLModel — the qwen-tts-server precedent showed this is enough at our scale. Pydantic only at the FastAPI boundary.

**Beads:** [BleakHouse-f6a](../../../).

---

## Schema

Seven tables. Foreign keys are `ON DELETE RESTRICT` by default (no cascading deletes — experiments are append-only history). All timestamps are `REAL` (`time.time()`).

```sql
-- The logical episode: a (novel, panel, pipeline-axes) tuple. Multiple
-- generation runs can produce different scripts for the same episode.
CREATE TABLE episode (
    id           INTEGER PRIMARY KEY,
    novel        TEXT NOT NULL,         -- "bh", "motf", "omf", ...
    panel        TEXT NOT NULL,         -- "literary", "alternatives", "interdisciplinary"
    pipeline     TEXT NOT NULL,         -- "trn", "emb", "nop", "rag"
    hostprep     INTEGER NOT NULL,      -- 0/1
    label        TEXT NOT NULL,         -- the run_id, e.g. "bh_trn_literary"
    created_at   REAL NOT NULL,
    UNIQUE(novel, panel, pipeline, hostprep)
);

-- One generated script. Produced by exactly one generation_run.
CREATE TABLE script_version (
    id              INTEGER PRIMARY KEY,
    episode_id      INTEGER NOT NULL REFERENCES episode(id),
    path            TEXT NOT NULL,           -- "data/runs/<rid>/phase3_episode.json"
    dvc_hash        TEXT,                    -- md5 from dvc.lock if available
    n_segments      INTEGER NOT NULL,
    n_turns         INTEGER NOT NULL,
    n_utterances    INTEGER NOT NULL,
    created_at      REAL NOT NULL
);

-- A single execution of a generation pipeline. Produces one script_version.
-- Captures git_commit + dvc_rev so we can reproduce.
CREATE TABLE generation_run (
    id                  INTEGER PRIMARY KEY,
    script_version_id   INTEGER NOT NULL REFERENCES script_version(id),
    generator           TEXT NOT NULL,       -- "anthropic_sonnet_4_6", "cerebras_qwen", ...
    git_commit          TEXT,
    dvc_rev             TEXT,                -- dvc_lock_sha from run_manifest
    config_json         TEXT,                -- whatever config.json had
    started_at          REAL,
    finished_at         REAL NOT NULL,
    UNIQUE(script_version_id, generator, git_commit)
);

-- A TTS configuration. References a designed voice ref version.
-- Many audio_artifacts can share a tts_config (same engine + voice = same config).
CREATE TABLE tts_config (
    id              INTEGER PRIMARY KEY,
    engine          TEXT NOT NULL,           -- "gemini-2.0-flash", "qwen3-tts-12hz", ...
    profile         TEXT,                    -- "classic", "trevelyan_v2", "qwen_designed_v1"
    voice_ref_ver   TEXT,                    -- "v1" — points at data/voice_refs/v1/
    config_json     TEXT NOT NULL,           -- engine-specific knobs as JSON
    created_at      REAL NOT NULL,
    UNIQUE(engine, profile, voice_ref_ver, config_json)
);

-- A rendered audio file. Path on disk + DVC hash + which (script, config) made it.
CREATE TABLE audio_artifact (
    id                  INTEGER PRIMARY KEY,
    script_version_id   INTEGER NOT NULL REFERENCES script_version(id),
    tts_config_id       INTEGER NOT NULL REFERENCES tts_config(id),
    name                TEXT NOT NULL,       -- "podcast.mp3", "podcast_qwen.mp3"
    path                TEXT NOT NULL,       -- relative to repo root
    dvc_hash            TEXT,                -- md5 from dvc.lock (or from sidecar)
    duration_s          REAL,                -- if known from manifest
    audio_manifest_path TEXT,                -- "data/runs/<rid>/audio/manifest.json"
    created_at          REAL NOT NULL,
    UNIQUE(script_version_id, tts_config_id, name)
);

-- Quality / verification measurements attached to a script or audio artefact.
-- metric_kind says what it is; metric_json carries the payload.
CREATE TABLE evaluation (
    id                  INTEGER PRIMARY KEY,
    script_version_id   INTEGER REFERENCES script_version(id),
    audio_artifact_id   INTEGER REFERENCES audio_artifact(id),
    metric_kind         TEXT NOT NULL,       -- "quote_verification", "asr_wer", "listener_mos"
    metric_json         TEXT NOT NULL,       -- e.g. {"verified": 42, "total": 42, "rate": 100.0}
    created_at          REAL NOT NULL,
    CHECK (script_version_id IS NOT NULL OR audio_artifact_id IS NOT NULL)
);

-- A request to redo a turn / segment / whole episode under a different
-- tts_config. Empty initially; populated by the future interactive UI.
CREATE TABLE regeneration_request (
    id                       INTEGER PRIMARY KEY,
    audio_artifact_id        INTEGER NOT NULL REFERENCES audio_artifact(id),
    new_tts_config_id        INTEGER NOT NULL REFERENCES tts_config(id),
    scope                    TEXT NOT NULL,   -- "turn:3:5", "segment:2", "episode"
    requested_at             REAL NOT NULL,
    fulfilled_audio_artifact INTEGER REFERENCES audio_artifact(id),
    fulfilled_at             REAL
);

CREATE INDEX idx_script_episode ON script_version(episode_id);
CREATE INDEX idx_run_script ON generation_run(script_version_id);
CREATE INDEX idx_audio_script ON audio_artifact(script_version_id);
CREATE INDEX idx_audio_config ON audio_artifact(tts_config_id);
CREATE INDEX idx_eval_script ON evaluation(script_version_id);
CREATE INDEX idx_eval_audio ON evaluation(audio_artifact_id);
```

---

## File structure

```
enrichment/expdb/
  __init__.py
  schema.sql                     -- DDL above
  models.py                      -- @dataclass row types
  store.py                       -- Store class — connect, init_schema, CRUD
  backfill.py                    -- scans data/runs/*/ → inserts rows
  cli.py                         -- python -m enrichment.expdb (list/show/scan)

tests/expdb/
  __init__.py
  conftest.py                    -- fixture: tmp DB
  test_models.py                 -- dataclass roundtrips
  test_store_episode.py
  test_store_script_run.py
  test_store_tts_audio.py
  test_store_evaluation.py
  test_backfill.py               -- against a stub run dir

data/experiments.db              -- gitignored; rebuild via `python -m enrichment.expdb scan`
```

`data/experiments.db` is gitignored — it's a derived index. The source of truth stays on disk under `data/runs/`. The DB is rebuilt by the scan command. (We can DVC-track it later if rebuild speed becomes a problem.)

---

## Out of scope (for this plan)

- Wiring `qwen-tts-server` to insert `audio_artifact` rows on render completion.
- Modifying the pipeline (`enrichment/run.py`, `enrichment/run_pipeline.py`) to write `generation_run` rows.
- Changing `webapp/run_tracker.py` to read from the DB instead of the filesystem.
- Deprecating `run_manifest.json` files.

These are follow-ups in a separate plan once Tasks 1–11 below are merged. The point of this plan is: **build the read-side foundation, populate it from existing data, prove the schema's correctness**, then layer integrations on top.

---

## Task 1: Package skeleton + dependencies + initial bd issue

**Files:**
- Create: `enrichment/expdb/__init__.py`
- Create: `tests/expdb/__init__.py`
- Create: `tests/expdb/conftest.py`

- [ ] **Step 1: File the bd issue and capture its ID at the top of the plan**

```bash
bd create \
  --title="Experiments DB migration: SQLite-backed experiment ledger" \
  --description="Replace per-run JSON manifests with a SQLite DB indexing episodes / scripts / generation runs / tts configs / audio artefacts / evaluations / regeneration requests. Heavy artefacts stay on disk under DVC; DB stores paths + DVC hashes. Plan: docs/superpowers/plans/2026-04-28-experiments-db.md" \
  --type=feature --priority=2
```

Note the resulting `BleakHouse-XXX` ID. Update line 9 of the plan ("Beads: [BleakHouse-?]") with the real ID.

- [ ] **Step 2: Create the package directories with placeholder docstrings**

Write `enrichment/expdb/__init__.py`:

```python
"""SQLite-backed experiment ledger.

See docs/superpowers/plans/2026-04-28-experiments-db.md.
"""
```

Write `tests/expdb/__init__.py` (empty file).

Write `tests/expdb/conftest.py`:

```python
"""Shared fixtures for expdb tests."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """A clean SQLite DB path under a per-test tmpdir."""
    return tmp_path / "experiments.db"
```

- [ ] **Step 3: Verify pytest discovers the new tests dir**

Run: `uv run pytest tests/expdb/ --collect-only 2>&1 | tail -5`
Expected: "no tests ran" or similar, but no collection errors.

- [ ] **Step 4: Commit**

```bash
git add enrichment/expdb/__init__.py tests/expdb/__init__.py tests/expdb/conftest.py docs/superpowers/plans/2026-04-28-experiments-db.md
git commit -m "expdb: package skeleton + plan"
```

---

## Task 2: Schema DDL + Store.init_schema()

**Files:**
- Create: `enrichment/expdb/schema.sql`
- Create: `enrichment/expdb/store.py`
- Create: `tests/expdb/test_store_init.py`

- [ ] **Step 1: Write the schema file**

Write `enrichment/expdb/schema.sql` — copy the SQL block from the "Schema" section of this plan verbatim (the seven CREATE TABLE statements + the six CREATE INDEX statements).

- [ ] **Step 2: Write the failing test**

Write `tests/expdb/test_store_init.py`:

```python
"""init_schema creates the seven tables and bumps user_version."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from enrichment.expdb.store import EXPECTED_USER_VERSION, Store


def test_init_schema_creates_seven_tables(tmp_db_path: Path) -> None:
    Store(tmp_db_path).init_schema()
    with sqlite3.connect(tmp_db_path) as c:
        rows = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    names = {r[0] for r in rows}
    assert {"episode", "script_version", "generation_run", "tts_config",
            "audio_artifact", "evaluation", "regeneration_request"} <= names


def test_init_schema_sets_user_version(tmp_db_path: Path) -> None:
    Store(tmp_db_path).init_schema()
    with sqlite3.connect(tmp_db_path) as c:
        v = c.execute("PRAGMA user_version").fetchone()[0]
    assert v == EXPECTED_USER_VERSION


def test_init_schema_is_idempotent(tmp_db_path: Path) -> None:
    s = Store(tmp_db_path)
    s.init_schema()
    s.init_schema()  # second call must not raise
    with sqlite3.connect(tmp_db_path) as c:
        n = c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    # 7 user tables (no sqlite_sequence since no INTEGER PRIMARY KEY AUTOINCREMENT used)
    assert n >= 7
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/expdb/test_store_init.py -v`
Expected: `ModuleNotFoundError: enrichment.expdb.store`.

- [ ] **Step 4: Implement Store with init_schema**

Write `enrichment/expdb/store.py`:

```python
"""Experiment ledger Store — SQLite, stdlib only."""
from __future__ import annotations

import sqlite3
from importlib.resources import files
from pathlib import Path

EXPECTED_USER_VERSION = 1


def _schema_sql() -> str:
    return (files("enrichment.expdb") / "schema.sql").read_text()


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        return c

    def init_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            current = c.execute("PRAGMA user_version").fetchone()[0]
            if current >= EXPECTED_USER_VERSION:
                return  # already initialised at this version or later
            c.executescript(_schema_sql())
            c.execute(f"PRAGMA user_version = {EXPECTED_USER_VERSION}")
```

- [ ] **Step 5: Verify schema.sql is included as package data**

Without explicit configuration `importlib.resources.files()` does not always find non-Python files. Add to `pyproject.toml`, in the `[tool.hatch.build.targets.wheel]` block (or wherever `packages` is set), a force-include for `*.sql`:

```toml
[tool.hatch.build.targets.wheel]
packages = ["enrichment", "webapp"]

[tool.hatch.build.targets.wheel.force-include]
"enrichment/expdb/schema.sql" = "enrichment/expdb/schema.sql"
```

If the project uses a different builder, the equivalent declaration goes in its config; check first by running the test in step 6 — if it fails with `FileNotFoundError`, the resource isn't being shipped.

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/expdb/test_store_init.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add enrichment/expdb/schema.sql enrichment/expdb/store.py tests/expdb/test_store_init.py pyproject.toml
git commit -m "expdb: schema DDL + Store.init_schema with user_version 1"
```

---

## Task 3: Episode CRUD

**Files:**
- Modify: `enrichment/expdb/store.py`
- Create: `enrichment/expdb/models.py`
- Create: `tests/expdb/test_store_episode.py`

- [ ] **Step 1: Write the failing test**

Write `tests/expdb/test_store_episode.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from enrichment.expdb.models import Episode
from enrichment.expdb.store import Store


@pytest.fixture
def store(tmp_db_path: Path) -> Store:
    s = Store(tmp_db_path)
    s.init_schema()
    return s


def test_upsert_episode_returns_id(store: Store) -> None:
    eid = store.upsert_episode(novel="bh", panel="literary", pipeline="trn",
                                hostprep=False, label="bh_trn_literary")
    assert eid >= 1


def test_upsert_episode_is_idempotent(store: Store) -> None:
    a = store.upsert_episode(novel="bh", panel="literary", pipeline="trn",
                              hostprep=False, label="bh_trn_literary")
    b = store.upsert_episode(novel="bh", panel="literary", pipeline="trn",
                              hostprep=False, label="bh_trn_literary")
    assert a == b


def test_get_episode_round_trips(store: Store) -> None:
    eid = store.upsert_episode(novel="bh", panel="literary", pipeline="trn",
                                hostprep=False, label="bh_trn_literary")
    ep = store.get_episode(eid)
    assert ep is not None
    assert ep.novel == "bh"
    assert ep.panel == "literary"
    assert ep.pipeline == "trn"
    assert ep.hostprep is False
    assert ep.label == "bh_trn_literary"


def test_list_episodes_filters_by_novel(store: Store) -> None:
    store.upsert_episode(novel="bh",   panel="literary",      pipeline="trn",
                          hostprep=False, label="bh_trn_literary")
    store.upsert_episode(novel="bh",   panel="alternatives",  pipeline="trn",
                          hostprep=False, label="bh_trn_alternatives")
    store.upsert_episode(novel="motf", panel="literary",      pipeline="trn",
                          hostprep=False, label="motf_trn_literary")
    bh = store.list_episodes(novel="bh")
    assert sorted(e.label for e in bh) == ["bh_trn_alternatives", "bh_trn_literary"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/expdb/test_store_episode.py -v`
Expected: `ModuleNotFoundError: enrichment.expdb.models`.

- [ ] **Step 3: Write the model + Store methods**

Write `enrichment/expdb/models.py`:

```python
"""Row dataclasses for the experiment ledger."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Episode:
    id: int
    novel: str
    panel: str
    pipeline: str
    hostprep: bool
    label: str
    created_at: float
```

Add to `enrichment/expdb/store.py` (after the class init):

```python
import time

from .models import Episode


# ---- inside class Store ----

    def upsert_episode(self, *, novel: str, panel: str, pipeline: str,
                       hostprep: bool, label: str) -> int:
        with self._conn() as c:
            row = c.execute(
                "SELECT id FROM episode WHERE novel=? AND panel=? AND pipeline=? AND hostprep=?",
                (novel, panel, pipeline, int(hostprep)),
            ).fetchone()
            if row is not None:
                return int(row["id"])
            cur = c.execute(
                "INSERT INTO episode(novel, panel, pipeline, hostprep, label, created_at) "
                "VALUES(?,?,?,?,?,?)",
                (novel, panel, pipeline, int(hostprep), label, time.time()),
            )
            return int(cur.lastrowid)

    def get_episode(self, episode_id: int) -> Episode | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM episode WHERE id=?", (episode_id,)).fetchone()
        return _row_to_episode(row) if row else None

    def list_episodes(self, *, novel: str | None = None) -> list[Episode]:
        sql = "SELECT * FROM episode"
        params: tuple = ()
        if novel is not None:
            sql += " WHERE novel=?"
            params = (novel,)
        sql += " ORDER BY id"
        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [_row_to_episode(r) for r in rows]


# ---- module-level helper ----

def _row_to_episode(row) -> Episode:
    return Episode(
        id=int(row["id"]),
        novel=row["novel"],
        panel=row["panel"],
        pipeline=row["pipeline"],
        hostprep=bool(row["hostprep"]),
        label=row["label"],
        created_at=float(row["created_at"]),
    )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/expdb/test_store_episode.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add enrichment/expdb/models.py enrichment/expdb/store.py tests/expdb/test_store_episode.py
git commit -m "expdb: Episode model + upsert_episode/get_episode/list_episodes"
```

---

## Task 4: ScriptVersion CRUD

**Files:**
- Modify: `enrichment/expdb/models.py`
- Modify: `enrichment/expdb/store.py`
- Create: `tests/expdb/test_store_script.py`

- [ ] **Step 1: Write the failing test**

Write `tests/expdb/test_store_script.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from enrichment.expdb.store import Store


@pytest.fixture
def store_with_episode(tmp_db_path: Path) -> tuple[Store, int]:
    s = Store(tmp_db_path)
    s.init_schema()
    eid = s.upsert_episode(novel="bh", panel="literary", pipeline="trn",
                            hostprep=False, label="bh_trn_literary")
    return s, eid


def test_create_script_returns_id(store_with_episode) -> None:
    s, eid = store_with_episode
    sid = s.create_script_version(
        episode_id=eid,
        path="data/runs/bh_trn_literary/phase3_episode.json",
        dvc_hash="0889681df9ebc4bb0f6ec85e9f53ef98",
        n_segments=7, n_turns=85, n_utterances=363,
    )
    assert sid >= 1


def test_get_script_round_trips(store_with_episode) -> None:
    s, eid = store_with_episode
    sid = s.create_script_version(
        episode_id=eid,
        path="x.json", dvc_hash=None,
        n_segments=1, n_turns=1, n_utterances=1,
    )
    sv = s.get_script_version(sid)
    assert sv is not None
    assert sv.episode_id == eid
    assert sv.path == "x.json"
    assert sv.dvc_hash is None
    assert sv.n_segments == 1


def test_list_scripts_for_episode(store_with_episode) -> None:
    s, eid = store_with_episode
    s.create_script_version(episode_id=eid, path="a.json", dvc_hash="h1",
                             n_segments=1, n_turns=1, n_utterances=1)
    s.create_script_version(episode_id=eid, path="b.json", dvc_hash="h2",
                             n_segments=2, n_turns=2, n_utterances=2)
    out = s.list_scripts_for_episode(eid)
    assert {sv.path for sv in out} == {"a.json", "b.json"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/expdb/test_store_script.py -v`
Expected: `AttributeError` on `create_script_version`.

- [ ] **Step 3: Add the model + Store methods**

In `enrichment/expdb/models.py`, append:

```python
@dataclass(frozen=True)
class ScriptVersion:
    id: int
    episode_id: int
    path: str
    dvc_hash: str | None
    n_segments: int
    n_turns: int
    n_utterances: int
    created_at: float
```

In `enrichment/expdb/store.py`, import `ScriptVersion` and add to the class:

```python
    def create_script_version(self, *, episode_id: int, path: str,
                              dvc_hash: str | None, n_segments: int,
                              n_turns: int, n_utterances: int) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO script_version"
                "(episode_id, path, dvc_hash, n_segments, n_turns, n_utterances, created_at)"
                " VALUES(?,?,?,?,?,?,?)",
                (episode_id, path, dvc_hash, n_segments, n_turns, n_utterances, time.time()),
            )
            return int(cur.lastrowid)

    def get_script_version(self, sid: int) -> ScriptVersion | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM script_version WHERE id=?", (sid,)).fetchone()
        return _row_to_script(row) if row else None

    def list_scripts_for_episode(self, episode_id: int) -> list[ScriptVersion]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM script_version WHERE episode_id=? ORDER BY id",
                (episode_id,),
            ).fetchall()
        return [_row_to_script(r) for r in rows]
```

Add the helper at module level:

```python
def _row_to_script(row) -> ScriptVersion:
    return ScriptVersion(
        id=int(row["id"]),
        episode_id=int(row["episode_id"]),
        path=row["path"],
        dvc_hash=row["dvc_hash"],
        n_segments=int(row["n_segments"]),
        n_turns=int(row["n_turns"]),
        n_utterances=int(row["n_utterances"]),
        created_at=float(row["created_at"]),
    )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/expdb/test_store_script.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add enrichment/expdb/models.py enrichment/expdb/store.py tests/expdb/test_store_script.py
git commit -m "expdb: ScriptVersion model + CRUD"
```

---

## Task 5: GenerationRun CRUD

**Files:**
- Modify: `enrichment/expdb/models.py`
- Modify: `enrichment/expdb/store.py`
- Create: `tests/expdb/test_store_run.py`

- [ ] **Step 1: Write the failing test**

Write `tests/expdb/test_store_run.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from enrichment.expdb.store import Store


@pytest.fixture
def store_with_script(tmp_db_path: Path) -> tuple[Store, int]:
    s = Store(tmp_db_path)
    s.init_schema()
    eid = s.upsert_episode(novel="bh", panel="literary", pipeline="trn",
                            hostprep=False, label="bh_trn_literary")
    sid = s.create_script_version(episode_id=eid, path="x.json", dvc_hash="h",
                                    n_segments=1, n_turns=1, n_utterances=1)
    return s, sid


def test_create_run_returns_id(store_with_script) -> None:
    s, sid = store_with_script
    rid = s.create_generation_run(
        script_version_id=sid,
        generator="anthropic_sonnet_4_6",
        git_commit="abc123",
        dvc_rev="def456",
        config={"temperature": 0.7},
        finished_at=1700000000.0,
    )
    assert rid >= 1


def test_get_run_returns_parsed_config(store_with_script) -> None:
    s, sid = store_with_script
    rid = s.create_generation_run(
        script_version_id=sid, generator="cerebras_qwen",
        git_commit=None, dvc_rev=None,
        config={"model": "qwen-3-235b"},
        finished_at=1700000000.0,
    )
    run = s.get_generation_run(rid)
    assert run is not None
    assert run.generator == "cerebras_qwen"
    assert run.config == {"model": "qwen-3-235b"}


def test_list_runs_for_script(store_with_script) -> None:
    s, sid = store_with_script
    s.create_generation_run(script_version_id=sid, generator="g1",
                              git_commit="c1", dvc_rev=None, config={},
                              finished_at=1700000000.0)
    s.create_generation_run(script_version_id=sid, generator="g2",
                              git_commit="c2", dvc_rev=None, config={},
                              finished_at=1700000001.0)
    out = s.list_runs_for_script(sid)
    assert {r.generator for r in out} == {"g1", "g2"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/expdb/test_store_run.py -v`
Expected: `AttributeError` on `create_generation_run`.

- [ ] **Step 3: Add the model + Store methods**

In `enrichment/expdb/models.py`, append:

```python
from typing import Any


@dataclass(frozen=True)
class GenerationRun:
    id: int
    script_version_id: int
    generator: str
    git_commit: str | None
    dvc_rev: str | None
    config: dict[str, Any]
    started_at: float | None
    finished_at: float
```

In `enrichment/expdb/store.py`, import `GenerationRun` and add to the class:

```python
    def create_generation_run(self, *, script_version_id: int, generator: str,
                              git_commit: str | None, dvc_rev: str | None,
                              config: dict, finished_at: float,
                              started_at: float | None = None) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO generation_run"
                "(script_version_id, generator, git_commit, dvc_rev, config_json,"
                " started_at, finished_at) VALUES(?,?,?,?,?,?,?)",
                (script_version_id, generator, git_commit, dvc_rev,
                 json.dumps(config), started_at, finished_at),
            )
            return int(cur.lastrowid)

    def get_generation_run(self, rid: int) -> GenerationRun | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM generation_run WHERE id=?", (rid,)).fetchone()
        return _row_to_run(row) if row else None

    def list_runs_for_script(self, script_version_id: int) -> list[GenerationRun]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM generation_run WHERE script_version_id=? ORDER BY id",
                (script_version_id,),
            ).fetchall()
        return [_row_to_run(r) for r in rows]
```

Add at the top of `store.py`:

```python
import json
```

Add helper at module level:

```python
def _row_to_run(row) -> GenerationRun:
    return GenerationRun(
        id=int(row["id"]),
        script_version_id=int(row["script_version_id"]),
        generator=row["generator"],
        git_commit=row["git_commit"],
        dvc_rev=row["dvc_rev"],
        config=json.loads(row["config_json"] or "{}"),
        started_at=float(row["started_at"]) if row["started_at"] is not None else None,
        finished_at=float(row["finished_at"]),
    )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/expdb/test_store_run.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add enrichment/expdb/models.py enrichment/expdb/store.py tests/expdb/test_store_run.py
git commit -m "expdb: GenerationRun model + CRUD"
```

---

## Task 6: TTSConfig + AudioArtifact CRUD

**Files:**
- Modify: `enrichment/expdb/models.py`
- Modify: `enrichment/expdb/store.py`
- Create: `tests/expdb/test_store_audio.py`

- [ ] **Step 1: Write the failing test**

Write `tests/expdb/test_store_audio.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from enrichment.expdb.store import Store


@pytest.fixture
def fixture(tmp_db_path: Path) -> tuple[Store, int]:
    s = Store(tmp_db_path)
    s.init_schema()
    eid = s.upsert_episode(novel="bh", panel="literary", pipeline="trn",
                            hostprep=False, label="bh_trn_literary")
    sid = s.create_script_version(episode_id=eid, path="x.json", dvc_hash="h",
                                    n_segments=1, n_turns=1, n_utterances=1)
    return s, sid


def test_upsert_tts_config_dedupes(fixture) -> None:
    s, _ = fixture
    a = s.upsert_tts_config(engine="qwen3-tts-12hz", profile="qwen_designed_v1",
                             voice_ref_ver="v1", config={"x_vector_only": True})
    b = s.upsert_tts_config(engine="qwen3-tts-12hz", profile="qwen_designed_v1",
                             voice_ref_ver="v1", config={"x_vector_only": True})
    assert a == b


def test_create_audio_artifact_records_path_and_hash(fixture) -> None:
    s, sid = fixture
    cfg_id = s.upsert_tts_config(engine="gemini-2.0-flash", profile="classic",
                                  voice_ref_ver=None, config={})
    aid = s.create_audio_artifact(
        script_version_id=sid, tts_config_id=cfg_id,
        name="podcast.mp3",
        path="data/runs/bh_trn_literary/audio/podcast.mp3",
        dvc_hash="ea0b3082baa072eed50612e8fcd68fd8",
        duration_s=2606.0,
        audio_manifest_path="data/runs/bh_trn_literary/audio/manifest.json",
    )
    a = s.get_audio_artifact(aid)
    assert a is not None
    assert a.dvc_hash == "ea0b3082baa072eed50612e8fcd68fd8"
    assert a.duration_s == 2606.0


def test_list_audio_for_script_returns_all_variants(fixture) -> None:
    s, sid = fixture
    classic = s.upsert_tts_config(engine="gemini-2.0-flash", profile="classic",
                                   voice_ref_ver=None, config={})
    qwen   = s.upsert_tts_config(engine="qwen3-tts-12hz", profile="qwen_designed_v1",
                                  voice_ref_ver="v1", config={})
    s.create_audio_artifact(script_version_id=sid, tts_config_id=classic,
                              name="podcast.mp3", path="a.mp3", dvc_hash=None)
    s.create_audio_artifact(script_version_id=sid, tts_config_id=qwen,
                              name="podcast_qwen.mp3", path="b.mp3", dvc_hash=None)
    out = s.list_audio_for_script(sid)
    assert {a.name for a in out} == {"podcast.mp3", "podcast_qwen.mp3"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/expdb/test_store_audio.py -v`
Expected: `AttributeError` on `upsert_tts_config`.

- [ ] **Step 3: Add the models + Store methods**

In `enrichment/expdb/models.py`, append:

```python
@dataclass(frozen=True)
class TTSConfig:
    id: int
    engine: str
    profile: str | None
    voice_ref_ver: str | None
    config: dict[str, Any]
    created_at: float


@dataclass(frozen=True)
class AudioArtifact:
    id: int
    script_version_id: int
    tts_config_id: int
    name: str
    path: str
    dvc_hash: str | None
    duration_s: float | None
    audio_manifest_path: str | None
    created_at: float
```

In `enrichment/expdb/store.py`, import the new models and add:

```python
    def upsert_tts_config(self, *, engine: str, profile: str | None,
                           voice_ref_ver: str | None, config: dict) -> int:
        cfg_json = json.dumps(config, sort_keys=True)
        with self._conn() as c:
            row = c.execute(
                "SELECT id FROM tts_config WHERE engine=? AND "
                "COALESCE(profile,'')=COALESCE(?,'') AND "
                "COALESCE(voice_ref_ver,'')=COALESCE(?,'') AND "
                "config_json=?",
                (engine, profile, voice_ref_ver, cfg_json),
            ).fetchone()
            if row is not None:
                return int(row["id"])
            cur = c.execute(
                "INSERT INTO tts_config(engine, profile, voice_ref_ver, config_json, created_at) "
                "VALUES(?,?,?,?,?)",
                (engine, profile, voice_ref_ver, cfg_json, time.time()),
            )
            return int(cur.lastrowid)

    def create_audio_artifact(self, *, script_version_id: int, tts_config_id: int,
                               name: str, path: str, dvc_hash: str | None,
                               duration_s: float | None = None,
                               audio_manifest_path: str | None = None) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO audio_artifact"
                "(script_version_id, tts_config_id, name, path, dvc_hash, "
                " duration_s, audio_manifest_path, created_at)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (script_version_id, tts_config_id, name, path, dvc_hash,
                 duration_s, audio_manifest_path, time.time()),
            )
            return int(cur.lastrowid)

    def get_audio_artifact(self, aid: int) -> AudioArtifact | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM audio_artifact WHERE id=?", (aid,)).fetchone()
        return _row_to_audio(row) if row else None

    def list_audio_for_script(self, script_version_id: int) -> list[AudioArtifact]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM audio_artifact WHERE script_version_id=? ORDER BY id",
                (script_version_id,),
            ).fetchall()
        return [_row_to_audio(r) for r in rows]
```

Add helpers at module level:

```python
def _row_to_audio(row) -> AudioArtifact:
    return AudioArtifact(
        id=int(row["id"]),
        script_version_id=int(row["script_version_id"]),
        tts_config_id=int(row["tts_config_id"]),
        name=row["name"],
        path=row["path"],
        dvc_hash=row["dvc_hash"],
        duration_s=float(row["duration_s"]) if row["duration_s"] is not None else None,
        audio_manifest_path=row["audio_manifest_path"],
        created_at=float(row["created_at"]),
    )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/expdb/test_store_audio.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add enrichment/expdb/models.py enrichment/expdb/store.py tests/expdb/test_store_audio.py
git commit -m "expdb: TTSConfig + AudioArtifact models + CRUD"
```

---

## Task 7: Evaluation + RegenerationRequest CRUD

**Files:**
- Modify: `enrichment/expdb/models.py`
- Modify: `enrichment/expdb/store.py`
- Create: `tests/expdb/test_store_eval.py`

- [ ] **Step 1: Write the failing test**

Write `tests/expdb/test_store_eval.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from enrichment.expdb.store import Store


@pytest.fixture
def populated(tmp_db_path: Path):
    s = Store(tmp_db_path)
    s.init_schema()
    eid = s.upsert_episode(novel="bh", panel="literary", pipeline="trn",
                            hostprep=False, label="bh_trn_literary")
    sid = s.create_script_version(episode_id=eid, path="x.json", dvc_hash="h",
                                    n_segments=1, n_turns=1, n_utterances=1)
    cfg = s.upsert_tts_config(engine="g", profile="p", voice_ref_ver=None, config={})
    aid = s.create_audio_artifact(script_version_id=sid, tts_config_id=cfg,
                                    name="p.mp3", path="p.mp3", dvc_hash=None)
    return s, sid, cfg, aid


def test_record_evaluation_against_script(populated) -> None:
    s, sid, _, _ = populated
    s.record_evaluation(script_version_id=sid, audio_artifact_id=None,
                         metric_kind="quote_verification",
                         metric={"verified": 42, "total": 42, "rate": 100.0})
    out = s.list_evaluations_for_script(sid)
    assert len(out) == 1
    assert out[0].metric_kind == "quote_verification"
    assert out[0].metric == {"verified": 42, "total": 42, "rate": 100.0}


def test_record_evaluation_against_audio(populated) -> None:
    s, _, _, aid = populated
    s.record_evaluation(script_version_id=None, audio_artifact_id=aid,
                         metric_kind="asr_wer",
                         metric={"wer": 0.083})
    out = s.list_evaluations_for_audio(aid)
    assert len(out) == 1
    assert out[0].metric == {"wer": 0.083}


def test_create_regeneration_request(populated) -> None:
    s, _, cfg, aid = populated
    new_cfg = s.upsert_tts_config(engine="g2", profile="p2",
                                    voice_ref_ver=None, config={})
    rid = s.create_regeneration_request(
        audio_artifact_id=aid, new_tts_config_id=new_cfg,
        scope="turn:3:5",
    )
    rr = s.get_regeneration_request(rid)
    assert rr is not None
    assert rr.audio_artifact_id == aid
    assert rr.new_tts_config_id == new_cfg
    assert rr.scope == "turn:3:5"
    assert rr.fulfilled_audio_artifact is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/expdb/test_store_eval.py -v`
Expected: `AttributeError`.

- [ ] **Step 3: Add the models + Store methods**

In `enrichment/expdb/models.py`, append:

```python
@dataclass(frozen=True)
class Evaluation:
    id: int
    script_version_id: int | None
    audio_artifact_id: int | None
    metric_kind: str
    metric: dict[str, Any]
    created_at: float


@dataclass(frozen=True)
class RegenerationRequest:
    id: int
    audio_artifact_id: int
    new_tts_config_id: int
    scope: str
    requested_at: float
    fulfilled_audio_artifact: int | None
    fulfilled_at: float | None
```

In `enrichment/expdb/store.py`, add:

```python
    def record_evaluation(self, *, script_version_id: int | None,
                           audio_artifact_id: int | None,
                           metric_kind: str, metric: dict) -> int:
        if script_version_id is None and audio_artifact_id is None:
            raise ValueError("evaluation must reference a script or an audio artefact")
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO evaluation"
                "(script_version_id, audio_artifact_id, metric_kind, metric_json, created_at)"
                " VALUES(?,?,?,?,?)",
                (script_version_id, audio_artifact_id, metric_kind,
                 json.dumps(metric), time.time()),
            )
            return int(cur.lastrowid)

    def list_evaluations_for_script(self, sid: int) -> list[Evaluation]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM evaluation WHERE script_version_id=? ORDER BY id",
                (sid,),
            ).fetchall()
        return [_row_to_eval(r) for r in rows]

    def list_evaluations_for_audio(self, aid: int) -> list[Evaluation]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM evaluation WHERE audio_artifact_id=? ORDER BY id",
                (aid,),
            ).fetchall()
        return [_row_to_eval(r) for r in rows]

    def create_regeneration_request(self, *, audio_artifact_id: int,
                                      new_tts_config_id: int, scope: str) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO regeneration_request"
                "(audio_artifact_id, new_tts_config_id, scope, requested_at)"
                " VALUES(?,?,?,?)",
                (audio_artifact_id, new_tts_config_id, scope, time.time()),
            )
            return int(cur.lastrowid)

    def get_regeneration_request(self, rid: int) -> RegenerationRequest | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM regeneration_request WHERE id=?",
                            (rid,)).fetchone()
        return _row_to_regen(row) if row else None
```

Helpers at module level:

```python
def _row_to_eval(row) -> Evaluation:
    return Evaluation(
        id=int(row["id"]),
        script_version_id=int(row["script_version_id"]) if row["script_version_id"] is not None else None,
        audio_artifact_id=int(row["audio_artifact_id"]) if row["audio_artifact_id"] is not None else None,
        metric_kind=row["metric_kind"],
        metric=json.loads(row["metric_json"]),
        created_at=float(row["created_at"]),
    )


def _row_to_regen(row) -> RegenerationRequest:
    return RegenerationRequest(
        id=int(row["id"]),
        audio_artifact_id=int(row["audio_artifact_id"]),
        new_tts_config_id=int(row["new_tts_config_id"]),
        scope=row["scope"],
        requested_at=float(row["requested_at"]),
        fulfilled_audio_artifact=int(row["fulfilled_audio_artifact"]) if row["fulfilled_audio_artifact"] is not None else None,
        fulfilled_at=float(row["fulfilled_at"]) if row["fulfilled_at"] is not None else None,
    )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/expdb/test_store_eval.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add enrichment/expdb/models.py enrichment/expdb/store.py tests/expdb/test_store_eval.py
git commit -m "expdb: Evaluation + RegenerationRequest models + CRUD"
```

---

## Task 8: Backfill scanner (single run)

**Files:**
- Create: `enrichment/expdb/backfill.py`
- Create: `tests/expdb/test_backfill.py`

The scanner reads one `data/runs/<run_id>/` directory and inserts the corresponding episode, script_version, generation_run, audio_artifacts, and evaluation rows. Idempotent — re-running on the same dir produces no duplicates.

Per-run inputs the scanner reads:

| File | Used for |
|---|---|
| `run_manifest.json` | `axes` → episode columns; `stages.phase4_audio.engine` → tts_config; `stages.quote_verification` → evaluation; `audio_variants` → audio_artifact rows; `dvc_lock_sha` → generation_run.dvc_rev |
| `phase3_episode.json` | `n_segments`, `n_turns`, `n_utterances`, path |
| `audio/manifest_qwen.json` if present | duration_s for any qwen-rendered audio_artifact |

- [ ] **Step 1: Write the failing test**

Write `tests/expdb/test_backfill.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from enrichment.expdb.backfill import scan_run_dir
from enrichment.expdb.store import Store


def _make_run_dir(tmp: Path) -> Path:
    rd = tmp / "bh_trn_literary"
    (rd / "audio").mkdir(parents=True)
    (rd / "run_manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "run_id": "bh_trn_literary",
        "axes": {"novel": "bh", "pipeline": "trn", "panel": "literary",
                  "hostprep": False, "generator": "anthropic_sonnet_4_6"},
        "stages": {
            "phase3": {"hash": "abc"},
            "quote_verification": {"verified": 42, "total": 42, "rate": 100.0},
            "phase4_audio": {
                "engine": "gemini-2.0-flash-preview-tts",
                "hash": "ea0b3082baa072eed50612e8fcd68fd8",
                "audio_file": "data/runs/bh_trn_literary/audio/podcast.mp3",
                "audio_manifest": "data/runs/bh_trn_literary/audio/manifest.json",
            },
        },
        "audio_variants": [{
            "name": "classic",
            "engine": "gemini-2.0-flash-preview-tts",
            "stage": "phase4_audio",
            "hash": "ea0b3082baa072eed50612e8fcd68fd8",
            "audio_file": "data/runs/bh_trn_literary/audio/podcast.mp3",
            "audio_manifest": "data/runs/bh_trn_literary/audio/manifest.json",
        }],
        "generated_at": "2026-04-25T10:00:00Z",
        "dvc_lock_sha": "deadbeef",
    }))
    (rd / "phase3_episode.json").write_text(json.dumps({
        "title": "BH literary",
        "segments": [
            {"turns": [
                {"speaker": "Host", "utterances": [{"text": "hi"}, {"text": "yes"}]},
                {"speaker": "James Blackstone", "utterances": [{"text": "indeed"}]},
            ]},
        ],
    }))
    return rd


def test_scan_creates_episode_script_run_audio_eval(tmp_path: Path, tmp_db_path: Path) -> None:
    rd = _make_run_dir(tmp_path)
    s = Store(tmp_db_path)
    s.init_schema()

    out = scan_run_dir(s, rd)

    assert out["episode_id"] is not None
    assert out["script_version_id"] is not None
    assert out["generation_run_id"] is not None
    assert len(out["audio_artifact_ids"]) == 1
    assert out["evaluation_ids"]  # quote_verification recorded

    sv = s.get_script_version(out["script_version_id"])
    assert sv is not None
    assert sv.n_segments == 1
    assert sv.n_turns == 2
    assert sv.n_utterances == 3


def test_scan_is_idempotent(tmp_path: Path, tmp_db_path: Path) -> None:
    rd = _make_run_dir(tmp_path)
    s = Store(tmp_db_path)
    s.init_schema()
    a = scan_run_dir(s, rd)
    b = scan_run_dir(s, rd)
    assert a == b  # same row IDs on re-scan
    eps = s.list_episodes(novel="bh")
    assert len(eps) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/expdb/test_backfill.py -v`
Expected: `ModuleNotFoundError` on `enrichment.expdb.backfill`.

- [ ] **Step 3: Implement the scanner**

Write `enrichment/expdb/backfill.py`:

```python
"""Walk data/runs/<run_id>/ dirs and populate the experiment ledger."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .store import Store


def _count_script(phase3: dict) -> tuple[int, int, int]:
    segments = phase3.get("segments", [])
    n_seg = len(segments)
    n_turns = sum(len(s.get("turns", [])) for s in segments)
    n_utt = sum(
        len(t.get("utterances", []))
        for s in segments for t in s.get("turns", [])
    )
    return n_seg, n_turns, n_utt


def scan_run_dir(store: Store, run_dir: Path) -> dict[str, Any]:
    """Idempotently insert rows for one run dir. Returns the resulting row IDs."""
    run_manifest_path = run_dir / "run_manifest.json"
    phase3_path = run_dir / "phase3_episode.json"
    if not run_manifest_path.exists():
        raise FileNotFoundError(run_manifest_path)
    if not phase3_path.exists():
        raise FileNotFoundError(phase3_path)

    rm = json.loads(run_manifest_path.read_text())
    phase3 = json.loads(phase3_path.read_text())

    axes = rm["axes"]
    label = rm.get("run_id", run_dir.name)

    episode_id = store.upsert_episode(
        novel=axes["novel"], panel=axes["panel"], pipeline=axes["pipeline"],
        hostprep=bool(axes.get("hostprep", False)), label=label,
    )

    # Idempotent script_version: keyed by (episode_id, path).
    n_seg, n_turns, n_utt = _count_script(phase3)
    script_path = str(phase3_path.relative_to(run_dir.parent.parent.parent)) \
        if (run_dir.parent.parent.parent / "data").exists() else str(phase3_path)
    # ^ best-effort relativisation; falls back to absolute if we can't find the repo root.
    existing = [s for s in store.list_scripts_for_episode(episode_id) if s.path == script_path]
    if existing:
        sid = existing[0].id
    else:
        sid = store.create_script_version(
            episode_id=episode_id, path=script_path,
            dvc_hash=rm.get("stages", {}).get("phase3", {}).get("hash"),
            n_segments=n_seg, n_turns=n_turns, n_utterances=n_utt,
        )

    # Idempotent generation_run: keyed by (script_version_id, generator, git_commit).
    generator = axes.get("generator", "unknown")
    dvc_rev = rm.get("dvc_lock_sha")
    existing_runs = store.list_runs_for_script(sid)
    matching = [r for r in existing_runs if r.generator == generator and r.dvc_rev == dvc_rev]
    if matching:
        run_id = matching[0].id
    else:
        run_id = store.create_generation_run(
            script_version_id=sid, generator=generator,
            git_commit=None, dvc_rev=dvc_rev, config={},
            finished_at=_parse_ts(rm.get("generated_at")),
        )

    # Audio variants → tts_config + audio_artifact rows.
    audio_ids: list[int] = []
    existing_audio = {a.name: a for a in store.list_audio_for_script(sid)}
    for variant in rm.get("audio_variants", []):
        engine = variant.get("engine", "unknown")
        profile = variant.get("name")  # "classic", "trevelyan_v2", ...
        cfg_id = store.upsert_tts_config(
            engine=engine, profile=profile, voice_ref_ver=None, config={},
        )
        manifest_rel = variant.get("audio_manifest")
        duration_s = _read_audio_duration(run_dir, manifest_rel) if manifest_rel else None
        # name = filename portion of audio_file, or "podcast" + variant tag.
        audio_file = variant.get("audio_file") or ""
        name = Path(audio_file).name or f"podcast_{profile or 'default'}.mp3"
        if name in existing_audio:
            audio_ids.append(existing_audio[name].id)
            continue
        aid = store.create_audio_artifact(
            script_version_id=sid, tts_config_id=cfg_id, name=name,
            path=audio_file, dvc_hash=variant.get("hash"),
            duration_s=duration_s, audio_manifest_path=manifest_rel,
        )
        audio_ids.append(aid)

    # Evaluations: quote_verification, if present.
    eval_ids: list[int] = []
    qv = rm.get("stages", {}).get("quote_verification")
    if qv and "verified" in qv:
        existing_evals = store.list_evaluations_for_script(sid)
        if not any(e.metric_kind == "quote_verification" for e in existing_evals):
            eval_ids.append(store.record_evaluation(
                script_version_id=sid, audio_artifact_id=None,
                metric_kind="quote_verification",
                metric={"verified": qv["verified"], "total": qv["total"],
                        "rate": qv.get("rate")},
            ))

    return {
        "episode_id": episode_id,
        "script_version_id": sid,
        "generation_run_id": run_id,
        "audio_artifact_ids": audio_ids,
        "evaluation_ids": eval_ids,
    }


def _read_audio_duration(run_dir: Path, manifest_rel: str | None) -> float | None:
    if not manifest_rel:
        return None
    candidate = run_dir / Path(manifest_rel).name  # try relative-to-run first
    if not candidate.exists():
        candidate = Path(manifest_rel)  # absolute / repo-relative
    if not candidate.exists():
        return None
    try:
        m = json.loads(candidate.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return m.get("episode_audio_seconds") or m.get("total_duration_s")


def _parse_ts(iso: str | None) -> float:
    import time
    if not iso:
        return time.time()
    try:
        from datetime import datetime
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return time.time()
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/expdb/test_backfill.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add enrichment/expdb/backfill.py tests/expdb/test_backfill.py
git commit -m "expdb: idempotent single-run backfill scanner"
```

---

## Task 9: Bulk backfill across data/runs/

**Files:**
- Modify: `enrichment/expdb/backfill.py`
- Create: `tests/expdb/test_backfill_bulk.py`

- [ ] **Step 1: Write the failing test**

Write `tests/expdb/test_backfill_bulk.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from enrichment.expdb.backfill import scan_runs_dir
from enrichment.expdb.store import Store


def _make_run(parent: Path, label: str, novel: str, panel: str) -> None:
    rd = parent / label
    (rd / "audio").mkdir(parents=True)
    (rd / "run_manifest.json").write_text(json.dumps({
        "schema_version": 1, "run_id": label,
        "axes": {"novel": novel, "pipeline": "trn", "panel": panel,
                  "hostprep": False, "generator": "anthropic_sonnet_4_6"},
        "stages": {}, "audio_variants": [],
        "generated_at": "2026-04-25T10:00:00Z", "dvc_lock_sha": "x",
    }))
    (rd / "phase3_episode.json").write_text(json.dumps({"segments": []}))


def test_scan_runs_dir_processes_all(tmp_path: Path, tmp_db_path: Path) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    _make_run(runs, "bh_trn_literary",     "bh",   "literary")
    _make_run(runs, "bh_trn_alternatives", "bh",   "alternatives")
    _make_run(runs, "motf_trn_literary",   "motf", "literary")

    s = Store(tmp_db_path)
    s.init_schema()
    summary = scan_runs_dir(s, runs)

    assert summary["scanned"] == 3
    assert summary["episodes_inserted"] == 3
    assert summary["scripts_inserted"] == 3
    assert summary["errors"] == []


def test_scan_runs_dir_skips_dirs_missing_required_files(tmp_path: Path, tmp_db_path: Path) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    _make_run(runs, "ok_run", "bh", "literary")
    (runs / "broken").mkdir()
    # No manifests inside broken/.

    s = Store(tmp_db_path)
    s.init_schema()
    summary = scan_runs_dir(s, runs)

    assert summary["scanned"] == 1
    assert summary["skipped"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/expdb/test_backfill_bulk.py -v`
Expected: `AttributeError` / `ImportError` on `scan_runs_dir`.

- [ ] **Step 3: Add the bulk function**

In `enrichment/expdb/backfill.py`, append:

```python
def scan_runs_dir(store: Store, runs_dir: Path) -> dict[str, Any]:
    """Walk runs_dir/* and scan each subdir that has the required files."""
    scanned = 0
    skipped = 0
    errors: list[dict[str, str]] = []
    eps_before = len(store.list_episodes())
    scripts_before = sum(
        len(store.list_scripts_for_episode(e.id)) for e in store.list_episodes()
    )

    for entry in sorted(runs_dir.iterdir()):
        if not entry.is_dir():
            continue
        if not (entry / "run_manifest.json").exists() or not (entry / "phase3_episode.json").exists():
            skipped += 1
            continue
        try:
            scan_run_dir(store, entry)
            scanned += 1
        except Exception as exc:
            errors.append({"run_dir": str(entry), "error": str(exc)})

    eps_after = len(store.list_episodes())
    scripts_after = sum(
        len(store.list_scripts_for_episode(e.id)) for e in store.list_episodes()
    )
    return {
        "scanned": scanned,
        "skipped": skipped,
        "episodes_inserted": eps_after - eps_before,
        "scripts_inserted": scripts_after - scripts_before,
        "errors": errors,
    }
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/expdb/test_backfill_bulk.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add enrichment/expdb/backfill.py tests/expdb/test_backfill_bulk.py
git commit -m "expdb: bulk scan_runs_dir with summary + skipped counts"
```

---

## Task 10: CLI

**Files:**
- Create: `enrichment/expdb/__main__.py`
- Create: `enrichment/expdb/cli.py`
- Create: `tests/expdb/test_cli.py`

The CLI exposes three subcommands at `python -m enrichment.expdb`:
- `scan [--runs-dir DIR] [--db PATH]` — bulk-scan a runs directory
- `list-episodes [--novel N] [--db PATH]` — print episodes
- `show <run_label> [--db PATH]` — print one episode + its scripts + audio

- [ ] **Step 1: Write the failing test**

Write `tests/expdb/test_cli.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from enrichment.expdb.cli import main


def test_cli_scan_then_list_then_show(tmp_path: Path, capsys, monkeypatch) -> None:
    db = tmp_path / "experiments.db"
    runs = tmp_path / "runs"
    rd = runs / "bh_trn_literary" / "audio"
    rd.mkdir(parents=True)
    (rd.parent / "run_manifest.json").write_text(json.dumps({
        "schema_version": 1, "run_id": "bh_trn_literary",
        "axes": {"novel": "bh", "pipeline": "trn", "panel": "literary",
                  "hostprep": False, "generator": "anthropic_sonnet_4_6"},
        "stages": {},
        "audio_variants": [],
        "generated_at": "2026-04-25T10:00:00Z", "dvc_lock_sha": "x",
    }))
    (rd.parent / "phase3_episode.json").write_text(json.dumps({"segments": []}))

    main(["scan", "--db", str(db), "--runs-dir", str(runs)])
    out = capsys.readouterr().out
    assert "scanned: 1" in out

    main(["list-episodes", "--db", str(db)])
    out = capsys.readouterr().out
    assert "bh_trn_literary" in out

    main(["show", "bh_trn_literary", "--db", str(db)])
    out = capsys.readouterr().out
    assert "bh" in out
    assert "literary" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/expdb/test_cli.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement CLI**

Write `enrichment/expdb/cli.py`:

```python
"""CLI for inspecting + populating the experiment ledger."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .backfill import scan_runs_dir
from .store import Store

DEFAULT_DB = Path("data/experiments.db")
DEFAULT_RUNS = Path("data/runs")


def cmd_scan(args: argparse.Namespace) -> int:
    store = Store(args.db)
    store.init_schema()
    summary = scan_runs_dir(store, args.runs_dir)
    print(f"scanned: {summary['scanned']}, skipped: {summary['skipped']}")
    print(f"episodes_inserted: {summary['episodes_inserted']}, "
          f"scripts_inserted: {summary['scripts_inserted']}")
    if summary["errors"]:
        print(f"errors: {len(summary['errors'])}")
        for e in summary["errors"][:5]:
            print(f"  {e['run_dir']}: {e['error']}")
    return 0


def cmd_list_episodes(args: argparse.Namespace) -> int:
    store = Store(args.db)
    store.init_schema()
    for ep in store.list_episodes(novel=args.novel):
        print(f"{ep.id:4d}  {ep.label:50s}  {ep.novel}/{ep.panel}/{ep.pipeline}"
              f"  hostprep={ep.hostprep}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    store = Store(args.db)
    store.init_schema()
    eps = [e for e in store.list_episodes() if e.label == args.label]
    if not eps:
        print(f"no episode with label {args.label!r}", file=sys.stderr)
        return 1
    ep = eps[0]
    print(f"episode {ep.id}: {ep.label}  ({ep.novel}/{ep.panel}/{ep.pipeline}"
          f", hostprep={ep.hostprep})")
    for sv in store.list_scripts_for_episode(ep.id):
        print(f"  script {sv.id}  {sv.path}  segs={sv.n_segments} "
              f"turns={sv.n_turns} utts={sv.n_utterances}")
        for a in store.list_audio_for_script(sv.id):
            print(f"    audio {a.id}  {a.name}  {a.path}  hash={a.dvc_hash}  "
                  f"dur={a.duration_s}")
        for ev in store.list_evaluations_for_script(sv.id):
            print(f"    eval {ev.id}  {ev.metric_kind}  {ev.metric}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m enrichment.expdb")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp_scan = sub.add_parser("scan")
    sp_scan.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS)
    sp_scan.set_defaults(fn=cmd_scan)

    sp_ls = sub.add_parser("list-episodes")
    sp_ls.add_argument("--novel", default=None)
    sp_ls.set_defaults(fn=cmd_list_episodes)

    sp_show = sub.add_parser("show")
    sp_show.add_argument("label")
    sp_show.set_defaults(fn=cmd_show)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
```

Write `enrichment/expdb/__main__.py`:

```python
from .cli import main
import sys
sys.exit(main())
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/expdb/test_cli.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add enrichment/expdb/__main__.py enrichment/expdb/cli.py tests/expdb/test_cli.py
git commit -m "expdb: CLI scan / list-episodes / show"
```

---

## Task 11: Real backfill across the project, sanity-check counts

**Files:** none (operational task — verifies the system end-to-end against real data)

- [ ] **Step 1: Run the bulk scan**

```bash
uv run python -m enrichment.expdb scan --db data/experiments.db --runs-dir data/runs
```

Expected output (rough — actual numbers depend on current state):
- `scanned: ~150-200`
- `skipped: 0` (or low — only counts dirs without manifests)
- `errors: 0` (any error means a run dir has malformed JSON; fix before continuing)

- [ ] **Step 2: Spot-check episode count**

```bash
uv run python -m enrichment.expdb list-episodes 2>&1 | wc -l
```

Expected: roughly matches `find data/runs -maxdepth 1 -mindepth 1 -type d | wc -l` minus any skipped dirs.

- [ ] **Step 3: Spot-check one specific run**

```bash
uv run python -m enrichment.expdb show bh_trn_literary
```

Expected: prints episode + at least one script + at least one audio variant + the quote_verification evaluation. Cross-check against `data/runs/bh_trn_literary/run_manifest.json` to confirm the values match.

- [ ] **Step 4: Add `data/experiments.db` to .gitignore**

In `.gitignore`, append:

```
# Experiment ledger (regenerable from data/runs via `python -m enrichment.expdb scan`).
data/experiments.db
data/experiments.db-wal
data/experiments.db-shm
```

- [ ] **Step 5: Commit**

```bash
git add .gitignore
git commit -m "expdb: gitignore the local DB (regenerable via scan)"
```

- [ ] **Step 6: Run the full test suite**

```bash
uv run pytest tests/expdb/ -v
uv run ruff check enrichment/expdb tests/expdb
```

Expected: all expdb tests pass, ruff clean.

---

## Self-review

**Spec coverage check** — every user requirement maps to a task:

- "branch for a migration" → branch already created (`experiments-db`)
- "explicitly represents experiments in a small sql database" → Tasks 1–7 (schema + CRUD)
- "Keep DVC for heavy artifacts" → audio_artifact.path + dvc_hash columns; scanner reads existing dvc-tracked paths
- "Add a first-class experiment table" with the 7 named tables → all 7 in schema (Task 2)
- "Store DVC paths/hashes in the DB" — `audio_artifact.path` + `audio_artifact.dvc_hash` + `generation_run.git_commit` + `generation_run.dvc_rev` → all present in schema and tested (Tasks 5, 6, 8)
- "Do not use Git branches for every creative variant. Use DB rows." → Captured by audio_artifact + tts_config rows; no per-variant git branches.
- "Use DVC stages only for deterministic-ish pipeline steps" → No new DVC stages introduced; existing ones stay. Documented in "Out of scope".

**Placeholder scan**: no "TBD" / "implement later" in steps — all code is shown verbatim.

**Type consistency**: `Episode`, `ScriptVersion`, `GenerationRun`, `TTSConfig`, `AudioArtifact`, `Evaluation`, `RegenerationRequest` referenced consistently across tasks.

**Out of scope is explicitly listed** at the top so the executor doesn't drift into integrating with qwen-tts-server / pipeline / webapp.

---

## What ships at the end

- `enrichment/expdb/` package with schema + 7 row types + CRUD + scanner + CLI.
- `tests/expdb/` with full coverage of the schema and scanner (no GPU / no live services needed).
- `data/experiments.db` regenerable via `python -m enrichment.expdb scan`.
- A clear "phase D" follow-up plan to wire the DB into the live services — that's a separate plan once this is merged.
