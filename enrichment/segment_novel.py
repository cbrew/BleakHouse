"""Segment a Gutenberg HTML novel into passages (paragraphs with IDs and offsets).

Handles four HTML structures found in Project Gutenberg:
  1. Anchor-based: <p><a id="cN"></p> (Bleak House, Our Mutual Friend)
  2. div.chapter with h3: Mill on the Floss
  3. div.chapter with h2: North and South
  4. Body-level h2: A Passage to India

Usage:
  uv run python -m enrichment.segment_novel --novel our_mutual_friend
  uv run python -m enrichment.segment_novel --novel mill_on_the_floss
  uv run python -m enrichment.segment_novel --novel north_and_south
  uv run python -m enrichment.segment_novel --novel passage_to_india
  uv run python -m enrichment.segment_novel --all
"""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import lxml.etree as etree

from enrichment.schemas import Passage

logger = logging.getLogger(__name__)

NOVELS_DIR = Path("data/novels")


@dataclass
class NovelConfig:
    key: str
    title: str
    author: str
    html_filename: str
    gutenberg_id: int
    # Optional overrides for novels without conventional chapter structure
    # (e.g. Mrs. Dalloway, a single-day stream of consciousness with no
    # chapter breaks). When `chunk_paragraphs` is set, the parser ignores
    # auto-detected structure and groups body <p>s into pseudo-chapters
    # of that size; `start_marker` / `end_marker` (substrings) skip
    # front-matter / end-matter (Gutenberg transcriber's note, etc.).
    chunk_paragraphs: int | None = None
    start_marker: str | None = None
    end_marker: str | None = None


NOVELS: dict[str, NovelConfig] = {
    "our_mutual_friend": NovelConfig(
        key="our_mutual_friend",
        title="Our Mutual Friend",
        author="Charles Dickens",
        html_filename="pg883-images.html",
        gutenberg_id=883,
    ),
    "mill_on_the_floss": NovelConfig(
        key="mill_on_the_floss",
        title="The Mill on the Floss",
        author="George Eliot",
        html_filename="pg6688-images.html",
        gutenberg_id=6688,
    ),
    "north_and_south": NovelConfig(
        key="north_and_south",
        title="North and South",
        author="Elizabeth Gaskell",
        html_filename="pg4276-images.html",
        gutenberg_id=4276,
    ),
    "passage_to_india": NovelConfig(
        key="passage_to_india",
        title="A Passage to India",
        author="E. M. Forster",
        html_filename="pg61221-images.html",
        gutenberg_id=61221,
    ),
    # --- New novels for generalization study ---
    "hard_times": NovelConfig(
        key="hard_times",
        title="Hard Times",
        author="Charles Dickens",
        html_filename="pg786-images.html",
        gutenberg_id=786,
    ),
    "middlemarch": NovelConfig(
        key="middlemarch",
        title="Middlemarch",
        author="George Eliot",
        html_filename="pg145-images.html",
        gutenberg_id=145,
    ),
    "daniel_deronda": NovelConfig(
        key="daniel_deronda",
        title="Daniel Deronda",
        author="George Eliot",
        html_filename="pg7469-images.html",
        gutenberg_id=7469,
    ),
    "david_copperfield": NovelConfig(
        key="david_copperfield",
        title="David Copperfield",
        author="Charles Dickens",
        html_filename="pg766-images.html",
        gutenberg_id=766,
    ),
    "cranford": NovelConfig(
        key="cranford",
        title="Cranford",
        author="Elizabeth Gaskell",
        html_filename="pg394-images.html",
        gutenberg_id=394,
    ),
    "no_name": NovelConfig(
        key="no_name",
        title="No Name",
        author="Wilkie Collins",
        html_filename="pg1438-images.html",
        gutenberg_id=1438,
    ),
    "new_grub_street": NovelConfig(
        key="new_grub_street",
        title="New Grub Street",
        author="George Gissing",
        html_filename="pg1709-images.html",
        gutenberg_id=1709,
    ),
    "odd_women": NovelConfig(
        key="odd_women",
        title="The Odd Women",
        author="George Gissing",
        html_filename="pg4313-images.html",
        gutenberg_id=4313,
    ),
    "miss_marjoribanks": NovelConfig(
        key="miss_marjoribanks",
        title="Miss Marjoribanks",
        author="Mrs Oliphant",
        html_filename="pg41286-images.html",
        gutenberg_id=41286,
    ),
    "hester": NovelConfig(
        key="hester",
        title="Hester",
        author="Mrs Oliphant",
        html_filename="hester_combined.html",
        gutenberg_id=48197,
    ),
    "room_with_a_view": NovelConfig(
        key="room_with_a_view",
        title="A Room with a View",
        author="E. M. Forster",
        html_filename="pg2641-images.html",
        gutenberg_id=2641,
    ),
    "oliver_twist": NovelConfig(
        key="oliver_twist",
        title="Oliver Twist",
        author="Charles Dickens",
        html_filename="pg730-images.html",
        gutenberg_id=730,
    ),
    "mrs_dalloway": NovelConfig(
        key="mrs_dalloway",
        title="Mrs. Dalloway",
        author="Virginia Woolf",
        html_filename="pg71865-images.html",
        gutenberg_id=71865,
        # Single-day stream of consciousness with no chapter structure.
        # Chunk body <p>s into ~120 pseudo-sections (~10 per "hour" across
        # the novel's 12-hour span). Skip front-matter (title page,
        # copyright, dedication) until the famous opening line.
        chunk_paragraphs=7,
        start_marker="Mrs. Dalloway said she would buy",
        end_marker="Minor punctuation errors",
    ),
}


def _is_chapter_heading(text: str) -> bool:
    """Check if text looks like a chapter heading (not a book/part heading)."""
    t = text.strip().upper()
    return bool(re.match(r"CHAPTER\s+[IVXLC\d]+", t))


def _make_chapter_id(index: int) -> str:
    """Generate a chapter ID like c1, c2, ..."""
    return f"c{index}"


def _extract_paragraphs(elements: list) -> list[str]:
    """Extract paragraph texts from a list of lxml elements."""
    paragraphs: list[str] = []
    for elem in elements:
        if elem.tag == "p":
            text = " ".join(elem.itertext()).strip()
            # Skip very short paragraphs that are likely decorative
            if text and len(text) > 2:
                paragraphs.append(text)
    return paragraphs


def parse_anchor_based(tree: etree._Element) -> list[dict]:
    """Parse novels using <p><a id="..."></p> chapter markers (Dickens on Gutenberg).

    Filters to only chapter anchors (link2HCH...), skipping book/part anchors.
    """
    anchors = tree.xpath("//p[a[@id]]")
    chapters: list[dict] = []
    chapter_num = 0

    for anchor in anchors:
        anchor_id = anchor[0].attrib.get("id", "")
        # Only process chapter anchors, not book/part markers
        if not anchor_id.startswith("link2HCH"):
            continue

        chapter_num += 1
        title = ""
        paragraphs: list[str] = []

        following = anchor.xpath("./following-sibling::*")
        for elem in following:
            # Stop at next anchor
            if elem.xpath("./a[@id]"):
                break
            if elem.tag in ("h2", "h3", "h4"):
                # Prefer h3 (chapter title) over h2 (chapter number)
                candidate = "".join(elem.itertext()).strip()
                if elem.tag == "h3":
                    title = candidate
                elif not title and not _is_chapter_heading(candidate):
                    title = candidate
            elif elem.tag == "p":
                text = " ".join(elem.itertext()).strip()
                if text and len(text) > 2:
                    paragraphs.append(text)

        if paragraphs:
            chapters.append(
                {
                    "id": _make_chapter_id(chapter_num),
                    "title": title,
                    "paragraphs": paragraphs,
                }
            )

    return chapters


def parse_div_chapter(tree: etree._Element, heading_tag: str = "h3") -> list[dict]:  # noqa: ARG001
    """Parse novels using <div class="chapter"> containers.

    Used by Mill on the Floss (h3 headings) and North and South (h2 headings).
    """
    divs = tree.xpath('//div[@class="chapter"]')
    chapters: list[dict] = []
    chapter_num = 0

    for div in divs:
        children = list(div)
        # Find the heading
        title = ""
        for child in children:
            if child.tag in ("h2", "h3", "h4"):
                raw = "".join(child.itertext()).strip()
                # Extract chapter title: strip "CHAPTER X." prefix
                lines = raw.split("\n")
                if len(lines) > 1:
                    # Title is usually the second line
                    title = lines[1].strip()
                elif not _is_chapter_heading(raw):
                    title = raw

        # For div.chapter, paragraphs may be inside the div or siblings after it
        paragraphs = _extract_paragraphs(children)

        # If no paragraphs inside div, collect siblings until next div.chapter
        if not paragraphs:
            parent = div.getparent()
            if parent is not None:
                sibs = list(parent)
                idx = sibs.index(div)
                for sib in sibs[idx + 1 :]:
                    if (
                        sib.tag == "div"
                        and sib.attrib.get("class") == "chapter"
                    ):
                        break
                    if sib.tag == "h2" and _is_chapter_heading(
                        "".join(sib.itertext()).strip()
                    ):
                        break
                    if sib.tag == "p":
                        text = " ".join(sib.itertext()).strip()
                        if text and len(text) > 2:
                            paragraphs.append(text)
                    elif sib.tag == "div" and sib.attrib.get("class") == "poetry":
                        # Include poetry blocks as paragraphs
                        text = " ".join(sib.itertext()).strip()
                        if text and len(text) > 2:
                            paragraphs.append(text)

        if paragraphs:
            chapter_num += 1
            chapters.append(
                {
                    "id": _make_chapter_id(chapter_num),
                    "title": title,
                    "paragraphs": paragraphs,
                }
            )

    return chapters


def parse_body_headings(tree: etree._Element, heading_tag: str = "h2") -> list[dict]:
    """Parse novels with chapter headings directly in body.

    Used by A Passage to India (h2), Hard Times (h3), Miss Marjoribanks (h2),
    Hester (h2).  Collects <p> elements between consecutive chapter headings.
    """
    body = tree.xpath("//body")[0]
    children = list(body)

    # Find all chapter heading indices
    chapter_starts: list[tuple[int, str]] = []
    current_part = ""
    for i, elem in enumerate(children):
        if elem.tag == heading_tag:
            text = "".join(elem.itertext()).strip()
            if text.upper().startswith(("PART", "BOOK THE", "BOOK I", "BOOK II", "BOOK III")):
                current_part = text
            elif _is_chapter_heading(text):
                chapter_starts.append((i, current_part))

    chapters: list[dict] = []
    for idx, (start_i, part) in enumerate(chapter_starts):
        # End is next chapter start or end of children
        end_i = (
            chapter_starts[idx + 1][0]
            if idx + 1 < len(chapter_starts)
            else len(children)
        )

        heading_text = "".join(children[start_i].itertext()).strip()
        # Extract title: strip "CHAPTER X" prefix, use remaining text
        lines = heading_text.split("\n")
        title = lines[1].strip() if len(lines) > 1 else ""
        if not title:
            title = part if part else heading_text

        paragraphs: list[str] = []
        for elem in children[start_i + 1 : end_i]:
            if elem.tag == "p":
                text = " ".join(elem.itertext()).strip()
                if text and len(text) > 2:
                    paragraphs.append(text)
            elif elem.tag in ("h2", "h3") and _is_chapter_heading(
                "".join(elem.itertext()).strip()
            ):
                # Next chapter heading — stop
                break

        if paragraphs:
            chapters.append(
                {
                    "id": _make_chapter_id(len(chapters) + 1),
                    "title": title,
                    "paragraphs": paragraphs,
                }
            )

    return chapters


def parse_chunked(
    tree: etree._Element,
    *,
    chunk_size: int,
    start_marker: str | None,
    end_marker: str | None = None,
) -> list[dict]:
    """Parse a novel without conventional chapter structure by chunking
    body <p>s into fixed-size pseudo-chapters.

    `start_marker` (substring) drops paragraphs until one contains it,
    skipping title page / copyright / dedication front-matter. The
    paragraph containing the marker is itself kept as the first body
    paragraph. `end_marker` is symmetric: collection stops as soon as a
    paragraph contains it (useful for stripping transcriber's notes).
    """
    paragraphs = tree.xpath("//body//p")
    texts: list[str] = []
    started = start_marker is None
    for p in paragraphs:
        text = " ".join(p.itertext()).strip()
        if not text or len(text) <= 2:
            continue
        if not started:
            if start_marker is not None and start_marker in text:
                started = True
            else:
                continue
        if end_marker is not None and end_marker in text:
            break
        texts.append(text)

    if not texts:
        suffix = f" after marker {start_marker!r}" if start_marker else ""
        raise ValueError(f"chunked parser found no body paragraphs{suffix}")

    chapters: list[dict] = []
    for i in range(0, len(texts), chunk_size):
        chunk = texts[i : i + chunk_size]
        chapter_num = (i // chunk_size) + 1
        chapters.append(
            {
                "id": _make_chapter_id(chapter_num),
                "title": f"Section {chapter_num}",
                "paragraphs": chunk,
            }
        )
    return chapters


def detect_and_parse(html_path: Path) -> list[dict]:
    """Auto-detect HTML structure and parse chapters."""
    html_content = html_path.read_text()
    tree = etree.HTML(html_content)

    # Strategy 1: anchor-based (Dickens)
    anchors = tree.xpath("//p[a[@id]]")
    chapter_anchors = [
        a for a in anchors if a[0].attrib.get("id", "").startswith("link2HCH")
    ]
    if chapter_anchors:
        logger.info("Detected anchor-based structure (%d chapters)", len(chapter_anchors))
        return parse_anchor_based(tree)

    # Strategy 2: div.chapter (only if divs actually contain content)
    chapter_divs = tree.xpath('//div[@class="chapter"]')
    non_empty_divs = [d for d in chapter_divs if len(list(d)) > 0]
    if non_empty_divs:
        # Check if chapters use h3 (Mill) or h2 (North and South)
        first_div = non_empty_divs[0]
        has_h3 = bool(first_div.xpath(".//h3"))
        tag = "h3" if has_h3 else "h2"
        logger.info(
            "Detected div.chapter structure (%d divs, %s headings)",
            len(non_empty_divs),
            tag,
        )
        return parse_div_chapter(tree, heading_tag=tag)

    # Strategy 3: body-level H2 chapters
    h2s = tree.xpath("//h2")
    chapter_h2s = [
        h for h in h2s if _is_chapter_heading("".join(h.itertext()).strip())
    ]
    if chapter_h2s:
        logger.info("Detected body-level H2 structure (%d chapters)", len(chapter_h2s))
        return parse_body_headings(tree, heading_tag="h2")

    # Strategy 4: body-level H3 chapters (Hard Times)
    h3s = tree.xpath("//h3")
    chapter_h3s = [
        h for h in h3s if _is_chapter_heading("".join(h.itertext()).strip())
    ]
    if chapter_h3s:
        logger.info("Detected body-level H3 structure (%d chapters)", len(chapter_h3s))
        return parse_body_headings(tree, heading_tag="h3")

    raise ValueError(f"Could not detect chapter structure in {html_path}")


def _split_paragraph(text: str, max_words: int) -> list[str]:
    """Split a long paragraph at sentence boundaries to stay under max_words."""
    if len(text.split()) <= max_words:
        return [text]

    # Split at sentence boundaries: period/exclamation/question followed by
    # whitespace and an uppercase letter or opening quote.
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'\u2018\u201C])", text)

    chunks: list[str] = []
    current: list[str] = []
    current_wc = 0

    for sent in sentences:
        sent_wc = len(sent.split())
        if current_wc + sent_wc > max_words and current:
            chunks.append(" ".join(current))
            current = [sent]
            current_wc = sent_wc
        else:
            current.append(sent)
            current_wc += sent_wc

    if current:
        chunks.append(" ".join(current))

    return chunks if chunks else [text]


def segment_chapter(
    chapter: dict, *, max_words: int | None = None,
) -> list[Passage]:
    """Convert a chapter's paragraphs into Passage objects with offsets.

    If *max_words* is set, long paragraphs are split at sentence boundaries
    so that each resulting passage stays close to *max_words* words.
    """
    chapter_id = chapter["id"]
    chapter_title = chapter.get("title", "")
    paragraphs: list[str] = chapter["paragraphs"]

    # Optionally split long paragraphs
    if max_words is not None:
        split_paras: list[str] = []
        for para in paragraphs:
            split_paras.extend(_split_paragraph(para, max_words))
        paragraphs = split_paras

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


def segment_novel(novel_key: str, *, max_words: int | None = None) -> None:
    """Segment a novel into passages and write to JSON."""
    config = NOVELS[novel_key]
    novel_dir = NOVELS_DIR / config.key
    html_path = novel_dir / config.html_filename
    output_path = novel_dir / "passages_raw.json"

    if not html_path.exists():
        raise FileNotFoundError(
            f"HTML not found at {html_path}. "
            f"Download from https://www.gutenberg.org/ebooks/{config.gutenberg_id}"
        )

    logger.info("Parsing %s from %s", config.title, html_path)
    if max_words:
        logger.info("Splitting long paragraphs at ~%d words", max_words)

    if config.chunk_paragraphs is not None:
        logger.info(
            "Using chunked strategy (%d paragraphs/section, start_marker=%r)",
            config.chunk_paragraphs, config.start_marker,
        )
        tree = etree.HTML(html_path.read_text())
        chapters = parse_chunked(
            tree,
            chunk_size=config.chunk_paragraphs,
            start_marker=config.start_marker,
            end_marker=config.end_marker,
        )
    else:
        chapters = detect_and_parse(html_path)
    logger.info("Found %d chapters", len(chapters))

    all_passages: list[dict] = []
    for chapter in chapters:
        passages = segment_chapter(chapter, max_words=max_words)
        logger.info(
            "  %s (%s): %d paragraphs",
            chapter["id"],
            chapter.get("title", "?")[:40],
            len(passages),
        )
        all_passages.extend(p.model_dump() for p in passages)

    output_path.write_text(json.dumps(all_passages, indent=2))
    logger.info(
        "Wrote %d passages to %s (%s by %s)",
        len(all_passages),
        output_path,
        config.title,
        config.author,
    )


def main() -> None:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Segment Gutenberg novels into passages")
    parser.add_argument(
        "--novel",
        choices=list(NOVELS.keys()),
        help="Which novel to segment",
    )
    parser.add_argument("--all", action="store_true", help="Segment all novels")
    parser.add_argument(
        "--max-words",
        type=int,
        default=None,
        help="Split paragraphs longer than this at sentence boundaries",
    )
    args = parser.parse_args()

    if args.all:
        for key in NOVELS:
            segment_novel(key, max_words=args.max_words)
    elif args.novel:
        segment_novel(args.novel, max_words=args.max_words)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
