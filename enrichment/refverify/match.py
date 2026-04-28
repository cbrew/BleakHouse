"""Deterministic helpers about candidates that don't require LLM
judgement: the audience flag (general / scholarly) reads off type,
publisher, and citation count."""
from __future__ import annotations

from typing import Any, Literal

# Trade vs scholarly: a small allowlist of academic publishers. If a
# book's publisher matches, it's "scholarly"; otherwise (and especially
# for trade-press books) we lean "general".
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
