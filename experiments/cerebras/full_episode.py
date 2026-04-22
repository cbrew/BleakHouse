"""Generate ALL segments of a podcast episode via Cerebras native SDK.

Same inputs/prompts as the Anthropic Phase 3 pipeline
(`enrichment.generate_podcast.run_phase3`). Writes one JSON per episode
containing all segments, per-segment metrics/costs, and aggregate totals.

Usage:
    uv run python -m experiments.cerebras.full_episode \
        --run data/runs/arc_v01_baseline \
        --model qwen-3-235b-a22b-instruct-2507
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
    ALTERNATIVE_PERSONAS,
    DEFAULT_PERSONAS,
    EpisodeSegment,
    ExpertPersona,
    HostBrief,
    SegmentTemplate,
)
from enrichment.segment_transport import (
    PassageAssignment,
    PlannedSegment,
)

from .native_section import _strictify
from .pricing import PRICING, cost_usd

logger = logging.getLogger(__name__)


def _activate_novel(run_dir: Path) -> None:
    cfg_path = run_dir / "config.json"
    if cfg_path.exists():
        with open(cfg_path) as f:
            novel = json.load(f).get("novel")
        if novel:
            os.environ["BLEAKHOUSE_NOVEL"] = novel


def _load_prompt_version(run_dir: Path) -> int:
    path = run_dir / "config.json"
    if not path.exists():
        return 2
    with open(path) as f:
        return int(json.load(f).get("prompt_version", 2))


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


def _load_personas(run_dir: Path) -> list[ExpertPersona]:
    """Resolve personas by name across DEFAULT_PERSONAS + ALTERNATIVE_PERSONAS."""
    cfg_path = run_dir / "config.json"
    if not cfg_path.exists():
        return list(DEFAULT_PERSONAS)
    with open(cfg_path) as f:
        cfg = json.load(f)
    ordered_names = [e["name"] for e in cfg.get("experts", [])]
    if not ordered_names:
        return list(DEFAULT_PERSONAS)
    by_name: dict[str, ExpertPersona] = {p.name: p for p in DEFAULT_PERSONAS}
    for p in ALTERNATIVE_PERSONAS.values():
        by_name.setdefault(p.name, p)
    resolved: list[ExpertPersona] = []
    missing: list[str] = []
    for n in ordered_names:
        if n in by_name:
            resolved.append(by_name[n])
        else:
            missing.append(n)
    if missing:
        raise RuntimeError(
            f"No ExpertPersona entry found for: {missing}. "
            "Add them to DEFAULT_PERSONAS or ALTERNATIVE_PERSONAS."
        )
    return resolved


def _get_key() -> str:
    key = llm.get_key(alias="cerebras", env="CEREBRAS_API_KEY")
    if not key:
        raise RuntimeError(
            "No Cerebras API key. Run `llm keys set cerebras` or export CEREBRAS_API_KEY."
        )
    return key


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s).strip("_")


def generate_episode(
    run_dir: Path,
    model_id: str,
    max_completion_tokens: int = 32768,
    temperature: float = 0.7,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    # zai-glm-4.7 is a reasoning model whose hidden chain-of-thought consumes
    # the completion-token budget. Disable reasoning by default so content
    # gets the whole budget.
    if reasoning_effort is None and model_id.startswith("zai-glm"):
        reasoning_effort = "none"
    _activate_novel(run_dir)
    planned = _load_planned_segments(run_dir)
    host_briefs = _load_host_briefs(run_dir)
    prompt_version = _load_prompt_version(run_dir)
    personas = _load_personas(run_dir)

    schema = _strictify(EpisodeSegment.model_json_schema())
    client = Cerebras(api_key=_get_key())

    segments_out: list[dict[str, Any]] = []
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "elapsed_seconds": 0.0, "cost_usd": 0.0}
    price_entry = PRICING.get(model_id)

    for i, seg in enumerate(planned):
        prev_title = planned[i - 1].template.name if i > 0 else None
        next_title = planned[i + 1].template.name if i < len(planned) - 1 else None
        brief = host_briefs[i] if host_briefs else None

        system_msg, user_msg = build_messages(
            seg,
            personas,
            is_first_segment=(i == 0),
            prompt_version=prompt_version,
            previous_segment_title=prev_title,
            next_segment_title=next_title,
            host_brief=brief,
        )

        logger.info(
            "[%d/%d] segment '%s' (%d passages) via %s",
            i + 1, len(planned), seg.template.name, len(seg.assignments), model_id,
        )
        create_kwargs: dict[str, Any] = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "episode_segment",
                    "strict": True,
                    "schema": schema,
                },
            },
            "max_completion_tokens": max_completion_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if reasoning_effort is not None:
            create_kwargs["reasoning_effort"] = reasoning_effort
        start = time.perf_counter()
        completion = client.chat.completions.create(**create_kwargs)
        assert isinstance(completion, ChatCompletionResponse)
        elapsed = time.perf_counter() - start
        choice = completion.choices[0]
        content = choice.message.content

        usage = completion.usage.model_dump() if completion.usage else {}
        in_tok = int(usage.get("prompt_tokens") or 0)
        out_tok = int(usage.get("completion_tokens") or 0)
        total_tok = int(usage.get("total_tokens") or (in_tok + out_tok))
        seg_cost = cost_usd(model_id, in_tok, out_tok) or 0.0

        raw: Any = None
        episode_seg: dict[str, Any] | None = None
        validation = "failed: unknown"
        if content is None:
            msg_dump = choice.message.model_dump()
            validation = (
                f"failed: message.content was None "
                f"(finish_reason={choice.finish_reason}, "
                f"message keys={sorted(msg_dump.keys())})"
            )
            logger.warning("  %s", validation)
        else:
            try:
                raw = json.loads(content)
                episode_seg = EpisodeSegment.model_validate(raw).model_dump()
                validation = "ok"
            except json.JSONDecodeError as e:
                validation = f"failed: JSONDecodeError: {e} (finish_reason={choice.finish_reason})"
                logger.warning("  JSON parse failed (likely truncated): %s", e)
            except Exception as e:
                validation = f"failed: {e.__class__.__name__}: {e}"
                logger.warning("  validation failed: %s", e)

        logger.info(
            "  %.1fs  in=%d out=%d  cost=$%.4f  turns=%s",
            elapsed, in_tok, out_tok, seg_cost,
            len(episode_seg["turns"]) if episode_seg else "?",
        )

        segments_out.append({
            "segment_index": i,
            "segment_name": seg.template.name,
            "finish_reason": choice.finish_reason,
            "validation": validation,
            "metrics": {
                "elapsed_seconds": elapsed,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "total_tokens": total_tok,
                "tokens_per_second": out_tok / elapsed if elapsed > 0 and out_tok else None,
                "cost_usd": seg_cost,
            },
            "episode_segment": episode_seg,
        })
        totals["input_tokens"] += in_tok
        totals["output_tokens"] += out_tok
        totals["total_tokens"] += total_tok
        totals["elapsed_seconds"] += elapsed
        totals["cost_usd"] += seg_cost

    result: dict[str, Any] = {
        "run_dir": str(run_dir),
        "model_id": model_id,
        "prompt_version": prompt_version,
        "personas": [p.name for p in personas],
        "num_segments": len(planned),
        "totals": totals,
        "pricing": {
            "input_per_mtok": price_entry[0] if price_entry else None,
            "output_per_mtok": price_entry[1] if price_entry else None,
            "source": price_entry[2] if price_entry else None,
        },
        "segments": segments_out,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--model", required=True, help="Cerebras model id, e.g. qwen-3-235b-a22b-instruct-2507 or zai-glm-4.7")
    parser.add_argument("--max-tokens", type=int, default=32768)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument(
        "--reasoning-effort",
        choices=["low", "medium", "high", "none"],
        default=None,
        help="Override reasoning_effort. Default: 'none' for zai-glm, unset otherwise.",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    result = generate_episode(
        args.run,
        args.model,
        max_completion_tokens=args.max_tokens,
        temperature=args.temperature,
        reasoning_effort=args.reasoning_effort,
    )
    out = args.output or (args.run / f"phase3_cerebras_native_{_slug(args.model)}_episode.json")
    out.write_text(json.dumps(result, indent=2))

    t = result["totals"]
    num_valid = sum(1 for s in result["segments"] if s["validation"] == "ok")
    print(f"\nWrote {out}")
    print(f"  model:        {result['model_id']}")
    print(f"  panel:        {', '.join(result['personas'])}")
    print(f"  segments:     {num_valid}/{result['num_segments']} validated")
    print(f"  tokens:       in={t['input_tokens']:,} out={t['output_tokens']:,} total={t['total_tokens']:,}")
    print(f"  elapsed:      {t['elapsed_seconds']:.1f}s")
    print(f"  cost:         ${t['cost_usd']:.4f}")


if __name__ == "__main__":
    main()
