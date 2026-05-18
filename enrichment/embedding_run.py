"""Execute an embedding-only pipeline run (RAG baseline comparison).

Replaces Phases 1+2 (min-cost flow) with embedding retrieval + LLM curation.
Reuses Phase 0 (segment design) and Phase 3 (script generation) identically.

Usage:
    uv run python -m enrichment.embedding_run --name emb_baseline
    uv run python -m enrichment.embedding_run --name emb_baseline --phase 2
    uv run python -m enrichment.embedding_run --name emb_radical \
        --replace-expert "James Blackstone=sir_edmund" \
        --replace-expert "Eleanor Hartley=dr_rosen"
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from copy import deepcopy
from pathlib import Path

from dotenv import load_dotenv

from enrichment.design_segments import (  # pyright: ignore[reportMissingImports]
    design_segments,
)
from enrichment.timing import Recorder
from enrichment.embedding_podcast import (  # pyright: ignore[reportMissingImports]
    RetrievalConfig,
    build_phase_outputs,
    build_retrieval_queries,
    curate_passages,
    retrieve_candidate_pool,
)
from enrichment.generate_podcast import run_phase3  # pyright: ignore[reportMissingImports]  # noqa: F401 — re-exported
from enrichment.llm.schemas import SegmentTemplate
from enrichment.personas import (
    ALTERNATIVE_PERSONAS,
    DEFAULT_PERSONAS,
    ExpertPersona,
)
from enrichment.run_config import RUNS_DIR  # pyright: ignore[reportMissingImports]
from enrichment.transport_podcast import (  # pyright: ignore[reportMissingImports]
    ALTERNATIVE_EXPERTS,
    ArcDemand,
    DEFAULT_ARCS,
    DEFAULT_EXPERTS,
    ExpertProfile,
)

load_dotenv()

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"


# ---------------------------------------------------------------------------
# Config (simpler than RunConfig — no transport parameters)
# ---------------------------------------------------------------------------


def _load_enrichment_data() -> list[dict]:
    import os
    novel = os.environ.get("BLEAKHOUSE_NOVEL")
    if novel and novel != "bleak_house":
        path = DATA_DIR / "novels" / novel / "passages_enriched.json"
    else:
        path = DATA_DIR / "passages_enriched.json"
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Phase runners
# ---------------------------------------------------------------------------


def run_embedding_phases(
    experts: list[ExpertProfile],
    arcs: list[ArcDemand],
    templates: list[SegmentTemplate],
    enrichment_data: list[dict],
    retrieval_config: RetrievalConfig,
    recorder: Recorder | None = None,
) -> tuple[dict, dict, dict]:
    """Run retrieval + curation (replaces transport Phases 1+2).

    Returns (phase1_data, phase2_data, curation_artifacts).
    """
    # Step 1: build and execute queries
    queries = build_retrieval_queries(experts, arcs, templates, retrieval_config)
    candidates = retrieve_candidate_pool(queries, enrichment_data, retrieval_config)

    # Step 2: LLM curation
    curation = curate_passages(
        candidates, experts, arcs, templates, retrieval_config,
        recorder=recorder,
    )

    # Step 3: convert to Phase 3-compatible format
    phase1_data, phase2_data = build_phase_outputs(
        curation, candidates, enrichment_data, templates,
    )

    # Save curation artifacts for analysis
    artifacts = {
        "queries": [
            {"text": q.text[:200], "source": q.source} for q in queries
        ],
        "candidates": [
            {
                "passage_id": c.passage_id,
                "chapter_id": c.chapter_id,
                "interest_score": c.interest_score,
                "query_hits": c.query_hits,
                "best_distance": c.best_distance,
            }
            for c in candidates
        ],
        "curation_strategy": curation.strategy,
        "curation_assignments": [a.model_dump() for a in curation.assignments],
    }

    return phase1_data, phase2_data, artifacts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run embedding-only pipeline (RAG baseline)"
    )
    parser.add_argument("--name", required=True, help="Run name (e.g. emb_baseline)")
    parser.add_argument(
        "--novel", required=True,
        help="Novel key (bleak_house, mill_on_the_floss, our_mutual_friend, "
             "north_and_south, passage_to_india)",
    )
    parser.add_argument(
        "--phase", type=int, default=3, choices=[2, 3],
        help="Stop after this phase (default: 3)",
    )

    # Expert replacement (same syntax as run.py)
    parser.add_argument(
        "--replace-expert", action="append", default=[],
        help="Replace an expert: 'Old Name=preset_key'",
    )

    # Arc demand overrides
    parser.add_argument(
        "--arc-demand", action="append", default=[],
        help="Override arc demand: 'Arc Name=N'",
    )

    # Expert demand overrides (same syntax as run.py)
    parser.add_argument(
        "--expert-demand", action="append", default=[],
        help="Override expert dimension demand: 'Expert Name:dimension=N'",
    )

    # Models
    parser.add_argument("--model", default="claude-sonnet-4-6", help="Phase 3 model")
    parser.add_argument(
        "--curation-model", default="claude-sonnet-4-6",
        help="Model for LLM curation step",
    )

    # Retrieval parameters
    parser.add_argument("--candidates-per-query", type=int, default=15)
    parser.add_argument("--candidate-cap", type=int, default=100)
    parser.add_argument("--passage-target", type=int, default=32)

    # Segment design
    parser.add_argument(
        "--no-design-segments", action="store_true",
        help="Skip LLM segment design; use default templates",
    )

    # Prompt version
    parser.add_argument(
        "--prompt-version", type=int, default=2,
        help="Prompt version: 1=original, 2=supply-aware+passage-grounded (default: 2)",
    )

    # Resume
    parser.add_argument(
        "--resume-from", type=int, default=None, choices=[3],
        help="Resume from Phase 3 using existing outputs",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    # Set novel identity from CLI arg
    os.environ["BLEAKHOUSE_NOVEL"] = args.novel
    logger.info("Novel: %s", args.novel)

    # Build expert/arc configuration
    experts: list[ExpertProfile] = list(DEFAULT_EXPERTS)
    personas: list[ExpertPersona] = list(DEFAULT_PERSONAS)
    arcs: list[ArcDemand] = list(DEFAULT_ARCS)

    # Apply expert replacements
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

    # Apply arc demand overrides
    if args.arc_demand:
        arcs = deepcopy(arcs)
        for spec in args.arc_demand:
            arc_name, _, val = spec.rpartition("=")
            for arc in arcs:
                if arc.name == arc_name:
                    arc.demand = int(val)
                    logger.info("Arc '%s' demand → %s", arc_name, val)
                    break

    # Apply expert demand overrides
    if args.expert_demand:
        experts = deepcopy(experts) if not args.replace_expert else experts
        for spec in args.expert_demand:
            expert_part, _, dim_val = spec.rpartition(":")
            dim_name, _, val = dim_val.rpartition("=")
            for exp in experts:
                if exp.name == expert_part:
                    exp.demands[dim_name] = int(val)
                    logger.info("Expert '%s' %s → %s", expert_part, dim_name, val)
                    break
            else:
                logger.warning("Expert '%s' not found, ignoring", expert_part)

    # Set up run directory
    run_dir = RUNS_DIR / args.name
    run_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Run '%s' → %s", args.name, run_dir)

    retrieval_config = RetrievalConfig(
        candidates_per_query=args.candidates_per_query,
        total_candidate_cap=args.candidate_cap,
        final_passage_target=args.passage_target,
        curation_model=args.curation_model,
    )

    # Phase 0: segment design
    if args.resume_from:
        with open(run_dir / "phase0_segments.json") as f:
            templates = [SegmentTemplate.model_validate(t) for t in json.load(f)]
    elif args.no_design_segments:
        from enrichment.run_config import DEFAULT_SEGMENT_TEMPLATES  # pyright: ignore[reportMissingImports]
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
        "pipeline_type": "embedding",
        "experts": [
            {"name": e.name, "role": e.role, "demands": e.demands} for e in experts
        ],
        "arcs": [
            {"name": a.name, "character": a.character, "demand": a.demand}
            for a in arcs
        ],
        "retrieval": {
            "candidates_per_query": retrieval_config.candidates_per_query,
            "total_candidate_cap": retrieval_config.total_candidate_cap,
            "final_passage_target": retrieval_config.final_passage_target,
            "curation_model": retrieval_config.curation_model,
        },
        "model": args.model,
        "prompt_version": args.prompt_version,
        # Versions snapshot — see enrichment/versions.py / BleakHouse-vwwg.
        "versions": __import__("enrichment.versions", fromlist=["collect_run_versions"]).collect_run_versions(),
    }
    with open(run_dir / "config.json", "w") as f:
        json.dump(config_data, f, indent=2)

    # Phases 1+2: embedding retrieval + curation
    if args.resume_from and args.resume_from >= 3:
        with open(run_dir / "phase1_assignments.json") as f:
            phase1 = json.load(f)
        with open(run_dir / "phase2_plan.json") as f:
            phase2 = json.load(f)
    else:
        logger.info("Phases 1+2: embedding retrieval + LLM curation")
        enrichment_data = _load_enrichment_data()

        phase1, phase2, artifacts = run_embedding_phases(
            experts, arcs, templates, enrichment_data, retrieval_config,
        )

        with open(run_dir / "phase1_assignments.json", "w") as f:
            json.dump(phase1, f, indent=2)
        with open(run_dir / "phase2_plan.json", "w") as f:
            json.dump(phase2, f, indent=2)
        with open(run_dir / "embedding_artifacts.json", "w") as f:
            json.dump(artifacts, f, indent=2)

        logger.info("  %d passages selected", phase1["count"])
        print(phase2["report"])

    if args.phase < 3:
        logger.info("Stopping after Phase 2")
        return

    # Phase 3: script generation (identical to transport pipeline)
    logger.info("Phase 3: script generation (model=%s)", args.model)
    phase3 = run_phase3(phase2, phase1, args.model, personas, prompt_version=args.prompt_version)
    with open(run_dir / "phase3_episode.json", "w") as f:
        json.dump(phase3, f, indent=2)

    # Phase 4: Post-generation outputs
    from enrichment.post_phase3 import run_post_phase3

    run_post_phase3(run_dir, args.name)


if __name__ == "__main__":
    main()
