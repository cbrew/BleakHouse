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
