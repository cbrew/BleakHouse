"""Per-million-token pricing for the models used in this comparison.

Rates fetched 2026-04-22 from the providers' own docs; realtime/uncached
only (no batch discount, no cache hits, no data-residency multiplier).

Sources:
  Anthropic: https://platform.claude.com/docs/en/about-claude/pricing
  Cerebras gpt-oss:  https://inference-docs.cerebras.ai/models/openai-oss
  Cerebras qwen-3:   https://inference-docs.cerebras.ai/models/qwen-3-235b-2507
"""

from __future__ import annotations

from typing import Any

# model_id -> (input_$/MTok, output_$/MTok, source_url)
PRICING: dict[str, tuple[float, float, str]] = {
    "claude-sonnet-4-6": (
        3.00,
        15.00,
        "https://platform.claude.com/docs/en/about-claude/pricing",
    ),
    "gpt-oss-120b": (
        0.35,
        0.75,
        "https://inference-docs.cerebras.ai/models/openai-oss",
    ),
    "cerebras-gpt-oss-120b": (  # plugin model id
        0.35,
        0.75,
        "https://inference-docs.cerebras.ai/models/openai-oss",
    ),
    "qwen-3-235b-a22b-instruct-2507": (
        0.60,
        1.20,
        "https://inference-docs.cerebras.ai/models/qwen-3-235b-2507",
    ),
    "zai-glm-4.7": (
        2.25,
        2.75,
        "https://inference-docs.cerebras.ai/models/zai-glm-47",
    ),
    "gpt-5-mini": (
        0.25,
        2.00,
        "https://platform.openai.com/docs/pricing",
    ),
    "gpt-5.4": (
        2.50,
        15.00,
        "https://platform.openai.com/docs/pricing",
    ),
}

QUOTED_AT = "2026-04-22"


def cost_usd(model_id: str, input_tokens: int, output_tokens: int) -> float | None:
    """Compute cost in USD for one call. Returns None if the model is unpriced."""
    entry = PRICING.get(model_id)
    if entry is None:
        return None
    in_rate, out_rate, _ = entry
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate


def annotate(result: dict[str, Any]) -> dict[str, Any]:
    """Add a `cost` block to a section-run result dict."""
    model_id = result.get("model_id", "")
    metrics = result.get("metrics", {})
    in_tok = metrics.get("input_tokens")
    out_tok = metrics.get("output_tokens")
    if not isinstance(in_tok, int) or not isinstance(out_tok, int):
        return result
    entry = PRICING.get(model_id)
    if entry is None:
        return result
    in_rate, out_rate, src = entry
    usd = cost_usd(model_id, in_tok, out_tok)
    result["cost"] = {
        "usd": usd,
        "input_rate_per_mtok": in_rate,
        "output_rate_per_mtok": out_rate,
        "source": src,
        "quoted_at": QUOTED_AT,
    }
    return result
