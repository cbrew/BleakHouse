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
