"""Embed contextualized passages into LanceDB for vector search.

Usage:
    uv run python -m enrichment.embed_passages [--db-path data/bleak_house_vectors]
"""

import argparse
import json
import logging
from pathlib import Path

import lancedb
from dotenv import load_dotenv

from enrichment.retrieval_schema import ContextualPassage

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
INPUT_PATH = DATA_DIR / "passages_contextual.json"
DEFAULT_DB_PATH = DATA_DIR / "bleak_house_vectors"

NOVEL_KEYS = [
    "our_mutual_friend",
    "mill_on_the_floss",
    "north_and_south",
    "passage_to_india",
    "hard_times",
    "middlemarch",
    "daniel_deronda",
    "david_copperfield",
    "cranford",
    "no_name",
    "new_grub_street",
    "odd_women",
    "miss_marjoribanks",
    "hester",
]

BATCH_SIZE = 500


def build_embedding_input(passage: dict) -> str:
    """Compose the text that gets embedded: context + text + metadata."""
    enrichment = passage.get("enrichment") or {}
    context = passage.get("context", "")
    text = passage.get("text", "")
    characters = ", ".join(enrichment.get("characters_present", []))
    themes = ", ".join(enrichment.get("themes", []))
    summary = enrichment.get("summary", "")

    parts = []
    if context:
        parts.append(context)
    parts.append(text)
    if characters:
        parts.append(f"Characters: {characters}")
    if themes:
        parts.append(f"Themes: {themes}")
    if summary:
        parts.append(f"Summary: {summary}")

    return "\n\n".join(parts)


def passage_to_record(passage: dict) -> dict:
    """Convert a passage dict to a ContextualPassage-compatible record."""
    enrichment = passage.get("enrichment") or {}
    return {
        "passage_id": passage["passage_id"],
        "chapter_id": passage["chapter_id"],
        "chapter_title": passage.get("chapter_title", ""),
        "paragraph_index": passage["paragraph_index"],
        "narrator": enrichment.get("narrator", "unknown"),
        "interest_score": enrichment.get("interest_score", 0),
        "themes": ", ".join(enrichment.get("themes", [])),
        "characters": ", ".join(enrichment.get("characters_present", [])),
        "summary": enrichment.get("summary", ""),
        "text": passage.get("text", ""),
        "context": passage.get("context", ""),
        "embedding_input": build_embedding_input(passage),
    }


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Embed contextualized passages into LanceDB"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help=f"LanceDB database path (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--novel",
        type=str,
        choices=NOVEL_KEYS,
        default=None,
        help="Novel key (reads from data/novels/<key>/)",
    )
    args = parser.parse_args()

    load_dotenv()

    if args.novel:
        novel_dir = DATA_DIR / "novels" / args.novel
        input_path = novel_dir / "passages_contextual.json"
        db_path = args.db_path or str(novel_dir / "vectors")
    else:
        input_path = INPUT_PATH
        db_path = args.db_path or str(DEFAULT_DB_PATH)

    raw = json.loads(input_path.read_text())
    logger.info("Loaded %d passages from %s", len(raw), input_path)

    # Filter to passages that have both enrichment and context
    passages = [p for p in raw if p.get("enrichment") and p.get("context")]
    logger.info("%d passages have enrichment + context", len(passages))

    records = [passage_to_record(p) for p in passages]

    db = lancedb.connect(db_path)
    table = db.create_table("passages", exist_ok=True, schema=ContextualPassage)

    for start in range(0, len(records), BATCH_SIZE):
        batch = records[start : start + BATCH_SIZE]
        table.add(batch)
        logger.info(
            "  Embedded batch %d-%d (%d records)",
            start,
            start + len(batch),
            len(batch),
        )

    logger.info(
        "Done: %d passages embedded into %s (table 'passages')",
        len(records),
        db_path,
    )


if __name__ == "__main__":
    main()
