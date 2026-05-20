"""Test: does a simpler opening-segment instruction fix the gemma-26b
degenerate-loop bug?

Per BleakHouse-dll8: gemma-4-26b-a4b crashes on bh seg-0 (opening) at
~30% rate. list_field_caps={'emphasis_words': 3} did NOT fix it (the
field is already self-capped at max 2). Reframed hypothesis: the
verbose opening-segment user-prompt instruction
(generate_podcast.py:373-379, "welcome listeners, briefly introduce
the show's premise, and then introduce each expert with warmth — who
they are, what makes them interesting, why their perspective matters
for *{title}*") may be putting the model into a fragile sampler state.

Remedy under test: scope-only-to-this-model swap of that block for a
single short directive: "Briefly introduce each expert." All other
prompting unchanged. 5 attempts, compared against the 7/10 baseline.
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
log = logging.getLogger("test-gemma26b-simpler-opening")

CAND_ID = "gemma-4-26b-a4b"
RUN_ID = "bh_trn_literary_hostprep_short"
SEG_IDX = 0
N_ATTEMPTS = 5

# The verbose opening directive in enrichment/generate_podcast.py:373-379.
# Substring match drops it; we replace with a minimal one.
VERBOSE_OPENING_PREFIX = "\n**This is the FIRST segment of the episode.**"
MINIMAL_OPENING = (
    "\n**This is the FIRST segment of the episode.** "
    "Briefly introduce each expert."
)


def classify_failure(raw_text: str) -> str:
    lines = raw_text.splitlines()
    if not lines:
        return "empty"
    nonblank = sum(1 for ln in lines if ln.strip())
    if (1 - nonblank / len(lines)) > 0.9 and len(lines) > 100:
        return f"degenerate_newline_loop ({nonblank}/{len(lines)} nonblank)"
    return "truncated_or_malformed"


def _shrink_opening_directive(user_msg: str) -> str:
    """Replace the verbose opening directive with a minimal one.

    Scoped change: only the FIRST-segment instruction paragraph. Finds
    the verbose block by its '**This is the FIRST segment of the
    episode.**' header, then snips up to (and including) the next
    blank line.
    """
    idx = user_msg.find(VERBOSE_OPENING_PREFIX)
    if idx < 0:
        raise ValueError("opening directive not found — prompt template changed?")
    # End is the first '\n\n' after the directive's first character.
    end = user_msg.find("\n\n", idx + len(VERBOSE_OPENING_PREFIX))
    if end < 0:
        raise ValueError("could not find end of opening directive")
    return user_msg[:idx] + MINIMAL_OPENING + user_msg[end:]


def main() -> None:
    spec = CANDIDATES[CAND_ID]
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
    user_msg_short = _shrink_opening_directive(user_msg)

    log.info("Original directive snippet:")
    snip_start = user_msg.find(VERBOSE_OPENING_PREFIX)
    snip_end = user_msg.find("\n\n", snip_start + len(VERBOSE_OPENING_PREFIX))
    log.info("  %r", user_msg[snip_start:snip_end])
    log.info("Replaced with:")
    log.info("  %r", MINIMAL_OPENING)

    cand_dir = OUTPUT_ROOT / CAND_ID / "simpler_opening_probe"
    cand_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for k in range(1, N_ATTEMPTS + 1):
        log.info("=== attempt %d/%d (simpler opening) ===", k, N_ATTEMPTS)
        out_path = cand_dir / f"attempt{k}.json"
        try:
            t0 = time.monotonic()
            r = llm_generate(GenerationRequest(
                task=TASK,
                system=system_msg,
                user=user_msg_short,
                max_tokens=16384,
                json_schema=schema,
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
                "attempt": k, "candidate_id": CAND_ID,
                "remedy": "simpler_opening_directive",
                "wall_seconds": wall,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "schema_valid": ok, "schema_error": err,
                "failure_mode": mode,
                "raw_text": r.text, "output": parsed,
            }
        except Exception as e:  # noqa: BLE001
            log.error("  FAILED: %s", e)
            record = {
                "attempt": k, "candidate_id": CAND_ID,
                "remedy": "simpler_opening_directive",
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

    valid_n = sum(1 for r in rows if r["valid"])
    log.info("=== summary (simpler opening) ===")
    log.info("valid: %d/%d  (baseline default+list_caps combined: 7/10)",
             valid_n, N_ATTEMPTS)
    for r in rows:
        log.info("  attempt %d: valid=%s wall=%s out_tok=%s mode=%s",
                 r["attempt"], r["valid"], r["wall_s"],
                 r["out_tokens"], r["failure_mode"])

    (cand_dir / "summary.json").write_text(json.dumps({
        "candidate_id": CAND_ID,
        "remedy": "simpler_opening_directive",
        "minimal_opening": MINIMAL_OPENING,
        "n_attempts": N_ATTEMPTS,
        "valid_count": valid_n,
        "baseline_valid_count_combined_no_caps_plus_caps": "7/10",
        "attempts": rows,
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
