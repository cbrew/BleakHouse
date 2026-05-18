"""Segment chapter text into paragraphs with IDs and character offsets.

Parses the Gutenberg HTML directly so each <p> tag becomes one passage,
preserving true paragraph boundaries.

Usage: uv run python -m enrichment.segment
"""

import json
import logging
from pathlib import Path

import lxml.etree as etree

from enrichment.passage import Passage

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
OUTPUT_PATH = DATA_DIR / "passages_raw.json"
HTML_PATH = DATA_DIR / "pg1023-images.html"
HTML_ZIP_URL = "https://www.gutenberg.org/cache/epub/1023/pg1023-h.zip"


def ensure_html() -> Path:
    """Ensure the Gutenberg HTML file exists, downloading if needed."""
    if HTML_PATH.exists():
        return HTML_PATH

    import io
    import zipfile

    import requests

    logger.info("Downloading Gutenberg HTML from %s", HTML_ZIP_URL)
    r = requests.get(HTML_ZIP_URL)
    z = zipfile.ZipFile(io.BytesIO(r.content))
    z.extractall(str(DATA_DIR))

    # Find the extracted HTML file
    for name in z.namelist():
        if name.endswith(".html") or name.endswith(".htm"):
            extracted = DATA_DIR / name
            if extracted.exists():
                return extracted

    raise FileNotFoundError("No HTML file found in Gutenberg zip")


def parse_chapters(html_path: Path) -> list[dict]:
    """Parse chapters from Gutenberg HTML, keeping each <p> as a paragraph.

    Returns a list of chapter dicts with keys:
        id, book_title, title, paragraphs (list of paragraph text strings)
    """
    html_content = html_path.read_text()
    tree = etree.HTML(html_content)
    book_title = tree.xpath("//head/title")[0].text or ""

    # Chapter boundaries are <p><a id="cN"></p> elements
    anchors = tree.xpath("//p[a[@id]]")
    chapters: list[dict] = []

    for anchor in anchors:
        chapter_id = anchor[0].attrib["id"]
        title = ""
        paragraphs: list[str] = []

        following_elements = anchor.xpath("./following-sibling::*")
        for element in following_elements:
            # Stop at the next chapter anchor
            if element.xpath("./a[@id]"):
                break

            if element.tag in ("h2", "h3", "h4"):
                title = "".join(element.itertext()).strip()
            elif element.tag == "p":
                text = " ".join(element.itertext()).strip()
                if text:
                    paragraphs.append(text)

        if title or paragraphs:
            chapters.append(
                {
                    "id": chapter_id,
                    "book_title": book_title,
                    "title": title,
                    "paragraphs": paragraphs,
                }
            )

    return chapters


def segment_chapter(chapter: dict) -> list[Passage]:
    """Convert a chapter's paragraphs into Passage objects with offsets."""
    chapter_id = chapter["id"]
    chapter_title = chapter.get("title", "")
    paragraphs: list[str] = chapter["paragraphs"]

    # Reconstruct full text to compute char offsets
    full_text = "\n\n".join(paragraphs)
    passages: list[Passage] = []
    char_offset = 0

    for idx, para_text in enumerate(paragraphs):
        char_start = full_text.index(para_text, char_offset)
        char_end = char_start + len(para_text)

        passages.append(
            Passage(
                passage_id=f"{chapter_id}:p{idx}",
                chapter_id=chapter_id,
                chapter_title=chapter_title,
                paragraph_index=idx,
                char_start=char_start,
                char_end=char_end,
                text=para_text,
            )
        )
        char_offset = char_end

    return passages


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    DATA_DIR.mkdir(exist_ok=True)

    html_path = ensure_html()
    logger.info("Parsing HTML from %s", html_path)

    chapters = parse_chapters(html_path)
    logger.info("Got %d chapters", len(chapters))

    all_passages: list[dict] = []
    for chapter in chapters:
        passages = segment_chapter(chapter)
        logger.info(
            "Chapter %s (%s): %d paragraphs",
            chapter["id"],
            chapter.get("title", "?"),
            len(passages),
        )
        all_passages.extend(p.model_dump() for p in passages)

    OUTPUT_PATH.write_text(json.dumps(all_passages, indent=2))
    logger.info("Wrote %d passages to %s", len(all_passages), OUTPUT_PATH)


if __name__ == "__main__":
    main()
