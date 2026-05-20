"""Poll a DashScope batch enrichment probe to completion + write a report.

Companion to scripts/submit_dashscope_batch_enrichment.py. Reads the
manifest the submitter wrote, polls until the batch reaches a terminal
state (no hard timeout — Ctrl+C and re-run is idempotent), downloads
the result file, validates each line against ChapterEnrichmentResult,
classifies defects, and writes probe_report.{json,md}.

Tracks BleakHouse-el1j.1.

Run:
    uv run python scripts/collect_dashscope_batch_enrichment.py \\
        data/runs/_qwen_plus_batch_enrichment_probe/bleak_house_c6

Re-running is safe: if batch_output.jsonl is already present, the
poll/download steps are skipped and the report is regenerated from
the cached output. Useful if you want to tweak the analysis without
re-spending API budget.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import ValidationError

from enrichment.llm.schemas import ChapterEnrichmentResult

logger = logging.getLogger("collect_dashscope_batch")

BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

# qwen-plus batch rates (intl, ≤256K input bucket, 50% off realtime).
RATE_INPUT_PER_MTOK = 0.20
RATE_OUTPUT_PER_MTOK = 0.60

DEFAULT_POLL_SECONDS = 30

# Any 20+ char run repeated 4+ consecutive times → likely repetition-loop
# pathology (cf. [[project_gemma4_repetition_bug]]).
REPETITION_RE = re.compile(r"(.{20,})\1{3,}")


@dataclass
class RequestResult:
    custom_id: str
    chapter_id: str
    chunk_index: int
    paragraph_indices: list[int]
    finish_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    raw_content: str | None = None
    validation: str = "n/a"
    parsed: dict[str, Any] | None = None
    defect: str | None = None


@dataclass
class ProbeReport:
    novel: str
    chapter: str
    model: str
    batch_id: str
    submitted_at: str
    completed_at: str | None = None
    wall_seconds: float = 0.0
    request_count: int = 0
    valid_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    defects: dict[str, int] = field(default_factory=dict)
    results: list[RequestResult] = field(default_factory=list)

    @property
    def validity_rate(self) -> float:
        return self.valid_count / self.request_count if self.request_count else 0.0


def _make_client() -> OpenAI:
    load_dotenv()
    key = os.environ.get("ALIBABA_API_KEY")
    if not key:
        raise SystemExit("ALIBABA_API_KEY not set in env / .env")
    return OpenAI(api_key=key, base_url=BASE_URL, timeout=600.0, max_retries=0)


def _poll_until_terminal(client: OpenAI, batch_id: str, poll_seconds: int) -> Any:
    """Poll until the batch leaves the in-progress family. No hard timeout —
    DashScope's own 24h completion window is the upper bound; Ctrl+C + re-run
    is the recovery path."""
    start = time.monotonic()
    in_flight = {"in_progress", "validating", "finalizing"}
    last_log = 0.0
    while True:
        batch = client.batches.retrieve(batch_id)
        elapsed = time.monotonic() - start
        if batch.status not in in_flight or elapsed - last_log > 60:
            counts = getattr(batch, "request_counts", None)
            counts_str = (
                f" counts={counts.completed}/{counts.total} "
                f"(failed={counts.failed})" if counts else ""
            )
            logger.info("status=%s  elapsed=%.0fs%s",
                        batch.status, elapsed, counts_str)
            last_log = elapsed
        if batch.status not in in_flight:
            return batch
        time.sleep(poll_seconds)


def _process_entry(
    entry: dict, indices_by_custom_id: dict[str, list[int]], chapter_id: str,
) -> RequestResult:
    """Process one JSONL line from output OR error file.

    Handles every failure shape we've observed or anticipate:
    - top-level `error` (entry-level API rejection)
    - response.body.error (server-side error like ModelServingOutputInvalidJsonError)
    - empty/missing choices
    - empty message.content
    - JSON parse failure
    - Pydantic validation failure
    - repetition-loop pathology in otherwise-parseable content
    """
    custom_id = entry.get("custom_id", "")
    indices = indices_by_custom_id.get(custom_id, [])
    chunk_index = (
        int(custom_id.rsplit("-part", 1)[1]) if "-part" in custom_id else 0
    )

    rr = RequestResult(
        custom_id=custom_id, chapter_id=chapter_id,
        chunk_index=chunk_index, paragraph_indices=indices,
    )

    resp = entry.get("response") or {}
    body = resp.get("body") or {}
    usage = body.get("usage") or {}
    rr.input_tokens = int(usage.get("prompt_tokens") or 0)
    rr.output_tokens = int(usage.get("completion_tokens") or 0)
    rr.cost_usd = (
        rr.input_tokens / 1_000_000 * RATE_INPUT_PER_MTOK
        + rr.output_tokens / 1_000_000 * RATE_OUTPUT_PER_MTOK
    )

    # Entry-level error (e.g. submitter passed a malformed line).
    top_err = entry.get("error")
    if top_err:
        code = top_err.get("code", "?")
        msg = (top_err.get("message") or "")[:200]
        rr.validation = f"failed: entry-level error {code}: {msg}"
        rr.defect = "api_error"
        return rr

    # Server-side error returned inside response.body (the
    # ModelServingOutputInvalidJsonError class from DashScope sits here).
    body_err = body.get("error")
    if body_err:
        code = body_err.get("code", "?")
        msg = (body_err.get("message") or "")[:200]
        status = resp.get("status_code")
        rr.validation = f"failed: server error {code} (status={status}): {msg}"
        rr.defect = "api_error"
        return rr

    choices = body.get("choices") or []
    if not choices:
        rr.validation = (
            f"failed: empty choices (status={resp.get('status_code')})"
        )
        rr.defect = "empty"
        return rr

    choice = choices[0]
    rr.finish_reason = choice.get("finish_reason")
    message = choice.get("message") or {}
    rr.raw_content = message.get("content")
    if not rr.raw_content:
        rr.validation = f"failed: empty content (finish={rr.finish_reason})"
        rr.defect = "empty"
        return rr

    try:
        obj = json.loads(rr.raw_content)
    except json.JSONDecodeError as e:
        rr.validation = f"failed: JSONDecodeError: {e}"
        rr.defect = "json_parse"
        return rr

    try:
        parsed = ChapterEnrichmentResult.model_validate(obj)
        rr.parsed = parsed.model_dump()
        rr.validation = "ok"
    except ValidationError as e:
        rr.validation = f"failed: ValidationError: {e.error_count()} errors"
        rr.defect = "validation"

    # Even successfully-parsed JSON can still be repetition-pathology output.
    if rr.defect is None and REPETITION_RE.search(rr.raw_content):
        rr.defect = "repetition"

    return rr


def _process_results(
    output_text: str,
    error_text: str,
    indices_by_custom_id: dict[str, list[int]],
    chapter_id: str,
) -> list[RequestResult]:
    """Process every JSONL line from both files (whichever are populated).
    Lines may appear in either file; each becomes a RequestResult."""
    results: list[RequestResult] = []
    for label, text in (("output", output_text), ("errors", error_text)):
        if not text.strip():
            continue
        for line_no, line in enumerate(text.strip().splitlines(), 1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning(
                    "skipping unparseable %s line %d: %s", label, line_no, e
                )
                continue
            results.append(_process_entry(entry, indices_by_custom_id, chapter_id))
    return results


def _write_reports(report: ProbeReport, probe_dir: Path) -> str:
    json_path = probe_dir / "probe_report.json"
    md_path = probe_dir / "probe_report.md"

    pass_validity = report.validity_rate >= 0.95
    pass_pathology = report.defects.get("repetition", 0) == 0
    verdict = "PASS" if (pass_validity and pass_pathology) else "FAIL"

    payload = {
        "verdict": verdict,
        "novel": report.novel,
        "chapter": report.chapter,
        "model": report.model,
        "batch_id": report.batch_id,
        "submitted_at": report.submitted_at,
        "completed_at": report.completed_at,
        "wall_seconds": report.wall_seconds,
        "request_count": report.request_count,
        "valid_count": report.valid_count,
        "validity_rate": report.validity_rate,
        "total_input_tokens": report.total_input_tokens,
        "total_output_tokens": report.total_output_tokens,
        "total_cost_usd": round(report.total_cost_usd, 6),
        "rates_per_mtok": {
            "input": RATE_INPUT_PER_MTOK,
            "output": RATE_OUTPUT_PER_MTOK,
        },
        "defects": report.defects,
        "per_request": [
            {
                "custom_id": r.custom_id,
                "validation": r.validation,
                "finish_reason": r.finish_reason,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "cost_usd": round(r.cost_usd, 6),
                "defect": r.defect,
                "paragraph_count": len(r.paragraph_indices),
            }
            for r in report.results
        ],
    }
    json_path.write_text(json.dumps(payload, indent=2))

    md = [
        f"# DashScope batch probe — {report.novel}/{report.chapter}",
        "",
        f"- batch_id: `{report.batch_id}`",
        f"- model: {report.model}",
        f"- submitted: {report.submitted_at}",
        f"- completed: {report.completed_at}",
        f"- wall: {report.wall_seconds:.0f}s",
        "",
        "## Verdict",
        "",
        f"**{verdict}** — validity {report.validity_rate:.1%} "
        f"(threshold ≥95%); repetition defects "
        f"{report.defects.get('repetition', 0)} (threshold 0). "
        f"Wall-time {report.wall_seconds:.0f}s (informational).",
        "",
        "## Numbers",
        "",
        f"- requests: {report.request_count}",
        f"- valid: {report.valid_count}",
        f"- validity_rate: {report.validity_rate:.1%}",
        f"- input tokens: {report.total_input_tokens:,}",
        f"- output tokens: {report.total_output_tokens:,}",
        f"- cost: ${report.total_cost_usd:.4f} "
        f"(at ${RATE_INPUT_PER_MTOK}/M in, ${RATE_OUTPUT_PER_MTOK}/M out)",
        "",
        "## Defects",
        "",
    ]
    if report.defects:
        for k, v in sorted(report.defects.items()):
            md.append(f"- {k}: {v}")
    else:
        md.append("- (none)")
    md += [
        "",
        "## Per-request",
        "",
        "| custom_id | validation | finish | in | out | cost | defect |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for r in report.results:
        v = r.validation[:40] + ("…" if len(r.validation) > 40 else "")
        md.append(
            f"| `{r.custom_id}` | {v} | {r.finish_reason or '-'} | "
            f"{r.input_tokens} | {r.output_tokens} | ${r.cost_usd:.4f} | "
            f"{r.defect or '-'} |"
        )
    md_path.write_text("\n".join(md))
    return verdict


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )

    p = argparse.ArgumentParser()
    p.add_argument("probe_dir", type=Path,
                   help="Directory containing manifest.json from the submitter")
    p.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS,
                   help="Poll interval (default: %(default)s)")
    p.add_argument("--force-poll", action="store_true",
                   help="Re-poll/re-download even if batch_output.jsonl exists.")
    args = p.parse_args()

    probe_dir: Path = args.probe_dir
    manifest_path = probe_dir / "manifest.json"
    state_path = probe_dir / "batch_state.json"
    output_path = probe_dir / "batch_output.jsonl"
    errors_path = probe_dir / "batch_errors.jsonl"

    if not manifest_path.exists():
        raise SystemExit(f"no manifest at {manifest_path} — submit first")
    manifest = json.loads(manifest_path.read_text())
    batch_id = manifest["batch_id"]
    submitted_at = manifest["submitted_at"]
    novel = manifest["novel"]
    chapter = manifest["chapter"]
    model = manifest["model"]
    indices_by_custom_id = manifest["indices_by_custom_id"]

    logger.info("probe_dir=%s  batch_id=%s", probe_dir, batch_id)

    client = _make_client()

    # Phase 1: poll until terminal, then persist the full batch state.
    # If we already have a terminal state on disk we skip the poll —
    # batch_state.json is the durable record. --force-poll bypasses the
    # cache for cases where you want to re-verify.
    cached_state = None
    if state_path.exists() and not args.force_poll:
        cached_state = json.loads(state_path.read_text())
        cached_id = cached_state.get("id")
        if cached_id and cached_id != batch_id:
            logger.warning(
                "%s has batch_id=%s, manifest has %s — discarding stale state",
                state_path, cached_id, batch_id,
            )
            cached_state = None
        elif cached_state.get("status") in (
            "completed", "failed", "expired", "cancelled"
        ):
            logger.info("loading cached %s (status=%s)",
                        state_path, cached_state["status"])
        else:
            cached_state = None  # re-poll: previous run died mid-poll

    if cached_state is None:
        poll_start = time.monotonic()
        batch = _poll_until_terminal(client, batch_id, args.poll_seconds)
        wall_seconds = time.monotonic() - poll_start
        completed_at = datetime.now(timezone.utc).isoformat()
        logger.info("terminal status=%s  wall=%.0fs", batch.status, wall_seconds)

        # Persist EVERYTHING the SDK returned before doing anything else.
        # If the script crashes later, this is the receipt of what DashScope
        # actually said.
        batch_state = batch.model_dump(mode="json")
        batch_state["_collect_wall_seconds"] = wall_seconds
        batch_state["_collect_completed_at"] = completed_at
        state_path.write_text(json.dumps(batch_state, indent=2, default=str))
        logger.info("persisted batch state to %s", state_path)
    else:
        batch_state = cached_state
        wall_seconds = batch_state.get("_collect_wall_seconds", 0.0)
        completed_at = batch_state.get("_collect_completed_at")

    # Phase 2: download both files defensively. Either can be None; both can be
    # absent on a failed-batch state. Errors during download are logged, not
    # raised — the next phase will surface what we have.
    output_file_id = batch_state.get("output_file_id")
    error_file_id = batch_state.get("error_file_id")
    logger.info("output_file_id=%s  error_file_id=%s",
                output_file_id, error_file_id)

    out_text = ""
    err_text = ""

    if output_path.exists():
        out_text = output_path.read_text()
        logger.info("loaded cached output (%d bytes)", len(out_text))
    elif output_file_id:
        try:
            out_text = client.files.content(output_file_id).text
            output_path.write_text(out_text)
            logger.info("wrote output to %s (%d bytes)",
                        output_path, len(out_text))
        except Exception as e:
            logger.exception("output download failed (%s): %s", output_file_id, e)

    if errors_path.exists():
        err_text = errors_path.read_text()
        logger.info("loaded cached errors (%d bytes)", len(err_text))
    elif error_file_id:
        try:
            err_text = client.files.content(error_file_id).text
            errors_path.write_text(err_text)
            logger.info("wrote errors to %s (%d bytes)",
                        errors_path, len(err_text))
        except Exception as e:
            logger.exception("error file download failed (%s): %s", error_file_id, e)

    # Phase 3: process whatever's on disk. Both files contribute one
    # RequestResult per line; missing files just produce no entries.
    results = _process_results(out_text, err_text, indices_by_custom_id, chapter)
    if not results:
        # Batch reached terminal but neither output nor error file is usable
        # — surface this as a single synthetic result so the report doesn't
        # silently say "0 requests" without explanation.
        synthetic = RequestResult(
            custom_id="<no-output>",
            chapter_id=chapter,
            chunk_index=0,
            paragraph_indices=[],
            validation=(
                f"failed: batch status={batch_state.get('status')} produced "
                f"no parseable output (output_file_id={output_file_id}, "
                f"error_file_id={error_file_id})"
            ),
            defect="api_error",
        )
        results = [synthetic]

    defects: dict[str, int] = {}
    valid_count = 0
    total_in = total_out = 0
    total_cost = 0.0
    for r in results:
        if r.validation == "ok":
            valid_count += 1
        if r.defect:
            defects[r.defect] = defects.get(r.defect, 0) + 1
        total_in += r.input_tokens
        total_out += r.output_tokens
        total_cost += r.cost_usd

    report = ProbeReport(
        novel=novel, chapter=chapter, model=model,
        batch_id=batch_id, submitted_at=submitted_at,
        completed_at=completed_at, wall_seconds=wall_seconds,
        request_count=len(results), valid_count=valid_count,
        total_input_tokens=total_in, total_output_tokens=total_out,
        total_cost_usd=total_cost, defects=defects, results=results,
    )
    verdict = _write_reports(report, probe_dir)
    logger.info("=" * 60)
    logger.info("%s  validity=%.1f%%  wall=%.0fs  cost=$%.4f  defects=%s",
                verdict, 100 * report.validity_rate, wall_seconds,
                total_cost, defects or "{}")
    logger.info("report: %s", probe_dir / "probe_report.md")
    return 0 if verdict == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
