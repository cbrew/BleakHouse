"""Phase 2: Assign (passage, expert) pairs to episode segments via min-cost flow.

Takes the output of transport_podcast.py (passage assignments to experts)
and organizes them into a structured episode by solving a second transport
problem.  Each segment template is a demand node; each (passage, expert)
pair is a supply node.

Usage: uv run python -m enrichment.segment_transport
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from ortools.graph.python import min_cost_flow  # pyright: ignore[reportMissingImports]

from enrichment.podcast_types import (  # pyright: ignore[reportMissingImports]
    DEFAULT_SEGMENT_TEMPLATES,
    SegmentTemplate,
)
from enrichment.transport_podcast import (  # pyright: ignore[reportMissingImports]
    AggregatedResult,
    PassageRecord,
    load_passages,
    run_pipeline,
)

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PassageAssignment:
    """A (passage, expert) pair from Phase 1, enriched with metadata."""

    passage_id: str
    expert: str
    dimension: str
    arc_name: str | None
    cost: int
    # Enrichment metadata (populated from PassageRecord)
    chapter_id: str = ""
    interest_score: int = 0
    characters_present: list[str] = field(default_factory=list)
    provisions: dict[str, str] = field(default_factory=dict)
    text: str = ""
    summary: str = ""
    best_quote: str = ""
    themes: list[str] = field(default_factory=list)
    emotional_register: list[str] = field(default_factory=list)
    narrator: str = ""


@dataclass
class SegmentPlan:
    """Result of Phase 2: an ordered list of segments with assigned passages."""

    segments: list[PlannedSegment]
    unassigned: list[PassageAssignment]  # passages that didn't fit any segment
    total_null_flow: int


@dataclass
class PlannedSegment:
    """A segment with its assigned passages and metadata."""

    template: SegmentTemplate
    assignments: list[PassageAssignment]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _chapter_number(chapter_id: str) -> int:
    """Extract numeric chapter index for ordering.  'c1' -> 1, 'cP' -> -1."""
    m = re.match(r"c(\d+)", chapter_id)
    if m:
        return int(m.group(1))
    return -1


# ---------------------------------------------------------------------------
# Build passage assignments from Phase 1 result
# ---------------------------------------------------------------------------


def build_passage_assignments(
    result: AggregatedResult,
    passages: list[PassageRecord],
    enrichment_data: list[dict] | None = None,  # type: ignore[type-arg]
) -> list[PassageAssignment]:
    """Convert Phase 1 output into enriched PassageAssignment objects."""
    passage_map = {p.passage_id: p for p in passages}

    # Load full enrichment for text, summary, best_quote, themes.
    # Routed through cas.paths so novel resolution is centralised; missing
    # data is a hard error (FileNotFoundError) rather than a silent
    # fallback to empty fields. To deliberately run without enrichment,
    # pass enrichment_data=[] explicitly. (Was a silent-fallback bug:
    # bleak_house masked an empty-string substitution for 32 long-form
    # runs because the legacy path no longer existed.)
    import os

    from cas import paths as cas_paths
    enr_map: dict[str, dict] = {}  # type: ignore[type-arg]
    if enrichment_data is None:
        novel = os.environ.get("BLEAKHOUSE_NOVEL", "bleak_house")
        variant = os.environ.get("BLEAKHOUSE_ENRICHMENT_VARIANT") or None
        with open(cas_paths.passages_enriched(novel, variant=variant)) as f:
            loaded: list[dict] = json.load(f)  # type: ignore[type-arg]
    else:
        loaded = enrichment_data
    for p in loaded:
        enr_map[p["passage_id"]] = p

    assignments: list[PassageAssignment] = []

    # Dimension assignments (expert-specific)
    for a in result.assignments:
        pr = passage_map.get(a.passage_id)
        raw = enr_map.get(a.passage_id, {})
        enr = raw.get("enrichment", {})
        pa = PassageAssignment(
            passage_id=a.passage_id,
            expert=a.expert,
            dimension=a.dimension,
            arc_name=a.arc_name,
            cost=a.cost,
            chapter_id=pr.chapter_id if pr else raw.get("chapter_id", ""),
            interest_score=pr.interest_score if pr else 0,
            characters_present=pr.characters_present if pr else [],
            provisions=pr.provisions if pr else {},
            text=raw.get("text", ""),
            summary=enr.get("summary", ""),
            best_quote=enr.get("best_quote", ""),
            themes=enr.get("themes", []),
            emotional_register=enr.get("emotional_register", []),
            narrator=enr.get("narrator", ""),
        )
        assignments.append(pa)

    # Arc assignments (not expert-specific — assign to most relevant expert)
    for ar in result.arc_results:
        for a in ar.assignments:
            pr = passage_map.get(a.passage_id)
            raw = enr_map.get(a.passage_id, {})
            enr = raw.get("enrichment", {})
            pa = PassageAssignment(
                passage_id=a.passage_id,
                expert=a.expert if a.expert else "",
                dimension=a.dimension,
                arc_name=a.arc_name,
                cost=a.cost,
                chapter_id=pr.chapter_id if pr else raw.get("chapter_id", ""),
                interest_score=pr.interest_score if pr else 0,
                characters_present=pr.characters_present if pr else [],
                provisions=pr.provisions if pr else {},
                text=raw.get("text", ""),
                summary=enr.get("summary", ""),
                best_quote=enr.get("best_quote", ""),
                themes=enr.get("themes", []),
                emotional_register=enr.get("emotional_register", []),
                narrator=enr.get("narrator", ""),
            )
            assignments.append(pa)

    # Deduplicate by passage_id (keep first occurrence — dimension assignments
    # take priority over arc-only assignments for the same passage)
    seen: set[str] = set()
    deduped: list[PassageAssignment] = []
    for pa in assignments:
        if pa.passage_id not in seen:
            seen.add(pa.passage_id)
            deduped.append(pa)

    logger.info("Built %d unique passage assignments from Phase 1", len(deduped))
    return deduped


# ---------------------------------------------------------------------------
# Phase 2 solver
# ---------------------------------------------------------------------------


def solve_segment_assignment(
    assignments: list[PassageAssignment],
    templates: list[SegmentTemplate] | None = None,
    null_cost: int = 50,
    dimension_mismatch_cost: int = 5,
    arc_mismatch_cost: int = 3,
    expert_mismatch_cost: int = 2,
) -> SegmentPlan:
    """Assign passage assignments to segments via min-cost flow.

    Network:
        SUPER_SOURCE → passage nodes   (cap=1, cost=0)
        SUPER_SOURCE → NULL node       (cap=total_demand, cost=0)
        passage nodes → segment nodes  (cap=1, cost=match_cost)
        NULL → segment nodes           (cap=max_passages, cost=null_cost)
        segment nodes → SUPER_SINK     (cap=max_passages, cost=0)
    """
    resolved_templates = templates if templates is not None else DEFAULT_SEGMENT_TEMPLATES

    if not assignments:
        return SegmentPlan(
            segments=[PlannedSegment(t, []) for t in resolved_templates],
            unassigned=[],
            total_null_flow=sum(t.min_passages for t in resolved_templates),
        )

    total_demand = sum(t.max_passages for t in resolved_templates)

    # Total flow = total_demand.  Source sends flow through passages
    # (cap=1 each, cost=0) or NULL (cap=total_demand, cost=0).
    # Passages route to segments at match_cost, competing with NULL
    # at null_cost.  Since null_cost >> match_cost, the solver prefers
    # real passages.  Passages that the solver doesn't select simply
    # get no flow from source — no WASTE node needed.

    # -- Node assignment --
    SUPER_SOURCE = 0
    SUPER_SINK = 1
    NULL_NODE = 2
    next_id = 3

    passage_node: dict[int, int] = {}  # index in assignments -> node id
    for i in range(len(assignments)):
        passage_node[i] = next_id
        next_id += 1

    segment_node: dict[int, int] = {}  # index in templates -> node id
    for i in range(len(resolved_templates)):
        segment_node[i] = next_id
        next_id += 1

    # -- Build network --
    smcf = min_cost_flow.SimpleMinCostFlow()

    # Track arcs for result extraction
    arc_meta: list[tuple[str, int, int]] = []  # (type, source_idx, target_idx)

    # SUPER_SOURCE → each passage (cap=1, cost=0)
    for i in range(len(assignments)):
        smcf.add_arc_with_capacity_and_unit_cost(
            SUPER_SOURCE, passage_node[i], 1, 0
        )
        arc_meta.append(("source_to_passage", i, -1))

    # SUPER_SOURCE → NULL (cap=total_demand, cost=0)
    smcf.add_arc_with_capacity_and_unit_cost(
        SUPER_SOURCE, NULL_NODE, total_demand, 0
    )
    arc_meta.append(("source_to_null", -1, -1))

    # Passage → Segment arcs (cap=1, cost=match_cost)
    for i, pa in enumerate(assignments):
        for j, tmpl in enumerate(resolved_templates):
            cost = _compute_match_cost(
                pa, tmpl,
                dimension_mismatch_cost=dimension_mismatch_cost,
                arc_mismatch_cost=arc_mismatch_cost,
                expert_mismatch_cost=expert_mismatch_cost,
            )
            smcf.add_arc_with_capacity_and_unit_cost(
                passage_node[i], segment_node[j], 1, cost
            )
            arc_meta.append(("passage_to_segment", i, j))

    # NULL → each segment (cap=max_passages, cost=null_cost)
    for j, tmpl in enumerate(resolved_templates):
        smcf.add_arc_with_capacity_and_unit_cost(
            NULL_NODE, segment_node[j], tmpl.max_passages, null_cost
        )
        arc_meta.append(("null_to_segment", -1, j))

    # Segment → SUPER_SINK (cap=max_passages, cost=0)
    for j, tmpl in enumerate(resolved_templates):
        smcf.add_arc_with_capacity_and_unit_cost(
            segment_node[j], SUPER_SINK, tmpl.max_passages, 0
        )
        arc_meta.append(("segment_to_sink", j, -1))

    # Supply/demand
    smcf.set_node_supply(SUPER_SOURCE, total_demand)
    smcf.set_node_supply(SUPER_SINK, -total_demand)

    # -- Solve --
    status = smcf.solve()

    if status != smcf.OPTIMAL:
        raise RuntimeError(
            f"Segment transport: solver returned {status} (expected OPTIMAL). "
            f"total_demand={total_demand}, assignments={len(assignments)}, "
            f"segments={len(resolved_templates)}"
        )

    logger.info("Segment transport: optimal cost = %d", smcf.optimal_cost())

    # -- Extract results --
    segment_assignments: dict[int, list[PassageAssignment]] = {
        j: [] for j in range(len(resolved_templates))
    }
    assigned_passage_indices: set[int] = set()
    total_null = 0

    for arc_idx in range(smcf.num_arcs()):
        flow = smcf.flow(arc_idx)
        if flow <= 0:
            continue
        arc_type, src_idx, tgt_idx = arc_meta[arc_idx]

        if arc_type == "passage_to_segment":
            segment_assignments[tgt_idx].append(assignments[src_idx])
            assigned_passage_indices.add(src_idx)
        elif arc_type == "null_to_segment":
            total_null += flow

    # Sort each segment's passages by chapter order
    for j in segment_assignments:
        segment_assignments[j].sort(key=lambda pa: _chapter_number(pa.chapter_id))

    # Build result
    planned_segments = [
        PlannedSegment(
            template=resolved_templates[j],
            assignments=segment_assignments[j],
        )
        for j in range(len(resolved_templates))
    ]

    unassigned = [
        assignments[i]
        for i in range(len(assignments))
        if i not in assigned_passage_indices
    ]

    return SegmentPlan(
        segments=planned_segments,
        unassigned=unassigned,
        total_null_flow=total_null,
    )


def _compute_match_cost(
    pa: PassageAssignment,
    tmpl: SegmentTemplate,
    dimension_mismatch_cost: int = 5,
    arc_mismatch_cost: int = 3,
    expert_mismatch_cost: int = 2,
) -> int:
    """Compute cost of assigning a passage to a segment."""
    cost = 0

    # Dimension match
    if tmpl.preferred_dimensions:
        if pa.dimension not in tmpl.preferred_dimensions:
            cost += dimension_mismatch_cost

    # Arc match
    if tmpl.preferred_arcs:
        if pa.arc_name and pa.arc_name not in tmpl.preferred_arcs:
            cost += arc_mismatch_cost
        elif not pa.arc_name:
            # No arc — mild penalty for arc-focused segments
            cost += arc_mismatch_cost // 2

    # Expert match
    if tmpl.preferred_experts:
        if pa.expert and pa.expert not in tmpl.preferred_experts:
            cost += expert_mismatch_cost

    # Narrative adjacency: reward passages from nearby chapters going
    # to the same segment.  We approximate by computing mean chapter
    # distance to other eligible passages for this segment.
    # For now, just use interest score as a tiebreaker: higher interest = lower cost
    interest_bonus = max(0, 3 - pa.interest_score)  # score 5 -> 0, score 0 -> 3
    cost += interest_bonus

    return cost


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def build_segment_report(plan: SegmentPlan) -> str:
    """Generate a human-readable report of the segment assignment."""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("PODCAST EPISODE — SEGMENT PLAN")
    lines.append("=" * 72)
    lines.append("")

    for seg in plan.segments:
        n = len(seg.assignments)
        fill = "FULL" if n >= seg.template.min_passages else "THIN"
        lines.append(
            f"--- {seg.template.name} ({seg.template.segment_type}) "
            f"[{n}/{seg.template.max_passages}] {fill} ---"
        )
        for pa in seg.assignments:
            arc_tag = f" [arc: {pa.arc_name}]" if pa.arc_name else ""
            expert_tag = f" ({pa.expert})" if pa.expert else ""
            lines.append(
                f"  {pa.passage_id:12s} ch={pa.chapter_id:5s} "
                f"dim={pa.dimension:30s} interest={pa.interest_score}"
                f"{expert_tag}{arc_tag}"
            )
            if pa.summary:
                preview = pa.summary[:80] + "..." if len(pa.summary) > 80 else pa.summary
                lines.append(f"{'':14s} {preview}")
        lines.append("")

    if plan.unassigned:
        lines.append("-" * 72)
        lines.append(f"UNASSIGNED PASSAGES ({len(plan.unassigned)}):")
        for pa in plan.unassigned:
            lines.append(f"  {pa.passage_id} ({pa.expert}) dim={pa.dimension}")
        lines.append("")

    lines.append("-" * 72)
    lines.append(f"Total NULL flow: {plan.total_null_flow}")
    total_assigned = sum(len(s.assignments) for s in plan.segments)
    lines.append(f"Total passages assigned to segments: {total_assigned}")

    # Coverage
    all_chapters = sorted(
        {pa.chapter_id for s in plan.segments for pa in s.assignments}
    )
    all_chars: set[str] = set()
    for s in plan.segments:
        for pa in s.assignments:
            all_chars.update(pa.characters_present)
    lines.append(f"Chapters covered: {len(all_chapters)} — {', '.join(all_chapters)}")
    lines.append(f"Characters featured: {len(all_chars)}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    # Phase 1: passage selection
    logger.info("Running Phase 1: passage selection")
    result = run_pipeline()
    passages = load_passages()

    # Build enriched assignments
    assignments = build_passage_assignments(result, passages)

    # Phase 2: segment assignment
    logger.info("Running Phase 2: segment assignment")
    plan = solve_segment_assignment(assignments)

    # Report
    report = build_segment_report(plan)
    print(report)

    # Save plan
    plan_data = {
        "segments": [
            {
                "name": seg.template.name,
                "segment_type": seg.template.segment_type,
                "passages": [
                    {
                        "passage_id": pa.passage_id,
                        "expert": pa.expert,
                        "dimension": pa.dimension,
                        "arc_name": pa.arc_name,
                        "chapter_id": pa.chapter_id,
                        "interest_score": pa.interest_score,
                        "summary": pa.summary,
                        "best_quote": pa.best_quote,
                    }
                    for pa in seg.assignments
                ],
            }
            for seg in plan.segments
        ],
        "unassigned": [
            {"passage_id": pa.passage_id, "expert": pa.expert}
            for pa in plan.unassigned
        ],
        "total_null_flow": plan.total_null_flow,
    }
    output_path = DATA_DIR / "segment_plan.json"
    with open(output_path, "w") as f:
        json.dump(plan_data, f, indent=2)
    logger.info("Saved segment plan to %s", output_path)


if __name__ == "__main__":
    main()
