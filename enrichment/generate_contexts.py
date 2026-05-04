"""Generate situating context for each passage using Haiku with prompt caching.

For each chapter, the full chapter text is sent as a cached system block,
then each passage is contextualized with a cheap user-message call.

NOTE: This uses synchronous, sequential API calls rather than the Batch API.
The Batch API does support prompt caching, but only on a best-effort basis —
because batch requests can be processed concurrently and in any order, cache
hits are not guaranteed. Sequential calls within a chapter guarantee the system
block stays hot in cache, giving reliable ~90% savings on the repeated chapter
text. The tradeoff is wall-clock time (~1-2 hours), but --resume makes that
painless. A batch approach could work (prime the cache with one request per
chapter, then submit the rest) but adds complexity for uncertain cache behavior.

Usage:
    uv run python -m enrichment.generate_contexts [--chapters c1,c2] [--resume]
"""

import argparse
import json
import logging
import os
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from enrichment.axes import NOVEL_IDS  # canonical source of novel directory ids
from enrichment.context_prompt import build_context_messages
from enrichment.submit_batch import format_chapter_text
from enrichment.timing import Recorder, time_model

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
PASSAGES_PATH = DATA_DIR / "passages_enriched.json"
CONTEXTS_PATH = DATA_DIR / "contexts.json"
OUTPUT_PATH = DATA_DIR / "passages_contextual.json"

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 300


def load_existing_contexts() -> dict[str, str]:
    """Load previously generated contexts for resumability."""
    if CONTEXTS_PATH.exists():
        return json.loads(CONTEXTS_PATH.read_text())
    return {}


def save_contexts(contexts: dict[str, str]) -> None:
    CONTEXTS_PATH.write_text(json.dumps(contexts, indent=2))


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Generate situating contexts for passages"
    )
    parser.add_argument(
        "--chapters",
        type=str,
        default=None,
        help="Comma-separated chapter IDs (default: all)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip chapters already in contexts.json",
    )
    parser.add_argument(
        "--novel",
        type=str,
        choices=sorted(NOVEL_IDS),
        default=None,
        help="Novel key (reads from data/novels/<key>/)",
    )
    args = parser.parse_args()

    # Resolve paths based on --novel
    if args.novel:
        novel_dir = DATA_DIR / "novels" / args.novel
        passages_path = novel_dir / "passages_enriched.json"
        contexts_path = novel_dir / "contexts.json"
        output_path = novel_dir / "passages_contextual.json"
    else:
        passages_path = PASSAGES_PATH
        contexts_path = CONTEXTS_PATH
        output_path = OUTPUT_PATH
        novel_dir = passages_path.parent

    load_dotenv()
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    raw = json.loads(passages_path.read_text())

    # Group by chapter
    by_chapter: dict[str, list[dict]] = {}
    for p in raw:
        by_chapter.setdefault(p["chapter_id"], []).append(p)

    if args.chapters:
        selected = set(args.chapters.split(","))
        by_chapter = {k: v for k, v in by_chapter.items() if k in selected}

    def _load_ctx() -> dict[str, str]:
        if contexts_path.exists():
            return json.loads(contexts_path.read_text())
        return {}

    def _save_ctx(ctx: dict[str, str]) -> None:
        contexts_path.write_text(json.dumps(ctx, indent=2))

    contexts = _load_ctx() if args.resume else {}
    logger.info(
        "Processing %d chapters (%d existing contexts)",
        len(by_chapter),
        len(contexts),
    )

    # Cost/time recorder for upstream passage enrichment. Sidecar lives
    # next to the passages it produced (per-novel, not per-run) — every
    # run that loads passages_enriched.json pays $0 for this step; the
    # spend is amortised across all runs of the novel.
    recorder = Recorder()
    timings_path = novel_dir / "passage_enrichment_timings.json"

    for chapter_id in sorted(by_chapter, key=_chapter_sort_key):
        passages = by_chapter[chapter_id]

        # Skip if all passages in this chapter already have contexts
        passage_ids = [p["passage_id"] for p in passages]
        if args.resume and all(pid in contexts for pid in passage_ids):
            logger.info("Skipping %s (already complete)", chapter_id)
            continue

        chapter_text = format_chapter_text(passages)
        logger.info(
            "Chapter %s: %d passages, ~%d chars",
            chapter_id,
            len(passages),
            len(chapter_text),
        )

        for i, passage in enumerate(passages):
            pid = passage["passage_id"]
            if args.resume and pid in contexts:
                continue

            system_blocks, user_msg = build_context_messages(
                chapter_text, passage["text"]
            )

            response = time_model(
                recorder,
                f"context {pid}",
                lambda: client.messages.create(
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    system=system_blocks,
                    messages=[{"role": "user", "content": user_msg}],
                ),
            )

            block = response.content[0]
            assert block.type == "text"
            contexts[pid] = block.text

            # Log caching stats
            usage = response.usage
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
            cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0
            if i == 0:
                logger.info(
                    "  %s: cache_create=%d cache_read=%d",
                    pid,
                    cache_create,
                    cache_read,
                )
            elif i == 1:
                logger.info(
                    "  %s: cache_create=%d cache_read=%d (should see cache hits)",
                    pid,
                    cache_create,
                    cache_read,
                )

        # Save after each chapter for resumability
        _save_ctx(contexts)
        timings_path.write_text(json.dumps(recorder.to_dict(), indent=2))
        logger.info(
            "  Saved %d total contexts; %d events to %s",
            len(contexts), len(recorder.events), timings_path,
        )

    # Merge contexts into passages and write output
    logger.info("Merging contexts into passages...")
    for p in raw:
        pid = p["passage_id"]
        if pid in contexts:
            p["context"] = contexts[pid]

    output_path.write_text(json.dumps(raw, indent=2))
    logger.info("Wrote %d passages to %s", len(raw), output_path)


def _chapter_sort_key(chapter_id: str) -> tuple[int, int]:
    """Sort chapter IDs: cP, c1, c2, ..., c67, F2, F3."""
    prefix = chapter_id[0]
    suffix = chapter_id[1:]
    if prefix == "c" and suffix.isdigit():
        return (1, int(suffix))
    elif prefix == "c":
        # cP (preface) etc — sort before numbered chapters
        return (0, 0)
    elif prefix == "F" and suffix.isdigit():
        return (2, int(suffix))
    return (3, 0)


if __name__ == "__main__":
    main()
