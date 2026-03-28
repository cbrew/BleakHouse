
"""Podcast passage selection via min-cost flow.

Selects passages for podcast experts by solving one min-cost flow per
provision dimension.  Each flow has passage supply nodes (strong=2,
weak=1 units), cluster transit nodes with convex diversity penalty,
expert demand nodes, and a NULL sink that absorbs excess supply at
zero cost.  A passage is selected if it wins in any dimension for any
expert.  The same passage may be assigned to multiple experts.

Character arcs get separate flow problems to ensure key narrative
threads receive adequate coverage.

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

# Novel data override: set via BLEAKHOUSE_NOVEL env var
def _novel_data_dir() -> Path | None:
    import os
    novel = os.environ.get("BLEAKHOUSE_NOVEL")
    if novel and novel != "bleak_house":
        return DATA_DIR / "novels" / novel
    return None


def _passages_file() -> Path:
    d = _novel_data_dir()
    return d / "passages_enriched.json" if d else PASSAGES_FILE


def _clusters_literary_file() -> Path:
    d = _novel_data_dir()
    return d / "clusters_literary.json" if d else CLUSTERS_LITERARY_FILE


def _clusters_characters_file() -> Path:
    d = _novel_data_dir()
    return d / "clusters_characters.json" if d else CLUSTERS_CHARACTERS_FILE

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
    cluster_lambda: int = 5  # marginal penalty per additional passage from same cluster
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
        name="Eleanor Hartley",
        role="literary_critic",
        demands={
            "prov_narrative_technique": 12,
            "prov_character_development": 10,
            "prov_thematic_depth": 6,
        },
    ),
    ExpertProfile(
        name="James Blackstone",
        role="social_historian",
        demands={
            "prov_social_critique": 12,
            "prov_atmosphere_setting": 10,
            "prov_thematic_depth": 6,
        },
    ),
    ExpertProfile(
        name="Caroline Woodcourt",
        role="close_reader",
        demands={
            "prov_humor_entertainment": 12,
            "prov_character_development": 8,
            "prov_atmosphere_setting": 6,
        },
    ),
]

# ---------------------------------------------------------------------------
# Alternative expert profiles (swappable at transport level)
# ---------------------------------------------------------------------------

ALTERNATIVE_EXPERTS: dict[str, ExpertProfile] = {
    # Edmund Leigh — traditionalist conservative critic.
    # Values moral seriousness, individual character, the primacy of literary
    # form.  Suspicious of readings that reduce literature to politics.
    # Thinks Dickens' greatness lies in his moral imagination, not his
    # social messaging.
    "sir_edmund": ExpertProfile(
        name="Edmund Leigh",
        role="traditionalist_critic",
        demands={
            "prov_character_development": 14,
            "prov_thematic_depth": 10,
            "prov_narrative_technique": 6,
        },
    ),
    # Daniel Rosen — materialist Marxist critic.
    # Reads Bleak House as an anatomy of class power and institutional
    # violence.  Every fog is ideology, every institution is a class
    # instrument, every character is shaped by their material conditions.
    # Thinks the novel's greatness lies in its unflinching depiction of
    # systemic oppression.
    "dr_rosen": ExpertProfile(
        name="Daniel Rosen",
        role="marxist_critic",
        demands={
            "prov_social_critique": 14,
            "prov_atmosphere_setting": 10,
            "prov_character_development": 6,
        },
    ),
    # Oliver Trevelyan — performer, wit, and Dickens devotee.
    # Has narrated the complete Dickens audiobooks.  Brings a performer's
    # eye: what's funny, what's theatrical, what makes prose sing aloud.
    # Cares about the experience of reading — humor, atmosphere, the
    # music of sentences.  A wildcard who pulls the episode toward
    # entertainment and craft rather than academic analysis.
    "trevelyan": ExpertProfile(
        name="Oliver Trevelyan",
        role="performer_and_wit",
        demands={
            "prov_humor_entertainment": 14,
            "prov_atmosphere_setting": 10,
            "prov_narrative_technique": 10,
        },
    ),
    # --- American interdisciplinary panel ---
    "chen_nlp": ExpertProfile(
        name="Sarah Chen",
        role="computer_scientist",
        demands={
            "prov_narrative_technique": 12,
            "prov_character_development": 10,
            "prov_thematic_depth": 6,
        },
    ),
    "martinez_astro": ExpertProfile(
        name="Rebecca Martinez",
        role="astronomer",
        demands={
            "prov_thematic_depth": 12,
            "prov_atmosphere_setting": 10,
            "prov_character_development": 6,
        },
    ),
    "volkov_music": ExpertProfile(
        name="Elena Volkov",
        role="musicologist",
        demands={
            "prov_social_critique": 12,
            "prov_thematic_depth": 10,
            "prov_atmosphere_setting": 6,
        },
    ),
}


_BLEAK_HOUSE_ARCS = [
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


def _get_default_arcs() -> list[ArcDemand]:
    """Return novel-appropriate arcs based on BLEAKHOUSE_NOVEL env var."""
    from enrichment.novel_prompts import get_novel_arcs  # pyright: ignore[reportMissingImports]
    novel_arcs = get_novel_arcs()
    if not novel_arcs:
        return list(_BLEAK_HOUSE_ARCS)
    return [
        ArcDemand(name, character, demand, req_field, req_value, min_interest)
        for name, character, demand, req_field, req_value, min_interest in novel_arcs
    ]


DEFAULT_ARCS = _get_default_arcs()

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
    pf = _passages_file()
    logger.info("Loading passages from %s", pf)
    with open(pf) as f:
        raw_passages: list[dict] = json.load(f)  # type: ignore[type-arg]

    # Load cluster assignments (passage_id -> cluster_id)
    clusters_lit: dict[str, int] = {}
    clusters_char: dict[str, int] = {}
    clf = _clusters_literary_file()
    ccf = _clusters_characters_file()
    if not clf.exists():
        raise FileNotFoundError(
            f"Literary cluster file not found: {clf}. "
            f"Run: uv run python -m enrichment.cluster_literary"
        )
    if not ccf.exists():
        raise FileNotFoundError(
            f"Character cluster file not found: {ccf}. "
            f"Run: uv run python -m enrichment.cluster_characters"
        )
    with open(clf) as f:
        clusters_lit = json.load(f)
    with open(ccf) as f:
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
    optimal_cost: int = 0
    total_supply: int = 0
    num_eligible: int = 0
    num_clusters: int = 0
    strong_count: int = 0
    weak_count: int = 0
    solver_status: str = "NOT_RUN"


def solve_dimension(
    dimension: str,
    passages: list[PassageRecord],
    experts: list[ExpertProfile],
    config: ProducerConfig,
) -> DimensionResult:
    """Build and solve the min-cost flow network for one provision dimension.

    Each eligible passage is a supply node (strong=2, weak=1 units).
    Each demanding expert is a demand node.  A NULL sink absorbs all
    supply that the solver does not route to experts.

    Costs on passage→cluster arcs encode provision strength and interest
    score, so the solver prefers strong, interesting passages.  Cluster→expert
    arcs use parallel capacity-1 arcs with costs 0, λ, 2λ, … to create a
    convex diversity penalty discouraging multiple passages from the same
    chapter cluster.

    Network structure:
        passage nodes (supply=strength)
            → cluster nodes (transit)
                → expert nodes (demand=expert_demand)
            → NULL_SINK (demand=total_supply − total_demand)
    """
    # Identify demanding experts for this dimension
    demanding_experts = [
        (exp, exp.demands.get(dimension, 0))
        for exp in experts
        if exp.demands.get(dimension, 0) > 0
    ]
    if not demanding_experts:
        return DimensionResult(dimension, [], [], 0, 0, 0,
                               solver_status="SKIPPED_NO_DEMAND")

    total_demand = sum(d for _, d in demanding_experts)

    # Identify eligible passages: those with provision != "none"
    # Deduplicate by passage_id (rare duplicates cause supply imbalance)
    seen_ids: set[str] = set()
    eligible: list[PassageRecord] = []
    for p in passages:
        if p.provisions.get(dimension, "none") != "none" and p.passage_id not in seen_ids:
            eligible.append(p)
            seen_ids.add(p.passage_id)
    if not eligible:
        gaps = [
            GapReport(dimension, exp.name, d, 0, d)
            for exp, d in demanding_experts
        ]
        return DimensionResult(dimension, [], gaps, total_demand, 0, total_demand,
                               solver_status="SKIPPED_NO_ELIGIBLE")

    # Group eligible passages by literary cluster
    cluster_members: dict[int, list[PassageRecord]] = {}
    for p in eligible:
        cluster_members.setdefault(p.literary_cluster, []).append(p)

    # Compute total passage supply
    total_supply = sum(
        STRENGTH_TO_SUPPLY[p.provisions[dimension]] for p in eligible
    )

    # The NULL sink absorbs all supply not routed to experts.
    # If supply < demand, the problem is infeasible (experts can't all
    # be satisfied); we report the gap but null_sink gets 0.
    if total_supply >= total_demand:
        null_sink_demand = total_supply - total_demand
    else:
        # Not enough passages — solver will fail.  Caller should ensure
        # demands are reasonable relative to corpus size.
        raise RuntimeError(
            f"Dimension {dimension}: insufficient supply ({total_supply}) "
            f"for demand ({total_demand}).  Reduce expert demands or enrich "
            f"more passages."
        )

    logger.debug(
        "Dimension %s: %d eligible passages in %d clusters, "
        "total_supply=%d, total_demand=%d, null_sink=%d",
        dimension,
        len(eligible),
        len(cluster_members),
        total_supply,
        total_demand,
        null_sink_demand,
    )

    # -- Node assignment --
    NULL_SINK = 0
    next_id = 1

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

    # Passage -> Cluster (capacity = supply, cost = provision + interest)
    for cid, members in cluster_members.items():
        for p in members:
            strength = p.provisions[dimension]
            base_cost = config.strong_cost if strength == "strong" else config.weak_cost
            # Interest bonus: score 5→0, score 0→5 (prefer interesting passages)
            interest_penalty = max(0, 5 - p.interest_score)
            supply = STRENGTH_TO_SUPPLY[strength]
            add_arc(
                passage_node[p.passage_id], cluster_node[cid], supply,
                base_cost + interest_penalty,
                "passage", p.passage_id, "cluster", str(cid),
            )

    # Passage -> NULL_SINK (capacity = supply, cost = interest_score)
    # Discarding interesting passages is expensive; the solver prefers
    # to route high-interest passages to experts rather than waste them.
    for p in eligible:
        supply = STRENGTH_TO_SUPPLY[p.provisions[dimension]]
        discard_cost = p.interest_score  # 5-star → costs 5, 0-star → free
        add_arc(
            passage_node[p.passage_id], NULL_SINK, supply, discard_cost,
            "passage", p.passage_id, "null_sink", "NULL_SINK",
        )

    # Cluster -> Expert (parallel arcs with convex penalty)
    cluster_supply: dict[int, int] = {}
    for cid, members in cluster_members.items():
        cluster_supply[cid] = sum(
            STRENGTH_TO_SUPPLY[p.provisions[dimension]] for p in members
        )

    lam = config.cluster_lambda
    for cid in cluster_members:
        k = cluster_supply[cid]
        for exp, _ in demanding_experts:
            for slot in range(k):
                add_arc(
                    cluster_node[cid], expert_node[exp.name],
                    1, slot * lam,
                    "cluster", str(cid), "expert", exp.name,
                )

    # -- Set supply on passage nodes (positive = produces flow) --
    for p in eligible:
        supply = STRENGTH_TO_SUPPLY[p.provisions[dimension]]
        smcf.set_node_supply(passage_node[p.passage_id], supply)

    # -- Set demand on expert nodes (negative = consumes flow) --
    for exp, demand in demanding_experts:
        smcf.set_node_supply(expert_node[exp.name], -demand)

    # -- Set demand on NULL sink (absorbs excess supply) --
    smcf.set_node_supply(NULL_SINK, -null_sink_demand)

    # Verify balance: passage supply = expert demand + null sink demand
    balance = total_supply - total_demand - null_sink_demand
    assert balance == 0, (
        f"Supply/demand imbalance: supply={total_supply}, "
        f"demand={total_demand}, null_sink={null_sink_demand}, "
        f"balance={balance}"
    )

    # -- Solve --
    status = smcf.solve()

    if status != smcf.OPTIMAL:
        raise RuntimeError(
            f"Dimension {dimension}: solver returned {status} (expected OPTIMAL). "
            f"total_supply={total_supply}, total_demand={total_demand}, "
            f"null_sink={null_sink_demand}, eligible={len(eligible)}, "
            f"clusters={len(cluster_members)}, "
            f"experts={[e.name for e, _ in demanding_experts]}"
        )

    logger.debug(
        "Dimension %s: optimal cost = %d", dimension, smcf.optimal_cost()
    )

    # -- Extract assignments and null flows --
    cluster_passage_flow: dict[int, list[tuple[str, int, int]]] = {}
    cluster_expert_flow: dict[tuple[int, str], int] = {}
    cluster_expert_penalty: dict[tuple[int, str], int] = {}
    null_flow_total = 0

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
            key = (cid, head_id)
            cluster_expert_flow[key] = cluster_expert_flow.get(key, 0) + flow
            cluster_expert_penalty[key] = cluster_expert_penalty.get(key, 0) + unit_cost
        elif tail_type == "passage" and head_type == "null_sink":
            null_flow_total += flow

    # Attribute passage→expert assignments through clusters
    assignments: list[Assignment] = []
    for (cid, expert_name), expert_flow in cluster_expert_flow.items():
        total_penalty = cluster_expert_penalty.get((cid, expert_name), 0)
        avg_penalty = total_penalty // max(expert_flow, 1)
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
                        cost=p_cost + avg_penalty,
                    )
                )
            remaining -= assigned

    # No gaps possible: we raise if supply < demand above
    gaps: list[GapReport] = []
    total_supplied = total_demand

    logger.debug(
        "Dimension %s: %d passages selected, %d discarded to null sink",
        dimension, len(assignments), null_flow_total,
    )

    strong_count = sum(1 for p in eligible if p.provisions[dimension] == "strong")
    weak_count = len(eligible) - strong_count

    return DimensionResult(
        dimension=dimension,
        assignments=assignments,
        gaps=gaps,
        total_demand=total_demand,
        total_supplied=total_supplied,
        total_null_flow=null_flow_total,
        optimal_cost=smcf.optimal_cost(),
        total_supply=total_supply,
        num_eligible=len(eligible),
        num_clusters=len(cluster_members),
        strong_count=strong_count,
        weak_count=weak_count,
        solver_status="OPTIMAL",
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
        raise RuntimeError(
            f"Arc '{arc.name}': solver returned {status} (expected OPTIMAL). "
            f"demand={arc.demand}, eligible_passages={len(eligible)}, "
            f"character='{arc.character}'"
        )

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

    # -- Solver diagnostics per dimension --
    lines.append("-" * 72)
    lines.append("SOLVER DIAGNOSTICS (per dimension)")
    lines.append("-" * 72)
    lines.append(
        f"  {'dimension':30s} {'status':8s} {'demand':>6s} {'supply':>6s} "
        f"{'null':>5s} {'cost':>6s} {'elig':>5s} {'clust':>5s} "
        f"{'strong':>6s} {'weak':>6s}"
    )
    lines.append("  " + "-" * 100)

    total_optimal_cost = 0
    for dr in result.dimension_results:
        total_optimal_cost += dr.optimal_cost
        if dr.total_demand > 0 or dr.solver_status != "NOT_RUN":
            lines.append(
                f"  {dr.dimension:30s} {dr.solver_status:8s} "
                f"{dr.total_demand:6d} {dr.total_supply:6d} "
                f"{dr.total_null_flow:5d} {dr.optimal_cost:6d} "
                f"{dr.num_eligible:5d} {dr.num_clusters:5d} "
                f"{dr.strong_count:6d} {dr.weak_count:6d}"
            )
    lines.append("")

    # -- Summary --
    lines.append("-" * 72)
    lines.append("SUMMARY")
    lines.append("-" * 72)
    lines.append(f"  Total unique passages assigned: {len(assigned_ids)}")
    lines.append(f"  Total dimension optimal cost:   {total_optimal_cost}")
    total_dim_demand = sum(dr.total_demand for dr in result.dimension_results)
    total_dim_supplied = sum(dr.total_supplied for dr in result.dimension_results)
    lines.append(f"  Total dimension demand:         {total_dim_demand}")
    lines.append(f"  Total dimension supplied:       {total_dim_supplied}")
    all_statuses = {dr.solver_status for dr in result.dimension_results
                    if dr.solver_status not in ("NOT_RUN", "SKIPPED_NO_DEMAND")}
    lines.append(f"  Solver statuses:                {', '.join(sorted(all_statuses)) or 'none'}")

    # Per-expert passage counts
    expert_counts: dict[str, int] = {}
    for a in result.assignments:
        if a.expert:
            expert_counts[a.expert] = expert_counts.get(a.expert, 0) + 1
    for name in sorted(expert_counts):
        lines.append(f"  {name:30s} {expert_counts[name]:3d} assignments")
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


STRUCTURE_EXPERT_NAME = "_episode_structure"


def run_pipeline(
    experts: list[ExpertProfile] | None = None,
    arcs: list[ArcDemand] | None = None,
    config: ProducerConfig | None = None,
    supplementary_demand: dict[str, int] | None = None,
) -> AggregatedResult:
    """Run the full podcast assignment pipeline.

    Args:
        supplementary_demand: Extra dimension demand from segment design
            (Phase 0).  For each dimension with a positive value, a synthetic
            expert is added to ensure Phase 1 selects enough passages.
            Passages assigned to the synthetic expert are available in Phase 2
            for any segment.
    """
    if experts is None:
        experts = DEFAULT_EXPERTS
    if arcs is None:
        arcs = DEFAULT_ARCS
    if config is None:
        config = ProducerConfig()

    passages = load_passages()

    # Build augmented expert list with supplementary demand from segment design
    augmented_experts = list(experts)
    if supplementary_demand:
        structure_demands = {
            dim: boost
            for dim, boost in supplementary_demand.items()
            if boost > 0
        }
        if structure_demands:
            augmented_experts.append(
                ExpertProfile(
                    name=STRUCTURE_EXPERT_NAME,
                    role="episode_structure",
                    demands=structure_demands,
                )
            )
            logger.info(
                "Added episode structure demand: %s",
                structure_demands,
            )

    # -- Solve per-dimension flow problems --
    dim_results: list[DimensionResult] = []
    for dimension in PROVISION_DIMENSIONS:
        dr = solve_dimension(dimension, passages, augmented_experts, config)
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
