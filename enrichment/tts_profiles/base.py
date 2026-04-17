"""TTSProfile protocol and shared types for render_audio.

A profile bundles everything that varies between different TTS renderings:
model id, voice selection, prompt construction, cache isolation, and
silence scaling. Adding a new profile must not require editing render_audio.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from enrichment.podcast_types import Turn


@dataclass(frozen=True)
class EpisodeContext:
    """Positional context for a turn within its episode."""

    episode_title: str
    segment_title: str
    segment_index: int
    turn_index: int
    previous_turn: Turn | None


class TTSProfile(Protocol):
    """A complete rendering configuration."""

    name: str
    model_id: str
    cache_namespace: str
    pause_scale: float

    def voice_name(self, speaker: str) -> str: ...
    def build_turn_prompt(self, turn: Turn, ctx: EpisodeContext) -> str: ...
