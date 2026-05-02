"""Per-model price table for cost reporting.

Single source of truth for $/MTok rates across the pipeline's LLM and
TTS providers. Update the dict values here when provider rates change;
all cost-reporting scripts (scripts/timings_summary.py) read from this
module.

Sources:
  Anthropic (Haiku 4.5 / Sonnet 4.6) — https://www.anthropic.com/pricing
  Gemini 2.5 Flash/Pro Preview TTS  — https://ai.google.dev/gemini-api/docs/pricing
  Gemini 3.1 Flash TTS Preview      — pricing not yet published; copied
                                       from 2.5 Flash as a working
                                       estimate. Update when official
                                       rates ship.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnthropicRate:
    input_per_mtok: float
    output_per_mtok: float


@dataclass(frozen=True)
class TTSRate:
    """Gemini-style TTS billing.

    Input is metered per text token (~chars_per_token characters per
    token). Output is metered per audio token; Gemini emits roughly
    audio_tokens_per_sec audio tokens per second of synthesised audio.
    """

    input_per_mtok: float
    output_per_mtok: float
    chars_per_token: int = 4
    audio_tokens_per_sec: int = 25


# Anthropic models indexed by family — name-substring match in
# anthropic_rate_for(model_id).
ANTHROPIC_RATES: dict[str, AnthropicRate] = {
    "haiku":  AnthropicRate(input_per_mtok=1.00, output_per_mtok=5.00),
    "sonnet": AnthropicRate(input_per_mtok=3.00, output_per_mtok=15.00),
    "opus":   AnthropicRate(input_per_mtok=15.00, output_per_mtok=75.00),
}

# Gemini TTS models indexed by exact model id — these come back verbatim
# from the response, so an exact match is fine.
TTS_RATES: dict[str, TTSRate] = {
    "gemini-2.5-flash-preview-tts": TTSRate(
        input_per_mtok=0.50, output_per_mtok=10.00,
    ),
    "gemini-2.5-pro-preview-tts": TTSRate(
        input_per_mtok=1.00, output_per_mtok=20.00,
    ),
    # 3.1 Flash TTS public pricing not yet posted; using 2.5 Flash as a
    # working estimate. Mark as such on cost reports so readers know.
    "gemini-3.1-flash-tts-preview": TTSRate(
        input_per_mtok=0.50, output_per_mtok=10.00,
    ),
}

# Models whose pricing is an estimate rather than an officially published
# rate. timings_summary.py flags these in the report.
ESTIMATED_RATES: frozenset[str] = frozenset({
    "gemini-3.1-flash-tts-preview",
})


def anthropic_rate_for(model_id: str) -> AnthropicRate | None:
    """Match an Anthropic model id to its rate by family substring."""
    n = model_id.lower()
    for family, rate in ANTHROPIC_RATES.items():
        if family in n:
            return rate
    return None


def tts_rate_for(model_id: str) -> TTSRate | None:
    """Look up a TTS model rate by exact id."""
    return TTS_RATES.get(model_id)


def event_cost(event: dict) -> float:
    """Cost in USD for a single CallEvent dict (kind=model | tool | tts)."""
    name = event.get("name", "")
    kind = event.get("kind", "")
    if kind == "tts":
        rate = tts_rate_for(name)
        if rate is None:
            return 0.0
        in_tok = event.get("input_chars", 0) / rate.chars_per_token
        audio_s = event.get("output_audio_ms", 0) / 1000
        out_tok = audio_s * rate.audio_tokens_per_sec
        return (
            in_tok * rate.input_per_mtok / 1_000_000
            + out_tok * rate.output_per_mtok / 1_000_000
        )
    if kind == "model":
        rate = anthropic_rate_for(name)
        if rate is None:
            return 0.0
        return (
            event.get("input_tokens", 0) * rate.input_per_mtok / 1_000_000
            + event.get("output_tokens", 0) * rate.output_per_mtok / 1_000_000
        )
    return 0.0
