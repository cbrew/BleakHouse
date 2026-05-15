"""Task-to-ModelSpec resolution tests."""
from __future__ import annotations

import pytest

from enrichment.llm import settings
from enrichment.llm.types import ModelSpec


def test_passage_enrichment_default_preserves_current_behaviour() -> None:
    """Phase 1 acceptance criterion: default settings reproduce
    current Anthropic Haiku behaviour for the migrated call site."""
    spec = settings.for_task("passage_enrichment")
    assert spec.provider == "anthropic"
    assert spec.model == "claude-haiku-4-5-20251001"
    assert spec.hosting == "anthropic"


def test_generate_podcast_default_is_sonnet_4_6() -> None:
    """Prose tasks default to Sonnet per the current pipeline.
    Phase 5 may flip generate_podcast_short to open-weight; this
    test pins the current behaviour."""
    spec = settings.for_task("generate_podcast")
    assert spec.provider == "anthropic"
    assert spec.model == "claude-sonnet-4-6"


def test_unknown_task_raises_with_helpful_message() -> None:
    with pytest.raises(KeyError) as excinfo:
        settings.for_task("not_a_real_task")
    assert "no ModelSpec configured" in str(excinfo.value)
    assert "known tasks" in str(excinfo.value)


def test_register_task_overrides_default() -> None:
    """register_task lets tests + experimental code swap a task's
    routing without editing settings.py."""
    settings.register_task("experimental_task", ModelSpec(
        provider="openai_compatible",
        model="some-model",
        hosting="some-host",
    ))
    spec = settings.for_task("experimental_task")
    assert spec.provider == "openai_compatible"
    assert spec.model == "some-model"


def test_known_tasks_lists_all_registered() -> None:
    tasks = settings.known_tasks()
    assert "passage_enrichment" in tasks
    assert "generate_podcast" in tasks
    # Tuple is sorted
    assert list(tasks) == sorted(tasks)


def test_default_profile_is_production() -> None:
    """Import-time activation uses params.yaml default_provider_profile."""
    # Reset to default in case a prior test activated something else.
    settings.activate()
    assert settings.active_profile_name() == "production"


def test_activate_all_openai_routes_to_gpt5() -> None:
    """The all_openai profile (params.yaml) routes Haiku-tier tasks to
    gpt-5-mini and prose-tier to gpt-5.4. Restore default at end."""
    try:
        settings.activate("all_openai")
        spec = settings.for_task("passage_enrichment")
        assert spec.provider == "openai_compatible"
        assert spec.model == "gpt-5-mini"
        assert spec.hosting == "openai"
        prose = settings.for_task("generate_podcast")
        assert prose.model == "gpt-5.4"
    finally:
        settings.activate()  # restore production


def test_overrides_layer_on_top_of_profile() -> None:
    """--provider-override TASK=MODEL_ID layers on top of the profile."""
    try:
        settings.activate(
            "all_openai",
            {"host_prep_brief": "anthropic_sonnet_4_6"},
        )
        # Override wins for host_prep_brief
        assert settings.for_task("host_prep_brief").provider == "anthropic"
        # Profile still wins for tasks not in the overrides map
        assert settings.for_task("passage_enrichment").model == "gpt-5-mini"
    finally:
        settings.activate()


def test_resolved_providers_is_complete_snapshot() -> None:
    """resolved_providers() returns the full task → ModelSpec map; every
    task in known_tasks() is present, with no extras."""
    settings.activate()
    resolved = settings.resolved_providers()
    assert set(resolved) == set(settings.known_tasks())
    # Defensive copy: mutating the returned dict mustn't affect state.
    resolved["passage_enrichment"] = "garbage"  # type: ignore[assignment]
    assert settings.for_task("passage_enrichment").model == "claude-haiku-4-5-20251001"


def test_unknown_profile_raises() -> None:
    with pytest.raises(ValueError, match="unknown provider profile"):
        settings.activate("not_a_real_profile")
    # Restore default so subsequent tests start clean.
    settings.activate()


def test_unknown_generator_id_in_override_raises() -> None:
    with pytest.raises(ValueError, match="unknown generator id"):
        settings.activate("production", {"passage_enrichment": "not_a_real_model"})
    settings.activate()
