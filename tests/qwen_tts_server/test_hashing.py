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
    assert len(h1) == 64


def test_hash_changes_on_content_change(two_files: tuple[Path, Path]) -> None:
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
