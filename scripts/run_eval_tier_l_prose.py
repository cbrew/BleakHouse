"""Run Stage 2 of o3ir, Tier L slice: short-prose generation benchmark.

Per BleakHouse-dll8 + bi7w (docs/tier_l_judge_methodology.md). Generates
prose for a 5-segment fixture across three open-weight candidates; the
Sonnet 4.6 baseline is captured from existing phase3_episode.json
artifacts in data/runs/. Quality judgment is blinded human preference
on rendered audio — this script produces only the text outputs.

Candidates (open weights on DeepInfra + Anthropic baseline):
- google/gemma-4-26B-A4B-it (MoE; $0.07/$0.34/M; Apache 2.0)
- google/gemma-4-31B-it (dense; $0.13/$0.38/M; Apache 2.0)
- deepseek-ai/DeepSeek-V3.2 ($0.26/$0.38/M; DeepSeek License)
- Qwen/Qwen3-235B-A22B-Instruct-2507 (MoE; $0.071/$0.10/M; Apache 2.0;
  non-thinking checkpoint, user-validated for Phase 3)
- claude-sonnet-4-6 (baseline; reused from existing runs)

Fixture (deterministic): 3 segments from bh_trn_literary_hostprep_short
+ 2 from wh_trn_literary_short, spread across each episode's arc.

Outputs:
- data/eval/stage2_tier_l_prose/<candidate_id>/segment_<run_id>_<seg_idx>.json
- data/eval/stage2_tier_l_prose/summary.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from enrichment.generate_podcast import build_messages  # noqa: E402
from enrichment.llm import generate as llm_generate  # noqa: E402
from enrichment.llm import settings  # noqa: E402
from enrichment.llm.types import GenerationRequest, ModelSpec  # noqa: E402
from enrichment.llm.schemas import (
    EpisodeSegment,
    HostBrief,
    SegmentTemplate,
)
from enrichment.personas import DEFAULT_PERSONAS
from enrichment.segment_transport import (  # noqa: E402
    PassageAssignment,
    PlannedSegment,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("eval-tier-l-prose")

DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
TASK = "generate_podcast"
OUTPUT_ROOT = REPO_ROOT / "data" / "eval" / "stage2_tier_l_prose"

CANDIDATES: dict[str, ModelSpec] = {
    "sonnet": ModelSpec(
        provider="anthropic",
        model="claude-sonnet-4-6",
        hosting="anthropic",
    ),
    "gemma-4-26b-a4b": ModelSpec(
        provider="openai_compatible",
        model="google/gemma-4-26B-A4B-it",
        hosting="deepinfra",
        base_url=DEEPINFRA_BASE_URL,
    ),
    "gemma-4-31b": ModelSpec(
        provider="openai_compatible",
        model="google/gemma-4-31B-it",
        hosting="deepinfra",
        base_url=DEEPINFRA_BASE_URL,
    ),
    "deepseek-v3-2": ModelSpec(
        provider="openai_compatible",
        model="deepseek-ai/DeepSeek-V3.2",
        hosting="deepinfra",
        base_url=DEEPINFRA_BASE_URL,
    ),
    "qwen3-235b-a22b": ModelSpec(
        provider="openai_compatible",
        model="Qwen/Qwen3-235B-A22B-Instruct-2507",
        hosting="deepinfra",
        base_url=DEEPINFRA_BASE_URL,
    ),
    # Added 2026-05-17 per dll8 methodology correction: treat Sonnet as
    # one candidate among many rather than the presumed default. gpt-5.4
    # is OpenAI's "frontier-quality at Sonnet-equivalent pricing" pick
    # (see docs/openai_pipeline_plan.md). max_completion_tokens path is
    # handled by the openai_compatible provider on hosting=='openai'.
    "gpt-5-4": ModelSpec(
        provider="openai_compatible",
        model="gpt-5.4",
        hosting="openai",
    ),
}

# Deterministic 5-segment sample: spread across both short runs.
FIXTURE: list[tuple[str, int]] = [
    ("bh_trn_literary_hostprep_short", 0),
    ("bh_trn_literary_hostprep_short", 2),
    ("bh_trn_literary_hostprep_short", 4),
    ("wh_trn_literary_short", 1),
    ("wh_trn_literary_short", 3),
]

# build_messages reads the active novel from BLEAKHOUSE_NOVEL via
# get_active_novel(); set it per fixture entry so the prompt's title/author
# block matches the source run.
_RUN_TO_NOVEL: dict[str, str] = {
    "bh_trn_literary_hostprep_short": "bleak_house",
    "wh_trn_literary_short": "wuthering_heights",
}


def load_segment(
    run_id: str, seg_idx: int,
) -> tuple[PlannedSegment, HostBrief | None, str | None, str | None, bool]:
    """Reconstruct the segment + host_brief + neighbor titles from disk."""
    run_dir = REPO_ROOT / "data" / "runs" / run_id
    phase1 = json.loads((run_dir / "phase1_assignments.json").read_text())
    phase2 = json.loads((run_dir / "phase2_plan.json").read_text())
    briefs_path = run_dir / "phase2_5_host_briefs.json"
    briefs_raw = (
        json.loads(briefs_path.read_text()) if briefs_path.exists() else None
    )

    pa_lookup = {a["passage_id"]: a for a in phase1.get("assignments", [])}
    plan = phase2["segments"]

    seg_data = plan[seg_idx]
    template = SegmentTemplate.model_validate(seg_data["template"])
    seg_assignments: list[PassageAssignment] = []
    for a in seg_data.get("assignments", []):
        full = pa_lookup.get(a.get("passage_id", ""), a)
        seg_assignments.append(PassageAssignment(**full))  # pyright: ignore[reportCallIssue]
    segment = PlannedSegment(template, seg_assignments)

    prev_title = plan[seg_idx - 1]["template"]["name"] if seg_idx > 0 else None
    next_title = (
        plan[seg_idx + 1]["template"]["name"]
        if seg_idx < len(plan) - 1 else None
    )
    is_first = seg_idx == 0

    brief: HostBrief | None = None
    if briefs_raw and seg_idx < len(briefs_raw):
        brief = HostBrief.model_validate(briefs_raw[seg_idx])

    return segment, brief, prev_title, next_title, is_first


def generate_one(
    spec: ModelSpec, system_msg: str, user_msg: str, schema: dict,
    max_attempts: int = 3,
):
    """Issue one prose-generation call for the given ModelSpec.

    Re-registers the seam task per call (cheap; matches the
    register_task-on-every-call convention used in enrichment/llm/eval/judge.py).

    reasoning_effort is only passed for Sonnet (which accepts 'minimal').
    DeepInfra-hosted Gemma 4 / DeepSeek-V3.2 are non-reasoning models and
    reject the parameter with HTTP 422; the seam does not yet filter
    per-hosting (a wider provider-aware fix is out of scope for dll8).
    """
    settings.register_task(TASK, spec)
    # reasoning_effort plumbing:
    # - Anthropic Sonnet: "minimal" works (was the original setting).
    # - OpenAI gpt-5.4: rejects "minimal" with HTTP 400 (see
    #   openai_compatible_provider._adapt_openai_reasoning_effort which
    #   would translate; we just send "low" directly here).
    # - DeepInfra Gemma/DeepSeek/Qwen non-reasoning models reject any
    #   value with 422; leave None.
    if spec.provider == "anthropic":
        reasoning_effort = "minimal"
    elif spec.hosting == "openai" and spec.model.startswith("gpt-5.4"):
        reasoning_effort = "low"
    else:
        reasoning_effort = None
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            t0 = time.monotonic()
            result = llm_generate(GenerationRequest(
                task=TASK,
                system=system_msg,
                user=user_msg,
                max_tokens=16384,
                json_schema=schema,
                reasoning_effort=reasoning_effort,
            ))
            wall = time.monotonic() - t0
            return result, wall
        except Exception as e:  # noqa: BLE001
            last_error = e
            if attempt < max_attempts:
                log.warning(
                    "  attempt %d/%d failed: %s; retrying",
                    attempt, max_attempts, e,
                )
                time.sleep(2 ** attempt)
            else:
                raise
    raise RuntimeError(f"unreachable: {last_error!r}")


def _validate_schema(text: str) -> tuple[bool, dict | None, str | None]:
    """Return (valid, parsed_dict, error_msg)."""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        return False, None, f"json decode: {e}"
    try:
        EpisodeSegment.model_validate(parsed)
    except Exception as e:  # noqa: BLE001
        return False, parsed, f"pydantic validate: {e}"
    return True, parsed, None


def capture_sonnet_baseline(fixture: list[tuple[str, int]]) -> dict:
    cand_dir = OUTPUT_ROOT / "sonnet"
    cand_dir.mkdir(parents=True, exist_ok=True)
    segments_summary = []
    for run_id, seg_idx in fixture:
        ep_path = REPO_ROOT / "data" / "runs" / run_id / "phase3_episode.json"
        ep = json.loads(ep_path.read_text())
        sonnet_seg = ep["segments"][seg_idx]
        out = {
            "source": "phase3_episode.json (existing production run)",
            "run_id": run_id,
            "seg_idx": seg_idx,
            "schema_valid": True,
            "output": sonnet_seg,
        }
        out_path = cand_dir / f"segment_{run_id}_{seg_idx}.json"
        out_path.write_text(json.dumps(out, indent=2))
        log.info("  baseline sonnet seg %s/%d captured (reused)", run_id, seg_idx)
        segments_summary.append({
            "run_id": run_id, "seg_idx": seg_idx,
            "schema_valid": True, "source": "reused",
        })
    return {"spec": "anthropic Sonnet 4.6 (existing prod runs)",
            "segments": segments_summary}


def run_candidate(cand_id: str, spec: ModelSpec,
                  fixture: list[tuple[str, int]]) -> dict:
    cand_dir = OUTPUT_ROOT / cand_id
    cand_dir.mkdir(parents=True, exist_ok=True)
    schema = EpisodeSegment.model_json_schema()
    segments_summary = []
    for run_id, seg_idx in fixture:
        log.info("=== %s on %s/seg-%d ===", cand_id, run_id, seg_idx)
        os.environ["BLEAKHOUSE_NOVEL"] = _RUN_TO_NOVEL[run_id]
        segment, brief, prev_t, next_t, is_first = load_segment(run_id, seg_idx)
        system_msg, user_msg = build_messages(
            segment, DEFAULT_PERSONAS, is_first, 2,
            previous_segment_title=prev_t,
            next_segment_title=next_t,
            host_brief=brief,
            length="short",
        )
        out: dict = {
            "candidate_id": cand_id,
            "run_id": run_id,
            "seg_idx": seg_idx,
            "model": spec.model,
        }
        try:
            result, wall = generate_one(spec, system_msg, user_msg, schema)
            schema_valid, parsed, err = _validate_schema(result.text)
            out.update({
                "wall_seconds": wall,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "schema_valid": schema_valid,
                "schema_error": err,
                "raw_text": result.text,
                "output": parsed,
            })
            log.info(
                "  ok: schema_valid=%s, in=%d out=%d wall=%.1fs",
                schema_valid, result.input_tokens or 0,
                result.output_tokens or 0, wall,
            )
        except Exception as e:  # noqa: BLE001
            log.error("  FAILED: %s", e)
            out.update({"error": str(e), "schema_valid": False})
        out_path = cand_dir / f"segment_{run_id}_{seg_idx}.json"
        out_path.write_text(json.dumps(out, indent=2, default=str))
        segments_summary.append({
            "run_id": run_id, "seg_idx": seg_idx,
            "schema_valid": out.get("schema_valid"),
            "wall_seconds": out.get("wall_seconds"),
            "input_tokens": out.get("input_tokens"),
            "output_tokens": out.get("output_tokens"),
            "error": out.get("error"),
        })
    return {"spec": asdict(spec), "segments": segments_summary}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--candidates", default="all",
        help="comma-separated subset, or 'all'",
    )
    parser.add_argument(
        "--smoke", action="store_true",
        help="run only first fixture pair as smoke test",
    )
    args = parser.parse_args()

    if args.candidates == "all":
        to_run = list(CANDIDATES.keys())
    else:
        to_run = [c.strip() for c in args.candidates.split(",") if c.strip()]
        for c in to_run:
            if c not in CANDIDATES:
                raise SystemExit(f"unknown candidate {c!r}; choices: {list(CANDIDATES)}")

    fixture = FIXTURE[:1] if args.smoke else FIXTURE
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    summary: dict = {}

    if "sonnet" in to_run:
        log.info("Capturing Sonnet baseline from existing runs")
        summary["sonnet"] = capture_sonnet_baseline(fixture)
        to_run.remove("sonnet")

    for cand_id in to_run:
        log.info("Running candidate: %s", cand_id)
        summary[cand_id] = run_candidate(cand_id, CANDIDATES[cand_id], fixture)

    summary_path = OUTPUT_ROOT / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str))
    log.info("Done. Results in %s", OUTPUT_ROOT)


if __name__ == "__main__":
    main()
