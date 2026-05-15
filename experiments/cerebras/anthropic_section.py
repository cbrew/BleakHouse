"""Regenerate one podcast segment via Anthropic Claude Sonnet 4.6.

Companion to `native_section.py` (Cerebras native SDK) and
`podcast_section.py` (llm + llm-cerebras). Same prompts/inputs via
`build_messages()`, different backend — for side-by-side comparison of
latency, tokens, and cost.

Key: reads `ANTHROPIC_API_KEY` from `.env` (or the ambient env).

Usage:
    uv run python -m experiments.cerebras.anthropic_section \
        --run data/runs/arc_v01_baseline --segment 0
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv

from enrichment.generate_podcast import build_messages
from enrichment.podcast_types import (
    DEFAULT_PERSONAS,
    EpisodeSegment,
    HostBrief,
    SegmentTemplate,
)
from enrichment.segment_transport import (
    PassageAssignment,
    PlannedSegment,
)

from enrichment.phase3_pricing import annotate

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-6"


def _activate_novel(run_dir: Path) -> None:
    cfg_path = run_dir / "config.json"
    if not cfg_path.exists():
        return
    with open(cfg_path) as f:
        cfg = json.load(f)
    novel = cfg.get("novel")
    if novel:
        os.environ["BLEAKHOUSE_NOVEL"] = novel


def _load_planned_segments(run_dir: Path) -> list[PlannedSegment]:
    with open(run_dir / "phase1_assignments.json") as f:
        phase1 = json.load(f)
    with open(run_dir / "phase2_plan.json") as f:
        phase2 = json.load(f)
    pa_lookup = {a["passage_id"]: a for a in phase1.get("assignments", [])}
    planned: list[PlannedSegment] = []
    for seg_data in phase2["segments"]:
        template = SegmentTemplate.model_validate(seg_data["template"])
        assignments: list[PassageAssignment] = []
        for a in seg_data.get("assignments", []):
            full = pa_lookup.get(a.get("passage_id", ""), a)
            assignments.append(PassageAssignment(**full))
        planned.append(PlannedSegment(template, assignments))
    return planned


def _load_host_briefs(run_dir: Path) -> list[HostBrief] | None:
    path = run_dir / "phase2_5_host_briefs.json"
    if not path.exists():
        return None
    with open(path) as f:
        return [HostBrief.model_validate(b) for b in json.load(f)]


def _load_prompt_version(run_dir: Path) -> int:
    path = run_dir / "config.json"
    if not path.exists():
        return 2
    with open(path) as f:
        return int(json.load(f).get("prompt_version", 2))


def generate_section_anthropic(
    run_dir: Path,
    segment_index: int = 0,
    model_id: str = DEFAULT_MODEL,
    max_tokens: int = 16384,
) -> dict[str, Any]:
    _activate_novel(run_dir)
    planned = _load_planned_segments(run_dir)
    if not 0 <= segment_index < len(planned):
        raise IndexError(
            f"segment_index {segment_index} out of range (0..{len(planned) - 1})"
        )
    prompt_version = _load_prompt_version(run_dir)
    host_briefs = _load_host_briefs(run_dir)

    segment = planned[segment_index]
    prev_title = planned[segment_index - 1].template.name if segment_index > 0 else None
    next_title = (
        planned[segment_index + 1].template.name
        if segment_index < len(planned) - 1
        else None
    )
    brief = host_briefs[segment_index] if host_briefs else None

    system_msg, user_msg = build_messages(
        segment,
        list(DEFAULT_PERSONAS),
        is_first_segment=(segment_index == 0),
        prompt_version=prompt_version,
        previous_segment_title=prev_title,
        next_segment_title=next_title,
        host_brief=brief,
    )

    client = anthropic.Anthropic()
    logger.info(
        "Generating segment %d '%s' (%d passages) via Anthropic model=%s",
        segment_index,
        segment.template.name,
        len(segment.assignments),
        model_id,
    )
    start = time.perf_counter()
    response = client.messages.parse(
        model=model_id,
        max_tokens=max_tokens,
        system=system_msg,
        messages=[{"role": "user", "content": user_msg}],
        output_format=EpisodeSegment,
    )
    elapsed = time.perf_counter() - start

    in_tok = response.usage.input_tokens
    out_tok = response.usage.output_tokens
    total_tok = in_tok + out_tok
    tps = out_tok / elapsed if elapsed > 0 else None

    logger.info(
        "  returned in %.1fs stop_reason=%s in=%d out=%d tok/s=%s",
        elapsed,
        response.stop_reason,
        in_tok,
        out_tok,
        f"{tps:.0f}" if tps else "n/a",
    )

    parsed_output = response.parsed_output
    if parsed_output is None:
        raw = None
        episode_dump: dict[str, Any] | None = None
        validation = "failed: parsed_output is None"
    else:
        # parsed_output is an EpisodeSegment; round-trip to dict
        raw = parsed_output.model_dump()
        episode_dump = raw
        validation = "ok"

    metrics = {
        "elapsed_seconds": elapsed,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "total_tokens": total_tok,
        "tokens_per_second": tps,
        "raw_usage": response.usage.model_dump(),
    }

    result: dict[str, Any] = {
        "segment_index": segment_index,
        "segment_name": segment.template.name,
        "model_id": model_id,
        "prompt_version": prompt_version,
        "stop_reason": response.stop_reason,
        "metrics": metrics,
        "raw_response": raw,
        "episode_segment": episode_dump,
        "validation": validation,
    }
    return annotate(result)


def _slug(model_id: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in model_id).strip("_")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--segment", type=int, default=0)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=16384)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    result = generate_section_anthropic(
        args.run, args.segment, args.model, max_tokens=args.max_tokens
    )
    out = args.output or (
        args.run / f"phase3_anthropic_{_slug(args.model)}_seg{args.segment}.json"
    )
    out.write_text(json.dumps(result, indent=2))
    print(f"Wrote {out}")
    m = result["metrics"]
    c = result.get("cost")
    seg = result.get("episode_segment")
    lines = [
        f"  model: {result['model_id']}",
        f"  segment: {result['segment_name']}",
        f"  validation: {result['validation']}",
        f"  stop_reason: {result['stop_reason']}",
    ]
    if seg:
        lines.append(f"  turns: {len(seg['turns'])}")
        lines.append(
            f"  utterances: {sum(len(t['utterances']) for t in seg['turns'])}"
        )
    lines.append(
        f"  tokens: input={m['input_tokens']} output={m['output_tokens']} total={m['total_tokens']}"
    )
    tps = m.get("tokens_per_second")
    lines.append(
        f"  elapsed: {m['elapsed_seconds']:.2f}s"
        + (f"  ({tps:.0f} tok/s)" if tps else "")
    )
    if c:
        lines.append(f"  cost: ${c['usd']:.4f}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
