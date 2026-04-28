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
