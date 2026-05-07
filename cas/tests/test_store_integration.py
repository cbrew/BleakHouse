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
