"""Pure scoring functions used by the eval runner.

These take dicts / strings / sets and return numbers in [0, 1] — no
LLM calls, no provider state, no IO. The runner orchestrates by
calling these against fixture inputs + candidate outputs.

Per Principle 3 of the migration plan, the seam treats JSON Schema
as the contract; scoring functions check candidate output against
the schema and against optional baseline outputs.
"""
from __future__ import annotations

import json
from typing import Any


def schema_validity(text: str, json_schema: dict[str, Any] | None) -> float:
    """Return 1.0 if `text` parses to JSON valid against `json_schema`,
    else 0.0. Returns 1.0 when no schema was requested (free-text task).

    Strict mode is delegated to the configured validator; this
    function uses a minimal-overhead approach (json.loads + a small
    structural check) to avoid pulling jsonschema as a hard dep.
    Callers needing strict draft-2020-12 validation can pass results
    through their own validator (e.g. Pydantic .model_validate_json).
    """
    if json_schema is None:
        return 1.0
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return 0.0
    # Minimal structural check — does the top-level shape match the
    # schema's `type`? Full validation would require jsonschema; we
    # keep this pure-Python so the eval harness has no extra deps.
    expected_type = json_schema.get("type")
    if expected_type == "object" and not isinstance(parsed, dict):
        return 0.0
    if expected_type == "array" and not isinstance(parsed, list):
        return 0.0
    return 1.0


def set_overlap_jaccard(
    candidate: set[str] | list[str],
    baseline: set[str] | list[str],
) -> float:
    """Jaccard overlap between two sets of identifiers.

    Used for listener-pick-style tasks where the output is a set of
    picks (e.g. ref-tags) and the floor is set-overlap vs baseline.

    Returns 1.0 when both sets are empty (no picks expected); 0.0
    when only one is empty.
    """
    c = set(candidate)
    b = set(baseline)
    if not c and not b:
        return 1.0
    union = c | b
    if not union:
        return 1.0
    intersection = c & b
    return len(intersection) / len(union)


def field_presence_match(
    candidate: dict[str, Any],
    expected_fields: list[str],
) -> float:
    """Fraction of `expected_fields` present (top-level keys with
    non-None values) in `candidate`.

    Used for structured_intermediate tasks where the floor is
    'candidate fills the schema as completely as the baseline did'.
    `expected_fields` is typically derived from the baseline output:
    the fields the baseline populated. The candidate is graded on
    how many of those it also populated.
    """
    if not expected_fields:
        return 1.0
    present = sum(
        1 for f in expected_fields
        if f in candidate and candidate[f] is not None
    )
    return present / len(expected_fields)


def extract_tags_from_listener_pick_response(text: str) -> list[str]:
    """Parse the listener-pick LLM's JSON response into a list of
    ref-tag identifiers.

    Format (from enrichment/host_prep.py): the model emits a single
    JSON object like {"tags": ["ref-3", "ref-7", ...]}. We mirror the
    regex-based extractor in host_prep here (looser than strict JSON
    parsing — the model sometimes emits prose around the JSON).
    """
    import re
    m = re.search(r'\{[^{}]*"tags"[^{}]*\}', text, re.DOTALL)
    if m is None:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    tags = data.get("tags") or []
    return [t for t in tags if isinstance(t, str)]
