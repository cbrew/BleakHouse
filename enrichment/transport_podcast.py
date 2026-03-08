"""Podcast expert assignment via min-cost flow (optimal transport).

Solves per-dimension flow problems to assign enriched passages to podcast
experts, then aggregates results.  Character arcs get separate flow problems.

Usage: uv run python -m enrichment.transport_podcast
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from ortools.graph.python import min_cost_flow  # pyright: ignore[reportMissingModuleSource]

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"

PASSAGES_FILE = DATA_DIR / "passages_enriched.json"
CLUSTERS_LITERARY_FILE = DATA_DIR / "clusters_literary.json"
CLUSTERS_CHARACTERS_FILE = DATA_DIR / "clusters_characters.json"
OUTPUT_FILE = DATA_DIR / "transport_assignments.json"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROVISION_DIMENSIONS = [
    "prov_character_development",
    "prov_plot_advancement",
    "prov_thematic_depth",
    "prov_social_critique",
    "prov_humor_entertainment",
    "prov_atmosphere_setting",
    "prov_narrative_technique",
]

STRENGTH_TO_SUPPLY: dict[str, int] = {
    "none": 0,
    "weak": 1,
    "strong": 2,
}

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ExpertProfile:
    name: str
    role: str  # e.g. "literary_critic", "social_historian", "close_reader"
    demands: dict[str, int]  # prov_field -> demand units (0/1/2)


@dataclass
class ArcDemand:
    name: str  # "Richard's deterioration"
    character: str  # "Richard Carstone"
    demand: int  # passages wanted
    require_field: str  # e.g. "prov_character_development"
    require_value: str  # e.g. "not_none" (anything except "none")
    prefer_min_interest: int  # e.g. 3


@dataclass
class ProducerConfig:
    total_budget: int = 60  # max passages total
    per_expert_max: int = 25  # max per expert
    per_expert_min: int = 8  # min per expert
    cluster_capacity: int = 3  # max passages drawn from one cluster
    cluster_penalty: int = 5  # per-unit cost for flowing through a cluster node
    null_cost: int = 100  # cost for unmet demand
    strong_cost: int = 1  # cost for strong provision match
    weak_cost: int = 3  # cost for weak provision match


@dataclass
class Assignment:
    passage_id: str
    expert: str
    dimension: str  # which prov_* field motivated it
    cost: int
    arc_name: str | None = None  # which character arc, if any


@dataclass
class GapReport:
    dimension: str
    expert: str
    demand: int
    supplied: int
    null_flow: int  # unmet demand


# ---------------------------------------------------------------------------
# Default experts and arcs for Bleak House
# ---------------------------------------------------------------------------

DEFAULT_EXPERTS = [
    ExpertProfile(
        name="Dr. Hartley",
        role="literary_critic",
        demands={
            "prov_narrative_technique": 2,
            "prov_character_development": 2,
            "prov_thematic_depth": 1,
        },
    ),
    ExpertProfile(
        name="Prof. Blackstone",
        role="social_historian",
        demands={
            "prov_social_critique": 2,
            "prov_atmosphere_setting": 2,
            "prov_thematic_depth": 1,
        },
    ),
    ExpertProfile(
        name="Ms. Woodcourt",
        role="close_reader",
        demands={
            "prov_humor_entertainment": 2,
            "prov_character_development": 1,
            "prov_atmosphere_setting": 1,
        },
    ),
]

DEFAULT_ARCS = [
    ArcDemand(
        "Richard's deterioration",
        "Richard Carstone",
        6,
        "prov_character_development",
        "not_none",
        3,
    ),
    ArcDemand(
        "Lady Dedlock's secret",
        "Lady Dedlock",
        5,
        "prov_plot_advancement",
        "not_none",
        3,
    ),
    ArcDemand(
        "Jo's suffering",
        "Jo",
        4,
        "prov_social_critique",
        "not_none",
        2,
    ),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def git_short_hash() -> str:
    """Return the short git hash of HEAD, or 'unknown'."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def make_timestamp() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")


def make_tag() -> str:
    return f"{make_timestamp()}_{git_short_hash()}"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


@dataclass
class PassageRecord:
    """Flat representation of an enriched passage for the flow solver."""

    passage_id: str
    chapter_id: str
    interest_score: int
    characters_present: list[str]
    provisions: dict[str, str]  # prov_field -> "none"/"weak"/"strong"
    literary_cluster: int
    character_cluster: int


def load_passages() -> list[PassageRecord]:
    """Load passages_enriched.json and cluster assignments."""
    logger.info("Loading passages from %s", PASSAGES_FILE)
    with open(PASSAGES_FILE) as f:
        raw_passages: list[dict] = json.load(f)  # type: ignore[type-arg]

    # Load cluster assignments (passage_id -> cluster_id)
    clusters_lit: dict[str, int] = {}
    clusters_char: dict[str, int] = {}
    if CLUSTERS_LITERARY_FILE.exists():
        with open(CLUSTERS_LITERARY_FILE) as f:
            clusters_lit = json.load(f)
    if CLUSTERS_CHARACTERS_FILE.exists():
        with open(CLUSTERS_CHARACTERS_FILE) as f:
            clusters_char = json.load(f)

    records: list[PassageRecord] = []
    for p in raw_passages:
        enr = p.get("enrichment")
        if enr is None:
            continue
        pid = p["passage_id"]
        provisions = {
            dim: enr.get(dim, "none") for dim in PROVISION_DIMENSIONS
        }
        records.append(
            PassageRecord(
                passage_id=pid,
                chapter_id=p["chapter_id"],
                interest_score=enr.get("interest_score", 0),
                characters_present=enr.get("characters_present", []),
                provisions=provisions,
                literary_cluster=clusters_lit.get(pid, -1),
                character_cluster=clusters_char.get(pid, -1),
            )
        )

    logger.info("Loaded %d passages with enrichment", len(records))
    return records


# ---------------------------------------------------------------------------
# Per-dimension flow solver
# ---------------------------------------------------------------------------


@dataclass
class DimensionResult:
    """Result of solving one per-dimension flow problem."""

    dimension: str
    assignments: list[Assignment]
    gaps: list[GapReport]
    total_demand: int
    total_supplied: int
    total_null_flow: int


def solve_dimension(
    dimension: str,
    passages: list[PassageRecord],
    experts: list[ExpertProfile],
    config: ProducerConfig,
) -> DimensionResult:
    """Build and solve the min-cost flow network for one provision dimension.

    Redundancy is controlled via intermediate cluster nodes rather than convex
    arc duplication.  Each passage belongs to a literary cluster.  The network
    routes flow through cluster nodes with bounded capacity and a per-unit
    penalty, so the solver naturally spreads across clusters.

    Network structure (5 layers):
        SUPER_SOURCE -> passage nodes         (cap=supply, cost=0)
        SUPER_SOURCE -> NULL node             (cap=total_demand, cost=0)
        passage nodes -> cluster nodes        (cap=supply, cost=base_cost)
        cluster nodes -> expert nodes         (cap=cluster_capacity, cost=cluster_penalty)
        NULL -> expert nodes                  (cap=expert demand, cost=null_cost)
        expert nodes -> SUPER_SINK            (cap=demand, cost=0)
    """
    # Identify demanding experts for this dimension
    demanding_experts = [
        (exp, exp.demands.get(dimension, 0))
        for exp in experts
        if exp.demands.get(dimension, 0) > 0
    ]
    if not demanding_experts:
        return DimensionResult(dimension, [], [], 0, 0, 0)

    total_demand = sum(d for _, d in demanding_experts)

    # Identify eligible passages: those with provision != "none"
    eligible = [
        p for p in passages if p.provisions.get(dimension, "none") != "none"
    ]
    if not eligible:
        gaps = [
            GapReport(dimension, exp.name, d, 0, d)
            for exp, d in demanding_experts
        ]
        return DimensionResult(dimension, [], gaps, total_demand, 0, total_demand)

    # Group eligible passages by literary cluster
    cluster_members: dict[int, list[PassageRecord]] = {}
    for p in eligible:
        cluster_members.setdefault(p.literary_cluster, []).append(p)

    logger.debug(
        "Dimension %s: %d eligible passages in %d clusters, "
        "%d demanding experts, total_demand=%d",
        dimension,
        len(eligible),
        len(cluster_members),
        len(demanding_experts),
        total_demand,
    )

    # -- Node assignment --
    SUPER_SOURCE = 0
    SUPER_SINK = 1
    NULL_NODE = 2
    next_id = 3

    passage_node: dict[str, int] = {}
    for p in eligible:
        passage_node[p.passage_id] = next_id
        next_id += 1

    cluster_node: dict[int, int] = {}
    for cid in cluster_members:
        cluster_node[cid] = next_id
        next_id += 1

    expert_node: dict[str, int] = {}
    for exp, _ in demanding_experts:
        expert_node[exp.name] = next_id
        next_id += 1

    # -- Build the flow network --
    smcf = min_cost_flow.SimpleMinCostFlow()

    # Track arc metadata for result extraction
    # (tail_type, tail_id, head_type, head_id, unit_cost)
    arc_meta: list[tuple[str, str, str, str, int]] = []

    def add_arc(tail: int, head: int, capacity: int, unit_cost: int,
                tail_type: str, tail_id: str, head_type: str, head_id: str) -> None:
        smcf.add_arc_with_capacity_and_unit_cost(tail, head, capacity, unit_cost)
        arc_meta.append((tail_type, tail_id, head_type, head_id, unit_cost))

    # SUPER_SOURCE -> each passage (capacity = supply, cost = 0)
    for p in eligible:
        supply = STRENGTH_TO_SUPPLY[p.provisions[dimension]]
        add_arc(
            SUPER_SOURCE, passage_node[p.passage_id], supply, 0,
            "source", "SUPER_SOURCE", "passage", p.passage_id,
        )

    # SUPER_SOURCE -> NULL (capacity = total_demand, cost = 0)
    add_arc(
        SUPER_SOURCE, NULL_NODE, total_demand, 0,
        "source", "SUPER_SOURCE", "null", "NULL",
    )

    # Passage -> Cluster (capacity = supply, cost = base provision cost)
    for cid, members in cluster_members.items():
        for p in members:
            strength = p.provisions[dimension]
            base_cost = config.strong_cost if strength == "strong" else config.weak_cost
            supply = STRENGTH_TO_SUPPLY[strength]
            add_arc(
                passage_node[p.passage_id], cluster_node[cid], supply, base_cost,
                "passage", p.passage_id, "cluster", str(cid),
            )

    # Cluster -> Expert (capacity = cluster_capacity, cost = cluster_penalty)
    # This is the redundancy control: each cluster can send at most
    # cluster_capacity units to each expert.
    for cid in cluster_members:
        for exp, _ in demanding_experts:
            add_arc(
                cluster_node[cid], expert_node[exp.name],
                config.cluster_capacity, config.cluster_penalty,
                "cluster", str(cid), "expert", exp.name,
            )

    # NULL -> each expert (capacity = expert's demand, cost = null_cost)
    for exp, demand in demanding_experts:
        add_arc(
            NULL_NODE, expert_node[exp.name], demand, config.null_cost,
            "null", "NULL", "expert", exp.name,
        )

    # Expert -> SUPER_SINK (capacity = demand, cost = 0)
    for exp, demand in demanding_experts:
        add_arc(
            expert_node[exp.name], SUPER_SINK, demand, 0,
            "expert", exp.name, "sink", "SUPER_SINK",
        )

    # Set supply/demand on source and sink
    smcf.set_node_supply(SUPER_SOURCE, total_demand)
    smcf.set_node_supply(SUPER_SINK, -total_demand)

    # -- Solve --
    status = smcf.solve()

    if status != smcf.OPTIMAL:
        logger.warning(
            "Dimension %s: solver returned status %d (not optimal)", dimension, status
        )
        gaps = [
            GapReport(dimension, exp.name, d, 0, d)
            for exp, d in demanding_experts
        ]
        return DimensionResult(dimension, [], gaps, total_demand, 0, total_demand)

    logger.debug(
        "Dimension %s: optimal cost = %d", dimension, smcf.optimal_cost()
    )

    # -- Extract assignments and null flows --
    # We need passage→expert assignments.  The flow goes
    # passage→cluster→expert, so we trace passage→cluster arcs with flow,
    # then cluster→expert arcs with flow, and attribute each passage-unit
    # to the expert(s) its cluster feeds.
    #
    # Simpler approach: for each passage→cluster arc with flow, record
    # which passages contribute to each cluster.  For each cluster→expert
    # arc with flow, distribute the flow back to contributing passages
    # (by passage order, deterministic).

    # Collect passage contributions to clusters
    cluster_passage_flow: dict[int, list[tuple[str, int, int]]] = {}  # cid -> [(pid, flow, cost)]
    # Collect cluster flow to experts
    cluster_expert_flow: dict[tuple[int, str], int] = {}  # (cid, expert) -> flow
    null_flows_by_expert: dict[str, int] = {exp.name: 0 for exp, _ in demanding_experts}

    for arc_idx in range(smcf.num_arcs()):
        flow = smcf.flow(arc_idx)
        if flow <= 0:
            continue
        tail_type, tail_id, head_type, head_id, unit_cost = arc_meta[arc_idx]

        if tail_type == "passage" and head_type == "cluster":
            cid = int(head_id)
            cluster_passage_flow.setdefault(cid, []).append((tail_id, flow, unit_cost))
        elif tail_type == "cluster" and head_type == "expert":
            cid = int(tail_id)
            cluster_expert_flow[(cid, head_id)] = flow
        elif tail_type == "null" and head_type == "expert":
            null_flows_by_expert[head_id] += flow

    # Attribute passage→expert assignments through clusters
    assignments: list[Assignment] = []
    for (cid, expert_name), expert_flow in cluster_expert_flow.items():
        remaining = expert_flow
        for pid, p_flow, p_cost in cluster_passage_flow.get(cid, []):
            if remaining <= 0:
                break
            assigned = min(p_flow, remaining)
            for _ in range(assigned):
                assignments.append(
                    Assignment(
                        passage_id=pid,
                        expert=expert_name,
                        dimension=dimension,
                        cost=p_cost + config.cluster_penalty,
                    )
                )
            remaining -= assigned

    # Build gap reports
    demand_by_expert = {exp.name: d for exp, d in demanding_experts}
    gaps: list[GapReport] = []
    total_null = sum(null_flows_by_expert.values())

    for exp_name, null_flow in null_flows_by_expert.items():
        if null_flow > 0:
            d = demand_by_expert[exp_name]
            gaps.append(
                GapReport(dimension, exp_name, d, d - null_flow, null_flow)
            )

    total_supplied = total_demand - total_null

    return DimensionResult(
        dimension=dimension,
        assignments=assignments,
        gaps=gaps,
        total_demand=total_demand,
        total_supplied=total_supplied,
        total_null_flow=total_null,
    )


# ---------------------------------------------------------------------------
# Character arc flow solver
# ---------------------------------------------------------------------------


@dataclass
class ArcResult:
    """Result of solving one character arc flow problem."""

    arc: ArcDemand
    assignments: list[Assignment]
    null_flow: int


def solve_arc(
    arc: ArcDemand,
    passages: list[PassageRecord],
    config: ProducerConfig,
) -> ArcResult:
    """Solve a flow problem for a single character arc.

    Network:
        SUPER_SOURCE -> each eligible passage  (cap=1, cost=0)
        SUPER_SOURCE -> NULL                   (cap=demand, cost=0)
        each passage -> ARC_DEMAND             (cap=1, cost based on interest)
        NULL -> ARC_DEMAND                     (cap=demand, cost=null_cost)
        ARC_DEMAND -> SUPER_SINK               (cap=demand, cost=0)
    """
    # Filter passages: character present AND require_field condition met
    eligible: list[PassageRecord] = []
    for p in passages:
        # Character must be present
        if not any(
            arc.character.lower() in c.lower() for c in p.characters_present
        ):
            continue
        # require_field condition
        field_val = p.provisions.get(arc.require_field, "none")
        if arc.require_value == "not_none" and field_val == "none":
            continue
        elif arc.require_value != "not_none" and field_val != arc.require_value:
            continue
        eligible.append(p)

    if not eligible:
        return ArcResult(arc, [], arc.demand)

    # Sort by chapter order for narrative coherence
    eligible.sort(key=lambda p: p.passage_id)

    logger.debug(
        "Arc '%s': %d eligible passages, demand=%d",
        arc.name,
        len(eligible),
        arc.demand,
    )

    # -- Node assignment --
    SUPER_SOURCE = 0
    SUPER_SINK = 1
    NULL_NODE = 2
    ARC_NODE = 3
    next_id = 4

    passage_node: dict[str, int] = {}
    for p in eligible:
        passage_node[p.passage_id] = next_id
        next_id += 1

    smcf = min_cost_flow.SimpleMinCostFlow()

    # Track arcs for extraction
    arc_meta: list[tuple[str, str, int]] = []  # (type, passage_id, cost)

    # SUPER_SOURCE -> each passage (cap=1, cost=0)
    # Each passage contributes at most 1 unit to the arc
    for p in eligible:
        smcf.add_arc_with_capacity_and_unit_cost(
            SUPER_SOURCE, passage_node[p.passage_id], 1, 0
        )
        arc_meta.append(("source_to_passage", p.passage_id, 0))

    # SUPER_SOURCE -> NULL (cap=demand, cost=0)
    smcf.add_arc_with_capacity_and_unit_cost(
        SUPER_SOURCE, NULL_NODE, arc.demand, 0
    )
    arc_meta.append(("source_to_null", "", 0))

    # Passage -> ARC_NODE (cap=1, cost based on interest score)
    # Lower cost for higher interest — prefer interesting passages
    for p in eligible:
        # Interest score 0-5; invert so higher interest = lower cost
        # Base: 10 - 2*interest (score 5 -> cost 0, score 0 -> cost 10)
        interest_cost = max(0, 10 - 2 * p.interest_score)
        # Bonus for meeting the prefer_min_interest threshold
        if p.interest_score >= arc.prefer_min_interest:
            interest_cost = max(0, interest_cost - 2)
        smcf.add_arc_with_capacity_and_unit_cost(
            passage_node[p.passage_id], ARC_NODE, 1, interest_cost
        )
        arc_meta.append(("passage_to_arc", p.passage_id, interest_cost))

    # NULL -> ARC_NODE (cap=demand, cost=null_cost)
    smcf.add_arc_with_capacity_and_unit_cost(
        NULL_NODE, ARC_NODE, arc.demand, config.null_cost
    )
    arc_meta.append(("null_to_arc", "", config.null_cost))

    # ARC_NODE -> SUPER_SINK (cap=demand, cost=0)
    smcf.add_arc_with_capacity_and_unit_cost(
        ARC_NODE, SUPER_SINK, arc.demand, 0
    )
    arc_meta.append(("arc_to_sink", "", 0))

    # Supply / demand
    smcf.set_node_supply(SUPER_SOURCE, arc.demand)
    smcf.set_node_supply(SUPER_SINK, -arc.demand)

    # Solve
    status = smcf.solve()

    if status != smcf.OPTIMAL:
        logger.warning("Arc '%s': solver status %d (not optimal)", arc.name, status)
        return ArcResult(arc, [], arc.demand)

    # Extract
    assignments: list[Assignment] = []
    null_flow = 0

    for arc_idx in range(smcf.num_arcs()):
        flow = smcf.flow(arc_idx)
        if flow <= 0:
            continue
        meta_type, pid, cost = arc_meta[arc_idx]
        if meta_type == "passage_to_arc":
            assignments.append(
                Assignment(
                    passage_id=pid,
                    expert="",  # arcs are not expert-specific
                    dimension=arc.require_field,
                    cost=cost,
                    arc_name=arc.name,
                )
            )
        elif meta_type == "null_to_arc":
            null_flow += flow

    return ArcResult(arc=arc, assignments=assignments, null_flow=null_flow)


# ---------------------------------------------------------------------------
# Aggregation and deduplication
# ---------------------------------------------------------------------------


@dataclass
class AggregatedResult:
    """Full result of the transport assignment pipeline."""

    assignments: list[Assignment]
    gaps: list[GapReport]
    arc_results: list[ArcResult]
    dimension_results: list[DimensionResult]


def aggregate(
    dim_results: list[DimensionResult],
    arc_results: list[ArcResult],
) -> AggregatedResult:
    """Merge dimension and arc assignments, deduplicating by passage+expert.

    When a passage is assigned to the same expert via multiple dimensions,
    keep the assignment with the lowest cost (highest priority).
    """
    # Collect all assignments
    all_assignments: list[Assignment] = []
    for dr in dim_results:
        all_assignments.extend(dr.assignments)

    # Deduplicate by (passage_id, expert): keep lowest cost
    seen: dict[tuple[str, str], Assignment] = {}
    for a in all_assignments:
        key = (a.passage_id, a.expert)
        if key not in seen or a.cost < seen[key].cost:
            seen[key] = a

    deduped = list(seen.values())

    # Collect all gaps
    all_gaps: list[GapReport] = []
    for dr in dim_results:
        all_gaps.extend(dr.gaps)

    return AggregatedResult(
        assignments=deduped,
        gaps=all_gaps,
        arc_results=arc_results,
        dimension_results=dim_results,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def build_report(result: AggregatedResult, passages: list[PassageRecord]) -> str:
    """Generate a human-readable text report."""
    passage_map = {p.passage_id: p for p in passages}
    lines: list[str] = []

    lines.append("=" * 72)
    lines.append("PODCAST EXPERT ASSIGNMENT — TRANSPORT REPORT")
    lines.append("=" * 72)
    lines.append("")

    # -- Per-expert assignment lists --
    experts_in_assignments = sorted(
        {a.expert for a in result.assignments if a.expert}
    )
    for expert_name in experts_in_assignments:
        expert_assignments = sorted(
            [a for a in result.assignments if a.expert == expert_name],
            key=lambda a: a.passage_id,
        )
        lines.append(f"--- {expert_name} ({len(expert_assignments)} passages) ---")
        for a in expert_assignments:
            p = passage_map.get(a.passage_id)
            interest = p.interest_score if p else "?"
            chars = ", ".join(p.characters_present) if p else ""
            arc_tag = f" [arc: {a.arc_name}]" if a.arc_name else ""
            lines.append(
                f"  {a.passage_id:12s} dim={a.dimension:30s} cost={a.cost:3d} "
                f"interest={interest}{arc_tag}"
            )
            if chars:
                lines.append(f"{'':14s} characters: {chars}")
        lines.append("")

    # -- Character arc results --
    lines.append("-" * 72)
    lines.append("CHARACTER ARCS")
    lines.append("-" * 72)
    for ar in result.arc_results:
        supplied = len(ar.assignments)
        lines.append(
            f"  {ar.arc.name:30s} demand={ar.arc.demand:2d} "
            f"supplied={supplied:2d} null={ar.null_flow:2d}"
        )
        for a in sorted(ar.assignments, key=lambda x: x.passage_id):
            lines.append(f"    {a.passage_id:12s} cost={a.cost:3d}")
    lines.append("")

    # -- Gap report --
    lines.append("-" * 72)
    lines.append("GAP REPORT (NULL flows)")
    lines.append("-" * 72)
    if not result.gaps:
        lines.append("  No gaps detected — all demand satisfied.")
    else:
        for g in sorted(result.gaps, key=lambda x: (x.dimension, x.expert)):
            lines.append(
                f"  {g.dimension:30s} expert={g.expert:20s} "
                f"demand={g.demand:2d} supplied={g.supplied:2d} null={g.null_flow:2d}"
            )
    lines.append("")

    # -- Coverage map --
    lines.append("-" * 72)
    lines.append("COVERAGE MAP")
    lines.append("-" * 72)

    assigned_ids = {a.passage_id for a in result.assignments}
    assigned_passages = [passage_map[pid] for pid in assigned_ids if pid in passage_map]

    # Chapters represented
    chapters = sorted({p.chapter_id for p in assigned_passages})
    lines.append(f"  Chapters covered: {len(chapters)}")
    lines.append(f"    {', '.join(chapters)}")

    # Characters represented
    all_chars: set[str] = set()
    for p in assigned_passages:
        all_chars.update(p.characters_present)
    lines.append(f"  Characters represented: {len(all_chars)}")
    top_chars = sorted(all_chars)[:20]
    lines.append(f"    {', '.join(top_chars)}{'...' if len(all_chars) > 20 else ''}")

    lines.append("")

    # -- Budget utilization --
    lines.append("-" * 72)
    lines.append("BUDGET UTILIZATION")
    lines.append("-" * 72)

    for dr in result.dimension_results:
        if dr.total_demand > 0:
            pct = 100 * dr.total_supplied / dr.total_demand if dr.total_demand else 0
            lines.append(
                f"  {dr.dimension:30s} demand={dr.total_demand:3d} "
                f"supplied={dr.total_supplied:3d} ({pct:5.1f}%)"
            )
    lines.append("")
    lines.append(f"Total unique passages assigned: {len(assigned_ids)}")
    lines.append("")

    return "\n".join(lines)


def save_assignments_json(
    result: AggregatedResult,
    output_path: Path,
) -> None:
    """Serialize assignments to JSON."""
    data = {
        "assignments": [
            {
                "passage_id": a.passage_id,
                "expert": a.expert,
                "dimension": a.dimension,
                "cost": a.cost,
                "arc_name": a.arc_name,
            }
            for a in result.assignments
        ],
        "gaps": [
            {
                "dimension": g.dimension,
                "expert": g.expert,
                "demand": g.demand,
                "supplied": g.supplied,
                "null_flow": g.null_flow,
            }
            for g in result.gaps
        ],
        "arc_results": [
            {
                "arc_name": ar.arc.name,
                "character": ar.arc.character,
                "demand": ar.arc.demand,
                "supplied": len(ar.assignments),
                "null_flow": ar.null_flow,
                "passages": [a.passage_id for a in ar.assignments],
            }
            for ar in result.arc_results
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)
    logger.info("Saved assignments to %s", output_path)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def run_pipeline(
    experts: list[ExpertProfile] | None = None,
    arcs: list[ArcDemand] | None = None,
    config: ProducerConfig | None = None,
) -> AggregatedResult:
    """Run the full podcast assignment pipeline."""
    if experts is None:
        experts = DEFAULT_EXPERTS
    if arcs is None:
        arcs = DEFAULT_ARCS
    if config is None:
        config = ProducerConfig()

    passages = load_passages()

    # -- Solve per-dimension flow problems --
    dim_results: list[DimensionResult] = []
    for dimension in PROVISION_DIMENSIONS:
        dr = solve_dimension(dimension, passages, experts, config)
        dim_results.append(dr)
        logger.info(
            "Dimension %-30s demand=%3d supplied=%3d null=%3d",
            dimension,
            dr.total_demand,
            dr.total_supplied,
            dr.total_null_flow,
        )

    # -- Solve character arc flow problems --
    arc_results: list[ArcResult] = []
    for arc in arcs:
        ar = solve_arc(arc, passages, config)
        arc_results.append(ar)
        logger.info(
            "Arc %-30s demand=%2d supplied=%2d null=%2d",
            arc.name,
            arc.demand,
            len(ar.assignments),
            ar.null_flow,
        )

    # -- Aggregate and deduplicate --
    result = aggregate(dim_results, arc_results)
    logger.info(
        "Aggregated: %d unique assignments, %d gaps",
        len(result.assignments),
        len(result.gaps),
    )

    # -- Reports --
    tag = make_tag()
    report_text = build_report(result, passages)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"transport_podcast_{tag}.txt"
    with open(report_path, "w") as f:
        f.write(report_text)
    logger.info("Report written to %s", report_path)

    save_assignments_json(result, OUTPUT_FILE)

    return result


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    run_pipeline()


if __name__ == "__main__":
    main()
