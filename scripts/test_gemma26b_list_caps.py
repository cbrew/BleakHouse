"""Test scoped remedy for gemma-4-26b-a4b degenerate-loop failure.

Per BleakHouse-dll8: gemma-4-26b-a4b on bh_trn_literary_hostprep_short
seg-0 produces a degenerate newline-loop (after "emphasis_words": ) at
~40% rate at default sampler. Hypothesis: vLLM constrained-decoder
pathology on unbounded list[str] field, same family as the documented
emotional_register loop bug (openai_compatible_provider.py:217-224).

This script tests whether passing `list_field_caps={"emphasis_words": 3}`
through the seam — scoped to this one candidate — eliminates the
failure. Runs N attempts on the failing prompt with caps applied;
compares against the baseline 3/5 valid we already have on file.

Scope: only applies caps when the candidate spec is gemma-4-26b-a4b
on DeepInfra. No global change to production routing.
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
from enrichment.llm.types import GenerationRequest  # noqa: E402
from enrichment.llm.schemas import EpisodeSegment
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
log = logging.getLogger("test-gemma26b-list-caps")

CAND_ID = "gemma-4-26b-a4b"
RUN_ID = "bh_trn_literary_hostprep_short"
SEG_IDX = 0
N_ATTEMPTS = 5

# Scoped remedy — applied only when candidate is this gemma 26B MoE on
# DeepInfra. emphasis_words is the empirical failure point; turns /
# utterances are intentionally unbounded (real episode shape varies).
LIST_FIELD_CAPS_BY_CANDIDATE: dict[str, dict[str, int]] = {
    "gemma-4-26b-a4b": {"emphasis_words": 3},
}


def classify_failure(raw_text: str) -> str:
    lines = raw_text.splitlines()
    if not lines:
        return "empty"
    nonblank = sum(1 for ln in lines if ln.strip())
    blank_ratio = 1 - (nonblank / len(lines))
    if blank_ratio > 0.9 and len(lines) > 100:
        return f"degenerate_newline_loop ({nonblank}/{len(lines)} nonblank)"
    return "truncated_or_malformed"


def main() -> None:
    spec = CANDIDATES[CAND_ID]
    settings.register_task(TASK, spec)
    schema = EpisodeSegment.model_json_schema()
    caps = LIST_FIELD_CAPS_BY_CANDIDATE.get(CAND_ID)
    assert caps is not None, f"no scoped caps configured for {CAND_ID}"
    log.info("Applying scoped list_field_caps for %s: %s", CAND_ID, caps)

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
    out_dir = cand_dir / "list_caps_probe"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for k in range(1, N_ATTEMPTS + 1):
        log.info("=== attempt %d/%d (with list_field_caps) ===", k, N_ATTEMPTS)
        out_path = out_dir / f"attempt{k}.json"
        try:
            t0 = time.monotonic()
            r = llm_generate(GenerationRequest(
                task=TASK,
                system=system_msg,
                user=user_msg,
                max_tokens=16384,
                json_schema=schema,
                list_field_caps=caps,
            ))
            wall = time.monotonic() - t0
            ok, parsed, err = _validate_schema(r.text)
            mode = None if ok else classify_failure(r.text)
            log.info(
                "  schema_valid=%s in=%d out=%d wall=%.1fs%s",
                ok, r.input_tokens or 0, r.output_tokens or 0, wall,
                "" if ok else f"  FAILURE_MODE={mode}",
            )
            record = {
                "attempt": k,
                "candidate_id": CAND_ID,
                "list_field_caps": caps,
                "wall_seconds": wall,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "schema_valid": ok,
                "schema_error": err,
                "failure_mode": mode,
                "raw_text": r.text,
                "output": parsed,
            }
        except Exception as e:  # noqa: BLE001
            log.error("  FAILED: %s", e)
            record = {
                "attempt": k, "candidate_id": CAND_ID,
                "list_field_caps": caps,
                "error": str(e), "schema_valid": False,
            }
        out_path.write_text(json.dumps(record, indent=2, default=str))
        rows.append({
            "attempt": k,
            "valid": record.get("schema_valid"),
            "wall_s": record.get("wall_seconds"),
            "out_tokens": record.get("output_tokens"),
            "failure_mode": record.get("failure_mode"),
        })

    log.info("=== summary (with list_field_caps=%s) ===", caps)
    valid_n = sum(1 for r in rows if r["valid"])
    log.info("valid: %d/%d  (baseline without caps: 3/5)", valid_n, N_ATTEMPTS)
    for r in rows:
        log.info("  attempt %d: valid=%s wall=%s out_tok=%s mode=%s",
                 r["attempt"], r["valid"], r["wall_s"],
                 r["out_tokens"], r["failure_mode"])

    # Save aggregated summary alongside per-attempt files.
    (out_dir / "summary.json").write_text(json.dumps({
        "candidate_id": CAND_ID,
        "list_field_caps": caps,
        "n_attempts": N_ATTEMPTS,
        "valid_count": valid_n,
        "baseline_valid_count_without_caps": "3/5 (smoke + benchmark + 3 retries)",
        "attempts": rows,
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
