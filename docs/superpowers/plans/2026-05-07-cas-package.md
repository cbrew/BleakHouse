# CAS Package Implementation Plan (BleakHouse-3u1g)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `cas/` Python package — a small content-addressed-store module exposing `put / url / local_path / push / pull / has_local / has_remote` plus a `cas.paths` helper module — as the foundation for migrating BleakHouse off DVC. Pure addition; coexists with DVC. Subsequent issues (8.2-8.8) consume it.

**Architecture:** Two modules under a top-level `cas/` package. `cas/store.py` handles bytes-by-md5 (local copy + R2 upload/download via boto3). `cas/paths.py` centralises novel- and run-aware path resolution (no `if novel == "bleak_house":` special cases anywhere in callers). All non-existence errors raise `FileNotFoundError`/`KeyError` with contextual messages. The single exception is `cas.local_path(md5) -> Path | None` — webapp uses `None` to decide local-vs-302.

**Tech Stack:** Python 3.13, boto3 (R2 over S3 protocol), pytest + moto for unit tests, real-R2 integration test gated behind `R2_INTEGRATION=1`.

**Spec:** `docs/superpowers/specs/2026-05-07-cas-migration-design.md` (§ Components → cas/ package).

---

## File structure

| Path | Responsibility | Status |
|---|---|---|
| `cas/__init__.py` | Re-export public API: `put`, `url`, `local_path`, `push`, `pull`, `has_local`, `has_remote`. Also re-export `cas.paths` as `cas.paths`. | Create |
| `cas/store.py` | Bytes-by-md5: hashing, local copy, R2 upload/download via boto3. ~120 LoC. | Create |
| `cas/paths.py` | Centralised path resolution helpers (per-novel + per-run). Each helper raises `FileNotFoundError` with a contextual message on miss. ~50 LoC. | Create |
| `cas/conftest.py` | Pytest fixture: `cas_root` (tmp_path-scoped), `r2_env` (sets all R2 env vars to test values). | Create |
| `cas/tests/__init__.py` | Empty — marks tests as a package so pytest discovers them. | Create |
| `cas/tests/test_store_local.py` | Local layer tests: hashing, put round-trip, idempotency, has_local, url. | Create |
| `cas/tests/test_store_remote.py` | R2 layer tests with moto: push, pull, has_remote, idempotent push. | Create |
| `cas/tests/test_store_integration.py` | Real-R2 round-trip; skip-marked unless `R2_INTEGRATION=1`. | Create |
| `cas/tests/test_paths.py` | Each path helper: returns expected path; raises with contextual message on miss. | Create |
| `pyproject.toml` | Add `boto3>=1.34` and `moto[s3]>=5.0` (dev group). | Modify |

**Note**: `cas/` lives at the repo root (alongside `webapp/`, `enrichment/`, `scripts/`), NOT under `webapp/`. Multiple consumers (webapp, enrichment, scripts) import it.

**Note on `dvc>=3.67.1` and `dvc-s3>=3.0`**: NOT removed in this issue. They stay until 8.7 (Phase E). Coexistence is intentional.

---

## Task 1: Package skeleton + boto3 dependency

**Files:**
- Create: `cas/__init__.py`
- Create: `cas/conftest.py`
- Create: `cas/tests/__init__.py`
- Modify: `pyproject.toml:7-46` (add `boto3` to `dependencies`, add `moto[s3]` to `[dependency-groups].dev`)

- [ ] **Step 1: Create empty package skeleton**

```bash
mkdir -p cas/tests
```

Create `cas/__init__.py`:

```python
"""Content-addressed store for BleakHouse.

Replaces DVC for blob storage. Bytes are addressed by md5; the same
md5 finds bytes both locally (under <BLEAKHOUSE_CAS_ROOT>/files/md5/...)
and on R2 (under /files/md5/...).

Public API lives in cas.store and cas.paths; this __init__ stays empty
during the build-out so the package imports cleanly at every commit.
Task 5 adds the re-exports once both modules exist.
"""
```

Create `cas/tests/__init__.py` as an empty file.

Create `cas/conftest.py`:

```python
"""Shared pytest fixtures for cas/ tests."""
from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def cas_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set BLEAKHOUSE_CAS_ROOT to a tmp dir; return the path."""
    root = tmp_path / "cas"
    root.mkdir()
    monkeypatch.setenv("BLEAKHOUSE_CAS_ROOT", str(root))
    return root


@pytest.fixture
def r2_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Set R2 env vars to test values. Used by tests that touch boto3
    via moto. Real-R2 integration tests do NOT use this fixture."""
    monkeypatch.setenv("R2_ENDPOINT_URL", "https://r2.test.local")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "test_access")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test_secret")
    monkeypatch.setenv("BLEAKHOUSE_R2_BUCKET", "test-bucket")
    yield
```

- [ ] **Step 2: Add boto3 + moto to pyproject.toml**

Modify `pyproject.toml`:

In the `dependencies` list (currently ends with `"dvc-s3>=3.0",` on line 46), add **after** `"dvc-s3>=3.0",`:

```toml
    "boto3>=1.34",
```

In the `[dependency-groups]` `dev` list (currently ends with `"pytest>=8.0.0",` on line 52), add **after** that line:

```toml
    "moto[s3]>=5.0",
```

- [ ] **Step 3: Sync and verify package imports cleanly**

```bash
uv sync
uv run python -c "import cas; print(cas.__doc__.splitlines()[0])"
```

Expected output: `Content-addressed store for BleakHouse.`

(The empty `__init__.py` imports cleanly because it has no `from cas.store ...` lines yet — those land in Task 5 once both modules exist.)

- [ ] **Step 4: Quality gates pass on the skeleton**

Run:

```bash
uv run ruff check cas/
```

Expected: `All checks passed!` (cas/__init__.py imports from a nonexistent module, but ruff doesn't follow imports so it's fine.)

```bash
uv run pytest cas/ --collect-only 2>&1 | tail -5
```

Expected: `no tests ran` or similar (cas/tests/ exists but is empty).

- [ ] **Step 5: Commit**

```bash
git add cas/__init__.py cas/conftest.py cas/tests/__init__.py pyproject.toml uv.lock
git commit -m "$(cat <<'EOF'
cas: package skeleton + boto3/moto deps (BleakHouse-3u1g)

First step of CAS migration. Pure addition; cas.store + cas.paths
land in following commits. DVC stays installed alongside.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Local store — hashing + put + local_path + has_local + url

**Files:**
- Create: `cas/store.py`
- Create: `cas/tests/test_store_local.py`

This task implements the local-only API surface. R2 (boto3) lives in Task 3 so it can be tested separately with moto. Same module, two halves.

- [ ] **Step 1: Write failing test for `url()`**

Create `cas/tests/test_store_local.py`:

```python
"""Tests for cas.store local-only API: url, put, local_path, has_local."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from cas import store


@pytest.fixture(autouse=True)
def public_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """All tests need a stable R2 public URL."""
    monkeypatch.setenv(
        "BLEAKHOUSE_R2_PUBLIC_URL",
        "https://r2.test.local",
    )


def test_url_returns_r2_path_keyed_by_md5_split() -> None:
    md5 = "abcdef0123456789" + "0" * 16
    assert store.url(md5) == (
        "https://r2.test.local/files/md5/ab/cdef0123456789" + "0" * 16
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest cas/tests/test_store_local.py::test_url_returns_r2_path_keyed_by_md5_split -v
```

Expected: `ImportError: cannot import name 'store' from 'cas'` (or similar — `cas/store.py` doesn't exist).

- [ ] **Step 3: Create cas/store.py with minimal content for url()**

Create `cas/store.py`:

```python
"""Content-addressed store: bytes by md5.

Local layer: hash + copy into <BLEAKHOUSE_CAS_ROOT>/files/md5/<prefix>/<rest>.
R2 layer: upload/download via boto3 (added in Task 3).
"""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

# Repo root is two levels up from this file (cas/store.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _cas_root() -> Path:
    """Local CAS root. Default <repo>/data/cas; overridable via env var."""
    override = os.environ.get("BLEAKHOUSE_CAS_ROOT")
    if override:
        return Path(override)
    return _REPO_ROOT / "data" / "cas"


def _cas_path_for(md5: str) -> Path:
    """Compute the on-disk path for an md5 (regardless of existence)."""
    return _cas_root() / "files" / "md5" / md5[:2] / md5[2:]


def _r2_public_url() -> str:
    return os.environ.get(
        "BLEAKHOUSE_R2_PUBLIC_URL",
        "https://pub-0ac622dd336f40438799d8dbd211234a.r2.dev",
    )


def url(md5: str) -> str:
    """Public R2 URL for the blob with this md5."""
    return f"{_r2_public_url()}/files/md5/{md5[:2]}/{md5[2:]}"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest cas/tests/test_store_local.py::test_url_returns_r2_path_keyed_by_md5_split -v
```

Expected: `1 passed`.

- [ ] **Step 5: Add tests for put + local_path + has_local**

Append to `cas/tests/test_store_local.py`:

```python
def test_put_round_trip_writes_blob_at_md5_path(
    cas_root: Path, tmp_path: Path
) -> None:
    src = tmp_path / "audio.mp3"
    payload = b"fake mp3 bytes"
    src.write_bytes(payload)
    expected_md5 = hashlib.md5(payload).hexdigest()

    md5 = store.put(src)

    assert md5 == expected_md5
    blob = cas_root / "files" / "md5" / md5[:2] / md5[2:]
    assert blob.is_file()
    assert blob.read_bytes() == payload


def test_put_does_not_move_or_modify_source(
    cas_root: Path, tmp_path: Path
) -> None:
    src = tmp_path / "audio.mp3"
    src.write_bytes(b"hello")
    store.put(src)
    assert src.is_file(), "put must not move/delete the source"
    assert src.read_bytes() == b"hello", "put must not modify the source"


def test_put_is_idempotent(cas_root: Path, tmp_path: Path) -> None:
    src = tmp_path / "audio.mp3"
    src.write_bytes(b"hello")
    md5_a = store.put(src)
    blob = cas_root / "files" / "md5" / md5_a[:2] / md5_a[2:]
    mtime_before = blob.stat().st_mtime_ns

    md5_b = store.put(src)

    assert md5_a == md5_b
    assert blob.stat().st_mtime_ns == mtime_before, (
        "second put must not rewrite the existing blob"
    )


def test_local_path_returns_path_when_blob_present(
    cas_root: Path, tmp_path: Path
) -> None:
    src = tmp_path / "audio.mp3"
    src.write_bytes(b"hello")
    md5 = store.put(src)

    p = store.local_path(md5)

    assert p is not None
    assert p == cas_root / "files" / "md5" / md5[:2] / md5[2:]
    assert p.is_file()


def test_local_path_returns_none_when_blob_absent(cas_root: Path) -> None:
    bogus = "0" * 32
    assert store.local_path(bogus) is None


def test_has_local_true_when_blob_present(
    cas_root: Path, tmp_path: Path
) -> None:
    src = tmp_path / "audio.mp3"
    src.write_bytes(b"hello")
    md5 = store.put(src)
    assert store.has_local(md5) is True


def test_has_local_false_when_blob_absent(cas_root: Path) -> None:
    assert store.has_local("0" * 32) is False
```

- [ ] **Step 6: Run new tests to verify they fail**

```bash
uv run pytest cas/tests/test_store_local.py -v 2>&1 | tail -20
```

Expected: 6 new tests fail with `AttributeError: module 'cas.store' has no attribute 'put'` (and similar for `local_path`, `has_local`).

- [ ] **Step 7: Implement put + local_path + has_local**

Append to `cas/store.py`:

```python
def put(path: Path) -> str:
    """Hash `path`, copy bytes into the CAS, return md5.

    Idempotent: if md5 already in CAS, no copy. Reads-and-copies
    (does not move/link); caller is responsible for the source file.
    """
    md5 = _md5_of_file(path)
    dest = _cas_path_for(md5)
    if not dest.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        shutil.copyfile(path, tmp)
        tmp.rename(dest)
    return md5


def local_path(md5: str) -> Path | None:
    """On-disk path if blob is in local CAS, else None."""
    p = _cas_path_for(md5)
    return p if p.is_file() else None


def has_local(md5: str) -> bool:
    return local_path(md5) is not None


def _md5_of_file(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
```

- [ ] **Step 8: Run all local-store tests to verify they pass**

```bash
uv run pytest cas/tests/test_store_local.py -v
```

Expected: `8 passed`.

- [ ] **Step 9: Quality gates**

```bash
uv run ruff check cas/
uv run pyright cas/
```

Both must report no errors.

- [ ] **Step 10: Commit**

```bash
git add cas/store.py cas/tests/test_store_local.py
git commit -m "$(cat <<'EOF'
cas: local-only API (put/url/local_path/has_local) (BleakHouse-3u1g)

Hash+copy bytes into <BLEAKHOUSE_CAS_ROOT>/files/md5/<prefix>/<rest>.
Idempotent put. local_path returns None on miss (only place 'missing'
is normal). put reads-and-copies — caller cleans up own temp files.
R2 layer (push/pull/has_remote) lands next.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: R2 store — push + pull + has_remote (with moto)

**Files:**
- Modify: `cas/store.py` (add boto3 client + push/pull/has_remote)
- Create: `cas/tests/test_store_remote.py`

R2 is S3-compatible. boto3 talks to it via an explicit `endpoint_url`. Tests use moto to mock S3 (no network).

- [ ] **Step 1: Write failing test for has_remote**

Create `cas/tests/test_store_remote.py`:

```python
"""Tests for cas.store R2 API: push, pull, has_remote (moto-mocked)."""
from __future__ import annotations

from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from cas import store


@pytest.fixture
def s3_bucket(r2_env: None) -> str:
    """Create the test bucket inside the moto mock."""
    with mock_aws():
        client = boto3.client(
            "s3",
            endpoint_url="https://r2.test.local",
            aws_access_key_id="test_access",
            aws_secret_access_key="test_secret",
            region_name="auto",
        )
        client.create_bucket(Bucket="test-bucket")
        yield "test-bucket"


def test_has_remote_false_when_blob_absent(
    s3_bucket: str, cas_root: Path
) -> None:
    with mock_aws():
        # Recreate bucket inside the active mock context
        boto3.client(
            "s3",
            endpoint_url="https://r2.test.local",
            aws_access_key_id="test_access",
            aws_secret_access_key="test_secret",
            region_name="auto",
        ).create_bucket(Bucket="test-bucket")
        assert store.has_remote("0" * 32) is False
```

**Note about moto context**: `s3_bucket` enters/exits the mock inside the fixture; the test then enters a NEW mock and recreates the bucket. This is awkward. Refactor: drop `s3_bucket` and put `mock_aws` + bucket creation directly in each test. Replace the test above with:

```python
def test_has_remote_false_when_blob_absent(
    r2_env: None, cas_root: Path
) -> None:
    with mock_aws():
        boto3.client(
            "s3",
            endpoint_url="https://r2.test.local",
            aws_access_key_id="test_access",
            aws_secret_access_key="test_secret",
            region_name="auto",
        ).create_bucket(Bucket="test-bucket")

        assert store.has_remote("0" * 32) is False
```

(Drop the `s3_bucket` fixture entirely; remove its definition.)

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest cas/tests/test_store_remote.py::test_has_remote_false_when_blob_absent -v
```

Expected: `AttributeError: module 'cas.store' has no attribute 'has_remote'`.

- [ ] **Step 3: Add boto3 client + has_remote to cas/store.py**

Append to `cas/store.py`:

```python
import boto3
from botocore.exceptions import ClientError


def _bucket() -> str:
    return os.environ.get("BLEAKHOUSE_R2_BUCKET", "not-in-our-time")


def _r2_client() -> "boto3.client":  # type: ignore[name-defined]
    """Construct a fresh boto3 S3 client. Required env vars:
    R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY.
    Raises KeyError on missing var."""
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def _r2_key(md5: str) -> str:
    return f"files/md5/{md5[:2]}/{md5[2:]}"


def has_remote(md5: str) -> bool:
    """True if R2 has the blob (HEAD check)."""
    try:
        _r2_client().head_object(Bucket=_bucket(), Key=_r2_key(md5))
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise
    return True
```

(Note: `import boto3` near the top of `store.py` — group with the other stdlib imports above the `_REPO_ROOT` line. botocore.exceptions.ClientError too.)

- [ ] **Step 4: Run has_remote test to verify it passes**

```bash
uv run pytest cas/tests/test_store_remote.py -v
```

Expected: `1 passed`.

- [ ] **Step 5: Add tests for push and pull**

Append to `cas/tests/test_store_remote.py`:

```python
def _make_bucket() -> None:
    """Create the test bucket inside the active moto mock."""
    boto3.client(
        "s3",
        endpoint_url="https://r2.test.local",
        aws_access_key_id="test_access",
        aws_secret_access_key="test_secret",
        region_name="auto",
    ).create_bucket(Bucket="test-bucket")


def test_push_uploads_local_blob_to_r2(
    r2_env: None, cas_root: Path, tmp_path: Path
) -> None:
    src = tmp_path / "audio.mp3"
    src.write_bytes(b"payload")
    md5 = store.put(src)

    with mock_aws():
        _make_bucket()
        store.push(md5)

        assert store.has_remote(md5) is True


def test_push_raises_when_blob_missing_locally(
    r2_env: None, cas_root: Path
) -> None:
    with mock_aws():
        _make_bucket()
        with pytest.raises(FileNotFoundError, match="not in local CAS"):
            store.push("0" * 32)


def test_push_is_idempotent(
    r2_env: None, cas_root: Path, tmp_path: Path
) -> None:
    src = tmp_path / "audio.mp3"
    src.write_bytes(b"payload")
    md5 = store.put(src)

    with mock_aws():
        _make_bucket()
        store.push(md5)
        store.push(md5)  # second push is a no-op
        assert store.has_remote(md5) is True


def test_pull_downloads_remote_blob_into_local_cas(
    r2_env: None, cas_root: Path, tmp_path: Path
) -> None:
    payload = b"remote bytes"
    md5 = "abc" + "0" * 29

    with mock_aws():
        _make_bucket()
        boto3.client(
            "s3",
            endpoint_url="https://r2.test.local",
            aws_access_key_id="test_access",
            aws_secret_access_key="test_secret",
            region_name="auto",
        ).put_object(Bucket="test-bucket", Key=f"files/md5/ab/c{'0'*29}", Body=payload)

        local = store.pull(md5)

        assert local.read_bytes() == payload
        assert local == cas_root / "files" / "md5" / "ab" / ("c" + "0" * 29)


def test_pull_raises_when_blob_missing_remotely(
    r2_env: None, cas_root: Path
) -> None:
    with mock_aws():
        _make_bucket()
        with pytest.raises(FileNotFoundError, match="not in R2"):
            store.pull("0" * 32)
```

- [ ] **Step 6: Run new tests to verify they fail**

```bash
uv run pytest cas/tests/test_store_remote.py -v 2>&1 | tail -20
```

Expected: 5 new tests fail with `AttributeError: module 'cas.store' has no attribute 'push'` (and `pull`).

- [ ] **Step 7: Implement push + pull**

Append to `cas/store.py`:

```python
def push(md5: str) -> None:
    """Upload local blob to R2. Idempotent (HEAD-then-PUT).

    Raises FileNotFoundError if blob missing locally.
    """
    src = local_path(md5)
    if src is None:
        raise FileNotFoundError(f"md5 {md5} not in local CAS")
    if has_remote(md5):
        return
    with src.open("rb") as f:
        _r2_client().put_object(Bucket=_bucket(), Key=_r2_key(md5), Body=f)


def pull(md5: str) -> Path:
    """Download blob from R2 into local CAS; return local path.

    Raises FileNotFoundError if blob missing in R2.
    """
    dest = _cas_path_for(md5)
    if dest.is_file():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        _r2_client().download_file(_bucket(), _r2_key(md5), str(tmp))
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"404", "NoSuchKey", "NotFound"}:
            raise FileNotFoundError(f"md5 {md5} not in R2") from exc
        raise
    tmp.rename(dest)
    return dest
```

- [ ] **Step 8: Run all remote-store tests to verify they pass**

```bash
uv run pytest cas/tests/test_store_remote.py -v
```

Expected: `6 passed`.

- [ ] **Step 9: Run all cas tests together**

```bash
uv run pytest cas/ -v
```

Expected: `14 passed` (8 local + 6 remote).

- [ ] **Step 10: Quality gates**

```bash
uv run ruff check cas/
uv run pyright cas/
```

Both must report no errors. If pyright complains about `boto3.client` typing, the inline `# type: ignore[name-defined]` already in `_r2_client` should suffice; if not, narrow the annotation to `Any`.

- [ ] **Step 11: Commit**

```bash
git add cas/store.py cas/tests/test_store_remote.py
git commit -m "$(cat <<'EOF'
cas: R2 API (push/pull/has_remote) via boto3 + moto tests (BleakHouse-3u1g)

push uploads local blob (HEAD-then-PUT, idempotent); pull downloads
into local CAS. has_remote is a HEAD probe. Tests use moto[s3] —
no network. Real-R2 round-trip lands in the next commit, gated
behind R2_INTEGRATION=1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Real-R2 integration test (skip-marked)

**Files:**
- Create: `cas/tests/test_store_integration.py`

This test exercises the full put → push → delete-local → pull → verify-bytes round-trip against real R2. Skip-marked unless `R2_INTEGRATION=1`. Used as a manual smoke test before relying on cas in production paths.

- [ ] **Step 1: Write the integration test**

Create `cas/tests/test_store_integration.py`:

```python
"""Real-R2 integration test for cas.store.

Skip-marked unless R2_INTEGRATION=1 in the environment. Uses the real
R2 bucket and credentials from the same env vars writers consume:
R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
BLEAKHOUSE_R2_BUCKET (defaults to 'not-in-our-time').

Run manually:
    R2_INTEGRATION=1 uv run pytest cas/tests/test_store_integration.py -v

Each run uploads ~32 bytes; idempotent — no cleanup required.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

import pytest

from cas import store

pytestmark = pytest.mark.skipif(
    os.environ.get("R2_INTEGRATION") != "1",
    reason="R2 integration tests require R2_INTEGRATION=1",
)


def test_round_trip_against_real_r2(
    cas_root: Path, tmp_path: Path
) -> None:
    """put → push → wipe local → pull → verify bytes match."""
    payload = secrets.token_bytes(32)
    src = tmp_path / "blob.bin"
    src.write_bytes(payload)

    md5 = store.put(src)
    assert store.has_local(md5) is True

    store.push(md5)
    assert store.has_remote(md5) is True

    blob_local = cas_root / "files" / "md5" / md5[:2] / md5[2:]
    blob_local.unlink()
    assert store.has_local(md5) is False

    pulled = store.pull(md5)
    assert pulled.read_bytes() == payload
    assert store.has_local(md5) is True
```

- [ ] **Step 2: Verify the test is correctly skipped without env var**

```bash
uv run pytest cas/tests/test_store_integration.py -v
```

Expected: `1 skipped` (with reason "R2 integration tests require R2_INTEGRATION=1").

- [ ] **Step 3: Verify the test passes against real R2**

This is a manual gate. Set R2 credentials and run:

```bash
export R2_ENDPOINT_URL="https://667cc18d4aff823066843e08c23a306c.r2.cloudflarestorage.com"
export R2_ACCESS_KEY_ID="<from .dvc/config.local>"
export R2_SECRET_ACCESS_KEY="<from .dvc/config.local>"
R2_INTEGRATION=1 uv run pytest cas/tests/test_store_integration.py -v
```

Expected: `1 passed`.

If credentials aren't available locally, defer this manual step — the moto tests in Task 3 cover the same logic.

- [ ] **Step 4: Quality gates**

```bash
uv run ruff check cas/
uv run pyright cas/
```

Both must report no errors.

- [ ] **Step 5: Commit**

```bash
git add cas/tests/test_store_integration.py
git commit -m "$(cat <<'EOF'
cas: real-R2 integration test (skip-marked) (BleakHouse-3u1g)

Round-trip put → push → delete-local → pull → verify against the
real R2 bucket. Skipped unless R2_INTEGRATION=1; idempotent (32
random bytes per run, no cleanup needed). Manual smoke test before
relying on cas in production paths.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: cas/paths.py — centralised path helpers

**Files:**
- Create: `cas/paths.py`
- Create: `cas/tests/test_paths.py`
- Modify: `cas/__init__.py` (re-export `paths` submodule)

The path helpers are the foundation for issue 8.5's silent-fallback audit. Each helper resolves a known-shape path under `data/`. None of them check existence — that's the caller's choice. They DO raise `FileNotFoundError` when the *novel* or *run* directory itself doesn't exist (because then no caller could possibly recover; the input is wrong).

The initial helper set covers what's already used in code today. The list grows during the 8.5 audit pass.

- [ ] **Step 1: Write failing tests for the per-novel helpers**

Create `cas/tests/test_paths.py`:

```python
"""Tests for cas.paths — centralised path resolution helpers."""
from __future__ import annotations

from pathlib import Path

import pytest

from cas import paths


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Synthetic data/ tree under tmp_path; cas.paths resolves under it."""
    monkeypatch.setattr(paths, "_DATA_DIR", tmp_path / "data")
    (tmp_path / "data" / "novels" / "bleak_house").mkdir(parents=True)
    (tmp_path / "data" / "novels" / "bleak_house" / "passages_enriched.json").write_text("[]")
    (tmp_path / "data" / "novels" / "bleak_house" / "clusters_literary.json").write_text("{}")
    (tmp_path / "data" / "novels" / "bleak_house" / "clusters_characters.json").write_text("{}")
    (tmp_path / "data" / "runs" / "bh_trn_literary").mkdir(parents=True)
    return tmp_path


def test_passages_enriched_resolves_under_novel_dir(fake_repo: Path) -> None:
    p = paths.passages_enriched("bleak_house")
    assert p == fake_repo / "data" / "novels" / "bleak_house" / "passages_enriched.json"


def test_passages_enriched_raises_when_novel_dir_missing(fake_repo: Path) -> None:
    with pytest.raises(FileNotFoundError, match="novel 'nonexistent' not registered"):
        paths.passages_enriched("nonexistent")


def test_clusters_literary_resolves_under_novel_dir(fake_repo: Path) -> None:
    p = paths.clusters_literary("bleak_house")
    assert p == fake_repo / "data" / "novels" / "bleak_house" / "clusters_literary.json"


def test_clusters_characters_resolves_under_novel_dir(fake_repo: Path) -> None:
    p = paths.clusters_characters("bleak_house")
    assert p == fake_repo / "data" / "novels" / "bleak_house" / "clusters_characters.json"


def test_clusters_literary_raises_when_novel_dir_missing(fake_repo: Path) -> None:
    with pytest.raises(FileNotFoundError, match="novel 'nope' not registered"):
        paths.clusters_literary("nope")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest cas/tests/test_paths.py -v 2>&1 | tail -10
```

Expected: `ImportError: cannot import name 'paths' from 'cas'` — `cas/paths.py` doesn't exist.

- [ ] **Step 3: Create cas/paths.py with per-novel helpers**

Create `cas/paths.py`:

```python
"""Centralised, novel-aware path resolution.

Each helper returns a resolved Path. Helpers DO NOT check whether the
file itself exists (that's the caller's choice — required vs. optional).
Helpers DO raise FileNotFoundError when the novel or run *directory*
is missing — at that point the input is wrong and no caller can
recover.

This module is the canonical answer to 'where is X for novel Y'. No
caller reconstructs paths bespoke; no caller has 'if novel ==
\"bleak_house\":' special cases. Adding a novel = registering it in
enrichment/axes.py + ensuring its data/novels/<id>/ directory exists.
"""
from __future__ import annotations

from pathlib import Path

# Repo root is two levels up from this file (cas/paths.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _REPO_ROOT / "data"


def _novel_dir(novel: str) -> Path:
    d = _DATA_DIR / "novels" / novel
    if not d.is_dir():
        raise FileNotFoundError(
            f"novel {novel!r} not registered: expected {d} to exist"
        )
    return d


def passages_enriched(novel: str) -> Path:
    return _novel_dir(novel) / "passages_enriched.json"


def clusters_literary(novel: str) -> Path:
    return _novel_dir(novel) / "clusters_literary.json"


def clusters_characters(novel: str) -> Path:
    return _novel_dir(novel) / "clusters_characters.json"
```

- [ ] **Step 4: Run novel-helper tests to verify they pass**

```bash
uv run pytest cas/tests/test_paths.py -v
```

Expected: `5 passed`.

- [ ] **Step 5: Add tests for per-run helpers**

Append to `cas/tests/test_paths.py`:

```python
def test_assignments_resolves_under_run_dir(fake_repo: Path) -> None:
    p = paths.assignments("bh_trn_literary")
    assert p == fake_repo / "data" / "runs" / "bh_trn_literary" / "phase1_assignments.json"


def test_reading_list_resolves_under_run_dir(fake_repo: Path) -> None:
    p = paths.reading_list("bh_trn_literary")
    assert p == fake_repo / "data" / "runs" / "bh_trn_literary" / "phase2_5_reading_list.json"


def test_episode_resolves_under_run_dir(fake_repo: Path) -> None:
    p = paths.episode("bh_trn_literary")
    assert p == fake_repo / "data" / "runs" / "bh_trn_literary" / "phase3_episode.json"


def test_shards_manifest_resolves_under_audio_subdir(fake_repo: Path) -> None:
    p = paths.shards_manifest("bh_trn_literary")
    assert p == fake_repo / "data" / "runs" / "bh_trn_literary" / "audio" / "shards.json"


def test_audio_assets_resolves_under_audio_subdir(fake_repo: Path) -> None:
    p = paths.audio_assets("bh_trn_literary")
    assert p == fake_repo / "data" / "runs" / "bh_trn_literary" / "audio" / "assets.json"


def test_run_helper_raises_when_run_dir_missing(fake_repo: Path) -> None:
    with pytest.raises(FileNotFoundError, match="run 'no_such_run' not found"):
        paths.assignments("no_such_run")
```

- [ ] **Step 6: Run new tests to verify they fail**

```bash
uv run pytest cas/tests/test_paths.py -v 2>&1 | tail -15
```

Expected: 6 new tests fail with `AttributeError: module 'cas.paths' has no attribute 'assignments'` (and similar).

- [ ] **Step 7: Add per-run helpers to cas/paths.py**

Append to `cas/paths.py`:

```python
def _run_dir(run_id: str) -> Path:
    d = _DATA_DIR / "runs" / run_id
    if not d.is_dir():
        raise FileNotFoundError(
            f"run {run_id!r} not found: expected {d} to exist"
        )
    return d


def assignments(run_id: str) -> Path:
    return _run_dir(run_id) / "phase1_assignments.json"


def reading_list(run_id: str) -> Path:
    return _run_dir(run_id) / "phase2_5_reading_list.json"


def episode(run_id: str) -> Path:
    return _run_dir(run_id) / "phase3_episode.json"


def shards_manifest(run_id: str) -> Path:
    return _run_dir(run_id) / "audio" / "shards.json"


def audio_assets(run_id: str) -> Path:
    return _run_dir(run_id) / "audio" / "assets.json"
```

- [ ] **Step 8: Run all path tests to verify they pass**

```bash
uv run pytest cas/tests/test_paths.py -v
```

Expected: `11 passed`.

- [ ] **Step 9: Re-export `cas.paths` from cas/__init__.py**

Modify `cas/__init__.py` — add `from cas import paths` and `"paths"` to `__all__`. Final file:

```python
"""Content-addressed store for BleakHouse.

Replaces DVC for blob storage. Bytes are addressed by md5; the same
md5 finds bytes both locally (under <BLEAKHOUSE_CAS_ROOT>/files/md5/...)
and on R2 (under /files/md5/...).

Public API re-exported here; full surface in cas.store and cas.paths.
"""
from cas import paths
from cas.store import (
    has_local,
    has_remote,
    local_path,
    pull,
    push,
    put,
    url,
)

__all__ = [
    "has_local",
    "has_remote",
    "local_path",
    "paths",
    "pull",
    "push",
    "put",
    "url",
]
```

- [ ] **Step 10: Run all cas tests together**

```bash
uv run pytest cas/ -v
```

Expected: `25 passed, 1 skipped` (8 local + 6 remote + 11 paths + 1 integration skipped).

- [ ] **Step 11: Quality gates (full pass)**

```bash
uv run ruff check cas/
uv run pyright cas/
uv run mypy cas/
```

All three must report no errors.

- [ ] **Step 12: Verify import surface**

```bash
uv run python -c "from cas import put, url, local_path, push, pull, has_local, has_remote, paths; print('OK')"
uv run python -c "from cas.paths import passages_enriched, clusters_literary, clusters_characters, assignments, reading_list, episode, shards_manifest, audio_assets; print('OK')"
```

Both must print `OK`.

- [ ] **Step 13: Commit**

```bash
git add cas/paths.py cas/tests/test_paths.py cas/__init__.py
git commit -m "$(cat <<'EOF'
cas: paths module with novel-/run-aware helpers (BleakHouse-3u1g)

Centralised path resolution: passages_enriched, clusters_literary,
clusters_characters, assignments, reading_list, episode,
shards_manifest, audio_assets. Each raises FileNotFoundError with
contextual message when the novel/run dir is missing. Caller
decides whether file existence is required or optional.

Initial set; 8.5 audit pass extends as new path classes surface.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Close the issue

- [ ] **Step 1: Verify the full acceptance bar**

The issue's acceptance criteria, restated with verification:

| Criterion | Verification |
|---|---|
| `pytest cas/` green | `uv run pytest cas/ -v` → `25 passed, 1 skipped` |
| put → local_path round-trip | `test_put_round_trip_writes_blob_at_md5_path` + `test_local_path_returns_path_when_blob_present` |
| push → pull round-trip against R2 (skip-marked) | `test_round_trip_against_real_r2` (manual or in CI with R2_INTEGRATION=1) |
| every cas.paths.* helper raises with contextual message on miss | `test_passages_enriched_raises_when_novel_dir_missing` + `test_clusters_literary_raises_when_novel_dir_missing` + `test_run_helper_raises_when_run_dir_missing` |
| boto3 added as direct dep | `grep boto3 pyproject.toml` shows it in `[project].dependencies` |

Run the full check:

```bash
uv run pytest cas/ -v
uv run ruff check cas/
uv run pyright cas/
grep "boto3>=" pyproject.toml
```

All four must succeed cleanly.

- [ ] **Step 2: Close the issue with completion summary**

```bash
bd close BleakHouse-3u1g --reason="$(cat <<'EOF'
cas/ package complete: store.py (put/url/local_path/has_local/push/pull/has_remote) + paths.py (8 helpers) + tests (8 local + 6 remote + 11 paths + 1 R2-integration skip-gated). 25 passed + 1 skipped. boto3 + moto[s3] in pyproject.toml. DVC + dvc-s3 untouched (Phase E in 8.7). Unblocks BleakHouse-weet (8.2 migration script).
EOF
)"
```

- [ ] **Step 3: Verify the next issue (8.2) is now in `bd ready`**

```bash
bd ready 2>&1 | grep -E "weet|3u1g"
```

Expected:
- `BleakHouse-weet` listed (now ready)
- `BleakHouse-3u1g` NOT listed (closed)

---

## Spec coverage check

Spec sections vs. plan tasks:

| Spec section | Plan task |
|---|---|
| § Components → cas/ package → API surface (put/url/local_path/push/pull/has_local/has_remote) | Tasks 2 + 3 |
| § Components → cas/ package → Backend choice (boto3 directly) | Task 1 (dep) + Task 3 (client) |
| § Components → cas/ package → Configuration (env vars) | Task 1 (conftest) + Task 2 (`_cas_root`, `_r2_public_url`) + Task 3 (`_bucket`, `_r2_client`) |
| § Components → cas/ package → Error policy (local_path returns None; everything else raises) | Tasks 2 + 3 |
| § Components → cas/ package → Tests (round-trip, idempotent, R2-integration skip-marked) | Tasks 2-4 |
| § Components → cas/ package → cas/paths.py | Task 5 |

Acceptance criteria (from BleakHouse-3u1g) all covered (Task 6 verifies).

**Out of scope here** (lands in subsequent issues, not this one):
- Migration script (8.2 — `BleakHouse-weet`)
- Webapp consumer swap (8.3)
- Audio generator integration (8.4)
- Silent-fallback audit (8.5 — extends `cas.paths` with more helpers)
- Cleanup script `cas.dedupe` — not part of cas package itself; lives in `scripts/cas_dedupe.py` and lands separately (likely 8.7 prep or its own follow-up)

---

## Risks and notes for the implementer

- **moto API surface**: moto 5.x consolidated everything under `mock_aws`. Older docs reference `mock_s3` — don't use that. The plan's tests use `mock_aws()` correctly.
- **boto3 ClientError shape**: the error code lives at `exc.response["Error"]["Code"]`. Different operations report missing-object differently — `head_object` returns `"404"`; `download_file` may surface `"NoSuchKey"`. The plan handles both.
- **Test isolation**: `cas_root` fixture sets `BLEAKHOUSE_CAS_ROOT` to a tmp_path; `r2_env` sets all R2 vars. Both are autouse-able if you want; the plan opts in per-test for explicitness.
- **`_DATA_DIR` patch in test_paths.py**: `monkeypatch.setattr(paths, "_DATA_DIR", ...)` overrides the module-level constant for the test. This works because `_DATA_DIR` is referenced inside the helper functions (not captured at import time). Confirmed by the `_novel_dir`/`_run_dir` impls reading `_DATA_DIR` each call.
- **Pyright + boto3**: boto3 has incomplete type stubs by default. If pyright complains, add `boto3-stubs[s3]>=1.34` to the dev group, or narrow the `_r2_client()` return type to `Any`. Don't suppress with broad `# type: ignore` outside the one already in the plan.
- **No commit-amend for hook failures**: if `ruff` or `pyright` fails on a commit, fix the issue and create a NEW commit (per project policy). Don't `--amend`.

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-07-cas-package.md`.** Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans; batch execution with checkpoints.

Which approach?
