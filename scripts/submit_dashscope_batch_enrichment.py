"""Submit one chapter of passage_enrichment to DashScope's OpenAI-Batch-API.

Companion to scripts/collect_dashscope_batch_enrichment.py. This script is
intentionally short: build the JSONL, upload, submit, write a manifest,
exit. Polling and result collection happen in the collector.

The Pydantic-generated schema for ChapterEnrichmentResult is *flattened*
(refs inlined, $defs removed) before submission — DashScope's strict
json_schema may not accept $defs/$refs, and inlining is cheaper than
finding out.

Tracks BleakHouse-el1j.1.

Run:
    uv run python scripts/submit_dashscope_batch_enrichment.py
    uv run python scripts/submit_dashscope_batch_enrichment.py \\
        --novel bleak_house --chapter c6
    uv run python scripts/submit_dashscope_batch_enrichment.py \\
        --novel north_and_south --chapter c6 --chunk-size 50

Then poll/collect:
    uv run python scripts/collect_dashscope_batch_enrichment.py \\
        data/runs/_qwen_plus_batch_enrichment_probe/bleak_house_c6
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from enrichment.novel_prompts import build_enrichment_prompt
from enrichment.llm.schemas import ChapterEnrichmentResult
from enrichment.submit_passages_enriched import format_chapter_text

logger = logging.getLogger("submit_dashscope_batch")

BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-plus"
DEFAULT_NOVEL = "bleak_house"
DEFAULT_CHAPTER = "c6"
DEFAULT_CHUNK_SIZE = 200
DEFAULT_MAX_COMPLETION_TOKENS = 32768
DEFAULT_TEMPERATURE = 0.0

PROBE_ROOT = Path("data/runs/_qwen_plus_batch_enrichment_probe")

# Probe-local prompt wrap. The shared build_enrichment_prompt doesn't
# mention JSON because the Anthropic seam enforces format at the API
# level regardless of prompt. DashScope's batch validator apparently
# relies on the prompt to set format expectation, so without this
# the model emits prose and DashScope rejects with
# ModelServingOutputInvalidJsonError. Avoid leaking Pydantic class
# names into the prompt — the model can't see them. (BleakHouse-el1j.1)
JSON_INSTRUCTION_SUFFIX = (
    "\n\n## Output format\n\n"
    "Respond with a single JSON object that conforms to the response "
    "schema. The schema is supplied separately. Do not include any prose, "
    "markdown fences, commentary, or chain-of-thought outside the JSON "
    "object — emit JSON only, starting with `{` and ending with `}`."
)


def add_list_caps(
    schema: Any, default_max: int = 8, _seen_id: set[int] | None = None,
) -> Any:
    """Probe-local mutation: walk the schema and add `maxItems` to every
    unbounded array of strings (or arrays of any primitive). Leaves
    array-of-object fields (e.g. ChapterEnrichmentResult.enrichments)
    untouched — we want all 20 paragraphs in the outer list.

    Rationale: the production Pydantic schemas deliberately don't enforce
    list-length caps (description-only), per the schemas.py docstring. On
    Qwen-family models under grammar-constrained decoding, unbounded
    string-array fields like `themes` and `characters_present` are
    susceptible to repetition loops (model emits "tender", "tender", ...
    until the server-side timeout cuts it off mid-JSON). Capping at the
    docstring's stated upper bound (8 items) prevents this without changing
    the production schema.
    """
    if _seen_id is None:
        _seen_id = set()
    if isinstance(schema, dict):
        if id(schema) in _seen_id:
            return schema
        _seen_id.add(id(schema))
        items = schema.get("items")
        if (
            schema.get("type") == "array"
            and "maxItems" not in schema
            and isinstance(items, dict)
            and items.get("type") in ("string", "number", "integer", "boolean")
        ):
            schema["maxItems"] = default_max
        for v in schema.values():
            if isinstance(v, (dict, list)):
                add_list_caps(v, default_max, _seen_id)
    elif isinstance(schema, list):
        for item in schema:
            add_list_caps(item, default_max, _seen_id)
    return schema


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve `$ref: #/$defs/<namcae>` inline and drop $defs.

    Non-recursive schemas only — raises ValueError if a self-referencing
    cycle is detected (ChapterEnrichmentResult isn't recursive, so this
    is just a safety check).
    """
    defs = schema.get("$defs", {})
    seen: set[str] = set()

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref = node["$ref"]
                if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
                    return node
                name = ref.split("/")[-1]
                if name in seen:
                    raise ValueError(f"recursive $defs reference: {name}")
                seen.add(name)
                try:
                    return walk(defs[name])
                finally:
                    seen.discard(name)
            return {k: walk(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    result = walk(schema)
    if isinstance(result, dict):
        result.pop("$defs", None)
    return result


def _read_passages(novel: str) -> list[dict]:
    novel_dir = Path("data/novels") / novel
    raw_path = novel_dir / "passages_raw.json"
    if raw_path.exists():
        return json.loads(raw_path.read_text())
    enriched_path = novel_dir / "passages_enriched.json"
    if enriched_path.exists():
        full = json.loads(enriched_path.read_text())
        return [
            {
                "passage_id": p["passage_id"],
                "chapter_id": p["chapter_id"],
                "chapter_title": p.get("chapter_title", ""),
                "paragraph_index": p["paragraph_index"],
                "text": p["text"],
            }
            for p in full
        ]
    raise FileNotFoundError(
        f"Need passages_raw.json or passages_enriched.json under {novel_dir}"
    )


def _build_jsonl_line(
    *,
    custom_id: str,
    chapter_id: str,
    chapter_title: str,
    chunk: list[dict],
    system_prompt: str,
    schema: dict,
    model: str,
    max_completion_tokens: int,
    temperature: float,
) -> dict:
    formatted = format_chapter_text(chunk)
    user_message = f"Chapter: {chapter_id} - {chapter_title}\n\n{formatted}"
    return {
        "custom_id": custom_id,
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "ChapterEnrichmentResult",
                    "strict": True,
                    "schema": schema,
                },
            },
            "max_completion_tokens": max_completion_tokens,
            "temperature": temperature,
            # Qwen 3.x thinking mode prepends "<think>...</think>" prose to
            # the response, which DashScope's batch server then rejects as
            # ModelServingOutputInvalidJsonError. Force the chat template to
            # skip the thinking turn. Verified pattern in docs/qwen_family_test_plan.md.
            "chat_template_kwargs": {"enable_thinking": False},
            # Repetition mitigation. qwen-plus under grammar-constrained
            # decoding occasionally loops on string-array fields (e.g.
            # emitting "tender", "tender", ... in themes). Modest positive
            # frequency_penalty makes repeat tokens less likely without
            # materially affecting normal output quality.
            "frequency_penalty": 0.5,
        },
    }


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )

    p = argparse.ArgumentParser()
    p.add_argument("--novel", default=DEFAULT_NOVEL,
                   help="Novel key (default: %(default)s). Validated downstream "
                        "via build_enrichment_prompt and the passages file.")
    p.add_argument("--chapter", default=DEFAULT_CHAPTER,
                   help="Chapter id, e.g. c6 (default: %(default)s)")
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help="DashScope model id (default: %(default)s)")
    p.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
                   help="Paragraphs per batch request (default: %(default)s)")
    p.add_argument("--max-completion-tokens", type=int,
                   default=DEFAULT_MAX_COMPLETION_TOKENS)
    p.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    args = p.parse_args()

    probe_dir = PROBE_ROOT / f"{args.novel}_{args.chapter}"
    probe_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = probe_dir / "batch_input.jsonl"
    manifest_path = probe_dir / "manifest.json"

    passages = _read_passages(args.novel)
    chap_passages = [p for p in passages if p["chapter_id"] == args.chapter]
    if not chap_passages:
        raise SystemExit(f"No passages for {args.novel}/{args.chapter}")
    chap_passages.sort(key=lambda x: x["paragraph_index"])
    chapter_title = chap_passages[0].get("chapter_title", "")
    logger.info(
        "%s/%s — %d passages (\"%s\"), chunk_size=%d",
        args.novel, args.chapter, len(chap_passages),
        chapter_title, args.chunk_size,
    )

    system_prompt = build_enrichment_prompt(args.novel) + JSON_INSTRUCTION_SUFFIX
    schema = add_list_caps(inline_refs(ChapterEnrichmentResult.model_json_schema()))
    logger.info("schema flattened (refs inlined, $defs removed); "
                "primitive-array fields capped at maxItems=8")
    logger.info("appended probe-local JSON-output instruction to system prompt")

    chunks = [
        chap_passages[i:i + args.chunk_size]
        for i in range(0, len(chap_passages), args.chunk_size)
    ]
    lines: list[dict] = []
    indices_by_custom_id: dict[str, list[int]] = {}
    for chunk_idx, chunk in enumerate(chunks):
        custom_id = f"enrich-{args.chapter}"
        if len(chunks) > 1:
            custom_id += f"-part{chunk_idx}"
        line = _build_jsonl_line(
            custom_id=custom_id,
            chapter_id=args.chapter,
            chapter_title=chapter_title,
            chunk=chunk,
            system_prompt=system_prompt,
            schema=schema,
            model=args.model,
            max_completion_tokens=args.max_completion_tokens,
            temperature=args.temperature,
        )
        lines.append(line)
        indices_by_custom_id[custom_id] = [p["paragraph_index"] for p in chunk]

    jsonl_text = "\n".join(json.dumps(L) for L in lines) + "\n"
    jsonl_path.write_text(jsonl_text)
    logger.info("wrote %d requests to %s (%d bytes)",
                len(lines), jsonl_path, len(jsonl_text))

    load_dotenv()
    key = os.environ.get("ALIBABA_API_KEY")
    if not key:
        raise SystemExit("ALIBABA_API_KEY not set in env / .env")
    client = OpenAI(api_key=key, base_url=BASE_URL,
                    timeout=600.0, max_retries=0)

    logger.info("uploading %s ...", jsonl_path)
    with open(jsonl_path, "rb") as f:
        file_resp = client.files.create(file=f, purpose="batch")
    logger.info("input_file_id: %s", file_resp.id)

    batch = client.batches.create(
        input_file_id=file_resp.id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
        metadata={
            "novel": args.novel,
            "chapter": args.chapter,
            "task": "passage_enrichment_probe",
            "model": args.model,
        },
    )
    submitted_at = datetime.now(timezone.utc).isoformat()
    logger.info("batch_id: %s  status=%s", batch.id, batch.status)

    manifest = {
        "novel": args.novel,
        "chapter": args.chapter,
        "model": args.model,
        "endpoint": "/v1/chat/completions",
        "base_url": BASE_URL,
        "schema_form": "flat (refs inlined)",
        "batch_id": batch.id,
        "input_file_id": file_resp.id,
        "submitted_at": submitted_at,
        "request_count": len(lines),
        "chunk_size": args.chunk_size,
        "max_completion_tokens": args.max_completion_tokens,
        "temperature": args.temperature,
        "indices_by_custom_id": indices_by_custom_id,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    logger.info("manifest saved to %s", manifest_path)
    logger.info("next: uv run python scripts/collect_dashscope_batch_enrichment.py %s",
                probe_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
