"""Build and submit Anthropic batch requests for passage enrichment.

Usage: uv run python -m enrichment.submit_batch [--chapters c1,c2,c3]
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

from enrichment.prompt import ENRICHMENT_SYSTEM_PROMPT
from enrichment.schemas import ChapterEnrichmentResult

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
PASSAGES_PATH = DATA_DIR / "passages_raw.json"
MANIFEST_PATH = DATA_DIR / "batch_manifest.json"

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
                        system=ENRICHMENT_SYSTEM_PROMPT,
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
    args = parser.parse_args()

    load_dotenv()
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    raw = json.loads(PASSAGES_PATH.read_text())
    passages_by_chapter: dict[str, list[dict]] = {}
    for p in raw:
        passages_by_chapter.setdefault(p["chapter_id"], []).append(p)

    if args.chapters:
        selected = set(args.chapters.split(","))
        passages_by_chapter = {
            k: v for k, v in passages_by_chapter.items() if k in selected
        }
        logger.info("Filtered to chapters: %s", sorted(passages_by_chapter))

    requests = build_requests(passages_by_chapter)
    logger.info("Built %d batch requests", len(requests))

    batch = client.messages.batches.create(requests=requests)

    manifest = {
        "batch_id": batch.id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "request_count": len(requests),
        "chapter_ids": sorted(passages_by_chapter.keys()),
        "model": MODEL,
        "status": "submitted",
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
    logger.info("Batch %s submitted (%d requests)", batch.id, len(requests))
    logger.info("Manifest saved to %s", MANIFEST_PATH)


if __name__ == "__main__":
    main()
