"""LLM-as-judge tests with a fake generate_fn (no live network)."""
from __future__ import annotations

from typing import Any

from enrichment.llm import GenerationRequest, GenerationResult
from enrichment.llm.eval.judge import (
    JudgeResult,
    _parse_judge_response,
    judge_listener_pick,
)


def _fake_result(text: str) -> GenerationResult:
    return GenerationResult(
        text=text,
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        hosting="anthropic",
        input_tokens=100,
        output_tokens=20,
        estimated_cost_usd=0.0,
    )


# ── _parse_judge_response ────────────────────────────────────────


def test_parse_judge_response_clean_json() -> None:
    rating, just = _parse_judge_response(
        '{"rating": 4, "justification": "Solid picks; one journal article."}'
    )
    assert rating == 4
    assert "Solid picks" in just


def test_parse_judge_response_json_in_prose() -> None:
    """Judge sometimes wraps the JSON in commentary — regex still extracts."""
    text = (
        'Here is my rating:\n'
        '{"rating": 3, "justification": "Mixed bag."}\n'
        'Reasoning: blah blah.'
    )
    rating, just = _parse_judge_response(text)
    assert rating == 3
    assert just == "Mixed bag."


def test_parse_judge_response_missing_json_returns_minus_one() -> None:
    rating, just = _parse_judge_response("No JSON anywhere.")
    assert rating == -1
    assert "no JSON" in just


def test_parse_judge_response_invalid_rating_returns_minus_one() -> None:
    """Out-of-range or non-int rating → -1."""
    rating, _ = _parse_judge_response('{"rating": 7, "justification": "x"}')
    assert rating == -1
    rating, _ = _parse_judge_response('{"rating": "high", "justification": "x"}')
    assert rating == -1


def test_parse_judge_response_malformed_json_returns_minus_one() -> None:
    rating, just = _parse_judge_response(
        '{"rating": 4, justification: "missing quotes"}'
    )
    assert rating == -1
    assert "parse failed" in just


# ── judge_listener_pick end-to-end with fake generate_fn ─────────


def test_judge_listener_pick_happy_path() -> None:
    captured: dict[str, Any] = {}

    def fake_gen(req: GenerationRequest) -> GenerationResult:
        captured["task"] = req.task
        captured["system"] = req.system
        captured["user"] = req.user
        return _fake_result(
            '{"rating": 4, "justification": "Mostly readable picks."}'
        )

    result = judge_listener_pick(
        input_id="ex-1",
        novel_title="Bleak House",
        candidate_list_text="Candidates (3):\n  [ref-1] x\n  [ref-2] y\n  [ref-3] z",
        candidate_output_text='{"tags": ["ref-1", "ref-3"]}',
        generate_fn=fake_gen,
    )

    assert isinstance(result, JudgeResult)
    assert result.input_id == "ex-1"
    assert result.rating == 4
    assert "readable picks" in result.justification
    assert result.candidate_tags == ["ref-1", "ref-3"]

    # The judge task name routes to the judge; verify the prompt
    # carries the rubric + the novel + the picks.
    assert captured["task"] == "listener_pick_judge"
    assert "Bleak House" in captured["user"]
    assert "ref-1, ref-3" in captured["user"]
    assert "1-5 scale" in captured["system"] or "1-5" in captured["system"]


def test_judge_listener_pick_handles_empty_candidate_output() -> None:
    """If the candidate produced empty text (e.g. Nemotron with too-small
    max_tokens), candidate_tags is empty and the judge still runs but
    can rate the picks as 1 (bad)."""
    def fake_gen(_req: GenerationRequest) -> GenerationResult:
        return _fake_result(
            '{"rating": 1, "justification": "No picks produced."}'
        )

    result = judge_listener_pick(
        input_id="empty",
        novel_title="x",
        candidate_list_text="...",
        candidate_output_text="",
        generate_fn=fake_gen,
    )
    assert result.candidate_tags == []
    assert result.rating == 1


def test_judge_listener_pick_propagates_parse_failure() -> None:
    """Judge returning unparseable text → rating=-1 in JudgeResult."""
    def fake_gen(_req: GenerationRequest) -> GenerationResult:
        return _fake_result("I refuse to rate this.")

    result = judge_listener_pick(
        input_id="x",
        novel_title="x",
        candidate_list_text="...",
        candidate_output_text='{"tags": ["ref-1"]}',
        generate_fn=fake_gen,
    )
    assert result.rating == -1
    assert "no JSON" in result.justification


def test_judge_listener_pick_includes_full_candidate_list_in_prompt() -> None:
    """The judge needs to see the full candidate list so it can verify
    that picked tags correspond to real entries — not hallucinated."""
    captured_user: list[str] = []

    def fake_gen(req: GenerationRequest) -> GenerationResult:
        captured_user.append(req.user)
        return _fake_result('{"rating": 3, "justification": "ok"}')

    candidate_list = (
        "Candidates (3):\n"
        "  [ref-1] Tomalin, \"Charles Dickens: A Life\"\n"
        "  [ref-2] Schlicke, \"Oxford Companion to Dickens\"\n"
        "  [ref-3] Slater, \"Charles Dickens\""
    )
    judge_listener_pick(
        input_id="x",
        novel_title="David Copperfield",
        candidate_list_text=candidate_list,
        candidate_output_text='{"tags": ["ref-1"]}',
        generate_fn=fake_gen,
    )
    assert "Charles Dickens: A Life" in captured_user[0]
    assert "Oxford Companion to Dickens" in captured_user[0]
