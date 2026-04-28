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
