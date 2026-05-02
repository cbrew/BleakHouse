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

import json
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, TypeVar


T = TypeVar("T")


@dataclass
class CallEvent:
    kind: str                  # "model" | "tool" | "tts"
    name: str                  # model id or tool name
    label: str                 # purpose / query / ref_tag
    duration_s: float
    started_at: float = 0.0
    # Anthropic-style usage (kind="model" / "tool"). input_tokens covers
    # only fresh (non-cached, non-write) input tokens; cache reads and
    # writes are billed separately at 0.1x / 1.25x respectively, so they
    # need their own counters for cost reporting to be accurate. Without
    # these, generate_contexts.py-style cached calls would under-report.
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    # TTS-style usage (kind="tts"). input_chars = prompt chars billed by
    # Gemini 2.5 flash/pro TTS; output_audio_ms = milliseconds of audio
    # produced (the second axis of TTS pricing).
    input_chars: int = 0
    output_audio_ms: int = 0
    # True when this call went through Anthropic's Batch API, which
    # bills at 50% of real-time rates. pricing.event_cost halves cost
    # accordingly. Default False for compatibility with existing events.
    batch: bool = False
    expert: str = ""
    segment: str = ""


@dataclass
class Recorder:
    """Accumulator for `CallEvent`s. Thread-safe; pass one Recorder per
    parallel work unit (e.g. per interview) and merge when done.

    If `flush_path` is set, every `record()` call (and every `merge()`)
    persists the full event list to disk atomically — so a crash mid-
    phase still leaves a complete sidecar for everything that did
    succeed, and a watcher tailing the file sees progress live.
    """

    expert: str = ""
    segment: str = ""
    events: list[CallEvent] = field(default_factory=list)
    flush_path: Path | None = None
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
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        input_chars: int = 0,
        output_audio_ms: int = 0,
        batch: bool = False,
    ) -> None:
        with self._lock:
            self.events.append(CallEvent(
                kind=kind, name=name, label=label,
                duration_s=duration_s, started_at=started_at,
                input_tokens=input_tokens, output_tokens=output_tokens,
                cache_creation_input_tokens=cache_creation_input_tokens,
                cache_read_input_tokens=cache_read_input_tokens,
                input_chars=input_chars, output_audio_ms=output_audio_ms,
                batch=batch,
                expert=self.expert, segment=self.segment,
            ))
        self._maybe_flush()

    def _maybe_flush(self) -> None:
        """Persist current events to flush_path if set. Snapshot under
        the lock, write outside it so concurrent record() calls don't
        serialize on disk I/O."""
        if self.flush_path is None:
            return
        with self._lock:
            data = {"events": [asdict(e) for e in self.events]}
        self.flush_path.write_text(json.dumps(data, indent=2))

    def merge(self, other: "Recorder") -> None:
        """Append another recorder's events into this one."""
        with self._lock:
            self.events.extend(other.events)
        self._maybe_flush()

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
        cache_creation_input_tokens=int(
            getattr(usage, "cache_creation_input_tokens", 0) or 0
        ),
        cache_read_input_tokens=int(
            getattr(usage, "cache_read_input_tokens", 0) or 0
        ),
    )
    return response


def time_tts(
    rec: Recorder | None,
    *,
    model: str,
    label: str,
    input_chars: int,
    fn: Callable[[], T],
) -> tuple[T, float]:
    """Time a Gemini TTS call.

    Returns (response, duration_s). The caller knows the produced audio
    duration (from the AudioSegment len) and passes it to record_tts_audio
    once decoding has completed — so audio_ms isn't double-counted on
    cache hits and isn't lost when the response object doesn't expose it.
    """
    t0 = time.monotonic()
    response = fn()
    duration_s = time.monotonic() - t0
    if rec is not None:
        rec.record(
            kind="tts",
            name=model,
            label=label[:120],
            duration_s=duration_s,
            started_at=t0,
            input_chars=input_chars,
            output_audio_ms=0,  # filled in by record_tts_audio
        )
    return response, duration_s


def record_tts_audio(rec: Recorder | None, output_audio_ms: int) -> None:
    """Update the most recent TTS event with its produced audio duration.

    Lets the caller compute audio_ms after pcm decoding without needing
    to plumb it back through the timing wrapper.
    """
    if rec is None:
        return
    with rec._lock:
        for ev in reversed(rec.events):
            if ev.kind == "tts":
                ev.output_audio_ms = output_audio_ms
                return
