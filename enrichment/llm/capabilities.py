"""Per-hosting provider capabilities.

Per BleakHouse-5b7m (closed; encoded in this seam), the migration
plan treats 'OpenAI-compatible' as a family with non-uniform
support — some providers honor `response_format` strict mode,
others ignore the flag; some support tool_use, others don't.

The seam exposes a small registry mapping hosting identifier to
ProviderCapabilities. Settings resolution + client dispatch fail
loudly when a task wants a capability the configured hosting
lacks — rather than silently degrading to free-text and producing
unparseable output.

Values are verified-at-survey-time where possible (see
docs/bleakhouse_provider_survey.md) and conservative-default
where not. Update via this file when a provider's behaviour changes.
"""
from __future__ import annotations

from enrichment.llm.types import ProviderCapabilities


# Per-hosting capabilities. Add an entry when introducing a new
# hosting. Unknown hostings fall back to a conservative all-False
# default that effectively forces fail-loud on structured tasks.
_CAPABILITIES: dict[str, ProviderCapabilities] = {
    # Anthropic — verified via the Phase 1 AnthropicProvider.
    # output_config with json_schema is a 'always strict' mechanism;
    # there's no separate strict flag like OpenAI.
    "anthropic": ProviderCapabilities(
        json_schema_constrained=True,
        json_schema_strict=True,
        tool_use=True,
        native_batch=True,
        context_window=200_000,
    ),

    # DeepInfra — OpenAI-compatible REST. response_format json_schema
    # supported; the strict-flag behavior is per-model and not
    # universally honored, so we mark it False and let the strict
    # call sites use the json_schema constraint without the flag.
    "deepinfra": ProviderCapabilities(
        json_schema_constrained=True,
        json_schema_strict=False,
        tool_use=True,
        native_batch=False,
        context_window=128_000,
    ),

    # Together — OpenAI-compatible. Function-calling + JSON-schema
    # outputs documented for Gemma 4 31B and similar. 50% batch
    # discount via their Batch Inference API. Context window varies
    # by model (262k on Gemma 4 31B per survey).
    "together": ProviderCapabilities(
        json_schema_constrained=True,
        json_schema_strict=True,
        tool_use=True,
        native_batch=True,
        context_window=262_144,
    ),

    # Fireworks — OpenAI-compatible. Documents 50% batch discount.
    # Per-model context windows; conservative 128k default.
    "fireworks": ProviderCapabilities(
        json_schema_constrained=True,
        json_schema_strict=True,
        tool_use=True,
        native_batch=True,
        context_window=131_072,
    ),

    # Groq — OpenAI-compatible, fast inference. response_format
    # json_schema supported; 50% batch discount via async batch API
    # (24h to 7d window). No custom-weight uploads on self-serve.
    "groq": ProviderCapabilities(
        json_schema_constrained=True,
        json_schema_strict=True,
        tool_use=True,
        native_batch=True,
        context_window=131_072,
    ),

    # Cerebras — OpenAI-compatible chat API. response_format works
    # for json_schema; strict semantics differ from OpenAI's
    # reference impl per BleakHouse-5b7m notes. No native batch.
    # NOTE: catalogue narrows to gpt-oss-120b only after 2026-05-27.
    "cerebras": ProviderCapabilities(
        json_schema_constrained=True,
        json_schema_strict=False,
        tool_use=True,
        native_batch=False,
        context_window=128_000,
    ),

    # NVIDIA NIM — OpenAI-compatible. Hosts the Nemotron family
    # plus a curated catalogue. response_format json_schema
    # supported.
    "nvidia": ProviderCapabilities(
        json_schema_constrained=True,
        json_schema_strict=True,
        tool_use=True,
        native_batch=False,
        context_window=128_000,
    ),

    # Novita — HF Inference Providers partner; OpenAI-compatible.
    # Hosts Gemma 4 26B-A4B (MoE) among others. Conservative defaults
    # — verify in Stage 2.
    "novita": ProviderCapabilities(
        json_schema_constrained=True,
        json_schema_strict=False,
        tool_use=True,
        native_batch=False,
        context_window=128_000,
    ),

    # Featherless-AI — HF Inference Providers partner; broad
    # fine-tunes catalogue. Conservative defaults — verify in Stage 2.
    "featherless": ProviderCapabilities(
        json_schema_constrained=True,
        json_schema_strict=False,
        tool_use=True,
        native_batch=False,
        context_window=128_000,
    ),

    # Self-hosted on Modal / Runpod / GKE via vLLM. Capabilities
    # depend on the deployed stack but vLLM supports
    # response_format json_schema natively as of recent versions.
    # Listed for completeness; the fallback rehearsal path in the
    # survey would use one of these.
    "modal": ProviderCapabilities(
        json_schema_constrained=True,
        json_schema_strict=True,
        tool_use=True,
        native_batch=False,
        context_window=131_072,
    ),
    "runpod": ProviderCapabilities(
        json_schema_constrained=True,
        json_schema_strict=True,
        tool_use=True,
        native_batch=False,
        context_window=131_072,
    ),
    "gke": ProviderCapabilities(
        json_schema_constrained=True,
        json_schema_strict=True,
        tool_use=True,
        native_batch=False,
        context_window=131_072,
    ),
}


# Conservative default: when we encounter an unknown hosting, refuse
# everything except free-text. This fails loud on structured tasks
# (which is what we want) rather than silently degrading.
_DEFAULT = ProviderCapabilities(
    json_schema_constrained=False,
    json_schema_strict=False,
    tool_use=False,
    native_batch=False,
    context_window=8_192,
)


def for_hosting(hosting: str) -> ProviderCapabilities:
    """Return the capabilities for a hosting identifier.

    Unknown hostings get a conservative all-False default — the
    intent is to force operators to register a capability entry
    before routing structured tasks through a new hosting.
    """
    return _CAPABILITIES.get(hosting, _DEFAULT)


def known_hostings() -> tuple[str, ...]:
    """Hostings with registered capability entries."""
    return tuple(sorted(_CAPABILITIES))


def register_hosting(hosting: str, caps: ProviderCapabilities) -> None:
    """Register or override a hosting's capabilities. Mostly for
    tests + experimental providers."""
    _CAPABILITIES[hosting] = caps


class CapabilityError(RuntimeError):
    """Raised when a task requests a capability the configured
    hosting can't honour. Failed at dispatch time, before any
    HTTP call — silent degradation is worse than a loud error."""


def require_capabilities_for_request(
    hosting: str,
    json_schema_requested: bool,
) -> None:
    """Validate that the hosting can serve the request's capability
    needs. Raises CapabilityError on mismatch.

    Called by client.generate() before dispatch to a provider.
    """
    caps = for_hosting(hosting)
    if json_schema_requested and not caps.json_schema_constrained:
        raise CapabilityError(
            f"task requests json_schema-constrained output but "
            f"hosting={hosting!r} has json_schema_constrained=False. "
            f"Either route this task to a hosting that supports it "
            f"or remove the json_schema from the request. "
            f"Update enrichment/llm/capabilities.py if this is wrong."
        )
