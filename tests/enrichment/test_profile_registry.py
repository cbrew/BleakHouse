"""Tests for the TTSProfile registry."""
from __future__ import annotations

import pytest

from enrichment.tts_profiles import get_profile, profile_names


def test_profile_names_lists_both_profiles() -> None:
    assert set(profile_names()) == {"classic", "trevelyan_v2"}


def test_get_profile_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown TTS profile"):
        get_profile("does_not_exist")


def test_get_profile_classic_returns_profile_with_expected_attrs() -> None:
    profile = get_profile("classic")
    assert profile.name == "classic"
    assert profile.cache_namespace == "classic"
    assert profile.pause_scale == 1.0
    assert profile.model_id == "gemini-2.5-flash-preview-tts"


def test_get_profile_classic_accepts_pro_model_id() -> None:
    profile = get_profile("classic", classic_model_id="gemini-2.5-pro-preview-tts")
    assert profile.model_id == "gemini-2.5-pro-preview-tts"


def test_get_profile_trevelyan_v2_returns_profile_with_expected_attrs() -> None:
    profile = get_profile("trevelyan_v2")
    assert profile.name == "trevelyan_v2"
    assert profile.cache_namespace == "trevelyan_v2"
    assert profile.pause_scale == 0.5
    assert profile.model_id == "gemini-3.1-flash-tts-preview"
