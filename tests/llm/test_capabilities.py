"""Capability registry tests."""
from __future__ import annotations

import pytest

from enrichment.llm import capabilities
from enrichment.llm.capabilities import (
    CapabilityError,
    for_hosting,
    register_hosting,
    require_capabilities_for_request,
)
from enrichment.llm.types import ProviderCapabilities


def test_anthropic_hosts_have_structured_output() -> None:
    caps = for_hosting("anthropic")
    assert caps.json_schema_constrained
    assert caps.json_schema_strict
    assert caps.tool_use
    assert caps.native_batch


def test_deepinfra_hosts_have_structured_output_but_not_strict() -> None:
    caps = for_hosting("deepinfra")
    assert caps.json_schema_constrained
    # We mark strict=False conservatively for DeepInfra per the survey notes.
    assert not caps.json_schema_strict
    assert caps.tool_use
    assert not caps.native_batch


def test_together_groq_fireworks_have_native_batch() -> None:
    """All three advertise 50% batch discount per the survey."""
    for host in ("together", "groq", "fireworks"):
        caps = for_hosting(host)
        assert caps.native_batch, f"{host} should support native_batch"


def test_cerebras_no_native_batch() -> None:
    caps = for_hosting("cerebras")
    assert caps.json_schema_constrained
    assert not caps.native_batch


def test_unknown_hosting_returns_conservative_default() -> None:
    """Unknown hostings get all-False capabilities — forces operators
    to register an entry before routing structured tasks."""
    caps = for_hosting("some-unknown-future-host")
    assert not caps.json_schema_constrained
    assert not caps.json_schema_strict
    assert not caps.tool_use
    assert not caps.native_batch


def test_known_hostings_includes_survey_set() -> None:
    known = capabilities.known_hostings()
    expected = {
        "anthropic", "deepinfra", "together", "fireworks",
        "groq", "cerebras", "nvidia", "novita", "featherless",
        "modal", "runpod", "gke",
    }
    assert expected.issubset(set(known))


def test_register_hosting_overrides() -> None:
    register_hosting(
        "test_custom_host",
        ProviderCapabilities(
            json_schema_constrained=True,
            json_schema_strict=True,
            tool_use=False,
            native_batch=False,
            context_window=4096,
        ),
    )
    caps = for_hosting("test_custom_host")
    assert caps.context_window == 4096
    assert caps.json_schema_constrained
    assert not caps.tool_use


def test_require_capabilities_for_request_passes_when_supported() -> None:
    """Anthropic supports json_schema → no error."""
    require_capabilities_for_request("anthropic", json_schema_requested=True)
    # Returns None / no exception.


def test_require_capabilities_for_request_passes_when_no_schema() -> None:
    """Free-text request → no capability check needed regardless of hosting."""
    require_capabilities_for_request(
        "some-unknown-host", json_schema_requested=False,
    )


def test_require_capabilities_for_request_fails_on_mismatch() -> None:
    """Unknown hosting + structured-output request → CapabilityError."""
    with pytest.raises(CapabilityError) as excinfo:
        require_capabilities_for_request(
            "some-unknown-host", json_schema_requested=True,
        )
    assert "json_schema-constrained" in str(excinfo.value)
    assert "some-unknown-host" in str(excinfo.value)
