"""OpenAICompatibleProvider tests with a fake client (no live network)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from enrichment.llm.providers.openai_compatible_provider import (
    OpenAICompatibleProvider,
)
from enrichment.llm.types import GenerationRequest, ModelSpec


# ── Fake OpenAI client surface ──────────────────────────────────


@dataclass
class _FakeUsage:
    prompt_tokens: int
    completion_tokens: int


@dataclass
class _FakeMessage:
    content: str


@dataclass
class _FakeChoice:
    message: _FakeMessage


@dataclass
class _FakeResponse:
    choices: list[_FakeChoice]
    usage: _FakeUsage


class _FakeCompletions:
    def __init__(self) -> None:
        self.last_kwargs: dict[str, Any] | None = None
        self.next_response: _FakeResponse | None = None

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.last_kwargs = kwargs
        assert self.next_response is not None
        return self.next_response


class _FakeChat:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()


class _FakeClient:
    def __init__(self) -> None:
        self.chat = _FakeChat()


# ── Helpers ──────────────────────────────────────────────────────


def _spec(
    *,
    hosting: str = "deepinfra",
    model: str = "meta-llama/Meta-Llama-3.1-8B-Instruct",
) -> ModelSpec:
    return ModelSpec(
        provider="openai_compatible",
        model=model,
        hosting=hosting,
        base_url="https://api.deepinfra.com/v1/openai",
    )


def _req(
    *,
    json_schema: dict | None = None,
    system: str | None = "you are helpful",
    **overrides: Any,
) -> GenerationRequest:
    kwargs: dict[str, Any] = dict(
        task="passage_enrichment",
        system=system,
        user="hello",
        max_tokens=100,
    )
    kwargs.update(overrides)
    if json_schema is not None:
        kwargs["json_schema"] = json_schema
    return GenerationRequest(**kwargs)


def _canned_response(
    text: str = "hello back",
    *,
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
) -> _FakeResponse:
    return _FakeResponse(
        choices=[_FakeChoice(message=_FakeMessage(content=text))],
        usage=_FakeUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        ),
    )


# ── Tests ────────────────────────────────────────────────────────


def test_generate_without_schema_no_response_format() -> None:
    client = _FakeClient()
    client.chat.completions.next_response = _canned_response()
    provider = OpenAICompatibleProvider(client=client)
    result = provider.generate(_spec(), _req())

    kwargs = client.chat.completions.last_kwargs
    assert kwargs is not None
    assert kwargs["model"] == "meta-llama/Meta-Llama-3.1-8B-Instruct"
    assert kwargs["max_tokens"] == 100
    assert "response_format" not in kwargs
    # System role goes via messages, not a top-level `system` kwarg.
    assert kwargs["messages"] == [
        {"role": "system", "content": "you are helpful"},
        {"role": "user", "content": "hello"},
    ]
    assert result.text == "hello back"


def test_generate_with_schema_sets_openai_response_format() -> None:
    """OpenAI's shape:
    response_format = {"type": "json_schema",
                       "json_schema": {"name": ..., "schema": ...,
                                       "strict": <hosting-cap>}}
    """
    schema = {
        "title": "MyShape",
        "type": "object",
        "properties": {"x": {"type": "integer"}},
    }
    client = _FakeClient()
    client.chat.completions.next_response = _canned_response(text='{"x": 1}')
    provider = OpenAICompatibleProvider(client=client)
    provider.generate(_spec(hosting="deepinfra"), _req(json_schema=schema))

    kwargs = client.chat.completions.last_kwargs
    assert kwargs is not None
    rf = kwargs["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "MyShape"
    assert rf["json_schema"]["schema"] == schema
    # DeepInfra has json_schema_strict=False per capabilities table.
    assert rf["json_schema"]["strict"] is False


def test_generate_with_schema_strict_for_strict_hosting() -> None:
    """Together has json_schema_strict=True → strict flag flows through."""
    schema = {"title": "S", "type": "object"}
    client = _FakeClient()
    client.chat.completions.next_response = _canned_response()
    provider = OpenAICompatibleProvider(client=client)
    provider.generate(
        _spec(hosting="together"),
        _req(json_schema=schema),
    )
    kwargs = client.chat.completions.last_kwargs
    assert kwargs is not None
    assert kwargs["response_format"]["json_schema"]["strict"] is True


def test_generate_schema_without_title_uses_fallback_name() -> None:
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
    client = _FakeClient()
    client.chat.completions.next_response = _canned_response()
    provider = OpenAICompatibleProvider(client=client)
    provider.generate(_spec(), _req(json_schema=schema))

    kwargs = client.chat.completions.last_kwargs
    assert kwargs is not None
    assert kwargs["response_format"]["json_schema"]["name"] == "response_schema"


def test_generate_omits_system_message_when_none() -> None:
    client = _FakeClient()
    client.chat.completions.next_response = _canned_response()
    provider = OpenAICompatibleProvider(client=client)
    provider.generate(_spec(), _req(system=None))

    kwargs = client.chat.completions.last_kwargs
    assert kwargs is not None
    assert kwargs["messages"] == [{"role": "user", "content": "hello"}]


def test_generate_passes_temperature_when_set() -> None:
    client = _FakeClient()
    client.chat.completions.next_response = _canned_response()
    provider = OpenAICompatibleProvider(client=client)
    provider.generate(_spec(), _req(temperature=0.3))

    kwargs = client.chat.completions.last_kwargs
    assert kwargs is not None
    assert kwargs["temperature"] == 0.3


def test_generate_populates_provenance_and_tokens() -> None:
    client = _FakeClient()
    client.chat.completions.next_response = _canned_response(
        prompt_tokens=1_000_000,
        completion_tokens=1_000_000,
    )
    provider = OpenAICompatibleProvider(client=client)
    spec = _spec(
        hosting="deepinfra",
        model="meta-llama/Meta-Llama-3.1-8B-Instruct",
    )
    result = provider.generate(spec, _req())

    assert result.provider == "openai_compatible"
    assert result.model == "meta-llama/Meta-Llama-3.1-8B-Instruct"
    assert result.hosting == "deepinfra"
    assert result.input_tokens == 1_000_000
    assert result.output_tokens == 1_000_000
    # Llama 3.1 8B on DeepInfra = $0.02 + $0.05 = $0.07 on 1M+1M.
    assert result.estimated_cost_usd is not None
    assert abs(result.estimated_cost_usd - 0.07) < 1e-9
    assert result.execution_mode == "one_shot"


def test_generate_handles_missing_usage_gracefully() -> None:
    """Some providers omit usage on streaming/error responses."""
    @dataclass
    class _NoUsageResponse:
        choices: list[_FakeChoice]

    client = _FakeClient()
    client.chat.completions.next_response = _NoUsageResponse(  # type: ignore[assignment]
        choices=[_FakeChoice(message=_FakeMessage(content="x"))],
    )
    provider = OpenAICompatibleProvider(client=client)
    result = provider.generate(_spec(), _req())

    assert result.input_tokens is None
    assert result.output_tokens is None
    assert result.estimated_cost_usd is None


def test_generate_handles_empty_choices() -> None:
    """Defensive: empty choices → empty text, not a crash."""
    client = _FakeClient()
    client.chat.completions.next_response = _FakeResponse(
        choices=[], usage=_FakeUsage(prompt_tokens=10, completion_tokens=0),
    )
    provider = OpenAICompatibleProvider(client=client)
    result = provider.generate(_spec(), _req())
    assert result.text == ""


def test_provider_loads_dotenv_on_real_client_construction(
    monkeypatch,
) -> None:
    """The provider's lazy real-client path calls load_dotenv() before
    reading env vars, so callers don't have to remember to invoke
    load_dotenv themselves.

    Verified by replacing dotenv.load_dotenv with a stub that sets a
    sentinel env var, then constructing a provider with no injected
    client and confirming the OpenAI SDK receives the sentinel key.
    """
    monkeypatch.delenv("DEEPINFRA_API_KEY", raising=False)

    # Replace dotenv.load_dotenv with our own that injects a sentinel
    # value into os.environ. This proves the provider IS calling
    # load_dotenv() before its env-var read, regardless of whether a
    # real .env file exists.
    import os as _os
    import dotenv
    load_dotenv_called = {"count": 0}

    def fake_load_dotenv(*_args: Any, **_kw: Any) -> bool:
        load_dotenv_called["count"] += 1
        _os.environ["DEEPINFRA_API_KEY"] = "sentinel-from-fake-load-dotenv"
        return True

    monkeypatch.setattr(dotenv, "load_dotenv", fake_load_dotenv)

    captured: dict[str, Any] = {}

    class _FakeOpenAI:
        def __init__(self, *, api_key: str | None, base_url: str | None) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url

        @property
        def chat(self) -> Any:
            return None  # never called

    import openai
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)

    provider = OpenAICompatibleProvider()  # no injected client
    spec = _spec(hosting="deepinfra")
    provider._client_for(spec)  # pyright: ignore[reportPrivateUsage]

    assert load_dotenv_called["count"] >= 1, "load_dotenv should be called"
    assert captured["api_key"] == "sentinel-from-fake-load-dotenv"
    assert captured["base_url"] == "https://api.deepinfra.com/v1/openai"
