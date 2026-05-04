"""Collect context generation batch results and merge into passages.

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
    contexts_path = novel_dir / "contexts.json"
    passages_path = novel_dir / "passages_enriched.json"
    output_path = novel_dir / "passages_contextual.json"

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
        logger.warning("Batch not yet complete — results may be partial")

    # Load existing contexts (for merging with partial results)
    contexts: dict[str, str] = {}
    if contexts_path.exists():
        contexts = json.loads(contexts_path.read_text())

    # Collect results using the id_map from the manifest
    id_map = manifest.get("id_map", {})
    new_count = 0
    for result in client.messages.batches.results(batch_id):
        if result.result.type == "succeeded":
            pid = id_map.get(result.custom_id, result.custom_id)
            msg = result.result.message
            if msg.content and msg.content[0].type == "text":
                contexts[pid] = msg.content[0].text
                new_count += 1

    logger.info("Collected %d new contexts (%d total)", new_count, len(contexts))

    # Save contexts
    contexts_path.write_text(json.dumps(contexts, indent=2))

    # Merge into passages
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

    # Update manifest
    manifest["status"] = "collected"
    manifest["succeeded"] = new_count
    manifest_path.write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
