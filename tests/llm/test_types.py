"""Smoke tests for the seam's dataclasses."""
from __future__ import annotations

from enrichment.llm.types import (
    GenerationRequest,
    GenerationResult,
    ModelSpec,
    ProviderCapabilities,
)


def test_model_spec_has_required_fields() -> None:
    spec = ModelSpec(
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        hosting="anthropic",
    )
    assert spec.provider == "anthropic"
    assert spec.model == "claude-haiku-4-5-20251001"
    assert spec.hosting == "anthropic"
    assert spec.base_url is None


def test_model_spec_base_url_optional() -> None:
    spec = ModelSpec(
        provider="openai_compatible",
        model="meta-llama/Meta-Llama-3.1-8B-Instruct",
        hosting="deepinfra",
        base_url="https://api.deepinfra.com/v1/openai",
    )
    assert spec.base_url == "https://api.deepinfra.com/v1/openai"


def test_provider_capabilities_flags() -> None:
    caps = ProviderCapabilities(
        json_schema_constrained=True,
        json_schema_strict=False,
        tool_use=True,
        native_batch=True,
        context_window=200_000,
    )
    assert caps.json_schema_constrained
    assert not caps.json_schema_strict
    assert caps.tool_use
    assert caps.native_batch
    assert caps.context_window == 200_000


def test_generation_request_minimal() -> None:
    req = GenerationRequest(
        task="passage_enrichment",
        system=None,
        user="hello",
        max_tokens=100,
    )
    assert req.task == "passage_enrichment"
    assert req.system is None
    assert req.user == "hello"
    assert req.json_schema is None
    assert req.temperature is None


def test_generation_request_with_schema() -> None:
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
    req = GenerationRequest(
        task="x",
        system="be brief",
        user="give me an integer",
        max_tokens=50,
        json_schema=schema,
        temperature=0.0,
    )
    assert req.json_schema == schema
    assert req.temperature == 0.0


def test_generation_result_default_execution_mode() -> None:
    r = GenerationResult(
        text="ok",
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        hosting="anthropic",
        input_tokens=100,
        output_tokens=20,
        estimated_cost_usd=0.0001,
    )
    assert r.execution_mode == "one_shot"
    assert r.raw is None


def test_generation_result_unknown_cost() -> None:
    """When provider/model isn't in the cost table, estimated_cost_usd
    is None — the seam records 'we don't know' rather than guessing."""
    r = GenerationResult(
        text="ok",
        provider="openai_compatible",
        model="some-unknown-model",
        hosting="some-host",
        input_tokens=None,
        output_tokens=None,
        estimated_cost_usd=None,
    )
    assert r.estimated_cost_usd is None
