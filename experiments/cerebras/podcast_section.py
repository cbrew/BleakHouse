"""Regenerate one podcast segment via Cerebras gpt-oss-120b.

Reuses the exact prompts, personas, and inputs from the Anthropic Phase 3
pipeline (`enrichment.generate_podcast.build_messages`) and swaps only the
LLM transport. Ground-truth baseline (Anthropic Sonnet) lives alongside in
the same run directory as `phase3_episode.json`.

Usage:
    uv run python -m experiments.cerebras.podcast_section \
        --run data/runs/arc_v01_baseline \
        --segment 0

Writes the regenerated segment to
    data/runs/<run>/phase3_cerebras_seg<N>.json
next to the existing Anthropic output.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Any

from enrichment.generate_podcast import build_messages
from enrichment.llm.schemas import (
    EpisodeSegment,
    HostBrief,
    SegmentTemplate,
)
from enrichment.personas import DEFAULT_PERSONAS
from enrichment.segment_transport import (
    PassageAssignment,
    PlannedSegment,
)

from .client import DEFAULT_MODEL, call_with_schema_metrics
from enrichment.phase3_pricing import annotate

logger = logging.getLogger(__name__)


def _load_planned_segments(run_dir: Path) -> list[PlannedSegment]:
    """Reconstruct PlannedSegment objects as run_phase3 does."""
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
        raw = json.load(f)
    return [HostBrief.model_validate(b) for b in raw]


def _load_prompt_version(run_dir: Path) -> int:
    path = run_dir / "config.json"
    if not path.exists():
        return 2
    with open(path) as f:
        cfg = json.load(f)
    return int(cfg.get("prompt_version", 2))


def _activate_novel(run_dir: Path) -> None:
    """Set BLEAKHOUSE_NOVEL from the run's config so novel_prompts resolves."""
    cfg_path = run_dir / "config.json"
    if not cfg_path.exists():
        return
    with open(cfg_path) as f:
        cfg = json.load(f)
    novel = cfg.get("novel")
    if novel:
        os.environ["BLEAKHOUSE_NOVEL"] = novel


def generate_section(
    run_dir: Path,
    segment_index: int = 0,
    model_id: str = DEFAULT_MODEL,
    **options: Any,
) -> dict[str, Any]:
    """Regenerate one segment via Cerebras using the same inputs as Anthropic."""
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

    # llm-cerebras's schema handler only emits top-level properties, so the
    # nested Turn -> utterances -> Utterance shape never reaches the model.
    # Plugin-friendly workaround: (1) add a coverage directive to the system
    # prompt so gpt-oss-120b doesn't stop after the host intro, (2) append
    # the full JSON Schema to the user message so the nested structure is
    # visible. We keep schema= on the call for post-hoc validation.
    system_msg += (
        "\n\n**Coverage requirement:** a full segment is a multi-voice "
        "discussion, not a host monologue. Produce 12–20 turns. After the "
        f"host opens, all {len(DEFAULT_PERSONAS)} experts must speak "
        "multiple times, reacting to each other and to the host. The host "
        "re-enters periodically to steer. Each assigned passage should be "
        "read aloud (a `quote_reading` utterance with `is_quote: true`) "
        "and then unpacked."
    )
    schema_json = json.dumps(EpisodeSegment.model_json_schema(), indent=2)
    user_msg += (
        "\n\n## Required Output Schema (nested — follow exactly)\n\n"
        "Return ONE JSON object conforming to this JSON Schema. Each turn "
        "has `{speaker, role, utterances: [...]}` — no top-level `text` on "
        "turns; text lives inside utterances. Populate every field on every "
        "utterance. Remember the coverage requirement: 12–20 turns with "
        "all experts speaking multiple times.\n\n"
        "```json\n" + schema_json + "\n```"
    )

    logger.info(
        "Generating segment %d '%s' (%d passages) via %s",
        segment_index,
        segment.template.name,
        len(segment.assignments),
        model_id,
    )
    parsed, metrics = call_with_schema_metrics(
        user_msg,
        EpisodeSegment,
        system=system_msg,
        model_id=model_id,
        **options,
    )
    logger.info(
        "  returned in %.1fs (in=%s out=%s tok/s=%s)",
        metrics.elapsed_seconds,
        metrics.input_tokens,
        metrics.output_tokens,
        f"{metrics.output_tokens / metrics.elapsed_seconds:.0f}"
        if metrics.output_tokens and metrics.elapsed_seconds > 0
        else "n/a",
    )

    result: dict[str, Any] = {
        "segment_index": segment_index,
        "segment_name": segment.template.name,
        "model_id": model_id,
        "prompt_version": prompt_version,
        "metrics": metrics.to_dict(),
        "raw_response": parsed,
    }
    try:
        result["episode_segment"] = EpisodeSegment.model_validate(parsed).model_dump()
        result["validation"] = "ok"
    except Exception as e:
        result["episode_segment"] = None
        result["validation"] = f"failed: {e.__class__.__name__}: {e}"
        logger.warning("Validation failed; raw response preserved. %s", e)
    return annotate(result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path, help="Run directory under data/runs/")
    parser.add_argument("--segment", type=int, default=0, help="Segment index (0-based)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="llm model id")
    parser.add_argument("--max-tokens", type=int, default=16384, help="Max output tokens")
    parser.add_argument("--temperature", type=float, default=0.7, help="Sampling temperature")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path (default: <run>/phase3_cerebras_seg<N>.json)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    result = generate_section(
        args.run,
        args.segment,
        args.model,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )

    out = args.output or (args.run / f"phase3_cerebras_seg{args.segment}.json")
    out.write_text(json.dumps(result, indent=2))
    print(f"Wrote {out}")
    m = result["metrics"]
    seg = result.get("episode_segment")
    lines = [
        f"  segment: {result['segment_name']}",
        f"  validation: {result['validation']}",
    ]
    if seg:
        lines.append(f"  turns: {len(seg['turns'])}")
        lines.append(
            f"  utterances: {sum(len(t['utterances']) for t in seg['turns'])}"
        )
    lines.extend([
        f"  tokens: input={m['input_tokens']} output={m['output_tokens']} total={m['total_tokens']}",
        f"  elapsed: {m['elapsed_seconds']:.2f}s"
        + (f"  ({m['tokens_per_second']:.0f} tok/s)" if m.get("tokens_per_second") else ""),
    ])
    c = result.get("cost")
    if c:
        lines.append(f"  cost: ${c['usd']:.4f}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
