"""Experiment 8: The Redundancy Question.

Tests whether transport-redundancy corresponds to embedding-redundancy,
enrichment-redundancy, or a distinct notion constructed from the interaction
of supply, demand, and cost structure.

Variants:
  (a) no_penalty    — cluster_capacity=999, cluster_penalty=0
  (b) default       — cluster_capacity=3, cluster_penalty=5 (default)
  (c) strict        — cluster_capacity=1, cluster_penalty=10

For each pair of variants, analyses the passages that changed and measures
embedding distance and enrichment profile distance between replaced and
replacement passages.

Usage:
    uv run python -m enrichment.experiment_redundancy
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import lancedb  # pyright: ignore[reportMissingImports]
import numpy as np
from dotenv import load_dotenv

from enrichment.transport_podcast import (  # pyright: ignore[reportMissingImports]
    DEFAULT_ARCS,
    DEFAULT_EXPERTS,
    PROVISION_DIMENSIONS,
    STRENGTH_TO_SUPPLY,
    AggregatedResult,
    PassageRecord,
    ProducerConfig,
    load_passages,
    run_pipeline,
)

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = Path("data")
REPORTS_DIR = Path("reports")
DB_PATH = DATA_DIR / "bleak_house_vectors"
OUTPUT_PATH = DATA_DIR / "experiment_redundancy.json"

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
# Variant configs
# ---------------------------------------------------------------------------

VARIANT_CONFIGS: dict[str, ProducerConfig] = {
    "no_penalty": ProducerConfig(cluster_capacity=999, cluster_penalty=0),
    "default": ProducerConfig(),  # cluster_capacity=3, cluster_penalty=5
    "strict": ProducerConfig(cluster_capacity=1, cluster_penalty=10),
}

# All pairwise comparisons (from less constrained to more constrained)
VARIANT_PAIRS: list[tuple[str, str]] = [
    ("no_penalty", "default"),
    ("no_penalty", "strict"),
    ("default", "strict"),
]

# ---------------------------------------------------------------------------
# Embedding loading
# ---------------------------------------------------------------------------


def load_embeddings(passage_ids: set[str]) -> dict[str, np.ndarray]:
    """Load passage embeddings from LanceDB for the given passage IDs."""
    logger.info("Loading embeddings from LanceDB at %s", DB_PATH)
    db = lancedb.connect(str(DB_PATH))
    table = db.open_table("passages")

    # Pull all rows and filter to needed IDs
    df = table.to_pandas()
    embeddings: dict[str, np.ndarray] = {}
    for _, row in df.iterrows():
        pid = str(row["passage_id"])
        if pid in passage_ids:
            embeddings[pid] = np.array(row["vector"], dtype=np.float64)

    logger.info("Loaded embeddings for %d / %d requested passages", len(embeddings), len(passage_ids))
    return embeddings


# ---------------------------------------------------------------------------
# Distance metrics
# ---------------------------------------------------------------------------


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine distance: 1 - cos(a, b)."""
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 1.0
    return float(1.0 - dot / (norm_a * norm_b))


def enrichment_profile(passage: PassageRecord) -> list[int]:
    """Convert provision fields to a 7-dim ordinal vector (none=0, weak=1, strong=2)."""
    return [
        STRENGTH_TO_SUPPLY.get(passage.provisions.get(dim, "none"), 0)
        for dim in PROVISION_DIMENSIONS
    ]


def enrichment_distance(a: PassageRecord, b: PassageRecord) -> int:
    """L1 (Manhattan) distance on discretized provision profiles."""
    pa = enrichment_profile(a)
    pb = enrichment_profile(b)
    return sum(abs(x - y) for x, y in zip(pa, pb))


# ---------------------------------------------------------------------------
# Pairwise analysis
# ---------------------------------------------------------------------------


@dataclass
class PairwiseChange:
    """A passage that was replaced between two variants."""
    removed_id: str
    added_id: str
    expert: str
    embedding_distance: float | None  # None if embedding unavailable
    enrichment_distance: int
    different_chapter: bool
    different_narrator: bool
    different_character_cluster: bool


@dataclass
class PairwiseAnalysis:
    """Analysis of differences between two transport variants."""
    variant_a: str
    variant_b: str
    n_passages_a: int
    n_passages_b: int
    n_only_in_a: int
    n_only_in_b: int
    n_shared: int
    changes: list[PairwiseChange]
    mean_embedding_distance: float | None
    mean_enrichment_distance: float | None
    frac_different_chapter: float
    frac_different_narrator: float
    frac_different_character_cluster: float
    # Characterization counts
    n_emb_close_enr_distant: int  # transport catches what embeddings miss
    n_emb_distant_enr_close: int  # transport optimizes beyond surface similarity
    n_both_close: int  # genuine near-duplicates suppressed
    n_both_distant: int  # network flow balancing


def extract_assignment_sets(result: AggregatedResult) -> dict[str, set[str]]:
    """Extract per-expert passage ID sets from an AggregatedResult."""
    expert_passages: dict[str, set[str]] = defaultdict(set)
    for a in result.assignments:
        if a.expert:
            expert_passages[a.expert].add(a.passage_id)
    return dict(expert_passages)


def extract_all_passage_ids(result: AggregatedResult) -> set[str]:
    """Extract the global set of assigned passage IDs."""
    return {a.passage_id for a in result.assignments}


def analyze_pair(
    name_a: str,
    name_b: str,
    result_a: AggregatedResult,
    result_b: AggregatedResult,
    passage_map: dict[str, PassageRecord],
    embeddings: dict[str, np.ndarray],
) -> PairwiseAnalysis:
    """Analyze differences between two transport variants."""
    ids_a = extract_all_passage_ids(result_a)
    ids_b = extract_all_passage_ids(result_b)

    only_in_a = ids_a - ids_b
    only_in_b = ids_b - ids_a
    shared = ids_a & ids_b

    logger.info(
        "Pair %s vs %s: |a|=%d |b|=%d shared=%d only_a=%d only_b=%d",
        name_a, name_b, len(ids_a), len(ids_b), len(shared),
        len(only_in_a), len(only_in_b),
    )

    # Per-expert change tracking: for each expert, find passages added/removed
    experts_a = extract_assignment_sets(result_a)
    experts_b = extract_assignment_sets(result_b)
    all_experts = set(experts_a.keys()) | set(experts_b.keys())

    changes: list[PairwiseChange] = []

    # Thresholds for close/distant characterization
    emb_close_threshold = 0.15
    enr_close_threshold = 3  # out of max 14

    for expert in sorted(all_experts):
        pids_a = experts_a.get(expert, set())
        pids_b = experts_b.get(expert, set())
        removed = pids_a - pids_b
        added = pids_b - pids_a

        # Pair removed passages with their closest added replacement
        # (by enrichment profile similarity)
        removed_list = sorted(removed)
        added_list = sorted(added)

        for rm_id in removed_list:
            rm_passage = passage_map.get(rm_id)
            if rm_passage is None:
                continue

            # Find the closest added passage by enrichment profile
            best_add_id: str | None = None
            best_enr_dist = 999
            for ad_id in added_list:
                ad_passage = passage_map.get(ad_id)
                if ad_passage is None:
                    continue
                d = enrichment_distance(rm_passage, ad_passage)
                if d < best_enr_dist:
                    best_enr_dist = d
                    best_add_id = ad_id

            if best_add_id is None:
                continue

            ad_passage = passage_map[best_add_id]

            # Embedding distance
            emb_dist: float | None = None
            if rm_id in embeddings and best_add_id in embeddings:
                emb_dist = cosine_distance(embeddings[rm_id], embeddings[best_add_id])

            # Narrator extraction: use chapter_id prefix as proxy
            # (Bleak House alternates first-person Esther chapters with
            # third-person omniscient)
            diff_chapter = rm_passage.chapter_id != ad_passage.chapter_id
            diff_narrator = False
            # Simple narrator heuristic: even-numbered chapters are Esther's
            # narration in Bleak House (chapters are 1-indexed)
            try:
                rm_ch = int(rm_passage.chapter_id.split("_")[-1])
                ad_ch = int(ad_passage.chapter_id.split("_")[-1])
                rm_narrator = "esther" if rm_ch % 2 == 0 else "omniscient"
                ad_narrator = "esther" if ad_ch % 2 == 0 else "omniscient"
                diff_narrator = rm_narrator != ad_narrator
            except (ValueError, IndexError):
                pass

            diff_char_cluster = rm_passage.character_cluster != ad_passage.character_cluster

            changes.append(PairwiseChange(
                removed_id=rm_id,
                added_id=best_add_id,
                expert=expert,
                embedding_distance=emb_dist,
                enrichment_distance=best_enr_dist,
                different_chapter=diff_chapter,
                different_narrator=diff_narrator,
                different_character_cluster=diff_char_cluster,
            ))

    # Aggregate metrics
    emb_dists = [c.embedding_distance for c in changes if c.embedding_distance is not None]
    enr_dists = [c.enrichment_distance for c in changes]

    mean_emb = float(np.mean(emb_dists)) if emb_dists else None
    mean_enr = float(np.mean(enr_dists)) if enr_dists else None

    n_total = len(changes) or 1  # avoid division by zero
    frac_diff_ch = sum(1 for c in changes if c.different_chapter) / n_total
    frac_diff_nar = sum(1 for c in changes if c.different_narrator) / n_total
    frac_diff_cc = sum(1 for c in changes if c.different_character_cluster) / n_total

    # Characterize changes
    n_emb_close_enr_distant = 0
    n_emb_distant_enr_close = 0
    n_both_close = 0
    n_both_distant = 0

    for c in changes:
        if c.embedding_distance is None:
            continue
        emb_close = c.embedding_distance < emb_close_threshold
        enr_close = c.enrichment_distance <= enr_close_threshold

        if emb_close and enr_close:
            n_both_close += 1
        elif emb_close and not enr_close:
            n_emb_close_enr_distant += 1
        elif not emb_close and enr_close:
            n_emb_distant_enr_close += 1
        else:
            n_both_distant += 1

    return PairwiseAnalysis(
        variant_a=name_a,
        variant_b=name_b,
        n_passages_a=len(ids_a),
        n_passages_b=len(ids_b),
        n_only_in_a=len(only_in_a),
        n_only_in_b=len(only_in_b),
        n_shared=len(shared),
        changes=changes,
        mean_embedding_distance=mean_emb,
        mean_enrichment_distance=mean_enr,
        frac_different_chapter=frac_diff_ch,
        frac_different_narrator=frac_diff_nar,
        frac_different_character_cluster=frac_diff_cc,
        n_emb_close_enr_distant=n_emb_close_enr_distant,
        n_emb_distant_enr_close=n_emb_distant_enr_close,
        n_both_close=n_both_close,
        n_both_distant=n_both_distant,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def build_report(analyses: list[PairwiseAnalysis], tag: str) -> str:
    """Generate a human-readable report."""
    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("Experiment 8: The Redundancy Question")
    lines.append(f"Tag: {tag}")
    lines.append("=" * 80)
    lines.append("")

    lines.append("VARIANT CONFIGURATIONS:")
    for name, cfg in VARIANT_CONFIGS.items():
        lines.append(
            f"  {name:<15s} cluster_capacity={cfg.cluster_capacity:3d}  "
            f"cluster_penalty={cfg.cluster_penalty:2d}"
        )
    lines.append("")

    for pa in analyses:
        lines.append("-" * 80)
        lines.append(f"COMPARISON: {pa.variant_a} vs {pa.variant_b}")
        lines.append("-" * 80)
        lines.append(f"  Passages in {pa.variant_a}: {pa.n_passages_a}")
        lines.append(f"  Passages in {pa.variant_b}: {pa.n_passages_b}")
        lines.append(f"  Shared passages:           {pa.n_shared}")
        lines.append(f"  Only in {pa.variant_a}:          {pa.n_only_in_a}")
        lines.append(f"  Only in {pa.variant_b}:          {pa.n_only_in_b}")
        lines.append(f"  Paired changes analysed:   {len(pa.changes)}")
        lines.append("")

        lines.append("  DISTANCE METRICS (replaced <-> replacement):")
        if pa.mean_embedding_distance is not None:
            lines.append(f"    Mean embedding distance (cosine):  {pa.mean_embedding_distance:.4f}")
        else:
            lines.append("    Mean embedding distance (cosine):  N/A (no embeddings)")
        if pa.mean_enrichment_distance is not None:
            lines.append(f"    Mean enrichment distance (L1/7d):  {pa.mean_enrichment_distance:.2f}")
        else:
            lines.append("    Mean enrichment distance (L1/7d):  N/A")
        lines.append("")

        lines.append("  DIVERSITY OF REPLACEMENTS:")
        lines.append(f"    From different chapter:           {pa.frac_different_chapter:.1%}")
        lines.append(f"    From different narrator:          {pa.frac_different_narrator:.1%}")
        lines.append(f"    From different character cluster:  {pa.frac_different_character_cluster:.1%}")
        lines.append("")

        lines.append("  CHARACTERIZATION (emb_close < 0.15, enr_close <= 3):")
        lines.append(f"    Both close (genuine near-duplicates):             {pa.n_both_close}")
        lines.append(f"    Emb close, enr distant (transport catches more):  {pa.n_emb_close_enr_distant}")
        lines.append(f"    Emb distant, enr close (beyond surface sim):      {pa.n_emb_distant_enr_close}")
        lines.append(f"    Both distant (network flow balancing):            {pa.n_both_distant}")
        lines.append("")

        # Interpretation
        total_classified = (
            pa.n_both_close + pa.n_emb_close_enr_distant
            + pa.n_emb_distant_enr_close + pa.n_both_distant
        )
        if total_classified > 0:
            lines.append("  INTERPRETATION:")
            pct_both_close = pa.n_both_close / total_classified
            pct_flow = pa.n_both_distant / total_classified
            pct_transport_extra = pa.n_emb_close_enr_distant / total_classified
            pct_beyond_surface = pa.n_emb_distant_enr_close / total_classified

            if pct_both_close > 0.5:
                lines.append(
                    "    Redundancy penalties mainly suppress genuine near-duplicates "
                    f"({pct_both_close:.0%} of changes)."
                )
            elif pct_transport_extra > 0.3:
                lines.append(
                    "    Transport catches redundancy that embeddings miss — "
                    "passages are textually similar but enrichment-diverse "
                    f"({pct_transport_extra:.0%} of changes)."
                )
            elif pct_beyond_surface > 0.3:
                lines.append(
                    "    Transport optimizes beyond surface similarity — "
                    "replacements are textually distant but enrichment-similar "
                    f"({pct_beyond_surface:.0%} of changes)."
                )
            elif pct_flow > 0.4:
                lines.append(
                    "    Changes are driven by network flow balancing, "
                    "not passage similarity "
                    f"({pct_flow:.0%} of changes are distant on both metrics)."
                )
            else:
                lines.append(
                    "    Mixed picture: no single characterization dominates."
                )
        lines.append("")

    # Overall conclusion
    lines.append("=" * 80)
    lines.append("OVERALL CONCLUSION")
    lines.append("=" * 80)
    lines.append(
        "Does transport-redundancy correspond to embedding-redundancy?"
    )

    # Gather stats across all pairs
    all_both_close = sum(pa.n_both_close for pa in analyses)
    all_emb_close_enr_dist = sum(pa.n_emb_close_enr_distant for pa in analyses)
    all_emb_dist_enr_close = sum(pa.n_emb_distant_enr_close for pa in analyses)
    all_both_distant = sum(pa.n_both_distant for pa in analyses)
    grand_total = all_both_close + all_emb_close_enr_dist + all_emb_dist_enr_close + all_both_distant

    if grand_total > 0:
        lines.append(f"  Across all pairs ({grand_total} classified changes):")
        lines.append(f"    Both close:              {all_both_close:3d} ({all_both_close/grand_total:.0%})")
        lines.append(f"    Emb close, enr distant:  {all_emb_close_enr_dist:3d} ({all_emb_close_enr_dist/grand_total:.0%})")
        lines.append(f"    Emb distant, enr close:  {all_emb_dist_enr_close:3d} ({all_emb_dist_enr_close/grand_total:.0%})")
        lines.append(f"    Both distant:            {all_both_distant:3d} ({all_both_distant/grand_total:.0%})")

        if all_both_close / grand_total < 0.5:
            lines.append("")
            lines.append(
                "  Transport-redundancy diverges from embedding-redundancy. "
                "The transport layer encodes a notion of redundancy that "
                "standard RAG (embedding similarity) does not capture."
            )
        else:
            lines.append("")
            lines.append(
                "  Transport-redundancy largely aligns with embedding-redundancy. "
                "Redundancy penalties mainly suppress near-duplicate passages."
            )
    else:
        lines.append("  No classified changes to analyse.")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON serialization
# ---------------------------------------------------------------------------


def serialize_results(
    variant_results: dict[str, AggregatedResult],
    analyses: list[PairwiseAnalysis],
) -> dict:
    """Serialize experiment results to a JSON-friendly dict."""
    data: dict = {
        "variants": {},
        "pairwise_analyses": [],
    }

    for name, result in variant_results.items():
        cfg = VARIANT_CONFIGS[name]
        ids = extract_all_passage_ids(result)
        data["variants"][name] = {
            "cluster_capacity": cfg.cluster_capacity,
            "cluster_penalty": cfg.cluster_penalty,
            "n_assignments": len(result.assignments),
            "n_unique_passages": len(ids),
            "passage_ids": sorted(ids),
        }

    for pa in analyses:
        changes_data = []
        for c in pa.changes:
            changes_data.append({
                "removed_id": c.removed_id,
                "added_id": c.added_id,
                "expert": c.expert,
                "embedding_distance": round(c.embedding_distance, 6) if c.embedding_distance is not None else None,
                "enrichment_distance": c.enrichment_distance,
                "different_chapter": c.different_chapter,
                "different_narrator": c.different_narrator,
                "different_character_cluster": c.different_character_cluster,
            })

        data["pairwise_analyses"].append({
            "variant_a": pa.variant_a,
            "variant_b": pa.variant_b,
            "n_passages_a": pa.n_passages_a,
            "n_passages_b": pa.n_passages_b,
            "n_shared": pa.n_shared,
            "n_only_in_a": pa.n_only_in_a,
            "n_only_in_b": pa.n_only_in_b,
            "n_changes": len(pa.changes),
            "mean_embedding_distance": round(pa.mean_embedding_distance, 6) if pa.mean_embedding_distance is not None else None,
            "mean_enrichment_distance": round(pa.mean_enrichment_distance, 4) if pa.mean_enrichment_distance is not None else None,
            "frac_different_chapter": round(pa.frac_different_chapter, 4),
            "frac_different_narrator": round(pa.frac_different_narrator, 4),
            "frac_different_character_cluster": round(pa.frac_different_character_cluster, 4),
            "characterization": {
                "both_close": pa.n_both_close,
                "emb_close_enr_distant": pa.n_emb_close_enr_distant,
                "emb_distant_enr_close": pa.n_emb_distant_enr_close,
                "both_distant": pa.n_both_distant,
            },
            "changes": changes_data,
        })

    return data


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def run_experiment() -> None:
    """Run all three variants and perform pairwise analysis."""
    tag = make_tag()
    logger.info("Experiment 8: The Redundancy Question")
    logger.info("Tag: %s", tag)

    # Run transport pipeline for each variant
    variant_results: dict[str, AggregatedResult] = {}
    for name, config in VARIANT_CONFIGS.items():
        logger.info("Running variant '%s' (cap=%d, penalty=%d)", name, config.cluster_capacity, config.cluster_penalty)
        result = run_pipeline(
            experts=DEFAULT_EXPERTS,
            arcs=DEFAULT_ARCS,
            config=config,
        )
        variant_results[name] = result
        n_unique = len(extract_all_passage_ids(result))
        logger.info("Variant '%s': %d assignments, %d unique passages", name, len(result.assignments), n_unique)

    # Load passages for metadata lookups
    passages = load_passages()
    passage_map = {p.passage_id: p for p in passages}

    # Collect all passage IDs that appear in any variant for embedding loading
    all_ids: set[str] = set()
    for result in variant_results.values():
        all_ids.update(extract_all_passage_ids(result))

    # Load embeddings from LanceDB
    embeddings = load_embeddings(all_ids)

    # Pairwise analyses
    analyses: list[PairwiseAnalysis] = []
    for name_a, name_b in VARIANT_PAIRS:
        logger.info("Analysing pair: %s vs %s", name_a, name_b)
        pa = analyze_pair(
            name_a, name_b,
            variant_results[name_a], variant_results[name_b],
            passage_map, embeddings,
        )
        analyses.append(pa)

    # Save JSON results
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    results_data = serialize_results(variant_results, analyses)
    OUTPUT_PATH.write_text(json.dumps(results_data, indent=2))
    logger.info("Saved results to %s", OUTPUT_PATH)

    # Save human-readable report
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_text = build_report(analyses, tag)
    report_path = REPORTS_DIR / f"redundancy_{tag}.txt"
    report_path.write_text(report_text)
    logger.info("Saved report to %s", report_path)

    # Print summary
    for pa in analyses:
        logger.info(
            "%s vs %s: %d changes, mean_emb=%.4f, mean_enr=%.2f, "
            "diff_chapter=%.0f%%, diff_narrator=%.0f%%, diff_cluster=%.0f%%",
            pa.variant_a, pa.variant_b,
            len(pa.changes),
            pa.mean_embedding_distance if pa.mean_embedding_distance is not None else 0.0,
            pa.mean_enrichment_distance if pa.mean_enrichment_distance is not None else 0.0,
            pa.frac_different_chapter * 100,
            pa.frac_different_narrator * 100,
            pa.frac_different_character_cluster * 100,
        )

    logger.info("Done.")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    run_experiment()


if __name__ == "__main__":
    main()
