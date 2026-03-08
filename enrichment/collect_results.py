"""Poll a batch and collect enrichment results.

Usage: uv run python -m enrichment.collect_results
"""

import json
import logging
import os
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from enrichment.schemas import ChapterEnrichmentResult, Passage

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
MANIFEST_PATH = DATA_DIR / "batch_manifest.json"
PASSAGES_PATH = DATA_DIR / "passages_raw.json"
OUTPUT_PATH = DATA_DIR / "passages_enriched.json"

POLL_INTERVAL_SECONDS = 30
POLL_TIMEOUT_SECONDS = 3600


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    load_dotenv()
    manifest = json.loads(MANIFEST_PATH.read_text())
    batch_id = manifest["batch_id"]
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Poll until batch ends or timeout
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        batch = client.messages.batches.retrieve(batch_id)
        logger.info("Batch %s status: %s", batch_id, batch.processing_status)
        if batch.processing_status == "ended":
            break
        logger.info("Waiting %ds...", POLL_INTERVAL_SECONDS)
        time.sleep(POLL_INTERVAL_SECONDS)
    else:
        logger.error("Timed out after %ds waiting for batch %s", POLL_TIMEOUT_SECONDS, batch_id)
        return

    # Load raw passages for merging
    raw_passages = json.loads(PASSAGES_PATH.read_text())
    passages_by_key: dict[tuple[str, int], dict] = {}
    for p in raw_passages:
        passages_by_key[(p["chapter_id"], p["paragraph_index"])] = p

    # Collect results
    enriched: list[dict] = []
    failed_ids: list[str] = []
    succeeded = 0

    for entry in client.messages.batches.results(batch_id):
        custom_id = entry.custom_id
        if entry.result.type == "errored":
            error_msg = entry.result.error.error.message
            logger.warning("Request %s: errored — %s", custom_id, error_msg)
            failed_ids.append(custom_id)
            continue
        if entry.result.type != "succeeded":
            logger.warning("Request %s: %s", custom_id, entry.result.type)
            failed_ids.append(custom_id)
            continue

        # Extract text content from the message
        message = entry.result.message
        content_text = ""
        for block in message.content:
            if block.type == "text":
                content_text = block.text
                break

        if not content_text:
            logger.warning("Request %s: no text content", custom_id)
            failed_ids.append(custom_id)
            continue

        if message.stop_reason != "end_turn":
            logger.warning(
                "Request %s: stop_reason=%s (likely truncated)",
                custom_id,
                message.stop_reason,
            )
            failed_ids.append(custom_id)
            continue

        try:
            result = ChapterEnrichmentResult.model_validate_json(content_text)
        except Exception:
            logger.warning("Request %s: failed to parse response", custom_id)
            failed_ids.append(custom_id)
            continue
        succeeded += 1

        for pe in result.enrichments:
            key = (result.chapter_id, pe.paragraph_index)
            raw = passages_by_key.get(key)
            if raw is None:
                logger.warning(
                    "No raw passage for %s:p%d", result.chapter_id, pe.paragraph_index
                )
                continue

            passage = Passage(**{**raw, "enrichment": pe.enrichment})
            enriched.append(passage.model_dump())

    OUTPUT_PATH.write_text(json.dumps(enriched, indent=2))
    logger.info(
        "Collected %d enriched passages from %d succeeded requests",
        len(enriched),
        succeeded,
    )
    if failed_ids:
        logger.warning("Failed request IDs: %s", failed_ids)

    # Update manifest
    manifest["status"] = "collected"
    manifest["succeeded"] = succeeded
    manifest["failed_ids"] = failed_ids
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
