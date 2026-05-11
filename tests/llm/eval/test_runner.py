"""End-to-end runner tests with a fake generate() function.

The runner is the only piece that calls into the provider layer.
Tests inject a fake `generate_fn` so no live calls are made, no
ANTHROPIC_API_KEY required.
"""
from __future__ import annotations

import json
from pathlib import Path

from enrichment.llm import GenerationRequest, GenerationResult
from enrichment.llm.eval import (
    Fixture,
    FixtureInput,
    floors,
    run_fixture,
)


def _make_listener_pick_fixture(
    *,
    baseline_tags: list[str],
    inputs_count: int = 1,
) -> Fixture:
    return Fixture(
        task="listener_pick",
        description="test",
        inputs=[
            FixtureInput(
                id=f"ex-{i}",
                system="be brief",
                user="pick some tags",
                max_tokens=128,
                baseline={"tags": baseline_tags},
            )
            for i in range(inputs_count)
        ],
    )


def _result(text: str, *, input_tokens: int = 100, output_tokens: int = 20) -> GenerationResult:
    return GenerationResult(
        text=text,
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        hosting="anthropic",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=(input_tokens / 1_000_000) * 1.0
        + (output_tokens / 1_000_000) * 5.0,
    )


def test_run_fixture_pass_listener_pick(tmp_path: Path) -> None:
    """All picks match baseline → set_overlap = 1.0, floor passes."""
    fixture = _make_listener_pick_fixture(baseline_tags=["ref-1", "ref-2"])
    fake_response = _result('{"tags": ["ref-1", "ref-2"]}')

    result = run_fixture(
        fixture,
        run_id="test-pass",
        generate_fn=lambda _req: fake_response,
        persist=False,
    )

    assert result.outcome == floors.FloorOutcome.PASS
    assert result.schema_validity_mean == 1.0
    assert result.set_overlap_mean == 1.0
    assert result.n_inputs == 1
    assert result.provider == "anthropic"
    assert result.total_cost_usd is not None


def test_run_fixture_fail_listener_pick_low_overlap(tmp_path: Path) -> None:
    """Candidate picks nothing in common with baseline → overlap = 0."""
    fixture = _make_listener_pick_fixture(baseline_tags=["ref-1", "ref-2"])
    fake_response = _result('{"tags": ["ref-99", "ref-100"]}')

    result = run_fixture(
        fixture,
        run_id="test-fail",
        generate_fn=lambda _req: fake_response,
        persist=False,
    )

    assert result.outcome == floors.FloorOutcome.FAIL
    assert result.set_overlap_mean == 0.0
    assert "set_overlap_mean" in result.outcome_reason


def test_run_fixture_persists_to_disk(tmp_path: Path, monkeypatch) -> None:
    """When persist=True, results land at data/eval/<run_id>/<task>.json."""
    from enrichment.llm.eval import storage

    monkeypatch.setattr(storage, "EVAL_ROOT", tmp_path)

    fixture = _make_listener_pick_fixture(baseline_tags=["ref-1"])
    run_fixture(
        fixture,
        run_id="test-persist",
        generate_fn=lambda _req: _result('{"tags": ["ref-1"]}'),
        persist=True,
    )

    path = tmp_path / "test-persist" / "listener_pick.json"
    assert path.exists()
    payload = json.loads(path.read_text())
    assert payload["task"] == "listener_pick"
    assert payload["outcome"] == "pass"
    assert payload["provider"] == "anthropic"
    assert payload["set_overlap_mean"] == 1.0


def test_run_fixture_inconclusive_when_baseline_missing(tmp_path: Path) -> None:
    """Floor specifies set_overlap_min but fixture inputs have no
    baseline.tags → outcome is INCONCLUSIVE, not FAIL."""
    fixture = Fixture(
        task="listener_pick",
        description="no baseline",
        inputs=[
            FixtureInput(
                id="ex-1",
                system=None,
                user="u",
                max_tokens=10,
                baseline=None,
            ),
        ],
    )
    result = run_fixture(
        fixture,
        run_id="test-inconclusive",
        generate_fn=lambda _req: _result("anything"),
        persist=False,
    )
    assert result.outcome == floors.FloorOutcome.INCONCLUSIVE
    assert "baseline" in result.outcome_reason.lower()


def test_run_fixture_schema_validity_check(tmp_path: Path) -> None:
    """When a fixture input has json_schema and the response isn't
    valid JSON, schema_validity_mean drops below the floor (1.0)
    and outcome is FAIL."""
    fixture = Fixture(
        task="passage_enrichment",
        description="schema check",
        inputs=[
            FixtureInput(
                id="ex-1",
                system=None,
                user="u",
                max_tokens=10,
                json_schema={"type": "object"},
                baseline={"fields": ["x", "y"]},
            ),
        ],
    )
    result = run_fixture(
        fixture,
        run_id="test-schema-fail",
        generate_fn=lambda _req: _result("not valid json"),
        persist=False,
    )
    assert result.outcome == floors.FloorOutcome.FAIL
    assert result.schema_validity_mean == 0.0
    assert "schema_validity" in result.outcome_reason


def test_run_fixture_n_inputs_averaging(tmp_path: Path) -> None:
    """Multi-input fixture: set_overlap_mean is the per-input mean."""
    fixture = _make_listener_pick_fixture(
        baseline_tags=["ref-1", "ref-2"],
        inputs_count=2,
    )
    # First call → perfect overlap (1.0). Second → no overlap (0.0).
    calls = iter([
        _result('{"tags": ["ref-1", "ref-2"]}'),
        _result('{"tags": ["ref-99"]}'),
    ])
    result = run_fixture(
        fixture,
        run_id="test-avg",
        generate_fn=lambda _req: next(calls),
        persist=False,
    )
    # (1.0 + 0.0) / 2 = 0.5
    assert result.set_overlap_mean == 0.5
    assert result.n_inputs == 2
    # 0.5 < 0.85 floor → FAIL
    assert result.outcome == floors.FloorOutcome.FAIL


def test_run_fixture_resolves_task_to_correct_model(tmp_path: Path) -> None:
    """The runner pulls the ModelSpec from settings and records the
    actual provider/model on the result."""
    fixture = _make_listener_pick_fixture(baseline_tags=["ref-1"])
    captured: list[GenerationRequest] = []

    def gen(req: GenerationRequest) -> GenerationResult:
        captured.append(req)
        return _result('{"tags": ["ref-1"]}')

    result = run_fixture(
        fixture,
        run_id="test-routing",
        generate_fn=gen,
        persist=False,
    )

    assert len(captured) == 1
    assert captured[0].task == "listener_pick"
    # Spec for listener_pick is currently Anthropic Haiku per settings.
    assert result.provider == "anthropic"
    assert result.model == "claude-haiku-4-5-20251001"
