"""Build and submit Anthropic batch requests for passage enrichment.

Usage:
  uv run python -m enrichment.submit_passages_enriched [--chapters c1,c2,c3]
  uv run python -m enrichment.submit_passages_enriched --novel our_mutual_friend
"""

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

from enrichment.novel_prompts import (  # noqa: I001 — single source of truth
    NOVEL_CONFIGS,
    build_enrichment_prompt,
)
from enrichment.schemas import ChapterEnrichmentResult

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")

# Available novels — derived from novel_prompts.NOVEL_CONFIGS, the single
# source of truth. Avoids the previous drift where adding a novel meant
# editing three hardcoded lists.
NOVEL_KEYS = sorted(NOVEL_CONFIGS.keys())

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 60000
MAX_PARAGRAPHS_PER_REQUEST = 200


def format_chapter_text(passages: list[dict]) -> str:
    """Format passages into marked-up text for the LLM."""
    lines: list[str] = []
    for p in passages:
        lines.append(f"[P{p['paragraph_index']}] {p['text']}")
    return "\n\n".join(lines)


def build_requests(
    passages_by_chapter: dict[str, list[dict]],
    system_prompt: str,
) -> list[Request]:
    """Build batch request objects, splitting large chapters."""
    schema = ChapterEnrichmentResult.model_json_schema()
    requests: list[Request] = []

    for chapter_id, passages in sorted(passages_by_chapter.items()):
        # Split into chunks if too many paragraphs
        chunks: list[list[dict]] = []
        if len(passages) > MAX_PARAGRAPHS_PER_REQUEST:
            mid = len(passages) // 2
            chunks = [passages[:mid], passages[mid:]]
        else:
            chunks = [passages]

        for chunk_idx, chunk in enumerate(chunks):
            custom_id = f"enrich-{chapter_id}"
            if len(chunks) > 1:
                custom_id += f"-part{chunk_idx}"

            formatted = format_chapter_text(chunk)
            chapter_title = chunk[0].get("chapter_title", "")
            user_message = (
                f"Chapter: {chapter_id} - {chapter_title}\n\n{formatted}"
            )

            requests.append(
                Request(
                    custom_id=custom_id,
                    params=MessageCreateParamsNonStreaming(
                        model=MODEL,
                        max_tokens=MAX_TOKENS,
                        output_config={
                            "format": {
                                "type": "json_schema",
                                "schema": schema,
                            }
                        },
                        system=system_prompt,
                        messages=[
                            {"role": "user", "content": user_message}
                        ],
                    ),
                )
            )

    return requests


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--chapters",
        type=str,
        default=None,
        help="Comma-separated chapter IDs to submit (default: all)",
    )
    parser.add_argument(
        "--novel",
        type=str,
        choices=NOVEL_KEYS,
        required=True,
        help="Novel key (reads from data/novels/<key>/passages_raw.json)",
    )
    args = parser.parse_args()

    novel_dir = DATA_DIR / "novels" / args.novel
    passages_path = novel_dir / "passages_raw.json"
    manifest_path = novel_dir / "batch_manifest.json"
    system_prompt = build_enrichment_prompt(args.novel)
    logger.info("Using novel-specific prompt for %s", args.novel)

    load_dotenv()
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    raw = json.loads(passages_path.read_text())
    passages_by_chapter: dict[str, list[dict]] = {}
    for p in raw:
        passages_by_chapter.setdefault(p["chapter_id"], []).append(p)

    if args.chapters:
        selected = set(args.chapters.split(","))
        passages_by_chapter = {
            k: v for k, v in passages_by_chapter.items() if k in selected
        }
        logger.info("Filtered to chapters: %s", sorted(passages_by_chapter))

    requests = build_requests(passages_by_chapter, system_prompt=system_prompt)
    logger.info("Built %d batch requests", len(requests))

    batch = client.messages.batches.create(requests=requests)

    manifest = {
        "batch_id": batch.id,
        "novel": args.novel,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "request_count": len(requests),
        "chapter_ids": sorted(passages_by_chapter.keys()),
        "model": MODEL,
        "status": "submitted",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    logger.info("Batch %s submitted (%d requests)", batch.id, len(requests))
    logger.info("Manifest saved to %s", manifest_path)


if __name__ == "__main__":
    main()
