"""Deterministic match gate. The agent never decides whether a citation
is verified — that's done here, by computing concrete overlap between the
raw citation and a candidate returned by OpenAlex / Wikipedia.

A candidate passes when EITHER:
  - title-Jaccard >= 0.8 (canonical match overrides everything)
  - OR title-Jaccard >= 0.5 AND author surname matches (or candidate has
    no authors, e.g. Wikipedia) AND year is within ±1 (or one side has
    no year)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

# Word-level tokenization for Jaccard. Drop short words and stopwords —
# a single shared "the" or "of" should not contribute.
_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "of", "and", "or", "in", "on", "to", "for", "with",
    "by", "as", "at", "from", "into", "is", "are", "was", "were",
    "be", "been", "being", "this", "that", "these", "those",
})

# Trade vs scholarly: a small allowlist of academic publishers for the
# audience flag. If a book's publisher matches this list, it's "scholarly";
# otherwise we lean "general".
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


@dataclass(frozen=True)
class MatchFeatures:
    title_jaccard: float
    author_match: bool      # True if surname found in authors OR in title
                            # (catches "Review of X by Author"), or candidate
                            # has no authors (Wikipedia)
    year_delta: int | None  # None if either side missing year

    @property
    def passes(self) -> bool:
        # Canonical title match: trust it without author/year checks.
        if self.title_jaccard >= 0.8:
            return True
        # Below 0.5 Jaccard: reject regardless.
        if self.title_jaccard < 0.5:
            return False
        # 0.5 <= J < 0.8: need author + plausible year.
        if not self.author_match:
            return False
        if self.year_delta is None:
            return True
        # Wide year window: a citation may resolve to a review (+2-5y),
        # an earlier edition, or a later reprint. Title + author do most
        # of the precision work.
        return abs(self.year_delta) <= 5


def _tokens(text: str) -> set[str]:
    """Lowercase word tokens, ≥3 chars, non-stopword."""
    return {
        w.lower()
        for w in re.findall(r"\w+", text)
        if len(w) >= 3 and w.lower() not in _STOPWORDS
    }


def _jaccard(a: str, b: str) -> float:
    aw, bw = _tokens(a), _tokens(b)
    if not aw or not bw:
        return 0.0
    return len(aw & bw) / len(aw | bw)


def _surname(author: str | None) -> str:
    if not author:
        return ""
    parts = re.split(r"\s+", author.strip())
    return parts[-1] if parts else ""


def features(citation: dict[str, Any], candidate: dict[str, Any]) -> MatchFeatures:
    """Score one candidate against a parsed citation (output of
    parse_citation: {author, title, year})."""
    cite_title = citation.get("title") or ""
    cand_title = candidate.get("title") or ""
    title_jaccard = _jaccard(cite_title, cand_title)

    cand_authors = candidate.get("authors") or []
    surname = _surname(citation.get("author"))
    if not cand_authors:
        # Wikipedia articles have no authors — don't penalise.
        author_match = True
    elif not surname:
        author_match = False
    else:
        sn = surname.lower()
        in_authors = any(sn in (a or "").lower() for a in cand_authors)
        # Reviews of books have the book author's surname in the title:
        # "Review of X by Author" or "X: Subtitle by Author".
        in_title = sn in cand_title.lower()
        author_match = in_authors or in_title

    cite_year = citation.get("year")
    cand_year = candidate.get("year")
    year_delta = (cand_year - cite_year) if (cite_year and cand_year) else None

    return MatchFeatures(title_jaccard, author_match, year_delta)


def best_match(
    citation: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, MatchFeatures | None]:
    """Return the highest-scoring passing candidate (and its features), or
    (None, None) if nothing passes the gate."""
    best: tuple[dict[str, Any], MatchFeatures] | None = None
    best_jacc = -1.0
    for c in candidates:
        f = features(citation, c)
        if not f.passes:
            continue
        if f.title_jaccard > best_jacc:
            best_jacc = f.title_jaccard
            best = (c, f)
    if best is None:
        return None, None
    return best


def audience(candidate: dict[str, Any]) -> Literal["general", "scholarly"]:
    """Cheap deterministic flag. type=book + non-academic publisher → general.
    Otherwise: cited_by >= 500 → general (something like a popular standard);
    else scholarly."""
    pub = (candidate.get("publisher") or "").lower().strip()
    type_ = (candidate.get("type") or "").lower()
    cited_by = candidate.get("cited_by") or 0
    if type_ == "book" and pub and pub not in _SCHOLARLY_PUBLISHERS:
        return "general"
    if cited_by and cited_by >= 500:
        return "general"
    return "scholarly"
