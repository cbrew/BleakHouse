"""Client facade tests — task resolution + provider dispatch."""
from __future__ import annotations

from dataclasses import dataclass

from enrichment.llm import client, settings
from enrichment.llm.types import (
    GenerationRequest,
    GenerationResult,
    ModelSpec,
)


@dataclass
class _FakeProvider:
    """Captures the (spec, request) pair and returns a canned result."""

    last_spec: ModelSpec | None = None
    last_request: GenerationRequest | None = None

    def generate(
        self, spec: ModelSpec, request: GenerationRequest,
    ) -> GenerationResult:
        self.last_spec = spec
        self.last_request = request
        return GenerationResult(
            text="fake response",
            provider=spec.provider,
            model=spec.model,
            hosting=spec.hosting,
            input_tokens=10,
            output_tokens=5,
            estimated_cost_usd=0.0,
        )


def test_generate_dispatches_to_anthropic_provider() -> None:
    fake = _FakeProvider()
    req = GenerationRequest(
        task="passage_enrichment",
        system="s",
        user="u",
        max_tokens=100,
    )
    result = client.generate(req, provider=fake)  # type: ignore[arg-type]

    assert result.text == "fake response"
    assert fake.last_spec is not None
    assert fake.last_spec.provider == "anthropic"
    assert fake.last_spec.model == "claude-haiku-4-5-20251001"
    assert fake.last_request is req


def test_generate_routes_via_settings_for_task() -> None:
    """Different tasks resolve to different ModelSpecs."""
    fake = _FakeProvider()
    req = GenerationRequest(
        task="generate_podcast",  # Sonnet 4.6, not Haiku
        system="s",
        user="u",
        max_tokens=100,
    )
    client.generate(req, provider=fake)  # type: ignore[arg-type]
    assert fake.last_spec is not None
    assert fake.last_spec.model == "claude-sonnet-4-6"


def test_generate_raises_for_unsupported_provider() -> None:
    """Phase 1 supports only Anthropic. Tasks routed to other
    providers must fail loudly, not silently fall back."""
    settings.register_task(
        "test_unsupported_provider",
        ModelSpec(provider="openai_compatible", model="x", hosting="x"),
    )
    req = GenerationRequest(
        task="test_unsupported_provider",
        system="s",
        user="u",
        max_tokens=100,
    )
    try:
        client.generate(req)
    except NotImplementedError as exc:
        assert "openai_compatible" in str(exc)
        assert "Phase 3" in str(exc)
    else:
        raise AssertionError("expected NotImplementedError")


def test_generate_raises_for_unknown_task() -> None:
    """settings.for_task raises KeyError for unknown tasks, which
    propagates through client.generate."""
    req = GenerationRequest(
        task="totally_made_up_task",
        system=None,
        user="u",
        max_tokens=100,
    )
    try:
        client.generate(req)
    except KeyError as exc:
        assert "totally_made_up_task" in str(exc)
    else:
        raise AssertionError("expected KeyError")
