"""Citation verifier — OpenAlex + Wikipedia, two Haiku calls per citation.

Per citation:
  1. CLEAN — Haiku reads the raw citation, outputs a search query and a
     hint about whether to lead with OpenAlex or Wikipedia.
  2. APIs — search the chosen source(s) with that query (no LLM here).
  3. JUDGE — Haiku sees raw + candidates, picks the matching one (or
     null) and writes the listener-facing description.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Literal

import anthropic
from anthropic.types import MessageParam

from .match import audience
from .sources import openalex_search, wikipedia_search

logger = logging.getLogger(__name__)

AGENT_MODEL = "claude-haiku-4-5-20251001"
HAIKU_INPUT_PER_MTOK = 1.00
HAIKU_OUTPUT_PER_MTOK = 5.00


@dataclass(frozen=True)
class ReadingListEntry:
    raw_text: str
    verified: bool
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    type: str | None = None
    publisher: str | None = None
    description: str | None = None
    cited_by: int | None = None
    url: str | None = None
    source: str | None = None
    audience: Literal["general", "scholarly"] | None = None
    haiku_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def cost_usd(self) -> float:
        return (
            self.input_tokens * HAIKU_INPUT_PER_MTOK / 1_000_000
            + self.output_tokens * HAIKU_OUTPUT_PER_MTOK / 1_000_000
        )


CLEAN_PROMPT = """\
You receive a raw scholarly citation. Output ONE JSON object only:

{"plausible": true|false, "kind": "academic"|"canonical", "query": "..."}

- plausible: false only for obvious fabrications. When in doubt, true.
- kind: "canonical" for Acts, named events, famous works, official
  reports, persons. "academic" for everything else.
- query: how you'd type this into a search box.
"""


JUDGE_PROMPT = """\
You have a citation and a list of CANDIDATES. Pick the one that is the
cited work, or null if none clearly is. Write 1-2 plain-English
sentences from that candidate's abstract or extract for a podcast
listener.

Output ONE JSON object only:
{"matched_index": <0-based index, or null>, "description": "<1-2 sentences, or empty>"}
"""


def _extract_text(content_blocks: Any) -> str:
    return "".join(
        getattr(b, "text", "")
        for b in content_blocks
        if getattr(b, "type", None) == "text" and getattr(b, "text", "")
    )


_JSON_RE = re.compile(r"\{.*?\}", re.DOTALL)


@dataclass(frozen=True)
class _Cleaned:
    plausible: bool
    kind: str
    query: str


def _parse_clean(text: str) -> _Cleaned | None:
    m = _JSON_RE.search(text)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    query = str(data.get("query") or "").strip()
    if not query:
        return None
    kind = data.get("kind") or "academic"
    if kind not in ("academic", "canonical"):
        kind = "academic"
    return _Cleaned(
        plausible=bool(data.get("plausible", True)),
        kind=kind,
        query=query,
    )


def _candidate_for_judge(c: dict[str, Any]) -> dict[str, Any]:
    abstract = c.get("abstract") or ""
    if len(abstract) > 700:
        abstract = abstract[:700] + "…"
    return {
        "title": c.get("title"),
        "authors": c.get("authors"),
        "year": c.get("year"),
        "type": c.get("type"),
        "publisher": c.get("publisher"),
        "venue": c.get("venue"),
        "abstract": abstract,
        "cited_by": c.get("cited_by"),
        "url": c.get("url"),
        "source": c.get("source"),
    }


def _parse_judge(text: str) -> tuple[int | None, str]:
    m = _JSON_RE.search(text)
    if not m:
        return None, ""
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None, ""
    raw_idx = data.get("matched_index")
    if raw_idx is None:
        idx: int | None = None
    else:
        try:
            idx = int(raw_idx)
        except (TypeError, ValueError):
            idx = None
    return idx, str(data.get("description") or "").strip()


def assess_citation(
    raw_text: str,
    *,
    client: anthropic.Anthropic | None = None,
) -> ReadingListEntry:
    """Verify a single citation. Two Haiku calls (clean, then judge)."""
    if client is None:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    input_tokens = 0
    output_tokens = 0

    def _accumulate(usage: Any) -> None:
        nonlocal input_tokens, output_tokens
        input_tokens += getattr(usage, "input_tokens", 0) or 0
        output_tokens += getattr(usage, "output_tokens", 0) or 0

    # ---- CLEAN ----
    clean_messages: list[MessageParam] = [{"role": "user", "content": raw_text}]
    clean_msg = client.messages.create(
        model=AGENT_MODEL,
        max_tokens=200,
        system=CLEAN_PROMPT,
        messages=clean_messages,
    )
    _accumulate(clean_msg.usage)
    cleaned = _parse_clean(_extract_text(clean_msg.content))

    if cleaned is None or not cleaned.plausible:
        return ReadingListEntry(
            raw_text=raw_text, verified=False,
            haiku_calls=1,
            input_tokens=input_tokens, output_tokens=output_tokens,
        )

    # ---- APIs ----
    if cleaned.kind == "canonical":
        candidates = wikipedia_search(cleaned.query) or openalex_search(cleaned.query)
    else:
        oa = openalex_search(cleaned.query)
        wp = wikipedia_search(cleaned.query)
        candidates = oa + wp  # both available to the judge

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for c in candidates:
        url = c.get("url") or ""
        if url and url in seen:
            continue
        if url:
            seen.add(url)
        unique.append(c)

    if not unique:
        return ReadingListEntry(
            raw_text=raw_text, verified=False,
            haiku_calls=1,
            input_tokens=input_tokens, output_tokens=output_tokens,
        )

    # ---- JUDGE ----
    judge_input = "\n".join([
        f"Citation: {raw_text}",
        "",
        "Candidates:",
        json.dumps(
            [_candidate_for_judge(c) for c in unique],
            indent=2, default=str,
        ),
    ])
    judge_msg = client.messages.create(
        model=AGENT_MODEL,
        max_tokens=400,
        system=JUDGE_PROMPT,
        messages=[{"role": "user", "content": judge_input}],
    )
    _accumulate(judge_msg.usage)
    matched_index, description = _parse_judge(_extract_text(judge_msg.content))

    if matched_index is None or not (0 <= matched_index < len(unique)):
        return ReadingListEntry(
            raw_text=raw_text, verified=False,
            haiku_calls=2,
            input_tokens=input_tokens, output_tokens=output_tokens,
        )

    chosen = unique[matched_index]
    return ReadingListEntry(
        raw_text=raw_text, verified=True,
        title=chosen.get("title"),
        authors=list(chosen.get("authors") or []),
        year=chosen.get("year"),
        type=chosen.get("type"),
        publisher=chosen.get("publisher"),
        description=description or None,
        cited_by=chosen.get("cited_by"),
        url=chosen.get("url"),
        source=chosen.get("source"),
        audience=audience(chosen),
        haiku_calls=2,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
