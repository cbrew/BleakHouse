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

import json
import os
from typing import Any, Protocol

from enrichment.llm.cost_table import cost_for
from enrichment.llm.capabilities import for_hosting
from enrichment.llm.types import (
    GenerationRequest,
    GenerationResult,
    ModelSpec,
    ToolCall,
)


# Hosting → env-var-name for the API key. Override-friendly: an
# operator that wants to share one key across hostings sets the
# specific env var to the shared key.
#
# Modal is intentionally NOT in this map: a deployed Modal vLLM
# endpoint at *.modal.run takes no auth header by default, and
# Modal's own credentials (token_id + token_secret) are for
# `modal deploy`, not for calls to the deployed endpoint. Modal-
# hosted specs flow through the provider with api_key=None, which
# the OpenAI SDK accepts. If a Modal endpoint is gated via Modal
# Secrets, the operator wires the auth header manually outside
# this seam.
_API_KEY_ENV: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "deepinfra": "DEEPINFRA_API_KEY",
    "together": "TOGETHER_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "groq": "GROQ_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "novita": "NOVITA_API_KEY",
    "featherless": "FEATHERLESS_API_KEY",
    # Self-hosted endpoints typically do need auth at request time
    # (Runpod hands you an API key with the deploy; GKE depends on
    # how you set up ingress). Modal is the exception — see above.
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
        # timeout=3600 / max_retries=0: long structured-output calls
        # on large open-weight models routinely exceed the SDK's
        # 600-second default; retries are disabled so a client-side
        # timeout fails the call once instead of stretching to
        # ~30 minutes total (3×600s).
        from openai import OpenAI
        client = OpenAI(
            api_key=api_key, base_url=spec.base_url,
            timeout=3600.0, max_retries=0,
        )
        self._cache[cache_key] = client
        return client

    def generate(
        self,
        spec: ModelSpec,
        request: GenerationRequest,
    ) -> GenerationResult:
        """Run a one-shot generation and return a provider-neutral
        GenerationResult.

        If request.tools is set, runs an agentic tool-use loop via Chat
        Completions. (Responses API tool use also exists but introduces a
        reasoning-pairing requirement for gpt-5 family that's
        provider-specific friction; Chat Completions has the same tool
        primitive without that quirk and works uniformly across
        openai-compat hostings.)
        """
        if request.tools:
            return self._generate_with_tools(spec, request)
        return self._generate_one_shot(spec, request)

    def _generate_one_shot(
        self,
        spec: ModelSpec,
        request: GenerationRequest,
    ) -> GenerationResult:
        """Existing structured-output path (no tools)."""
        client = self._client_for(spec)

        messages: list[dict[str, Any]] = []
        if request.system is not None:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.user})

        kwargs: dict[str, Any] = {
            "model": spec.model,
            "messages": messages,
        }
        # OpenAI-native API surface changed for gpt-5 family: requires
        # `max_completion_tokens` (rejects `max_tokens` with 400) and
        # only accepts the default temperature=1 (rejects temperature=0
        # with 400). Third-party openai-compat providers (DeepInfra,
        # Together, etc.) still accept the old shape. Branch on
        # hosting. See bd memory:
        # openai-gpt-5-family-api-surface-differs-from
        if spec.hosting == "openai":
            kwargs["max_completion_tokens"] = request.max_tokens
            # Skip temperature entirely — OpenAI native gpt-5 family
            # rejects explicit values. The default behaviour applies.
            # reasoning_effort is the documented top-level parameter
            # for gpt-5 family. Translate per model — gpt-5-mini accepts
            # minimal|low|medium|high; gpt-5.4 accepts none|low|medium|
            # high|xhigh (rejects 'minimal' with HTTP 400). See
            # docs/structured_output_review.html addendum.
            if request.reasoning_effort is not None:
                kwargs["reasoning_effort"] = _adapt_openai_reasoning_effort(
                    spec.model, request.reasoning_effort,
                )
        else:
            kwargs["max_tokens"] = request.max_tokens
            if request.temperature is not None:
                kwargs["temperature"] = request.temperature
            # For third-party openai-compat providers (DeepInfra), the
            # gpt-oss family takes reasoning_effort via extra_body.
            # See docs/structured_output_review.html supplementary probe.
            if request.reasoning_effort is not None:
                kwargs.setdefault("extra_body", {})
                kwargs["extra_body"]["reasoning_effort"] = request.reasoning_effort
        if request.json_schema is not None:
            schema = request.json_schema
            if request.list_field_caps:
                # Inject maxItems into the JSON Schema for decoder-level
                # cap enforcement. vLLM-backed providers (DeepInfra etc.)
                # use this to prevent decode-time loops on unbounded
                # list[Literal] fields (e.g. emotional_register emitting
                # the same Literal value 100+ times until max_tokens).
                schema = _apply_list_caps_to_schema(
                    schema, request.list_field_caps,
                )
            caps = for_hosting(spec.hosting)
            if caps.json_schema_strict:
                # OpenAI strict mode requires additionalProperties=false on
                # every object. Pydantic doesn't emit it. Inject before
                # sending. Same posture as the Phase 3 alt driver's
                # _strictify (enrichment/phase3_runner.py).
                schema = _strictify_for_openai(schema)
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": _schema_name(schema),
                    "schema": schema,
                    "strict": caps.json_schema_strict,
                },
            }

        response = client.chat.completions.create(**kwargs)

        text = _extract_text(response)
        (
            input_tokens, output_tokens,
            cache_read_tokens, provider_reported_cost,
        ) = _extract_token_counts(response)

        return GenerationResult(
            text=text,
            provider="openai_compatible",
            model=spec.model,
            hosting=spec.hosting,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_input_tokens=None,  # not a concept in OAI-compat
            cache_read_input_tokens=cache_read_tokens,
            provider_reported_cost_usd=provider_reported_cost,
            estimated_cost_usd=cost_for(
                "openai_compatible", spec.model,
                input_tokens, output_tokens,
                cache_read_input_tokens=cache_read_tokens,
                provider_reported_cost=provider_reported_cost,
            ),
            execution_mode="one_shot",
            raw=response,
        )

    def _generate_with_tools(
        self,
        spec: ModelSpec,
        request: GenerationRequest,
    ) -> GenerationResult:
        """Chat-Completions tool-use loop. Per iteration:
          1. Send messages + tools.
          2. If response has tool_calls → execute via tool_executors, append
             assistant message (preserving tool_calls) + role:tool messages
             (one per call, keyed by tool_call_id), repeat.
          3. Else → done; accumulate text.

        Match shape: docs/tool_use_review.html section 2.2 / 2.3 ("OpenAI
        Chat Completions"). gpt-5 family takes the same Chat Completions
        tool primitive — no Responses-API reasoning-pairing required.
        """
        if not request.tool_executors:
            raise ValueError(
                "GenerationRequest.tools set but tool_executors is empty; "
                "the seam can't dispatch calls without executors"
            )

        client = self._client_for(spec)

        tools_payload = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in request.tools
        ]

        messages: list[dict[str, Any]] = []
        if request.system is not None:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.user})

        text_chunks: list[str] = []
        transcript: list[ToolCall] = []
        agg_input = 0
        agg_output = 0
        agg_cache_read = 0
        any_cache_seen = False
        agg_provider_cost: float | None = None
        last_response: Any = None

        for iteration in range(request.max_tool_iterations + 1):
            kwargs: dict[str, Any] = {
                "model": spec.model,
                "messages": messages,
                "tools": tools_payload,
            }
            if spec.hosting == "openai":
                kwargs["max_completion_tokens"] = request.max_tokens
                if request.reasoning_effort is not None:
                    kwargs["reasoning_effort"] = _adapt_openai_reasoning_effort(
                        spec.model, request.reasoning_effort,
                    )
            else:
                kwargs["max_tokens"] = request.max_tokens
                if request.temperature is not None:
                    kwargs["temperature"] = request.temperature
                if request.reasoning_effort is not None:
                    kwargs.setdefault("extra_body", {})
                    kwargs["extra_body"]["reasoning_effort"] = (
                        request.reasoning_effort
                    )

            response = client.chat.completions.create(**kwargs)
            last_response = response

            in_t, out_t, cr_t, prov_cost = _extract_token_counts(response)
            if in_t is not None:
                agg_input += in_t
            if out_t is not None:
                agg_output += out_t
            if cr_t is not None:
                any_cache_seen = True
                agg_cache_read += cr_t
            if prov_cost is not None:
                agg_provider_cost = (agg_provider_cost or 0.0) + prov_cost

            choice = response.choices[0]
            message = choice.message
            content = getattr(message, "content", None)
            if isinstance(content, str) and content:
                text_chunks.append(content)

            tool_calls = getattr(message, "tool_calls", None) or []
            if not tool_calls:
                break

            # Echo the assistant message back (per Chat Completions tool spec
            # — assistant turn must precede role:tool responses to it).
            # The SDK gives objects; we serialise to plain dicts so the next
            # send re-validates the schema and we don't depend on SDK-version
            # tool_call dataclass shapes.
            assistant_msg: dict[str, Any] = {"role": "assistant"}
            if isinstance(content, str) and content:
                assistant_msg["content"] = content
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ]
            messages.append(assistant_msg)

            for tc in tool_calls:
                tool_name = tc.function.name
                raw_args = tc.function.arguments or "{}"
                try:
                    parsed_args = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError:
                    parsed_args = {}
                executor = request.tool_executors.get(tool_name)
                if executor is None:
                    output = f"tool error: no executor registered for {tool_name!r}"
                else:
                    try:
                        output = executor(parsed_args)
                    except Exception as exc:  # noqa: BLE001
                        output = f"tool error: {exc.__class__.__name__}: {exc}"
                transcript.append(ToolCall(
                    name=tool_name,
                    arguments=dict(parsed_args) if isinstance(parsed_args, dict) else {},
                    output=output,
                    iteration=iteration,
                ))
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": output,
                })

        return GenerationResult(
            text="\n".join(text_chunks),
            provider="openai_compatible",
            model=spec.model,
            hosting=spec.hosting,
            input_tokens=agg_input or None,
            output_tokens=agg_output or None,
            cache_creation_input_tokens=None,
            cache_read_input_tokens=agg_cache_read if any_cache_seen else None,
            provider_reported_cost_usd=agg_provider_cost,
            estimated_cost_usd=cost_for(
                "openai_compatible", spec.model, agg_input, agg_output,
                cache_read_input_tokens=agg_cache_read if any_cache_seen else None,
                provider_reported_cost=agg_provider_cost,
            ),
            execution_mode="one_shot",
            tool_transcript=tuple(transcript),
            raw=last_response,
        )


def _adapt_openai_reasoning_effort(model: str, effort: str) -> str:
    """Map a requested effort to a value the specific model accepts.

    gpt-5-mini accepts: minimal | low | medium | high.
    gpt-5.4    accepts: none | low | medium | high | xhigh (rejects 'minimal').
    For unrecognised models, pass through unchanged."""
    if effort == "minimal" and model.startswith("gpt-5.4"):
        return "low"
    return effort


def _strictify_for_openai(schema: Any) -> Any:
    """Walk a JSON Schema dict and add `additionalProperties: false` to every
    object. OpenAI strict json_schema mode requires this; Pydantic-generated
    schemas omit it. Returns a new structure; input is not mutated.

    Same transform as enrichment/phase3_runner.py:_strictify (duplicated
    here to avoid a cross-package import; both copies are 12 lines)."""
    if isinstance(schema, dict):
        out: dict[str, Any] = {}
        for k, v in schema.items():
            out[k] = _strictify_for_openai(v)
        if out.get("type") == "object" and "additionalProperties" not in out:
            out["additionalProperties"] = False
        return out
    if isinstance(schema, list):
        return [_strictify_for_openai(item) for item in schema]
    return schema


def _apply_list_caps_to_schema(
    schema: Any, caps: dict[str, int],
) -> Any:
    """Walk the schema and, for each property named in `caps`, inject
    `maxItems: N` into the property's definition. Returns a new
    structure; input is not mutated.

    Matches by property name regardless of nesting depth. Skips
    properties that already have a maxItems (caller's existing
    constraint wins)."""
    if isinstance(schema, dict):
        out: dict[str, Any] = {}
        for k, v in schema.items():
            if k == "properties" and isinstance(v, dict):
                new_props: dict[str, Any] = {}
                for prop_name, prop_def in v.items():
                    if (prop_name in caps
                            and isinstance(prop_def, dict)
                            and "maxItems" not in prop_def):
                        new_def = dict(prop_def)
                        new_def["maxItems"] = caps[prop_name]
                        new_props[prop_name] = _apply_list_caps_to_schema(
                            new_def, caps,
                        )
                    else:
                        new_props[prop_name] = _apply_list_caps_to_schema(
                            prop_def, caps,
                        )
                out[k] = new_props
            else:
                out[k] = _apply_list_caps_to_schema(v, caps)
        return out
    if isinstance(schema, list):
        return [_apply_list_caps_to_schema(item, caps) for item in schema]
    return schema


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


def _extract_token_counts(
    response: Any,
) -> tuple[int | None, int | None, int | None, float | None]:
    """OpenAI-compatible response → (input_tokens, output_tokens,
    cache_read_input_tokens, provider_reported_cost).

    OpenAI exposes `prompt_tokens` (total input), `completion_tokens`
    (output), and `prompt_tokens_details.cached_tokens` (subset of
    input billed at cache_read rate). All authoritative.

    DeepInfra ships its own `usage.estimated_cost` field (a non-OpenAI
    extension) which is their authoritative bill; they do NOT expose
    cached_tokens (prompt_tokens_details is null in their responses
    per the 2026-05-12 probe). When estimated_cost is present we
    prefer it over recomputation.

    Returns:
        (input_tokens, output_tokens, cache_read_tokens|None,
         provider_reported_cost_usd|None)

    cache_read_tokens is None when the provider doesn't report it at
    all (so the caller can distinguish "0 cached" from "unknown").
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return None, None, None, None

    cache_read: int | None = None
    details = getattr(usage, "prompt_tokens_details", None)
    if details is not None:
        # OpenAI: details.cached_tokens. DeepInfra: details is None
        # so we never reach here for them.
        cached = getattr(details, "cached_tokens", None)
        if cached is not None:
            cache_read = int(cached)

    provider_reported_cost: float | None = None
    raw_cost = getattr(usage, "estimated_cost", None)
    if raw_cost is not None:
        try:
            provider_reported_cost = float(raw_cost)
        except (TypeError, ValueError):
            provider_reported_cost = None

    return (
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "completion_tokens", None),
        cache_read,
        provider_reported_cost,
    )
