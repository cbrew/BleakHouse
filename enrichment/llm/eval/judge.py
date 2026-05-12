"""LLM-as-judge eval pass.

Stage 2 Tier S of o3ir (BleakHouse-1aav) found that the
'set_overlap_with_Haiku' floor measures conformity, not quality —
even Haiku-against-itself only hits 0.851 because LLM stochasticity.
Open-weight candidates picking different (but possibly equally
reasonable) items score near zero against that floor.

This module replaces the conformity metric with an absolute-rubric
LLM-judge pass: given a candidate's listener-pick output, ask Haiku
4.5 to rate whether the picks are well-chosen for a literary
podcast listener (1-5 scale + justification).

The judge runs as a SECOND PASS over saved per-input results from
the runner — no re-payment for candidate generation. Judge cost is
constant across candidates (we judge each candidate's existing
output once).

Bias caveat: Haiku judging Haiku-picks introduces an obvious
favourable bias. User accepted this trade-off; the alternative is
hand-rating which is more reliable but slower. Note the bias when
reading results.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Callable

from enrichment.llm import GenerationRequest, GenerationResult, generate
from enrichment.llm.eval.scoring import (
    extract_tags_from_listener_pick_response,
)
from enrichment.llm.settings import register_task
from enrichment.llm.types import ModelSpec

logger = logging.getLogger(__name__)


_JUDGE_TASK_NAME = "listener_pick_judge"


_JUDGE_SYSTEM = """\
You are reviewing a curated reading list for a literary podcast.

A model was given a list of candidate references (books, articles,
Wikipedia entries) and asked to pick 3-8 that a general listener —
someone driving home after the episode — would actually pursue.
"General listener" means accessible (no specialist training needed),
findable in a library or bookshop, genuinely illuminating about the
novel.

Your job: rate the picks on a 1-5 scale.

5 = All picks are excellent for a general listener. Real books, accessible writing, varied perspectives, well-matched to the novel.
4 = Mostly good picks. Maybe one weaker or one that lists too much specialist material; the bulk would help a listener.
3 = Mixed — some great picks, some questionable (journal articles, niche specialist books, paraphrase-y titles).
2 = Mostly poor picks. Too many journal articles, dissertations, or items a listener can't access. Or picks that wouldn't help.
1 = All bad / wrong format / fewer than 3 picks / picks reference invalid tags.

Output ONE JSON object only — no prose, no code fences:

{{"rating": <1-5>, "justification": "<one sentence>"}}
"""


@dataclass(frozen=True)
class JudgeResult:
    """One judge rating."""

    input_id: str
    rating: int          # 1..5; -1 on judge failure
    justification: str
    candidate_tags: list[str]
    judge_raw_text: str


def _build_judge_user_message(
    *,
    novel_title: str,
    candidate_list_text: str,
    candidate_picks_tags: list[str],
) -> str:
    """Assemble the judge's user message: novel + full candidate
    list (so the judge can verify tag→entry mapping) + the model's
    picks."""
    picks_str = ", ".join(candidate_picks_tags) if candidate_picks_tags else "(none)"
    return (
        f"Novel: {novel_title}\n\n"
        f"## Full candidate list the model saw\n\n"
        f"{candidate_list_text}\n\n"
        f"## The model picked these tags\n\n"
        f"{picks_str}\n\n"
        f"Rate these picks 1-5 against the rubric in your system "
        f"message, considering only what a general listener would "
        f"find useful."
    )


def _parse_judge_response(text: str) -> tuple[int, str]:
    """Parse the judge's {rating, justification} JSON. Returns
    (-1, error_message) on parse failure."""
    m = re.search(r"\{[^{}]*\"rating\"[^{}]*\}", text, re.DOTALL)
    if m is None:
        return -1, f"no JSON object found in judge output: {text[:200]!r}"
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        return -1, f"judge JSON parse failed: {exc}"
    rating = obj.get("rating")
    justification = obj.get("justification") or ""
    if not isinstance(rating, int) or not (1 <= rating <= 5):
        return -1, f"judge rating out of range or non-int: {rating!r}"
    return rating, str(justification)


def judge_listener_pick(
    *,
    input_id: str,
    novel_title: str,
    candidate_list_text: str,
    candidate_output_text: str,
    generate_fn: Callable[[GenerationRequest], GenerationResult] = generate,
) -> JudgeResult:
    """Judge one candidate-output by re-running Haiku as an absolute
    rater.

    Extracts the candidate's tags from its raw output, builds the
    judge prompt, invokes generate() for the judge task, parses the
    rating.
    """
    candidate_tags = extract_tags_from_listener_pick_response(
        candidate_output_text,
    )

    # Ensure the judge task is bound to Haiku. Re-binding on every
    # call is cheap; the alternative (register once at import time)
    # surprises tests that monkeypatch settings.
    register_task(_JUDGE_TASK_NAME, ModelSpec(
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        hosting="anthropic",
    ))

    user_message = _build_judge_user_message(
        novel_title=novel_title,
        candidate_list_text=candidate_list_text,
        candidate_picks_tags=candidate_tags,
    )

    request = GenerationRequest(
        task=_JUDGE_TASK_NAME,
        system=_JUDGE_SYSTEM,
        user=user_message,
        max_tokens=256,
    )
    result = generate_fn(request)

    rating, justification = _parse_judge_response(result.text)

    return JudgeResult(
        input_id=input_id,
        rating=rating,
        justification=justification,
        candidate_tags=candidate_tags,
        judge_raw_text=result.text,
    )
