"""Run Stage 2 Tier M-Haiku slice of o3ir: passage_enrichment benchmark.

Compares 3 candidates on a fixture sampled from real chapter data
(data/novels/<novel>/passages_enriched.json):
- Anthropic Haiku 4.5 (current default, baseline)
- meta-llama/Llama-3.3-70B-Instruct-Turbo on DeepInfra
- Qwen/Qwen2.5-72B-Instruct on DeepInfra

Fixture builder samples 3 chapters in the 15-50 paragraph range
(big enough to be realistic, small enough to keep cost/complexity
manageable). Each fixture input reconstructs the exact
passage_enrichment prompt enrichment/submit_passages_enriched.py
sends.

Metrics:
- schema_validity (gate): ChapterEnrichmentResult.model_validate_json
  succeeds, AND paragraph count matches the input.
- literal_field_agreement: fraction of Literal-typed enrichment
  fields (narrator, plot_function, quotability, accessibility,
  prov_* fields) that match the baseline value per paragraph.
  Structural signal, not LLM-judged.

The Haiku-as-judge content-fidelity rating is a separate pass
(scripts/run_eval_passage_enrichment_judge.py — added if needed
after this run's results).

Run:
    uv run python scripts/run_eval_passage_enrichment.py
    uv run python scripts/run_eval_passage_enrichment.py --n 3 --seed 42
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from enrichment.llm import GenerationRequest, generate, settings  # noqa: E402
from enrichment.llm.eval.storage import save_results  # noqa: E402
from enrichment.llm.types import ModelSpec  # noqa: E402
from enrichment.novel_prompts import build_enrichment_prompt  # noqa: E402
from enrichment.schemas import (  # noqa: E402
    ChapterEnrichmentResult,
    ParagraphEnrichment,
)
from enrichment.submit_passages_enriched import format_chapter_text  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("eval-passage-enrichment")

REPO_DATA = REPO_ROOT / "data"
DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"

# Per-candidate metadata.
#
# call_shape:
#   "per_chapter"   — one request emits all paragraph enrichments for the
#                     chapter in a single ChapterEnrichmentResult. Plays
#                     to Haiku 4.5's long-context + long-structured-output
#                     strength.
#   "per_paragraph" — one request per paragraph; the chapter text sits
#                     inside the (cached) system block so it's seen by
#                     the model but billed at cache-read rates from the
#                     2nd paragraph onward. Output is a single
#                     ParagraphEnrichment. Plays to smaller open-weight
#                     models which fail on long structured-JSON output
#                     but handle short focused calls fine.
#
# Pick per candidate, not per task. The eval measures each candidate
# under the shape it's strongest in.
@dataclass(frozen=True)
class Candidate:
    spec: ModelSpec
    call_shape: str  # "per_chapter" | "per_paragraph"


CANDIDATES: dict[str, Candidate] = {
    "haiku": Candidate(
        spec=ModelSpec(
            provider="anthropic",
            model="claude-haiku-4-5-20251001",
            hosting="anthropic",
        ),
        call_shape="per_chapter",
    ),
    # v5 open-weight lineup — small-active-parameter MoE models for
    # fast per-call latency on the per_paragraph shape.
    #
    # Dropped from earlier drafts (2026-05-12 probe evidence):
    # - Qwen3-235B-A22B-Instruct-2507: 84s/call latency, 47% schema valid
    # - Qwen2.5-72B-Instruct: superseded by Qwen 3.x catalogue
    # - GLM-4.7-Flash: DeepInfra ignores `thinking={"type":"disabled"}`;
    #   the model emits JSON to reasoning_content instead of content.
    #   Adding it would require seam plumbing for a reasoning_content
    #   fallback. Worth revisiting if Tier-1 results justify the effort.
    # - Qwen3.6-35B-A3B: needs extra_body={"chat_template_kwargs":
    #   {"enable_thinking": False}} which the seam can't pass today.
    #   Qwen3-Next-80B-A3B-Instruct gets us the same architecture
    #   (3B active MoE) without the special-case flag.
    "qwen3_next_80b": Candidate(
        spec=ModelSpec(
            provider="openai_compatible",
            # Qwen 3-Next 80B-A3B Instruct: explicit -Instruct variant,
            # 80B total / 3B active MoE. Apache 2.0. 262k context.
            # Probe (2026-05-12): 3.1s/call, schema valid out of the
            # box, no thinking flag needed. DeepInfra $0.09/$1.10.
            model="Qwen/Qwen3-Next-80B-A3B-Instruct",
            hosting="deepinfra",
            base_url=DEEPINFRA_BASE_URL,
        ),
        call_shape="per_paragraph",
    ),
    "gemma4_26b_a4b": Candidate(
        spec=ModelSpec(
            provider="openai_compatible",
            # Google Gemma 4 small-MoE: 26B total / 4B active.
            # $0.07/$0.34, 256k context. v5 n=1 result (2026-05-12):
            # collapsed to 53% schema validity at chapter scale (vs
            # 100% on single-paragraph probe), 344s wall time.
            # Effectively unviable — kept for repeatability only.
            model="google/gemma-4-26B-A4B-it",
            hosting="deepinfra",
            base_url=DEEPINFRA_BASE_URL,
        ),
        call_shape="per_paragraph",
    ),
    "deepseek_v4_flash": Candidate(
        spec=ModelSpec(
            provider="openai_compatible",
            # DeepSeek-V4-Flash: 284B total / 13B active MoE, MIT
            # license, 1M context. $0.14/$0.28 with cache $0.028.
            # v5 probe + eyeball (2026-05-12): schema valid out of box,
            # no character hallucination, sensible theme selection,
            # 7.9s probe latency. DeepInfra ships authoritative
            # `usage.estimated_cost`.
            model="deepseek-ai/DeepSeek-V4-Flash",
            hosting="deepinfra",
            base_url=DEEPINFRA_BASE_URL,
        ),
        call_shape="per_paragraph",
    ),
    # Non-open-weight cross-check. OpenAI gpt-4o-mini is the
    # cheapest first-party model with reliable json_schema strict
    # mode (~$0.15/$0.60 per 1M). Tells us how the open-weight
    # candidates compare against a known-good cheap closed model.
    "gpt4o_mini": Candidate(
        spec=ModelSpec(
            provider="openai_compatible",
            model="gpt-4o-mini",
            hosting="openai",
            base_url=None,  # SDK default points at OpenAI
        ),
        call_shape="per_paragraph",
    ),
    # Llama 3.3-70B (both Turbo and non-Turbo) removed from candidate
    # list: structured-output probes (scripts/debug_structured_output.py)
    # showed both variants markdown-wrap pseudo-JSON ("Here is the
    # `ParagraphEnrichment` object...") regardless of strict-flag.
    # DeepInfra's response_format does not enforce schema for these
    # Llama variants. Off-list for this schema; revisit if hosting
    # changes (e.g. Together, vLLM-with-guided_json).
}

# Literal-typed enrichment fields we measure agreement on. These have
# defined value sets, so disagreement is meaningful (a real
# classification difference, not phrasing variation).
LITERAL_FIELDS = [
    "narrator", "plot_function", "quotability", "accessibility",
    "prov_character_development", "prov_plot_advancement",
    "prov_thematic_depth", "prov_social_critique",
    "prov_humor_entertainment", "prov_atmosphere_setting",
    "prov_narrative_technique",
]


# Per-list-field caps applied at request shaping time. Pydantic does
# NOT enforce these (the schema is intentionally liberal so we can
# store whatever the model emits, including over-cap lists). Each
# provider applies them in the way it can:
#   - openai_compatible providers inject maxItems → vLLM-backed
#     decoders enforce at sample time (prevents loop pathology where
#     a model emits the same Literal value 100+ times).
#   - AnthropicProvider injects the caps into descriptions as
#     "Maximum N items." (Anthropic rejects maxItems outright).
# Values follow the 2026-05-13 user guidance: 2-4 typical / 8 rich
# for content lists; 4 for emotional registers; 4 for speakers.
LIST_FIELD_CAPS: dict[str, int] = {
    "characters_present": 8,
    "characters_speaking": 4,
    "emotional_register": 4,
    "themes": 8,
}


@dataclass
class ChapterFixture:
    """A single fixture input — one chapter."""

    chapter_id: str
    novel: str
    chapter_title: str
    passages: list[dict] = field(default_factory=list)
    baseline_enrichments: list[dict] = field(default_factory=list)


def find_small_chapters(
    *, min_paragraphs: int, max_paragraphs: int,
) -> list[ChapterFixture]:
    """Walk data/novels/<n>/passages_enriched.json and yield fixtures
    where a chapter's paragraph count is in the [min, max) range.

    The baseline enrichments come from the existing enriched data —
    that's the Haiku output we're comparing against.
    """
    out: list[ChapterFixture] = []
    novels_dir = REPO_DATA / "novels"
    for novel_dir in sorted(novels_dir.iterdir()):
        if not novel_dir.is_dir():
            continue
        enriched_path = novel_dir / "passages_enriched.json"
        if not enriched_path.exists():
            continue
        try:
            passages = json.loads(enriched_path.read_text())
        except Exception:
            continue
        by_chapter: dict[str, list[dict]] = defaultdict(list)
        for p in passages:
            by_chapter[p["chapter_id"]].append(p)
        for chapter_id, chapter_passages in sorted(by_chapter.items()):
            chapter_passages.sort(key=lambda p: p["paragraph_index"])
            n = len(chapter_passages)
            if not (min_paragraphs <= n < max_paragraphs):
                continue
            if not all(p.get("enrichment") for p in chapter_passages):
                continue  # need full baseline coverage
            out.append(ChapterFixture(
                chapter_id=chapter_id,
                novel=novel_dir.name,
                chapter_title=chapter_passages[0].get("chapter_title", ""),
                passages=chapter_passages,
                baseline_enrichments=[
                    {
                        "paragraph_index": p["paragraph_index"],
                        "enrichment": p["enrichment"],
                    }
                    for p in chapter_passages
                ],
            ))
    return out


def build_user_message(fixture: ChapterFixture) -> str:
    formatted = format_chapter_text(fixture.passages)
    return f"Chapter: {fixture.chapter_id} - {fixture.chapter_title}\n\n{formatted}"


def parse_candidate_output(text: str) -> dict[int, dict] | None:
    """Parse the candidate's text → {paragraph_index: enrichment_dict}.

    Returns None if the response doesn't parse against the
    ChapterEnrichmentResult schema.
    """
    if not text or not text.strip():
        return None
    try:
        result = ChapterEnrichmentResult.model_validate_json(text)
    except Exception as exc:
        log.debug("schema validation failed: %s", exc)
        return None
    return {
        e.paragraph_index: e.enrichment.model_dump() for e in result.enrichments
    }


def score_one_chapter(
    *,
    candidate_text: str,
    baseline_enrichments: list[dict],
    n_paragraphs_expected: int,
) -> dict[str, Any]:
    """Score a candidate's output for one chapter against the baseline.

    Returns:
        schema_valid: 0.0/1.0
        n_paragraphs_returned: int
        paragraph_coverage: 0..1 (fraction of expected paragraphs the
            candidate covered)
        literal_agreement_per_field: dict {field: 0..1}
        literal_agreement_mean: 0..1 (mean across all Literal fields)
    """
    candidate = parse_candidate_output(candidate_text)
    if candidate is None:
        return {
            "schema_valid": 0.0,
            "n_paragraphs_returned": 0,
            "paragraph_coverage": 0.0,
            "literal_agreement_per_field": {},
            "literal_agreement_mean": None,
        }

    baseline_by_idx = {
        b["paragraph_index"]: b["enrichment"] for b in baseline_enrichments
    }

    common = set(candidate.keys()) & set(baseline_by_idx.keys())
    coverage = len(common) / max(1, n_paragraphs_expected)

    per_field: dict[str, list[int]] = {f: [] for f in LITERAL_FIELDS}
    for idx in common:
        c_enr = candidate[idx]
        b_enr = baseline_by_idx[idx]
        for field_name in LITERAL_FIELDS:
            c_val = c_enr.get(field_name)
            b_val = b_enr.get(field_name)
            per_field[field_name].append(1 if c_val == b_val else 0)

    agree_per_field = {
        f: (sum(v) / len(v) if v else None) for f, v in per_field.items()
    }
    valid_means = [a for a in agree_per_field.values() if a is not None]
    agree_mean = sum(valid_means) / len(valid_means) if valid_means else None

    return {
        "schema_valid": 1.0,
        "n_paragraphs_returned": len(candidate),
        "paragraph_coverage": coverage,
        "literal_agreement_per_field": agree_per_field,
        "literal_agreement_mean": agree_mean,
    }


def _run_one_chapter_per_chapter(*, fix: ChapterFixture) -> dict[str, Any]:
    """One Haiku-shaped call: emit all paragraph enrichments at once."""
    request = GenerationRequest(
        task="passage_enrichment",
        system=build_enrichment_prompt(fix.novel),
        user=build_user_message(fix),
        max_tokens=16000,
        json_schema=ChapterEnrichmentResult.model_json_schema(),
        temperature=0.0,
        # System prompt is short (~500 tokens); marker is a no-op below
        # Haiku's 1024-token cache minimum but preserved for parity with
        # the per-paragraph path's intent.
        cache_system=True,
        list_field_caps=LIST_FIELD_CAPS,
    )
    log.info("  -> %s/%s (%dp) START [per_chapter]",
             fix.novel, fix.chapter_id, len(fix.passages))
    t_start = time.time()
    try:
        result = generate(request)
        elapsed = time.time() - t_start
        text = result.text
        scored = score_one_chapter(
            candidate_text=text,
            baseline_enrichments=fix.baseline_enrichments,
            n_paragraphs_expected=len(fix.passages),
        )
        log.info(
            "  %s/%s schema=%.0f cov=%.2f agree=%s elapsed=%.1fs cost=$%.4f "
            "cache_read=%s create=%s",
            fix.novel, fix.chapter_id,
            scored["schema_valid"],
            scored["paragraph_coverage"],
            f"{scored['literal_agreement_mean']:.2f}"
                if scored["literal_agreement_mean"] is not None else "n/a",
            elapsed,
            result.estimated_cost_usd or 0.0,
            result.cache_read_input_tokens
                if result.cache_read_input_tokens is not None else "n/a",
            result.cache_creation_input_tokens
                if result.cache_creation_input_tokens is not None else "n/a",
        )
        # Parse full response so per-paragraph enrichments are
        # available for human eyeball / cross-candidate rendering.
        parsed = parse_candidate_output(text)
        candidate_enrichments = (
            {str(k): v for k, v in parsed.items()} if parsed else {}
        )
        return {
            "call_shape": "per_chapter",
            "novel": fix.novel,
            "chapter_id": fix.chapter_id,
            "n_paragraphs_expected": len(fix.passages),
            "n_calls": 1,
            "elapsed_seconds": elapsed,
            "cost_usd": result.estimated_cost_usd,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "cache_read_tokens": result.cache_read_input_tokens,
            "cache_creation_tokens": result.cache_creation_input_tokens,
            "provider_reported_cost_usd": result.provider_reported_cost_usd,
            "candidate_enrichments": candidate_enrichments,
            **scored,
        }
    except Exception as exc:
        elapsed = time.time() - t_start
        log.error("  %s/%s FAILED after %.1fs: %s",
                  fix.novel, fix.chapter_id, elapsed, exc)
        return {
            "call_shape": "per_chapter",
            "novel": fix.novel,
            "chapter_id": fix.chapter_id,
            "n_paragraphs_expected": len(fix.passages),
            "n_calls": 1,
            "elapsed_seconds": elapsed,
            "error": str(exc),
        }


def _build_per_paragraph_system(novel_key: str, chapter_id: str,
                                chapter_title: str, passages: list[dict]) -> str:
    """System block carries (a) the novel-specific enrichment instructions
    and (b) the whole chapter wrapped as <document>...</document>. Both
    are static across paragraphs of the same chapter, so this block is
    the cacheable prefix — Anthropic caches via cache_system=True;
    OpenAI/DeepInfra auto-cache identical prefixes.
    """
    instructions = build_enrichment_prompt(novel_key)
    formatted = format_chapter_text(passages)
    return (
        f"{instructions}\n\n"
        f"<document>\n"
        f"Chapter: {chapter_id} - {chapter_title}\n\n"
        f"{formatted}\n"
        f"</document>"
    )


def _parse_paragraph_output(text: str) -> tuple[dict | None, str | None]:
    """Parse one ParagraphEnrichment response.

    Returns (enrichment_dict, error_message). On success: (dict, None).
    On parse failure: (None, "<error tag>: <message>"). Empty text is
    treated as a distinct failure mode for diagnostics.
    """
    if not text or not text.strip():
        return None, "empty_response: no text content from provider"
    try:
        obj = ParagraphEnrichment.model_validate_json(text)
    except Exception as exc:
        log.debug("paragraph schema validation failed: %s", exc)
        return None, f"schema_invalid: {type(exc).__name__}: {str(exc)[:300]}"
    return obj.enrichment.model_dump(), None


def _run_one_chapter_per_paragraph(*, fix: ChapterFixture) -> dict[str, Any]:
    """N small calls: each requests one paragraph's enrichment, with the
    whole chapter cached in the system block."""
    system = _build_per_paragraph_system(
        fix.novel, fix.chapter_id, fix.chapter_title, fix.passages,
    )
    schema = ParagraphEnrichment.model_json_schema()

    log.info("  -> %s/%s (%dp) START [per_paragraph]",
             fix.novel, fix.chapter_id, len(fix.passages))
    t_start = time.time()

    candidate: dict[int, dict] = {}
    total_cost = 0.0
    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_read_tokens = 0
    total_cache_creation_tokens = 0
    cache_read_reported = False  # True if any call surfaced cached_tokens
    failed_paragraphs: list[int] = []
    failure_diagnostics: list[dict] = []  # one entry per failure with details

    for p in fix.passages:
        idx = p["paragraph_index"]
        user_msg = (
            f"Return one `ParagraphEnrichment` object for paragraph "
            f"[P{idx}] of the chapter above. The enrichment must "
            f"describe ONLY this paragraph:\n\n"
            f"[P{idx}] {p['text']}"
        )
        call_t0 = time.time()
        try:
            result = generate(GenerationRequest(
                task="passage_enrichment",
                system=system,
                user=user_msg,
                # 8192 (up from 2048) so the richest paragraphs in
                # a chapter don't truncate. Rich Margaret/Lennox-style
                # passages can produce ~2k token rationales; an 8k
                # ceiling gives 4× headroom without affecting cost
                # (output billed on emitted tokens, not max).
                max_tokens=8192,
                json_schema=schema,
                temperature=0.0,
                cache_system=True,
                list_field_caps=LIST_FIELD_CAPS,
            ))
        except Exception as exc:
            call_elapsed = time.time() - call_t0
            # Try to extract HTTP status / response body from the
            # exception. openai SDK puts these on APIError subclasses.
            status = getattr(exc, "status_code", None)
            body = getattr(exc, "body", None)
            response = getattr(exc, "response", None)
            response_text = None
            if response is not None:
                try:
                    response_text = response.text[:500]
                except Exception:
                    pass
            log.error(
                "    p%d FAILED (network/sdk) after %.1fs: %s%s",
                idx, call_elapsed, type(exc).__name__,
                f" status={status}" if status else "",
            )
            failed_paragraphs.append(idx)
            failure_diagnostics.append({
                "paragraph_index": idx,
                "stage": "generate",
                "elapsed_seconds": call_elapsed,
                "exception_type": type(exc).__name__,
                "message": str(exc)[:500],
                "status_code": status,
                "response_body": body if isinstance(body, (str, dict, list)) else (str(body)[:500] if body is not None else None),
                "response_text_preview": response_text,
            })
            continue

        call_elapsed = time.time() - call_t0
        enr, parse_err = _parse_paragraph_output(result.text)
        if enr is None:
            failed_paragraphs.append(idx)
            failure_diagnostics.append({
                "paragraph_index": idx,
                "stage": "parse",
                "elapsed_seconds": call_elapsed,
                "parse_error": parse_err,
                "raw_text_preview": (result.text or "")[:500],
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cache_read_input_tokens": result.cache_read_input_tokens,
            })
        else:
            candidate[idx] = enr
        total_cost += result.estimated_cost_usd or 0.0
        total_input_tokens += result.input_tokens or 0
        total_output_tokens += result.output_tokens or 0
        if result.cache_read_input_tokens is not None:
            cache_read_reported = True
            total_cache_read_tokens += result.cache_read_input_tokens
        if result.cache_creation_input_tokens is not None:
            total_cache_creation_tokens += result.cache_creation_input_tokens

    elapsed = time.time() - t_start

    # Score against baseline using same logic as per-chapter, but built
    # from the per-paragraph dict directly.
    baseline_by_idx = {
        b["paragraph_index"]: b["enrichment"] for b in fix.baseline_enrichments
    }
    common = set(candidate.keys()) & set(baseline_by_idx.keys())
    coverage = len(common) / max(1, len(fix.passages))
    per_field: dict[str, list[int]] = {f: [] for f in LITERAL_FIELDS}
    for idx in common:
        c_enr = candidate[idx]
        b_enr = baseline_by_idx[idx]
        for field_name in LITERAL_FIELDS:
            per_field[field_name].append(
                1 if c_enr.get(field_name) == b_enr.get(field_name) else 0
            )
    agree_per_field = {
        f: (sum(v) / len(v) if v else None) for f, v in per_field.items()
    }
    valid_means = [a for a in agree_per_field.values() if a is not None]
    agree_mean = sum(valid_means) / len(valid_means) if valid_means else None

    schema_valid = 1.0 if not failed_paragraphs else (
        len(candidate) / max(1, len(fix.passages))
    )

    cache_frac = (
        total_cache_read_tokens / max(1, total_input_tokens)
        if cache_read_reported else None
    )
    log.info(
        "  %s/%s schema_ok=%d/%d cov=%.2f agree=%s elapsed=%.1fs cost=$%.4f cache=%s",
        fix.novel, fix.chapter_id,
        len(candidate), len(fix.passages),
        coverage,
        f"{agree_mean:.2f}" if agree_mean is not None else "n/a",
        elapsed, total_cost,
        f"{cache_frac:.0%} read" if cache_frac is not None
            else "not reported",
    )

    return {
        "call_shape": "per_paragraph",
        "novel": fix.novel,
        "chapter_id": fix.chapter_id,
        "n_paragraphs_expected": len(fix.passages),
        "n_calls": len(fix.passages),
        "n_paragraphs_returned": len(candidate),
        "n_paragraphs_failed": len(failed_paragraphs),
        "failed_paragraphs": failed_paragraphs,
        "failure_diagnostics": failure_diagnostics,
        "elapsed_seconds": elapsed,
        "cost_usd": total_cost,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cache_read_tokens": (
            total_cache_read_tokens if cache_read_reported else None
        ),
        "cache_creation_tokens": total_cache_creation_tokens,
        "schema_valid": schema_valid,
        "paragraph_coverage": coverage,
        "literal_agreement_per_field": agree_per_field,
        "literal_agreement_mean": agree_mean,
        # Per-paragraph candidate output (for eyeball comparison vs
        # other candidates / Haiku baseline). Keyed by paragraph_index.
        "candidate_enrichments": {str(k): v for k, v in candidate.items()},
    }


def _run_one_chapter(
    *, fix: ChapterFixture, call_shape: str,
) -> dict[str, Any]:
    """Dispatch on candidate's call shape."""
    if call_shape == "per_chapter":
        return _run_one_chapter_per_chapter(fix=fix)
    if call_shape == "per_paragraph":
        return _run_one_chapter_per_paragraph(fix=fix)
    raise ValueError(f"unknown call_shape: {call_shape!r}")


def run_candidate(
    *, candidate_name: str, spec: ModelSpec, call_shape: str,
    fixtures: list[ChapterFixture],
    run_id: str,
    max_workers: int = 1,
) -> dict[str, Any]:
    """Run all fixtures through one candidate, score each, return summary.

    Fixtures are grouped by novel so consecutive chapters share an
    identical system prompt, maximising prompt-cache hits (Anthropic
    cache_system=True; DeepInfra/OpenAI cache by prefix automatically).

    Default max_workers=1 (sequential) so progress is visible in
    real time and the prompt cache stays hot rather than fighting
    multiple in-flight requests with the same prefix. Raise it for
    candidates that need wall-clock compression.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    settings.register_task("passage_enrichment", spec)

    # Sort by novel for cache locality. Within a novel, sort by
    # chapter_id for deterministic ordering.
    grouped = sorted(fixtures, key=lambda f: (f.novel, f.chapter_id))

    t0 = time.time()
    per_chapter: list[dict] = []

    if max_workers == 1:
        # Sequential path: log each completion in order, no thread
        # pool overhead. Required for per_paragraph: sequential keeps
        # the prompt cache hot across same-chapter paragraphs.
        for fix in grouped:
            per_chapter.append(_run_one_chapter(fix=fix, call_shape=call_shape))
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {
                ex.submit(_run_one_chapter, fix=fix, call_shape=call_shape):
                    fix for fix in grouped
            }
            for fut in as_completed(futures):
                per_chapter.append(fut.result())
        per_chapter.sort(key=lambda d: (d["novel"], d["chapter_id"]))

    total_cost = sum(c.get("cost_usd") or 0.0 for c in per_chapter)
    total_input_tokens = sum(c.get("input_tokens") or 0 for c in per_chapter)
    total_output_tokens = sum(c.get("output_tokens") or 0 for c in per_chapter)

    schema_valid_mean = (
        sum(c.get("schema_valid", 0.0) for c in per_chapter) / len(per_chapter)
        if per_chapter else 0.0
    )
    coverage_mean = (
        sum(c.get("paragraph_coverage", 0.0) for c in per_chapter) / len(per_chapter)
        if per_chapter else 0.0
    )
    agree_values = [
        c["literal_agreement_mean"] for c in per_chapter
        if c.get("literal_agreement_mean") is not None
    ]
    agree_mean = sum(agree_values) / len(agree_values) if agree_values else None

    summary = {
        "candidate": candidate_name,
        "provider": spec.provider,
        "model": spec.model,
        "hosting": spec.hosting,
        "n_chapters": len(fixtures),
        "elapsed_seconds": time.time() - t0,
        "schema_valid_mean": schema_valid_mean,
        "coverage_mean": coverage_mean,
        "literal_agreement_mean": agree_mean,
        "total_cost_usd": total_cost,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "per_chapter": per_chapter,
    }
    save_results(run_id, candidate_name, summary)
    return summary


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n", type=int, default=3, help="number of chapters")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--min-paragraphs", type=int, default=15)
    p.add_argument("--max-paragraphs", type=int, default=50)
    p.add_argument(
        "--candidates", type=str,
        default="haiku,gpt4o_mini,qwen3_next_80b,gemma4_26b_a4b",
        help="comma-separated candidate names from "
             "{haiku, gpt4o_mini, qwen3_next_80b, gemma4_26b_a4b}",
    )
    p.add_argument("--workers", type=int, default=1,
                   help="per-candidate concurrent chapter requests "
                        "(default 1: sequential, max prompt-cache reuse, "
                        "real-time progress)")
    p.add_argument(
        "--run-id", type=str,
        default="stage2_tier_m_haiku_passage_enrichment_v5",
    )
    args = p.parse_args()

    load_dotenv()
    candidates = [c.strip() for c in args.candidates.split(",") if c.strip()]
    unknown = [c for c in candidates if c not in CANDIDATES]
    if unknown:
        raise SystemExit(f"unknown candidates: {unknown}; known: {list(CANDIDATES)}")

    log.info(
        "finding chapters in [%d, %d) paragraphs",
        args.min_paragraphs, args.max_paragraphs,
    )
    all_fixtures = find_small_chapters(
        min_paragraphs=args.min_paragraphs,
        max_paragraphs=args.max_paragraphs,
    )
    log.info("found %d eligible chapters across novels", len(all_fixtures))
    if len(all_fixtures) < args.n:
        raise SystemExit(
            f"only {len(all_fixtures)} eligible; can't sample {args.n}"
        )
    rng = random.Random(args.seed)
    fixtures = rng.sample(all_fixtures, args.n)
    log.info(
        "fixture: %s",
        [f"{f.novel}/{f.chapter_id}({len(f.passages)}p)" for f in fixtures],
    )

    summary_all: dict[str, Any] = {}
    for name in candidates:
        cand = CANDIDATES[name]
        log.info("=== candidate %s (provider=%s model=%s shape=%s) ===",
                 name, cand.spec.provider, cand.spec.model, cand.call_shape)
        s = run_candidate(
            candidate_name=name, spec=cand.spec, call_shape=cand.call_shape,
            fixtures=fixtures, run_id=args.run_id,
            max_workers=args.workers,
        )
        summary_all[name] = {
            k: v for k, v in s.items() if k != "per_chapter"
        }
        summary_all[name]["call_shape"] = cand.call_shape

    log.info("=" * 60)
    log.info("SUMMARY")
    for name, s in summary_all.items():
        log.info(
            "  %-15s schema=%.2f cov=%.2f literal_agree=%s cost=$%.4f wall=%.1fs",
            name,
            s["schema_valid_mean"],
            s["coverage_mean"],
            f"{s['literal_agreement_mean']:.3f}" if s["literal_agreement_mean"] is not None else "n/a",
            s["total_cost_usd"] or 0.0,
            s["elapsed_seconds"],
        )

    save_results(args.run_id, "summary", {
        "n_chapters": len(fixtures),
        "fixtures": [
            {"novel": f.novel, "chapter_id": f.chapter_id,
             "n_paragraphs": len(f.passages)}
            for f in fixtures
        ],
        "candidates": summary_all,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
