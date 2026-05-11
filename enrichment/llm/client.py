"""Task-facing facade.

    generate(GenerationRequest) -> GenerationResult

Resolves the request's task to a ModelSpec via settings, then
dispatches on the spec's provider to the matching Provider.
The Provider returns a GenerationResult with cost telemetry already
populated.

Supports `provider='anthropic'` (Phase 1) and
`provider='openai_compatible'` (Phase 3).

Capability pre-check: when the request has a json_schema, the
client validates that the resolved hosting can deliver constrained
output before dispatching. Mismatch raises CapabilityError loudly
— no silent free-text degradation.
"""
from __future__ import annotations

from typing import Protocol

from enrichment.llm import settings
from enrichment.llm.capabilities import require_capabilities_for_request
from enrichment.llm.providers import AnthropicProvider, OpenAICompatibleProvider
from enrichment.llm.types import (
    GenerationRequest,
    GenerationResult,
    ModelSpec,
)


class _Provider(Protocol):
    """Minimal duck-typed provider surface for client.generate()."""

    def generate(
        self, spec: ModelSpec, request: GenerationRequest,
    ) -> GenerationResult: ...


# Module-level cached provider instances. Lazy so unit tests that
# never call generate(...) don't construct real SDK clients.
_anthropic_provider: AnthropicProvider | None = None
_openai_compatible_provider: OpenAICompatibleProvider | None = None


def _get_anthropic_provider() -> AnthropicProvider:
    global _anthropic_provider
    if _anthropic_provider is None:
        _anthropic_provider = AnthropicProvider()
    return _anthropic_provider


def _get_openai_compatible_provider() -> OpenAICompatibleProvider:
    global _openai_compatible_provider
    if _openai_compatible_provider is None:
        _openai_compatible_provider = OpenAICompatibleProvider()
    return _openai_compatible_provider


def generate(
    request: GenerationRequest,
    *,
    provider: _Provider | None = None,
) -> GenerationResult:
    """Resolve task → ModelSpec → provider → response.

    The optional `provider` argument is for tests + special-case
    callers that want to inject a fake provider; production code
    should not pass it.

    Raises CapabilityError when the request asks for a structured
    output that the resolved hosting can't deliver — caught before
    any HTTP call.
    """
    spec = settings.for_task(request.task)

    # Capability pre-check. Fails loudly if the hosting can't honour
    # the request's structured-output requirement.
    require_capabilities_for_request(
        hosting=spec.hosting,
        json_schema_requested=request.json_schema is not None,
    )

    if spec.provider == "anthropic":
        impl = provider or _get_anthropic_provider()
        return impl.generate(spec, request)
    if spec.provider == "openai_compatible":
        impl = provider or _get_openai_compatible_provider()
        return impl.generate(spec, request)
    raise NotImplementedError(
        f"provider {spec.provider!r} is not supported. "
        f"Known providers: 'anthropic', 'openai_compatible'."
    )
