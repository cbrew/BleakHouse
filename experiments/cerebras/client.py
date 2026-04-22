"""Minimal Cerebras client built on the `llm` library + `llm-cerebras` plugin.

Key management follows llm idioms: set once with `llm keys set cerebras`, or
export `CEREBRAS_API_KEY`. No imports from the rest of this project.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import llm
from pydantic import BaseModel

CEREBRAS_PREFIX = "cerebras-"
DEFAULT_MODEL = "cerebras-gpt-oss-120b"


@dataclass
class CallMetrics:
    elapsed_seconds: float
    input_tokens: int | None
    output_tokens: int | None
    details: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "elapsed_seconds": self.elapsed_seconds,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": (
                (self.input_tokens or 0) + (self.output_tokens or 0)
                if self.input_tokens is not None or self.output_tokens is not None
                else None
            ),
            "tokens_per_second": (
                self.output_tokens / self.elapsed_seconds
                if self.output_tokens and self.elapsed_seconds > 0
                else None
            ),
            "details": self.details,
        }


def list_models(*, refresh: bool = False) -> list[str]:
    """Return the Cerebras model IDs registered with llm.

    The `llm-cerebras` plugin prefixes every Cerebras id with `cerebras-`
    and caches the /models response for 24 h on disk. To force a refresh,
    run `llm cerebras refresh` from the shell (the plugin does not expose a
    public Python hook for this).
    """
    if refresh:
        raise NotImplementedError(
            "Programmatic refresh is not exposed by llm-cerebras; "
            "run `llm cerebras refresh` from the shell instead."
        )
    return sorted(
        m.model_id for m in llm.get_models() if m.model_id.startswith(CEREBRAS_PREFIX)
    )


def call_with_schema(
    prompt: str,
    schema: type[BaseModel] | dict[str, Any],
    *,
    system: str | None = None,
    model_id: str = DEFAULT_MODEL,
    **options: Any,
) -> dict[str, Any]:
    """Call a Cerebras model with a JSON schema and return the parsed object.

    `schema` may be a Pydantic `BaseModel` subclass or a raw JSON Schema dict.
    Extra kwargs (temperature, max_tokens, ...) are forwarded to `model.prompt`.
    """
    parsed, _ = call_with_schema_metrics(
        prompt, schema, system=system, model_id=model_id, **options
    )
    return parsed


def call_with_schema_metrics(
    prompt: str,
    schema: type[BaseModel] | dict[str, Any],
    *,
    system: str | None = None,
    model_id: str = DEFAULT_MODEL,
    **options: Any,
) -> tuple[dict[str, Any], CallMetrics]:
    """Like `call_with_schema` but also returns timing and token usage."""
    model = llm.get_model(model_id)
    start = time.perf_counter()
    response = model.prompt(prompt, system=system, schema=schema, **options)
    text = response.text()
    elapsed = time.perf_counter() - start
    usage = response.usage()
    metrics = CallMetrics(
        elapsed_seconds=elapsed,
        input_tokens=usage.input,
        output_tokens=usage.output,
        details=dict(usage.details) if usage.details else None,
    )
    return json.loads(text), metrics


