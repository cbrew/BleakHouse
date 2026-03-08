"""Test enrichment on a single chapter synchronously.

Run this before submitting a batch to validate schema, prompt, and parsing.

Usage: uv run python -m enrichment.test_single [--chapter c1]
"""

import argparse
import json
import logging
import os
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from enrichment.prompt import ENRICHMENT_SYSTEM_PROMPT
from enrichment.schemas import ChapterEnrichmentResult
from enrichment.submit_batch import MODEL, format_chapter_text

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
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

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

    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        output_config={"format": {"type": "json_schema", "schema": schema}},
        system=ENRICHMENT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    block = response.content[0]
    assert block.type == "text"
    result = ChapterEnrichmentResult.model_validate_json(block.text)

    logger.info(
        "OK: %d enrichments for chapter %s (expected %d)",
        len(result.enrichments),
        result.chapter_id,
        len(passages),
    )
    for e in result.enrichments:
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
