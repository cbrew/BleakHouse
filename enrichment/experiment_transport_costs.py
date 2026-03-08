"""Experiment 7: Transport Assignments — Embeddings vs. Metadata Costs.

Compares two cost functions for the podcast expert transport assignment:
  (a) Metadata costs (baseline): enrichment-derived provision strengths.
  (b) Embedding costs: cosine similarity between passage vectors and
      embedded expert profile descriptions.

Measures overlap, divergence, and enrichment profile differences between
the two assignment sets.

Usage:
    uv run python -m enrichment.experiment_transport_costs
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import lancedb  # pyright: ignore[reportMissingImports]
import numpy as np
from dotenv import load_dotenv
from openai import OpenAI
from ortools.graph.python import min_cost_flow  # pyright: ignore[reportMissingImports]

from enrichment.transport_podcast import (  # pyright: ignore[reportMissingImports]
    DEFAULT_ARCS,
    DEFAULT_EXPERTS,
    PROVISION_DIMENSIONS,
    STRENGTH_TO_SUPPLY,
    AggregatedResult,
    Assignment,
    DimensionResult,
    ExpertProfile,
    GapReport,
    PassageRecord,
    ProducerConfig,
    aggregate,
    load_passages,
    run_pipeline,
    solve_arc,
)

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"
DB_PATH = DATA_DIR / "bleak_house_vectors"
OUTPUT_PATH = DATA_DIR / "experiment_transport_costs.json"

EMBEDDING_MODEL = "text-embedding-3-small"


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
# Expert profile embedding
# ---------------------------------------------------------------------------


def expert_to_text(expert: ExpertProfile) -> str:
    """Convert an expert profile to natural-language text for embedding."""
    parts = [f"{expert.name}, {expert.role}."]
    for dim, level in expert.demands.items():
        if level > 0:
            short = dim.replace("prov_", "").replace("_", " ")
            strength = "strong" if level >= 2 else "moderate"
            parts.append(f"Interested in {strength} {short}.")
    return " ".join(parts)


def embed_expert_profiles(
    experts: list[ExpertProfile],
) -> dict[str, np.ndarray]:
    """Embed expert profile texts using OpenAI embeddings API.

    Returns a dict mapping expert name to its embedding vector.
    """
    client = OpenAI()
    texts = [expert_to_text(exp) for exp in experts]
    logger.info("Embedding %d expert profiles via OpenAI", len(texts))
    for exp, txt in zip(experts, texts):
        logger.debug("  %s: %s", exp.name, txt)

    response = client.embeddings.create(input=texts, model=EMBEDDING_MODEL)
    result: dict[str, np.ndarray] = {}
    for exp, item in zip(experts, response.data):
        result[exp.name] = np.array(item.embedding, dtype=np.float32)
    return result


def load_passage_vectors() -> dict[str, np.ndarray]:
    """Load passage vectors from LanceDB.

    Returns a dict mapping passage_id to its embedding vector.
    """
    logger.info("Loading passage vectors from %s", DB_PATH)
    db = lancedb.connect(str(DB_PATH))
    table = db.open_table("passages")
    df = table.to_pandas()
    vectors: dict[str, np.ndarray] = {}
    for _, row in df.iterrows():
        pid = str(row["passage_id"])
        vec = np.array(row["vector"], dtype=np.float32)
        vectors[pid] = vec
    logger.info("Loaded %d passage vectors", len(vectors))
    return vectors


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    dot = float(np.dot(a, b))
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def compute_embedding_costs(
    passages: list[PassageRecord],
    experts: list[ExpertProfile],
    passage_vectors: dict[str, np.ndarray],
    expert_vectors: dict[str, np.ndarray],
) -> dict[tuple[str, str], int]:
    """Compute quantized embedding-based costs for each (passage, expert) pair.

    Cost = quantized (1 - cosine_similarity) scaled to integer range 1-10.
    """
    costs: dict[tuple[str, str], int] = {}
    for p in passages:
        pvec = passage_vectors.get(p.passage_id)
        if pvec is None:
            continue
        for exp in experts:
            evec = expert_vectors.get(exp.name)
            if evec is None:
                continue
            sim = cosine_similarity(pvec, evec)
            # Scale (1 - sim) to integer range 1-10
            # sim ranges roughly 0..1; distance = 1-sim ranges 0..1
            raw_cost = 1.0 - sim
            quantized = int(round(raw_cost * 9.0)) + 1  # maps 0->1, 1->10
            quantized = max(1, min(10, quantized))
            costs[(p.passage_id, exp.name)] = quantized
    return costs


# ---------------------------------------------------------------------------
# Embedding-cost dimension solver
# ---------------------------------------------------------------------------


def solve_dimension_embedding(
    dimension: str,
    passages: list[PassageRecord],
    experts: list[ExpertProfile],
    config: ProducerConfig,
    embedding_costs: dict[tuple[str, str], int],
) -> DimensionResult:
    """Solve a per-dimension flow problem using embedding-derived costs.

    Same network topology as solve_dimension but replaces provision-based
    arc costs with embedding similarity costs.  Passage eligibility still
    requires provision != "none" so the network structure is identical.
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
        "Dimension %s (embedding): %d eligible passages in %d clusters, "
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

    arc_meta: list[tuple[str, str, str, str, int]] = []

    def add_arc(
        tail: int,
        head: int,
        capacity: int,
        unit_cost: int,
        tail_type: str,
        tail_id: str,
        head_type: str,
        head_id: str,
    ) -> None:
        smcf.add_arc_with_capacity_and_unit_cost(tail, head, capacity, unit_cost)
        arc_meta.append((tail_type, tail_id, head_type, head_id, unit_cost))

    # SUPER_SOURCE -> each passage (capacity = supply from provision, cost = 0)
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

    # Passage -> Cluster: use embedding cost instead of provision-based cost
    # For each passage in a cluster, the cost comes from the minimum embedding
    # cost across demanding experts (since at cluster->expert level we pick the
    # specific expert).  We use a uniform per-passage cost here: average
    # embedding cost across demanding experts for this passage.
    for cid, members in cluster_members.items():
        for p in members:
            supply = STRENGTH_TO_SUPPLY[p.provisions[dimension]]
            # Use mean embedding cost across demanding experts as the arc cost
            expert_costs = [
                embedding_costs.get((p.passage_id, exp.name), 10)
                for exp, _ in demanding_experts
            ]
            base_cost = int(round(sum(expert_costs) / len(expert_costs)))
            base_cost = max(1, min(10, base_cost))
            add_arc(
                passage_node[p.passage_id], cluster_node[cid], supply, base_cost,
                "passage", p.passage_id, "cluster", str(cid),
            )

    # Cluster -> Expert (capacity = cluster_capacity, cost = cluster_penalty)
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
            "Dimension %s (embedding): solver status %d (not optimal)",
            dimension, status,
        )
        gaps = [
            GapReport(dimension, exp.name, d, 0, d)
            for exp, d in demanding_experts
        ]
        return DimensionResult(dimension, [], gaps, total_demand, 0, total_demand)

    logger.debug(
        "Dimension %s (embedding): optimal cost = %d",
        dimension, smcf.optimal_cost(),
    )

    # -- Extract assignments and null flows --
    cluster_passage_flow: dict[int, list[tuple[str, int, int]]] = {}
    cluster_expert_flow: dict[tuple[int, str], int] = {}
    null_flows_by_expert: dict[str, int] = {exp.name: 0 for exp, _ in demanding_experts}

    for arc_idx in range(smcf.num_arcs()):
        flow = smcf.flow(arc_idx)
        if flow <= 0:
            continue
        tail_type, tail_id, head_type, head_id, unit_cost = arc_meta[arc_idx]

        if tail_type == "passage" and head_type == "cluster":
            cid = int(head_id)
            cluster_passage_flow.setdefault(cid, []).append(
                (tail_id, flow, unit_cost)
            )
        elif tail_type == "cluster" and head_type == "expert":
            cid = int(tail_id)
            cluster_expert_flow[(cid, head_id)] = flow
        elif tail_type == "null" and head_type == "expert":
            null_flows_by_expert[head_id] += flow

    # Attribute passage->expert assignments through clusters
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
# Variant (b): embedding-cost pipeline
# ---------------------------------------------------------------------------


def run_pipeline_embedding(
    experts: list[ExpertProfile] | None = None,
    config: ProducerConfig | None = None,
) -> AggregatedResult:
    """Run the transport pipeline with embedding-derived costs."""
    resolved_experts = experts if experts is not None else DEFAULT_EXPERTS
    resolved_config = config if config is not None else ProducerConfig()

    passages = load_passages()

    # Load vectors
    passage_vectors = load_passage_vectors()
    expert_vectors = embed_expert_profiles(resolved_experts)

    # Compute embedding costs for all (passage, expert) pairs
    embedding_costs = compute_embedding_costs(
        passages, resolved_experts, passage_vectors, expert_vectors,
    )
    logger.info(
        "Computed %d embedding costs (mean=%.2f)",
        len(embedding_costs),
        float(np.mean(list(embedding_costs.values()))) if embedding_costs else 0.0,
    )

    # Solve per-dimension flow problems with embedding costs
    dim_results: list[DimensionResult] = []
    for dimension in PROVISION_DIMENSIONS:
        dr = solve_dimension_embedding(
            dimension, passages, resolved_experts, resolved_config, embedding_costs,
        )
        dim_results.append(dr)
        logger.info(
            "Dimension %-30s (embedding) demand=%3d supplied=%3d null=%3d",
            dimension, dr.total_demand, dr.total_supplied, dr.total_null_flow,
        )

    # Character arcs use the same solver (not embedding-based)
    arc_results = []
    for arc_demand in DEFAULT_ARCS:
        ar = solve_arc(arc_demand, passages, resolved_config)
        arc_results.append(ar)

    result = aggregate(dim_results, arc_results)
    logger.info(
        "Embedding pipeline: %d unique assignments, %d gaps",
        len(result.assignments), len(result.gaps),
    )
    return result


# ---------------------------------------------------------------------------
# Comparison analysis
# ---------------------------------------------------------------------------


@dataclass
class ComparisonResult:
    """Comparison between metadata-cost and embedding-cost assignments."""

    overlap_count: int
    overlap_fraction: float
    metadata_only_count: int
    embedding_only_count: int
    total_metadata: int
    total_embedding: int
    # Enrichment profile stats for each group
    metadata_only_profiles: dict[str, object]
    embedding_only_profiles: dict[str, object]
    overlap_profiles: dict[str, object]
    # Distribution comparisons
    metadata_interest_mean: float
    embedding_interest_mean: float
    metadata_narrator_counts: dict[str, int]
    embedding_narrator_counts: dict[str, int]
    metadata_provision_strengths: dict[str, dict[str, int]]
    embedding_provision_strengths: dict[str, dict[str, int]]
    # For divergent passages: which variant has stronger profiles?
    divergent_metadata_stronger: int
    divergent_embedding_stronger: int
    divergent_tied: int


def _passage_strength_score(p: PassageRecord) -> int:
    """Sum of provision strengths for a passage (strong=2, weak=1, none=0)."""
    total = 0
    for dim in PROVISION_DIMENSIONS:
        val = p.provisions.get(dim, "none")
        total += STRENGTH_TO_SUPPLY.get(val, 0)
    return total


def _provision_strength_distribution(
    passage_ids: set[str],
    passage_map: dict[str, PassageRecord],
) -> dict[str, dict[str, int]]:
    """Count provision strength values across passages for each dimension."""
    dist: dict[str, dict[str, int]] = {}
    for dim in PROVISION_DIMENSIONS:
        counts: dict[str, int] = Counter()
        for pid in passage_ids:
            p = passage_map.get(pid)
            if p:
                counts[p.provisions.get(dim, "none")] += 1
        dist[dim] = dict(counts)
    return dist


def _narrator_distribution(
    assignments: list[Assignment],
    enriched_path: Path,
) -> dict[str, int]:
    """Count narrator values for assigned passages."""
    # Load enriched data for narrator info
    if not enriched_path.exists():
        return {}
    with open(enriched_path) as f:
        raw = json.load(f)
    narrator_map: dict[str, str] = {}
    for p in raw:
        enr = p.get("enrichment")
        if enr:
            narrator_map[p["passage_id"]] = enr.get("narrator", "unknown")
    counts: dict[str, int] = Counter()
    assigned_ids = {a.passage_id for a in assignments}
    for pid in assigned_ids:
        counts[narrator_map.get(pid, "unknown")] += 1
    return dict(counts)


def _mean_interest(
    passage_ids: set[str],
    passage_map: dict[str, PassageRecord],
) -> float:
    """Mean interest score for a set of passages."""
    scores = [
        passage_map[pid].interest_score
        for pid in passage_ids
        if pid in passage_map
    ]
    return float(np.mean(scores)) if scores else 0.0


def _enrichment_profile_summary(
    passage_ids: set[str],
    passage_map: dict[str, PassageRecord],
) -> dict[str, object]:
    """Summarize enrichment profiles for a set of passages."""
    if not passage_ids:
        return {"count": 0}
    scores = [
        passage_map[pid].interest_score
        for pid in passage_ids
        if pid in passage_map
    ]
    strengths = [
        _passage_strength_score(passage_map[pid])
        for pid in passage_ids
        if pid in passage_map
    ]
    return {
        "count": len(passage_ids),
        "mean_interest": float(np.mean(scores)) if scores else 0.0,
        "mean_strength": float(np.mean(strengths)) if strengths else 0.0,
        "median_interest": float(np.median(scores)) if scores else 0.0,
        "median_strength": float(np.median(strengths)) if strengths else 0.0,
    }


def compare_assignments(
    metadata_result: AggregatedResult,
    embedding_result: AggregatedResult,
    passages: list[PassageRecord],
) -> ComparisonResult:
    """Compare metadata-cost vs embedding-cost assignment sets."""
    passage_map = {p.passage_id: p for p in passages}
    enriched_path = DATA_DIR / "passages_enriched.json"

    # Build sets of (passage_id, expert) pairs
    meta_pairs = {
        (a.passage_id, a.expert)
        for a in metadata_result.assignments
        if a.expert
    }
    emb_pairs = {
        (a.passage_id, a.expert)
        for a in embedding_result.assignments
        if a.expert
    }

    overlap = meta_pairs & emb_pairs
    meta_only = meta_pairs - emb_pairs
    emb_only = emb_pairs - meta_pairs

    total_union = len(meta_pairs | emb_pairs)
    overlap_fraction = len(overlap) / total_union if total_union > 0 else 0.0

    # Passage IDs in each group
    meta_only_pids = {pid for pid, _ in meta_only}
    emb_only_pids = {pid for pid, _ in emb_only}
    overlap_pids = {pid for pid, _ in overlap}

    # Enrichment profile summaries
    meta_only_profiles = _enrichment_profile_summary(meta_only_pids, passage_map)
    emb_only_profiles = _enrichment_profile_summary(emb_only_pids, passage_map)
    overlap_profiles = _enrichment_profile_summary(overlap_pids, passage_map)

    # Interest score means
    meta_all_pids = {a.passage_id for a in metadata_result.assignments}
    emb_all_pids = {a.passage_id for a in embedding_result.assignments}
    meta_interest = _mean_interest(meta_all_pids, passage_map)
    emb_interest = _mean_interest(emb_all_pids, passage_map)

    # Narrator distributions
    meta_narrators = _narrator_distribution(
        metadata_result.assignments, enriched_path,
    )
    emb_narrators = _narrator_distribution(
        embedding_result.assignments, enriched_path,
    )

    # Provision strength distributions
    meta_prov = _provision_strength_distribution(meta_all_pids, passage_map)
    emb_prov = _provision_strength_distribution(emb_all_pids, passage_map)

    # For divergent passages: compare strength scores
    divergent_meta_stronger = 0
    divergent_emb_stronger = 0
    divergent_tied = 0

    # Passages that appear in one set but not the other
    divergent_pids = (meta_only_pids | emb_only_pids) - (meta_only_pids & emb_only_pids)
    for pid in divergent_pids:
        if pid not in passage_map:
            continue
        in_meta = pid in meta_only_pids
        in_emb = pid in emb_only_pids
        if in_meta and not in_emb:
            # This passage only in metadata variant
            divergent_meta_stronger += 1
        elif in_emb and not in_meta:
            divergent_emb_stronger += 1
        else:
            divergent_tied += 1

    # For passages in both but assigned to different experts, compare strengths
    # These are passages in meta_only and emb_only that share the same passage_id
    shared_divergent = meta_only_pids & emb_only_pids
    meta_shared_strength = 0.0
    emb_shared_strength = 0.0
    shared_count = 0
    for pid in shared_divergent:
        p = passage_map.get(pid)
        if p:
            shared_count += 1
            meta_shared_strength += _passage_strength_score(p)
            emb_shared_strength += _passage_strength_score(p)
    # The strength is the same since it is the same passage; what differs is
    # assignment.  Report the count for context.

    return ComparisonResult(
        overlap_count=len(overlap),
        overlap_fraction=overlap_fraction,
        metadata_only_count=len(meta_only),
        embedding_only_count=len(emb_only),
        total_metadata=len(meta_pairs),
        total_embedding=len(emb_pairs),
        metadata_only_profiles=meta_only_profiles,
        embedding_only_profiles=emb_only_profiles,
        overlap_profiles=overlap_profiles,
        metadata_interest_mean=meta_interest,
        embedding_interest_mean=emb_interest,
        metadata_narrator_counts=meta_narrators,
        embedding_narrator_counts=emb_narrators,
        metadata_provision_strengths=meta_prov,
        embedding_provision_strengths=emb_prov,
        divergent_metadata_stronger=divergent_meta_stronger,
        divergent_embedding_stronger=divergent_emb_stronger,
        divergent_tied=divergent_tied,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def build_report(comparison: ComparisonResult) -> str:
    """Generate a human-readable text report of the comparison."""
    lines: list[str] = []

    lines.append("=" * 72)
    lines.append("EXPERIMENT 7: TRANSPORT COSTS — EMBEDDINGS vs. METADATA")
    lines.append("=" * 72)
    lines.append("")

    # -- Overview --
    lines.append("-" * 72)
    lines.append("OVERVIEW")
    lines.append("-" * 72)
    lines.append(f"  Metadata-cost assignments:  {comparison.total_metadata}")
    lines.append(f"  Embedding-cost assignments: {comparison.total_embedding}")
    lines.append(f"  Overlap (passage, expert):  {comparison.overlap_count}")
    lines.append(f"  Overlap fraction:           {comparison.overlap_fraction:.3f}")
    lines.append(f"  Metadata-only pairs:        {comparison.metadata_only_count}")
    lines.append(f"  Embedding-only pairs:       {comparison.embedding_only_count}")
    lines.append("")

    # -- Interest scores --
    lines.append("-" * 72)
    lines.append("MEAN INTEREST SCORES")
    lines.append("-" * 72)
    lines.append(f"  Metadata variant: {comparison.metadata_interest_mean:.2f}")
    lines.append(f"  Embedding variant: {comparison.embedding_interest_mean:.2f}")
    lines.append("")

    # -- Narrator balance --
    lines.append("-" * 72)
    lines.append("NARRATOR DISTRIBUTION")
    lines.append("-" * 72)
    lines.append("  Metadata variant:")
    for narrator, count in sorted(
        comparison.metadata_narrator_counts.items(), key=lambda x: -x[1]
    ):
        lines.append(f"    {narrator:20s} {count:4d}")
    lines.append("  Embedding variant:")
    for narrator, count in sorted(
        comparison.embedding_narrator_counts.items(), key=lambda x: -x[1]
    ):
        lines.append(f"    {narrator:20s} {count:4d}")
    lines.append("")

    # -- Enrichment profiles of divergent passages --
    lines.append("-" * 72)
    lines.append("ENRICHMENT PROFILES OF DIVERGENT PASSAGES")
    lines.append("-" * 72)
    lines.append("  Metadata-only passages:")
    for k, v in comparison.metadata_only_profiles.items():
        lines.append(f"    {k}: {v}")
    lines.append("  Embedding-only passages:")
    for k, v in comparison.embedding_only_profiles.items():
        lines.append(f"    {k}: {v}")
    lines.append("  Overlap passages:")
    for k, v in comparison.overlap_profiles.items():
        lines.append(f"    {k}: {v}")
    lines.append("")

    # -- Divergence direction --
    lines.append("-" * 72)
    lines.append("DIVERGENT PASSAGE DIRECTION")
    lines.append("-" * 72)
    lines.append(
        f"  Passages only in metadata variant:  {comparison.divergent_metadata_stronger}"
    )
    lines.append(
        f"  Passages only in embedding variant: {comparison.divergent_embedding_stronger}"
    )
    lines.append(
        f"  Passages in both (reassigned):      {comparison.divergent_tied}"
    )
    lines.append("")

    # -- Provision strength distributions --
    lines.append("-" * 72)
    lines.append("PROVISION STRENGTH DISTRIBUTIONS")
    lines.append("-" * 72)
    for dim in PROVISION_DIMENSIONS:
        meta_dist = comparison.metadata_provision_strengths.get(dim, {})
        emb_dist = comparison.embedding_provision_strengths.get(dim, {})
        lines.append(f"  {dim}:")
        lines.append(f"    metadata: {meta_dist}")
        lines.append(f"    embedding: {emb_dist}")
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

    tag = make_tag()
    logger.info("Experiment 7: transport costs comparison (tag=%s)", tag)

    # -- Variant (a): metadata costs (baseline) --
    logger.info("Running variant (a): metadata costs")
    metadata_result = run_pipeline()

    # -- Variant (b): embedding costs --
    logger.info("Running variant (b): embedding costs")
    embedding_result = run_pipeline_embedding()

    # -- Load passages for comparison --
    passages = load_passages()

    # -- Compare --
    logger.info("Comparing assignment sets")
    comparison = compare_assignments(metadata_result, embedding_result, passages)

    # -- Report --
    report_text = build_report(comparison)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"transport_costs_{tag}.txt"
    with open(report_path, "w") as f:
        f.write(report_text)
    logger.info("Report written to %s", report_path)

    # -- Save JSON --
    output_data = {
        "tag": tag,
        "overlap_count": comparison.overlap_count,
        "overlap_fraction": comparison.overlap_fraction,
        "metadata_only_count": comparison.metadata_only_count,
        "embedding_only_count": comparison.embedding_only_count,
        "total_metadata": comparison.total_metadata,
        "total_embedding": comparison.total_embedding,
        "metadata_interest_mean": comparison.metadata_interest_mean,
        "embedding_interest_mean": comparison.embedding_interest_mean,
        "metadata_narrator_counts": comparison.metadata_narrator_counts,
        "embedding_narrator_counts": comparison.embedding_narrator_counts,
        "metadata_only_profiles": comparison.metadata_only_profiles,
        "embedding_only_profiles": comparison.embedding_only_profiles,
        "overlap_profiles": comparison.overlap_profiles,
        "metadata_provision_strengths": comparison.metadata_provision_strengths,
        "embedding_provision_strengths": comparison.embedding_provision_strengths,
        "divergent_metadata_stronger": comparison.divergent_metadata_stronger,
        "divergent_embedding_stronger": comparison.divergent_embedding_stronger,
        "divergent_tied": comparison.divergent_tied,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output_data, f, indent=2)
    logger.info("Saved results to %s", OUTPUT_PATH)

    # Print report to stdout
    print(report_text)


if __name__ == "__main__":
    main()
