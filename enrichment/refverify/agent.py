"""Citation verifier — OpenAlex + Wikipedia, Haiku for query massaging
and result composition only.

Flow per citation:
  1. Haiku formulates an initial query and parallel-calls
     search_openalex + search_wikipedia.
  2. A DETERMINISTIC match gate (enrichment.refverify.match) runs over
     the returned candidates. If anything passes, we skip ahead to
     composition.
  3. If nothing passed and we have budget left, Haiku gets one chance to
     reformulate the query and re-search.
  4. Composition: given the chosen candidate (or "no match"), Haiku writes
     a 1-2-sentence listener-friendly description grounded in the
     candidate's metadata. Verdict (verified yes/no) is the gate's result,
     never Haiku's opinion.

Output: ReadingListEntry — title, authors, year, type, publisher,
description, cite count, URL, audience tag, plus accounting fields.
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
    ToolResultBlockParam,
    ToolUnionParam,
    ToolUseBlock,
)

from .match import audience, best_match
from .sources import openalex_search, parse_citation, wikipedia_search

logger = logging.getLogger(__name__)

AGENT_MODEL = "claude-haiku-4-5-20251001"
HAIKU_INPUT_PER_MTOK = 1.00
HAIKU_OUTPUT_PER_MTOK = 5.00

# Search-turn budget (does NOT include the composition turn). 1 = single
# round of parallel calls; 2 = a chance to massage and retry.
MAX_SEARCH_TURNS = 2


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
    # Match diagnostics — useful for downstream auditing.
    title_jaccard: float | None = None
    year_delta: int | None = None
    # Accounting
    haiku_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def cost_usd(self) -> float:
        return (
            self.input_tokens * HAIKU_INPUT_PER_MTOK / 1_000_000
            + self.output_tokens * HAIKU_OUTPUT_PER_MTOK / 1_000_000
        )


# ---------- Tool schemas -----------------------------------------------------

TOOL_DEFS: list[ToolUnionParam] = [
    {
        "name": "search_openalex",
        "description": (
            "OpenAlex academic graph. Broad coverage: articles, books, "
            "chapters, theses, conference papers. Returns up to 5 "
            "candidates with title, authors, year, type, publisher, "
            "abstract, citation count, DOI/URL. Use for academic citations."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Free-text search query. Combine author surname + "
                        "key title words. If first attempt is empty, try "
                        "again with surname only or with a different title "
                        "fragment."
                    ),
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_wikipedia",
        "description": (
            "English Wikipedia article search with intro extracts. Use for "
            "Acts of Parliament, canonical works, historical events, "
            "well-known persons — anything likely to have its own article. "
            "Returns up to 5 articles with title, intro extract, and URL."
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


# ---------- System prompts ---------------------------------------------------

SEARCH_PROMPT = """\
You are searching for a real-world citation. Your job in this phase is to
formulate effective queries for two tools — OpenAlex (academic) and
Wikipedia (canonical works, Acts, historical events). You are NOT
deciding whether the citation is real; a deterministic check runs after
your search and decides.

GUIDANCE
- For academic citations: parallel-call search_openalex AND search_wikipedia
  on turn 1. OpenAlex catches articles, books, theses; Wikipedia catches
  canonical works that have their own article (rare but high-signal).
- For UK Acts of Parliament, named historical events, famous works:
  Wikipedia is the better starting point.
- A query like '"Author Title (Year)"' is usually too specific. Prefer
  unquoted "Author key-title-words". OpenAlex handles natural-language
  queries well.
- If turn 1 returned nothing useful and you have a second search turn,
  try: surname-only, title-fragment-only, or swap the source.

After your tool calls return, the system runs a deterministic match check
on the candidates and either accepts one (you'll be asked to compose the
final entry) or asks you to retry with a different query.
"""

COMPOSE_PROMPT = """\
You have one job: take a CANDIDATE returned by OpenAlex or Wikipedia and
write a 1-2 sentence description that helps a podcast listener decide
whether to read it. Use only what's in the candidate metadata (title,
authors, abstract, publisher, type). Do NOT invent.

If the candidate has an abstract, summarise it in plain language.
If it's a Wikipedia article, summarise the intro extract.
Avoid jargon, hedging, and meta-talk like "this work argues that…".

Output ONE JSON object — no prose, no code fences:
{"description": "<1-2 sentences>"}
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


def _candidate_for_model(c: dict[str, Any]) -> dict[str, Any]:
    """Trim a candidate dict to fields useful to the model — drop noisy
    fields, truncate the abstract."""
    abstract = c.get("abstract") or ""
    if len(abstract) > 800:
        abstract = abstract[:800] + "…"
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


_DESC_RE = re.compile(r'\{[^{}]*"description"[^{}]*\}', re.DOTALL)


def _parse_description(text: str) -> str:
    m = _DESC_RE.search(text)
    if not m:
        return ""
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return ""
    return str(data.get("description") or "").strip()


# ---------- Main entry point -------------------------------------------------

def assess_citation(
    raw_text: str,
    *,
    client: anthropic.Anthropic | None = None,
    max_search_turns: int = MAX_SEARCH_TURNS,
) -> ReadingListEntry:
    """Verify a single citation. Returns a ReadingListEntry — verified=True
    with rich metadata if the deterministic gate accepted a candidate;
    verified=False otherwise."""
    if client is None:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    parsed = parse_citation(raw_text)

    messages: list[MessageParam] = [{
        "role": "user",
        "content": (
            f"Citation to verify:\n\n{raw_text}\n\n"
            f"Parsed hint — author: {parsed.get('author')!r}, "
            f"title: {parsed.get('title')!r}, year: {parsed.get('year')!r}.\n\n"
            "Search for it using the tools."
        ),
    }]

    candidates: list[dict[str, Any]] = []
    chosen: dict[str, Any] | None = None
    chosen_features = None
    input_tokens = 0
    output_tokens = 0
    haiku_calls = 0

    def _accumulate(usage: Any) -> None:
        nonlocal input_tokens, output_tokens, haiku_calls
        haiku_calls += 1
        input_tokens += getattr(usage, "input_tokens", 0) or 0
        output_tokens += getattr(usage, "output_tokens", 0) or 0

    # Search turns (1 or 2)
    for turn in range(max_search_turns):
        msg = client.messages.create(
            model=AGENT_MODEL,
            max_tokens=1024,
            system=SEARCH_PROMPT,
            tools=TOOL_DEFS,
            messages=messages,
        )
        _accumulate(msg.usage)
        if msg.stop_reason != "tool_use":
            break

        tool_results: list[ToolResultBlockParam] = []
        for block in msg.content:
            if not isinstance(block, ToolUseBlock):
                continue
            tool_input = block.input if isinstance(block.input, dict) else {}
            result = _run_tool(block.name, tool_input)
            for c in result.get("candidates", []):
                candidates.append(c)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, default=str),
            })

        messages.append({"role": "assistant", "content": msg.content})
        messages.append({"role": "user", "content": tool_results})

        # Deterministic gate after each search round
        chosen, chosen_features = best_match(parsed, candidates)
        if chosen is not None:
            break

        # Otherwise prompt the model to reformulate (only if we have budget)
        if turn + 1 < max_search_turns:
            messages.append({
                "role": "user",
                "content": (
                    "No candidate passed the deterministic match gate. "
                    "Try ONE alternate query — e.g. surname only, a "
                    "different title fragment, or a different tool."
                ),
            })

    # No match: return verified=False, no composition turn, no extra cost.
    if chosen is None or chosen_features is None:
        return ReadingListEntry(
            raw_text=raw_text,
            verified=False,
            haiku_calls=haiku_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    # Composition turn (one Haiku call, no tools)
    cand_for_model = _candidate_for_model(chosen)
    compose_msg = client.messages.create(
        model=AGENT_MODEL,
        max_tokens=400,
        system=COMPOSE_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                f"Original citation: {raw_text}\n\n"
                f"Candidate:\n{json.dumps(cand_for_model, indent=2)}\n\n"
                "Compose the JSON description."
            ),
        }],
    )
    _accumulate(compose_msg.usage)
    description = _parse_description(_extract_text(compose_msg.content))

    return ReadingListEntry(
        raw_text=raw_text,
        verified=True,
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
        title_jaccard=chosen_features.title_jaccard,
        year_delta=chosen_features.year_delta,
        haiku_calls=haiku_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
