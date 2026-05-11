"""Provider implementations.

Each provider exposes a `generate(spec, request) -> GenerationResult`
function (or class with that method). The client.py facade dispatches
on `spec.provider`.

Phase 1: only AnthropicProvider is implemented. Phase 3 adds the
OpenAI-compatible provider.
"""
from enrichment.llm.providers.anthropic_provider import AnthropicProvider

__all__ = ["AnthropicProvider"]
