"""Anthropic provider implementation.

Translates a provider-neutral GenerationRequest into an Anthropic
messages.create call, attaches structured-output configuration when
the request carries a json_schema, and packages the response into a
GenerationResult with the cost-telemetry fields populated.

The provider does NOT parse the response into Pydantic models —
that stays in the caller (Principle 3 of the migration plan:
'Pydantic stays in the caller').

Anthropic structured output: per the BleakHouse pattern (verified
in enrichment/test_single.py's pre-migration code), the API surface
is `output_config={"format": {"type": "json_schema", "schema": ...}}`.
The response's first content block has type 'text' and `text` is the
JSON-encoded result. The seam normalises this into the result's
`text` field; the caller validates with `Model.model_validate_json(text)`.

Dependency injection: the constructor accepts an optional `client`
argument so tests can pass a fake without monkey-patching the
`anthropic` module.
"""
from __future__ import annotations

import os
from typing import Any, Protocol

from enrichment.llm.cost_table import cost_for
from enrichment.llm.types import (
    GenerationRequest,
    GenerationResult,
    ModelSpec,
    ToolCall,
)


class _AnthropicClientProto(Protocol):
    """Minimal subset of anthropic.Anthropic the provider depends on.

    Defined as a Protocol so tests can pass a FakeAnthropicClient
    without importing the real SDK.
    """

    @property
    def messages(self) -> Any: ...


class AnthropicProvider:
    """Wraps an Anthropic client; exposes generate(spec, request)."""

    def __init__(self, client: _AnthropicClientProto | None = None) -> None:
        if client is not None:
            self._client = client
        else:
            # Lazy real-client construction so unit tests that
            # never call generate(...) don't require ANTHROPIC_API_KEY.
            #
            # load_dotenv() is called defensively here: the BleakHouse
            # convention is that callers (run_pipeline.py, test_single.py,
            # etc.) call load_dotenv() at startup, but a fresh caller of
            # the seam may not. load_dotenv() is idempotent and won't
            # override env vars already set, so this is safe.
            #
            # timeout=3600 / max_retries=0: long generations on
            # large-context structured-output calls regularly exceed
            # the SDK's 10-minute default. Retries are disabled so a
            # client-side timeout fails the call once and bubbles up,
            # rather than masquerading as a server-side error after
            # 3×600s = 30 minutes.
            from dotenv import load_dotenv
            import anthropic
            load_dotenv()
            self._client = anthropic.Anthropic(
                api_key=os.environ.get("ANTHROPIC_API_KEY"),
                timeout=3600.0,
                max_retries=0,
            )

    def generate(
        self,
        spec: ModelSpec,
        request: GenerationRequest,
    ) -> GenerationResult:
        """Run a one-shot generation against Anthropic and return a
        provider-neutral GenerationResult.

        If request.tools is set, runs an agentic tool-use loop until the
        model stops emitting tool_use blocks (or max_tool_iterations is
        hit). The two modes don't combine — tool loops in host_prep are
        free-text agentic conversations, with structured-output extraction
        done as a separate second call.
        """
        if request.tools:
            return self._generate_with_tools(spec, request)
        return self._generate_one_shot(spec, request)

    def _generate_one_shot(
        self, spec: ModelSpec, request: GenerationRequest,
    ) -> GenerationResult:
        """Existing structured-output path (no tools)."""
        kwargs: dict[str, Any] = {
            "model": spec.model,
            "max_tokens": request.max_tokens,
            "messages": [{"role": "user", "content": request.user}],
        }
        if request.system is not None:
            if request.cache_system:
                # Cache breakpoint at the end of the system block.
                # Subsequent calls with the same system text hit the
                # ephemeral (~5-minute) prompt cache.
                kwargs["system"] = [{
                    "type": "text",
                    "text": request.system,
                    "cache_control": {"type": "ephemeral"},
                }]
            else:
                kwargs["system"] = request.system
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.json_schema is not None:
            schema = request.json_schema
            # 1) Apply caller-supplied list-field caps as prompt-level
            #    guidance (Anthropic decoder can't enforce maxItems;
            #    description text is the closest thing).
            if request.list_field_caps:
                schema = _apply_list_caps_to_descriptions(
                    schema, request.list_field_caps,
                )
            # 2) Anthropic's output_config schema subset rejects several
            #    JSON Schema features that Pydantic emits and that other
            #    providers accept — verified 2026-05-13 via 400 response
            #    "For 'array' type, property 'maxItems' is not supported".
            #    Strip them and fold the constraint into descriptions.
            schema = _strip_unsupported_schema_keys(schema)
            kwargs["output_config"] = {
                "format": {"type": "json_schema", "schema": schema}
            }

        response = self._client.messages.create(**kwargs)

        # Extract the text block. Anthropic returns content as a list
        # of blocks; for our schema-constrained calls the first block
        # is type='text' with the JSON-encoded payload as `.text`.
        text = _extract_text(response)
        (
            input_tokens, output_tokens,
            cache_create_tokens, cache_read_tokens,
        ) = _extract_token_counts(response)

        return GenerationResult(
            text=text,
            provider="anthropic",
            model=spec.model,
            hosting=spec.hosting,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_input_tokens=cache_create_tokens,
            cache_read_input_tokens=cache_read_tokens,
            estimated_cost_usd=cost_for(
                "anthropic", spec.model, input_tokens, output_tokens,
                cache_creation_input_tokens=cache_create_tokens,
                cache_read_input_tokens=cache_read_tokens,
            ),
            execution_mode="one_shot",
            raw=response,
        )

    def _generate_with_tools(
        self, spec: ModelSpec, request: GenerationRequest,
    ) -> GenerationResult:
        """Agentic tool-use loop. Mirrors host_prep.run_pre_interview_with_tools
        (the call site we're migrating). Loop body per iteration:
          1. messages.create(messages=conversation, tools=anthropic_tools)
          2. Collect text blocks from response.content (accumulate)
          3. If stop_reason != 'tool_use', break
          4. For each tool_use block: execute via tool_executors[name], build
             a tool_result block keyed by the tool_use.id
          5. Append response.content as assistant + tool_results as user
          6. Repeat (max max_tool_iterations turns; matches host_prep's
             MAX_TOOL_CALLS=6 historical default)
        """
        if not request.tool_executors:
            raise ValueError(
                "GenerationRequest.tools set but tool_executors is empty; "
                "the seam can't dispatch calls without executors"
            )

        tools_payload = [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in request.tools
        ]

        messages: list[dict[str, Any]] = [
            {"role": "user", "content": request.user},
        ]

        text_chunks: list[str] = []
        transcript: list[ToolCall] = []
        agg_input = 0
        agg_output = 0
        agg_cache_create = 0
        agg_cache_read = 0
        any_cache_seen = False
        last_response: Any = None

        for iteration in range(request.max_tool_iterations + 1):
            kwargs: dict[str, Any] = {
                "model": spec.model,
                "max_tokens": request.max_tokens,
                "messages": messages,
                "tools": tools_payload,
            }
            if request.system is not None:
                if request.cache_system:
                    kwargs["system"] = [{
                        "type": "text",
                        "text": request.system,
                        "cache_control": {"type": "ephemeral"},
                    }]
                else:
                    kwargs["system"] = request.system
            if request.temperature is not None:
                kwargs["temperature"] = request.temperature

            response = self._client.messages.create(**kwargs)
            last_response = response

            # Per-turn usage accumulation.
            in_t, out_t, cc_t, cr_t = _extract_token_counts(response)
            if in_t is not None:
                agg_input += in_t
            if out_t is not None:
                agg_output += out_t
            if cc_t is not None:
                any_cache_seen = True
                agg_cache_create += cc_t
            if cr_t is not None:
                any_cache_seen = True
                agg_cache_read += cr_t

            for block in response.content:
                if getattr(block, "type", None) == "text":
                    text_chunks.append(block.text)

            if getattr(response, "stop_reason", None) != "tool_use":
                break

            tool_result_blocks: list[dict[str, Any]] = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                tool_name = block.name
                tool_input = block.input  # Anthropic SDK pre-parses to dict.
                executor = request.tool_executors.get(tool_name)
                if executor is None:
                    output = f"tool error: no executor registered for {tool_name!r}"
                else:
                    try:
                        output = executor(tool_input)
                    except Exception as exc:  # noqa: BLE001 — see docs/tool_use_review.html
                        output = f"tool error: {exc.__class__.__name__}: {exc}"
                transcript.append(ToolCall(
                    name=tool_name,
                    arguments=dict(tool_input),
                    output=output,
                    iteration=iteration,
                ))
                tool_result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                })

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_result_blocks})

        # Iteration cap hit without natural termination is recoverable from the
        # caller's standpoint — they get the accumulated text + transcript and
        # decide whether it's enough. Surface via the transcript length vs
        # max_tool_iterations; the model could not naturally end the loop.

        return GenerationResult(
            text="\n".join(text_chunks),
            provider="anthropic",
            model=spec.model,
            hosting=spec.hosting,
            input_tokens=agg_input or None,
            output_tokens=agg_output or None,
            cache_creation_input_tokens=agg_cache_create if any_cache_seen else None,
            cache_read_input_tokens=agg_cache_read if any_cache_seen else None,
            estimated_cost_usd=cost_for(
                "anthropic", spec.model, agg_input, agg_output,
                cache_creation_input_tokens=agg_cache_create if any_cache_seen else None,
                cache_read_input_tokens=agg_cache_read if any_cache_seen else None,
            ),
            execution_mode="one_shot",
            tool_transcript=tuple(transcript),
            raw=last_response,
        )


# JSON Schema keys Anthropic's output_config rejects. Documented in
# platform.claude.com/docs/en/docs/build-with-claude/structured-outputs
# (2026-05-13). The SDK's `messages.parse()` auto-strips these and
# folds them into field descriptions; `messages.create()` (what the
# seam uses) does not, so we replicate the transform here.
#
# minItems: only values 0 and 1 are accepted by Anthropic; higher
# values must be stripped + described.
# pattern: simple patterns supported; complex (lookahead, etc.) not.
# We strip conservatively.
_UNSUPPORTED_KEYS: frozenset[str] = frozenset({
    "maxItems",
    "minItems",
    "uniqueItems",
    "maxLength",
    "minLength",
    "pattern",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
})


def _describe_constraint(key: str, value: Any) -> str:
    """Human-readable note appended to a description when we strip a
    constraint key. Mirrors the SDK's auto-transformation output."""
    if key == "maxItems":
        return f"Maximum {value} items."
    if key == "minItems":
        return f"Minimum {value} items."
    if key == "uniqueItems":
        return "Each item must be unique." if value else ""
    if key == "maxLength":
        return f"Maximum length {value} characters."
    if key == "minLength":
        return f"Minimum length {value} characters."
    if key == "pattern":
        return f"Must match pattern: {value}."
    if key == "minimum":
        return f"Minimum value: {value}."
    if key == "maximum":
        return f"Maximum value: {value}."
    if key == "exclusiveMinimum":
        return f"Must be greater than {value}."
    if key == "exclusiveMaximum":
        return f"Must be less than {value}."
    if key == "multipleOf":
        return f"Must be a multiple of {value}."
    return f"{key}={value}."


def _apply_list_caps_to_descriptions(
    schema: Any, caps: dict[str, int],
) -> Any:
    """Walk the schema and, for each property named in `caps`, append
    a "Maximum N items." sentence to its description. Returns a new
    structure; input is not mutated.

    Matches by property name regardless of nesting depth (typically
    fields live under $defs/<Model>/properties/<name>)."""
    if isinstance(schema, dict):
        out: dict[str, Any] = {}
        for k, v in schema.items():
            if k == "properties" and isinstance(v, dict):
                new_props: dict[str, Any] = {}
                for prop_name, prop_def in v.items():
                    if prop_name in caps and isinstance(prop_def, dict):
                        cap_note = f"Maximum {caps[prop_name]} items."
                        existing = prop_def.get("description", "")
                        new_def = dict(prop_def)
                        sep = " " if existing else ""
                        new_def["description"] = (
                            f"{existing}{sep}{cap_note}".strip()
                        )
                        new_props[prop_name] = _apply_list_caps_to_descriptions(
                            new_def, caps,
                        )
                    else:
                        new_props[prop_name] = _apply_list_caps_to_descriptions(
                            prop_def, caps,
                        )
                out[k] = new_props
            else:
                out[k] = _apply_list_caps_to_descriptions(v, caps)
        return out
    if isinstance(schema, list):
        return [_apply_list_caps_to_descriptions(item, caps) for item in schema]
    return schema


def _strip_unsupported_schema_keys(schema: Any) -> Any:
    """Recursively remove JSON Schema keys Anthropic's output_config
    rejects and fold them into the parent's `description` so the model
    still sees the constraint as prompt-level guidance.

    Returns a new structure; the input is not mutated. Pydantic
    validation on our side still enforces the original constraints
    against the model's text output."""
    if isinstance(schema, dict):
        # Collect descriptions for any unsupported keys at this level
        # so we can append them to this object's description.
        notes: list[str] = []
        out: dict[str, Any] = {}
        for k, v in schema.items():
            if k in _UNSUPPORTED_KEYS:
                note = _describe_constraint(k, v)
                if note:
                    notes.append(note)
                continue
            out[k] = _strip_unsupported_schema_keys(v)
        if notes:
            existing_desc = out.get("description", "")
            note_text = " " + " ".join(notes) if existing_desc else " ".join(notes)
            out["description"] = (existing_desc + note_text).strip()
        return out
    if isinstance(schema, list):
        return [_strip_unsupported_schema_keys(item) for item in schema]
    return schema


def _extract_text(response: Any) -> str:
    """Anthropic response → first text block's `text` field.

    Defensive against fakes that may return a simpler structure.
    """
    content = getattr(response, "content", None) or []
    for block in content:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text = getattr(block, "text", None)
            if isinstance(text, str):
                return text
    # Fall back: some response shapes may flatten to .text directly.
    text_attr = getattr(response, "text", None)
    if isinstance(text_attr, str):
        return text_attr
    return ""


def _extract_token_counts(
    response: Any,
) -> tuple[int | None, int | None, int, int]:
    """Anthropic response → (input_tokens, output_tokens,
    cache_creation_input_tokens, cache_read_input_tokens).

    Anthropic reports cache_creation / cache_read as separate fields
    on usage; input_tokens excludes cached. Defaults zero for missing
    cache fields (fakes / older responses).

    Returns (None, None, 0, 0) if usage isn't on the response.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return None, None, 0, 0
    return (
        getattr(usage, "input_tokens", None),
        getattr(usage, "output_tokens", None),
        int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
        int(getattr(usage, "cache_read_input_tokens", 0) or 0),
    )
