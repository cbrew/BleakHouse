"""Per-task quality-floor protocols.

Encoded from BleakHouse-0rtg's specification. The PROTOCOL (what we
measure, what against) is the contract; the VALUES are starting
positions, revisable once Stage 2 of the o3ir survey produces real
data.

Floor protocols here are deliberately declarative — a Floor is a
data object naming the metrics + thresholds. The runner consumes
this; scoring functions in scoring.py do the actual math.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FloorOutcome(Enum):
    """Result of comparing scored metrics against a floor."""

    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"   # missing baseline / not enough data


@dataclass(frozen=True)
class Floor:
    """A per-task quality floor.

    Field semantics:
    - `task` — the task name as registered in enrichment.llm.settings.
    - `task_class` — coarse grouping ('small_structured',
      'structured_intermediate', 'quote_verification', 'agentic',
      'prose_short'). Determines which scoring functions apply.
    - `schema_validity_min` — minimum fraction of fixture inputs
      where the response parses against the request's json_schema.
      Always 1.0 for structured tasks per 0rtg.
    - `set_overlap_min` — minimum Jaccard overlap (0..1) between
      candidate picks and baseline picks. Used for set-output
      tasks (listener_pick, reading_list_winnow, etc.). None for
      non-set tasks.
    - `field_presence_min` — minimum fraction of expected schema
      fields actually present in the candidate output. Used for
      structured_intermediate tasks. None for non-applicable tasks.
    - `blinded_preference_min` — minimum win rate against baseline
      in blinded preference comparisons. Used for prose tasks.
      None for non-applicable tasks.
    - `description` — free-text rationale for the values; useful
      when revising.
    """

    task: str
    task_class: str
    schema_validity_min: float
    set_overlap_min: float | None = None
    field_presence_min: float | None = None
    blinded_preference_min: float | None = None
    description: str = ""


# Per-task floor registry. Values are starting-position guesses
# from BleakHouse-0rtg; tighten / loosen / replace metrics as
# Stage 2 of the o3ir survey produces empirical data.
#
# A task without a floor entry can still be evaluated, but only on
# the always-applicable schema_validity check (defaulted to 1.0 by
# `floor_for_task`).
_FLOORS: dict[str, Floor] = {
    "listener_pick": Floor(
        task="listener_pick",
        task_class="small_structured",
        schema_validity_min=1.0,
        set_overlap_min=0.85,
        description=(
            "Jaccard overlap with the Anthropic-Haiku baseline picks. "
            "0.85 = on a 5-pick output, on average ≥4-of-5 agree. "
            "Tighten or replace with a more semantic metric "
            "(e.g. tag-level quality rubric) after Stage 2."
        ),
    ),
    "reading_list_winnow": Floor(
        task="reading_list_winnow",
        task_class="small_structured",
        schema_validity_min=1.0,
        set_overlap_min=0.85,
        description="Same protocol as listener_pick.",
    ),
    "reference_tools_winnow": Floor(
        task="reference_tools_winnow",
        task_class="small_structured",
        schema_validity_min=1.0,
        set_overlap_min=0.85,
        description="Same protocol as listener_pick.",
    ),
    "quote_verification": Floor(
        task="quote_verification",
        task_class="quote_verification",
        schema_validity_min=1.0,
        set_overlap_min=0.98,   # high — verification is deterministic-adjacent
        description=(
            "Exact-match recall against held-out set where the baseline "
            "got it right; FP rate ≤2%. Higher overlap requirement "
            "because verification has a low tolerance for noise."
        ),
    ),
    "passage_enrichment": Floor(
        task="passage_enrichment",
        task_class="structured_intermediate",
        schema_validity_min=1.0,
        field_presence_min=0.95,
        description=(
            "Schema-strict + field-presence on a small fixture. "
            "Content-fidelity rubric (Stage 2) supplements once we "
            "have data."
        ),
    ),
    "design_segments": Floor(
        task="design_segments",
        task_class="structured_intermediate",
        schema_validity_min=1.0,
        field_presence_min=0.95,
        description="Same protocol as passage_enrichment.",
    ),
    "host_prep_brief": Floor(
        task="host_prep_brief",
        task_class="structured_intermediate",
        schema_validity_min=1.0,
        field_presence_min=0.95,
        description="Same protocol as passage_enrichment.",
    ),
    "generate_podcast_short": Floor(
        task="generate_podcast_short",
        task_class="prose_short",
        schema_validity_min=1.0,
        blinded_preference_min=0.45,
        description=(
            "≥45% blinded preference vs Sonnet-on-short baseline = "
            "'not statistically worse' on a small (10-episode) "
            "fixture. Defer prose default-flip until human-preference "
            "protocol exists. Note: the legacy long-form generate_podcast "
            "task may keep Anthropic Sonnet default by policy."
        ),
    ),
}


def floor_for_task(task: str) -> Floor:
    """Return the Floor for a task, falling back to a schema-validity-
    only floor when no task-specific entry exists. The fallback covers
    early-development tasks where we only know we want 'valid JSON'."""
    if task in _FLOORS:
        return _FLOORS[task]
    return Floor(
        task=task,
        task_class="unknown",
        schema_validity_min=1.0,
        description=(
            f"No task-specific floor registered for {task!r}; "
            f"falling back to schema-validity-only (=1.0)."
        ),
    )


def known_floors() -> tuple[str, ...]:
    """Tasks with registered floors. Useful for the eval CLI."""
    return tuple(sorted(_FLOORS))


def register_floor(floor: Floor) -> None:
    """Register or override a task's floor. Mostly for tests +
    experimental task definitions."""
    _FLOORS[floor.task] = floor
