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
