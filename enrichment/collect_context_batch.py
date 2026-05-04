"""Collect context generation batch results and merge into passages.

Idempotency: writes data/novels/<novel>/passages_contextual.json once
on success. If that output already exists, the script is a no-op
(refuses to overwrite). Delete the output file to re-collect.

Usage:
    uv run python -m enrichment.collect_context_batch --novel hard_times
"""

import argparse
import json
import logging
import os
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from enrichment.axes import NOVEL_IDS  # canonical source of novel directory ids

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(
        description="Collect context batch results"
    )
    parser.add_argument(
        "--novel", required=True, choices=sorted(NOVEL_IDS), help="Novel key"
    )
    args = parser.parse_args()

    novel_dir = DATA_DIR / "novels" / args.novel
    manifest_path = novel_dir / "context_batch_manifest.json"
    passages_path = novel_dir / "passages_enriched.json"
    output_path = novel_dir / "passages_contextual.json"

    if output_path.exists():
        logger.info(
            "%s already exists; nothing to do. Delete it to re-collect.",
            output_path,
        )
        return

    load_dotenv()
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    manifest = json.loads(manifest_path.read_text())
    batch_id = manifest["batch_id"]

    batch = client.messages.batches.retrieve(batch_id)
    logger.info(
        "Batch %s: status=%s succeeded=%d errored=%d",
        batch_id,
        batch.processing_status,
        batch.request_counts.succeeded,
        batch.request_counts.errored,
    )

    if batch.processing_status != "ended":
        logger.info(
            "Batch still %s; nothing to collect yet. Re-run when "
            "processing_status == 'ended'.", batch.processing_status,
        )
        return

    # Collect results using the id_map from the manifest.
    contexts: dict[str, str] = {}
    id_map = manifest.get("id_map", {})
    for result in client.messages.batches.results(batch_id):
        if result.result.type == "succeeded":
            pid = id_map.get(result.custom_id, result.custom_id)
            msg = result.result.message
            if msg.content and msg.content[0].type == "text":
                contexts[pid] = msg.content[0].text

    logger.info("Collected %d contexts", len(contexts))

    # Merge into passages and write output once.
    passages = json.loads(passages_path.read_text())
    merged = 0
    for p in passages:
        pid = p["passage_id"]
        if pid in contexts:
            p["context"] = contexts[pid]
            merged += 1

    output_path.write_text(json.dumps(passages, indent=2))
    logger.info(
        "Merged %d contexts into %d passages → %s",
        merged, len(passages), output_path,
    )

    # Update manifest with terminal status.
    manifest["status"] = "collected"
    manifest["succeeded"] = len(contexts)
    manifest_path.write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
