"""Chain orchestrator: run sources in order, judge each, return first match."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import anthropic

from .judge import judge
from .sources import select_sources

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VerifyResult:
    verified: bool
    source: str | None
    url: str | None
    matched_candidate: dict[str, Any] | None


def verify_citation(
    raw_text: str,
    *,
    sources: list[Callable[[str], list[dict[str, Any]]]] | None = None,
    client: anthropic.Anthropic | None = None,
) -> VerifyResult:
    """Run each source in turn. First confirmed match wins.

    By default the chain is chosen by select_sources(raw_text) so we route
    each citation only to plausible sources. Pass an explicit `sources` list
    to override (mostly useful in tests).
    """
    if sources is None:
        sources = select_sources(raw_text)
    for src in sources:
        try:
            candidates = src(raw_text)
        except Exception as exc:
            logger.warning("source %s raised: %s", src.__name__, exc)
            continue
        if not candidates:
            continue
        match = judge(raw_text, candidates, client=client)
        if match is not None:
            return VerifyResult(
                verified=True,
                source=match["source"],
                url=match.get("url"),
                matched_candidate=match,
            )
    return VerifyResult(verified=False, source=None, url=None, matched_candidate=None)
