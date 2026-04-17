"""TTS profile registry."""
from __future__ import annotations

from enrichment.tts_profiles.base import EpisodeContext, TTSProfile

__all__ = ["EpisodeContext", "TTSProfile", "get_profile", "profile_names"]


def profile_names() -> list[str]:
    return ["classic", "trevelyan_v2"]


def get_profile(name: str, *, classic_model_id: str | None = None) -> TTSProfile:
    if name == "classic":
        from enrichment.tts_profiles.classic import ClassicProfile

        return ClassicProfile(model_id=classic_model_id)
    if name == "trevelyan_v2":
        from enrichment.tts_profiles.trevelyan_v2 import TrevelyanV2Profile

        return TrevelyanV2Profile()
    raise ValueError(f"Unknown TTS profile: {name!r}. Known: {profile_names()!r}")
