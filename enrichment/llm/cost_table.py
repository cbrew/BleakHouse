"""Per-model price table for cost telemetry.

Brittle by design — vendors change prices and we update by hand.
The cost is bounded by the value: knowing the per-task per-model
spend is cheap (a Python dict lookup) and valuable (it makes
provider-substitution decisions quantifiable rather than vibes-
based).

Prices are USD per 1M tokens. `cache_write` and `cache_read` are
Anthropic-specific; non-Anthropic providers leave them as None.

Unknown models are not an error — we log a warning once and return
None for the cost. The calling code persists `estimated_cost_usd=None`
in the manifest, which is honest about not knowing rather than
papering over with a wrong number.

Update protocol: when a model is added/repriced, edit this file and
note the date in a comment.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelPricing:
    input_per_m: float          # USD per 1M input tokens
    output_per_m: float         # USD per 1M output tokens
    cache_write_per_m: float | None = None
    cache_read_per_m: float | None = None


# Verified 2026-05-11 against vendor pricing pages.
# When a model isn't listed, `cost_for` returns None and warns once.
_PRICES: dict[tuple[str, str], ModelPricing] = {
    # provider, model id (as appears in API calls)

    # Anthropic — verified at claude.com/pricing as of 2026-05-11.
    # Batch discount = 50% off both input and output; calculated at
    # call time by the caller (execution_mode='native_batch').
    ("anthropic", "claude-haiku-4-5-20251001"): ModelPricing(
        input_per_m=1.00, output_per_m=5.00,
        cache_write_per_m=0.30, cache_read_per_m=0.10,
    ),
    ("anthropic", "claude-sonnet-4-6"): ModelPricing(
        input_per_m=3.00, output_per_m=15.00,
        cache_write_per_m=3.75, cache_read_per_m=0.30,
    ),

    # DeepInfra — verified at deepinfra.com/models as of 2026-05-11.
    ("openai_compatible", "meta-llama/Meta-Llama-3.1-8B-Instruct"): ModelPricing(
        input_per_m=0.02, output_per_m=0.05,
    ),
    ("openai_compatible", "meta-llama/Llama-3.3-70B-Instruct-Turbo"): ModelPricing(
        input_per_m=0.10, output_per_m=0.32,
    ),
    ("openai_compatible", "Qwen/Qwen2.5-72B-Instruct"): ModelPricing(
        input_per_m=0.36, output_per_m=0.40,
    ),
    ("openai_compatible", "google/gemma-4-26B-A4B-it"): ModelPricing(
        input_per_m=0.07, output_per_m=0.34,
    ),
    ("openai_compatible", "google/gemma-4-31B-it"): ModelPricing(
        input_per_m=0.13, output_per_m=0.38,
    ),
    ("openai_compatible", "google/gemma-3-4b-it"): ModelPricing(
        input_per_m=0.04, output_per_m=0.08,
    ),
    ("openai_compatible", "nvidia/NVIDIA-Nemotron-Nano-9B-v2"): ModelPricing(
        input_per_m=0.04, output_per_m=0.16,
    ),
    ("openai_compatible", "deepseek-ai/DeepSeek-V3.2"): ModelPricing(
        input_per_m=0.26, output_per_m=0.38,
    ),
}


_warned_unknown: set[tuple[str, str]] = set()


def get_pricing(provider: str, model: str) -> ModelPricing | None:
    """Return the price table entry for (provider, model), or None
    if unknown. Warns once per unknown key."""
    key = (provider, model)
    if key in _PRICES:
        return _PRICES[key]
    if key not in _warned_unknown:
        _warned_unknown.add(key)
        logger.warning(
            "unknown pricing for provider=%r model=%r; "
            "cost will be recorded as None. "
            "Add to enrichment/llm/cost_table.py to fix.",
            provider, model,
        )
    return None


def cost_for(
    provider: str,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    *,
    execution_mode: str = "one_shot",
) -> float | None:
    """Compute total USD cost for a call. Returns None when pricing
    is unknown OR when token counts are None.

    Applies the 50% batch discount to Anthropic native_batch.
    Other providers' batch APIs are treated separately (their
    discounted pricing is recorded as a distinct price entry when
    we exercise that path).
    """
    if input_tokens is None or output_tokens is None:
        return None
    pricing = get_pricing(provider, model)
    if pricing is None:
        return None
    cost = (
        input_tokens * pricing.input_per_m / 1_000_000
        + output_tokens * pricing.output_per_m / 1_000_000
    )
    if execution_mode == "native_batch" and provider == "anthropic":
        cost *= 0.5
    return cost
