"""Per-call timing for the host-prep pipeline.

Every Sonnet/Haiku call and every search-tool call gets a `CallEvent`
appended to a `Recorder`. Recorders can be merged and serialised to a
sidecar file (`phase2_5_timings.json`), which a small analyser script
turns into per-tool / per-model / per-interview summaries.

Usage:
    rec = Recorder(expert="Sir Edmund", segment="Chancery as machine")

    response = time_model(rec, "interview_loop_turn",
                          lambda: client.messages.create(...))

    with time_tool(rec, "search_openalex", "Mary Poovey..."):
        out = execute_search_openalex(...)

The recorder is thread-safe; one recorder per interview is the typical
shape. `merge` aggregates many recorders into one for the final dump.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, TypeVar


T = TypeVar("T")


@dataclass
class CallEvent:
    kind: str                  # "model" | "tool"
    name: str                  # model id or tool name
    label: str                 # purpose / query / ref_tag
    duration_s: float
    started_at: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    expert: str = ""
    segment: str = ""


@dataclass
class Recorder:
    """Accumulator for `CallEvent`s. Thread-safe; pass one Recorder per
    parallel work unit (e.g. per interview) and merge when done."""

    expert: str = ""
    segment: str = ""
    events: list[CallEvent] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(
        self, *,
        kind: str,
        name: str,
        label: str,
        duration_s: float,
        started_at: float = 0.0,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        with self._lock:
            self.events.append(CallEvent(
                kind=kind, name=name, label=label,
                duration_s=duration_s, started_at=started_at,
                input_tokens=input_tokens, output_tokens=output_tokens,
                expert=self.expert, segment=self.segment,
            ))

    def merge(self, other: "Recorder") -> None:
        """Append another recorder's events into this one."""
        with self._lock:
            self.events.extend(other.events)

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "events": [asdict(e) for e in self.events],
            }


@contextmanager
def time_tool(rec: Recorder | None, name: str, label: str):
    """Time a tool call. Records duration regardless of exception."""
    if rec is None:
        yield
        return
    t0 = time.monotonic()
    try:
        yield
    finally:
        rec.record(
            kind="tool", name=name, label=label[:120],
            duration_s=time.monotonic() - t0, started_at=t0,
        )


def time_model(
    rec: Recorder | None,
    label: str,
    fn: Callable[[], T],
) -> T:
    """Call `fn`, time it, record token counts from the returned object's
    `.usage`. Returns whatever `fn` returns."""
    t0 = time.monotonic()
    response = fn()
    if rec is None:
        return response
    usage = getattr(response, "usage", None)
    rec.record(
        kind="model",
        name=str(getattr(response, "model", "?") or "?"),
        label=label[:120],
        duration_s=time.monotonic() - t0,
        started_at=t0,
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
    )
    return response
