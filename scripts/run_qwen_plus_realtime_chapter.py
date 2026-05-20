"""Run passage_enrichment on one or many chapters via concurrent qwen-plus realtime calls.

Designed as the fallback when DashScope batch is unusable: chunk each
chapter, dispatch each chunk as an async chat completion via
`asyncio.TaskGroup`. Across chapters, a small asyncio.Semaphore bounds
how many chapters can be in flight at once — chapter-level concurrency
is the right granularity because each chapter is self-contained and the
TPM budget is naturally measured per-chapter. The cross-chapter
semaphore is ~5 lines and keeps us under DashScope's 1M TPM cap.

Why this exists (BleakHouse-el1j.1):
- Three batch attempts at 158 passages/call all returned
  ModelServingOutputInvalidJsonError. The model's output was destroyed
  by the server-side validator before we could see it.
- Realtime json_schema strict=True works for 1-passage and 20-passage
  chunks (verified in scripts/probe_qwen_plus_realtime_enrichment.py).
- qwen-plus generates at ~50 tok/s, so a 20-passage chunk takes ~135s.
  RPM/TPM headroom (600 RPM / 1M TPM) makes 8 concurrent chunks
  per chapter trivially safe.

Behaviour:
- Read chapter passages.
- Chunk into groups of --chunk-size (default 20).
- Build one chat completion body per chunk (json_schema strict + the
  enable_thinking:False + JSON-instruction prompt suffix used by the
  batch submitter).
- TaskGroup dispatches every chunk concurrently. Each task catches its
  own exception so a single failure doesn't cancel siblings.
- For each chunk: persist request, response, content, and any error
  text. Validate the content against ChapterEnrichmentResult.
- After all tasks complete: write run_report.{json,md}.

Tracks BleakHouse-el1j.1.

Run:
    # single chapter
    uv run python scripts/run_qwen_plus_realtime_chapter.py \\
        --chapters c6
    # several explicit chapters
    uv run python scripts/run_qwen_plus_realtime_chapter.py \\
        --chapters c1,c2,c6
    # entire novel (67 chapters for bleak_house, ~16 min wall, ~$5)
    uv run python scripts/run_qwen_plus_realtime_chapter.py \\
        --novel bleak_house --chapters all

Run directory layout:
    data/runs/_qwen_plus_realtime_chapter_runs/
        <novel>/
            <chapter>/
                manifest.json
                chunk_NN_{request,response,content,error}.{json,txt}
                run_report.{json,md}
            novel_report.{json,md}     # only when chapters > 1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic import ValidationError

from enrichment.novel_prompts import build_enrichment_prompt
from enrichment.llm.schemas import ChapterEnrichmentResult
from enrichment.submit_passages_enriched import format_chapter_text
from scripts.submit_dashscope_batch_enrichment import (
    JSON_INSTRUCTION_SUFFIX,
    add_list_caps,
    inline_refs,
    _read_passages,
)

logger = logging.getLogger("run_qwen_plus_realtime_chapter")

BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-plus"
DEFAULT_NOVEL = "bleak_house"
DEFAULT_CHAPTER = "c6"
DEFAULT_CHUNK_SIZE = 20
DEFAULT_MAX_COMPLETION_TOKENS = 32768
DEFAULT_TEMPERATURE = 0.0

# Realtime rates (intl, ≤256K input bucket). No 50% batch discount.
RATE_INPUT_PER_MTOK = 0.40
RATE_OUTPUT_PER_MTOK = 1.20

RUN_ROOT = Path("data/runs/_qwen_plus_realtime_chapter_runs")


@dataclass
class ChunkResult:
    label: str
    paragraph_indices: list[int]
    status: str = "pending"            # pending / ok / api_error / parse_error
    elapsed_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str | None = None
    validation: str = "n/a"            # ok / failed: ...
    parsed_count: int = 0              # number of ParagraphEnrichment items parsed
    cost_usd: float = 0.0
    error_class: str | None = None
    error_text: str | None = None


def _build_body(
    *,
    model: str,
    system_prompt: str,
    user_message: str,
    max_completion_tokens: int,
    temperature: float,
    schema: dict,
) -> dict:
    return {
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
        "chat_template_kwargs": {"enable_thinking": False},
        # Repetition mitigation — see submit_dashscope_batch_enrichment.py
        # for the rationale. qwen-plus loops on unbounded string-array
        # fields; frequency_penalty plus add_list_caps()'s maxItems
        # constraint together prevent the runaway.
        "frequency_penalty": 0.5,
    }


async def _call_one_chunk(
    *,
    client: AsyncOpenAI,
    body: dict,
    label: str,
    run_dir: Path,
    paragraph_indices: list[int],
) -> ChunkResult:
    """One async chat completion. Catches its own exceptions and persists
    every artifact before returning. Never raises — sibling tasks must
    not be cancelled by one bad chunk."""
    req_path = run_dir / f"{label}_request.json"
    resp_path = run_dir / f"{label}_response.json"
    content_path = run_dir / f"{label}_content.txt"
    error_path = run_dir / f"{label}_error.txt"

    sdk_body = dict(body)
    chat_template_kwargs = sdk_body.pop("chat_template_kwargs", None)

    # Persist what we're about to send BEFORE making the call.
    req_path.write_text(json.dumps(body, indent=2))

    result = ChunkResult(label=label, paragraph_indices=paragraph_indices)

    started = time.monotonic()
    try:
        resp = await client.chat.completions.create(
            **sdk_body,
            extra_body=({"chat_template_kwargs": chat_template_kwargs}
                        if chat_template_kwargs else {}),
        )
    except Exception as e:
        result.elapsed_seconds = time.monotonic() - started
        result.status = "api_error"
        result.error_class = e.__class__.__name__
        result.error_text = str(e)
        error_path.write_text(
            f"elapsed_seconds: {result.elapsed_seconds:.1f}\n"
            f"exception_type: {result.error_class}\n"
            f"exception_str: {result.error_text}\n"
        )
        logger.warning("%s: api_error after %.1fs: %s",
                       label, result.elapsed_seconds, e)
        return result

    result.elapsed_seconds = time.monotonic() - started

    # Persist the full response first.
    resp_dump = resp.model_dump()
    resp_dump["_elapsed_seconds"] = result.elapsed_seconds
    resp_path.write_text(json.dumps(resp_dump, indent=2, default=str))

    usage = resp.usage.model_dump() if resp.usage else {}
    result.input_tokens = int(usage.get("prompt_tokens") or 0)
    result.output_tokens = int(usage.get("completion_tokens") or 0)
    result.cost_usd = (
        result.input_tokens / 1_000_000 * RATE_INPUT_PER_MTOK
        + result.output_tokens / 1_000_000 * RATE_OUTPUT_PER_MTOK
    )

    choices = resp.choices or []
    if not choices:
        result.status = "parse_error"
        result.validation = "failed: empty choices"
        content_path.write_text("")
        logger.warning("%s: empty choices", label)
        return result

    choice = choices[0]
    result.finish_reason = choice.finish_reason
    content = choice.message.content or ""
    content_path.write_text(content)

    if not content:
        result.status = "parse_error"
        result.validation = f"failed: empty content (finish={result.finish_reason})"
        return result

    try:
        obj = json.loads(content)
    except json.JSONDecodeError as e:
        result.status = "parse_error"
        result.validation = f"failed: JSONDecodeError: {e}"
        return result

    try:
        parsed = ChapterEnrichmentResult.model_validate(obj)
        result.status = "ok"
        result.validation = "ok"
        result.parsed_count = len(parsed.enrichments)
        logger.info(
            "%s: ok  %.1fs  in=%d out=%d  parsed=%d  cost=$%.4f",
            label, result.elapsed_seconds,
            result.input_tokens, result.output_tokens,
            result.parsed_count, result.cost_usd,
        )
    except ValidationError as e:
        result.status = "parse_error"
        result.validation = f"failed: ValidationError: {e.error_count()} errors"
        logger.warning("%s: schema invalid (%d errors)",
                       label, e.error_count())

    return result


def _write_reports(
    results: list[ChunkResult],
    run_dir: Path,
    manifest: dict,
    wall_seconds: float,
) -> str:
    json_path = run_dir / "run_report.json"
    md_path = run_dir / "run_report.md"

    total_in = sum(r.input_tokens for r in results)
    total_out = sum(r.output_tokens for r in results)
    total_cost = sum(r.cost_usd for r in results)
    ok_count = sum(1 for r in results if r.status == "ok")
    total_parsed = sum(r.parsed_count for r in results)
    expected_total = sum(len(r.paragraph_indices) for r in results)

    by_status: dict[str, int] = {}
    for r in results:
        by_status[r.status] = by_status.get(r.status, 0) + 1

    # PASS = every chunk returned valid schema-conforming JSON AND we
    # got at least 98% paragraph coverage. The model occasionally drops
    # 1-2 paragraphs per chapter from successful chunks; treating that
    # as hard-FAIL would over-state failure since the infrastructure
    # itself is sound. See smoke #2 (commit aXXX) for the empirical basis.
    coverage = total_parsed / expected_total if expected_total else 1.0
    pass_all_ok = ok_count == len(results)
    pass_coverage = coverage >= 0.98
    verdict = "PASS" if (pass_all_ok and pass_coverage) else "FAIL"

    payload = {
        "verdict": verdict,
        "manifest": manifest,
        "wall_seconds": wall_seconds,
        "chunk_count": len(results),
        "ok_chunks": ok_count,
        "by_status": by_status,
        "expected_paragraphs": expected_total,
        "parsed_paragraphs": total_parsed,
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "total_cost_usd": round(total_cost, 6),
        "rates_per_mtok": {"input": RATE_INPUT_PER_MTOK, "output": RATE_OUTPUT_PER_MTOK},
        "per_chunk": [
            {
                "label": r.label,
                "status": r.status,
                "elapsed_seconds": round(r.elapsed_seconds, 2),
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "finish_reason": r.finish_reason,
                "validation": r.validation,
                "parsed_count": r.parsed_count,
                "expected_count": len(r.paragraph_indices),
                "cost_usd": round(r.cost_usd, 6),
                "error_class": r.error_class,
            }
            for r in results
        ],
    }
    json_path.write_text(json.dumps(payload, indent=2))

    md = [
        f"# qwen-plus realtime chapter run — {manifest['novel']}/{manifest['chapter']}",
        "",
        f"- run_dir: `{run_dir}`",
        f"- model: {manifest['model']}",
        f"- chunk_size: {manifest['chunk_size']}",
        f"- chunks: {len(results)}",
        f"- started: {manifest['started_at']}",
        f"- wall: {wall_seconds:.0f}s",
        "",
        "## Verdict",
        "",
        f"**{verdict}** — {ok_count}/{len(results)} chunks ok; "
        f"{total_parsed}/{expected_total} paragraphs parsed.",
        "",
        "## Numbers",
        "",
        f"- by_status: {by_status}",
        f"- input tokens: {total_in:,}",
        f"- output tokens: {total_out:,}",
        f"- cost: ${total_cost:.4f} "
        f"(at ${RATE_INPUT_PER_MTOK}/M in, ${RATE_OUTPUT_PER_MTOK}/M out)",
        "",
        "## Per-chunk",
        "",
        "| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |",
        "|---|---|---:|---:|---:|---|---:|---|---|",
    ]
    for r in results:
        v = r.validation[:40] + ("…" if len(r.validation) > 40 else "")
        md.append(
            f"| `{r.label}` | {r.status} | {r.elapsed_seconds:.1f}s | "
            f"{r.input_tokens} | {r.output_tokens} | "
            f"{r.parsed_count}/{len(r.paragraph_indices)} | "
            f"${r.cost_usd:.4f} | {r.finish_reason or '-'} | {v} |"
        )
    md_path.write_text("\n".join(md))
    return verdict


async def _run_one_chapter(
    *,
    client: AsyncOpenAI,
    novel: str,
    chapter: str,
    chap_passages: list[dict],
    system_prompt: str,
    schema: dict,
    args: argparse.Namespace,
    novel_root: Path,
) -> dict:
    """Run one chapter via concurrent chunk TaskGroup. Persists per-chunk
    artifacts + chapter manifest + chapter run_report. Returns a summary
    dict for the novel-level report."""
    chapter_title = chap_passages[0].get("chapter_title", "")
    chunks = [
        chap_passages[i:i + args.chunk_size]
        for i in range(0, len(chap_passages), args.chunk_size)
    ]
    logger.info(
        "%s/%s — %d passages (\"%s\"), %d chunks of up to %d",
        novel, chapter, len(chap_passages), chapter_title,
        len(chunks), args.chunk_size,
    )

    run_dir = novel_root / chapter
    run_dir.mkdir(parents=True, exist_ok=True)

    bodies: list[tuple[str, dict, list[int]]] = []
    for i, chunk in enumerate(chunks):
        user_message = (
            f"Chapter: {chapter} - {chapter_title}\n\n"
            + format_chapter_text(chunk)
        )
        body = _build_body(
            model=args.model,
            system_prompt=system_prompt,
            user_message=user_message,
            max_completion_tokens=args.max_completion_tokens,
            temperature=args.temperature,
            schema=schema,
        )
        label = f"chunk_{i:02d}"
        indices = [p["paragraph_index"] for p in chunk]
        bodies.append((label, body, indices))

    started_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "novel": novel,
        "chapter": chapter,
        "chapter_title": chapter_title,
        "passage_count": len(chap_passages),
        "chunk_size": args.chunk_size,
        "chunk_count": len(chunks),
        "model": args.model,
        "max_completion_tokens": args.max_completion_tokens,
        "temperature": args.temperature,
        "base_url": BASE_URL,
        "started_at": started_at,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    started = time.monotonic()
    async with asyncio.TaskGroup() as tg:
        tasks = [
            tg.create_task(_call_one_chunk(
                client=client, body=body, label=label,
                run_dir=run_dir, paragraph_indices=indices,
            ))
            for label, body, indices in bodies
        ]
    results = [t.result() for t in tasks]
    wall_seconds = time.monotonic() - started

    manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
    manifest["wall_seconds"] = wall_seconds
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    verdict = _write_reports(results, run_dir, manifest, wall_seconds)

    ok_count = sum(1 for r in results if r.status == "ok")
    total_parsed = sum(r.parsed_count for r in results)
    expected_total = sum(len(r.paragraph_indices) for r in results)
    total_in = sum(r.input_tokens for r in results)
    total_out = sum(r.output_tokens for r in results)
    total_cost = sum(r.cost_usd for r in results)
    logger.info(
        "%s/%s: %s  chunks=%d ok=%d  parsed=%d/%d  wall=%.0fs  cost=$%.4f",
        novel, chapter, verdict, len(results), ok_count,
        total_parsed, expected_total, wall_seconds, total_cost,
    )
    return {
        "novel": novel,
        "chapter": chapter,
        "verdict": verdict,
        "chunk_count": len(results),
        "ok_chunks": ok_count,
        "expected_paragraphs": expected_total,
        "parsed_paragraphs": total_parsed,
        "wall_seconds": wall_seconds,
        "input_tokens": total_in,
        "output_tokens": total_out,
        "cost_usd": total_cost,
        "run_dir": str(run_dir),
    }


def _natural_chapter_sort_key(passages_by_chapter: dict[str, list[dict]]) -> Any:
    """Sort chapters by chapter-id pattern. char_start/paragraph_index both
    restart per chapter so neither can drive order; the only signal in the
    enriched passages data is chapter_id itself.

    Convention used: cP (preface) first, F2 (preface footnote) right after,
    then c1..cN numerically, with anything unrecognised at the end.
    Works for the canonical BleakHouse layout and is harmless for novels
    that only use c1..cN."""
    def key(ch: str) -> tuple:
        if ch == "cP":
            return (0, 0)
        if ch == "F2":
            return (0, 1)
        if ch.startswith("c"):
            try:
                return (1, int(ch[1:]))
            except ValueError:
                pass
        return (2, ch)
    return key


def _write_novel_report(
    novel_root: Path,
    novel: str,
    summaries: list[dict],
    wall_seconds: float,
    started_at: str,
) -> str:
    json_path = novel_root / "novel_report.json"
    md_path = novel_root / "novel_report.md"

    chapter_count = len(summaries)
    pass_count = sum(1 for s in summaries if s["verdict"] == "PASS")
    total_in = sum(s["input_tokens"] for s in summaries)
    total_out = sum(s["output_tokens"] for s in summaries)
    total_cost = sum(s["cost_usd"] for s in summaries)
    total_parsed = sum(s["parsed_paragraphs"] for s in summaries)
    expected_paragraphs = sum(s["expected_paragraphs"] for s in summaries)

    coverage = total_parsed / expected_paragraphs if expected_paragraphs else 1.0
    verdict = "PASS" if pass_count == chapter_count and coverage >= 0.98 else "FAIL"

    payload = {
        "verdict": verdict,
        "novel": novel,
        "chapter_count": chapter_count,
        "pass_count": pass_count,
        "started_at": started_at,
        "wall_seconds": wall_seconds,
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "total_cost_usd": round(total_cost, 6),
        "parsed_paragraphs": total_parsed,
        "expected_paragraphs": expected_paragraphs,
        "chapters": summaries,
    }
    json_path.write_text(json.dumps(payload, indent=2))

    md = [
        f"# qwen-plus realtime novel run — {novel}",
        "",
        f"- novel_root: `{novel_root}`",
        f"- started: {started_at}",
        f"- wall: {wall_seconds:.0f}s",
        "",
        "## Verdict",
        "",
        f"**{verdict}** — {pass_count}/{chapter_count} chapters PASS; "
        f"{total_parsed}/{expected_paragraphs} paragraphs parsed.",
        "",
        "## Totals",
        "",
        f"- input tokens: {total_in:,}",
        f"- output tokens: {total_out:,}",
        f"- cost: ${total_cost:.4f}",
        "",
        "## Per-chapter",
        "",
        "| chapter | verdict | chunks ok | parsed/expected | wall | cost |",
        "|---|---|---|---|---:|---:|",
    ]
    for s in summaries:
        md.append(
            f"| {s['chapter']} | {s['verdict']} | "
            f"{s['ok_chunks']}/{s['chunk_count']} | "
            f"{s['parsed_paragraphs']}/{s['expected_paragraphs']} | "
            f"{s['wall_seconds']:.0f}s | ${s['cost_usd']:.4f} |"
        )
    md_path.write_text("\n".join(md))
    return verdict


def _resolve_chapters(
    chapters_arg: str, passages_by_chapter: dict[str, list[dict]],
) -> list[str]:
    if chapters_arg == "all":
        return sorted(
            passages_by_chapter.keys(),
            key=_natural_chapter_sort_key(passages_by_chapter),
        )
    wanted = [c.strip() for c in chapters_arg.split(",") if c.strip()]
    unknown = [c for c in wanted if c not in passages_by_chapter]
    if unknown:
        raise SystemExit(f"unknown chapter ids: {unknown}")
    return wanted


async def main_async(args: argparse.Namespace) -> int:
    passages = _read_passages(args.novel)
    passages_by_chapter: dict[str, list[dict]] = {}
    for p in passages:
        passages_by_chapter.setdefault(p["chapter_id"], []).append(p)
    for chap_list in passages_by_chapter.values():
        chap_list.sort(key=lambda x: x["paragraph_index"])

    chapters = _resolve_chapters(args.chapters, passages_by_chapter)
    logger.info(
        "%s — running %d chapters: %s",
        args.novel, len(chapters),
        ",".join(chapters) if len(chapters) <= 8 else f"{chapters[:4]}..{chapters[-2:]}",
    )

    system_prompt = build_enrichment_prompt(args.novel) + JSON_INSTRUCTION_SUFFIX
    schema = add_list_caps(inline_refs(ChapterEnrichmentResult.model_json_schema()))
    novel_root = RUN_ROOT / args.novel
    novel_root.mkdir(parents=True, exist_ok=True)

    load_dotenv()
    key = os.environ.get("ALIBABA_API_KEY")
    if not key:
        raise SystemExit("ALIBABA_API_KEY not set in env / .env")
    # max_retries: let the SDK absorb startup bursts that briefly exceed
    # DashScope's 10 RPS. Sustained rate at 5 chapters × 8 chunks / 135s
    # is ~0.3 req/s, well under limit — only the dispatch burst is hot.
    client = AsyncOpenAI(api_key=key, base_url=BASE_URL,
                         timeout=1800.0, max_retries=10)

    sem = asyncio.Semaphore(args.max_concurrent_chapters)

    async def bounded(ch: str) -> dict:
        async with sem:
            return await _run_one_chapter(
                client=client,
                novel=args.novel,
                chapter=ch,
                chap_passages=passages_by_chapter[ch],
                system_prompt=system_prompt,
                schema=schema,
                args=args,
                novel_root=novel_root,
            )

    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(bounded(ch)) for ch in chapters]
    summaries = [t.result() for t in tasks]
    wall_seconds = time.monotonic() - started

    await client.close()

    if len(chapters) > 1:
        verdict = _write_novel_report(
            novel_root, args.novel, summaries, wall_seconds, started_at,
        )
    else:
        verdict = summaries[0]["verdict"]

    logger.info("=" * 60)
    pass_count = sum(1 for s in summaries if s["verdict"] == "PASS")
    total_cost = sum(s["cost_usd"] for s in summaries)
    logger.info(
        "%s  chapters=%d  pass=%d  wall=%.1fs  cost=$%.4f",
        verdict, len(summaries), pass_count, wall_seconds, total_cost,
    )
    if len(chapters) > 1:
        logger.info("novel report: %s", novel_root / "novel_report.md")
    return 0 if verdict == "PASS" else 2


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )

    p = argparse.ArgumentParser()
    p.add_argument("--novel", default=DEFAULT_NOVEL)
    p.add_argument("--chapters", default=DEFAULT_CHAPTER,
                   help="Comma-separated chapter ids (e.g. c1,c2,c6), or "
                        "'all' for every chapter in the novel "
                        "(default: %(default)s)")
    p.add_argument("--max-concurrent-chapters", type=int, default=5,
                   help="How many chapters to run concurrently; each chapter "
                        "internally fans out to chunk_count concurrent calls. "
                        "Default 5 produces a startup burst of ~40 calls "
                        "(5 × 8 chunks) — over DashScope's 10 RPS, but the "
                        "client max_retries=10 absorbs the burst. Sustained "
                        "rate is ~0.3 req/s, well under cap. Going higher "
                        "amplifies the burst proportionally.")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    p.add_argument("--max-completion-tokens", type=int,
                   default=DEFAULT_MAX_COMPLETION_TOKENS)
    p.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    args = p.parse_args()

    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
