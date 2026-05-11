"""Provider implementations.

Each provider exposes a `generate(spec, request) -> GenerationResult`
method. The client.py facade dispatches on `spec.provider`.

- AnthropicProvider: Phase 1.
- OpenAICompatibleProvider: Phase 3 (DeepInfra, Together, Fireworks,
  Groq, Cerebras, NVIDIA NIM, Novita, Featherless, plus self-hosted
  vLLM on Modal/Runpod/GKE).
"""
from enrichment.llm.providers.anthropic_provider import AnthropicProvider
from enrichment.llm.providers.openai_compatible_provider import (
    OpenAICompatibleProvider,
)

__all__ = ["AnthropicProvider", "OpenAICompatibleProvider"]
