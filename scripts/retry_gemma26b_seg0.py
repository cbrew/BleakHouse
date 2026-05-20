"""Retry gemma-4-26b-a4b on the failing seg-0 to characterise stability.

Per BleakHouse-dll8: the first benchmark run produced a degenerate
output (17 lines of valid JSON head, then 8112 lines of '\\n' padding
to fill the 16K cap). The earlier smoke-test run on the same prompt
produced valid output. This script runs N retries to estimate the
fail-rate at default sampler settings, so we can decide whether the
candidate fails the structural gate or is just noisy on opening
segments.

Writes per-attempt JSON to
data/eval/stage2_tier_l_prose/gemma-4-26b-a4b/segment_..._0.retry<k>.json
and prints a one-line summary per attempt.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from enrichment.generate_podcast import build_messages  # noqa: E402
from enrichment.llm import generate as llm_generate  # noqa: E402
from enrichment.llm import settings  # noqa: E402
from enrichment.llm.types import GenerationRequest, ModelSpec  # noqa: E402
from enrichment.llm.schemas import EpisodeSegment  # Re-use the same fixture-loading helper.
from enrichment.personas import DEFAULT_PERSONAS
from scripts.run_eval_tier_l_prose import (  # noqa: E402
    CANDIDATES,
    OUTPUT_ROOT,
    TASK,
    _RUN_TO_NOVEL,
    _validate_schema,
    load_segment,
)

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("retry-gemma26b-seg0")

CAND_ID = "gemma-4-26b-a4b"
RUN_ID = "bh_trn_literary_hostprep_short"
SEG_IDX = 0
N_ATTEMPTS = 3


def classify_failure(raw_text: str) -> str:
    """Distinguish degenerate-loop from real truncation."""
    lines = raw_text.splitlines()
    if not lines:
        return "empty"
    nonblank = sum(1 for ln in lines if ln.strip())
    blank_ratio = 1 - (nonblank / len(lines))
    if blank_ratio > 0.9 and len(lines) > 100:
        return f"degenerate_newline_loop ({nonblank}/{len(lines)} nonblank)"
    return "truncated_or_malformed"


def main() -> None:
    spec: ModelSpec = CANDIDATES[CAND_ID]
    settings.register_task(TASK, spec)
    schema = EpisodeSegment.model_json_schema()

    os.environ["BLEAKHOUSE_NOVEL"] = _RUN_TO_NOVEL[RUN_ID]
    segment, brief, prev_t, next_t, is_first = load_segment(RUN_ID, SEG_IDX)
    system_msg, user_msg = build_messages(
        segment, DEFAULT_PERSONAS, is_first, 2,
        previous_segment_title=prev_t,
        next_segment_title=next_t,
        host_brief=brief,
        length="short",
    )

    cand_dir = OUTPUT_ROOT / CAND_ID
    cand_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for k in range(1, N_ATTEMPTS + 1):
        log.info("=== attempt %d/%d ===", k, N_ATTEMPTS)
        out_path = cand_dir / f"segment_{RUN_ID}_{SEG_IDX}.retry{k}.json"
        try:
            t0 = time.monotonic()
            r = llm_generate(GenerationRequest(
                task=TASK,
                system=system_msg,
                user=user_msg,
                max_tokens=16384,
                json_schema=schema,
            ))
            wall = time.monotonic() - t0
            ok, parsed, err = _validate_schema(r.text)
            record = {
                "attempt": k,
                "candidate_id": CAND_ID,
                "run_id": RUN_ID,
                "seg_idx": SEG_IDX,
                "model": spec.model,
                "wall_seconds": wall,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "schema_valid": ok,
                "schema_error": err,
                "failure_mode": None if ok else classify_failure(r.text),
                "raw_text": r.text,
                "output": parsed,
            }
            log.info(
                "  schema_valid=%s in=%d out=%d wall=%.1fs%s",
                ok, r.input_tokens or 0, r.output_tokens or 0, wall,
                "" if ok else f"  FAILURE_MODE={record['failure_mode']}",
            )
        except Exception as e:  # noqa: BLE001
            log.error("  FAILED: %s", e)
            record = {
                "attempt": k,
                "candidate_id": CAND_ID,
                "run_id": RUN_ID,
                "seg_idx": SEG_IDX,
                "model": spec.model,
                "error": str(e),
                "schema_valid": False,
            }
        out_path.write_text(json.dumps(record, indent=2, default=str))
        results.append({
            "attempt": k,
            "schema_valid": record.get("schema_valid"),
            "wall": record.get("wall_seconds"),
            "out_tokens": record.get("output_tokens"),
            "failure_mode": record.get("failure_mode"),
        })

    log.info("=== summary ===")
    valid_n = sum(1 for r in results if r["schema_valid"])
    log.info("valid: %d/%d", valid_n, N_ATTEMPTS)
    for r in results:
        log.info("  attempt %d: valid=%s wall=%s out_tok=%s mode=%s",
                 r["attempt"], r["schema_valid"], r["wall"],
                 r["out_tokens"], r["failure_mode"])


if __name__ == "__main__":
    main()
