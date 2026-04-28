"""Row dataclasses for the experiment ledger."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
