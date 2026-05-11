"""AnthropicProvider tests with a fake client (no live network)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from enrichment.llm.providers.anthropic_provider import AnthropicProvider
from enrichment.llm.types import GenerationRequest, ModelSpec


# ── Fake Anthropic client + response objects ─────────────────────


@dataclass
class _FakeUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class _FakeBlock:
    type: str
    text: str


@dataclass
class _FakeResponse:
    content: list[_FakeBlock]
    usage: _FakeUsage


class _FakeMessages:
    def __init__(self) -> None:
        self.last_kwargs: dict[str, Any] | None = None
        self.next_response: _FakeResponse | None = None

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.last_kwargs = kwargs
        assert self.next_response is not None, "set next_response before calling"
        return self.next_response


class _FakeClient:
    def __init__(self) -> None:
        self.messages = _FakeMessages()


def _spec(model: str = "claude-haiku-4-5-20251001") -> ModelSpec:
    return ModelSpec(
        provider="anthropic", model=model, hosting="anthropic",
    )


def _req(json_schema: dict | None = None, **overrides: Any) -> GenerationRequest:
    kwargs: dict[str, Any] = dict(
        task="passage_enrichment",
        system="you are a literary analyst",
        user="analyze this chapter",
        max_tokens=4096,
    )
    kwargs.update(overrides)
    if json_schema is not None:
        kwargs["json_schema"] = json_schema
    return GenerationRequest(**kwargs)


# ── Tests ────────────────────────────────────────────────────────


def test_generate_without_schema_calls_messages_create_no_output_config() -> None:
    """A free-text request should NOT include output_config."""
    client = _FakeClient()
    client.messages.next_response = _FakeResponse(
        content=[_FakeBlock(type="text", text="some prose")],
        usage=_FakeUsage(input_tokens=100, output_tokens=20),
    )
    provider = AnthropicProvider(client=client)
    result = provider.generate(_spec(), _req())

    kwargs = client.messages.last_kwargs
    assert kwargs is not None
    assert kwargs["model"] == "claude-haiku-4-5-20251001"
    assert kwargs["max_tokens"] == 4096
    assert kwargs["system"] == "you are a literary analyst"
    assert kwargs["messages"] == [
        {"role": "user", "content": "analyze this chapter"},
    ]
    assert "output_config" not in kwargs
    assert result.text == "some prose"


def test_generate_with_schema_adds_output_config() -> None:
    """A schema-constrained request must include output_config in
    the Anthropic-native shape: format.type=json_schema, format.schema=..."""
    client = _FakeClient()
    client.messages.next_response = _FakeResponse(
        content=[_FakeBlock(type="text", text='{"ok": true}')],
        usage=_FakeUsage(input_tokens=200, output_tokens=10),
    )
    provider = AnthropicProvider(client=client)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}

    result = provider.generate(_spec(), _req(json_schema=schema))

    kwargs = client.messages.last_kwargs
    assert kwargs is not None
    assert kwargs["output_config"] == {
        "format": {"type": "json_schema", "schema": schema},
    }
    assert result.text == '{"ok": true}'


def test_generate_populates_provenance_and_cost() -> None:
    """The GenerationResult should carry provider/model/hosting,
    token counts, and estimated cost (from cost_table)."""
    client = _FakeClient()
    client.messages.next_response = _FakeResponse(
        content=[_FakeBlock(type="text", text="ok")],
        usage=_FakeUsage(input_tokens=1_000_000, output_tokens=1_000_000),
    )
    provider = AnthropicProvider(client=client)
    result = provider.generate(_spec(), _req())

    assert result.provider == "anthropic"
    assert result.model == "claude-haiku-4-5-20251001"
    assert result.hosting == "anthropic"
    assert result.input_tokens == 1_000_000
    assert result.output_tokens == 1_000_000
    # Haiku 4.5 = $1/M input + $5/M output → $6 on 1M+1M.
    assert result.estimated_cost_usd == 6.0
    assert result.execution_mode == "one_shot"


def test_generate_handles_missing_usage_gracefully() -> None:
    """If the provider doesn't surface token counts, the seam records
    None rather than crashing or guessing."""
    # _FakeResponse without usage — simulate a partial-response case.
    @dataclass
    class _MissingUsage:
        content: list[_FakeBlock]

    client = _FakeClient()
    client.messages.next_response = _MissingUsage(  # type: ignore[assignment]
        content=[_FakeBlock(type="text", text="hello")],
    )
    provider = AnthropicProvider(client=client)
    result = provider.generate(_spec(), _req())

    assert result.input_tokens is None
    assert result.output_tokens is None
    assert result.estimated_cost_usd is None


def test_generate_passes_temperature_when_set() -> None:
    client = _FakeClient()
    client.messages.next_response = _FakeResponse(
        content=[_FakeBlock(type="text", text="ok")],
        usage=_FakeUsage(input_tokens=10, output_tokens=5),
    )
    provider = AnthropicProvider(client=client)
    provider.generate(_spec(), _req(temperature=0.5))
    kwargs = client.messages.last_kwargs
    assert kwargs is not None
    assert kwargs.get("temperature") == 0.5


def test_generate_omits_system_when_none() -> None:
    client = _FakeClient()
    client.messages.next_response = _FakeResponse(
        content=[_FakeBlock(type="text", text="ok")],
        usage=_FakeUsage(input_tokens=10, output_tokens=5),
    )
    provider = AnthropicProvider(client=client)
    req = GenerationRequest(
        task="passage_enrichment", system=None, user="hi", max_tokens=10,
    )
    provider.generate(_spec(), req)
    kwargs = client.messages.last_kwargs
    assert kwargs is not None
    assert "system" not in kwargs
