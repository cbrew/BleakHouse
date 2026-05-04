"""Submit context generation as Anthropic batch requests.

Uses the Batch API instead of sequential calls. Prompt caching is
best-effort in batches (not guaranteed), but the 50% batch discount
on input tokens compensates. Much faster wall-clock time.

Idempotency: writes data/novels/<novel>/context_batch_manifest.json
when the batch is submitted. Re-running with the manifest already
present is a no-op (refuses to create a duplicate batch). To re-submit,
delete the manifest first.

Usage:
    uv run python -m enrichment.submit_passage_contexts --novel hard_times
    uv run python -m enrichment.submit_passage_contexts --novel middlemarch --chapters c1,c2,c3
"""

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
from dotenv import load_dotenv

from enrichment.axes import NOVEL_IDS  # canonical source of novel directory ids
from enrichment.context_prompt import build_context_messages
from enrichment.submit_batch import format_chapter_text

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 300


def build_context_requests(
    by_chapter: dict[str, list[dict]],
    novel_key: str,
) -> list[Request]:
    """Build batch requests for context generation."""
    # Set env var so build_context_messages can find the novel config
    os.environ["BLEAKHOUSE_NOVEL"] = novel_key

    requests: list[Request] = []
    seq = 0
    for chapter_id in sorted(by_chapter):
        passages = by_chapter[chapter_id]
        chapter_text = format_chapter_text(passages)

        for passage in passages:
            pid = f"s{seq}"
            seq += 1
            system_blocks, user_msg = build_context_messages(
                chapter_text, passage["text"]
            )

            requests.append(
                Request(
                    custom_id=f"ctx-{pid}",
                    params=MessageCreateParamsNonStreaming(
                        model=MODEL,
                        max_tokens=MAX_TOKENS,
                        temperature=0,  # tightens cross-run consistency for the C/D comparison
                        system=system_blocks,
                        messages=[{"role": "user", "content": user_msg}],
                    ),
                )
            )

    return requests


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(
        description="Submit context generation as batch"
    )
    parser.add_argument(
        "--novel", required=True, choices=sorted(NOVEL_IDS), help="Novel key"
    )
    parser.add_argument(
        "--chapters", type=str, default=None,
        help="Comma-separated chapter IDs (default: all)",
    )
    args = parser.parse_args()

    novel_dir = DATA_DIR / "novels" / args.novel
    passages_path = novel_dir / "passages_enriched.json"
    manifest_path = novel_dir / "context_batch_manifest.json"

    if manifest_path.exists():
        logger.info(
            "%s already exists; nothing to do. Run collect_passage_contexts "
            "to retrieve results, or delete the manifest to resubmit.",
            manifest_path,
        )
        return

    load_dotenv()
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    raw = json.loads(passages_path.read_text())
    by_chapter: dict[str, list[dict]] = {}
    for p in raw:
        by_chapter.setdefault(p["chapter_id"], []).append(p)

    if args.chapters:
        selected = set(args.chapters.split(","))
        by_chapter = {k: v for k, v in by_chapter.items() if k in selected}

    requests = build_context_requests(by_chapter, args.novel)
    logger.info("Built %d context requests for %s", len(requests), args.novel)

    batch = client.messages.batches.create(requests=requests)

    # Build custom_id → passage_id mapping for the collector
    id_map = {}
    seq2 = 0
    for chapter_id in sorted(by_chapter):
        for passage in by_chapter[chapter_id]:
            id_map[f"ctx-s{seq2}"] = passage["passage_id"]
            seq2 += 1

    manifest = {
        "batch_id": batch.id,
        "novel": args.novel,
        "type": "context",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "request_count": len(requests),
        "chapter_ids": sorted(by_chapter.keys()),
        "model": MODEL,
        "status": "submitted",
        "id_map": id_map,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    logger.info("Batch %s submitted (%d requests)", batch.id, len(requests))
    logger.info("Manifest saved to %s", manifest_path)


if __name__ == "__main__":
    main()
