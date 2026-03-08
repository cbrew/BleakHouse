"""Re-submit batch requests for chapters missing from enriched results.

Usage: uv run python -m enrichment.retry_failed
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from enrichment.submit_batch import build_requests

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
PASSAGES_PATH = DATA_DIR / "passages_raw.json"
ENRICHED_PATH = DATA_DIR / "passages_enriched.json"
MANIFEST_PATH = DATA_DIR / "batch_manifest.json"


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    raw = json.loads(PASSAGES_PATH.read_text())
    enriched = json.loads(ENRICHED_PATH.read_text())

    all_chapter_ids = {p["chapter_id"] for p in raw}
    enriched_chapter_ids = {p["chapter_id"] for p in enriched}
    missing = all_chapter_ids - enriched_chapter_ids

    if not missing:
        logger.info("All chapters enriched, nothing to retry.")
        return

    logger.info("Missing chapters: %s", sorted(missing))

    passages_by_chapter: dict[str, list[dict]] = {}
    for p in raw:
        if p["chapter_id"] in missing:
            passages_by_chapter.setdefault(p["chapter_id"], []).append(p)

    requests = build_requests(passages_by_chapter)
    logger.info("Built %d retry requests", len(requests))

    load_dotenv()
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    batch = client.messages.batches.create(requests=requests)

    manifest = {
        "batch_id": batch.id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "request_count": len(requests),
        "chapter_ids": sorted(missing),
        "model": "claude-haiku-4-5-20251001",
        "status": "submitted (retry)",
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
    logger.info("Retry batch %s submitted (%d requests)", batch.id, len(requests))
    logger.info("Run collect_results.py again after this batch completes.")


if __name__ == "__main__":
    main()
