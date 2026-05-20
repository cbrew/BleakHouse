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

    # OpenAI — first-party. Pricing per openai.com/api/pricing
    # (verified 2026-05-12). gpt-4o-mini is the cheap-tier
    # cross-check against open-weight DeepInfra candidates.
    # cache_read_per_m for OpenAI = half the input rate (their
    # documented automatic prompt-cache discount for gpt-4o family).
    ("openai_compatible", "gpt-4o-mini"): ModelPricing(
        input_per_m=0.15, output_per_m=0.60,
        cache_read_per_m=0.075,
    ),
    # GPT-5 family — pricing per openai.com/api/pricing and the
    # devtk.ai pricing tracker (verified 2026-05-14). These are the
    # recommended cheap-tier (gpt-5-mini) and prose-tier (gpt-5.4)
    # picks for the OpenAI parallel pipeline (docs/openai_execution_plan.md).
    # gpt-5-mini's cache_read_per_m is not separately published; left
    # None until measured empirically.
    ("openai_compatible", "gpt-5-mini"): ModelPricing(
        input_per_m=0.25, output_per_m=2.00,
    ),
    ("openai_compatible", "gpt-5.4"): ModelPricing(
        input_per_m=2.50, output_per_m=15.00,
        cache_read_per_m=0.25,
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
    # Newer Qwen 3 variants (verified 2026-05-12 against
    # deepinfra.com/Qwen/Qwen3-* model pages).
    ("openai_compatible", "Qwen/Qwen3-235B-A22B-Instruct-2507"): ModelPricing(
        input_per_m=0.071, output_per_m=0.10,
    ),
    ("openai_compatible", "Qwen/Qwen3-32B"): ModelPricing(
        input_per_m=0.08, output_per_m=0.28,
    ),
    # Qwen 3.6 small-MoE (35B total / 3B active). Verified 2026-05-12
    # via deepinfra.com/models. Cache pricing not advertised; if
    # DeepInfra silently caches, we'll see it via provider_reported_cost.
    # Requires extra_body={"chat_template_kwargs": {"enable_thinking": False}}
    # to suppress thinking mode (Qwen 3.5+ docs).
    ("openai_compatible", "Qwen/Qwen3.6-35B-A3B"): ModelPricing(
        input_per_m=0.15, output_per_m=0.95,
    ),
    # Qwen 3-Next 80B-A3B Instruct (80B total / 3B active MoE).
    # Apache 2.0. 262k context (extensible). Verified 2026-05-12:
    # $0.09 in / $1.10 out. Explicit -Instruct variant — no thinking
    # disable flag needed; emits to content cleanly.
    ("openai_compatible", "Qwen/Qwen3-Next-80B-A3B-Instruct"): ModelPricing(
        input_per_m=0.09, output_per_m=1.10,
    ),
    ("openai_compatible", "google/gemma-4-26B-A4B-it"): ModelPricing(
        input_per_m=0.07, output_per_m=0.34,
    ),
    ("openai_compatible", "google/gemma-4-31B-it"): ModelPricing(
        input_per_m=0.13, output_per_m=0.38,
    ),
    # GLM-4.7-Flash (Zhipu AI / 30B total / 3B active MoE).
    # Verified 2026-05-12: cache_read $0.01 — the only DeepInfra entry
    # advertising explicit prefix-cache pricing in our shortlist.
    ("openai_compatible", "zai-org/GLM-4.7-Flash"): ModelPricing(
        input_per_m=0.06, output_per_m=0.40,
        cache_read_per_m=0.01,
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

    # Alibaba DashScope (intl Singapore). qwen-plus tiered: ≤256K input
    # is $0.40 in / $1.20 out; 256K-1M tier is 3x. We bill the ≤256K
    # rate here — Phase 2.5 / Phase 3 chunks stay well within that
    # bucket. Batch is 50% off (file API) but broken for our schema;
    # the realtime rate below is what we actually pay (BleakHouse-el1j).
    ("openai_compatible", "qwen-plus"): ModelPricing(
        input_per_m=0.40, output_per_m=1.20,
    ),
    # DeepSeek-V4-Flash (284B total / 13B active MoE). Apache 2.0.
    # 1M context. Verified 2026-05-12 via deepinfra.com/models page:
    # $0.14 in / $0.28 out, cached $0.028.
    ("openai_compatible", "deepseek-ai/DeepSeek-V4-Flash"): ModelPricing(
        input_per_m=0.14, output_per_m=0.28,
        cache_read_per_m=0.028,
    ),
    # OpenAI gpt-oss open-weights family, Apache 2.0. Pricing per
    # artificialanalysis.ai/models/gpt-oss-{120b,20b}/providers
    # (verified 2026-05-13). DeepInfra is the cheapest documented
    # provider for both sizes.
    ("openai_compatible", "openai/gpt-oss-120b"): ModelPricing(
        input_per_m=0.04, output_per_m=0.19,
    ),
    ("openai_compatible", "openai/gpt-oss-20b"): ModelPricing(
        input_per_m=0.03, output_per_m=0.14,
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
    cache_creation_input_tokens: int | None = None,
    cache_read_input_tokens: int | None = None,
    provider_reported_cost: float | None = None,
) -> float | None:
    """Compute total USD cost for a call. Returns None when pricing
    is unknown OR when token counts are None.

    Cache accounting is *provider-aware*. The semantics of input_tokens
    differ between providers:

    - **Anthropic**: usage.input_tokens is the NON-cached input.
      cache_creation_input_tokens and cache_read_input_tokens are
      reported separately. Total billable input ≈
      input + cache_create * 1.25× + cache_read * 0.1×.

    - **OpenAI**: usage.prompt_tokens is the TOTAL input, and
      prompt_tokens_details.cached_tokens (passed here as
      cache_read_input_tokens) is the subset billed at the cache_read
      rate. Total cost = (input − cached) × full + cached × cache_read.

    - **DeepInfra**: ships usage.estimated_cost — their own
      authoritative bill. When passed in as provider_reported_cost we
      return it directly without recomputing.

    Applies the 50% batch discount to Anthropic native_batch.
    """
    if provider_reported_cost is not None:
        # DeepInfra (and any future provider that bills its own cost)
        # is the source of truth. Don't second-guess.
        cost = provider_reported_cost
        if execution_mode == "native_batch" and provider == "anthropic":
            cost *= 0.5
        return cost

    if input_tokens is None or output_tokens is None:
        return None
    pricing = get_pricing(provider, model)
    if pricing is None:
        return None

    cache_create = cache_creation_input_tokens or 0
    cache_read = cache_read_input_tokens or 0

    if provider == "anthropic":
        # Anthropic input_tokens excludes cached; add cache_creation and
        # cache_read separately at their priced rates.
        cost = (
            input_tokens * pricing.input_per_m
            + cache_create * (pricing.cache_write_per_m or pricing.input_per_m)
            + cache_read * (pricing.cache_read_per_m or pricing.input_per_m)
            + output_tokens * pricing.output_per_m
        ) / 1_000_000
    else:
        # OpenAI-compat: input_tokens is the total; cached subset
        # billed at cache_read rate.
        non_cached = max(0, input_tokens - cache_read)
        cache_read_rate = pricing.cache_read_per_m
        if cache_read_rate is None:
            # No documented cache_read price → assume full rate for
            # cached tokens too. Honest over-estimate.
            cache_read_rate = pricing.input_per_m
        cost = (
            non_cached * pricing.input_per_m
            + cache_read * cache_read_rate
            + output_tokens * pricing.output_per_m
        ) / 1_000_000

    if execution_mode == "native_batch" and provider == "anthropic":
        cost *= 0.5
    return cost
