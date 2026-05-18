"""Tests for host_prep.run_pre_interview (D2 migration).

The no-refs pre-interview now routes through enrichment.llm.generate
with a JSON schema and a Pydantic-side parse. These tests inject a
fake AnthropicProvider so the real seam dispatch runs without
hitting the network.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from enrichment.host_prep import run_pre_interview
from enrichment.llm import client as llm_client
from enrichment.llm import settings
from enrichment.llm.providers import AnthropicProvider
from enrichment.llm.schemas import PreInterviewResponse
from enrichment.personas import (
    ExpertPersona,
    VoicePolicy,
)
@dataclass
class _Blk:
    text: str
    type: str = "text"


@dataclass
class _Usage:
    input_tokens: int = 100
    output_tokens: int = 50
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None


@dataclass
class _Resp:
    content: list[Any]
    stop_reason: str = "end_turn"
    usage: _Usage = field(default_factory=_Usage)


class _FakeMessages:
    def __init__(self, *responses: _Resp) -> None:
        self.calls: list[dict[str, Any]] = []
        self._queue = list(responses)

    def create(self, **kwargs: Any) -> _Resp:
        self.calls.append(kwargs)
        if not self._queue:
            raise AssertionError("fake anthropic ran out of canned responses")
        return self._queue.pop(0)


class _FakeAnthropic:
    def __init__(self, *responses: _Resp) -> None:
        self.messages = _FakeMessages(*responses)


def _expert() -> ExpertPersona:
    return ExpertPersona(
        name="Test Expert",
        role="critic",
        description="A test critic.",
        voice_policy=VoicePolicy(
            rate=1.0, energy="medium", pause_bias_ms=200, style="neutral",
        ),
    )


def _valid_payload() -> str:
    return json.dumps({
        "expert_name": "Test Expert",
        "key_points": ["point A", "point B"],
        "potential_quotes": ["quote one"],
        "disagreement_angles": [],
        "strongest_take": "",
        "proposed_references": [],
    })


def _inject(monkeypatch, *responses: _Resp) -> _FakeAnthropic:
    fake = _FakeAnthropic(*responses)
    provider = AnthropicProvider(client=fake)
    monkeypatch.setattr(llm_client, "_anthropic_provider", provider)
    return fake


def _assignments() -> list[dict]:
    return [{
        "passage_id": "p1",
        "char_start": 0,
        "char_end": 100,
        "rationale": "test passage",
    }]


def test_pre_interview_happy_path(monkeypatch) -> None:
    settings.activate()
    fake = _inject(monkeypatch, _Resp(content=[_Blk(text=_valid_payload())]))
    result = run_pre_interview(
        _expert(), other_expert_names=["Other A"],
        segment_name="Test Segment",
        assignments=_assignments(),
        novel_title="Bleak House", novel_author="Dickens",
    )
    assert isinstance(result, PreInterviewResponse)
    assert result.expert_name == "Test Expert"
    assert result.key_points == ["point A", "point B"]
    # Single call; carries the seam-built json_schema (not Pydantic class)
    kwargs = fake.messages.calls[0]
    # output_config is what AnthropicProvider sets for json_schema requests
    assert "output_config" in kwargs
    assert kwargs["output_config"]["format"]["type"] == "json_schema"


def test_pre_interview_retries_on_validation_failure(monkeypatch) -> None:
    """Pydantic raises on bad JSON → retry once → succeed."""
    settings.activate()
    fake = _inject(
        monkeypatch,
        _Resp(content=[_Blk(text="not valid json")]),
        _Resp(content=[_Blk(text=_valid_payload())]),
    )
    result = run_pre_interview(
        _expert(), [], "S", _assignments(), "X", "Y",
    )
    assert result.key_points == ["point A", "point B"]
    assert len(fake.messages.calls) == 2


def test_pre_interview_raises_after_all_retries_exhausted(monkeypatch) -> None:
    """Three invalid responses → final attempt raises (last_error bubbles)."""
    settings.activate()
    _inject(
        monkeypatch,
        _Resp(content=[_Blk(text="bad")]),
        _Resp(content=[_Blk(text="bad")]),
        _Resp(content=[_Blk(text="bad")]),
    )
    with pytest.raises(Exception):  # noqa: BLE001 — Pydantic ValidationError is what we expect
        run_pre_interview(
            _expert(), [], "S", _assignments(), "X", "Y",
        )
