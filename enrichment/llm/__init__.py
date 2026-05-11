"""Provider-neutral LLM call seam (BleakHouse-4thc).

Public surface:

    from enrichment.llm import generate
    from enrichment.llm.types import GenerationRequest, GenerationResult

    result = generate(GenerationRequest(
        task="passage_enrichment",
        system="...",
        user="...",
        max_tokens=4096,
        json_schema=MyPydanticModel.model_json_schema(),
    ))

The default provider/model per task lives in enrichment.llm.settings;
overrides via environment variables are not wired in this PR but the
plan (Phase 5) calls for them per task.

See docs/bleakhouse_anthropic_optionality_migration_plan.md.
"""

from enrichment.llm.client import generate
from enrichment.llm.types import (
    GenerationRequest,
    GenerationResult,
    ModelSpec,
    ProviderCapabilities,
)

__all__ = [
    "generate",
    "GenerationRequest",
    "GenerationResult",
    "ModelSpec",
    "ProviderCapabilities",
]
