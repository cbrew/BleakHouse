"""OpenAI-compatible provider implementation.

Targets any endpoint that speaks the OpenAI Chat Completions REST
shape: DeepInfra, Together, Fireworks, Groq, Cerebras, NVIDIA NIM,
Novita, Featherless-AI, plus self-hosted vLLM on Modal / Runpod /
GKE. The provider uses the official `openai` Python client with a
configurable `base_url`, so capability differences across providers
show up as 4xx responses rather than as silently-wrong behaviour.

Structured output:
    OpenAI's shape is
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "<schema-id>",
            "schema": {...},
            "strict": <bool>,
        },
    }

The seam picks `name` from the schema's title (falling back to a
fixed string when absent) and `strict` from the hosting's capability
flag — providers that don't honour strict get `strict=False` so we
don't ask for behaviour they won't deliver.

API key resolution:
    Per-hosting env var lookup (DEEPINFRA_API_KEY, TOGETHER_API_KEY,
    etc.). The provider doesn't enforce key presence — callers that
    don't need network calls (unit tests with FakeOpenAIClient) skip
    the env var entirely. A real call without a key produces an
    OpenAI authentication error.

Dependency injection:
    `client` argument lets tests pass a FakeOpenAIClient without
    importing the real SDK or hitting the network.

Cached clients:
    For repeated calls to the same hosting+base_url, the provider
    reuses the OpenAI client. The cache key is (base_url, api_key).
"""
from __future__ import annotations

import os
from typing import Any, Protocol

from enrichment.llm.cost_table import cost_for
from enrichment.llm.capabilities import for_hosting
from enrichment.llm.types import GenerationRequest, GenerationResult, ModelSpec


# Hosting → env-var-name for the API key. Override-friendly: an
# operator that wants to share one key across hostings sets the
# specific env var to the shared key.
_API_KEY_ENV: dict[str, str] = {
    "deepinfra": "DEEPINFRA_API_KEY",
    "together": "TOGETHER_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "groq": "GROQ_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "novita": "NOVITA_API_KEY",
    "featherless": "FEATHERLESS_API_KEY",
    # Self-hosted endpoints don't usually require auth, but some
    # deployments do. Env vars exist so operators can wire them up.
    "modal": "MODAL_VLLM_API_KEY",
    "runpod": "RUNPOD_VLLM_API_KEY",
    "gke": "GKE_VLLM_API_KEY",
}


class _OpenAIClientProto(Protocol):
    """Minimal subset of openai.OpenAI used by the provider.

    Tests pass a FakeOpenAIClient implementing this surface; no
    `openai` SDK import required for unit tests.
    """

    @property
    def chat(self) -> Any: ...


class OpenAICompatibleProvider:
    """OpenAI-compatible REST provider with configurable base_url.

    Stateless beyond a small client cache: `generate(spec, request)`
    looks up or constructs a client for `(spec.base_url,
    spec.hosting)` and invokes chat.completions.create.
    """

    def __init__(
        self,
        client: _OpenAIClientProto | None = None,
    ) -> None:
        # If a specific client was injected, use it for all calls
        # (single-hosting test mode). Otherwise the provider caches
        # clients per (base_url, api_key) tuple.
        self._injected_client = client
        self._cache: dict[tuple[str | None, str | None], _OpenAIClientProto] = {}

    def _client_for(self, spec: ModelSpec) -> _OpenAIClientProto:
        if self._injected_client is not None:
            return self._injected_client

        # load_dotenv() is called defensively here: the BleakHouse
        # convention is that callers (run_pipeline.py etc.) call it at
        # startup, but a fresh caller of the seam may not. Idempotent;
        # won't override env vars already set.
        from dotenv import load_dotenv
        load_dotenv()

        api_key_env = _API_KEY_ENV.get(spec.hosting)
        api_key = os.environ.get(api_key_env) if api_key_env else None
        cache_key = (spec.base_url, api_key)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        # Lazy real-client construction.
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=spec.base_url)
        self._cache[cache_key] = client
        return client

    def generate(
        self,
        spec: ModelSpec,
        request: GenerationRequest,
    ) -> GenerationResult:
        """Run a one-shot generation and return a provider-neutral
        GenerationResult."""
        client = self._client_for(spec)

        messages: list[dict[str, str]] = []
        if request.system is not None:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.user})

        kwargs: dict[str, Any] = {
            "model": spec.model,
            "max_tokens": request.max_tokens,
            "messages": messages,
        }
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.json_schema is not None:
            caps = for_hosting(spec.hosting)
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": _schema_name(request.json_schema),
                    "schema": request.json_schema,
                    "strict": caps.json_schema_strict,
                },
            }

        response = client.chat.completions.create(**kwargs)

        text = _extract_text(response)
        input_tokens, output_tokens = _extract_token_counts(response)

        return GenerationResult(
            text=text,
            provider="openai_compatible",
            model=spec.model,
            hosting=spec.hosting,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=cost_for(
                "openai_compatible", spec.model,
                input_tokens, output_tokens,
            ),
            execution_mode="one_shot",
            raw=response,
        )


def _schema_name(schema: dict[str, Any]) -> str:
    """OpenAI's json_schema config requires a `name` field. Use the
    schema's title when present; fall back to a fixed marker."""
    title = schema.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return "response_schema"


def _extract_text(response: Any) -> str:
    """OpenAI response → choices[0].message.content."""
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    msg = getattr(choices[0], "message", None)
    if msg is None:
        return ""
    content = getattr(msg, "content", None)
    if isinstance(content, str):
        return content
    return ""


def _extract_token_counts(response: Any) -> tuple[int | None, int | None]:
    """OpenAI response → (input_tokens, output_tokens).

    OpenAI uses `prompt_tokens` / `completion_tokens` on the usage
    object; we map them to the seam's input_/output_tokens fields.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return None, None
    return (
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "completion_tokens", None),
    )
