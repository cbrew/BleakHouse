"""Combined mitigation probe for gemma-4-26b-a4b on DeepInfra.

Per vLLM #40080 + PR #40099 (open / not merged), the Gemma 4 family
has a model-level repetition collapse that grammar-constrained
decoding amplifies. Cross-confirmed on Vertex / Cloudflare / ollama /
llama.cpp. Standard sampling penalties "partially help"; the
proposed RepetitionDetectionParams server-side abort is not yet
shipped.

This probe bypasses the seam to send three mitigations at once,
direct to DeepInfra's openai-compat endpoint:

  1) frequency_penalty=0.3      — std OpenAI param; DeepInfra accepts
  2) stop=["\\n\\n\\n\\n\\n"]   — belt-and-braces; caps wasted wall on
                                  failures from ~6min to ~1s
  3) extra_body={
       "repetition_detection": {"max_pattern_size": 20,
                                "min_pattern_size": 3,
                                "min_count": 4},
     }                          — speculative; DeepInfra silently no-ops
                                  if its vLLM doesn't expose this yet.

Records each attempt's finish_reason. Watch for:
- finish_reason="repetition_detected" → (3) works.
- finish_reason="stop" with short output → (2) clipped early.
- finish_reason="length" + degenerate → none of the three saved us.
- finish_reason="stop" with full output → success.
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

load_dotenv()

import openai  # noqa: E402

from enrichment.generate_podcast import build_messages  # noqa: E402
from enrichment.llm.schemas import EpisodeSegment  # noqa: E402
from enrichment.personas import DEFAULT_PERSONAS
from scripts.run_eval_tier_l_prose import (  # noqa: E402
    OUTPUT_ROOT,
    _RUN_TO_NOVEL,
    _validate_schema,
    load_segment,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("test-gemma26b-rep-mitigations")

CAND_ID = "gemma-4-26b-a4b"
MODEL = "google/gemma-4-26B-A4B-it"
RUN_ID = "bh_trn_literary_hostprep_short"
SEG_IDX = 0
N_ATTEMPTS = 5
DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"


def classify_failure(raw_text: str) -> str:
    lines = raw_text.splitlines()
    if not lines:
        return "empty"
    nonblank = sum(1 for ln in lines if ln.strip())
    if (1 - nonblank / len(lines)) > 0.9 and len(lines) > 100:
        return f"degenerate_newline_loop ({nonblank}/{len(lines)} nonblank)"
    return "truncated_or_malformed"


def main() -> None:
    api_key = os.environ.get("DEEPINFRA_API_KEY")
    if not api_key:
        raise SystemExit("DEEPINFRA_API_KEY missing from env")

    client = openai.OpenAI(base_url=DEEPINFRA_BASE_URL, api_key=api_key)

    os.environ["BLEAKHOUSE_NOVEL"] = _RUN_TO_NOVEL[RUN_ID]
    segment, brief, prev_t, next_t, is_first = load_segment(RUN_ID, SEG_IDX)
    system_msg, user_msg = build_messages(
        segment, DEFAULT_PERSONAS, is_first, 2,
        previous_segment_title=prev_t,
        next_segment_title=next_t,
        host_brief=brief,
        length="short",
    )

    schema = EpisodeSegment.model_json_schema()
    schema_name = schema.get("title", "response_schema")

    # Mitigation bundle.
    common_kwargs: dict = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 16384,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "schema": schema,
                            "strict": False},
        },
        # (1) standard OpenAI param — DeepInfra accepts.
        "frequency_penalty": 0.3,
        # (2) belt-and-braces stop sequence (5 consecutive newlines = the
        # degenerate-loop signature; legitimate JSON never emits this).
        "stop": ["\n\n\n\n\n"],
        # (3) speculative vLLM extra (proposed in PR #40099 — silently
        # no-ops if the deployed vLLM doesn't know the field).
        "extra_body": {
            "repetition_detection": {
                "max_pattern_size": 20,
                "min_pattern_size": 3,
                "min_count": 4,
            },
        },
    }

    out_dir = OUTPUT_ROOT / CAND_ID / "rep_mitigations_probe"
    out_dir.mkdir(parents=True, exist_ok=True)
    log.info("Mitigations: frequency_penalty=0.3, stop=['\\n\\n\\n\\n\\n'], "
             "extra_body.repetition_detection={...}")

    rows = []
    for k in range(1, N_ATTEMPTS + 1):
        log.info("=== attempt %d/%d ===", k, N_ATTEMPTS)
        out_path = out_dir / f"attempt{k}.json"
        record: dict = {"attempt": k, "candidate_id": CAND_ID,
                        "mitigations": ["frequency_penalty=0.3", "stop",
                                        "extra_body.repetition_detection"]}
        try:
            t0 = time.monotonic()
            r = client.chat.completions.create(**common_kwargs)
            wall = time.monotonic() - t0
            choice = r.choices[0]
            text = choice.message.content or ""
            ok, parsed, err = _validate_schema(text)
            mode = None if ok else classify_failure(text)
            in_tok = r.usage.prompt_tokens if r.usage else None
            out_tok = r.usage.completion_tokens if r.usage else None
            record.update({
                "wall_seconds": wall,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "finish_reason": choice.finish_reason,
                "schema_valid": ok,
                "schema_error": err,
                "failure_mode": mode,
                "raw_text": text,
                "output": parsed,
            })
            log.info(
                "  schema_valid=%s finish=%s in=%d out=%d wall=%.1fs%s",
                ok, choice.finish_reason, in_tok or 0, out_tok or 0, wall,
                "" if ok else f"  FAILURE_MODE={mode}",
            )
        except openai.APIError as e:
            log.error("  API ERROR: %s", e)
            record.update({"error": str(e), "schema_valid": False})
        except Exception as e:  # noqa: BLE001
            log.error("  FAILED: %s", e)
            record.update({"error": str(e), "schema_valid": False})
        out_path.write_text(json.dumps(record, indent=2, default=str))
        rows.append({
            "attempt": k,
            "valid": record.get("schema_valid"),
            "wall_s": record.get("wall_seconds"),
            "out_tokens": record.get("output_tokens"),
            "finish_reason": record.get("finish_reason"),
            "failure_mode": record.get("failure_mode"),
        })

    valid_n = sum(1 for r in rows if r["valid"])
    log.info("=== summary (combined mitigations) ===")
    log.info("valid: %d/%d  (baseline combined 7/10 valid, 27%% fail)",
             valid_n, N_ATTEMPTS)
    for r in rows:
        log.info(
            "  attempt %d: valid=%s finish=%s wall=%s out_tok=%s mode=%s",
            r["attempt"], r["valid"], r["finish_reason"], r["wall_s"],
            r["out_tokens"], r["failure_mode"],
        )

    (out_dir / "summary.json").write_text(json.dumps({
        "candidate_id": CAND_ID,
        "mitigations_applied": {
            "frequency_penalty": 0.3,
            "stop": ["\n\n\n\n\n"],
            "extra_body.repetition_detection": {
                "max_pattern_size": 20, "min_pattern_size": 3,
                "min_count": 4,
            },
        },
        "n_attempts": N_ATTEMPTS,
        "valid_count": valid_n,
        "baseline_combined": "7/10 valid across default + list_caps + simpler_opening probes",
        "attempts": rows,
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
