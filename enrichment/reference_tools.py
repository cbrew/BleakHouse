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
                                        every cite-template from the
                                        canonical Parsoid HTML via
                                        mwparserfromhtml, then runs each
                                        through the verification cascade
                                        from enrichment.reference_verify
                                        before registering it

The audience flag (general/scholarly) is deterministic from publisher
and citation count.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import urllib.parse
from urllib.parse import unquote, urlparse

import anthropic
import requests
from anthropic.types import ToolUnionParam

from enrichment.timing import Recorder, time_model, time_tool

# time_model is unused after BleakHouse-hgws (Haiku extraction retired);
# keep the import for any future model timing within this module.
_ = time_model

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

    Resolution status (added BleakHouse-hgws): for citations that pass
    through the verification cascade, `resolution_status` is either
    'resolved' (a verified URL landed in `url`) or 'unresolved' (the
    cascade ran but couldn't find a verifiable URL — the textual
    metadata is still real, just no working link). `attempted` lists
    the cascade strategies that ran HTTP calls. None means the record
    didn't go through verification (e.g., legacy OpenAlex search hits).
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
    isbn: str | None = None       # normalised ISBN-10/13; populated for cite-book templates (BleakHouse-2qs0)
    source: str = ""              # 'openalex' | 'wikipedia_article' | 'wikipedia_further_reading'
    parent_tag: str | None = None # for further_reading items: the article they came from
    audience: Literal["general", "scholarly"] = "scholarly"
    resolution_status: str | None = None  # 'resolved' | 'unresolved' | None (not verified)
    resolution_source: str | None = None  # which cascade strategy resolved it (or None)
    attempted: list[str] = field(default_factory=list)
    resolution_reason: str | None = None  # 'no_match' when unresolved
    head_verified: bool | None = None  # whether the winning URL passed HEAD; None for unresolved or pre-2qs0 records
    raw_text: str = ""            # original cite-template text or pre-resolve URL — for unresolved-comment rendering


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
        isbn: str | None = None,
        parent_tag: str | None = None,
        resolution_status: str | None = None,
        resolution_source: str | None = None,
        attempted: list[str] | None = None,
        resolution_reason: str | None = None,
        head_verified: bool | None = None,
        raw_text: str = "",
    ) -> str:
        """Register a record, return its tag. Dedups by URL (non-empty
        only; unresolved records with url='' each get their own tag)."""
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
            isbn=isbn,
            source=source,
            parent_tag=parent_tag,
            audience=audience(
                {"type": type, "publisher": publisher, "cited_by": cited_by}
            ),
            resolution_status=resolution_status,
            resolution_source=resolution_source,
            attempted=attempted or [],
            resolution_reason=resolution_reason,
            head_verified=head_verified,
            raw_text=raw_text,
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


def _openalex_get(
    query: str, max_results: int, recorder: Recorder | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"search": query, "per_page": max_results}
    api_key = os.environ.get("OPENALEX_API_KEY")
    if api_key:
        params["api_key"] = api_key
    else:
        params["mailto"] = "brewc@cbrew.com"
    with time_tool(recorder, "http_openalex_search", query):
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
    recorder: Recorder | None = None,
) -> str:
    """Search OpenAlex, register every hit in the registry, return text
    for the LLM that prefixes each line with the candidate's tag."""
    results = _openalex_get(query, max_results, recorder)
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


def _wikipedia_search_pages(
    query: str, max_results: int, recorder: Recorder | None = None,
) -> list[dict[str, Any]]:
    """Search Wikipedia and return article dicts (title, intro extract, url)."""
    with time_tool(recorder, "http_wikipedia_search", query):
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
    recorder: Recorder | None = None,
) -> str:
    pages = _wikipedia_search_pages(query, max_results, recorder)
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


def _wikipedia_title_from_url(url: str) -> str:
    parsed = urlparse(url)
    if "wikipedia.org" not in parsed.netloc:
        return ""
    last = parsed.path.rstrip("/").split("/")[-1]
    return unquote(last).replace("_", " ")


# ---------------------------------------------------------------------------
# Wikipedia HTML fetch + cite-template extraction (BleakHouse-hgws)
# ---------------------------------------------------------------------------
#
# The pre-hgws code fetched plain text via the Action API and asked
# Haiku to re-discover citation structure from prose. That conflated
# extraction (mechanical, deterministic) with research-grade
# inference (expensive, lossy) and synthesised non-clickable
# wiki-fr: URLs.
#
# The new path:
#   1. Fetch canonical Parsoid HTML from the REST API
#      (/api/rest_v1/page/html/<title>). Citation templates are
#      rendered with data-mw attributes preserving the original
#      parameters.
#   2. Parse with mwparserfromhtml. Walk all cite-templates
#      ({{cite book}}, {{cite journal}}, {{cite news}},
#      {{citation}}, etc.) in the article. We deliberately do NOT
#      scope to Further-reading/Bibliography sections — the
#      Holdsworth example ('Charles Dickens as a Legal Historian')
#      is an inline citation in Bleak House but a real scholarly
#      reference with a working archive.org URL. Section-scoping
#      would have missed it.
#   3. Each cite-template yields a normalised candidate (title,
#      authors, year, publisher, isbn, doi, url, raw text). The
#      verification cascade then HEAD-checks any URL/DOI/ISBN and
#      registers the record with resolution_status='resolved' or
#      'unresolved'.


def _fetch_wikipedia_html(
    title: str, recorder: Recorder | None = None,
) -> str:
    """Fetch the canonical Parsoid HTML of a Wikipedia article.

    Uses the REST API endpoint /api/rest_v1/page/html/<title>, which
    returns rendered HTML with stable data-mw attributes that
    mwparserfromhtml is built to parse. Returns '' on any failure.
    """
    if not title.strip():
        return ""
    encoded = urllib.parse.quote(title.replace(" ", "_"), safe="")
    url = f"https://en.wikipedia.org/api/rest_v1/page/html/{encoded}"
    with time_tool(recorder, "http_wikipedia_html", title):
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": _USER_AGENT},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            logger.warning(
                "Wikipedia HTML fetch failed for %r: %s", title, exc,
            )
            return ""


_CITE_TARGETS: frozenset[str] = frozenset({
    "cite book", "cite journal", "cite news", "cite web",
    "cite encyclopedia", "cite thesis", "cite report", "cite magazine",
    "citation",
})

_WIKITEXT_LINK_RE = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]")
_WIKITEXT_EXTLINK_RE = re.compile(r"\[[^\s\]]+\s+([^\]]+)\]")
_WIKITEXT_BOLD_RE = re.compile(r"'''([^']+)'''")
_WIKITEXT_ITALIC_RE = re.compile(r"''([^']+)''")


def _strip_wikitext(s: str) -> str:
    """Strip basic wikitext markup from a cite-template parameter value."""
    if not s:
        return ""
    s = _WIKITEXT_LINK_RE.sub(r"\1", s)
    s = _WIKITEXT_EXTLINK_RE.sub(r"\1", s)
    s = _WIKITEXT_BOLD_RE.sub(r"\1", s)
    s = _WIKITEXT_ITALIC_RE.sub(r"\1", s)
    return s.strip()


def _param(params: dict[str, Any], key: str) -> str:
    """Read a cite-template parameter value, stripping wikitext markup.
    Returns '' if absent or non-string."""
    v = params.get(key)
    if isinstance(v, dict):
        v = v.get("wt", "")
    if not isinstance(v, str):
        return ""
    return _strip_wikitext(v)


def _extract_authors(params: dict[str, Any]) -> list[str]:
    """Pull authors from a cite-template's parameters.

    Handles the three conventions:
      - author=Name or authors=Name1; Name2
      - last=Foo, first=Bar (single author)
      - last1=Foo, first1=Bar, last2=Baz, first2=Qux (numbered)
    Deduplicates while preserving order.
    """
    out: list[str] = []

    single = _param(params, "author")
    if single:
        out.append(single)

    multi = _param(params, "authors")
    if multi:
        for part in re.split(r"\s*(?:;| and )\s*", multi):
            part = part.strip()
            if part:
                out.append(part)

    # last/first compound. Try un-numbered first, then 1..N.
    last = _param(params, "last")
    first = _param(params, "first")
    if last or first:
        name = " ".join(p for p in (first, last) if p)
        if name:
            out.append(name)
    i = 1
    while True:
        ln = _param(params, f"last{i}")
        fn = _param(params, f"first{i}")
        if not ln and not fn:
            break
        name = " ".join(p for p in (fn, ln) if p)
        if name:
            out.append(name)
        i += 1
        if i > 30:  # sanity cap
            break

    seen: set[str] = set()
    result: list[str] = []
    for a in out:
        if a and a not in seen:
            seen.add(a)
            result.append(a)
    return result


def _extract_year(s: str) -> int | None:
    """Extract a 4-digit year from a cite-template date/year value.

    Matches 1500-2039 with a leading word boundary; uses a negative
    digit-lookahead instead of a trailing word boundary so trailing
    letters ('1850s') still let the year match.
    """
    if not s:
        return None
    m = re.search(r"\b(1[5-9]\d\d|20[0-3]\d)(?!\d)", s)
    return int(m.group(1)) if m else None


def _normalize_isbn(s: str) -> str:
    """Strip hyphens, spaces, dots; keep digits and X. Returns the
    canonical 10- or 13-digit ISBN, or '' if not a recognisable form."""
    if not s:
        return ""
    digits = re.sub(r"[^\dXx]", "", s).upper()
    return digits if len(digits) in (10, 13) else ""


@dataclass(frozen=True)
class _CiteCandidate:
    """A single cite-template extracted from a Wikipedia article."""
    title: str
    authors: list[str]
    year: int | None
    publisher: str
    url: str           # explicit URL from |url=, post-wikitext-strip
    doi: str
    isbn: str
    cite_kind: str     # e.g. 'cite book', 'cite journal'
    raw_text: str      # for the unresolved-comment rendering


def _extract_cite_templates(html: str) -> list[_CiteCandidate]:
    """Walk every cite-template in a Wikipedia HTML page and return
    normalised candidates. No section-scoping — see module docstring."""
    if not html:
        return []
    # Lazy import: mwparserfromhtml pulls in beautifulsoup4 + a parser;
    # the rest of reference_tools doesn't need it.
    from mwparserfromhtml import Article

    art = Article(html)
    templates = art.wikistew.get_templates()
    out: list[_CiteCandidate] = []
    for _tid, t in templates.items():
        for part in t.get("parts", []):
            if not isinstance(part, dict):
                continue
            tpl = part.get("template")
            if not isinstance(tpl, dict):
                continue
            target = tpl.get("target", {})
            kind = (target.get("wt") or "").strip().lower()
            if kind not in _CITE_TARGETS:
                continue
            params = tpl.get("params", {}) or {}
            if not isinstance(params, dict):
                continue
            title = _param(params, "title") or _param(params, "chapter")
            if not title:
                continue
            year = (
                _extract_year(_param(params, "year"))
                or _extract_year(_param(params, "date"))
                or _extract_year(_param(params, "orig-year"))
            )
            doi = _param(params, "doi")
            isbn = _normalize_isbn(_param(params, "isbn"))
            url = _param(params, "url")
            # If the URL is itself wikitext-link-ish (rare), it would
            # have been collapsed by _strip_wikitext already.
            out.append(_CiteCandidate(
                title=title,
                authors=_extract_authors(params),
                year=year,
                publisher=_param(params, "publisher"),
                url=url,
                doi=doi,
                isbn=isbn,
                cite_kind=kind,
                raw_text=_render_cite_raw(kind, params),
            ))
    return out


def _render_cite_raw(kind: str, params: dict[str, Any]) -> str:
    """Reassemble a compact human-readable form of a cite-template,
    suitable for the raw_text field of unresolved records (so the
    HTML comment in ticket 7cgk's renderer can include the full
    structured form)."""
    bits = [f"{{{{{kind}"]
    for k, v in params.items():
        wt = ""
        if isinstance(v, dict):
            wt = (v.get("wt") or "").strip().replace("\n", " ")
        elif isinstance(v, str):
            wt = v.strip().replace("\n", " ")
        if wt:
            bits.append(f"|{k}={wt[:200]}")
    bits.append("}}")
    return " ".join(bits)


def execute_read_wikipedia_article(
    ref_tag: str,
    registry: CitationRegistry,
    recorder: Recorder | None = None,
    verifier: "Any | None" = None,
) -> str:
    """Fetch an article's Parsoid HTML, extract every cite-template,
    verify each via the reference_verify cascade, and register each
    as a tagged record (resolved or unresolved).

    The previous version asked Haiku to re-discover citation structure
    from rendered prose and minted synthetic 'wiki-fr:' URLs that
    weren't navigable. This version reads structured citation fields
    directly from the rendered HTML's data-mw attributes — no LLM
    call, no synthetic URLs, every recorded URL HEAD-verified.

    `verifier` is injected for tests; production uses the module-level
    shared verifier from enrichment.reference_verify.
    """
    record = registry.get(ref_tag)
    if record is None:
        return f"No record for tag {ref_tag!r} — search Wikipedia first."
    if record.source != "wikipedia_article":
        return (
            f"Tag {ref_tag!r} is not a Wikipedia article (source="
            f"{record.source!r}). read_wikipedia_article is for Wikipedia hits only."
        )

    title = _wikipedia_title_from_url(record.url) or record.title
    html = _fetch_wikipedia_html(title, recorder)
    if not html:
        return f"Could not fetch HTML for {title!r}."

    candidates = _extract_cite_templates(html)

    # Lazy import + default verifier. `verifier` is duck-typed —
    # anything with a `.resolve(CandidateReference) -> ResolverResult`
    # is accepted, so tests can pass a stand-in.
    from enrichment.reference_verify import CandidateReference, resolve
    resolve_fn = resolve if verifier is None else verifier.resolve

    new_tags: list[str] = []
    for cand in candidates:
        # Pass identifiers (doi, isbn, url) explicitly to the cascade.
        # `source_trusted=True` reflects that this candidate comes from
        # a Wikipedia cite template — see CLAUDE.md policy on Wikipedia-
        # sourced DOIs/ISBNs being authoritative (BleakHouse-2qs0).
        ref = CandidateReference(
            title=cand.title,
            authors=tuple(cand.authors),
            year=cand.year,
            publisher=cand.publisher or None,
            raw_url=cand.url,
            doi=cand.doi,
            isbn=cand.isbn,
            source_trusted=True,
        )
        result = resolve_fn(ref)

        if result.resolved:
            tag = registry.register(
                title=cand.title,
                authors=cand.authors,
                year=cand.year,
                type=cand.cite_kind,
                publisher=cand.publisher or None,
                description=(
                    f"Cited in the Wikipedia article on {title}."
                ),
                url=result.url or "",
                doi=cand.doi or None,
                isbn=cand.isbn or None,
                source="wikipedia_further_reading",
                parent_tag=ref_tag,
                resolution_status="resolved",
                resolution_source=result.source,
                attempted=list(result.attempted),
                head_verified=result.head_verified,
                raw_text=cand.raw_text,
            )
        else:
            tag = registry.register(
                title=cand.title,
                authors=cand.authors,
                year=cand.year,
                type=cand.cite_kind,
                publisher=cand.publisher or None,
                description=(
                    f"Cited in the Wikipedia article on {title}; "
                    f"no resolvable URL found."
                ),
                url="",
                doi=cand.doi or None,
                isbn=cand.isbn or None,
                source="wikipedia_further_reading",
                parent_tag=ref_tag,
                resolution_status="unresolved",
                resolution_source=None,
                attempted=list(result.attempted),
                resolution_reason=result.reason,
                raw_text=cand.raw_text,
            )
        new_tags.append(tag)

    # LLM-facing summary: the article body (plaintext) + each
    # newly-tagged candidate on its own line. Only resolved candidates
    # are encouraged for citation; unresolved ones still get a tag so
    # the registry is the single source of truth, but the prose marks
    # them clearly.
    try:
        from mwparserfromhtml import Article as _MWArticle
        # get_plaintext yields paragraph-sized chunks
        plaintext = "\n".join(str(p) for p in _MWArticle(html).get_plaintext())
    except Exception:
        plaintext = ""

    lines = [
        f"=== Wikipedia article: {title} ({ref_tag}) ===",
        "",
        plaintext,
        "",
    ]
    if new_tags:
        lines.append(
            f"=== Citations mined from {title!r} "
            f"({len(new_tags)} total) ==="
        )
        for tag, cand in zip(new_tags, candidates):
            rec = registry.get(tag)
            if rec is None:
                continue
            author = ", ".join(cand.authors) if cand.authors else "—"
            year_s = str(cand.year) if cand.year else "—"
            status_marker = (
                "" if rec.resolution_status == "resolved"
                else " [unresolved — no verified URL]"
            )
            lines.append(
                f"  [{tag}] {author}. {cand.title} ({year_s}).{status_marker}"
            )
    else:
        lines.append("(No cite-templates found in this article.)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


def dispatch_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    registry: CitationRegistry,
    client: anthropic.Anthropic,
    recorder: Recorder | None = None,
) -> str:
    """Execute a tool by name. Returns result text for the LLM.

    Timing is fine-grained at the HTTP/model layer (not at this
    dispatch layer) so durations by `kind` sum without overlap:
      - http_openalex_search / http_wikipedia_search / http_wikipedia_full
        record the request latency
      - the Haiku enrichment call inside read_wikipedia_article is its
        own model event
    """
    if tool_name == "search_openalex":
        return execute_search_openalex(
            tool_input.get("query", ""), registry, recorder=recorder,
        )
    if tool_name == "search_wikipedia":
        return execute_search_wikipedia(
            tool_input.get("query", ""), registry, recorder=recorder,
        )
    if tool_name == "read_wikipedia_article":
        # `client` is no longer used by read_wikipedia_article (the
        # Haiku extraction was retired in BleakHouse-hgws; the new
        # path reads structured cite-template fields from the
        # rendered HTML via mwparserfromhtml).
        _ = client
        return execute_read_wikipedia_article(
            tool_input.get("ref_tag", ""), registry, recorder,
        )
    return f"Unknown tool: {tool_name}"
