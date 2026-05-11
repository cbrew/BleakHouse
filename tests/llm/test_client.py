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


def test_generate_dispatches_to_openai_compatible_provider() -> None:
    """Phase 3: tasks routed to provider='openai_compatible' dispatch
    to the OpenAICompatibleProvider."""
    fake = _FakeProvider()
    settings.register_task(
        "test_oai_dispatch",
        ModelSpec(
            provider="openai_compatible",
            model="meta-llama/Meta-Llama-3.1-8B-Instruct",
            hosting="deepinfra",
            base_url="https://api.deepinfra.com/v1/openai",
        ),
    )
    req = GenerationRequest(
        task="test_oai_dispatch",
        system="s",
        user="u",
        max_tokens=100,
    )
    result = client.generate(req, provider=fake)  # type: ignore[arg-type]
    assert result.provider == "openai_compatible"
    assert result.hosting == "deepinfra"
    assert fake.last_spec is not None
    assert fake.last_spec.base_url == "https://api.deepinfra.com/v1/openai"


def test_generate_raises_for_unknown_provider() -> None:
    """A spec with an unrecognised provider string fails loudly."""
    settings.register_task(
        "test_unknown_provider",
        ModelSpec(provider="some_future_provider", model="x", hosting="x"),
    )
    req = GenerationRequest(
        task="test_unknown_provider",
        system="s",
        user="u",
        max_tokens=100,
    )
    try:
        client.generate(req)
    except NotImplementedError as exc:
        assert "some_future_provider" in str(exc)
    else:
        raise AssertionError("expected NotImplementedError")


def test_generate_capability_check_blocks_schema_on_unsupported_hosting() -> None:
    """When the resolved hosting doesn't advertise json_schema_constrained,
    a structured-output request fails BEFORE any HTTP call."""
    from enrichment.llm.capabilities import CapabilityError
    settings.register_task(
        "test_cap_mismatch",
        ModelSpec(
            provider="openai_compatible",
            model="x",
            hosting="some-unknown-host-without-caps",
        ),
    )
    req = GenerationRequest(
        task="test_cap_mismatch",
        system=None,
        user="u",
        max_tokens=100,
        json_schema={"type": "object"},
    )
    try:
        client.generate(req)
    except CapabilityError as exc:
        assert "json_schema-constrained" in str(exc)
        assert "some-unknown-host-without-caps" in str(exc)
    else:
        raise AssertionError("expected CapabilityError")


def test_generate_capability_check_allows_free_text_on_any_hosting() -> None:
    """No json_schema → no capability check fires, even on a hosting
    that lacks structured-output support."""
    fake = _FakeProvider()
    settings.register_task(
        "test_cap_free_text",
        ModelSpec(
            provider="openai_compatible",
            model="x",
            hosting="another-unknown-host",
        ),
    )
    req = GenerationRequest(
        task="test_cap_free_text",
        system=None,
        user="just text",
        max_tokens=100,
    )
    # Should not raise.
    result = client.generate(req, provider=fake)  # type: ignore[arg-type]
    assert result.text == "fake response"


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
