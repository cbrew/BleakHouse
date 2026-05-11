"""Task → ModelSpec resolution.

Defaults preserve current Anthropic behaviour: every task that
currently runs on Anthropic Haiku 4.5 or Sonnet 4.6 still does
under the defaults defined here. Phase 5 of the migration plan
flips per-task defaults to open-weight candidates after the survey
data lands (BleakHouse-9k9n).

Overrides via environment variables (BLEAKHOUSE_LLM_<TASK>_PROVIDER,
BLEAKHOUSE_LLM_<TASK>_MODEL, etc.) are NOT wired in this PR. The
plan calls for them but they're not load-bearing for Phase 1 — the
default registry is enough to seam the test_single migration.
"""
from __future__ import annotations

from enrichment.llm.types import ModelSpec

# Task names are the logical-operation identifiers used at call
# sites. The seam keeps these decoupled from model identifiers so
# Phase 5 default-flips are one-line changes here, not call-site
# rewrites.
#
# Tasks below correspond to the call sites in docs/llm_call_sites.md.
# Only `passage_enrichment` is wired to a real call site in Phase 1
# (via the test_single migration); the others are stubbed here so
# adding their migrations later is a settings-only change.

_TASK_DEFAULTS: dict[str, ModelSpec] = {
    # Passage enrichment — Phase 0 batch enrichment per chapter.
    # Current behaviour: claude-haiku-4-5-20251001 via Anthropic
    # native batch (submit_passages_enriched.py) or single-shot
    # (test_single.py).
    "passage_enrichment": ModelSpec(
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        hosting="anthropic",
    ),

    # Phase 1: passage contextualisation batch.
    "passage_contexts": ModelSpec(
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        hosting="anthropic",
    ),

    # Phase 1: LLM-driven segment design.
    "design_segments": ModelSpec(
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        hosting="anthropic",
    ),

    # Phase 2.5: pre-interview agentic loop + structured response +
    # host brief. Different sites use Haiku vs Sonnet; we model
    # them as distinct tasks so per-task routing can differ.
    "host_prep_pre_interview": ModelSpec(
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        hosting="anthropic",
    ),
    "host_prep_pre_interview_structured": ModelSpec(
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        hosting="anthropic",
    ),
    "host_prep_brief": ModelSpec(
        provider="anthropic",
        model="claude-sonnet-4-6",
        hosting="anthropic",
    ),

    # Phase 2.5: reading-list winnowing.
    "reading_list_winnow": ModelSpec(
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        hosting="anthropic",
    ),

    # Phase 3: prose generation (long format, current default).
    # Phase 5 will introduce a `generate_podcast_short` task that
    # may default to an open-weight model.
    "generate_podcast": ModelSpec(
        provider="anthropic",
        model="claude-sonnet-4-6",
        hosting="anthropic",
    ),
    "embedding_podcast_curate": ModelSpec(
        provider="anthropic",
        model="claude-sonnet-4-6",
        hosting="anthropic",
    ),
}


def for_task(task: str) -> ModelSpec:
    """Return the ModelSpec configured for the given task.

    Raises KeyError for unknown tasks — explicit failure is better
    than silently routing to a wrong model. Tests should add
    expected tasks to the registry before exercising them.
    """
    try:
        return _TASK_DEFAULTS[task]
    except KeyError as exc:
        raise KeyError(
            f"no ModelSpec configured for task {task!r}; "
            f"known tasks: {sorted(_TASK_DEFAULTS)}"
        ) from exc


def register_task(task: str, spec: ModelSpec) -> None:
    """Register or override a task's ModelSpec. Mostly for tests;
    callers wanting to flip a default at runtime should do it via
    environment variables once those are wired (Phase 5)."""
    _TASK_DEFAULTS[task] = spec


def known_tasks() -> tuple[str, ...]:
    """Currently-registered task names — useful for diagnostics
    and for the eval harness to iterate over."""
    return tuple(sorted(_TASK_DEFAULTS))
