"""Scholarly reference search tools — correct-by-construction.

Each search hit is registered in a per-interview `CitationRegistry` and
exposed to the model with a stable tag (`ref-7`). The model's structured
response cites tags only; post-interview is a dict lookup, not a fuzzy
re-verification. There is no second pass: a citation is real because it
came from a tool result.

Three tools:
  - search_openalex(query)              tagged academic candidates
  - search_wikipedia(query)             tagged Wikipedia article candidates
  - read_wikipedia_article(ref_tag)     drills into an article, extracts
                                        its bibliography items via Haiku,
                                        registers each as a tagged record

The audience flag (general/scholarly) is deterministic from publisher
and citation count.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import anthropic
import requests
from anthropic.types import ToolUnionParam
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)

_TIMEOUT = 15
_USER_AGENT = (
    "BleakHouseResearch/2.0 (academic research; "
    "https://github.com/cbrew/BleakHouse)"
)


# ---------------------------------------------------------------------------
# Citation record + registry
# ---------------------------------------------------------------------------


@dataclass
class CitationRecord:
    """One reference candidate registered during an interview.

    `tag` is a stable identifier the model uses to refer to this record.
    All other fields are populated from the originating API response or
    from a Wikipedia article's bibliography.
    """

    tag: str
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    type: str = ""                # OpenAlex type, or 'wikipedia_article', or 'wikipedia_further_reading'
    publisher: str | None = None
    description: str | None = None
    cited_by: int | None = None
    url: str = ""
    doi: str | None = None
    source: str = ""              # 'openalex' | 'wikipedia_article' | 'wikipedia_further_reading'
    parent_tag: str | None = None # for further_reading items: the article they came from
    audience: Literal["general", "scholarly"] = "scholarly"


class CitationRegistry:
    """Per-interview cache of citation records keyed by tag.

    Tags are minted as `ref-N` in registration order. Records are
    deduplicated by URL on registration: re-registering a record whose
    URL matches an existing one returns the existing tag instead of
    minting a new one.
    """

    def __init__(self) -> None:
        self._by_tag: dict[str, CitationRecord] = {}
        self._tag_by_url: dict[str, str] = {}
        self._next = 1

    def register(
        self,
        *,
        title: str,
        url: str,
        source: str,
        authors: list[str] | None = None,
        year: int | None = None,
        type: str = "",
        publisher: str | None = None,
        description: str | None = None,
        cited_by: int | None = None,
        doi: str | None = None,
        parent_tag: str | None = None,
    ) -> str:
        """Register a record, return its tag. Dedups by URL."""
        if url and url in self._tag_by_url:
            return self._tag_by_url[url]
        tag = f"ref-{self._next}"
        self._next += 1
        record = CitationRecord(
            tag=tag,
            title=title,
            authors=authors or [],
            year=year,
            type=type,
            publisher=publisher,
            description=description,
            cited_by=cited_by,
            url=url,
            doi=doi,
            source=source,
            parent_tag=parent_tag,
            audience=audience(
                {"type": type, "publisher": publisher, "cited_by": cited_by}
            ),
        )
        self._by_tag[tag] = record
        if url:
            self._tag_by_url[url] = tag
        return tag

    def get(self, tag: str) -> CitationRecord | None:
        return self._by_tag.get(tag)

    def all(self) -> list[CitationRecord]:
        return list(self._by_tag.values())

    def to_dicts(self) -> list[dict[str, Any]]:
        return [asdict(r) for r in self._by_tag.values()]


# ---------------------------------------------------------------------------
# Audience flag (deterministic; moved from refverify.match)
# ---------------------------------------------------------------------------


_SCHOLARLY_PUBLISHERS: frozenset[str] = frozenset({
    "cambridge university press", "oxford university press",
    "university of chicago press", "princeton university press",
    "harvard university press", "yale university press",
    "duke university press", "stanford university press",
    "mit press", "cornell university press",
    "johns hopkins university press", "columbia university press",
    "university of california press", "university of pennsylvania press",
    "university of minnesota press", "university of michigan press",
    "routledge", "palgrave macmillan", "wiley", "wiley-blackwell",
    "springer", "elsevier", "taylor & francis", "sage publications",
    "brill", "edinburgh university press",
})


def audience(candidate: dict[str, Any]) -> Literal["general", "scholarly"]:
    """type=book + non-academic publisher  -> general
    cited_by >= 500                        -> general (something canonical)
    otherwise                              -> scholarly"""
    pub = (candidate.get("publisher") or "").lower().strip()
    type_ = (candidate.get("type") or "").lower()
    cited_by = candidate.get("cited_by") or 0
    if type_ == "book" and pub and pub not in _SCHOLARLY_PUBLISHERS:
        return "general"
    if cited_by and cited_by >= 500:
        return "general"
    return "scholarly"


# ---------------------------------------------------------------------------
# Anthropic tool definitions
# ---------------------------------------------------------------------------


SEARCH_OPENALEX_TOOL: ToolUnionParam = {
    "name": "search_openalex",
    "description": (
        "Search OpenAlex for scholarly works (books, journal articles, "
        "chapters). Returns up to 3 candidates, each prefixed with a "
        "stable [ref-N] tag. Cite a candidate later by its tag — do not "
        "invent citation text."
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

SEARCH_WIKIPEDIA_TOOL: ToolUnionParam = {
    "name": "search_wikipedia",
    "description": (
        "Search Wikipedia for articles. Returns up to 3 candidate articles, "
        "each prefixed with a stable [ref-N] tag and a short snippet. "
        "Cite an article later by its tag. To access works listed in the "
        "article's bibliography, call read_wikipedia_article on its tag."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
        },
        "required": ["query"],
    },
}

READ_WIKIPEDIA_ARTICLE_TOOL: ToolUnionParam = {
    "name": "read_wikipedia_article",
    "description": (
        "Drill into a Wikipedia article that was previously surfaced by "
        "search_wikipedia (you must give its [ref-N] tag). Returns a "
        "longer extract of the article body and registers each item from "
        "the article's Bibliography / Further reading / References "
        "sections as a new tagged candidate citation. Use this when an "
        "article looks central to the discussion and you want to cite "
        "scholarly works it points to."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ref_tag": {
                "type": "string",
                "description": "Tag of a Wikipedia article (e.g. 'ref-3')",
            },
        },
        "required": ["ref_tag"],
    },
}

ALL_TOOLS: list[ToolUnionParam] = [
    SEARCH_OPENALEX_TOOL, SEARCH_WIKIPEDIA_TOOL, READ_WIKIPEDIA_ARTICLE_TOOL,
]


# ---------------------------------------------------------------------------
# OpenAlex
# ---------------------------------------------------------------------------


def _invert_abstract(inv: dict[str, list[int]] | None) -> str:
    """Reconstruct an abstract from OpenAlex's inverted index."""
    if not inv:
        return ""
    word_at: dict[int, str] = {}
    for word, positions in inv.items():
        for p in positions:
            word_at[p] = word
    return " ".join(word_at[i] for i in sorted(word_at) if i in word_at)


def _openalex_get(query: str, max_results: int) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"search": query, "per_page": max_results}
    api_key = os.environ.get("OPENALEX_API_KEY")
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
        return resp.json().get("results", [])
    except Exception as exc:
        logger.warning("OpenAlex search failed for %r: %s", query, exc)
        return []


def execute_search_openalex(
    query: str,
    registry: CitationRegistry,
    max_results: int = 3,
) -> str:
    """Search OpenAlex, register every hit in the registry, return text
    for the LLM that prefixes each line with the candidate's tag."""
    results = _openalex_get(query, max_results)
    if not results:
        return f"No scholarly works found for {query!r}."

    lines: list[str] = []
    for w in results:
        title = w.get("display_name") or "Unknown"
        authors = [
            (a.get("author") or {}).get("display_name", "")
            for a in (w.get("authorships") or [])[:5]
        ]
        authors = [a for a in authors if a]
        year = w.get("publication_year")
        cited = w.get("cited_by_count") or 0
        doi = w.get("doi") or None
        # url is the DOI link if available, else the OpenAlex work id
        if doi:
            url = doi if doi.startswith("http") else f"https://doi.org/{doi}"
        else:
            url = w.get("id") or ""
        host_venue = w.get("host_venue") or {}
        primary_loc = w.get("primary_location") or {}
        venue_source = primary_loc.get("source") or {}
        publisher = (
            host_venue.get("publisher")
            or venue_source.get("host_organization_name")
            or venue_source.get("publisher")
            or None
        )
        abstract = _invert_abstract(w.get("abstract_inverted_index")) or None
        type_ = w.get("type") or ""

        tag = registry.register(
            title=title,
            authors=authors,
            year=year,
            type=type_,
            publisher=publisher,
            description=abstract,
            cited_by=cited,
            url=url,
            doi=doi,
            source="openalex",
        )
        author_str = ", ".join(authors[:3]) or "—"
        lines.append(
            f"[{tag}] {author_str}. \"{title}\" ({year or '?'}). "
            f"Cited by {cited}."
        )
        if abstract:
            lines.append(f"  Abstract: {abstract[:400]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Wikipedia
# ---------------------------------------------------------------------------


def _wikipedia_search_pages(query: str, max_results: int) -> list[dict[str, Any]]:
    """Search Wikipedia and return article dicts (title, intro extract, url)."""
    try:
        resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "generator": "search",
                "gsrsearch": query[:300],
                "gsrlimit": max_results,
                "prop": "extracts|info",
                "exintro": "1",
                "explaintext": "1",
                "exchars": "800",
                "inprop": "url",
                "format": "json",
                "redirects": "1",
            },
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Wikipedia search failed for %r: %s", query, exc)
        return []
    pages = (resp.json().get("query") or {}).get("pages") or {}
    items = sorted(pages.values(), key=lambda p: p.get("index", 999))
    return items[:max_results]


def execute_search_wikipedia(
    query: str,
    registry: CitationRegistry,
    max_results: int = 3,
) -> str:
    pages = _wikipedia_search_pages(query, max_results)
    if not pages:
        return f"No Wikipedia articles found for {query!r}."

    lines: list[str] = []
    for p in pages:
        title = p.get("title") or "Unknown"
        extract = p.get("extract") or ""
        url = p.get("fullurl") or (
            f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
        )
        tag = registry.register(
            title=title,
            url=url,
            type="wikipedia_article",
            publisher="Wikipedia",
            description=extract or None,
            source="wikipedia_article",
        )
        lines.append(f"[{tag}] **{title}** — {url}")
        if extract:
            lines.append(f"  {extract[:500]}")
    return "\n".join(lines)


def wikipedia_full_extract(title: str) -> str:
    """Fetch the full plain-text body of a Wikipedia article (not just intro)."""
    if not title.strip():
        return ""
    try:
        resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "titles": title,
                "prop": "extracts",
                "explaintext": "1",
                "format": "json",
                "redirects": "1",
            },
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Wikipedia full extract failed for %r: %s", title, exc)
        return ""
    pages = (resp.json().get("query") or {}).get("pages") or {}
    for p in pages.values():
        if p.get("extract"):
            return p["extract"]
    return ""


_BIB_SECTION_RE = re.compile(
    r"^==\s*("
    r"Further reading|Bibliography|Selected works|"
    r"References|Sources|Works cited|Works|Selected publications"
    r")\s*==\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_SECTION_HEADER_RE = re.compile(r"^==\s*[^=]+\s*==\s*$", re.MULTILINE)


def _slice_wikipedia_for_haiku(
    full: str, intro_chars: int = 4000, bib_chars: int = 8000
) -> str:
    """Return intro + bibliography sections, capped, for compact prompts."""
    if len(full) <= intro_chars + bib_chars:
        return full
    intro = full[:intro_chars]
    bib_sections: list[str] = []
    for m in _BIB_SECTION_RE.finditer(full):
        start = m.start()
        next_hdr = _SECTION_HEADER_RE.search(full, m.end())
        end = next_hdr.start() if next_hdr else len(full)
        bib_sections.append(full[start:end])
    bib = "\n\n".join(bib_sections)[:bib_chars]
    if not bib:
        return intro
    return intro + "\n\n[…]\n\n" + bib


def _wikipedia_title_from_url(url: str) -> str:
    parsed = urlparse(url)
    if "wikipedia.org" not in parsed.netloc:
        return ""
    last = parsed.path.rstrip("/").split("/")[-1]
    return unquote(last).replace("_", " ")


_WIKI_ENRICH_PROMPT = """\
You have a Wikipedia article body. Extract up to 5 further-reading items
the article itself cites. These usually live in 'Further reading',
'Bibliography', 'References', 'Selected works', or similar sections.
Skip generic web links and Wikipedia-internal cross-references.

Output ONE JSON object only, no prose, no code fences:

{
  "further_reading": [
    {"title": "...", "author": "..." | null, "year": <int|null>, "publisher": "..." | null},
    ...
  ]
}

If there are no further-reading items, return an empty list.
"""

_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_enrich(text: str) -> list[dict[str, Any]]:
    """Parse Haiku's bibliography-extraction JSON. Returns list of items."""
    m = _OBJ_RE.search(text)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    raw = data.get("further_reading") or []
    items: list[dict[str, Any]] = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "").strip()
        if not title:
            continue
        items.append({
            "title": title,
            "author": (str(it["author"]).strip() if it.get("author") else None),
            "year": it.get("year") if isinstance(it.get("year"), int) else None,
            "publisher": (str(it["publisher"]).strip() if it.get("publisher") else None),
        })
    return items[:5]


_ENRICH_MODEL = "claude-haiku-4-5-20251001"


def execute_read_wikipedia_article(
    ref_tag: str,
    registry: CitationRegistry,
    client: anthropic.Anthropic,
) -> str:
    """Fetch an article's full body, extract its bibliography via Haiku,
    register each extracted item as a tagged record. Returns text for
    the LLM listing the new tags and a short body summary."""
    record = registry.get(ref_tag)
    if record is None:
        return f"No record for tag {ref_tag!r} — search Wikipedia first."
    if record.source != "wikipedia_article":
        return (
            f"Tag {ref_tag!r} is not a Wikipedia article (source="
            f"{record.source!r}). read_wikipedia_article is for Wikipedia hits only."
        )

    title = _wikipedia_title_from_url(record.url) or record.title
    full = wikipedia_full_extract(title)
    if not full:
        return f"Could not fetch full body for {title!r}."

    body_slice = _slice_wikipedia_for_haiku(full)
    try:
        msg = client.messages.create(
            model=_ENRICH_MODEL,
            max_tokens=800,
            system=_WIKI_ENRICH_PROMPT,
            messages=[{
                "role": "user",
                "content": (
                    f"Wikipedia article '{title}':\n\n{body_slice}"
                ),
            }],
        )
    except Exception as exc:
        logger.warning("Wikipedia enrich Haiku call failed for %r: %s",
                       title, exc)
        return f"Body fetched for {title!r}, but bibliography extraction failed: {exc}"

    text = "".join(
        getattr(b, "text", "")
        for b in msg.content
        if getattr(b, "type", None) == "text"
    )
    items = _parse_enrich(text)
    if not items:
        return (
            f"Article body fetched for {title!r}; no further-reading items "
            "found in its bibliography sections."
        )

    new_tags: list[str] = []
    for it in items:
        # Synthesise a stable URL: either an author-and-title-keyed string,
        # or fall back to the article URL (so dedup still works per-article).
        synth_url = (
            f"wiki-fr:{record.url}#{it['title'].lower().replace(' ', '_')}"
        )
        # Compose a description that names the source article.
        desc = f"Listed in the bibliography of the Wikipedia article on {title}."
        if it.get("publisher"):
            desc += f" Publisher: {it['publisher']}."
        # type='book' is a guess; further-reading items in Wikipedia tend to
        # be books, but it's not enforced. Keep the audience-flag conservative.
        tag = registry.register(
            title=it["title"],
            authors=[it["author"]] if it.get("author") else [],
            year=it.get("year"),
            type="wikipedia_further_reading",
            publisher=it.get("publisher"),
            description=desc,
            url=synth_url,
            source="wikipedia_further_reading",
            parent_tag=ref_tag,
        )
        new_tags.append(tag)

    lines = [f"Bibliography mined from {title!r}:"]
    for tag, it in zip(new_tags, items):
        author = it.get("author") or "—"
        year = it.get("year") or "—"
        lines.append(f"  [{tag}] {author}. {it['title']} ({year}).")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


def dispatch_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    registry: CitationRegistry,
    client: anthropic.Anthropic,
) -> str:
    """Execute a tool by name. Returns result text for the LLM."""
    if tool_name == "search_openalex":
        return execute_search_openalex(tool_input.get("query", ""), registry)
    if tool_name == "search_wikipedia":
        return execute_search_wikipedia(tool_input.get("query", ""), registry)
    if tool_name == "read_wikipedia_article":
        return execute_read_wikipedia_article(
            tool_input.get("ref_tag", ""), registry, client
        )
    return f"Unknown tool: {tool_name}"
