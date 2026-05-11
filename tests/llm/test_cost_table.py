"""Cost-table tests."""
from __future__ import annotations

import logging

from enrichment.llm import cost_table


def test_anthropic_haiku_pricing() -> None:
    pricing = cost_table.get_pricing(
        "anthropic", "claude-haiku-4-5-20251001",
    )
    assert pricing is not None
    assert pricing.input_per_m == 1.00
    assert pricing.output_per_m == 5.00


def test_unknown_model_returns_none_and_warns_once(
    caplog: logging.LogRecord,
) -> None:
    # Clear the dedup set so this test is idempotent in either ordering.
    cost_table._warned_unknown.clear()  # pyright: ignore[reportPrivateUsage]
    with caplog.at_level(logging.WARNING):  # type: ignore[attr-defined]
        a = cost_table.get_pricing("openai_compatible", "unique-test-model")
        b = cost_table.get_pricing("openai_compatible", "unique-test-model")
    assert a is None and b is None
    warnings = [
        r for r in caplog.records  # type: ignore[attr-defined]
        if "unique-test-model" in r.message
    ]
    assert len(warnings) == 1, "should warn once, not twice"


def test_cost_for_haiku_one_shot() -> None:
    # 1M input + 1M output on Haiku = $1 + $5 = $6
    cost = cost_table.cost_for(
        "anthropic", "claude-haiku-4-5-20251001",
        input_tokens=1_000_000, output_tokens=1_000_000,
    )
    assert cost == 6.0


def test_cost_for_haiku_native_batch_half_price() -> None:
    """Anthropic native batch = 50% off both input and output."""
    cost = cost_table.cost_for(
        "anthropic", "claude-haiku-4-5-20251001",
        input_tokens=1_000_000, output_tokens=1_000_000,
        execution_mode="native_batch",
    )
    assert cost == 3.0


def test_cost_for_unknown_model_is_none() -> None:
    cost = cost_table.cost_for(
        "openai_compatible", "another-unique-test-model",
        input_tokens=1_000, output_tokens=500,
    )
    assert cost is None


def test_cost_for_none_tokens_is_none() -> None:
    """If usage isn't reported by the provider, cost is unknown."""
    cost = cost_table.cost_for(
        "anthropic", "claude-haiku-4-5-20251001",
        input_tokens=None, output_tokens=None,
    )
    assert cost is None


def test_deepinfra_gemma_4_26b_moe_pricing() -> None:
    """Sanity-check the survey-validated DeepInfra Gemma 4 26B-A4B
    price."""
    pricing = cost_table.get_pricing(
        "openai_compatible", "google/gemma-4-26B-A4B-it",
    )
    assert pricing is not None
    assert pricing.input_per_m == 0.07
    assert pricing.output_per_m == 0.34
