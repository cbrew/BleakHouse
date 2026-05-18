"""Link existing LiteraryElements to enriched passages via quote matching.

Usage: uv run python -m enrichment.join_elements
"""

import json
import logging
from pathlib import Path

from enrichment.passage import Passage

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
ENRICHED_PATH = DATA_DIR / "passages_enriched.json"
OUTPUT_PATH = DATA_DIR / "passages_with_elements.json"

# Minimum overlap ratio for a quote to match a passage
MATCH_THRESHOLD = 0.6


def normalize(text: str) -> str:
    """Lowercase and collapse whitespace for fuzzy matching."""
    return " ".join(text.lower().split())


def quote_matches_passage(quote: str, passage_text: str) -> bool:
    """Check if a quote appears (approximately) in a passage."""
    nq = normalize(quote)
    np = normalize(passage_text)

    # Exact substring
    if nq in np:
        return True

    # Check word overlap for fuzzy matching
    quote_words = set(nq.split())
    passage_words = set(np.split())
    if not quote_words:
        return False
    overlap = len(quote_words & passage_words) / len(quote_words)
    return overlap >= MATCH_THRESHOLD


def load_literary_elements(chapters: list[dict]) -> list[dict]:
    """Extract literary elements with their quotes from chapter schemas.

    Expects the chapter data to have a 'LiteraryElements' key from
    the existing ChapterSchema pipeline output.
    """
    elements: list[dict] = []
    for chapter in chapters:
        chapter_id = chapter.get("id", "")
        for i, elem in enumerate(chapter.get("LiteraryElements", [])):
            elem_id = f"{chapter_id}:le{i}"
            quotes = elem.get("Quotes", [])
            elements.append(
                {
                    "element_id": elem_id,
                    "chapter_id": chapter_id,
                    "quotes": quotes,
                    "type": elem.get("type", type(elem).__name__),
                }
            )
    return elements


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    enriched_data = json.loads(ENRICHED_PATH.read_text())
    passages = [Passage(**p) for p in enriched_data]

    # Try to load chapter schema outputs if they exist
    chapter_schemas_path = DATA_DIR / "chapter_schemas.json"
    if not chapter_schemas_path.exists():
        logger.warning(
            "%s not found. Skipping element linking. "
            "Run the literary analysis pipeline first to generate chapter schemas.",
            chapter_schemas_path,
        )
        # Just copy enriched to output
        OUTPUT_PATH.write_text(json.dumps(enriched_data, indent=2))
        return

    chapters = json.loads(chapter_schemas_path.read_text())
    elements = load_literary_elements(chapters)
    logger.info("Loaded %d literary elements", len(elements))

    # Index passages by chapter
    passages_by_chapter: dict[str, list[Passage]] = {}
    for p in passages:
        passages_by_chapter.setdefault(p.chapter_id, []).append(p)

    # Match quotes to passages
    total_links = 0
    for elem in elements:
        chapter_passages = passages_by_chapter.get(elem["chapter_id"], [])
        for quote in elem["quotes"]:
            for passage in chapter_passages:
                if quote_matches_passage(quote, passage.text):
                    if elem["element_id"] not in passage.literary_element_ids:
                        passage.literary_element_ids.append(elem["element_id"])
                        total_links += 1

    logger.info("Created %d passage-element links", total_links)

    output = [p.model_dump() for p in passages]
    OUTPUT_PATH.write_text(json.dumps(output, indent=2))
    logger.info("Wrote %d passages to %s", len(output), OUTPUT_PATH)


if __name__ == "__main__":
    main()
