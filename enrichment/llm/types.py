"""Provider-neutral LLM call types.

Per the migration plan (Principle 1: per-task config, Principle 3:
schema as contract, Principle 5: explicit auditable manifest), the
seam types carry enough metadata that any LLM-backed artifact can
record provider/model/hosting/tokens/cost/execution_mode without
the call site touching provider-specific code.

Provider implementations consume GenerationRequest and produce
GenerationResult. They never see Pydantic model classes — only
JSON Schema dicts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ToolSpec:
    """Provider-neutral tool definition.

    Three providers use three names for the schema field: Anthropic
    `input_schema`, OpenAI Responses `parameters`, OpenAI Chat Completions
    `function.parameters`. We pick Anthropic's name (`input_schema`) since
    that matches the existing host_prep convention; the providers translate
    when sending. See docs/tool_use_review.html for the wire formats.
    """
    name: str
    description: str
    input_schema: dict[str, Any]


# A tool executor maps name → callable. The callable receives the
# already-parsed argument dict (the seam handles JSON-string parsing for
# OpenAI providers transparently — callers never deal with raw arguments).
# It returns a str result; the seam wraps the result into the
# provider-appropriate tool-result block.
#
# Errors should be returned as a string (e.g. "tool error: ..."). Raising
# from the executor will bubble up and abort the loop — fine for
# unrecoverable errors, but for model-recoverable ones (rate limit hit, no
# results found) the string return is the path that lets the model adapt.
ToolExecutor = Callable[[dict[str, Any]], str]


@dataclass(frozen=True)
class ToolCall:
    """One entry in a GenerationResult.tool_transcript. Records what the
    model asked for and what the executor returned, in order of execution.
    The seam guarantees `arguments` is a parsed dict (not a JSON string),
    regardless of provider."""
    name: str
    arguments: dict[str, Any]
    output: str
    iteration: int  # 0-indexed loop turn the call happened on


@dataclass(frozen=True)
class ModelSpec:
    """A (provider, model, endpoint) triple resolved from a task name.

    `hosting` is the substrate identity used for cost telemetry —
    e.g. 'anthropic', 'deepinfra', 'together', 'novita', 'modal',
    'runpod', 'gke'. It distinguishes 'same model on different
    infra' for the cost-per-task-per-hosting manifest field.
    """

    provider: str            # "anthropic" | "openai_compatible"
    model: str
    hosting: str
    base_url: str | None = None


@dataclass(frozen=True)
class ProviderCapabilities:
    """Per-provider capability flags.

    BleakHouse-5b7m (closed): the seam doesn't pretend providers
    have uniform structured-output support. Each provider declares
    what it can do; settings resolution fails loudly at
    configuration time when a task requests a capability the
    configured provider lacks.
    """

    json_schema_constrained: bool
    json_schema_strict: bool          # OpenAI 'strict' semantics; not all providers honor
    tool_use: bool
    native_batch: bool
    context_window: int


@dataclass(frozen=True)
class GenerationRequest:
    """A task-level LLM call request.

    `task` identifies the logical operation (passage_enrichment,
    listener_pick, etc.). The settings layer maps task → ModelSpec.

    `json_schema` is the JSON Schema dict (typically
    `MyPydanticModel.model_json_schema()`) — NOT a Pydantic model
    class. Keep Pydantic in the caller.
    """

    task: str
    system: str | None
    user: str
    max_tokens: int
    json_schema: dict[str, Any] | None = None
    temperature: float | None = None
    # Anthropic prompt caching: when True, the provider attaches a
    # cache_control breakpoint to the system message so repeated calls
    # with the same system prompt hit the cache. No-op for
    # openai_compatible providers (DeepInfra etc. auto-cache by prefix).
    cache_system: bool = False
    # Caller-supplied list-field caps applied at request shaping
    # time per provider. Keys are JSON Schema property names found
    # somewhere in `json_schema` (typically under `$defs/<Model>/
    # properties/<field>`); values are the maximum list length to
    # enforce. The seam intentionally does NOT enforce these in
    # Pydantic (the underlying schema stays liberal so callers can
    # store the model's actual output, including over-cap lists,
    # without validation failures). Each provider chooses how to
    # apply them:
    #   - openai_compatible providers inject `maxItems: N` into the
    #     JSON Schema sent to the decoder. vLLM-backed providers
    #     (DeepInfra, etc.) need this to prevent decode-time loops
    #     on unbounded list[Literal] fields.
    #   - AnthropicProvider injects the cap into the field's
    #     description as "Maximum N items." (Anthropic rejects
    #     `maxItems` outright). Best-effort prompt-level guidance.
    # Both treatments coexist with the existing description text and
    # the schema stripper; if a cap is unsupported by a provider's
    # decoder it falls back to prompt-only.
    list_field_caps: dict[str, int] | None = None
    # Reasoning-effort knob for reasoning-class models. Documented for
    # OpenAI gpt-5 family (accepts "minimal" | "low" | "medium" |
    # "high"; default is medium) and for the gpt-oss family via
    # DeepInfra (low / medium / high; passed as extra_body
    # reasoning_effort). For structured-output extraction tasks
    # "minimal" or "low" is decisively the right setting — see the
    # gpt-oss probe in docs/structured_output_review.html. Ignored by
    # providers/models that don't recognize the parameter.
    reasoning_effort: str | None = None
    # Tool-use support (BleakHouse-otae Subtask C). When `tools` is
    # non-empty, the provider runs an agentic loop: model emits tool
    # calls → seam dispatches via `tool_executors` → results returned
    # to the model → repeat. The loop terminates when the model emits
    # no further tool calls or `max_tool_iterations` is reached.
    #
    # Empirical surprises documented in docs/tool_use_review.html:
    #   - Anthropic gives arguments as a parsed dict; OpenAI as a JSON
    #     string. The seam normalises to dict before calling executors.
    #   - OpenAI Responses requires the prior reasoning items to be
    #     echoed back alongside the function_call when tool_results are
    #     sent; the provider handles this transparently.
    tools: tuple[ToolSpec, ...] | None = None
    tool_executors: dict[str, ToolExecutor] | None = None
    max_tool_iterations: int = 6


@dataclass(frozen=True)
class GenerationResult:
    """Outcome of a single LLM generation.

    `text` is the model's output (raw text or JSON-as-string;
    callers validate with their own Pydantic models if applicable).

    The remaining fields populate the manifest's cost-telemetry
    record per Principle 5 of the migration plan.

    `head_verified` is not present here — that's for the reference-
    verification seam. This seam's per-call audit lives in the
    fields below.
    """

    text: str
    provider: str
    model: str
    hosting: str
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost_usd: float | None
    # Cache telemetry from authoritative response fields. None when the
    # provider's response doesn't expose this dimension (e.g. DeepInfra
    # does not itemise cache hits in its OpenAI-compat usage shape).
    # Anthropic: from usage.cache_creation_input_tokens / cache_read_input_tokens.
    # OpenAI:    cache_read_input_tokens = usage.prompt_tokens_details.cached_tokens
    #            (OpenAI auto-caches; no separate "creation" event).
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    # Provider-reported cost (e.g. DeepInfra includes usage.estimated_cost
    # which is their authoritative bill). estimated_cost_usd above
    # prefers this when present and falls back to cost_for() computation.
    provider_reported_cost_usd: float | None = None
    execution_mode: str = "one_shot"   # "one_shot" | "native_batch" | "portable_batch"
    # Per-call tool-use audit. Empty tuple when the request did not use
    # tools or the model emitted no calls. Populated in the order the model
    # called them across all loop iterations. Each entry records the
    # parsed args (never the JSON-string raw) so audit is provider-neutral.
    tool_transcript: tuple[ToolCall, ...] = ()
    raw: Any | None = field(default=None, repr=False)  # provider-native response for debugging
