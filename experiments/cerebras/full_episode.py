"""Generate ALL segments of a podcast episode via Cerebras native SDK.

Writes into a fresh canonical run directory
`{source_axes with generator=<cerebras_*>}` containing:
  - symlinks to phase0/1/2/2_5 inputs from the source run
  - config.json (copied, axes.generator updated, generator scalar set)
  - phase3_episode.json (canonical filename, via assemble_episode)
  - phase3_generation_metrics.json (tokens/cost/latency per segment + totals)

Then invokes enrichment.post_phase3.run_post_phase3 to produce
manifest.json / report.html. The webapp discovers the run automatically
— no more sibling phase3_cerebras_native_<model>_episode.json dumps in
the source dir.

Usage:
    uv run python -m experiments.cerebras.full_episode \\
        --source data/runs/bh_trn_literary_hostprep \\
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

from enrichment import axes
from enrichment.generate_podcast import assemble_episode, build_messages, fix_turn_roles
from enrichment.podcast_types import (
    ALTERNATIVE_PERSONAS,
    DEFAULT_PERSONAS,
    EpisodeSegment,
    ExpertPersona,
    HostBrief,
    SegmentTemplate,
)
from enrichment.post_phase3 import run_post_phase3
from enrichment.segment_transport import (
    PassageAssignment,
    PlannedSegment,
    SegmentPlan,
)

from .native_section import _strictify
from .pricing import PRICING, cost_usd

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
RUNS_DIR = BASE_DIR / "data" / "runs"

# Files in the source dir that the target needs as inputs. Missing files
# (e.g. phase2_5 when hostprep=False) are skipped silently.
_INPUT_FILES: tuple[str, ...] = (
    "phase0_segments.json",
    "phase1_assignments.json",
    "phase2_plan.json",
    "phase2_5_host_briefs.json",
    "phase2_5_interviews.json",
    "phase2_5_reading_list.json",
)


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


def _load_source_axes(source_dir: Path) -> axes.RunAxes:
    cfg_path = source_dir / "config.json"
    if not cfg_path.exists():
        raise RuntimeError(f"{source_dir}: no config.json — not a migrated run dir")
    with open(cfg_path) as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict) or "axes" not in cfg:
        raise RuntimeError(f"{source_dir}: config.json has no 'axes' block")
    return axes.RunAxes.from_dict(cfg["axes"])


def _resolve_generator(model_id: str) -> axes.Generator:
    """Map a user-supplied id (slug or api_model) to an axes.Generator."""
    for g in axes.GENERATORS_TUPLE:
        if model_id in (g.id, g.api_model):
            return g
    raise ValueError(
        f"Unknown generator {model_id!r}. Known: "
        + ", ".join(f"{g.id} ({g.api_model})" for g in axes.GENERATORS_TUPLE)
    )


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
        raise RuntimeError(f"No ExpertPersona for: {missing}")
    return resolved


def _get_key() -> str:
    key = llm.get_key(alias="cerebras", env="CEREBRAS_API_KEY")
    if not key:
        raise RuntimeError(
            "No Cerebras API key. Run `llm keys set cerebras` or export CEREBRAS_API_KEY."
        )
    return key


def _provision_target_dir(
    source_dir: Path,
    target_dir: Path,
    target_axes: axes.RunAxes,
) -> None:
    """Create target_dir, symlink input files from source, copy config.json with
    axes.generator updated."""
    target_dir.mkdir(parents=True, exist_ok=True)
    for fname in _INPUT_FILES:
        src = source_dir / fname
        if not src.exists():
            continue
        dst = target_dir / fname
        if dst.exists() or dst.is_symlink():
            continue
        # Symlink relative so the source can be re-located without breakage.
        rel = os.path.relpath(src, target_dir)
        dst.symlink_to(rel)

    # config.json: copy then retarget axes
    src_cfg_path = source_dir / "config.json"
    if not src_cfg_path.exists():
        return
    with open(src_cfg_path) as f:
        cfg = json.load(f)
    cfg["axes"] = target_axes.to_dict()
    cfg["generator"] = target_axes.generator
    # Keep the name aligned with the dir for legibility.
    cfg["name"] = target_dir.name
    with open(target_dir / "config.json", "w") as f:
        json.dump(cfg, f, indent=2)


def generate_episode(
    source_dir: Path,
    model_id: str,
    *,
    max_completion_tokens: int = 32768,
    temperature: float = 0.7,
    reasoning_effort: str | None = None,
    run_post_phase3_after: bool = True,
) -> dict[str, Any]:
    """Generate a full episode via Cerebras, write canonical run dir + reports."""
    _activate_novel(source_dir)
    source_axes = _load_source_axes(source_dir)
    generator = _resolve_generator(model_id)
    # zai-glm-4.7 is a reasoning model whose hidden chain-of-thought consumes
    # the completion-token budget. Disable reasoning by default so content
    # gets the whole budget. Check after resolution so both the slug
    # `cerebras_zai_glm` and the api_model `zai-glm-4.7` trigger correctly.
    if reasoning_effort is None and "zai-glm" in generator.api_model:
        reasoning_effort = "none"

    target_axes = axes.RunAxes(
        novel=source_axes.novel,
        pipeline=source_axes.pipeline,
        panel=source_axes.panel,
        hostprep=source_axes.hostprep,
        generator=generator.id,
    )
    target_dir = RUNS_DIR / target_axes.dir_name()
    _provision_target_dir(source_dir, target_dir, target_axes)

    planned = _load_planned_segments(target_dir)
    host_briefs = _load_host_briefs(target_dir)
    prompt_version = _load_prompt_version(target_dir)
    personas = _load_personas(target_dir)

    schema = _strictify(EpisodeSegment.model_json_schema())
    client = Cerebras(api_key=_get_key())

    episode_segments: list[EpisodeSegment] = []
    segments_metrics: list[dict[str, Any]] = []
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
              "elapsed_seconds": 0.0, "cost_usd": 0.0}
    price_entry = PRICING.get(generator.api_model) or PRICING.get(generator.id)

    for i, seg in enumerate(planned):
        prev_title = planned[i - 1].template.name if i > 0 else None
        next_title = planned[i + 1].template.name if i < len(planned) - 1 else None
        brief = host_briefs[i] if host_briefs else None

        system_msg, user_msg = build_messages(
            seg, personas,
            is_first_segment=(i == 0),
            prompt_version=prompt_version,
            previous_segment_title=prev_title,
            next_segment_title=next_title,
            host_brief=brief,
        )

        logger.info("[%d/%d] segment '%s' (%d passages) via %s",
                    i + 1, len(planned), seg.template.name,
                    len(seg.assignments), generator.api_model)

        create_kwargs: dict[str, Any] = {
            "model": generator.api_model,
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
        seg_cost = cost_usd(generator.api_model, in_tok, out_tok) or 0.0

        episode_seg: EpisodeSegment | None = None
        validation = "failed: unknown"
        if content is None:
            validation = (
                f"failed: message.content=None "
                f"(finish_reason={choice.finish_reason})"
            )
        else:
            try:
                episode_seg = EpisodeSegment.model_validate(json.loads(content))
                validation = "ok"
            except json.JSONDecodeError as e:
                validation = f"failed: JSONDecodeError: {e} (finish_reason={choice.finish_reason})"
            except Exception as e:
                validation = f"failed: {e.__class__.__name__}: {e}"

        logger.info("  %.1fs  in=%d out=%d  cost=$%.4f  validation=%s",
                    elapsed, in_tok, out_tok, seg_cost, validation.split(":")[0])

        if episode_seg is not None:
            episode_segments.append(episode_seg)

        segments_metrics.append({
            "segment_index": i,
            "segment_name": seg.template.name,
            "finish_reason": choice.finish_reason,
            "validation": validation,
            "elapsed_seconds": elapsed,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "total_tokens": total_tok,
            "tokens_per_second": out_tok / elapsed if elapsed > 0 and out_tok else None,
            "cost_usd": seg_cost,
        })
        totals["input_tokens"] += in_tok
        totals["output_tokens"] += out_tok
        totals["total_tokens"] += total_tok
        totals["elapsed_seconds"] += elapsed
        totals["cost_usd"] += seg_cost

    plan = SegmentPlan(segments=planned, unassigned=[], total_null_flow=0)
    episode = assemble_episode(episode_segments, plan)
    episode_dict = episode.model_dump()
    fix_turn_roles(episode_dict, personas)

    # Canonical Phase 3 output — what post_phase3 consumes.
    with open(target_dir / "phase3_episode.json", "w") as f:
        json.dump(episode_dict, f, indent=2)

    # Generation metadata (tokens, cost, latency) as a sibling file — does
    # NOT collide with phase3_episode.json, lets the demo stay canonical.
    generation_meta = {
        "generator": generator.id,
        "api_model": generator.api_model,
        "prompt_version": prompt_version,
        "personas": [p.name for p in personas],
        "num_segments_planned": len(planned),
        "num_segments_validated": len(episode_segments),
        "totals": totals,
        "pricing": {
            "input_per_mtok": price_entry[0] if price_entry else None,
            "output_per_mtok": price_entry[1] if price_entry else None,
            "source": price_entry[2] if price_entry else None,
        },
        "segments": segments_metrics,
    }
    with open(target_dir / "phase3_generation_metrics.json", "w") as f:
        json.dump(generation_meta, f, indent=2)

    if run_post_phase3_after:
        logger.info("Running post_phase3 on %s", target_dir.name)
        run_post_phase3(target_dir, target_dir.name)

    return {
        "target_dir": str(target_dir),
        "run_id": target_dir.name,
        "axes": target_axes.to_dict(),
        "num_segments_validated": len(episode_segments),
        "totals": totals,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path,
                        help="Source run dir with phase0/1/2/2_5 inputs (must have an axes block).")
    parser.add_argument("--model", required=True,
                        help="Generator id or api_model (e.g. cerebras_qwen OR qwen-3-235b-a22b-instruct-2507).")
    parser.add_argument("--max-tokens", type=int, default=32768)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--reasoning-effort",
                        choices=["low", "medium", "high", "none"],
                        default=None,
                        help="Override reasoning_effort. Default: 'none' for zai-glm, unset otherwise.")
    parser.add_argument("--no-post-phase3", action="store_true",
                        help="Skip manifest/report generation after phase3.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    result = generate_episode(
        args.source, args.model,
        max_completion_tokens=args.max_tokens,
        temperature=args.temperature,
        reasoning_effort=args.reasoning_effort,
        run_post_phase3_after=not args.no_post_phase3,
    )

    t = result["totals"]
    print("\nEpisode complete.")
    print(f"  target_dir:    {result['target_dir']}")
    print(f"  axes:          {result['axes']}")
    print(f"  validated:     {result['num_segments_validated']} segments")
    print(f"  tokens:        in={t['input_tokens']:,} out={t['output_tokens']:,} total={t['total_tokens']:,}")
    print(f"  elapsed:       {t['elapsed_seconds']:.1f}s")
    print(f"  cost:          ${t['cost_usd']:.4f}")


if __name__ == "__main__":
    main()
