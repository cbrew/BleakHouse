"""Minimal Cerebras client built on the `llm` library + `llm-cerebras` plugin.

Key management follows llm idioms: set once with `llm keys set cerebras`, or
export `CEREBRAS_API_KEY`. No imports from the rest of this project.
"""

from __future__ import annotations

import json
from typing import Any

import llm
from pydantic import BaseModel

CEREBRAS_PREFIX = "cerebras-"
DEFAULT_MODEL = "cerebras-gpt-oss-120b"


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
    model = llm.get_model(model_id)
    response = model.prompt(prompt, system=system, schema=schema, **options)
    return json.loads(response.text())


