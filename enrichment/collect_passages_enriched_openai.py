"""Poll an OpenAI batch and collect enrichment results.

Parallels enrichment/collect_passages_enriched.py (the Anthropic
collector) for the OpenAI Batch + Responses API path. Reads the
batch_manifest.openai.json written by submit_passages_enriched_openai.py.

Output: data/novels/<key>/passages_enriched.openai_5_mini.json
(suffixed so the existing Anthropic-derived passages_enriched.json
stays as the production default). Production consumers can pick the
right file at runtime.

Usage:
  uv run python -m enrichment.collect_passages_enriched_openai --novel bleak_house
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

import openai
from dotenv import load_dotenv

from enrichment.novel_prompts import NOVEL_CONFIGS
from enrichment.schemas import ChapterEnrichmentResult, Passage
from enrichment.timing import Recorder

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
NOVEL_KEYS = sorted(NOVEL_CONFIGS.keys())

POLL_TIMEOUT_SECONDS = 86400  # 24h, matches the SLA

# Graduated polling schedule. The batch SLA is 24h best-effort but
# typically completes in 1-6h, so a fixed short interval just wastes
# API calls. Schedule: start at 5min, step up to 30min after a few
# polls. Total ~55 polls over 24h instead of 1440 at the old 60s.
POLL_SCHEDULE_SECONDS: list[int] = (
    [300] * 3      # 0-15 min:   3 × 5min
    + [600] * 3    # 15-45 min:  3 × 10min
    + [900] * 3    # 45-90 min:  3 × 15min
    + [1200] * 3   # 90-150 min: 3 × 20min
    # After 150 min, fall through to the 30-minute cap below.
)
POLL_INTERVAL_CAP_SECONDS = 1800  # 30 minutes


def _read_passages(novel_dir: Path) -> list[dict]:
    """Same fallback as submit: raw if present, else strip enriched."""
    raw_path = novel_dir / "passages_raw.json"
    if raw_path.exists():
        return json.loads(raw_path.read_text())
    enriched_path = novel_dir / "passages_enriched.json"
    if not enriched_path.exists():
        raise FileNotFoundError(
            f"Neither {raw_path} nor {enriched_path} found."
        )
    data = json.loads(enriched_path.read_text())
    return [{k: v for k, v in p.items() if k != "enrichment"} for p in data]


def _extract_response_text(response_body: dict) -> str:
    """Extract the model-emitted text from a Responses API response.

    The Responses API output shape:
      {"output": [
        {"type": "message", "role": "assistant",
         "content": [{"type": "output_text", "text": "..."}, ...]},
        ...
      ]}
    Concatenate all output_text content blocks across all message items.
    """
    output = response_body.get("output", []) or []
    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content", []) or []
        for c in content:
            if not isinstance(c, dict):
                continue
            t = c.get("type")
            if t in ("output_text", "text"):
                txt = c.get("text", "")
                if isinstance(txt, str):
                    chunks.append(txt)
    return "".join(chunks)


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
        "--output-suffix",
        type=str,
        default="openai_5_mini",
        help=(
            "Suffix for the output file: passages_enriched.<suffix>.json. "
            "Default 'openai_5_mini'. Set to '' to write the bare "
            "passages_enriched.json (will overwrite the Anthropic-derived "
            "version, so use cautiously)."
        ),
    )
    args = parser.parse_args()

    novel_dir = DATA_DIR / "novels" / args.novel
    manifest_path = novel_dir / "batch_manifest.openai.json"
    output_name = (
        f"passages_enriched.{args.output_suffix}.json"
        if args.output_suffix
        else "passages_enriched.json"
    )
    output_path = novel_dir / output_name

    load_dotenv()
    manifest = json.loads(manifest_path.read_text())
    batch_id = manifest["batch_id"]
    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    # Poll until batch finalised, using a graduated schedule:
    # 5 min × 3, 10 min × 3, 15 min × 3, 20 min × 3, then 30 min thereafter.
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    final_states = {"completed", "failed", "expired", "cancelled"}
    batch = None
    poll_idx = 0
    while time.monotonic() < deadline:
        batch = client.batches.retrieve(batch_id)
        status = batch.status
        rc = getattr(batch, "request_counts", None)
        rc_str = (
            f" (total={rc.total} completed={rc.completed} failed={rc.failed})"
            if rc is not None else ""
        )
        logger.info("Batch %s status: %s%s", batch_id, status, rc_str)
        if status in final_states:
            break
        # Pick next interval from the schedule, falling through to the cap.
        if poll_idx < len(POLL_SCHEDULE_SECONDS):
            wait_s = POLL_SCHEDULE_SECONDS[poll_idx]
        else:
            wait_s = POLL_INTERVAL_CAP_SECONDS
        poll_idx += 1
        logger.info(
            "Poll #%d done; sleeping %d min before next check...",
            poll_idx, wait_s // 60,
        )
        time.sleep(wait_s)
    else:
        logger.error(
            "Timed out after %ds waiting for batch %s",
            POLL_TIMEOUT_SECONDS, batch_id,
        )
        return

    if batch.status != "completed":
        logger.error(
            "Batch %s ended in status %s; checking error file",
            batch_id, batch.status,
        )

    # Load raw passages for merge
    raw_passages = _read_passages(novel_dir)
    passages_by_key: dict[tuple[str, int], dict] = {}
    for p in raw_passages:
        passages_by_key[(p["chapter_id"], p["paragraph_index"])] = p

    enriched: list[dict] = []
    failed_ids: list[str] = []
    succeeded = 0

    timings_path = novel_dir / f"passage_enrichment_timings.{args.output_suffix or 'openai'}.json"
    recorder = Recorder(flush_path=timings_path)

    # Output file is JSONL, one record per request
    output_file_id = getattr(batch, "output_file_id", None)
    if output_file_id:
        logger.info("Downloading output file %s...", output_file_id)
        content_resp = client.files.content(output_file_id)
        # `content_resp` is an HttpxBinaryResponseContent; read text via .text
        try:
            output_text = content_resp.text
        except AttributeError:
            # Some SDK versions expose .read() returning bytes
            output_text = content_resp.read().decode()

        for line_idx, line in enumerate(output_text.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("Output line %d: JSON parse failed: %s", line_idx, exc)
                continue
            custom_id = entry.get("custom_id", f"line-{line_idx}")
            err = entry.get("error")
            response = entry.get("response")
            if err is not None or response is None:
                logger.warning("Request %s: error %r", custom_id, err)
                failed_ids.append(custom_id)
                continue
            status_code = response.get("status_code")
            if status_code != 200:
                logger.warning(
                    "Request %s: HTTP %s — %s",
                    custom_id, status_code, response.get("body"),
                )
                failed_ids.append(custom_id)
                continue

            body = response.get("body") or {}

            # Record usage. Responses API usage shape: input_tokens,
            # output_tokens, reasoning_tokens (separate).
            usage = body.get("usage", {}) or {}
            input_tokens = int(usage.get("input_tokens", 0) or 0)
            output_tokens = int(usage.get("output_tokens", 0) or 0)
            reasoning_tokens = int(
                usage.get("output_tokens_details", {}).get("reasoning_tokens", 0)
                or usage.get("reasoning_tokens", 0)
                or 0
            )
            recorder.record(
                kind="model",
                name=body.get("model", manifest.get("model", "gpt-5-mini")),
                label=f"passage_enrichment {custom_id}",
                duration_s=0.0,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                # Reuse cache_creation_input_tokens to track reasoning_tokens
                # so the existing Recorder schema doesn't need a new field.
                # Document this in the manifest for readers.
                cache_creation_input_tokens=reasoning_tokens,
                cache_read_input_tokens=0,
                batch=True,
            )

            content_text = _extract_response_text(body)
            if not content_text:
                logger.warning("Request %s: no text content", custom_id)
                failed_ids.append(custom_id)
                continue

            try:
                result = ChapterEnrichmentResult.model_validate_json(content_text)
            except Exception as exc:
                logger.warning(
                    "Request %s: failed to parse response: %s",
                    custom_id, str(exc)[:200],
                )
                failed_ids.append(custom_id)
                continue
            succeeded += 1

            for pe in result.enrichments:
                key = (result.chapter_id, pe.paragraph_index)
                raw = passages_by_key.get(key)
                if raw is None:
                    logger.warning(
                        "No raw passage for %s:p%d",
                        result.chapter_id, pe.paragraph_index,
                    )
                    continue
                passage = Passage(**{**raw, "enrichment": pe.enrichment})
                enriched.append(passage.model_dump())

    error_file_id = getattr(batch, "error_file_id", None)
    if error_file_id:
        logger.info("Batch has an error file; downloading for diagnostics.")
        try:
            err_resp = client.files.content(error_file_id)
            err_text = err_resp.text if hasattr(err_resp, "text") else err_resp.read().decode()
            err_path = novel_dir / f"batch_errors.{args.output_suffix or 'openai'}.jsonl"
            err_path.write_text(err_text)
            logger.info("Saved errors to %s (%d bytes)", err_path, len(err_text))
        except Exception as exc:
            logger.warning("Failed to download error file: %s", exc)

    output_path.write_text(json.dumps(enriched, indent=2))
    logger.info(
        "Collected %d enriched passages from %d succeeded requests",
        len(enriched), succeeded,
    )
    if failed_ids:
        logger.warning("Failed request IDs: %s", failed_ids)

    timings_path.write_text(json.dumps(recorder.to_dict(), indent=2))
    logger.info(
        "Recorded %d batch requests to %s",
        len(recorder.events), timings_path,
    )

    manifest["status"] = "collected"
    manifest["succeeded"] = succeeded
    manifest["failed_ids"] = failed_ids
    manifest["output_path"] = str(output_path)
    manifest_path.write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
