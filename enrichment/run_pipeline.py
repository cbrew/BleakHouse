"""Unified pipeline runner for all passage selection strategies.

Replaces the separate run.py, no_passages_run.py, and embedding_run.py
entry points with a single module that dispatches on --pipeline.

Usage:
    uv run python -m enrichment.run_pipeline --novel bleak_house --name ext_v01 --pipeline transport
    uv run python -m enrichment.run_pipeline --novel bleak_house --name nop_v01 --pipeline no-passages
    uv run python -m enrichment.run_pipeline --novel bleak_house --name emb_v01 --pipeline embedding
    uv run python -m enrichment.run_pipeline --novel bleak_house --name ext_v01 --pipeline transport --host-prep
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from enrichment import axes
from enrichment.axes import panel_for_experts
from enrichment.design_segments import design_segments  # pyright: ignore[reportMissingImports]
from enrichment.podcast_types import (  # pyright: ignore[reportMissingImports]
    ALTERNATIVE_PERSONAS,
    DEFAULT_PERSONAS,
    DEFAULT_SEGMENT_TEMPLATES,
    ExpertPersona,
    HostBrief,
    SegmentTemplate,
)
from enrichment.segment_transport import (  # pyright: ignore[reportMissingImports]
    PassageAssignment,
    build_passage_assignments,
    solve_segment_assignment,
)
from enrichment.transport_podcast import (  # pyright: ignore[reportMissingImports]
    ALTERNATIVE_EXPERTS,
    DEFAULT_ARCS,
    DEFAULT_EXPERTS,
    ArcDemand,
    ExpertProfile,
)

load_dotenv()

logger = logging.getLogger(__name__)

RUNS_DIR = Path(__file__).resolve().parent.parent / "data" / "runs"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"

PIPELINES = ["transport", "no-passages", "embedding"]


# ---------------------------------------------------------------------------
# Preflight: enrichment-completeness smoke test
# ---------------------------------------------------------------------------


_PREFLIGHT_EMPTY_THRESHOLD = 0.05  # ≤5% empty allowed


def _preflight_check(novel: str, variant: str | None = None) -> None:
    """Validate the enrichment file before the pipeline starts.

    Catches the 'data is loadable but unusable' class — JSON parses
    fine but the fields the pipeline actually reads are empty,
    silently substituted by a missing-data fallback. (See
    enrichment/segment_transport.py:build_passage_assignments — the
    bleak_house bug that masked empty popovers for 32 long-form runs.)

    The pipeline reads `passage["text"]` (top-level) and
    `passage["enrichment"]["summary"]` (nested). best_quote is NOT
    checked because legitimate nulls exist for digressions /
    non-literary passages (quotability == "none"). Threshold ≥95%
    complete; raises RuntimeError on miss with the first 5 offending
    passage IDs for triage.
    """
    from cas import paths as cas_paths

    enr_path = cas_paths.passages_enriched(novel, variant=variant)
    enriched = json.loads(enr_path.read_text())
    if not enriched:
        raise RuntimeError(f"{enr_path} is empty")
    bad: list[str] = []
    for p in enriched:
        text = p.get("text") or ""
        summary = (p.get("enrichment") or {}).get("summary") or ""
        if not text or not summary:
            bad.append(p.get("passage_id", "<missing-id>"))
    if len(bad) / len(enriched) > _PREFLIGHT_EMPTY_THRESHOLD:
        raise RuntimeError(
            f"{len(bad)}/{len(enriched)} passages in {novel} have empty "
            f"text or enrichment.summary "
            f"(>{_PREFLIGHT_EMPTY_THRESHOLD:.0%} threshold). "
            f"First 5: {bad[:5]}"
        )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def apply_expert_replacements(
    experts: list[ExpertProfile],
    personas: list[ExpertPersona],
    specs: list[str],
) -> tuple[list[ExpertProfile], list[ExpertPersona]]:
    """Apply --replace-expert specs to both expert profiles and personas."""
    for spec in specs:
        old_name, _, preset_key = spec.rpartition("=")
        if preset_key not in ALTERNATIVE_EXPERTS:
            logger.warning("Unknown preset '%s', skipping", preset_key)
            continue
        new_profile = ALTERNATIVE_EXPERTS[preset_key]
        for i, e in enumerate(experts):
            if e.name == old_name:
                experts[i] = new_profile
                break
        if preset_key in ALTERNATIVE_PERSONAS:
            new_persona = ALTERNATIVE_PERSONAS[preset_key]
            for i, p in enumerate(personas):
                if p.name == old_name:
                    personas[i] = new_persona
                    break
    return experts, personas


def apply_arc_overrides(arcs: list[ArcDemand], specs: list[str]) -> list[ArcDemand]:
    """Apply --arc-demand overrides."""
    for spec in specs:
        name, _, val = spec.rpartition("=")
        for arc in arcs:
            if arc.name == name:
                arc.demand = int(val)
                break
    return arcs


def apply_expert_demand_overrides(
    experts: list[ExpertProfile], specs: list[str],
) -> list[ExpertProfile]:
    """Apply --expert-demand overrides."""
    for spec in specs:
        expert_part, _, val = spec.rpartition("=")
        expert_name, _, dim = expert_part.rpartition(":")
        for e in experts:
            if e.name == expert_name:
                e.demands[dim] = int(val)
                break
    return experts


def run_phase0(
    experts: list[ExpertProfile],
    arcs: list[ArcDemand],
    prompt_version: int,
    personas: list[ExpertPersona] | None,
    run_dir: Path,
    no_design: bool = False,
    segment_model: str | None = None,
    length: str = "long",
) -> list[SegmentTemplate]:
    """Phase 0: segment design. Returns segment templates.

    When the LLM call fires (no cached phase0_segments.json, no
    --no-design), records the call to <run_dir>/phase0_timings.json.
    """
    if (run_dir / "phase0_segments.json").exists():
        with open(run_dir / "phase0_segments.json") as f:
            return [SegmentTemplate.model_validate(t) for t in json.load(f)]

    if no_design:
        templates = list(DEFAULT_SEGMENT_TEMPLATES)
    else:
        from enrichment.timing import Recorder
        logger.info("Phase 0: designing segments")
        recorder = Recorder(flush_path=run_dir / "phase0_timings.json")
        kwargs: dict = dict(
            prompt_version=prompt_version,
            personas=personas if prompt_version >= 3 else None,
            recorder=recorder,
            length=length,
        )
        if segment_model is not None:
            # --segment-model is a deprecated alias post-otae-D4. The
            # design_segments call now routes through the seam
            # (task='design_segments'); use --provider-override
            # design_segments=<generator_id> instead.
            logger.warning(
                "--segment-model is ignored after BleakHouse-otae D4; "
                "use --provider-override design_segments=<generator_id>"
            )
        templates = design_segments(experts, arcs, **kwargs)
        logger.info("Recorded %d phase 0 calls to %s",
                    len(recorder.events), recorder.flush_path)

    with open(run_dir / "phase0_segments.json", "w") as f:
        json.dump([t.model_dump() for t in templates], f, indent=2)
    for t in templates:
        logger.info("  %s (%s, %d-%d)", t.name, t.segment_type, t.min_passages, t.max_passages)
    return templates


# ---------------------------------------------------------------------------
# Phase 1+2 dispatchers
# ---------------------------------------------------------------------------


def run_phases_1_2_transport(
    experts: list[ExpertProfile],
    arcs: list[ArcDemand],
    templates: list[SegmentTemplate],
    run_dir: Path,
    cluster_lambda: int | None = None,
    total_budget: int | None = None,
    per_expert_max: int | None = None,
    per_expert_min: int | None = None,
    strong_cost: int | None = None,
    weak_cost: int | None = None,
) -> tuple[dict, dict]:
    """Phases 1+2 for transport pipeline: min-cost flow."""
    from enrichment.transport_podcast import (  # pyright: ignore[reportMissingImports]
        load_passages,
        run_pipeline,
    )
    from enrichment.run_config import RunConfig  # pyright: ignore[reportMissingImports]

    # Build a RunConfig for the transport solver
    config = RunConfig(name=run_dir.name)
    config.experts = experts
    config.arcs = arcs
    config.segment_templates = templates

    # Apply Phase 1 overrides
    producer = config.producer
    if cluster_lambda is not None:
        producer.cluster_lambda = cluster_lambda
    if total_budget is not None:
        producer.total_budget = total_budget
    if per_expert_max is not None:
        producer.per_expert_max = per_expert_max
    if per_expert_min is not None:
        producer.per_expert_min = per_expert_min
    if strong_cost is not None:
        producer.strong_provision_cost = strong_cost
    if weak_cost is not None:
        producer.weak_provision_cost = weak_cost

    # Phase 1: passage selection
    logger.info("Phase 1: passage selection (transport)")
    from enrichment.design_segments import compute_supplementary_demand  # pyright: ignore[reportMissingImports]
    supp = compute_supplementary_demand(config.segment_templates, config.experts)
    supp_demand = supp.dimension_boost if supp.total_boost > 0 else None
    result = run_pipeline(config.experts, config.arcs, config.producer, supp_demand)
    passages = load_passages()
    assignments = build_passage_assignments(result, passages)

    phase1: dict = {
        "count": len(assignments),
        "assignments": [a.__dict__ for a in assignments],
    }
    with open(run_dir / "phase1_assignments.json", "w") as f:
        json.dump(phase1, f, indent=2)
    logger.info("Phase 1: %d passages selected", len(assignments))

    # Phase 2: segment assignment
    logger.info("Phase 2: segment assignment (transport)")
    plan = solve_segment_assignment(
        assignments, templates,
    )
    from enrichment.segment_transport import build_segment_report  # pyright: ignore[reportMissingImports]
    phase2: dict = {
        "segments": [
            {
                "template": seg.template.model_dump(),
                "assignments": [a.__dict__ for a in seg.assignments],
            }
            for seg in plan.segments
        ],
        "total_null_flow": plan.total_null_flow,
        "report": build_segment_report(plan),
    }
    with open(run_dir / "phase2_plan.json", "w") as f:
        json.dump(phase2, f, indent=2)

    return phase1, phase2


def run_phases_1_2_embedding(
    experts: list[ExpertProfile],
    arcs: list[ArcDemand],
    templates: list[SegmentTemplate],
    personas: list[ExpertPersona],  # noqa: ARG001
    run_dir: Path,
    curation_model: str = "claude-sonnet-4-6",
    candidates_per_query: int = 15,
    candidate_cap: int = 100,
    passage_target: int = 32,
) -> tuple[dict, dict]:
    """Phases 1+2 for embedding pipeline: retrieval + LLM curation."""
    from enrichment.embedding_podcast import RetrievalConfig  # pyright: ignore[reportMissingImports]
    from enrichment.embedding_run import (  # pyright: ignore[reportMissingImports]
        _load_enrichment_data,
        run_embedding_phases,
    )

    retrieval_config = RetrievalConfig(
        candidates_per_query=candidates_per_query,
        total_candidate_cap=candidate_cap,
        final_passage_target=passage_target,
        curation_model=curation_model,
    )

    enrichment_data = _load_enrichment_data()
    logger.info("Phases 1+2: embedding retrieval + LLM curation")
    from enrichment.timing import Recorder
    recorder = Recorder(flush_path=run_dir / "phase1_2_timings.json")
    phase1, phase2, artifacts = run_embedding_phases(
        experts, arcs, templates, enrichment_data, retrieval_config,
        recorder=recorder,
    )
    logger.info("Recorded %d phase 1+2 calls to %s",
                len(recorder.events), recorder.flush_path)

    with open(run_dir / "phase1_assignments.json", "w") as f:
        json.dump(phase1, f, indent=2)
    with open(run_dir / "phase2_plan.json", "w") as f:
        json.dump(phase2, f, indent=2)
    with open(run_dir / "embedding_artifacts.json", "w") as f:
        json.dump(artifacts, f, indent=2)

    logger.info("Phases 1+2: %d passages selected", phase1["count"])
    return phase1, phase2


def run_phases_1_2_no_passages(
    templates: list[SegmentTemplate],
    run_dir: Path,
) -> tuple[dict, dict]:
    """Phases 1+2 for no-passages: empty assignments."""
    logger.info("Phases 1+2: no passages (prior knowledge baseline)")
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
    return phase1, phase2


# ---------------------------------------------------------------------------
# Phase 2.5: Host preparation (optional)
# ---------------------------------------------------------------------------


def run_phase_2_5(
    client: anthropic.Anthropic,
    personas: list[ExpertPersona],
    phase1: dict,
    phase2: dict,
    novel_title: str,
    novel_author: str,
    run_dir: Path,
    interview_model: str = "claude-haiku-4-5-20251001",
    planning_model: str = "claude-sonnet-4-6",
    use_reference_tools: bool = False,
    length: str = "long",
) -> list[HostBrief]:
    """Phase 2.5: host preparation (pre-interviews + question planning)."""
    from enrichment.host_prep import run_host_prep  # pyright: ignore[reportMissingImports]

    logger.info("Phase 2.5: host preparation")
    pa_lookup = {a["passage_id"]: a for a in phase1.get("assignments", [])}
    segments_data = phase2.get("segments", [])
    assignments_by_segment = []
    for seg_data in segments_data:
        seg_assignments = []
        for a in seg_data.get("assignments", []):
            full = pa_lookup.get(a.get("passage_id", ""), a)
            seg_assignments.append(full)
        assignments_by_segment.append(seg_assignments)

    briefs, interviews = run_host_prep(
        personas, segments_data, assignments_by_segment,
        novel_title, novel_author,
        use_reference_tools=use_reference_tools,
        run_dir=run_dir,
        length=length,
    )

    with open(run_dir / "phase2_5_host_briefs.json", "w") as f:
        json.dump([b.model_dump() for b in briefs], f, indent=2)
    with open(run_dir / "phase2_5_interviews.json", "w") as f:
        json.dump([[iv.model_dump() for iv in seg] for seg in interviews], f, indent=2)
    logger.info("Saved %d host briefs + %d interview sets", len(briefs), len(interviews))
    return briefs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the podcast generation pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s --novel bleak_house --name ext_v01 --pipeline transport
  %(prog)s --novel mill_on_the_floss --name motf_nop_v01 --pipeline no-passages
  %(prog)s --novel bleak_house --name emb_v01 --pipeline embedding
  %(prog)s --novel bleak_house --name ext_v01_hp --pipeline transport --host-prep
""",
    )

    # Required
    parser.add_argument("--name", required=True, help="Run name")
    parser.add_argument(
        "--novel", required=True,
        help="Novel key (bleak_house, mill_on_the_floss, our_mutual_friend, "
             "north_and_south, passage_to_india)",
    )
    parser.add_argument(
        "--pipeline", default="transport", choices=PIPELINES,
        help="Passage selection strategy (default: transport)",
    )

    # Phase control
    parser.add_argument(
        "--phase", type=int, default=3, choices=[0, 1, 2, 3],
        help="Stop after this phase (default: 3)",
    )
    parser.add_argument(
        "--resume-from", type=int, default=None, choices=[1, 2, 3],
        help="Resume from this phase using existing outputs",
    )

    # Expert configuration
    parser.add_argument(
        "--replace-expert", action="append", default=[],
        help="Replace an expert: 'Old Name=preset_key'",
    )
    parser.add_argument(
        "--arc-demand", action="append", default=[],
        help="Override arc demand: 'Arc Name=N'",
    )
    parser.add_argument(
        "--expert-demand", action="append", default=[],
        help="Override expert demand: 'Expert Name:dimension=N'",
    )

    # Segment design
    parser.add_argument("--no-design-segments", action="store_true")
    parser.add_argument("--segment-model", default=None)

    # Transport-specific Phase 1 parameters
    parser.add_argument("--cluster-lambda", type=int, default=None)
    parser.add_argument("--total-budget", type=int, default=None)
    parser.add_argument("--per-expert-max", type=int, default=None)
    parser.add_argument("--per-expert-min", type=int, default=None)
    parser.add_argument("--strong-cost", type=int, default=None)
    parser.add_argument("--weak-cost", type=int, default=None)

    # Embedding-specific parameters
    parser.add_argument("--curation-model", default="claude-sonnet-4-6")
    parser.add_argument("--candidates-per-query", type=int, default=15)
    parser.add_argument("--candidate-cap", type=int, default=100)
    parser.add_argument("--passage-target", type=int, default=32)

    # Prompt and model
    parser.add_argument("--prompt-version", type=int, default=2)
    parser.add_argument("--model", default="claude-sonnet-4-6")

    # Host preparation (Phase 2.5). Defaults to ON since 2026-05-02 — the
    # production episode shape is host-prepped + reference-tooled. Use
    # --no-host-prep / --no-reference-tools to opt out for cheap runs.
    parser.add_argument("--host-prep", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--interview-model", default="claude-haiku-4-5-20251001")
    parser.add_argument(
        "--reference-tools", action=argparse.BooleanOptionalAction, default=True,
        help="Enable scholarly reference search tools in pre-interviews (requires --host-prep)",
    )
    parser.add_argument(
        "--only-host-prep", action="store_true",
        help="Regenerate only Phase 2.5 outputs, reading phases 0/1/2 from disk. "
             "Implies --host-prep; exits before phase 3.",
    )
    parser.add_argument(
        "--length", choices=("long", "short"), default="long",
        help="Episode length variant. 'long' (~90 min, ~1500 words/segment) "
             "is the legacy default. 'short' (~30 min, ~600 words/segment) "
             "uses a tighter Phase 3 prompt and writes to a sibling run dir "
             "with a '_short' suffix on the name.",
    )
    parser.add_argument(
        "--enrichment-variant", default=None,
        help="Pick a non-default enrichment file: "
             "data/novels/<novel>/passages_enriched.<variant>.json. "
             "Default (omitted) reads the canonical passages_enriched.json "
             "(Anthropic Haiku derived). Use e.g. 'openai_5_mini' for the "
             "gpt-5-mini-derived variant produced by "
             "enrichment.collect_passages_enriched_openai.",
    )
    # Provider-control surface (BleakHouse-otae / docs/provider_control_spec.md).
    # The flags activate a named profile + optional per-task overrides. Call
    # sites that have not yet migrated to the seam still hardcode their models,
    # so today the profile's effect is recorded for provenance + reads by any
    # seam-aware caller (eval harness, test_single). Migration of call sites
    # to actually consume the resolved map is tracked in Subtask D.
    parser.add_argument(
        "--provider-profile", default=None,
        help="Named LLM provider profile from params.yaml "
             "(e.g. 'production', 'all_openai'). Default: the value of "
             "params.yaml default_provider_profile.",
    )
    parser.add_argument(
        "--provider-override", action="append", default=[],
        metavar="TASK=MODEL_ID",
        help="Per-task generator override, repeatable. Layers on top of "
             "--provider-profile. Example: "
             "--provider-override host_prep_brief=openai_5_4. Task names "
             "are those in params.yaml task_models; generator IDs are those "
             "in params.yaml generators[].id.",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    # Set novel identity
    os.environ["BLEAKHOUSE_NOVEL"] = args.novel
    # Set enrichment variant (empty means default canonical file). Readers
    # in transport_podcast / segment_transport pick this up from the env.
    if args.enrichment_variant:
        os.environ["BLEAKHOUSE_ENRICHMENT_VARIANT"] = args.enrichment_variant
    else:
        os.environ.pop("BLEAKHOUSE_ENRICHMENT_VARIANT", None)

    # Activate the LLM provider profile + per-task overrides. Parse
    # 'task=model_id' pairs from --provider-override (repeatable). The seam
    # resolves the active map; for_task() callers (eval harness; future
    # migrated call sites) see the resolution. Fails loud on bad task names.
    from enrichment.llm import settings as _llm_settings
    provider_overrides: dict[str, str] = {}
    for raw in args.provider_override:
        if "=" not in raw:
            raise SystemExit(
                f"--provider-override must be TASK=MODEL_ID, got {raw!r}"
            )
        task, model_id = raw.split("=", 1)
        provider_overrides[task.strip()] = model_id.strip()
    _llm_settings.activate(args.provider_profile, provider_overrides)
    logger.info(
        "LLM provider profile: %s%s",
        _llm_settings.active_profile_name(),
        f" (overrides: {provider_overrides})" if provider_overrides else "",
    )
    # TEMPORARY (until BleakHouse-otae Subtask D lands): warn when the active
    # profile or any override would route any call to a non-default provider.
    # Today, call sites still hardcode their models; the resolved_per_task
    # block in config.json records the intended routing but does NOT yet
    # reflect what actually executed. Without this warning, an audit reading
    # the providers block would draw wrong conclusions.
    _resolved_now = _llm_settings.resolved_providers()
    _non_anthropic = {
        task: spec for task, spec in _resolved_now.items()
        if spec.provider != "anthropic"
    }
    if _non_anthropic:
        logger.warning(
            "PROVIDER ROUTING NOT YET HONORED: profile=%s resolves these tasks "
            "to non-Anthropic providers, but call sites still hardcode Anthropic: %s. "
            "Resolution is recorded in config.json.providers for audit; actual "
            "execution will not match until Subtask D of BleakHouse-otae lands.",
            _llm_settings.active_profile_name(), sorted(_non_anthropic),
        )

    # Preflight: enrichment-completeness smoke test. Catches the
    # 'data is loadable but unusable' class before any phase runs.
    _preflight_check(args.novel, variant=args.enrichment_variant)

    # Apply the _short suffix to the run name when --length short is set.
    # This keeps existing call sites that pass --name <base> unchanged for
    # long runs and writes shorts to <base>_short/ siblings, matching the
    # convention in enrichment/axes.py (LENGTH_TOKEN).
    if args.length == "short" and not args.name.endswith("_short"):
        args.name = f"{args.name}_short"
    logger.info("Novel: %s, Pipeline: %s, Length: %s, Run: %s",
                args.novel, args.pipeline, args.length, args.name)

    # Build expert and persona lists
    experts: list[ExpertProfile] = list(DEFAULT_EXPERTS)
    personas: list[ExpertPersona] = list(DEFAULT_PERSONAS)
    arcs: list[ArcDemand] = list(DEFAULT_ARCS)

    # Apply novel-specific arcs if available
    from enrichment.novel_prompts import get_novel_arcs  # pyright: ignore[reportMissingImports]
    novel_arcs = get_novel_arcs(args.novel)
    if novel_arcs:
        arcs = [ArcDemand(*a) for a in novel_arcs]

    # Apply expert replacements
    experts, personas = apply_expert_replacements(experts, personas, args.replace_expert)

    # Apply demand overrides
    if args.arc_demand:
        arcs = apply_arc_overrides(arcs, args.arc_demand)
    if args.expert_demand:
        experts = apply_expert_demand_overrides(experts, args.expert_demand)

    # Create run directory
    run_dir = RUNS_DIR / args.name
    run_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Run '%s' → %s", args.name, run_dir)

    # Resolve axes from CLI flags so the experiments-DB scanner doesn't
    # have to reverse-engineer them from the run dir name.
    # args.novel and args.pipeline use long forms (e.g. "oliver_twist",
    # "transport") but the axes validation sets are short forms ("ot",
    # "trn"). Normalize via the registries before writing.
    novel_short = (
        axes.NOVEL_BY_ID[args.novel].key
        if args.novel in axes.NOVEL_BY_ID
        else args.novel
    )
    # PIPELINE_LONG_TO_SHORT is the inverse of the alias map declared on the
    # pipeline Axis (axes.py:330). Built once here; CANONICAL_PIPELINES is
    # the long-form vocabulary.
    _pipeline_long_to_short = {"transport": "trn", "embedding": "emb", "no_passages": "nop", "rag": "rag"}
    pipeline_short = _pipeline_long_to_short.get(args.pipeline, args.pipeline)
    panel = panel_for_experts(e.name for e in experts) or "unknown"
    generator = "anthropic_sonnet_4_6"  # TODO: derive from --model when alt generators land
    config_axes = {
        "novel": novel_short,
        "pipeline": pipeline_short,
        "panel": panel,
        "hostprep": args.host_prep,
        "generator": generator,
        "length": args.length,
    }

    # Snapshot the resolved provider routing for this run. Self-describing
    # provenance: future readers can tell exactly which model served each
    # task without reading params.yaml or env state. Per the spec at
    # docs/provider_control_spec.md, resolved_per_task is the source of
    # truth — profile + overrides are recorded only as audit metadata.
    _resolved = _llm_settings.resolved_providers()
    # Find the generator id (e.g. "anthropic_haiku_4_5") for each task by
    # reverse-lookup against the registered generators so the recorded
    # value is the stable user-facing identifier, not the api_model string.
    _gen_id_by_api_model = {g.api_model: g.id for g in axes.GENERATORS_TUPLE}
    providers_block = {
        "profile": _llm_settings.active_profile_name(),
        "overrides_at_runtime": provider_overrides,
        "resolved_per_task": {
            task: _gen_id_by_api_model.get(spec.model, spec.model)
            for task, spec in _resolved.items()
        },
        # TEMPORARY: while Subtask D of BleakHouse-otae is pending, call sites
        # hardcode their providers. resolved_per_task records the INTENT of
        # the active profile + overrides; what actually ran was hardcoded
        # per call site (mostly Anthropic). Flip to true once D lands.
        "enforced_by_call_sites": False,
    }

    # Save config
    config_data = {
        "name": args.name,
        "novel": args.novel,
        "pipeline": args.pipeline,
        "experts": [{"name": e.name, "role": e.role, "demands": e.demands} for e in experts],
        "arcs": [{"name": a.name, "character": a.character, "demand": a.demand} for a in arcs],
        "model": args.model,
        "prompt_version": args.prompt_version,
        "host_prep": args.host_prep,
        "axes": config_axes,
        "generator": generator,
        # Records which enrichment variant fed this run so downstream readers
        # (e.g. expdb scan, full_episode driver) can audit provenance without
        # rummaging through env-var or symlink state. None means the canonical
        # Anthropic-derived passages_enriched.json.
        "enrichment_variant": args.enrichment_variant,
        "providers": providers_block,
    }
    with open(run_dir / "config.json", "w") as f:
        json.dump(config_data, f, indent=2)

    resume = args.resume_from

    # ── Phase 0: Segment design ──
    if resume and resume >= 1:
        templates = run_phase0(experts, arcs, args.prompt_version, personas,
                               run_dir, length=args.length)
    else:
        templates = run_phase0(
            experts, arcs, args.prompt_version, personas, run_dir,
            no_design=args.no_design_segments,
            segment_model=args.segment_model,
            length=args.length,
        )

    if args.phase < 1:
        logger.info("Stopping after Phase 0")
        return

    # ── Phases 1+2: Passage selection ──
    if resume and resume >= 3:
        # Load existing phase outputs
        with open(run_dir / "phase1_assignments.json") as f:
            phase1 = json.load(f)
        with open(run_dir / "phase2_plan.json") as f:
            phase2 = json.load(f)
        logger.info("Resumed Phases 1+2 from disk")
    elif resume and resume >= 2:
        with open(run_dir / "phase1_assignments.json") as f:
            phase1 = json.load(f)
        # Re-run Phase 2 only
        if args.pipeline == "transport":
            assignments = [PassageAssignment(**a) for a in phase1["assignments"]]  # pyright: ignore[reportCallIssue]
            plan = solve_segment_assignment(assignments, templates)
            from enrichment.segment_transport import build_segment_report  # pyright: ignore[reportMissingImports]
            phase2 = {
                "segments": [
                    {"template": seg.template.model_dump(),
                     "assignments": [a.__dict__ for a in seg.assignments]}
                    for seg in plan.segments
                ],
                "total_null_flow": plan.total_null_flow,
                "report": build_segment_report(plan),
            }
            with open(run_dir / "phase2_plan.json", "w") as f:
                json.dump(phase2, f, indent=2)
        else:
            with open(run_dir / "phase2_plan.json") as f:
                phase2 = json.load(f)
    else:
        if args.pipeline == "transport":
            phase1, phase2 = run_phases_1_2_transport(
                experts, arcs, templates, run_dir,
                cluster_lambda=args.cluster_lambda,
                total_budget=args.total_budget,
                per_expert_max=args.per_expert_max,
                per_expert_min=args.per_expert_min,
                strong_cost=args.strong_cost,
                weak_cost=args.weak_cost,
            )
        elif args.pipeline == "embedding":
            phase1, phase2 = run_phases_1_2_embedding(
                experts, arcs, templates, personas, run_dir,
                curation_model=args.curation_model,
                candidates_per_query=args.candidates_per_query,
                candidate_cap=args.candidate_cap,
                passage_target=args.passage_target,
            )
        elif args.pipeline == "no-passages":
            phase1, phase2 = run_phases_1_2_no_passages(templates, run_dir)
        else:
            raise ValueError(f"Unknown pipeline: {args.pipeline}")

    if args.phase < 3 and not args.only_host_prep:
        logger.info("Stopping after Phase 2")
        return

    # ── Phase 2.5: Host preparation (optional) ──
    host_briefs = None
    if args.host_prep or args.only_host_prep:
        from enrichment.novel_prompts import get_active_novel  # pyright: ignore[reportMissingImports]
        novel_cfg = get_active_novel(args.novel)
        host_briefs = run_phase_2_5(
            anthropic.Anthropic(), personas, phase1, phase2,
            novel_cfg.title, novel_cfg.author, run_dir,
            interview_model=args.interview_model,
            planning_model=args.model,
            use_reference_tools=args.reference_tools,
            length=args.length,
        )

    if args.only_host_prep:
        logger.info("Stopping after Phase 2.5 (--only-host-prep)")
        return

    # ── Phase 3: Script generation ──
    # Routes through the seam (task='generate_podcast'). --model is a
    # deprecated alias post-otae D6; use --provider-override generate_podcast=<id>.
    logger.info("Phase 3: script generation via seam task='generate_podcast'")
    from enrichment.generate_podcast import run_phase3  # pyright: ignore[reportMissingImports]
    phase3 = run_phase3(
        phase2, phase1, None, personas,
        prompt_version=args.prompt_version,
        host_briefs=host_briefs,
        run_dir=run_dir,
        length=args.length,
    )
    with open(run_dir / "phase3_episode.json", "w") as f:
        json.dump(phase3, f, indent=2)

    # ── Phase 4: Post-generation outputs ──
    from enrichment.post_phase3 import run_post_phase3

    run_post_phase3(run_dir, args.name)

    # ── Reading-list post-pass: shrink recommended[] to a listener-friendly
    # subset. Runs AFTER script generation so the script content doesn't
    # depend on this filter — purely a show-notes refinement.
    if args.host_prep and args.reference_tools:
        from enrichment.host_prep import filter_reading_list_recommended
        from enrichment.novel_prompts import get_active_novel  # pyright: ignore[reportMissingImports]

        post_pass_cfg = get_active_novel(args.novel)
        filter_reading_list_recommended(
            run_dir / "phase2_5_reading_list.json",
            post_pass_cfg.title, post_pass_cfg.author,
        )


if __name__ == "__main__":
    main()
