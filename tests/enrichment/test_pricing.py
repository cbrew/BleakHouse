"""Tests for cost calculation across Anthropic + Gemini TTS models."""
from __future__ import annotations

from enrichment.pricing import (
    ESTIMATED_RATES,
    anthropic_rate_for,
    event_cost,
    tts_rate_for,
)


def test_anthropic_family_match_by_substring():
    assert anthropic_rate_for("claude-sonnet-4-6") is not None
    assert anthropic_rate_for("claude-sonnet-4-6").input_per_mtok == 3.00
    assert anthropic_rate_for("claude-haiku-4-5-20251001").input_per_mtok == 1.00
    assert anthropic_rate_for("claude-opus-4-7").output_per_mtok == 75.00
    assert anthropic_rate_for("gpt-4") is None


def test_tts_rate_match_by_exact_id():
    assert tts_rate_for("gemini-2.5-flash-preview-tts") is not None
    assert tts_rate_for("gemini-2.5-pro-preview-tts").output_per_mtok == 20.00
    assert tts_rate_for("gemini-3.1-flash-tts-preview") is not None
    assert tts_rate_for("gemini-2.5-flash") is None  # not a TTS model


def test_anthropic_event_cost():
    # Sonnet at 3.00/15.00 with 1M input + 100k output = $3 + $1.50 = $4.50
    e = {
        "kind": "model",
        "name": "claude-sonnet-4-6",
        "input_tokens": 1_000_000,
        "output_tokens": 100_000,
    }
    assert abs(event_cost(e) - 4.50) < 1e-6


def test_tts_event_cost_flash():
    # gemini-2.5-flash TTS: $0.50/MTok input, $10/MTok output (audio).
    # 1000 chars input → 250 input tokens (4 chars/tok) → cost $0.000125
    # 60 seconds audio → 1500 audio tokens → cost $0.015
    # total ≈ $0.015125
    e = {
        "kind": "tts",
        "name": "gemini-2.5-flash-preview-tts",
        "input_chars": 1000,
        "output_audio_ms": 60_000,
    }
    expected = 0.000125 + 0.015
    assert abs(event_cost(e) - expected) < 1e-9


def test_tts_event_cost_pro_double_flash():
    e_flash = {
        "kind": "tts",
        "name": "gemini-2.5-flash-preview-tts",
        "input_chars": 4000,
        "output_audio_ms": 30_000,
    }
    e_pro = {**e_flash, "name": "gemini-2.5-pro-preview-tts"}
    assert abs(event_cost(e_pro) - 2 * event_cost(e_flash)) < 1e-9


def test_unknown_model_costs_zero():
    e = {"kind": "model", "name": "future-model-x", "input_tokens": 100}
    assert event_cost(e) == 0.0
    e_tts = {"kind": "tts", "name": "future-tts-y", "input_chars": 100}
    assert event_cost(e_tts) == 0.0


def test_tool_event_costs_zero():
    e = {"kind": "tool", "name": "search_openalex", "duration_s": 2.5}
    assert event_cost(e) == 0.0


def test_3_1_flash_marked_estimated():
    """Public pricing for Gemini 3.1 Flash TTS isn't published as of this
    commit. Cost reports must flag it; if the rate becomes verified the
    flag should be removed in pricing.py and this assertion updated."""
    assert "gemini-3.1-flash-tts-preview" in ESTIMATED_RATES
