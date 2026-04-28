"""Citation verifier — OpenAlex + Wikipedia, two Haiku calls per citation.

Flow:
  1. SEARCH turn — Haiku reads the raw citation, formulates several
     parallel queries (different angles) for search_openalex /
     search_wikipedia. All run concurrently in one turn; pooled results
     come back in one ToolResult batch.
  2. JUDGE turn — Haiku sees the original raw + the candidate list with
     full metadata, picks the best match (or null) and composes a
     1-2 sentence listener-friendly description in one shot.
     Output: {matched_index: int | null, description: str}.

No `parse_citation`, no Jaccard / year-delta gate. The model handles the
matching directly — it has the raw citation and each candidate's title,
authors, year, type, publisher, abstract right in front of it. A
deterministic gate using regex-extracted fields is brittle (the year-
parse bug we just hit) and forfeits the LLM's pattern-matching strength
for no precision gain on tasks where the inputs are right there.

The "audience" flag (general vs scholarly) IS deterministic — it reads
off the candidate's publisher and citation count.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Literal

import anthropic
from anthropic.types import (
    MessageParam,
    ToolUnionParam,
    ToolUseBlock,
)

from .match import audience
from .sources import openalex_search, wikipedia_search

logger = logging.getLogger(__name__)

AGENT_MODEL = "claude-haiku-4-5-20251001"
HAIKU_INPUT_PER_MTOK = 1.00
HAIKU_OUTPUT_PER_MTOK = 5.00


# ---------- Result type ------------------------------------------------------

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


# ---------- Tool schemas (search turn) --------------------------------------

TOOL_DEFS: list[ToolUnionParam] = [
    {
        "name": "search_openalex",
        "description": (
            "OpenAlex academic graph. Broad coverage — articles, books, "
            "chapters, theses, conference papers — with title, authors, "
            "year, type, publisher, abstract, citation count, DOI/URL. "
            "Use for academic citations. Call multiple times in one turn "
            "with different query phrasings (full citation; surname + "
            "title-keywords; surname only) to maximise the chance of "
            "catching the actual work."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text search query."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_wikipedia",
        "description": (
            "English Wikipedia article search with intro extracts. Use for "
            "Acts of Parliament, canonical works, historical events, "
            "well-known persons — items likely to have their own article. "
            "Returns title, intro extract, URL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
        },
    },
]


def _tool_search_openalex(args: dict[str, Any]) -> list[dict[str, Any]]:
    return openalex_search(args["query"])


def _tool_search_wikipedia(args: dict[str, Any]) -> list[dict[str, Any]]:
    return wikipedia_search(args["query"])


TOOL_DISPATCH: dict[str, Any] = {
    "search_openalex": _tool_search_openalex,
    "search_wikipedia": _tool_search_wikipedia,
}


# ---------- Prompts ----------------------------------------------------------

SEARCH_PROMPT = """\
You have a citation to look up against OpenAlex (academic) and
Wikipedia (canonical works, Acts, historical events). Fire several
parallel searches in this single turn with different query angles —
they run concurrently. Don't judge anything here; you'll see all
candidates afterwards.
"""

JUDGE_PROMPT = """\
You have a citation and a list of CANDIDATES. Pick the candidate that
is the work being cited, or null if none clearly is. Then write 1-2
plain-English sentences from that candidate's abstract or extract that
tell a podcast listener what the work is about.

To pick a candidate, ALL of these must hold:
- Its title clearly corresponds to the cited title — same subject, same
  scope. Sharing a few keywords is NOT enough.
- The citation's author surname appears in the candidate's authors OR
  in the candidate's title. Wikipedia articles are exempt (they have
  no authors).
- The candidate's year is within roughly 5 years of the cited year, or
  one side has no year.

If any of these fail for every candidate, return matched_index = null.
Spurious matches mislead listeners — null is the right answer when no
candidate is clearly the cited work.

Output ONE JSON object only — no prose, no code fences:
{"matched_index": <0-based index, or null>, "description": "<1-2 sentences, or empty>"}
"""


# ---------- Helpers ----------------------------------------------------------

def _extract_text(content_blocks: Any) -> str:
    return "".join(
        getattr(b, "text", "")
        for b in content_blocks
        if getattr(b, "type", None) == "text" and getattr(b, "text", "")
    )


def _run_tool(name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    fn = TOOL_DISPATCH.get(name)
    if fn is None:
        return {"error": f"unknown tool: {name}"}
    try:
        candidates = fn(tool_input)
    except Exception as exc:
        logger.warning("tool %s raised: %s", name, exc)
        return {"error": str(exc)}
    return {"candidates": candidates[:5]}


def _candidate_for_judge(c: dict[str, Any]) -> dict[str, Any]:
    """Trim a candidate to fields useful for matching + composition.
    Truncates the abstract to keep prompt tokens bounded."""
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


_JSON_RE = re.compile(r"\{[^{}]*\"matched_index\"[^{}]*\}", re.DOTALL)


def _parse_judge(text: str) -> tuple[int | None, str]:
    m = _JSON_RE.search(text)
    if not m:
        logger.warning("no judge JSON in: %r", text[:200])
        return None, ""
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        logger.warning("judge JSON decode failed (%s): %r", exc, m.group(0)[:200])
        return None, ""
    raw_idx = data.get("matched_index")
    idx: int | None
    if raw_idx is None:
        idx = None
    else:
        try:
            idx = int(raw_idx)
        except (TypeError, ValueError):
            idx = None
    return idx, str(data.get("description") or "").strip()


# ---------- Main entry point -------------------------------------------------

def assess_citation(
    raw_text: str,
    *,
    client: anthropic.Anthropic | None = None,
) -> ReadingListEntry:
    """Verify a single citation. Returns a ReadingListEntry — verified=True
    with rich metadata if Haiku picked a candidate, verified=False otherwise.
    Always uses exactly 2 Haiku calls (search + judge)."""
    if client is None:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    input_tokens = 0
    output_tokens = 0
    haiku_calls = 0

    def _accumulate(usage: Any) -> None:
        nonlocal input_tokens, output_tokens, haiku_calls
        haiku_calls += 1
        input_tokens += getattr(usage, "input_tokens", 0) or 0
        output_tokens += getattr(usage, "output_tokens", 0) or 0

    # ---- SEARCH TURN ----
    search_messages: list[MessageParam] = [{
        "role": "user",
        "content": (
            f"Citation:\n{raw_text}\n\n"
            "Fire your parallel searches now."
        ),
    }]
    search_msg = client.messages.create(
        model=AGENT_MODEL,
        max_tokens=1024,
        system=SEARCH_PROMPT,
        tools=TOOL_DEFS,
        messages=search_messages,
    )
    _accumulate(search_msg.usage)

    candidates: list[dict[str, Any]] = []
    if search_msg.stop_reason == "tool_use":
        for block in search_msg.content:
            if not isinstance(block, ToolUseBlock):
                continue
            tool_input = block.input if isinstance(block.input, dict) else {}
            result = _run_tool(block.name, tool_input)
            for c in result.get("candidates", []):
                candidates.append(c)

    # Deduplicate by URL — different queries often return the same hit
    seen_urls: set[str] = set()
    unique_candidates: list[dict[str, Any]] = []
    for c in candidates:
        url = c.get("url") or ""
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        unique_candidates.append(c)

    # No candidates at all → drop without spending the judge call
    if not unique_candidates:
        return ReadingListEntry(
            raw_text=raw_text, verified=False,
            haiku_calls=haiku_calls,
            input_tokens=input_tokens, output_tokens=output_tokens,
        )

    # ---- JUDGE TURN ----
    judge_input = "\n".join([
        f"Citation: {raw_text}",
        "",
        "Candidates:",
        json.dumps(
            [_candidate_for_judge(c) for c in unique_candidates],
            indent=2, default=str,
        ),
    ])
    judge_msg = client.messages.create(
        model=AGENT_MODEL,
        max_tokens=512,
        system=JUDGE_PROMPT,
        messages=[{"role": "user", "content": judge_input}],
    )
    _accumulate(judge_msg.usage)
    matched_index, description = _parse_judge(_extract_text(judge_msg.content))

    if matched_index is None or not (0 <= matched_index < len(unique_candidates)):
        return ReadingListEntry(
            raw_text=raw_text, verified=False,
            haiku_calls=haiku_calls,
            input_tokens=input_tokens, output_tokens=output_tokens,
        )

    chosen = unique_candidates[matched_index]
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
        haiku_calls=haiku_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
