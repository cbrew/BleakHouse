"""Shared pytest fixtures for cas/ tests."""
from __future__ import annotations

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
