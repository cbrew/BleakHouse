"""Test enrichment on a single chapter synchronously.

Run this before submitting a batch to validate schema, prompt, and parsing.

Migrated to the provider-neutral seam (BleakHouse-4thc / Phase 1 of
the Anthropic-optionality migration). Behavior preserved: default
task routing for 'passage_enrichment' points at the same Claude
Haiku model and uses Anthropic structured-output configuration via
the seam.

Usage: uv run python -m enrichment.test_single [--chapter c1]
"""

import argparse
import json
import logging
from pathlib import Path

from dotenv import load_dotenv

from enrichment.llm import GenerationRequest, generate
from enrichment.prompt import ENRICHMENT_SYSTEM_PROMPT
from enrichment.schemas import ChapterEnrichmentResult
from enrichment.submit_passages_enriched import format_chapter_text

TOKENS_PER_PARAGRAPH = 350

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
PASSAGES_PATH = DATA_DIR / "passages_raw.json"


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--chapter",
        type=str,
        default="c1",
        help="Chapter ID to test (default: c1)",
    )
    args = parser.parse_args()

    load_dotenv()

    raw = json.loads(PASSAGES_PATH.read_text())
    passages = [p for p in raw if p["chapter_id"] == args.chapter]
    if not passages:
        logger.error("No passages found for chapter %s", args.chapter)
        return

    logger.info("Testing chapter %s (%d paragraphs)", args.chapter, len(passages))

    schema = ChapterEnrichmentResult.model_json_schema()
    formatted = format_chapter_text(passages)
    title = passages[0].get("chapter_title", "")
    user_message = f"Chapter: {args.chapter} - {title}\n\n{formatted}"

    max_tokens = min(len(passages) * TOKENS_PER_PARAGRAPH, 8192)
    logger.info("Using max_tokens=%d", max_tokens)

    result = generate(GenerationRequest(
        task="passage_enrichment",
        system=ENRICHMENT_SYSTEM_PROMPT,
        user=user_message,
        max_tokens=max_tokens,
        json_schema=schema,
    ))

    logger.info(
        "provider=%s model=%s hosting=%s input_tokens=%s output_tokens=%s cost=%s",
        result.provider, result.model, result.hosting,
        result.input_tokens, result.output_tokens,
        f"${result.estimated_cost_usd:.4f}" if result.estimated_cost_usd else "unknown",
    )

    enriched = ChapterEnrichmentResult.model_validate_json(result.text)

    logger.info(
        "OK: %d enrichments for chapter %s (expected %d)",
        len(enriched.enrichments),
        enriched.chapter_id,
        len(passages),
    )
    for e in enriched.enrichments:
        en = e.enrichment
        logger.info(
            "  p%d: score=%d narrator=%s plot=%s — %s",
            e.paragraph_index,
            en.interest_score,
            en.narrator,
            en.plot_function,
            en.summary[:80],
        )


if __name__ == "__main__":
    main()
