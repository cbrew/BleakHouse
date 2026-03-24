"""Execute a versioned pipeline run, saving outputs at each phase.

Usage:
    uv run python -m enrichment.run --name baseline
    uv run python -m enrichment.run --name strict --cluster-lambda 20
    uv run python -m enrichment.run --name more_jo --arc-demand "Jo's suffering=8"
    uv run python -m enrichment.run --name baseline --phase 2   # stop after Phase 2
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from copy import deepcopy
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from enrichment.design_segments import (  # pyright: ignore[reportMissingImports]
    compute_supplementary_demand,
    design_segments,
)
from enrichment.generate_podcast import (  # pyright: ignore[reportMissingImports]
    assemble_episode,
    generate_segment_script,
)
from enrichment.run_config import (  # pyright: ignore[reportMissingImports]
    RunConfig,
)
from enrichment.segment_transport import (  # pyright: ignore[reportMissingImports]
    build_passage_assignments,
    build_segment_report,
    solve_segment_assignment,
)
from enrichment.transport_podcast import (  # pyright: ignore[reportMissingImports]
    ProducerConfig,
    load_passages,
    run_pipeline,
)

load_dotenv()

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = BASE_DIR / "reports"


# ---------------------------------------------------------------------------
# Phase runners
# ---------------------------------------------------------------------------


def run_phase1(
    config: RunConfig,
    supplementary_demand: dict[str, int] | None = None,
) -> dict:
    """Phase 1: passage selection. Returns serializable assignments."""
    result = run_pipeline(
        experts=config.experts,
        arcs=config.arcs,
        config=config.producer,
        supplementary_demand=supplementary_demand,
    )
    passages = load_passages()
    assignments = build_passage_assignments(result, passages)

    # Serialize (all fields from PassageAssignment dataclass)
    from dataclasses import asdict as _asdict

    data = [_asdict(pa) for pa in assignments]
    return {"assignments": data, "count": len(data)}


def run_phase2(config: RunConfig, phase1_data: dict) -> dict:
    """Phase 2: segment assignment. Returns serializable plan."""
    from enrichment.segment_transport import PassageAssignment  # pyright: ignore[reportMissingImports]

    assignments: list[PassageAssignment] = [
        PassageAssignment(**a)  # pyright: ignore[reportCallIssue]
        for a in phase1_data["assignments"]
    ]

    plan = solve_segment_assignment(
        assignments,
        templates=config.segment_templates,
        null_cost=config.segment_null_cost,
        dimension_mismatch_cost=config.segment_dimension_mismatch_cost,
        arc_mismatch_cost=config.segment_arc_mismatch_cost,
        expert_mismatch_cost=config.segment_expert_mismatch_cost,
    )

    # Serialize
    segments = []
    for ps in plan.segments:
        segments.append({
            "template": ps.template.model_dump(),
            "assignments": [
                {
                    "passage_id": a.passage_id,
                    "chapter_id": a.chapter_id,
                    "expert": a.expert,
                    "dimension": a.dimension,
                    "interest_score": a.interest_score,
                    "arc_name": a.arc_name,
                }
                for a in ps.assignments
            ],
        })

    report = build_segment_report(plan)

    return {
        "segments": segments,
        "total_null_flow": plan.total_null_flow,
        "report": report,
    }


def run_phase3(config: RunConfig, phase2_data: dict, phase1_data: dict) -> dict:
    """Phase 3: script generation. Returns serializable episode."""
    from enrichment.segment_transport import (  # pyright: ignore[reportMissingImports]
        PassageAssignment,
        PlannedSegment,
        SegmentPlan,
    )
    from enrichment.podcast_types import SegmentTemplate  # pyright: ignore[reportMissingImports]

    # Rebuild the full PassageAssignment objects (with text) for LLM prompts
    pa_lookup: dict[str, dict] = {}
    for a in phase1_data["assignments"]:
        pa_lookup[a["passage_id"]] = a

    planned_segments = []
    for seg_data in phase2_data["segments"]:
        template = SegmentTemplate.model_validate(seg_data["template"])
        seg_assignments = []
        for a in seg_data["assignments"]:
            full = pa_lookup.get(a["passage_id"], a)
            seg_assignments.append(PassageAssignment(**full))  # pyright: ignore[reportCallIssue]
        planned_segments.append(PlannedSegment(template, seg_assignments))

    plan = SegmentPlan(
        segments=planned_segments,
        unassigned=[],
        total_null_flow=phase2_data["total_null_flow"],
    )

    client = anthropic.Anthropic()
    personas = config.personas

    episode_segments = []
    for i, seg in enumerate(plan.segments):
        prev_title = plan.segments[i - 1].template.name if i > 0 else None
        next_title = plan.segments[i + 1].template.name if i < len(plan.segments) - 1 else None
        episode_seg = generate_segment_script(
            seg, client, config.model, personas,
            is_first_segment=(i == 0),
            prompt_version=config.prompt_version,
            previous_segment_title=prev_title,
            next_segment_title=next_title,
        )
        episode_segments.append(episode_seg)
        logger.info(
            "  Segment '%s': %d turns",
            episode_seg.title,
            len(episode_seg.turns),
        )

    episode = assemble_episode(episode_segments, plan)
    return episode.model_dump()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Run versioned pipeline")
    parser.add_argument("--name", required=True, help="Run name (e.g. baseline)")
    parser.add_argument(
        "--novel", required=True,
        help="Novel key (bleak_house, mill_on_the_floss, our_mutual_friend, "
             "north_and_south, passage_to_india)",
    )
    parser.add_argument(
        "--phase",
        type=int,
        default=3,
        choices=[1, 2, 3],
        help="Stop after this phase (default: 3)",
    )

    # Phase 1 overrides
    parser.add_argument("--cluster-lambda", type=int, default=None)
    parser.add_argument("--total-budget", type=int, default=None)
    parser.add_argument("--per-expert-max", type=int, default=None)
    parser.add_argument("--per-expert-min", type=int, default=None)
    parser.add_argument("--strong-cost", type=int, default=None)
    parser.add_argument("--weak-cost", type=int, default=None)

    # Arc demand overrides: --arc-demand "Jo's suffering=8"
    parser.add_argument(
        "--arc-demand",
        action="append",
        default=[],
        help="Override arc demand: 'Arc Name=N'",
    )

    # Expert demand overrides: --expert-demand "Eleanor Hartley:prov_narrative_technique=4"
    parser.add_argument(
        "--expert-demand",
        action="append",
        default=[],
        help="Override expert dimension demand: 'Expert Name:dimension=N'",
    )

    # Expert replacement: --replace-expert "James Blackstone=sir_edmund"
    parser.add_argument(
        "--replace-expert",
        action="append",
        default=[],
        help="Replace an expert with an alternative: 'Old Name=preset_key'",
    )

    # Segment design
    parser.add_argument(
        "--no-design-segments",
        action="store_true",
        help="Skip LLM segment design; use default templates",
    )
    parser.add_argument(
        "--segment-model",
        default=None,
        help="Model for segment design (default: haiku)",
    )

    # Resume from existing phase outputs
    parser.add_argument(
        "--resume-from",
        type=int,
        default=None,
        choices=[1, 2, 3],
        help="Resume from this phase using existing outputs (skips earlier phases)",
    )

    # Prompt version
    parser.add_argument(
        "--prompt-version", type=int, default=2,
        help="Prompt version: 1=original, 2=supply-aware+passage-grounded (default: 2)",
    )

    # Phase 3 overrides
    parser.add_argument("--model", default=None)

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    # Set novel identity from CLI arg — all downstream code reads this
    os.environ["BLEAKHOUSE_NOVEL"] = args.novel
    logger.info("Novel: %s", args.novel)

    # Build config
    config = RunConfig(name=args.name, prompt_version=args.prompt_version)

    # Apply Phase 1 overrides
    producer = ProducerConfig()
    changed = False
    if args.cluster_lambda is not None:
        producer.cluster_lambda = args.cluster_lambda
        changed = True
    if args.total_budget is not None:
        producer.total_budget = args.total_budget
        changed = True
    if args.per_expert_max is not None:
        producer.per_expert_max = args.per_expert_max
        changed = True
    if args.per_expert_min is not None:
        producer.per_expert_min = args.per_expert_min
        changed = True
    if args.strong_cost is not None:
        producer.strong_cost = args.strong_cost
        changed = True
    if args.weak_cost is not None:
        producer.weak_cost = args.weak_cost
        changed = True
    if changed:
        config.producer = producer

    # Apply expert replacements
    if args.replace_expert:
        from enrichment.transport_podcast import ALTERNATIVE_EXPERTS  # pyright: ignore[reportMissingImports]
        from enrichment.podcast_types import ALTERNATIVE_PERSONAS  # pyright: ignore[reportMissingImports]

        experts = deepcopy(config.experts)
        personas = deepcopy(config.personas)
        for spec in args.replace_expert:
            old_name, _, preset_key = spec.rpartition("=")
            if preset_key not in ALTERNATIVE_EXPERTS:
                logger.warning("Unknown expert preset '%s', ignoring", preset_key)
                continue
            new_profile = ALTERNATIVE_EXPERTS[preset_key]
            # Replace in expert profiles
            for i, exp in enumerate(experts):
                if exp.name == old_name:
                    experts[i] = deepcopy(new_profile)
                    logger.info(
                        "Replaced expert '%s' → '%s' (%s)",
                        old_name, new_profile.name, preset_key,
                    )
                    break
            else:
                logger.warning("Expert '%s' not found, ignoring", old_name)
            # Replace in personas (for Phase 3)
            if preset_key in ALTERNATIVE_PERSONAS:
                new_persona = ALTERNATIVE_PERSONAS[preset_key]
                for i, p in enumerate(personas):
                    if p.name == old_name:
                        personas[i] = deepcopy(new_persona)
                        break
        config.experts = experts
        config.personas = personas

    # Apply expert demand overrides
    if args.expert_demand:
        experts = deepcopy(config.experts)
        for spec in args.expert_demand:
            # "Eleanor Hartley:prov_narrative_technique=4"
            expert_part, _, dim_val = spec.rpartition(":")
            dim_name, _, val = dim_val.rpartition("=")
            for exp in experts:
                if exp.name == expert_part:
                    exp.demands[dim_name] = int(val)
                    logger.info(
                        "Expert '%s' %s → %s", expert_part, dim_name, val
                    )
                    break
            else:
                logger.warning("Expert '%s' not found, ignoring", expert_part)
        config.experts = experts

    # Apply arc demand overrides
    if args.arc_demand:
        arcs = deepcopy(config.arcs)
        for spec in args.arc_demand:
            arc_name, _, val = spec.rpartition("=")
            for arc in arcs:
                if arc.name == arc_name:
                    arc.demand = int(val)
                    logger.info("Arc '%s' demand → %s", arc_name, val)
                    break
            else:
                logger.warning("Arc '%s' not found, ignoring", arc_name)
        config.arcs = arcs

    if args.model:
        config.model = args.model

    # Save initial config
    run_dir = config.run_dir()
    run_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Run '%s' → %s", config.name, run_dir)

    resume_from = args.resume_from

    # --- Resume: load existing phase outputs ---
    if resume_from is not None:
        config = RunConfig.load(args.name)
        if args.model:
            config.model = args.model

    phase1: dict = {}
    if resume_from and resume_from >= 2:
        # Load Phase 1 from disk
        with open(run_dir / "phase1_assignments.json") as f:
            phase1 = json.load(f)
        logger.info("Resumed Phase 1: %d passages", phase1["count"])
    elif resume_from and resume_from >= 1:
        # Phase 1 needs re-running with existing Phase 0 segments
        logger.info("Phase 1: passage selection (resumed)")
        supp0 = compute_supplementary_demand(config.segment_templates, config.experts)
        phase1 = run_phase1(config, supplementary_demand=supp0.dimension_boost if supp0.total_boost > 0 else None)
        with open(run_dir / "phase1_assignments.json", "w") as f:
            json.dump(phase1, f, indent=2)
        logger.info("  %d passages selected", phase1["count"])
    else:
        # Phase 0: LLM segment design (before passage selection)
        supp_demand_val: dict[str, int] | None = None
        if not args.no_design_segments:
            segment_model = args.segment_model or "claude-haiku-4-5-20251001"
            logger.info("Phase 0: designing segments with %s", segment_model)
            templates = design_segments(
                config.experts, config.arcs,
                model=segment_model,
                prompt_version=config.prompt_version,
                personas=config.personas if config.prompt_version >= 3 else None,
            )
            config.segment_templates = templates
            with open(run_dir / "phase0_segments.json", "w") as f:
                json.dump([t.model_dump() for t in templates], f, indent=2)
            for t in templates:
                logger.info(
                    "  %s (%s, %d-%d)", t.name, t.segment_type,
                    t.min_passages, t.max_passages,
                )

            # Compute supplementary demand
            supp = compute_supplementary_demand(templates, config.experts)
            if supp.total_boost > 0:
                supp_demand_val = supp.dimension_boost

        config.save()

        # Phase 1: passage selection
        logger.info("Phase 1: passage selection")
        phase1 = run_phase1(config, supplementary_demand=supp_demand_val)
        with open(run_dir / "phase1_assignments.json", "w") as f:
            json.dump(phase1, f, indent=2)
        logger.info("  %d passages selected", phase1["count"])

    if args.phase < 2:
        logger.info("Stopping after Phase 1")
        return

    if resume_from and resume_from >= 3:
        # Load Phase 2 from disk
        with open(run_dir / "phase2_plan.json") as f:
            phase2 = json.load(f)
        logger.info("Resumed Phase 2")
    else:
        # Phase 2
        logger.info("Phase 2: segment assignment")
        phase2 = run_phase2(config, phase1)
        with open(run_dir / "phase2_plan.json", "w") as f:
            json.dump(phase2, f, indent=2)
        print(phase2["report"])

    if args.phase < 3:
        logger.info("Stopping after Phase 2")
        return

    # Phase 3
    logger.info("Phase 3: script generation (model=%s)", config.model)
    phase3 = run_phase3(config, phase2, phase1)
    with open(run_dir / "phase3_episode.json", "w") as f:
        json.dump(phase3, f, indent=2)

    from enrichment.podcast_types import PodcastEpisode  # pyright: ignore[reportMissingImports]
    from enrichment.generate_podcast import build_script_report  # pyright: ignore[reportMissingImports]

    episode = PodcastEpisode.model_validate(phase3)
    report = build_script_report(episode)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "report.txt"
    with open(report_path, "w") as f:
        f.write(report)
    logger.info("Saved report to %s", report_path)


if __name__ == "__main__":
    main()
