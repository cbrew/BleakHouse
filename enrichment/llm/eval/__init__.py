"""Evaluation harness for the LLM seam.

Per the migration plan (Phase 2, moved up from old Phase 5 under
the open-weight-default policy), the eval harness is load-bearing
— without it every default-flip in Phase 5 ships on faith.

Public surface:

    from enrichment.llm.eval import (
        Floor, FloorOutcome,
        Fixture, FixtureInput,
        run_fixture, score_result,
    )

The harness operates on:
- **Fixtures** — JSON files under enrichment/llm/eval/fixtures/.
  Each fixture pins a task + a list of inputs + optional baseline
  outputs (for comparison-against-baseline scoring).
- **Floors** — declarative per-task quality thresholds from
  BleakHouse-0rtg. Floor protocol stays fixed; floor values are
  revisable starting positions.
- **Runner** — `run_fixture(fixture, run_id)` loads inputs, calls
  generate() for each, scores results against the floor, persists
  to data/eval/<run-id>/<task>.json.

See docs/bleakhouse_anthropic_optionality_migration_plan.md Phase 2.
"""

from enrichment.llm.eval.floors import Floor, FloorOutcome, floor_for_task
from enrichment.llm.eval.fixtures_io import Fixture, FixtureInput, load_fixture
from enrichment.llm.eval.runner import RunResult, run_fixture
from enrichment.llm.eval.scoring import (
    field_presence_match,
    schema_validity,
    set_overlap_jaccard,
)

__all__ = [
    "Floor",
    "FloorOutcome",
    "floor_for_task",
    "Fixture",
    "FixtureInput",
    "load_fixture",
    "RunResult",
    "run_fixture",
    "schema_validity",
    "set_overlap_jaccard",
    "field_presence_match",
]
