"""Tests for host_prep._select_listener_recommendations (D1 migration).

The winnower now routes through enrichment.llm.generate. These tests inject
a fake AnthropicProvider so the call goes through the real seam dispatch
(settings → client.generate → AnthropicProvider.generate) but without
hitting the network.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from enrichment.host_prep import _select_listener_recommendations
from enrichment.llm import client as llm_client
from enrichment.llm import settings
from enrichment.llm.providers import AnthropicProvider
from enrichment.reference_tools import CitationRecord


@dataclass
class _FakeBlock:
    text: str
    type: str = "text"


@dataclass
class _FakeUsage:
    input_tokens: int = 20
    output_tokens: int = 5
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None


@dataclass
class _FakeResponse:
    content: list[Any]
    stop_reason: str = "end_turn"
    usage: _FakeUsage = field(default_factory=_FakeUsage)


class _FakeMessages:
    def __init__(self, canned_text: str) -> None:
        self.calls: list[dict[str, Any]] = []
        self._canned = canned_text

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        return _FakeResponse(content=[_FakeBlock(text=self._canned)])


class _FakeAnthropic:
    def __init__(self, canned_text: str) -> None:
        self.messages = _FakeMessages(canned_text)


def _candidates() -> list[CitationRecord]:
    return [
        CitationRecord(tag="ref-1", title="Bleak House Companion",
                       authors=["A"], year="2020", type="book"),
        CitationRecord(tag="ref-2", title="Dickens Reader",
                       authors=["B"], year="2018", type="book"),
        CitationRecord(tag="ref-3", title="Niche Paper",
                       authors=["C"], year="2024", type="article"),
    ]


def _inject_fake_anthropic(monkeypatch, canned_text: str) -> _FakeAnthropic:
    """Swap the seam's cached AnthropicProvider for one wrapping the fake.
    Restores the cache on teardown."""
    fake = _FakeAnthropic(canned_text)
    provider = AnthropicProvider(client=fake)
    monkeypatch.setattr(llm_client, "_anthropic_provider", provider)
    return fake


def test_winnower_dispatches_through_seam_returns_picked_tags(monkeypatch) -> None:
    """The model's JSON response picks ref-1 and ref-2; winnower returns
    those and only those (drops anything not in the available set)."""
    settings.activate()  # production
    fake = _inject_fake_anthropic(
        monkeypatch, '{"tags": ["ref-1", "ref-2", "ref-invalid"]}',
    )

    picks = _select_listener_recommendations(
        _candidates(), novel_title="Bleak House", novel_author="Dickens",
    )
    assert sorted(picks) == ["ref-1", "ref-2"]
    # The seam built the request: one create call with the listener-pick
    # system prompt + a user block listing candidates.
    assert len(fake.messages.calls) == 1
    kwargs = fake.messages.calls[0]
    assert "Bleak House" in kwargs["system"]
    assert "ref-3" in kwargs["messages"][0]["content"]   # candidate listed


def test_winnower_empty_candidates_short_circuits() -> None:
    """No model call at all when there's nothing to filter."""
    assert _select_listener_recommendations(
        [], "X", "Y",
    ) == []


def test_winnower_falls_back_to_all_on_parse_failure(monkeypatch) -> None:
    """Model returned junk → fall back to all candidates rather than drop them."""
    settings.activate()
    _inject_fake_anthropic(monkeypatch, "This is not JSON. No tags here.")
    picks = _select_listener_recommendations(
        _candidates(), novel_title="Bleak House", novel_author="Dickens",
    )
    # All three candidates returned.
    assert sorted(picks) == ["ref-1", "ref-2", "ref-3"]


def test_winnower_active_profile_decides_provider(monkeypatch) -> None:
    """Smoke: under production profile the call routes through the
    Anthropic provider, so our injected fake gets called."""
    settings.activate()  # production → Anthropic
    fake = _inject_fake_anthropic(monkeypatch, json.dumps({"tags": ["ref-1"]}))
    _select_listener_recommendations(_candidates()[:1], "X", "Y")
    assert len(fake.messages.calls) == 1, (
        "production profile must route to Anthropic"
    )
