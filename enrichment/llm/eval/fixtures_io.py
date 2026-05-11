"""Fixture loading and shape.

A fixture pins a task + a list of inputs. Each input carries
everything the runner needs to make one call via generate():
the system prompt, user message, max_tokens, optional json_schema,
optional baseline output (for set-overlap and field-presence
scoring).

Fixtures live as JSON under enrichment/llm/eval/fixtures/. Format:

    {
      "task": "listener_pick",
      "description": "...",
      "inputs": [
        {
          "id": "fixture-001",
          "system": "...",
          "user": "...",
          "max_tokens": 512,
          "json_schema": null,
          "baseline": {
            "text": "...",
            "tags": ["ref-3", "ref-7"]   // task-specific baseline
          }
        },
        ...
      ]
    }

The `baseline` shape is task-specific; the runner peeks at the
task class via the floor to know how to interpret it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = REPO_ROOT / "enrichment" / "llm" / "eval" / "fixtures"


@dataclass(frozen=True)
class FixtureInput:
    """One input row in a fixture."""

    id: str
    system: str | None
    user: str
    max_tokens: int
    json_schema: dict[str, Any] | None = None
    # Baseline output — interpreted by the runner per task class.
    # Common shapes:
    #   {"text": "..."}                        — free-text baseline
    #   {"text": "...", "tags": ["ref-3", ...]}— listener_pick-shape
    #   {"text": "...", "fields": ["...", ...]}— field-presence baseline
    baseline: dict[str, Any] | None = None


@dataclass(frozen=True)
class Fixture:
    """A loaded fixture file."""

    task: str
    description: str
    inputs: list[FixtureInput] = field(default_factory=list)


def load_fixture(path: Path | str) -> Fixture:
    """Load a fixture from disk."""
    p = Path(path)
    payload = json.loads(p.read_text())
    inputs = [
        FixtureInput(
            id=row["id"],
            system=row.get("system"),
            user=row["user"],
            max_tokens=row["max_tokens"],
            json_schema=row.get("json_schema"),
            baseline=row.get("baseline"),
        )
        for row in payload.get("inputs", [])
    ]
    return Fixture(
        task=payload["task"],
        description=payload.get("description", ""),
        inputs=inputs,
    )


def load_fixture_by_name(name: str) -> Fixture:
    """Convenience: load by basename (without `.json` suffix) from
    the standard fixtures directory."""
    return load_fixture(FIXTURES_DIR / f"{name}.json")
