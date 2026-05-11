"""Task-facing facade.

    generate(GenerationRequest) -> GenerationResult

Resolves the request's task to a ModelSpec via settings, then
dispatches on the spec's provider to the matching Provider.
The Provider returns a GenerationResult with cost telemetry already
populated.

Phase 1 supports only `provider='anthropic'`. Phase 3 will add
`provider='openai_compatible'`.
"""
from __future__ import annotations

from enrichment.llm import settings
from enrichment.llm.providers import AnthropicProvider
from enrichment.llm.types import GenerationRequest, GenerationResult


# Module-level cached provider instances. Lazy so unit tests that
# never call generate(...) don't construct a real Anthropic client.
_anthropic_provider: AnthropicProvider | None = None


def _get_anthropic_provider() -> AnthropicProvider:
    global _anthropic_provider
    if _anthropic_provider is None:
        _anthropic_provider = AnthropicProvider()
    return _anthropic_provider


def generate(
    request: GenerationRequest,
    *,
    provider: AnthropicProvider | None = None,
) -> GenerationResult:
    """Resolve task → ModelSpec → provider → response.

    The optional `provider` argument is for tests + special-case
    callers that want to inject a fake provider; production code
    should not pass it.
    """
    spec = settings.for_task(request.task)
    if spec.provider == "anthropic":
        impl = provider or _get_anthropic_provider()
        return impl.generate(spec, request)
    raise NotImplementedError(
        f"provider {spec.provider!r} is not implemented in Phase 1 of "
        f"the migration; only 'anthropic' is currently supported. "
        f"Phase 3 of the plan adds the OpenAI-compatible provider."
    )
