"""Build and submit an OpenAI Batch job for passage enrichment.

Parallels enrichment/submit_passages_enriched.py (the Anthropic Batch
path), with these differences:

  - Uses OpenAI Batch API + Responses endpoint (/v1/responses).
    Responses gives gpt-5 family separate reasoning + visible-output
    budgets, avoiding the budget-conflation trap we hit in Stage 1
    of the OpenAI execution plan (docs/openai_execution_plan.md).
  - Writes a JSONL file with per-line `body` parameters matching the
    sync Responses API request shape.
  - Uploads via client.files.create(purpose="batch"), then submits
    via client.batches.create with endpoint="/v1/responses".

Per OpenAI's documented JSONL shape, each line is:
  {"custom_id": "...", "method": "POST", "url": "/v1/responses",
   "body": {model, input, text:{format}, reasoning:{effort},
            max_output_tokens}}

Usage:
  uv run python -m enrichment.submit_passages_enriched_openai --novel bleak_house
  uv run python -m enrichment.submit_passages_enriched_openai --novel bleak_house --chapters c1,c2

Reads passages from data/novels/<key>/passages_raw.json if present;
falls back to passages_enriched.json (text + chapter_id + paragraph_index
are all that's needed; existing enrichment is ignored).

Writes data/novels/<key>/batch_manifest.openai.json with batch_id and
metadata. Collector picks it up.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import openai
from dotenv import load_dotenv

from enrichment.novel_prompts import NOVEL_CONFIGS, build_enrichment_prompt
from enrichment.llm.schemas import ChapterEnrichmentResult
from enrichment.submit_passages_enriched import format_chapter_text

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
NOVEL_KEYS = sorted(NOVEL_CONFIGS.keys())

# gpt-5-mini on Responses API. Stage 1 budget-conflation trap means
# we always pass reasoning.effort="minimal" + a generous
# max_output_tokens cap (visible output only, no reasoning overlap).
DEFAULT_MODEL = "gpt-5-mini"
DEFAULT_REASONING_EFFORT = "minimal"
DEFAULT_MAX_OUTPUT_TOKENS = 50000  # Stage 1 long-tier chapter emitted ~45k visible

# Per-request paragraph chunk size. The 2026-05-15 full-novel run with
# reasoning.effort=minimal showed contiguous-prefix truncation on long
# chapters (e.g. c21 with 168 paragraphs emitted enrichments for only
# the first 14). Empirically chunks up to ~60 paragraphs survive; 20 is
# a conservative safety margin. BleakHouse-7ng9 tracks the remediation.
# Override with --chunk-size at the CLI.
DEFAULT_CHUNK_SIZE = 20


def _read_passages(novel_dir: Path) -> list[dict]:
    """Prefer passages_raw.json; fall back to the enriched file's text
    fields. Bleak House (and possibly others) don't have raw checked
    in but have enriched data with the text preserved."""
    raw_path = novel_dir / "passages_raw.json"
    if raw_path.exists():
        return json.loads(raw_path.read_text())
    enriched_path = novel_dir / "passages_enriched.json"
    if not enriched_path.exists():
        raise FileNotFoundError(
            f"Neither {raw_path} nor {enriched_path} found. "
            "Need passages_raw.json or passages_enriched.json under "
            "the novel directory."
        )
    data = json.loads(enriched_path.read_text())
    # Strip enrichment field so the rest of the script sees raw-shape
    # records. The text + chapter_id + paragraph_index + chapter_title
    # fields are what we need.
    out = []
    for p in data:
        rec = {k: v for k, v in p.items() if k != "enrichment"}
        out.append(rec)
    return out


def build_jsonl_line(
    *,
    custom_id: str,
    chapter_id: str,
    chapter_title: str,
    chunk: list[dict],
    system_prompt: str,
    schema: dict,
    model: str,
    reasoning_effort: str,
    max_output_tokens: int,
) -> dict:
    """Build one JSONL line for the batch input file.

    Responses API request shape (per OpenAI docs):
      - `model`: model id
      - `input`: list of messages with role/content; we put the
        novel-specific system prompt as a system-role message and
        the chapter content as a user-role message.
      - `text.format` = {"type": "json_schema", "name": "...",
        "schema": {...}, "strict": True} — constrains the visible
        output.
      - `reasoning.effort` = "minimal" — gpt-5 family separate
        reasoning budget; "minimal" suppresses most internal
        deliberation for structured-extraction tasks.
      - `max_output_tokens` = visible-output cap. Reasoning tokens
        are budgeted separately.
    """
    formatted = format_chapter_text(chunk)
    user_message = f"Chapter: {chapter_id} - {chapter_title}\n\n{formatted}"
    return {
        "custom_id": custom_id,
        "method": "POST",
        "url": "/v1/responses",
        "body": {
            "model": model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "ChapterEnrichmentResult",
                    "schema": schema,
                    "strict": True,
                },
            },
            "reasoning": {"effort": reasoning_effort},
            "max_output_tokens": max_output_tokens,
        },
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--novel",
        type=str,
        choices=NOVEL_KEYS,
        required=True,
        help="Novel key (reads from data/novels/<key>/).",
    )
    parser.add_argument(
        "--chapters",
        type=str,
        default=None,
        help="Comma-separated chapter IDs to submit (default: all).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"OpenAI model id (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--reasoning-effort",
        type=str,
        default=DEFAULT_REASONING_EFFORT,
        choices=["minimal", "low", "medium", "high"],
        help=(
            f"Responses API reasoning.effort (default: "
            f"{DEFAULT_REASONING_EFFORT})."
        ),
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=DEFAULT_MAX_OUTPUT_TOKENS,
        help=(
            f"Per-request visible-output cap (default: "
            f"{DEFAULT_MAX_OUTPUT_TOKENS})."
        ),
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help=(
            f"Paragraphs per batch request (default: {DEFAULT_CHUNK_SIZE}). "
            "Smaller chunks reduce the early-termination loss seen with "
            "reasoning.effort=minimal on long chapters."
        ),
    )
    args = parser.parse_args()

    novel_dir = DATA_DIR / "novels" / args.novel
    manifest_path = novel_dir / "batch_manifest.openai.json"
    jsonl_path = novel_dir / "batch_input.openai.jsonl"
    system_prompt = build_enrichment_prompt(args.novel)
    logger.info("Using novel-specific prompt for %s", args.novel)

    load_dotenv()
    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    raw_passages = _read_passages(novel_dir)
    passages_by_chapter: dict[str, list[dict]] = {}
    for p in raw_passages:
        passages_by_chapter.setdefault(p["chapter_id"], []).append(p)
    for ch_list in passages_by_chapter.values():
        ch_list.sort(key=lambda x: x["paragraph_index"])

    if args.chapters:
        selected = set(args.chapters.split(","))
        passages_by_chapter = {
            k: v for k, v in passages_by_chapter.items() if k in selected
        }
        logger.info("Filtered to chapters: %s", sorted(passages_by_chapter))

    schema = ChapterEnrichmentResult.model_json_schema()
    lines: list[dict] = []

    for chapter_id, passages in sorted(passages_by_chapter.items()):
        # Uniform fixed-size chunking: split each chapter into chunks of
        # at most args.chunk_size paragraphs. Earlier binary-split logic
        # left long chapters in single requests, which triggered
        # contiguous-prefix truncation under reasoning.effort=minimal
        # (BleakHouse-7ng9).
        cs = args.chunk_size
        chunks: list[list[dict]] = [
            passages[i:i + cs] for i in range(0, len(passages), cs)
        ]

        chapter_title = passages[0].get("chapter_title", "")
        for chunk_idx, chunk in enumerate(chunks):
            custom_id = f"enrich-{chapter_id}"
            if len(chunks) > 1:
                custom_id += f"-part{chunk_idx}"
            line = build_jsonl_line(
                custom_id=custom_id,
                chapter_id=chapter_id,
                chapter_title=chapter_title,
                chunk=chunk,
                system_prompt=system_prompt,
                schema=schema,
                model=args.model,
                reasoning_effort=args.reasoning_effort,
                max_output_tokens=args.max_output_tokens,
            )
            lines.append(line)

    jsonl_text = "\n".join(json.dumps(line) for line in lines) + "\n"
    jsonl_path.write_text(jsonl_text)
    logger.info(
        "Wrote %d requests to %s (%d bytes)",
        len(lines), jsonl_path, len(jsonl_text),
    )

    # Upload + submit
    logger.info("Uploading batch input file...")
    with open(jsonl_path, "rb") as f:
        file_resp = client.files.create(file=f, purpose="batch")
    logger.info("File id: %s", file_resp.id)

    batch = client.batches.create(
        input_file_id=file_resp.id,
        endpoint="/v1/responses",
        completion_window="24h",
        metadata={
            "novel": args.novel,
            "task": "passage_enrichment",
            "model": args.model,
        },
    )

    manifest = {
        "batch_id": batch.id,
        "input_file_id": file_resp.id,
        "novel": args.novel,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "request_count": len(lines),
        "chapter_ids": sorted(passages_by_chapter.keys()),
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "max_output_tokens": args.max_output_tokens,
        "endpoint": "/v1/responses",
        "status": "submitted",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    logger.info("Batch %s submitted (%d requests)", batch.id, len(lines))
    logger.info("Manifest saved to %s", manifest_path)


if __name__ == "__main__":
    main()
