"""Eyeball-compare per-paragraph enrichment across candidates.

Hits each candidate model with the per_paragraph call shape on a
small fixed set of paragraphs from one chapter, prints the resulting
enrichments side by side along with the existing Haiku baseline. Use
this when the eval metrics suggest a difference but the literal-field-
agreement metric is too coarse to tell whether differences are
meaningful or noise.

Usage:
    uv run python scripts/eyeball_compare.py \\
        --novel north_and_south --chapter c6 \\
        --paragraphs 0,5,10,15

If --paragraphs is omitted, picks a quarter-and-three-quarter sample
from the chapter (one near the start, one near the end).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

from enrichment.llm import GenerationRequest, generate, settings  # noqa: E402
from enrichment.llm.types import ModelSpec  # noqa: E402
from enrichment.novel_prompts import build_enrichment_prompt  # noqa: E402
from enrichment.llm.schemas import ParagraphEnrichment  # noqa: E402
from enrichment.submit_passages_enriched import format_chapter_text  # noqa: E402

DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"

CANDIDATES = {
    "gpt4o_mini": ModelSpec(
        provider="openai_compatible", model="gpt-4o-mini",
        hosting="openai", base_url=None,
    ),
    "qwen3_next_80b": ModelSpec(
        provider="openai_compatible",
        model="Qwen/Qwen3-Next-80B-A3B-Instruct",
        hosting="deepinfra", base_url=DEEPINFRA_BASE_URL,
    ),
    "gemma4_26b_a4b": ModelSpec(
        provider="openai_compatible",
        model="google/gemma-4-26B-A4B-it",
        hosting="deepinfra", base_url=DEEPINFRA_BASE_URL,
    ),
    "deepseek_v4_flash": ModelSpec(
        provider="openai_compatible",
        model="deepseek-ai/DeepSeek-V4-Flash",
        hosting="deepinfra", base_url=DEEPINFRA_BASE_URL,
    ),
}


def render_enrichment_brief(e: dict, label: str) -> str:
    """One-paragraph human-readable summary of a FieldReportEnrichment dict."""
    lines = [f"  [{label}]"]
    lines.append(f"    interest: {e.get('interest_score')}  "
                 f"narrator: {e.get('narrator')}  "
                 f"plot: {e.get('plot_function')}")
    chars = e.get('characters_present', [])
    speaking = e.get('characters_speaking', [])
    lines.append(f"    characters: {chars}")
    if speaking:
        lines.append(f"    speaking: {speaking}")
    lines.append(f"    themes: {e.get('themes')}")
    lines.append(f"    register: {e.get('emotional_register')}")
    lines.append(f"    quotability: {e.get('quotability')} | "
                 f"accessibility: {e.get('accessibility')}")
    bq = e.get('best_quote')
    if bq:
        lines.append(f"    best_quote: {bq[:120]!r}")
    lines.append(f"    summary: {e.get('summary')}")
    prov = {k: v for k, v in e.items() if k.startswith("prov_")}
    nonzero = [f"{k.removeprefix('prov_')}={v}" for k, v in prov.items()
               if v not in (None, "none")]
    if nonzero:
        lines.append(f"    provisions: {' | '.join(nonzero)}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--novel", default="north_and_south")
    parser.add_argument("--chapter", default="c6")
    parser.add_argument("--paragraphs", type=str, default=None,
                        help="Comma-separated paragraph indices; "
                             "default: quartiles of the chapter")
    parser.add_argument("--candidates", type=str,
                        default="gpt4o_mini,qwen3_next_80b,gemma4_26b_a4b")
    args = parser.parse_args()

    load_dotenv()

    # Load the chapter's passages
    enriched_path = (REPO_ROOT / "data" / "novels" / args.novel
                     / "passages_enriched.json")
    raw = json.loads(enriched_path.read_text())
    passages = sorted(
        [p for p in raw if p["chapter_id"] == args.chapter],
        key=lambda p: p["paragraph_index"],
    )
    if not passages:
        raise SystemExit(f"no passages found for {args.novel}/{args.chapter}")
    n = len(passages)
    print(f"Chapter has {n} paragraphs.")

    # Select paragraphs to compare
    if args.paragraphs:
        target_idxs = [int(x) for x in args.paragraphs.split(",")]
    else:
        target_idxs = sorted({n // 4, n // 2, (3 * n) // 4})
    target_idxs = [i for i in target_idxs
                   if any(p["paragraph_index"] == i for p in passages)]
    print(f"Comparing paragraphs: {target_idxs}")

    # Build the shared system block (cached prefix)
    chapter_text = format_chapter_text(passages)
    chapter_title = passages[0].get("chapter_title", "")
    system_block = (
        f"{build_enrichment_prompt(args.novel)}\n\n<document>\n"
        f"Chapter: {args.chapter} - {chapter_title}\n\n"
        f"{chapter_text}\n</document>"
    )
    schema = ParagraphEnrichment.model_json_schema()

    # Candidates to compare
    cand_names = [c.strip() for c in args.candidates.split(",") if c.strip()]
    unknown = [c for c in cand_names if c not in CANDIDATES]
    if unknown:
        raise SystemExit(f"unknown candidates: {unknown}")

    by_idx = {p["paragraph_index"]: p for p in passages}

    for idx in target_idxs:
        p = by_idx[idx]
        print()
        print("=" * 88)
        print(f"Paragraph [P{idx}]: {p['text'][:200]!r}{'...' if len(p['text']) > 200 else ''}")
        print("=" * 88)

        # Existing Haiku baseline
        baseline = p.get("enrichment")
        if baseline is not None:
            print()
            print(render_enrichment_brief(baseline, "haiku (baseline, per_chapter)"))

        # Each candidate
        for name in cand_names:
            spec = CANDIDATES[name]
            settings.register_task("passage_enrichment", spec)
            user_msg = (
                f"Return one `ParagraphEnrichment` object for paragraph "
                f"[P{idx}] of the chapter above. The enrichment must "
                f"describe ONLY this paragraph:\n\n"
                f"[P{idx}] {p['text']}"
            )
            try:
                r = generate(GenerationRequest(
                    task="passage_enrichment",
                    system=system_block,
                    user=user_msg,
                    max_tokens=2048,
                    json_schema=schema,
                    temperature=0.0,
                    cache_system=True,
                ))
                obj = ParagraphEnrichment.model_validate_json(r.text)
                print()
                print(render_enrichment_brief(obj.enrichment.model_dump(), name))
            except Exception as exc:
                print()
                print(f"  [{name}] FAILED: {type(exc).__name__}: {str(exc)[:200]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
