"""Regenerate one podcast segment via Cerebras's native SDK with json_schema.

Same prompts/inputs as `experiments.cerebras.podcast_section`, but uses the
native Cerebras Cloud SDK directly so we can pass the full nested JSON
Schema via `response_format={"type": "json_schema", ...}` with `strict=True`
— which the llm-cerebras plugin does not expose.

Key is read via llm's keystore alias `cerebras` (same as the plugin path)
with `CEREBRAS_API_KEY` as env fallback, so no duplicate key management.

Usage:
    uv run python -m experiments.cerebras.native_section \
        --run data/runs/arc_v01_baseline \
        --segment 0
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import llm
from cerebras.cloud.sdk import Cerebras
from cerebras.cloud.sdk.types.chat.chat_completion import ChatCompletionResponse

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

logger = logging.getLogger(__name__)

NATIVE_MODEL = "gpt-oss-120b"  # no vendor prefix for the native SDK


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


def _strictify(schema: Any) -> Any:
    """Walk a JSON Schema dict and add `additionalProperties: false` to every
    object. Cerebras's strict json_schema mode requires this on all objects.
    """
    if isinstance(schema, dict):
        if schema.get("type") == "object" and "additionalProperties" not in schema:
            schema["additionalProperties"] = False
        for v in schema.values():
            _strictify(v)
    elif isinstance(schema, list):
        for v in schema:
            _strictify(v)
    return schema


def _get_cerebras_key() -> str:
    """Resolve the Cerebras key via llm's keystore (alias 'cerebras') with
    CEREBRAS_API_KEY env fallback.
    """
    key = llm.get_key(alias="cerebras", env="CEREBRAS_API_KEY")
    if not key:
        raise RuntimeError(
            "No Cerebras API key. Run `llm keys set cerebras` or export CEREBRAS_API_KEY."
        )
    return key


def generate_section_native(
    run_dir: Path,
    segment_index: int = 0,
    model_id: str = NATIVE_MODEL,
    max_completion_tokens: int | None = 16384,
    temperature: float = 0.7,
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

    schema = _strictify(EpisodeSegment.model_json_schema())

    client = Cerebras(api_key=_get_cerebras_key())
    logger.info(
        "Generating segment %d '%s' (%d passages) via native SDK model=%s",
        segment_index,
        segment.template.name,
        len(segment.assignments),
        model_id,
    )
    start = time.perf_counter()
    completion = client.chat.completions.create(
        model=model_id,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "episode_segment",
                "strict": True,
                "schema": schema,
            },
        },
        max_completion_tokens=max_completion_tokens,
        temperature=temperature,
        stream=False,
    )
    assert isinstance(completion, ChatCompletionResponse)
    elapsed = time.perf_counter() - start
    choice = completion.choices[0]
    content = choice.message.content
    assert content is not None, "Cerebras returned no content"
    raw = json.loads(content)
    logger.info("  returned in %.1fs (finish_reason=%s)", elapsed, choice.finish_reason)

    result: dict[str, Any] = {
        "segment_index": segment_index,
        "segment_name": segment.template.name,
        "model_id": model_id,
        "prompt_version": prompt_version,
        "elapsed_seconds": elapsed,
        "finish_reason": choice.finish_reason,
        "usage": completion.usage.model_dump() if completion.usage else None,
        "raw_response": raw,
    }
    try:
        result["episode_segment"] = EpisodeSegment.model_validate(raw).model_dump()
        result["validation"] = "ok"
    except Exception as e:
        result["episode_segment"] = None
        result["validation"] = f"failed: {e.__class__.__name__}: {e}"
        logger.warning("Validation failed; raw response preserved.")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--segment", type=int, default=0)
    parser.add_argument("--model", default=NATIVE_MODEL)
    parser.add_argument("--max-tokens", type=int, default=16384)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    result = generate_section_native(
        args.run,
        args.segment,
        args.model,
        max_completion_tokens=args.max_tokens,
        temperature=args.temperature,
    )

    out = args.output or (args.run / f"phase3_cerebras_native_seg{args.segment}.json")
    out.write_text(json.dumps(result, indent=2))
    print(f"Wrote {out}")
    seg = result.get("episode_segment")
    if seg:
        print(
            f"  segment: {result['segment_name']}\n"
            f"  turns: {len(seg['turns'])}\n"
            f"  utterances: {sum(len(t['utterances']) for t in seg['turns'])}\n"
            f"  finish_reason: {result['finish_reason']}\n"
            f"  elapsed: {result['elapsed_seconds']:.1f}s"
        )
    else:
        print(f"  validation: {result['validation']}")


if __name__ == "__main__":
    main()
