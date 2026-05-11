"""End-to-end eval runner.

Loads a fixture, runs each input through enrichment.llm.generate(),
scores results against the task's floor, persists everything to
data/eval/<run-id>/<task>.json, returns a RunResult summary.

The runner is the only piece that calls generate() — scoring and
storage stay pure. This keeps the eval harness testable with a
fake provider (no live network) and reproducible (deterministic
when input + provider + model + temperature are fixed).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from enrichment.llm import GenerationRequest, GenerationResult, generate
from enrichment.llm.eval.fixtures_io import Fixture
from enrichment.llm.eval.floors import Floor, FloorOutcome, floor_for_task
from enrichment.llm.eval.scoring import (
    extract_tags_from_listener_pick_response,
    field_presence_match,
    schema_validity,
    set_overlap_jaccard,
)
from enrichment.llm.eval.storage import save_results
from enrichment.llm.settings import for_task

logger = logging.getLogger(__name__)


@dataclass
class _InputResult:
    """Per-input metrics."""

    id: str
    text: str
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost_usd: float | None
    schema_valid: float
    set_overlap: float | None = None
    field_presence: float | None = None


@dataclass
class RunResult:
    """Summary of one eval run.

    Aggregates per-input metrics into headline numbers, persists the
    full record to disk, and returns a FloorOutcome the caller can
    use to gate a default-flip.
    """

    run_id: str
    task: str
    provider: str
    model: str
    hosting: str
    n_inputs: int
    schema_validity_mean: float
    set_overlap_mean: float | None
    field_presence_mean: float | None
    total_cost_usd: float | None
    floor: Floor
    outcome: FloorOutcome
    outcome_reason: str
    per_input: list[_InputResult] = field(default_factory=list)


def _check_floor(
    floor: Floor,
    schema_validity_mean: float,
    set_overlap_mean: float | None,
    field_presence_mean: float | None,
) -> tuple[FloorOutcome, str]:
    """Apply the floor's threshold checks. Returns (outcome, reason).

    INCONCLUSIVE is reserved for cases where the floor specifies a
    metric but the fixture didn't carry the baseline data needed to
    compute it (e.g. set_overlap_min set but no fixture input had
    a baseline.tags field).
    """
    failures: list[str] = []

    if schema_validity_mean < floor.schema_validity_min:
        failures.append(
            f"schema_validity {schema_validity_mean:.2f} < "
            f"floor.schema_validity_min {floor.schema_validity_min:.2f}"
        )

    if floor.set_overlap_min is not None:
        if set_overlap_mean is None:
            return FloorOutcome.INCONCLUSIVE, (
                "floor specifies set_overlap_min but fixture has no "
                "baseline.tags to score against"
            )
        if set_overlap_mean < floor.set_overlap_min:
            failures.append(
                f"set_overlap_mean {set_overlap_mean:.2f} < "
                f"floor.set_overlap_min {floor.set_overlap_min:.2f}"
            )

    if floor.field_presence_min is not None:
        if field_presence_mean is None:
            return FloorOutcome.INCONCLUSIVE, (
                "floor specifies field_presence_min but fixture has no "
                "baseline.fields to score against"
            )
        if field_presence_mean < floor.field_presence_min:
            failures.append(
                f"field_presence_mean {field_presence_mean:.2f} < "
                f"floor.field_presence_min {floor.field_presence_min:.2f}"
            )

    # blinded_preference_min — needs out-of-band human/LLM-judge data
    # we don't have inside the unit runner. Phase 2 records the
    # protocol; Phase 5 wires the actual preference-collection step.

    if failures:
        return FloorOutcome.FAIL, "; ".join(failures)
    return FloorOutcome.PASS, "all metrics meet floor"


def _score_one(
    fixture_input,
    result: GenerationResult,
    floor: Floor,
) -> _InputResult:
    """Score one input/result pair against the task's floor."""
    sv = schema_validity(result.text, fixture_input.json_schema)

    set_overlap: float | None = None
    field_presence: float | None = None

    baseline = fixture_input.baseline or {}

    # Set-overlap scoring (listener_pick-shape tasks)
    if floor.set_overlap_min is not None and "tags" in baseline:
        baseline_tags = baseline.get("tags") or []
        # For listener_pick-shape outputs, parse the JSON response
        # for its "tags" field. For other set-output tasks we'd
        # need a per-task extractor — Phase 2 covers listener_pick
        # only; others get a None overlap and INCONCLUSIVE outcome
        # which the runner reports honestly.
        if floor.task in (
            "listener_pick", "reading_list_winnow",
            "reference_tools_winnow",
        ):
            candidate_tags = extract_tags_from_listener_pick_response(result.text)
            set_overlap = set_overlap_jaccard(candidate_tags, baseline_tags)

    # Field-presence scoring (structured_intermediate tasks)
    if floor.field_presence_min is not None and "fields" in baseline:
        expected = baseline.get("fields") or []
        try:
            import json as _json
            candidate_obj = _json.loads(result.text)
            if isinstance(candidate_obj, dict):
                field_presence = field_presence_match(candidate_obj, expected)
        except ValueError:
            field_presence = 0.0

    return _InputResult(
        id=fixture_input.id,
        text=result.text,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        estimated_cost_usd=result.estimated_cost_usd,
        schema_valid=sv,
        set_overlap=set_overlap,
        field_presence=field_presence,
    )


def run_fixture(
    fixture: Fixture,
    *,
    run_id: str,
    generate_fn: Callable[[GenerationRequest], GenerationResult] = generate,
    persist: bool = True,
) -> RunResult:
    """Run a fixture end-to-end.

    `generate_fn` defaults to enrichment.llm.generate; tests pass a
    fake that returns canned GenerationResults. `persist=False`
    skips the data/eval/ write (useful for unit tests).
    """
    floor = floor_for_task(fixture.task)
    spec = for_task(fixture.task)

    per_input: list[_InputResult] = []
    schema_scores: list[float] = []
    overlap_scores: list[float] = []
    field_scores: list[float] = []
    costs: list[float] = []

    t0 = time.time()
    for inp in fixture.inputs:
        request = GenerationRequest(
            task=fixture.task,
            system=inp.system,
            user=inp.user,
            max_tokens=inp.max_tokens,
            json_schema=inp.json_schema,
        )
        result = generate_fn(request)
        scored = _score_one(inp, result, floor)
        per_input.append(scored)
        schema_scores.append(scored.schema_valid)
        if scored.set_overlap is not None:
            overlap_scores.append(scored.set_overlap)
        if scored.field_presence is not None:
            field_scores.append(scored.field_presence)
        if scored.estimated_cost_usd is not None:
            costs.append(scored.estimated_cost_usd)

    schema_mean = (
        sum(schema_scores) / len(schema_scores)
        if schema_scores else 1.0
    )
    overlap_mean = (
        sum(overlap_scores) / len(overlap_scores)
        if overlap_scores else None
    )
    field_mean = (
        sum(field_scores) / len(field_scores)
        if field_scores else None
    )
    total_cost = sum(costs) if costs else None

    outcome, reason = _check_floor(floor, schema_mean, overlap_mean, field_mean)

    run = RunResult(
        run_id=run_id,
        task=fixture.task,
        provider=spec.provider,
        model=spec.model,
        hosting=spec.hosting,
        n_inputs=len(fixture.inputs),
        schema_validity_mean=schema_mean,
        set_overlap_mean=overlap_mean,
        field_presence_mean=field_mean,
        total_cost_usd=total_cost,
        floor=floor,
        outcome=outcome,
        outcome_reason=reason,
        per_input=per_input,
    )

    elapsed = time.time() - t0
    logger.info(
        "eval run_id=%s task=%s provider=%s model=%s n=%d outcome=%s reason=%r elapsed=%.2fs",
        run_id, fixture.task, spec.provider, spec.model,
        len(fixture.inputs), outcome.value, reason, elapsed,
    )

    if persist:
        payload: dict[str, Any] = {
            "run_id": run.run_id,
            "task": run.task,
            "provider": run.provider,
            "model": run.model,
            "hosting": run.hosting,
            "n_inputs": run.n_inputs,
            "schema_validity_mean": run.schema_validity_mean,
            "set_overlap_mean": run.set_overlap_mean,
            "field_presence_mean": run.field_presence_mean,
            "total_cost_usd": run.total_cost_usd,
            "floor": run.floor,
            "outcome": run.outcome.value,
            "outcome_reason": run.outcome_reason,
            "per_input": run.per_input,
        }
        save_results(run_id, fixture.task, payload)

    return run
