"""LLM judge — does any candidate hit confirm a citation?

CONSERVATIVE BIAS. The judge defaults to "NO MATCH" when in doubt. The whole
point of the post-processor is to lift recall without compromising precision;
a fake-verified pastiche is worse than a missed real citation.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import anthropic

logger = logging.getLogger(__name__)

JUDGE_MODEL = "claude-haiku-4-5-20251001"

PROMPT_SYSTEM = """\
You verify scholarly citations against candidate search results. Be CONSERVATIVE:
only return a match when the candidate clearly confirms the citation. When in
doubt, say NO MATCH. A wrong "match" silently fakes a verified pastiche, which
is worse than a real citation we miss.

A match requires ALL of:
  1. Author surname appears in the candidate's authors (or the candidate is a
     legal case / Act / government publication where authors don't apply).
  2. The candidate title overlaps substantively with the citation's title —
     not just a single word in common. Subtitle differences are OK.
  3. If the citation gives a year, the candidate's year is within ±1, or the
     candidate is a clearly-the-same-work later edition.

Reply on ONE LINE in this exact format:
  MATCH <number>
or
  NO MATCH

The <number> is the candidate's index (1-based) from the list provided.
Do NOT add commentary.
"""


def judge(citation: str, candidates: list[dict[str, Any]],
          *, client: anthropic.Anthropic | None = None) -> dict[str, Any] | None:
    """Return the matching candidate dict, or None.

    `candidates` is the uniform-shape list from sources.*_search.
    """
    if not candidates:
        return None
    if client is None:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    lines = [f"Citation: {citation}", "", "Candidates:"]
    for i, c in enumerate(candidates, 1):
        authors_str = ", ".join((c.get("authors") or [])[:4])
        lines.append(
            f"  {i}. title={c.get('title','')!r}  "
            f"authors={authors_str}  year={c.get('year')}  source={c.get('source')}"
        )

    msg = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=64,
        system=PROMPT_SYSTEM,
        messages=[{"role": "user", "content": "\n".join(lines)}],
    )
    reply = "".join(
        getattr(b, "text", "") for b in msg.content if hasattr(b, "text")
    ).strip()

    if reply.startswith("MATCH "):
        try:
            idx = int(reply.split()[1]) - 1
            if 0 <= idx < len(candidates):
                return candidates[idx]
        except (IndexError, ValueError):
            pass
    return None
