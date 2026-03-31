"""Execute a no-passages pipeline run (prior knowledge baseline).

Phase 3 receives expert personas + segment structure but zero passages.
Isolates how much of script quality comes from the LLM's prior knowledge
of Bleak House vs the specific passages provided.

Usage:
    uv run python -m enrichment.no_passages_run --name nop_v01_baseline
    uv run python -m enrichment.no_passages_run --name nop_v19_all_swapped \
        --replace-expert "Eleanor Hartley=trevelyan" \
        --replace-expert "James Blackstone=sir_edmund" \
        --replace-expert "Caroline Woodcourt=dr_rosen"
"""

from __future__ import annotations

import argparse
import json
import logging
from copy import deepcopy

from dotenv import load_dotenv

from enrichment.design_segments import (  # pyright: ignore[reportMissingImports]
    design_segments,
)
from enrichment.embedding_run import (  # pyright: ignore[reportMissingImports]
    run_phase3,
)
from enrichment.podcast_types import (  # pyright: ignore[reportMissingImports]
    ALTERNATIVE_PERSONAS,
    DEFAULT_PERSONAS,
    ExpertPersona,
    SegmentTemplate,
)
from enrichment.run_config import RUNS_DIR  # pyright: ignore[reportMissingImports]
from enrichment.transport_podcast import (  # pyright: ignore[reportMissingImports]
    ALTERNATIVE_EXPERTS,
    DEFAULT_ARCS,
    DEFAULT_EXPERTS,
    ExpertProfile,
)

load_dotenv()

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run no-passages pipeline (prior knowledge baseline)"
    )
    parser.add_argument("--name", required=True, help="Run name (e.g. nop_v01_baseline)")
    parser.add_argument(
        "--novel", required=True,
        help="Novel key (bleak_house, mill_on_the_floss, our_mutual_friend, "
             "north_and_south, passage_to_india)",
    )
    parser.add_argument("--model", default="claude-sonnet-4-6", help="Phase 3 model")
    parser.add_argument(
        "--replace-expert", action="append", default=[],
        help="Replace an expert: 'Old Name=preset_key'",
    )
    parser.add_argument(
        "--no-design-segments", action="store_true",
        help="Skip LLM segment design; use default templates",
    )
    parser.add_argument(
        "--prompt-version", type=int, default=2,
        help="Prompt version: 1=original, 2=supply-aware+passage-grounded (default: 2)",
    )
    parser.add_argument(
        "--resume-from", type=int, default=None, choices=[3],
        help="Resume from Phase 3 using existing Phase 0 output",
    )
    parser.add_argument(
        "--host-prep", action="store_true",
        help="Enable host preparation: pre-interviews + question planning",
    )
    parser.add_argument(
        "--interview-model", default="claude-haiku-4-5-20251001",
        help="Model for Phase 2.5a pre-interviews (default: haiku)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    # Set novel identity from CLI arg
    import os
    os.environ["BLEAKHOUSE_NOVEL"] = args.novel
    logger.info("Novel: %s", args.novel)

    # Build expert/persona configuration
    experts: list[ExpertProfile] = list(DEFAULT_EXPERTS)
    personas: list[ExpertPersona] = list(DEFAULT_PERSONAS)
    arcs = list(DEFAULT_ARCS)

    if args.replace_expert:
        experts = deepcopy(experts)
        personas = deepcopy(personas)
        for spec in args.replace_expert:
            old_name, _, preset_key = spec.rpartition("=")
            if preset_key not in ALTERNATIVE_EXPERTS:
                logger.warning("Unknown expert preset '%s'", preset_key)
                continue
            new_profile = ALTERNATIVE_EXPERTS[preset_key]
            for i, exp in enumerate(experts):
                if exp.name == old_name:
                    experts[i] = deepcopy(new_profile)
                    logger.info("Replaced expert '%s' → '%s'", old_name, new_profile.name)
                    break
            if preset_key in ALTERNATIVE_PERSONAS:
                new_persona = ALTERNATIVE_PERSONAS[preset_key]
                for i, p in enumerate(personas):
                    if p.name == old_name:
                        personas[i] = deepcopy(new_persona)
                        break

    # Set up run directory
    run_dir = RUNS_DIR / args.name
    run_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Run '%s' → %s", args.name, run_dir)

    # Phase 0: segment design
    if args.resume_from:
        with open(run_dir / "phase0_segments.json") as f:
            templates = [SegmentTemplate.model_validate(t) for t in json.load(f)]
    elif args.no_design_segments:
        from enrichment.podcast_types import DEFAULT_SEGMENT_TEMPLATES  # pyright: ignore[reportMissingImports]
        templates = list(DEFAULT_SEGMENT_TEMPLATES)
    else:
        logger.info("Phase 0: designing segments")
        templates = design_segments(
            experts, arcs,
            prompt_version=args.prompt_version,
            personas=personas if args.prompt_version >= 3 else None,
        )
        with open(run_dir / "phase0_segments.json", "w") as f:
            json.dump([t.model_dump() for t in templates], f, indent=2)
        for t in templates:
            logger.info("  %s (%s, %d-%d)", t.name, t.segment_type, t.min_passages, t.max_passages)

    # Save config
    config_data = {
        "name": args.name,
        "pipeline_type": "no_passages",
        "experts": [
            {"name": e.name, "role": e.role, "demands": e.demands} for e in experts
        ],
        "model": args.model,
        "prompt_version": args.prompt_version,
        "passage_target": 0,
    }
    with open(run_dir / "config.json", "w") as f:
        json.dump(config_data, f, indent=2)

    # Phases 1+2: empty assignments (no passages)
    phase1: dict = {
        "pipeline_type": "no_passages",
        "count": 0,
        "assignments": [],
    }

    segments_out = []
    for template in templates:
        segments_out.append({
            "template": template.model_dump(),
            "assignments": [],
        })

    phase2: dict = {
        "segments": segments_out,
        "total_null_flow": 0,
        "report": f"No-passages baseline: 0 passages, {len(templates)} segments",
    }

    with open(run_dir / "phase1_assignments.json", "w") as f:
        json.dump(phase1, f, indent=2)
    with open(run_dir / "phase2_plan.json", "w") as f:
        json.dump(phase2, f, indent=2)

    logger.info("Phases 1+2: no passages (prior knowledge baseline)")

    # Phase 2.5: Host preparation (optional)
    host_briefs = None
    if args.host_prep:
        from enrichment.host_prep import run_host_prep  # pyright: ignore[reportMissingImports]
        from enrichment.novel_prompts import get_active_novel  # pyright: ignore[reportMissingImports]

        novel_cfg = get_active_novel(args.novel)
        logger.info("Phase 2.5: host preparation (interview=%s)", args.interview_model)

        segments_data = phase2.get("segments", [])
        assignments_by_segment = [[] for _ in segments_data]  # no passages

        host_briefs, host_interviews = run_host_prep(
            __import__("anthropic").Anthropic(),
            personas, segments_data, assignments_by_segment,
            novel_cfg.title, novel_cfg.author,
            interview_model=args.interview_model,
            planning_model=args.model,
        )
        with open(run_dir / "phase2_5_host_briefs.json", "w") as f:
            json.dump([b.model_dump() for b in host_briefs], f, indent=2)
        with open(run_dir / "phase2_5_interviews.json", "w") as f:
            json.dump([[iv.model_dump() for iv in seg] for seg in host_interviews], f, indent=2)
        logger.info("Saved %d host briefs + %d interview sets", len(host_briefs), len(host_interviews))

    # Phase 3: script generation
    logger.info("Phase 3: script generation (model=%s)", args.model)
    phase3 = run_phase3(phase2, phase1, args.model, personas,
                        prompt_version=args.prompt_version, host_briefs=host_briefs)
    from enrichment.podcast_types import fix_turn_roles
    fix_turn_roles(phase3, personas)
    with open(run_dir / "phase3_episode.json", "w") as f:
        json.dump(phase3, f, indent=2)

    # Phase 4: Post-generation outputs
    from enrichment.post_phase3 import run_post_phase3

    run_post_phase3(run_dir, args.name)


if __name__ == "__main__":
    main()
