"""Execute a random-passages pipeline run (passage identity baseline).

Selects 32 random Bleak House passages (uniform random, seeded by panel).
Assigns round-robin to experts. Same Phase 0 and Phase 3.
Tests whether passage *identity* matters or just having *some* grounding text.

Usage:
    uv run python -m enrichment.random_rag_run --name rand_v01_baseline
    uv run python -m enrichment.random_rag_run --name rand_v19_all_swapped \
        --replace-expert "Eleanor Hartley=trevelyan" \
        --replace-expert "James Blackstone=sir_edmund" \
        --replace-expert "Caroline Woodcourt=dr_rosen"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
from copy import deepcopy
from pathlib import Path

from dotenv import load_dotenv

from enrichment.design_segments import (  # pyright: ignore[reportMissingImports]
    design_segments,
)
from enrichment.embedding_run import (  # pyright: ignore[reportMissingImports]
    run_phase3,
)
from enrichment.generate_podcast import (  # pyright: ignore[reportMissingImports]
    build_script_report,
)
from enrichment.episode import PodcastEpisode
from enrichment.llm.schemas import SegmentTemplate
from enrichment.personas import (
    ALTERNATIVE_PERSONAS,
    DEFAULT_PERSONAS,
    ExpertPersona,
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

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def _load_enrichment_data() -> list[dict]:
    path = DATA_DIR / "passages_enriched.json"
    with open(path) as f:
        return json.load(f)


def _panel_seed(experts: list[ExpertProfile]) -> int:
    """Deterministic seed from sorted expert names."""
    key = ",".join(sorted(e.name for e in experts))
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)


def assign_passages_random(
    experts: list[ExpertProfile],
    templates: list[SegmentTemplate],
    enrichment_data: list[dict],
    passage_target: int,
    seed: int,
) -> tuple[dict, dict]:
    """Select random passages and assign round-robin to experts and segments."""
    rng = random.Random(seed)

    # Filter to Bleak House chapters only (c1-c67)
    import re
    bh_passages = [p for p in enrichment_data if re.match(r"^c\d+$", p.get("chapter_id", ""))]
    logger.info("Pool: %d Bleak House passages", len(bh_passages))

    # Draw random sample
    selected = rng.sample(bh_passages, min(passage_target, len(bh_passages)))
    logger.info("Selected %d random passages (seed=%d)", len(selected), seed)

    # Round-robin assignment to experts
    assignments: list[dict] = []
    for i, p in enumerate(selected):
        exp = experts[i % len(experts)]
        enrichment = p.get("enrichment", {})

        provisions = {}
        for dim in [
            "prov_character_development", "prov_plot_advancement",
            "prov_thematic_depth", "prov_social_critique",
            "prov_humor_entertainment", "prov_atmosphere_setting",
            "prov_narrative_technique",
        ]:
            provisions[dim] = enrichment.get(dim, "none")

        assignments.append({
            "passage_id": p["passage_id"],
            "expert": exp.name,
            "dimension": "random",
            "arc_name": None,
            "cost": 0,
            "chapter_id": p.get("chapter_id", ""),
            "interest_score": enrichment.get("interest_score", 1),
            "characters_present": enrichment.get("characters_present", []),
            "provisions": provisions,
            "text": p.get("text", ""),
            "summary": enrichment.get("summary", ""),
            "best_quote": enrichment.get("best_quote", ""),
            "themes": enrichment.get("themes", []),
            "emotional_register": enrichment.get("emotional_register", []),
            "narrator": p.get("narrator", "unknown"),
        })

    assignments.sort(key=lambda a: a["passage_id"])

    phase1 = {
        "pipeline_type": "random",
        "count": len(assignments),
        "assignments": assignments,
    }

    # Distribute to segments: fill each to min_passages, then distribute remainder
    seg_assignments: dict[int, list[dict]] = {i: [] for i in range(len(templates))}
    assignment_queue = list(assignments)
    rng.shuffle(assignment_queue)

    # First pass: fill to min_passages
    for seg_idx, template in enumerate(templates):
        for _ in range(template.min_passages):
            if assignment_queue:
                seg_assignments[seg_idx].append(assignment_queue.pop())

    # Second pass: distribute remainder up to max_passages
    for seg_idx, template in enumerate(templates):
        while len(seg_assignments[seg_idx]) < template.max_passages and assignment_queue:
            seg_assignments[seg_idx].append(assignment_queue.pop())

    # Any remaining go to segment with fewest
    while assignment_queue:
        min_seg = min(seg_assignments, key=lambda s: len(seg_assignments[s]))
        seg_assignments[min_seg].append(assignment_queue.pop())

    segments_out = []
    for seg_idx, template in enumerate(templates):
        seg_a = seg_assignments[seg_idx]
        segments_out.append({
            "template": template.model_dump(),
            "assignments": [
                {
                    "passage_id": a["passage_id"],
                    "expert": a["expert"],
                    "dimension": a["dimension"],
                    "arc_name": a["arc_name"],
                    "chapter_id": a["chapter_id"],
                    "interest_score": a["interest_score"],
                }
                for a in seg_a
            ],
        })

    expert_counts: dict[str, int] = {}
    for a in assignments:
        expert_counts[a["expert"]] = expert_counts.get(a["expert"], 0) + 1
    chapter_set = {a["chapter_id"] for a in assignments}
    report = (
        f"Random assignment: {len(assignments)} passages from "
        f"{len(chapter_set)} chapters (seed={seed})\n"
        f"Expert distribution: {expert_counts}\n"
        f"Segments: {', '.join(f'{t.name}({len(seg_assignments[i])})' for i, t in enumerate(templates))}"
    )

    phase2 = {
        "segments": segments_out,
        "total_null_flow": 0,
        "report": report,
    }

    return phase1, phase2


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run random-passages pipeline (passage identity baseline)"
    )
    parser.add_argument("--name", required=True, help="Run name (e.g. rand_v01_baseline)")
    parser.add_argument(
        "--phase", type=int, default=3, choices=[2, 3],
        help="Stop after this phase (default: 3)",
    )
    parser.add_argument(
        "--replace-expert", action="append", default=[],
        help="Replace an expert: 'Old Name=preset_key'",
    )
    parser.add_argument("--model", default="claude-sonnet-4-6", help="Phase 3 model")
    parser.add_argument("--passage-target", type=int, default=32)
    parser.add_argument(
        "--no-design-segments", action="store_true",
        help="Skip LLM segment design; use default templates",
    )
    parser.add_argument(
        "--resume-from", type=int, default=None, choices=[3],
        help="Resume from Phase 3 using existing outputs",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

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

    seed = _panel_seed(experts)

    # Phase 0: segment design
    if args.resume_from:
        with open(run_dir / "phase0_segments.json") as f:
            templates = [SegmentTemplate.model_validate(t) for t in json.load(f)]
    elif args.no_design_segments:
        from enrichment.run_config import DEFAULT_SEGMENT_TEMPLATES  # pyright: ignore[reportMissingImports]
        templates = list(DEFAULT_SEGMENT_TEMPLATES)
    else:
        logger.info("Phase 0: designing segments")
        templates = design_segments(experts, arcs)
        with open(run_dir / "phase0_segments.json", "w") as f:
            json.dump([t.model_dump() for t in templates], f, indent=2)
        for t in templates:
            logger.info("  %s (%s, %d-%d)", t.name, t.segment_type, t.min_passages, t.max_passages)

    # Save config
    config_data = {
        "name": args.name,
        "pipeline_type": "random",
        "experts": [
            {"name": e.name, "role": e.role, "demands": e.demands} for e in experts
        ],
        "model": args.model,
        "passage_target": args.passage_target,
        "seed": seed,
    }
    with open(run_dir / "config.json", "w") as f:
        json.dump(config_data, f, indent=2)

    # Phases 1+2: random assignment
    if args.resume_from and args.resume_from >= 3:
        with open(run_dir / "phase1_assignments.json") as f:
            phase1 = json.load(f)
        with open(run_dir / "phase2_plan.json") as f:
            phase2 = json.load(f)
    else:
        logger.info("Phases 1+2: random passage assignment (seed=%d)", seed)
        enrichment_data = _load_enrichment_data()

        phase1, phase2 = assign_passages_random(
            experts, templates, enrichment_data, args.passage_target, seed,
        )

        with open(run_dir / "phase1_assignments.json", "w") as f:
            json.dump(phase1, f, indent=2)
        with open(run_dir / "phase2_plan.json", "w") as f:
            json.dump(phase2, f, indent=2)

        logger.info("  %d passages selected", phase1["count"])
        print(phase2["report"])

    if args.phase < 3:
        logger.info("Stopping after Phase 2")
        return

    # Phase 3: script generation (identical to other pipelines)
    logger.info("Phase 3: script generation (model=%s)", args.model)
    phase3 = run_phase3(phase2, phase1, args.model, personas)
    with open(run_dir / "phase3_episode.json", "w") as f:
        json.dump(phase3, f, indent=2)

    episode = PodcastEpisode.model_validate(phase3)
    report = build_script_report(episode)
    report_path = run_dir / "report.txt"
    with open(report_path, "w") as f:
        f.write(report)
    logger.info("Saved report to %s", report_path)


if __name__ == "__main__":
    main()
