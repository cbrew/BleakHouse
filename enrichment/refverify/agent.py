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
    govinfo_search,
    legislation_gov_uk_search,
    openalex_search,
    semantic_scholar_search,
    wikipedia_search,
)
# NOTE: fatcat_search intentionally not imported — see TOOL_DEFS comment.

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
            "FAST (~1-2s). DOI registry. USE FOR: scholarly articles, books, "
            "chapters, conference papers. The single best first call for any "
            "academic citation. DO NOT USE FOR: Acts of Parliament (no DOI), "
            "legal cases, government reports, Wikipedia-style references, or "
            "items where the citation lacks a clear author + title."
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
        "name": "search_openalex",
        "description": (
            "FAST (~1-2s). OpenAlex is the broadest academic graph: covers "
            "DOIs, books, theses, preprints, including older works missed "
            "by CrossRef. USE IN PARALLEL with search_crossref on turn 1 "
            "for academic citations — both are FAST and cheap, and "
            "OpenAlex often catches what CrossRef misses (and vice versa). "
            "DO NOT USE FOR: Acts, legal cases, government reports."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "author": {"type": "string"},
                "title": {"type": "string", "description": "Title or substantive fragment"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "search_wikipedia",
        "description": (
            "FAST (~1-2s). English Wikipedia article search. USE FOR: Acts "
            "of Parliament (often have detailed articles), famous "
            "historical works, canonical persons, parliamentary reports, "
            "well-known events. STRONG signal when an Act or work has its "
            "own Wikipedia page. DO NOT USE FOR: ordinary academic "
            "articles (almost never have Wikipedia pages)."
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
        "name": "search_semantic_scholar",
        "description": (
            "MEDIUM (~2-4s, 1.5s/req throttle). Academic paper search with "
            "good humanities/CS coverage. USE FOR: academic articles where "
            "CrossRef + OpenAlex returned nothing useful. DO NOT USE FOR: "
            "pre-1900 works (poor coverage), Acts, legal cases, government "
            "reports, or non-scholarly material."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text query (author + title)"},
            },
            "required": ["query"],
        },
    },
    # NOTE: search_fatcat dropped — its elastic endpoint times out reliably
    # on every query and adds ~30s of dead time per citation. Re-enable here
    # and in TOOL_DISPATCH if it ever comes back to life.
    # {
    #     "name": "search_fatcat",
    #     "description": "...",
    #     "input_schema": {...},
    # },
    {
        "name": "search_cinii",
        "description": (
            "MEDIUM (~2-3s). Japan NII academic catalog. USE FOR: citations "
            "with Japanese authors (kanji/hiragana/katakana OR romanized "
            "Japanese surnames like Kondo, Yamada, Tanaka, Kobayashi) or "
            "Japanese-language scholarship. DO NOT USE FOR: anglophone "
            "citations — coverage is essentially zero outside Japan."
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
            "FAST (~1s). Direct legislation.gov.uk URL probe. USE ONLY for "
            "UK Acts of Parliament with a regnal-year citation that gives "
            "BOTH year AND chapter, e.g. '(45 & 46 Vict. c. 75)'. DO NOT USE "
            "for: Acts without a chapter number, US statutes, secondary "
            "sources, or anything that isn't a UK public general act."
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
            "MEDIUM (~2-4s, sometimes 5xx). USE ONLY for US legal opinions "
            "with case-name + reporter, e.g. 'Smith v. Jones, 123 U.S. 456 "
            "(1899)'. DO NOT USE FOR: UK cases (no coverage), academic "
            "articles, Acts of Parliament, government publications."
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
            "MEDIUM (~2-3s). USE ONLY for US federal government "
            "publications — congressional reports, hearings, bills, Federal "
            "Register, GAO reports, agency documents. DO NOT USE FOR: "
            "academic articles, books from commercial publishers, UK "
            "government material, anything pre-1900, or non-US sources."
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
            "SLOW (~5-10s). Web search filtered to faculty/academic domains "
            "(.edu, .ac.*, Project MUSE, Cambridge, JSTOR, archive.org). "
            "USE FOR: niche real academic works missed by CrossRef/S2 — this "
            "is the only tool that catches author CVs, department pages, "
            "and small-press / older works. CALL IT IN PARALLEL with "
            "search_semantic_scholar on turn 2 when search_crossref missed; "
            "the 3-turn cap means you cannot afford to try it sequentially. "
            "DO NOT USE FOR: Acts, legal cases, government documents."
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


def _tool_search_openalex(args: dict[str, Any]) -> list[dict[str, Any]]:
    return openalex_search(_as_raw(args.get("author"), args.get("title")))


def _tool_search_wikipedia(args: dict[str, Any]) -> list[dict[str, Any]]:
    return wikipedia_search(args["query"])


def _tool_search_semantic_scholar(args: dict[str, Any]) -> list[dict[str, Any]]:
    return semantic_scholar_search(args["query"])


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
    "search_openalex": _tool_search_openalex,
    "search_wikipedia": _tool_search_wikipedia,
    "search_semantic_scholar": _tool_search_semantic_scholar,
    # "search_fatcat": _tool_search_fatcat,  # disabled — see TOOL_DEFS note
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
- USE PARALLEL TOOL CALLS. Within a single turn you can emit multiple
  tool_use blocks at once and they run concurrently. This is almost always
  the right move on turn 2 when turn 1 missed — fire several alternates in
  parallel rather than sequentially.

CALL BUDGET (hard cap: 3 model turns per citation)
- Turn 1: parallel-call the cheap structured indexes that fit the citation
  TYPE. For an academic item: parallel-call search_crossref + search_openalex
  (both FAST, broad coverage; either may hit). For a UK Act: parallel-call
  lookup_uk_act + search_wikipedia. For a US case: search_courtlistener
  alone.
- Turn 2: if turn 1 missed, fire fallbacks IN PARALLEL — typically
  search_semantic_scholar + search_faculty_pages together. Add
  search_cinii in parallel if the author looks Japanese.
- Turn 3: forced finalise (no tools available). Output the JSON.

TOOL SPEED TIERS (parallel calls in the same turn only cost as much
wall-clock as the slowest one)
- FAST   (~1-2s):  search_crossref, search_openalex, search_wikipedia,
                   lookup_uk_act
- MEDIUM (~2-4s):  search_semantic_scholar, search_cinii,
                   search_courtlistener, search_govinfo
- SLOW   (~5-10s): search_faculty_pages

ROUTING SUMMARY (read each tool's own description for full do/don't lists)
- Academic article / book / chapter   -> turn 1: search_crossref +
  search_openalex in parallel. Turn 2 (on miss): search_semantic_scholar +
  search_faculty_pages in parallel.
- UK Act of Parliament                 -> search_wikipedia + lookup_uk_act
  in parallel (Wikipedia almost always has an article on a real Act,
  even when regnal-year parsing fails).
- US legal case ('Smith v. Jones, 123 U.S. 456') -> search_courtlistener.
- US federal / government publication  -> search_govinfo + search_wikipedia.
- Japanese-language / Japanese author  -> include search_cinii.

DO NOTs (wasted calls — never do these)
- DO NOT call search_govinfo for academic articles, UK material, or pre-
  1900 sources.
- DO NOT call search_courtlistener for UK cases, academic articles, or
  non-legal items.
- DO NOT call search_cinii for anglophone works without Japanese authors.
- DO NOT call lookup_uk_act unless the citation gives BOTH year AND
  chapter number.
- DO NOT call search_wikipedia for ordinary academic articles — almost
  none have Wikipedia pages.
- DO NOT call search_crossref / search_openalex / search_semantic_scholar
  for Acts, legal cases, or government reports — they have no DOIs.

MATCH STANDARD
A candidate confirms a citation when ALL hold:
  (a) author surname appears (or the work is a legal case / Act where
      authors don't apply);
  (b) candidate title overlaps substantively with the citation title — not
      just a single common word; subtitle differences are fine;
  (c) the year is within ±1, allowing for hardback/paperback gaps and
      reprints.

OUTPUT FORMAT
On your final turn (no tools), reply with ONE JSON object only — no prose,
no code fences:

{"odds_real_to_confab": <float>, "evidence_summary": "<1-2 sentences>", "primary_url": "<best URL or null>", "matched_source": "<tool name or null, e.g. search_crossref>"}

ODDS GUIDANCE
- 100.0  strong textual match (DOI agrees; author + title + year all check)
-  20.0  good evidence (multiple weaker sources agree on title/author,
                        OR a faculty page lists the title verbatim)
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
