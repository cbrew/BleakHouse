"""Realtime (non-batch) diagnostic for qwen-plus passage_enrichment.

Three failed batch attempts have all returned an opaque
ModelServingOutputInvalidJsonError. The model's actual output has been
destroyed by DashScope's server-side validator each time. This script
makes two direct realtime chat-completions calls so we can see what
the model is actually emitting.

Call A: no `response_format` at all. DashScope won't intercept; we get
the raw `message.content` whatever shape it takes (prose, JSON, JSON
with prefix prose, `<think>...</think>`, truncated, etc.).

Call B: response_format=json_schema strict=True. Replicates the batch
configuration on the realtime endpoint. Two outcomes possible:
- Succeeds → DashScope's batch path is broken vs realtime path.
- Fails identically → the request itself is the problem (model + schema
  + scale don't compose).

Both calls share: same model (qwen-plus), same chunk (full chapter,
158 passages for bleak_house/c6), same system prompt as the submitter,
same enable_thinking:False, same max_completion_tokens, same temp.

Every artifact is persisted before any analysis:
- manifest.json — shared call metadata
- call_{a,b}_request.json — full request body sent
- call_{a,b}_response.json — ChatCompletion.model_dump() (or null)
- call_{a,b}_content.txt — raw message.content (or empty)
- call_{a,b}_error.txt — exception text (only if the call raised)

Analysis is a separate function that reads from disk; re-run with
--analyze-only to redo the analysis without re-spending API.

Tracks BleakHouse-el1j.1.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import ValidationError

from enrichment.novel_prompts import build_enrichment_prompt
from enrichment.llm.schemas import ChapterEnrichmentResult
from enrichment.submit_passages_enriched import format_chapter_text
from scripts.submit_dashscope_batch_enrichment import (
    JSON_INSTRUCTION_SUFFIX,
    inline_refs,
    _read_passages,
)

logger = logging.getLogger("probe_qwen_plus_realtime")

BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-plus"
DEFAULT_NOVEL = "bleak_house"
DEFAULT_CHAPTER = "c6"
DEFAULT_MAX_COMPLETION_TOKENS = 32768
DEFAULT_TEMPERATURE = 0.0
# Default to ONE passage. Smallest meaningful unit — output is ~50
# tokens of JSON, eyeball-readable in whole. If the model can't satisfy
# the schema for one passage, the problem is fundamental and we don't
# need to scale up to find out. Bump only after a clean baseline.
DEFAULT_MAX_PASSAGES = 1
PROBE_ROOT = Path("data/runs/_qwen_plus_realtime_enrichment_probe")
REPETITION_RE = re.compile(r"(.{20,})\1{3,}")


def _make_client() -> OpenAI:
    load_dotenv()
    key = os.environ.get("ALIBABA_API_KEY")
    if not key:
        raise SystemExit("ALIBABA_API_KEY not set in env / .env")
    # Realtime call can be slow at this scale — generous timeout.
    return OpenAI(api_key=key, base_url=BASE_URL,
                  timeout=1800.0, max_retries=0)


def _build_body(
    *,
    model: str,
    system_prompt: str,
    user_message: str,
    max_completion_tokens: int,
    temperature: float,
    with_schema: bool,
    schema: dict | None,
) -> dict:
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "max_completion_tokens": max_completion_tokens,
        "temperature": temperature,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if with_schema:
        assert schema is not None
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "ChapterEnrichmentResult",
                "strict": True,
                "schema": schema,
            },
        }
    return body


def _call_and_capture(
    *,
    client: OpenAI,
    label: str,
    body: dict,
    probe_dir: Path,
) -> None:
    """Make one call. Persist request, response, raw content, or error
    text. Never raises — every failure path writes a file."""
    req_path = probe_dir / f"call_{label}_request.json"
    resp_path = probe_dir / f"call_{label}_response.json"
    content_path = probe_dir / f"call_{label}_content.txt"
    error_path = probe_dir / f"call_{label}_error.txt"

    # extra_body is the OpenAI SDK's pass-through for non-standard params;
    # chat_template_kwargs travels through that, not as a direct kwarg.
    sdk_body = dict(body)
    chat_template_kwargs = sdk_body.pop("chat_template_kwargs", None)

    # Persist what we're about to send BEFORE making the call.
    req_path.write_text(json.dumps(body, indent=2))
    logger.info("call %s: persisted request to %s", label, req_path)

    started = time.monotonic()
    try:
        resp = client.chat.completions.create(
            **sdk_body,
            extra_body=({"chat_template_kwargs": chat_template_kwargs}
                        if chat_template_kwargs else {}),
        )
    except Exception as e:
        elapsed = time.monotonic() - started
        error_path.write_text(
            f"elapsed_seconds: {elapsed:.1f}\n"
            f"exception_type: {e.__class__.__name__}\n"
            f"exception_str: {e!s}\n"
        )
        logger.warning("call %s raised after %.1fs: %s",
                       label, elapsed, e)
        return

    elapsed = time.monotonic() - started
    # Persist the full response first — content extraction is below.
    resp_dump = resp.model_dump()
    resp_dump["_elapsed_seconds"] = elapsed
    resp_path.write_text(json.dumps(resp_dump, indent=2, default=str))
    logger.info("call %s: persisted response to %s (%.1fs)",
                label, resp_path, elapsed)

    content = (resp.choices[0].message.content or "") if resp.choices else ""
    content_path.write_text(content)
    logger.info("call %s: content %d chars  finish=%s",
                label, len(content),
                resp.choices[0].finish_reason if resp.choices else None)


# ---------------------------------------------------------------------------
# Analysis (separate pass; reads from disk)
# ---------------------------------------------------------------------------

def _analyse_call(probe_dir: Path, label: str) -> dict:
    req_path = probe_dir / f"call_{label}_request.json"
    resp_path = probe_dir / f"call_{label}_response.json"
    content_path = probe_dir / f"call_{label}_content.txt"
    error_path = probe_dir / f"call_{label}_error.txt"

    result: dict[str, Any] = {"label": label}
    result["request_present"] = req_path.exists()
    result["error_text"] = (
        error_path.read_text() if error_path.exists() else None
    )

    if not resp_path.exists():
        result["status"] = "errored" if error_path.exists() else "absent"
        return result

    resp = json.loads(resp_path.read_text())
    result["elapsed_seconds"] = resp.get("_elapsed_seconds")
    usage = resp.get("usage") or {}
    result["input_tokens"] = usage.get("prompt_tokens") or 0
    result["output_tokens"] = usage.get("completion_tokens") or 0
    choices = resp.get("choices") or []
    if choices:
        result["finish_reason"] = choices[0].get("finish_reason")
    else:
        result["finish_reason"] = None

    content = content_path.read_text() if content_path.exists() else ""
    result["content_length"] = len(content)
    result["content_head"] = content[:300]
    result["content_tail"] = content[-300:] if len(content) > 300 else ""
    result["has_think_tags"] = bool(re.search(r"<think\b", content, re.IGNORECASE))
    result["has_markdown_fence"] = "```" in content
    result["repetition_loop"] = bool(REPETITION_RE.search(content))
    result["was_truncated"] = result["finish_reason"] == "length"

    # JSON parse + schema validate
    if content.strip():
        try:
            obj = json.loads(content)
            result["json_parse"] = "ok"
            try:
                ChapterEnrichmentResult.model_validate(obj)
                result["schema_validate"] = "ok"
            except ValidationError as e:
                result["schema_validate"] = f"failed: {e.error_count()} errors"
        except json.JSONDecodeError as e:
            result["json_parse"] = f"failed: {e!s}"
            result["schema_validate"] = "n/a"
    else:
        result["json_parse"] = "n/a (empty content)"
        result["schema_validate"] = "n/a"

    result["status"] = "ok"
    return result


def _write_diagnostic_report(
    probe_dir: Path, analysis_a: dict, analysis_b: dict,
) -> None:
    md_path = probe_dir / "diagnostic_report.md"
    lines: list[str] = []

    def hypothesis_check(a: dict, b: dict) -> str:
        a_ok = a.get("json_parse") == "ok" and a.get("schema_validate") == "ok"
        b_ok = b.get("json_parse") == "ok" and b.get("schema_validate") == "ok"
        if a_ok and b_ok:
            return "Both calls produced valid schema-conforming JSON. The batch path is broken vs realtime — DashScope batch and realtime are not behaviourally equivalent."
        if b_ok and not a_ok:
            return "Call B (with response_format) succeeded; Call A (no response_format) did not. Schema enforcement is helping the model. Batch path may be filtering something realtime allows through."
        if a_ok and not b_ok:
            return "Call A (no response_format) produced valid JSON; Call B (with response_format) did not. The schema-enforcement path itself is the problem; the model can produce the structure but DashScope's strict mode rejects it."
        return "Both calls failed to produce schema-conforming JSON. The diagnosis is upstream of the batch path: model+schema+scale don't compose. Specific failures below."

    lines += [
        "# qwen-plus realtime diagnostic — bleak_house/c6",
        "",
        f"Run dir: `{probe_dir}`",
        "",
        "## Hypothesis assessment",
        "",
        hypothesis_check(analysis_a, analysis_b),
        "",
    ]

    for label, analysis in (("A — no response_format", analysis_a),
                            ("B — response_format=json_schema strict=True", analysis_b)):
        lines += [
            f"## Call {label}",
            "",
            f"- status: {analysis.get('status')}",
            f"- elapsed: {analysis.get('elapsed_seconds')}",
            f"- input_tokens: {analysis.get('input_tokens')}",
            f"- output_tokens: {analysis.get('output_tokens')}",
            f"- finish_reason: {analysis.get('finish_reason')}",
            f"- content_length: {analysis.get('content_length')}",
            f"- has_think_tags: {analysis.get('has_think_tags')}",
            f"- has_markdown_fence: {analysis.get('has_markdown_fence')}",
            f"- repetition_loop: {analysis.get('repetition_loop')}",
            f"- was_truncated: {analysis.get('was_truncated')}",
            f"- json_parse: {analysis.get('json_parse')}",
            f"- schema_validate: {analysis.get('schema_validate')}",
        ]
        if analysis.get("error_text"):
            lines += [
                "",
                "### error",
                "",
                "```",
                analysis["error_text"].strip(),
                "```",
            ]
        if analysis.get("content_head"):
            lines += [
                "",
                "### content (first 300 chars)",
                "",
                "```",
                analysis["content_head"],
                "```",
            ]
            if analysis.get("content_tail"):
                lines += [
                    "",
                    "### content (last 300 chars)",
                    "",
                    "```",
                    analysis["content_tail"],
                    "```",
                ]
        lines.append("")

    md_path.write_text("\n".join(lines))
    logger.info("wrote %s", md_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )

    p = argparse.ArgumentParser()
    p.add_argument("--novel", default=DEFAULT_NOVEL)
    p.add_argument("--chapter", default=DEFAULT_CHAPTER)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--max-completion-tokens", type=int,
                   default=DEFAULT_MAX_COMPLETION_TOKENS)
    p.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    p.add_argument("--max-passages", type=int, default=DEFAULT_MAX_PASSAGES,
                   help="Cap on passages sent in the diagnostic chunk "
                        "(default: %(default)s — keeps the output "
                        "eyeball-readable and isolates 'can the model do "
                        "this at all?' from 'does it scale?'). Bump only "
                        "after a clean baseline.")
    p.add_argument("--analyze-only", action="store_true",
                   help="Re-run analysis on cached calls; do not call the API.")
    args = p.parse_args()

    probe_dir = PROBE_ROOT / f"{args.novel}_{args.chapter}"
    probe_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = probe_dir / "manifest.json"

    passages = _read_passages(args.novel)
    chap_passages = [p for p in passages if p["chapter_id"] == args.chapter]
    if not chap_passages:
        raise SystemExit(f"no passages for {args.novel}/{args.chapter}")
    chap_passages.sort(key=lambda x: x["paragraph_index"])
    chapter_title = chap_passages[0].get("chapter_title", "")
    full_chapter_count = len(chap_passages)
    if args.max_passages and len(chap_passages) > args.max_passages:
        chap_passages = chap_passages[:args.max_passages]

    system_prompt = build_enrichment_prompt(args.novel) + JSON_INSTRUCTION_SUFFIX
    user_message = (
        f"Chapter: {args.chapter} - {chapter_title}\n\n"
        + format_chapter_text(chap_passages)
    )
    schema = inline_refs(ChapterEnrichmentResult.model_json_schema())

    manifest = {
        "novel": args.novel,
        "chapter": args.chapter,
        "chapter_title": chapter_title,
        "full_chapter_passage_count": full_chapter_count,
        "passages_sent": len(chap_passages),
        "max_passages_cap": args.max_passages,
        "model": args.model,
        "max_completion_tokens": args.max_completion_tokens,
        "temperature": args.temperature,
        "base_url": BASE_URL,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "system_prompt_chars": len(system_prompt),
        "user_message_chars": len(user_message),
        "schema_form": "flat (refs inlined)",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    logger.info(
        "%s/%s — sending %d/%d passages (\"%s\")",
        args.novel, args.chapter, len(chap_passages),
        full_chapter_count, chapter_title,
    )
    logger.info("manifest: %s", manifest_path)

    if not args.analyze_only:
        client = _make_client()
        body_a = _build_body(
            model=args.model, system_prompt=system_prompt,
            user_message=user_message,
            max_completion_tokens=args.max_completion_tokens,
            temperature=args.temperature,
            with_schema=False, schema=None,
        )
        body_b = _build_body(
            model=args.model, system_prompt=system_prompt,
            user_message=user_message,
            max_completion_tokens=args.max_completion_tokens,
            temperature=args.temperature,
            with_schema=True, schema=schema,
        )
        _call_and_capture(client=client, label="a", body=body_a, probe_dir=probe_dir)
        _call_and_capture(client=client, label="b", body=body_b, probe_dir=probe_dir)
    else:
        logger.info("--analyze-only: skipping API calls")

    analysis_a = _analyse_call(probe_dir, "a")
    analysis_b = _analyse_call(probe_dir, "b")
    (probe_dir / "diagnostic_analysis.json").write_text(
        json.dumps({"call_a": analysis_a, "call_b": analysis_b}, indent=2)
    )
    _write_diagnostic_report(probe_dir, analysis_a, analysis_b)

    # Print a concise summary
    logger.info("=" * 60)
    for label, a in (("A (no response_format)", analysis_a),
                     ("B (json_schema strict)", analysis_b)):
        logger.info(
            "%s: status=%s  json_parse=%s  schema_validate=%s  "
            "finish=%s  content_len=%s  think_tags=%s",
            label, a.get("status"), a.get("json_parse"),
            a.get("schema_validate"), a.get("finish_reason"),
            a.get("content_length"), a.get("has_think_tags"),
        )
    logger.info("report: %s", probe_dir / "diagnostic_report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
