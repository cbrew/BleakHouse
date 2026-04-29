"""Scholarly reference search tools and verification for Phase 2.5a.

Provides Anthropic tool definitions for OpenAlex and Wikipedia search,
tool execution functions, and post-interview citation verification.
"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

import requests
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_TIMEOUT = 10
_USER_AGENT = "BleakHouseResearch/1.0 (academic research; https://github.com/cbrew/BleakHouse)"

# ---------------------------------------------------------------------------
# Anthropic tool definitions
# ---------------------------------------------------------------------------

SEARCH_OPENALEX_TOOL = {
    "name": "search_openalex",
    "description": (
        "Search OpenAlex for scholarly works (books, journal articles, chapters). "
        "Returns title, authors, year, and citation count. Use this to find or "
        "verify scholarly references relevant to the discussion."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query — author name, title keywords, or topic",
            },
        },
        "required": ["query"],
    },
}

SEARCH_WIKIPEDIA_TOOL = {
    "name": "search_wikipedia",
    "description": (
        "Search Wikipedia for background context on a topic, person, historical "
        "event, or concept. Returns article titles and snippets. Use this to "
        "verify facts or find context about people, events, or literary concepts."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query",
            },
        },
        "required": ["query"],
    },
}

ALL_TOOLS = [SEARCH_OPENALEX_TOOL, SEARCH_WIKIPEDIA_TOOL]


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------


def execute_search_openalex(query: str, max_results: int = 3) -> str:
    """Search OpenAlex for scholarly works. Returns formatted text for the LLM."""
    import os as _os
    params: dict = {"search": query, "per_page": max_results}
    api_key = _os.environ.get("OPENALEX_API_KEY")
    if api_key:
        params["api_key"] = api_key
    else:
        params["mailto"] = "brewc@cbrew.com"
    try:
        resp = requests.get(
            "https://api.openalex.org/works",
            params=params,
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return f"No scholarly works found for '{query}'."

        lines = []
        for work in results:
            title = work.get("display_name", "Unknown")
            year = work.get("publication_year", "?")
            cited = work.get("cited_by_count", 0)
            authors = [
                a.get("author", {}).get("display_name", "?")
                for a in work.get("authorships", [])[:3]
            ]
            author_str = ", ".join(authors)
            doi = work.get("doi") or ""
            lines.append(
                f"- {author_str}. \"{title}\" ({year}). "
                f"Cited by {cited}.{f' DOI: {doi}' if doi else ''}"
            )
            # Reconstruct abstract from inverted index if available
            abstract_ii = work.get("abstract_inverted_index")
            if abstract_ii and isinstance(abstract_ii, dict):
                word_positions: list[tuple[int, str]] = []
                for word, positions in abstract_ii.items():
                    for pos in positions:
                        word_positions.append((pos, word))
                word_positions.sort()
                abstract = " ".join(w for _, w in word_positions[:200])
                lines.append(f"  Abstract: {abstract}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning("OpenAlex search failed for '%s': %s", query, e)
        return f"Search failed: {e}"


def _fetch_wikipedia_extract(title: str, sentences: int = 8) -> str:
    """Fetch the opening sentences of a Wikipedia article by exact title."""
    try:
        resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "titles": title,
                "prop": "extracts",
                "exsentences": sentences,
                "explaintext": "1",
                "format": "json",
            },
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        pages = resp.json().get("query", {}).get("pages", {})
        for page in pages.values():
            extract = page.get("extract", "")
            if extract:
                return extract[:800]
    except Exception as e:
        logger.debug("Wikipedia extract failed for '%s': %s", title, e)
    return ""


def execute_search_wikipedia(query: str, max_results: int = 3) -> str:
    """Search Wikipedia for articles. Returns formatted text for the LLM."""
    try:
        resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": max_results,
                "format": "json",
            },
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("query", {}).get("search", [])
        if not results:
            return f"No Wikipedia articles found for '{query}'."

        lines = []
        for item in results:
            title = item.get("title", "Unknown")
            snippet = re.sub(r"<[^>]+>", "", item.get("snippet", ""))
            lines.append(f"- **{title}**: {snippet}")

            # Fetch the first ~500 words of the top result
            extract = _fetch_wikipedia_extract(title)
            if extract:
                lines.append(f"  Content: {extract}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning("Wikipedia search failed for '%s': %s", query, e)
        return f"Search failed: {e}"


def dispatch_tool(tool_name: str, tool_input: dict) -> str:
    """Execute a tool by name. Returns result text."""
    if tool_name == "search_openalex":
        return execute_search_openalex(tool_input.get("query", ""))
    elif tool_name == "search_wikipedia":
        return execute_search_wikipedia(tool_input.get("query", ""))
    else:
        return f"Unknown tool: {tool_name}"


# ---------------------------------------------------------------------------
# Verification models
# ---------------------------------------------------------------------------


class VerifiedReference(BaseModel):
    """A reference after verification against external APIs."""

    raw_text: str
    expert_name: str = ""
    segment_name: str = ""
    verified: bool = False
    verification_source: str = "unverified"  # touchstone/openalex/wikipedia/unverified
    openalex_title: str = ""
    openalex_authors: list[str] = Field(default_factory=list)
    openalex_year: int | None = None
    openalex_doi: str = ""
    openalex_cited_by: int = 0


class ReadingList(BaseModel):
    """Aggregated reading list for an episode."""

    verified: list[VerifiedReference] = Field(default_factory=list)
    unverified: list[VerifiedReference] = Field(default_factory=list)
    total_proposed: int = 0
    total_verified: int = 0
    verification_rate: float = 0.0


# ---------------------------------------------------------------------------
# Verification logic
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Normalize a reference string for comparison."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    return " ".join(text.split())


def _title_similarity(a: str, b: str) -> float:
    """Fuzzy title match ratio (0.0 to 1.0)."""
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _verify_via_openalex(raw_text: str) -> VerifiedReference | None:
    """Try to verify a reference via OpenAlex search."""
    import os as _os
    params: dict = {"search": raw_text, "per_page": 3}
    api_key = _os.environ.get("OPENALEX_API_KEY")
    if api_key:
        params["api_key"] = api_key
    else:
        params["mailto"] = "brewc@cbrew.com"
    try:
        resp = requests.get(
            "https://api.openalex.org/works",
            params=params,
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except Exception as e:
        logger.warning("OpenAlex verification failed for '%s': %s", raw_text, e)
        return None

    for work in results:
        title = work.get("display_name", "")
        if _title_similarity(raw_text, title) > 0.5:
            authors = [
                a.get("author", {}).get("display_name", "")
                for a in work.get("authorships", [])[:5]
            ]
            return VerifiedReference(
                raw_text=raw_text,
                verified=True,
                verification_source="openalex",
                openalex_title=title,
                openalex_authors=authors,
                openalex_year=work.get("publication_year"),
                openalex_doi=work.get("doi") or "",
                openalex_cited_by=work.get("cited_by_count") or 0,
            )
    return None


def _verify_via_wikipedia(raw_text: str) -> VerifiedReference | None:
    """Try to verify a reference via Wikipedia search."""
    try:
        resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": raw_text,
                "srlimit": 3,
                "format": "json",
            },
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        results = resp.json().get("query", {}).get("search", [])
    except Exception as e:
        logger.warning("Wikipedia verification failed for '%s': %s", raw_text, e)
        return None

    for item in results:
        title = item.get("title", "")
        if _title_similarity(raw_text, title) > 0.4:
            return VerifiedReference(
                raw_text=raw_text,
                verified=True,
                verification_source="wikipedia",
            )
    return None


def verify_references(
    proposed: list[dict],
    touchstone_works: list[str],
) -> ReadingList:
    """Verify proposed references against OpenAlex and Wikipedia.

    Args:
        proposed: list of {"raw_text": str, "expert_name": str, "segment_name": str}
        touchstone_works: list of canonical works that are auto-verified

    Returns:
        ReadingList with verified and unverified references.
    """
    touchstone_normalized = {_normalize(t) for t in touchstone_works}
    seen: set[str] = set()
    verified_list: list[VerifiedReference] = []
    unverified_list: list[VerifiedReference] = []

    for ref in proposed:
        raw = ref["raw_text"]
        key = _normalize(raw)
        if key in seen or not key.strip():
            continue
        seen.add(key)

        vr = VerifiedReference(
            raw_text=raw,
            expert_name=ref.get("expert_name", ""),
            segment_name=ref.get("segment_name", ""),
        )

        # 1. Touchstone match
        if any(_title_similarity(key, t) > 0.7 for t in touchstone_normalized):
            vr.verified = True
            vr.verification_source = "touchstone"
            verified_list.append(vr)
            logger.info("  Verified (touchstone): %s", raw)
            continue

        # 2. OpenAlex
        oa_result = _verify_via_openalex(raw)
        if oa_result:
            oa_result.expert_name = vr.expert_name
            oa_result.segment_name = vr.segment_name
            verified_list.append(oa_result)
            logger.info("  Verified (openalex): %s → %s", raw, oa_result.openalex_title)
            continue

        # 3. Wikipedia
        wp_result = _verify_via_wikipedia(raw)
        if wp_result:
            wp_result.expert_name = vr.expert_name
            wp_result.segment_name = vr.segment_name
            verified_list.append(wp_result)
            logger.info("  Verified (wikipedia): %s", raw)
            continue

        # 4. Unverified
        unverified_list.append(vr)
        logger.info("  Unverified: %s", raw)

    total = len(verified_list) + len(unverified_list)
    return ReadingList(
        verified=verified_list,
        unverified=unverified_list,
        total_proposed=total,
        total_verified=len(verified_list),
        verification_rate=len(verified_list) / total if total > 0 else 0.0,
    )


# ---------------------------------------------------------------------------
# Winnowing: select listener-friendly recommendations
# ---------------------------------------------------------------------------

class WinnowedReadingList(BaseModel):
    """Reading list after winnowing to listener-friendly recommendations."""

    recommended: list[str] = Field(
        description="3-5 works a radio listener could realistically find and read"
    )
    full_verified: list[VerifiedReference] = Field(default_factory=list)
    full_unverified: list[VerifiedReference] = Field(default_factory=list)
    total_before_winnowing: int = 0


_WINNOW_SYSTEM = """\
You are a radio producer preparing the reading list for a literary \
discussion podcast about **{novel_title}** by **{novel_author}**.

Your experts proposed these references during pre-interviews.  Your job \
is to select 3–5 that a normal listener — someone driving home who \
enjoyed the discussion — would actually seek out.

Criteria:
- Available in a public library or bookshop (not journal articles, \
  not Acts of Parliament, not archival documents, not dissertations)
- Readable by a general audience (not specialist academic monographs \
  unless they are famously readable)
- Genuinely illuminating about the novel under discussion
- Diverse: not all by the same author or on the same narrow topic

Return ONLY the selected works, one per line, in "Author, Title (Year)" \
format.  No commentary.  If fewer than 3 works qualify, return what you have."""


def winnow_reading_list(
    client: object,
    reading_list: ReadingList,
    novel_title: str,
    novel_author: str,
    model: str = "claude-haiku-4-5-20251001",
) -> WinnowedReadingList:
    """Winnow verified references to 3-5 listener-friendly recommendations."""
    if not reading_list.verified:
        return WinnowedReadingList(
            recommended=[],
            full_verified=reading_list.verified,
            full_unverified=reading_list.unverified,
            total_before_winnowing=reading_list.total_proposed,
        )

    # Deduplicate verified references by normalized title
    seen: set[str] = set()
    unique_refs: list[str] = []
    for ref in reading_list.verified:
        key = _normalize(ref.raw_text)
        if key not in seen:
            seen.add(key)
            unique_refs.append(ref.raw_text)

    system = _WINNOW_SYSTEM.format(
        novel_title=novel_title,
        novel_author=novel_author,
    )
    user = "References proposed by experts:\n\n" + "\n".join(
        f"- {ref}" for ref in unique_refs
    )

    response = client.messages.create(
        model=model,
        max_tokens=512,
        system=system,
        messages=[{"role": "user", "content": user}],
    )

    # Parse the response: one work per line
    text = response.content[0].text if response.content else ""
    recommended = [
        line.lstrip("- ").strip()
        for line in text.strip().split("\n")
        if line.strip() and not line.startswith("#")
    ]

    logger.info(
        "  Winnowed %d unique → %d recommended",
        len(unique_refs), len(recommended),
    )

    return WinnowedReadingList(
        recommended=recommended,
        full_verified=reading_list.verified,
        full_unverified=reading_list.unverified,
        total_before_winnowing=reading_list.total_proposed,
    )
