"""Seam tool-use loop tests (BleakHouse-otae C5).

Uses fake clients — no live API calls. Tests cover:
  - Anthropic and OpenAI both loop correctly and produce the same
    transcript shape (parsed-dict args, name, output, iteration).
  - Tool-result blocks are routed by the right ID per provider.
  - Executor errors are captured as strings (not raised).
  - max_tool_iterations cap is honoured.
  - Parallel tool calls in one turn execute in order and all get
    matching tool_result blocks.
  - Empty tool_executors with non-empty tools raises at request time.

The Anthropic and OpenAI cases share a `script` parameter — a sequence of
canned responses the fake client serves in order — so the test bodies
mirror each other where the seam abstracts the differences.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from enrichment.llm.providers.anthropic_provider import AnthropicProvider
from enrichment.llm.providers.openai_compatible_provider import (
    OpenAICompatibleProvider,
)
from enrichment.llm.types import GenerationRequest, ModelSpec, ToolSpec


# ─────────────────────────────────────────────────────────────────
# Anthropic fakes
# ─────────────────────────────────────────────────────────────────


@dataclass
class _ATextBlock:
    text: str
    type: str = "text"


@dataclass
class _AToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]
    type: str = "tool_use"


@dataclass
class _AUsage:
    input_tokens: int = 10
    output_tokens: int = 5
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None


@dataclass
class _AResponse:
    content: list[Any]
    stop_reason: str
    usage: _AUsage = field(default_factory=_AUsage)


class _FakeAnthropicMessages:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._script: list[_AResponse] = []

    def queue(self, *responses: _AResponse) -> None:
        self._script.extend(responses)

    def create(self, **kwargs: Any) -> _AResponse:
        self.calls.append(kwargs)
        assert self._script, "fake anthropic ran out of canned responses"
        return self._script.pop(0)


class _FakeAnthropicClient:
    def __init__(self) -> None:
        self.messages = _FakeAnthropicMessages()


def _aspec() -> ModelSpec:
    return ModelSpec(
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        hosting="anthropic",
    )


# ─────────────────────────────────────────────────────────────────
# OpenAI fakes (Chat Completions shape)
# ─────────────────────────────────────────────────────────────────


@dataclass
class _OFunction:
    name: str
    arguments: str   # JSON string


@dataclass
class _OToolCall:
    id: str
    function: _OFunction
    type: str = "function"


@dataclass
class _OMessage:
    content: str | None = None
    tool_calls: list[_OToolCall] | None = None


@dataclass
class _OChoice:
    message: _OMessage
    finish_reason: str = "stop"


@dataclass
class _OUsage:
    prompt_tokens: int = 10
    completion_tokens: int = 5
    prompt_tokens_details: Any = None


@dataclass
class _OResponse:
    choices: list[_OChoice]
    usage: _OUsage = field(default_factory=_OUsage)


class _FakeOpenAICompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._script: list[_OResponse] = []

    def queue(self, *responses: _OResponse) -> None:
        self._script.extend(responses)

    def create(self, **kwargs: Any) -> _OResponse:
        self.calls.append(kwargs)
        assert self._script, "fake openai ran out of canned responses"
        return self._script.pop(0)


class _FakeOpenAIChat:
    def __init__(self) -> None:
        self.completions = _FakeOpenAICompletions()


class _FakeOpenAIClient:
    def __init__(self) -> None:
        self.chat = _FakeOpenAIChat()


def _ospec(*, hosting: str = "openai") -> ModelSpec:
    return ModelSpec(
        provider="openai_compatible",
        model="gpt-5-mini",
        hosting=hosting,
    )


# ─────────────────────────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────────────────────────


def _echo_tool() -> ToolSpec:
    return ToolSpec(
        name="echo",
        description="Echo back its msg argument.",
        input_schema={
            "type": "object",
            "properties": {"msg": {"type": "string"}},
            "required": ["msg"],
        },
    )


def _request(tool: ToolSpec, executors: dict[str, Any], *, max_iters: int = 4) -> GenerationRequest:
    return GenerationRequest(
        task="probe",
        system="you call tools when needed",
        user="please call echo with msg=hi then say done",
        max_tokens=200,
        tools=(tool,),
        tool_executors=executors,
        max_tool_iterations=max_iters,
    )


# ─────────────────────────────────────────────────────────────────
# Anthropic tests
# ─────────────────────────────────────────────────────────────────


def test_anthropic_single_tool_call_then_stop() -> None:
    client = _FakeAnthropicClient()
    client.messages.queue(
        _AResponse(
            content=[_AToolUseBlock(id="tu_01", name="echo", input={"msg": "hi"})],
            stop_reason="tool_use",
        ),
        _AResponse(
            content=[_ATextBlock(text="Done.")],
            stop_reason="end_turn",
        ),
    )
    provider = AnthropicProvider(client=client)
    result = provider.generate(
        _aspec(),
        _request(_echo_tool(), {"echo": lambda d: f"echo:{d['msg']}"}),
    )

    assert result.text == "Done."
    assert len(result.tool_transcript) == 1
    tc = result.tool_transcript[0]
    assert tc.name == "echo"
    assert tc.arguments == {"msg": "hi"}
    assert tc.output == "echo:hi"
    assert tc.iteration == 0
    # Per-turn usage accumulated across both loop turns
    assert result.input_tokens == 20  # 10 + 10
    assert result.output_tokens == 10  # 5 + 5


def test_anthropic_parallel_tool_calls_in_one_turn() -> None:
    """Anthropic can emit multiple tool_use blocks in one response; the seam
    must execute all of them, in order, and send back matching tool_result
    blocks keyed by tool_use_id."""
    client = _FakeAnthropicClient()
    client.messages.queue(
        _AResponse(
            content=[
                _AToolUseBlock(id="a", name="echo", input={"msg": "one"}),
                _AToolUseBlock(id="b", name="echo", input={"msg": "two"}),
            ],
            stop_reason="tool_use",
        ),
        _AResponse(content=[_ATextBlock(text="Both done.")], stop_reason="end_turn"),
    )
    provider = AnthropicProvider(client=client)
    result = provider.generate(
        _aspec(),
        _request(_echo_tool(), {"echo": lambda d: f"echo:{d['msg']}"}),
    )

    assert result.text == "Both done."
    names = [tc.arguments["msg"] for tc in result.tool_transcript]
    assert names == ["one", "two"]
    # Second turn's user-message routes both results back keyed by tool_use_id.
    second_call_messages = client.messages.calls[1]["messages"]
    assistant_msg, user_msg = second_call_messages[-2], second_call_messages[-1]
    assert assistant_msg["role"] == "assistant"
    assert user_msg["role"] == "user"
    user_ids = sorted(b["tool_use_id"] for b in user_msg["content"])
    assert user_ids == ["a", "b"]


def test_anthropic_executor_error_returned_as_string() -> None:
    """Executor raises → seam captures the error as a tool_result string so
    the model can recover (or at least continue). Loop must not abort."""
    def broken(_args: dict) -> str:
        raise RuntimeError("boom")

    client = _FakeAnthropicClient()
    client.messages.queue(
        _AResponse(
            content=[_AToolUseBlock(id="x", name="echo", input={"msg": "?"})],
            stop_reason="tool_use",
        ),
        _AResponse(content=[_ATextBlock(text="ok recovered")], stop_reason="end_turn"),
    )
    provider = AnthropicProvider(client=client)
    result = provider.generate(_aspec(), _request(_echo_tool(), {"echo": broken}))

    assert "ok recovered" in result.text
    assert "tool error: RuntimeError: boom" in result.tool_transcript[0].output


def test_anthropic_max_iterations_cap_honoured() -> None:
    """If the model never emits end_turn within the budget, the seam stops
    and returns the accumulated transcript without raising."""
    client = _FakeAnthropicClient()
    # Always asks for another tool call; would loop forever without the cap.
    for i in range(10):
        client.messages.queue(_AResponse(
            content=[_AToolUseBlock(id=f"t{i}", name="echo", input={"msg": str(i)})],
            stop_reason="tool_use",
        ))
    provider = AnthropicProvider(client=client)
    result = provider.generate(
        _aspec(),
        _request(_echo_tool(), {"echo": lambda d: "x"}, max_iters=2),
    )
    # max_tool_iterations=2 means 3 loop turns (range(2+1)); each turn does
    # one tool call. After turn 2 the loop body runs once more (turn 3) but
    # there's no end_turn so the loop exits at the cap.
    assert len(result.tool_transcript) == 3


# ─────────────────────────────────────────────────────────────────
# OpenAI tests
# ─────────────────────────────────────────────────────────────────


def _otoolcall(call_id: str, name: str, args: dict) -> _OToolCall:
    return _OToolCall(
        id=call_id,
        function=_OFunction(name=name, arguments=json.dumps(args)),
    )


def test_openai_single_tool_call_then_stop() -> None:
    client = _FakeOpenAIClient()
    client.chat.completions.queue(
        _OResponse(
            choices=[_OChoice(
                message=_OMessage(
                    content=None,
                    tool_calls=[_otoolcall("call_x", "echo", {"msg": "hi"})],
                ),
                finish_reason="tool_calls",
            )],
        ),
        _OResponse(
            choices=[_OChoice(
                message=_OMessage(content="Done."),
                finish_reason="stop",
            )],
        ),
    )
    provider = OpenAICompatibleProvider(client=client)
    result = provider.generate(
        _ospec(),
        _request(_echo_tool(), {"echo": lambda d: f"echo:{d['msg']}"}),
    )

    assert result.text == "Done."
    tc = result.tool_transcript[0]
    assert tc.name == "echo"
    # Seam normalised the JSON-string arguments to a parsed dict.
    assert tc.arguments == {"msg": "hi"}
    assert tc.output == "echo:hi"
    # Second call's messages include role=tool with the result keyed by call_id.
    second_msgs = client.chat.completions.calls[1]["messages"]
    tool_msg = next(m for m in second_msgs if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "call_x"
    assert tool_msg["content"] == "echo:hi"


def test_openai_parallel_tool_calls_in_one_turn() -> None:
    client = _FakeOpenAIClient()
    client.chat.completions.queue(
        _OResponse(
            choices=[_OChoice(
                message=_OMessage(
                    content=None,
                    tool_calls=[
                        _otoolcall("a", "echo", {"msg": "one"}),
                        _otoolcall("b", "echo", {"msg": "two"}),
                    ],
                ),
                finish_reason="tool_calls",
            )],
        ),
        _OResponse(
            choices=[_OChoice(
                message=_OMessage(content="Both done."),
                finish_reason="stop",
            )],
        ),
    )
    provider = OpenAICompatibleProvider(client=client)
    result = provider.generate(
        _ospec(),
        _request(_echo_tool(), {"echo": lambda d: f"echo:{d['msg']}"}),
    )
    names = [tc.arguments["msg"] for tc in result.tool_transcript]
    assert names == ["one", "two"]
    # Second call has TWO role:tool messages, one per call.
    second_msgs = client.chat.completions.calls[1]["messages"]
    tool_ids = sorted(m["tool_call_id"] for m in second_msgs if m["role"] == "tool")
    assert tool_ids == ["a", "b"]


def test_openai_executor_error_returned_as_string() -> None:
    def broken(_args: dict) -> str:
        raise ValueError("nope")

    client = _FakeOpenAIClient()
    client.chat.completions.queue(
        _OResponse(choices=[_OChoice(
            message=_OMessage(
                content=None,
                tool_calls=[_otoolcall("x", "echo", {"msg": "?"})],
            ),
            finish_reason="tool_calls",
        )]),
        _OResponse(choices=[_OChoice(
            message=_OMessage(content="recovered"),
            finish_reason="stop",
        )]),
    )
    provider = OpenAICompatibleProvider(client=client)
    result = provider.generate(_ospec(), _request(_echo_tool(), {"echo": broken}))
    assert "recovered" in result.text
    assert "tool error: ValueError: nope" in result.tool_transcript[0].output


def test_openai_chat_completions_tool_spec_shape() -> None:
    """The seam sends Chat Completions tool format: {type: 'function',
    function: {name, description, parameters}}. Anthropic gets a different
    shape — test that here separately for symmetry."""
    client = _FakeOpenAIClient()
    client.chat.completions.queue(
        _OResponse(choices=[_OChoice(
            message=_OMessage(content="ok"),
            finish_reason="stop",
        )]),
    )
    provider = OpenAICompatibleProvider(client=client)
    provider.generate(_ospec(), _request(_echo_tool(), {"echo": lambda d: "ok"}))
    sent = client.chat.completions.calls[0]
    assert sent["tools"] == [{
        "type": "function",
        "function": {
            "name": "echo",
            "description": "Echo back its msg argument.",
            "parameters": {
                "type": "object",
                "properties": {"msg": {"type": "string"}},
                "required": ["msg"],
            },
        },
    }]


# ─────────────────────────────────────────────────────────────────
# Shared validation
# ─────────────────────────────────────────────────────────────────


def test_missing_executors_raises_for_both_providers() -> None:
    req = GenerationRequest(
        task="probe", system=None, user="hi", max_tokens=100,
        tools=(_echo_tool(),),
        tool_executors=None,
    )
    with pytest.raises(ValueError, match="tool_executors is empty"):
        AnthropicProvider(client=_FakeAnthropicClient()).generate(_aspec(), req)
    with pytest.raises(ValueError, match="tool_executors is empty"):
        OpenAICompatibleProvider(client=_FakeOpenAIClient()).generate(_ospec(), req)
