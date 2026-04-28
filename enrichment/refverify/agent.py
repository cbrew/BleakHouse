"""Haiku-driven citation assessor with sources packaged as tools.

Replaces the older fixed-chain verifier (`verify.py` + `judge.py`). Instead
of a hardcoded routing of citation→sources→judge, the model itself decides
which tools to call. Output is a calibrated odds ratio: how much more
likely the citation is real than confabulated, given the evidence gathered.

Tools wrap the source functions in `sources.py` and `faculty.py`. Haiku can
call any tool with structured inputs of its choosing, may call several in
one turn or across turns, and may revise its query if results are weak.

Bias is set in the system prompt: lean toward "confabulated" when in doubt.
A fake-verified pastiche is worse than a missed real citation.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

import anthropic
from anthropic.types import (
    MessageParam,
    ToolResultBlockParam,
    ToolUnionParam,
    ToolUseBlock,
)

from . import cache as _cache
from .faculty import faculty_search
from .sources import (
    cinii_search,
    courtlistener_search,
    crossref_search,
    fatcat_search,
    govinfo_search,
    legislation_gov_uk_search,
    semantic_scholar_search,
)

logger = logging.getLogger(__name__)

AGENT_MODEL = "claude-haiku-4-5-20251001"

# Hard cap on model calls per citation. Tool use is multi-turn by protocol
# (model -> tool_use -> tool_result -> model), but a tight cap keeps cost
# bounded. Typical flow: turn 1 emits 1–3 tool_use blocks, turn 2 finalises
# the JSON. Turn 3 leaves room for one revision when the first round
# returned nothing useful.
MAX_HAIKU_CALLS = 3

DEFAULT_PROMOTE_THRESHOLD = 5.0  # odds_real_to_confab needed to count as verified


# ---------- Result type ------------------------------------------------------

# Haiku 4.5 pricing as of 2026-04 ($/MTok). Update when pricing changes.
HAIKU_INPUT_PER_MTOK = 1.00
HAIKU_OUTPUT_PER_MTOK = 5.00


@dataclass(frozen=True)
class Assessment:
    """Haiku's final judgement of a citation."""
    odds_real_to_confab: float
    evidence_summary: str
    primary_url: str | None
    matched_source: str | None
    tools_used: list[str] = field(default_factory=list)
    raw_response: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    haiku_calls: int = 0
    cache_hits: int = 0

    @property
    def verified(self) -> bool:
        return self.odds_real_to_confab >= DEFAULT_PROMOTE_THRESHOLD

    @property
    def cost_usd(self) -> float:
        return (
            self.input_tokens * HAIKU_INPUT_PER_MTOK / 1_000_000
            + self.output_tokens * HAIKU_OUTPUT_PER_MTOK / 1_000_000
        )


# ---------- Tool schemas (sent to Haiku) -------------------------------------

TOOL_DEFS: list[ToolUnionParam] = [
    {
        "name": "search_crossref",
        "description": (
            "Search CrossRef (DOI registry) for a scholarly work — articles, "
            "books, chapters, conference papers. Returns up to 5 candidates "
            "with title, authors, year, DOI."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "author": {"type": "string", "description": "Author surname or full name"},
                "title": {"type": "string", "description": "Title or substantive fragment"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "search_semantic_scholar",
        "description": (
            "Search Semantic Scholar for academic papers. Good coverage of "
            "humanities and CS. Returns up to 5 candidates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text query (author + title)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_fatcat",
        "description": (
            "Search Internet Archive's Fatcat / Scholar catalog. Useful for "
            "older or harder-to-find works the major indexes miss."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_cinii",
        "description": (
            "Search CiNii (Japan NII academic catalog). Use for Japanese-language "
            "scholarship or romanized Japanese authors who may be missing from "
            "Anglocentric databases."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "lookup_uk_act",
        "description": (
            "Verify a UK Act of Parliament by year + chapter on legislation.gov.uk. "
            "Use only when the citation gives a regnal-year-style reference like "
            "(33 & 34 Vict. c. 23). Year and chapter only — no title."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "year": {"type": "integer"},
                "chapter": {"type": "integer"},
            },
            "required": ["year", "chapter"],
        },
    },
    {
        "name": "search_courtlistener",
        "description": (
            "Search CourtListener for US federal/state legal cases. Use for US "
            "case-law citations like 'Smith v. Jones, 123 U.S. 456 (1899)'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Case name or partial citation"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_govinfo",
        "description": (
            "Search GovInfo for US federal government publications — congressional "
            "reports, hearings, Federal Register, GAO. Not for academic articles."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_faculty_pages",
        "description": (
            "Web-search faculty / personal academic pages and bibliographic sites "
            "(.edu, .ac.*, Project MUSE, Cambridge, JSTOR, archive.org) via Brave "
            "Search. Returns hits where the title appears in the result snippet — "
            "useful for niche real works that don't show up in CrossRef/S2."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "author": {"type": "string"},
                "title": {"type": "string", "description": "Title or substantive fragment"},
            },
            "required": ["author", "title"],
        },
    },
]


# ---------- Tool dispatch ----------------------------------------------------

def _as_raw(*parts: str | None) -> str:
    """Glue structured args into the 'Author, Title (Year)' shape that the
    underlying source functions parse internally."""
    return ", ".join(p for p in parts if p)


def _tool_search_crossref(args: dict[str, Any]) -> list[dict[str, Any]]:
    return crossref_search(_as_raw(args.get("author"), args.get("title")))


def _tool_search_semantic_scholar(args: dict[str, Any]) -> list[dict[str, Any]]:
    return semantic_scholar_search(args["query"])


def _tool_search_fatcat(args: dict[str, Any]) -> list[dict[str, Any]]:
    return fatcat_search(args["query"])


def _tool_search_cinii(args: dict[str, Any]) -> list[dict[str, Any]]:
    return cinii_search(args["query"])


def _tool_lookup_uk_act(args: dict[str, Any]) -> list[dict[str, Any]]:
    raw = f"{args['year']} (c. {args['chapter']})"
    return legislation_gov_uk_search(raw)


def _tool_search_courtlistener(args: dict[str, Any]) -> list[dict[str, Any]]:
    return courtlistener_search(args["query"])


def _tool_search_govinfo(args: dict[str, Any]) -> list[dict[str, Any]]:
    return govinfo_search(args["query"])


def _tool_search_faculty_pages(args: dict[str, Any]) -> list[dict[str, Any]]:
    return faculty_search(_as_raw(args["author"], args["title"]))


TOOL_DISPATCH: dict[str, Any] = {
    "search_crossref": _tool_search_crossref,
    "search_semantic_scholar": _tool_search_semantic_scholar,
    "search_fatcat": _tool_search_fatcat,
    "search_cinii": _tool_search_cinii,
    "lookup_uk_act": _tool_lookup_uk_act,
    "search_courtlistener": _tool_search_courtlistener,
    "search_govinfo": _tool_search_govinfo,
    "search_faculty_pages": _tool_search_faculty_pages,
}


# ---------- System prompt ----------------------------------------------------

SYSTEM_PROMPT = """\
You verify scholarly citations. Many of these were generated by an LLM and
could be confabulated (made up). Use the search tools to gather evidence and
produce a calibrated odds ratio of "real" vs "confabulated".

PRINCIPLES
- BE CONSERVATIVE. We'd rather miss a real citation than fake-verify a
  pastiche. When in doubt, lean toward confabulated.
- Match tools to the citation TYPE. Don't search GovInfo for an academic
  article. Don't search CrossRef for an Act of Parliament. Use
  search_faculty_pages for niche real works that the major indexes miss.
- A real citation usually shows: (a) the author surname appears in the
  candidate authors (or the work is a legal case / Act where authors don't
  apply); (b) the candidate title overlaps substantively with the citation
  title (not just one word in common; subtitle differences are fine);
  (c) the year is within ±1, allowing for hardback/paperback gaps and
  reprints.
- Try multiple tools or query variants before giving up. If CrossRef misses,
  try Semantic Scholar, Fatcat, or faculty_pages. Surnames-only or
  title-fragment queries can find what full-citation queries miss.

OUTPUT FORMAT
When you have enough evidence, stop calling tools and reply with ONE JSON
object — nothing else, no prose, no code fences:

{"odds_real_to_confab": <float>, "evidence_summary": "<1-2 sentences>", "primary_url": "<best URL or null>", "matched_source": "<source name or null>"}

ODDS GUIDANCE
- 100.0  strong textual match (DOI agrees; author + title + year all check)
-  20.0  good evidence (multiple weaker sources agree on title/author)
-   5.0  some evidence with caveats (year off, partial title match)
-   1.0  even — could be real or confabulated
-   0.2  searched but found nothing convincing
-   0.05 clearly confabulated (specific searches turned up no plausible match)

Don't quote these guidelines. Output only the JSON object on your final turn.
"""


# ---------- Agent loop -------------------------------------------------------

def _extract_text(content_blocks: Any) -> str:
    out = []
    for b in content_blocks:
        if getattr(b, "type", None) == "text":
            t = getattr(b, "text", "")
            if t:
                out.append(t)
    return "".join(out)


def _run_tool(name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
    fn = TOOL_DISPATCH.get(name)
    if fn is None:
        return {"error": f"unknown tool: {name}"}
    cached = _cache.get(name, tool_input)
    if cached is not None:
        return {"candidates": cached, "cached": True}
    try:
        candidates = fn(tool_input)
    except Exception as exc:
        logger.warning("tool %s raised: %s", name, exc)
        # Don't cache failures — transient errors should retry next call.
        return {"error": str(exc)}
    top = candidates[:5]
    _cache.put(name, tool_input, top)
    return {"candidates": top}


_JSON_OBJ_RE = re.compile(
    r"\{[^{}]*\"odds_real_to_confab\"[^{}]*\}", re.DOTALL,
)


def _parse_assessment(
    text: str,
    tools_used: list[str],
    *,
    input_tokens: int,
    output_tokens: int,
    haiku_calls: int,
    cache_hits: int,
) -> Assessment:
    metrics: dict[str, Any] = dict(
        tools_used=tools_used, raw_response=text,
        input_tokens=input_tokens, output_tokens=output_tokens,
        haiku_calls=haiku_calls, cache_hits=cache_hits,
    )
    m = _JSON_OBJ_RE.search(text)
    if m is None:
        logger.warning("no JSON assessment found in: %r", text[:200])
        return Assessment(
            odds_real_to_confab=1.0, evidence_summary="parse_failed",
            primary_url=None, matched_source=None, **metrics,
        )
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        logger.warning("JSON decode failed (%s): %r", exc, m.group(0)[:200])
        return Assessment(
            odds_real_to_confab=1.0, evidence_summary="json_decode_failed",
            primary_url=None, matched_source=None, **metrics,
        )
    return Assessment(
        odds_real_to_confab=float(data.get("odds_real_to_confab", 1.0)),
        evidence_summary=str(data.get("evidence_summary") or ""),
        primary_url=data.get("primary_url") or None,
        matched_source=data.get("matched_source") or None,
        **metrics,
    )


def assess_citation(
    raw_text: str,
    *,
    client: anthropic.Anthropic | None = None,
    max_haiku_calls: int = MAX_HAIKU_CALLS,
) -> Assessment:
    """Hand the citation to Haiku with the source tools available; return
    Haiku's final odds ratio + summary.

    Caps total Haiku calls at `max_haiku_calls` (default 3). On the final
    permitted call, force the model to stop calling tools by switching
    `tool_choice` to disabling tools and asking explicitly for the JSON.
    """
    if client is None:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    messages: list[MessageParam] = [{
        "role": "user",
        "content": (
            f"Citation to verify:\n\n{raw_text}\n\n"
            "Use the tools to gather evidence, then produce the final JSON."
        ),
    }]
    tools_used: list[str] = []
    final_text = ""
    input_tokens = 0
    output_tokens = 0
    haiku_calls = 0
    cache_hits = 0

    def _accumulate(usage: Any) -> None:
        nonlocal input_tokens, output_tokens, haiku_calls
        haiku_calls += 1
        input_tokens += getattr(usage, "input_tokens", 0) or 0
        output_tokens += getattr(usage, "output_tokens", 0) or 0

    for call_idx in range(max_haiku_calls):
        is_last_call = call_idx == max_haiku_calls - 1
        if is_last_call:
            # On the final call, force termination: drop tools and ask
            # explicitly for the JSON given evidence so far.
            messages.append({
                "role": "user",
                "content": "Final answer required now: output the JSON assessment based on evidence gathered.",
            })
            msg = client.messages.create(
                model=AGENT_MODEL,
                max_tokens=512,
                system=SYSTEM_PROMPT,
                messages=messages,
            )
            _accumulate(msg.usage)
            final_text = _extract_text(msg.content)
            break

        msg = client.messages.create(
            model=AGENT_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFS,
            messages=messages,
        )
        _accumulate(msg.usage)
        if msg.stop_reason in ("end_turn", "stop_sequence"):
            final_text = _extract_text(msg.content)
            break
        if msg.stop_reason != "tool_use":
            final_text = _extract_text(msg.content)
            break

        tool_results: list[ToolResultBlockParam] = []
        for block in msg.content:
            if not isinstance(block, ToolUseBlock):
                continue
            tools_used.append(block.name)
            tool_input = block.input if isinstance(block.input, dict) else {}
            result = _run_tool(block.name, tool_input)
            if result.get("cached"):
                cache_hits += 1
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, default=str),
            })

        messages.append({"role": "assistant", "content": msg.content})
        messages.append({"role": "user", "content": tool_results})

    return _parse_assessment(
        final_text, tools_used,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        haiku_calls=haiku_calls,
        cache_hits=cache_hits,
    )
