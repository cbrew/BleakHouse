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
from enrichment.prompt import ENRICHMENT_SYSTEM_PROMPT  # noqa: E402
from enrichment.schemas import ChapterEnrichmentResult  # noqa: E402
from enrichment.submit_passages_enriched import format_chapter_text  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("eval-passage-enrichment")

REPO_DATA = REPO_ROOT / "data"
DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"

CANDIDATES: dict[str, ModelSpec] = {
    "haiku": ModelSpec(
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        hosting="anthropic",
    ),
    "qwen72b": ModelSpec(
        provider="openai_compatible",
        model="Qwen/Qwen2.5-72B-Instruct",
        hosting="deepinfra",
        base_url=DEEPINFRA_BASE_URL,
    ),
    "llama70b_turbo": ModelSpec(
        provider="openai_compatible",
        model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        hosting="deepinfra",
        base_url=DEEPINFRA_BASE_URL,
    ),
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


def run_candidate(
    *, candidate_name: str, spec: ModelSpec,
    fixtures: list[ChapterFixture],
    run_id: str,
) -> dict[str, Any]:
    """Run all fixtures through one candidate, score each, return summary."""
    settings.register_task("passage_enrichment", spec)

    per_chapter: list[dict] = []
    t0 = time.time()
    total_cost = 0.0
    total_input_tokens = 0
    total_output_tokens = 0

    for fix in fixtures:
        request = GenerationRequest(
            task="passage_enrichment",
            system=ENRICHMENT_SYSTEM_PROMPT,
            user=build_user_message(fix),
            max_tokens=16000,
            json_schema=ChapterEnrichmentResult.model_json_schema(),
        )
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
            total_cost += result.estimated_cost_usd or 0.0
            total_input_tokens += result.input_tokens or 0
            total_output_tokens += result.output_tokens or 0
            log.info(
                "  %s/%s schema=%.0f cov=%.2f agree=%s elapsed=%.1fs cost=$%.4f",
                fix.novel, fix.chapter_id,
                scored["schema_valid"],
                scored["paragraph_coverage"],
                f"{scored['literal_agreement_mean']:.2f}" if scored["literal_agreement_mean"] is not None else "n/a",
                elapsed,
                result.estimated_cost_usd or 0.0,
            )
            per_chapter.append({
                "novel": fix.novel,
                "chapter_id": fix.chapter_id,
                "n_paragraphs_expected": len(fix.passages),
                "elapsed_seconds": elapsed,
                "cost_usd": result.estimated_cost_usd,
                "candidate_text": text[:5000],  # truncate to keep eval files small
                **scored,
            })
        except Exception as exc:
            elapsed = time.time() - t_start
            log.error("  %s/%s FAILED after %.1fs: %s", fix.novel, fix.chapter_id, elapsed, exc)
            per_chapter.append({
                "novel": fix.novel,
                "chapter_id": fix.chapter_id,
                "n_paragraphs_expected": len(fix.passages),
                "elapsed_seconds": elapsed,
                "error": str(exc),
            })

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
        default="haiku,qwen72b,llama70b_turbo",
        help="comma-separated candidate names from {haiku, qwen72b, llama70b_turbo}",
    )
    p.add_argument("--run-id", type=str, default="stage2_tier_m_haiku_passage_enrichment")
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
        spec = CANDIDATES[name]
        log.info("=== candidate %s (provider=%s model=%s) ===",
                 name, spec.provider, spec.model)
        s = run_candidate(
            candidate_name=name, spec=spec,
            fixtures=fixtures, run_id=args.run_id,
        )
        summary_all[name] = {
            k: v for k, v in s.items() if k != "per_chapter"
        }

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
