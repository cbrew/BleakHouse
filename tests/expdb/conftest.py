"""Shared fixtures for expdb tests."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """A clean SQLite DB path under a per-test tmpdir."""
    return tmp_path / "experiments.db"
