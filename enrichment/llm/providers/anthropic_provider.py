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
from enrichment.llm.types import GenerationRequest, GenerationResult, ModelSpec


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
            from dotenv import load_dotenv
            import anthropic
            load_dotenv()
            self._client = anthropic.Anthropic(
                api_key=os.environ.get("ANTHROPIC_API_KEY"),
            )

    def generate(
        self,
        spec: ModelSpec,
        request: GenerationRequest,
    ) -> GenerationResult:
        """Run a one-shot generation against Anthropic and return a
        provider-neutral GenerationResult."""
        kwargs: dict[str, Any] = {
            "model": spec.model,
            "max_tokens": request.max_tokens,
            "messages": [{"role": "user", "content": request.user}],
        }
        if request.system is not None:
            kwargs["system"] = request.system
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.json_schema is not None:
            kwargs["output_config"] = {
                "format": {"type": "json_schema", "schema": request.json_schema}
            }

        response = self._client.messages.create(**kwargs)

        # Extract the text block. Anthropic returns content as a list
        # of blocks; for our schema-constrained calls the first block
        # is type='text' with the JSON-encoded payload as `.text`.
        text = _extract_text(response)
        input_tokens, output_tokens = _extract_token_counts(response)

        return GenerationResult(
            text=text,
            provider="anthropic",
            model=spec.model,
            hosting=spec.hosting,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=cost_for(
                "anthropic", spec.model, input_tokens, output_tokens,
            ),
            execution_mode="one_shot",
            raw=response,
        )


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


def _extract_token_counts(response: Any) -> tuple[int | None, int | None]:
    """Anthropic response → (input_tokens, output_tokens).

    Returns (None, None) if usage isn't on the response (some fakes
    omit it). The cost computation in cost_for treats None tokens
    as 'unknown' and stores estimated_cost_usd=None.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return None, None
    return (
        getattr(usage, "input_tokens", None),
        getattr(usage, "output_tokens", None),
    )
