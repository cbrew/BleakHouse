"""Experiment 6: Character Arc Retrieval.

Tests whether embedding-based retrieval can reconstruct character arcs by
comparing vector retrieval (top-30 from LanceDB) against metadata-filtered
retrieval (characters_present + prov_character_development from enrichment).

Metrics computed for both strategies:
  - Coverage: fraction of character's chapters represented in retrieved set
  - Ordering (Kendall's tau): correlation between retrieved chapter order
    and true chapter sequence
  - Arc endpoint coverage: whether first-quarter and last-quarter chapters
    are included

Usage:
    uv run python -m enrichment.experiment_character_arcs
"""

import json
import logging
import subprocess
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import lancedb  # pyright: ignore[reportMissingImports]
import numpy as np
from dotenv import load_dotenv
from scipy.stats import kendalltau

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
REPORTS_DIR = Path("reports")
DB_PATH = DATA_DIR / "bleak_house_vectors"
PASSAGES_PATH = DATA_DIR / "passages_enriched.json"
ARCS_PATH = DATA_DIR / "character_arcs.json"
OUTPUT_PATH = DATA_DIR / "experiment_character_arcs.json"

TABLE_NAME = "passages"
TOP_K = 30

# Characters to evaluate with their arc queries
CHARACTER_QUERIES: dict[str, str] = {
    "Richard Carstone": "Richard Carstone's relationship with Jarndyce and Jarndyce",
    "Lady Dedlock": "Lady Dedlock's secret and her exposure",
    "Esther Summerson": "Esther Summerson's identity and sense of belonging",
}


def _chapter_sort_key(chapter_id: str) -> tuple[int, str]:
    """Sort chapter IDs: cP before numbered, c1-c67 numerically, F2-F3 after."""
    suffix = chapter_id[1:]
    if suffix.isdigit():
        return (1, str(int(suffix)).zfill(4))
    return (0, chapter_id)


def get_git_hash() -> str:
    """Return short git hash for tagging output files."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "nogit"


def make_tag() -> str:
    """Return a timestamp_githash tag for output file naming."""
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    gh = get_git_hash()
    return f"{ts}_{gh}"


@dataclass
class ArcMetrics:
    """Metrics for a single character under a single retrieval strategy."""

    character: str
    strategy: str
    num_retrieved: int = 0
    chapters_retrieved: list[str] = field(default_factory=list)
    ground_truth_chapters: list[str] = field(default_factory=list)
    coverage: float = 0.0
    kendall_tau: float = 0.0
    kendall_pvalue: float = 0.0
    first_quarter_covered: bool = False
    last_quarter_covered: bool = False
    arc_endpoint_coverage: float = 0.0


def load_passages(path: Path) -> list[dict]:
    """Load passages from JSON."""
    raw: list[dict] = json.loads(path.read_text())
    logger.info("Loaded %d passages from %s", len(raw), path)
    return raw


def load_character_arcs(path: Path) -> dict[str, list[str]]:
    """Load character -> [chapter_ids] mapping."""
    arcs: dict[str, list[str]] = json.loads(path.read_text())
    logger.info("Loaded arcs for %d characters from %s", len(arcs), path)
    return arcs


def build_enrichment_index(
    passages: list[dict],
) -> dict[str, dict]:
    """Build passage_id -> enrichment dict lookup."""
    index: dict[str, dict] = {}
    for p in passages:
        pid = p.get("passage_id", "")
        enrichment = p.get("enrichment")
        if pid and enrichment:
            index[pid] = {
                "chapter_id": p["chapter_id"],
                "characters_present": enrichment.get("characters_present", []),
                "prov_character_development": enrichment.get(
                    "prov_character_development", "none"
                ),
            }
    return index


def get_ground_truth_chapters(
    character: str,
    character_arcs: dict[str, list[str]],
    enrichment_index: dict[str, dict],
) -> list[str]:
    """Get sorted list of chapters where a character appears.

    Combines character_arcs.json data with scanning enrichment for
    characters_present mentions.
    """
    chapters: set[str] = set()

    # From character_arcs.json
    if character in character_arcs:
        chapters.update(character_arcs[character])

    # From enrichment characters_present
    for info in enrichment_index.values():
        chars = info["characters_present"]
        if character in chars:
            chapters.add(info["chapter_id"])

    return sorted(chapters, key=_chapter_sort_key)


def vector_retrieval(
    table: lancedb.table.Table,
    query: str,
    top_k: int,
) -> list[dict]:
    """Retrieve top-k passages by vector similarity."""
    results = table.search(query, query_type="vector").limit(top_k).to_pandas()
    records: list[dict] = []
    for _, row in results.iterrows():
        records.append(
            {
                "passage_id": row["passage_id"],
                "chapter_id": row["chapter_id"],
                "distance": float(row.get("_distance") or 0.0),
            }
        )
    return records


def metadata_filtered_retrieval(
    character: str,
    enrichment_index: dict[str, dict],
) -> list[dict]:
    """Retrieve passages where character is present and has character development.

    Returns passages filtered by characters_present containing the character
    AND prov_character_development != "none", ordered by chapter.
    """
    matches: list[dict] = []
    for pid, info in enrichment_index.items():
        if (
            character in info["characters_present"]
            and info["prov_character_development"] != "none"
        ):
            matches.append(
                {
                    "passage_id": pid,
                    "chapter_id": info["chapter_id"],
                }
            )

    # Sort by chapter order
    matches.sort(key=lambda m: _chapter_sort_key(m["chapter_id"]))
    return matches


def compute_metrics(
    character: str,
    strategy: str,
    retrieved: list[dict],
    ground_truth_chapters: list[str],
) -> ArcMetrics:
    """Compute coverage, Kendall's tau, and arc endpoint coverage."""
    metrics = ArcMetrics(
        character=character,
        strategy=strategy,
        num_retrieved=len(retrieved),
        ground_truth_chapters=ground_truth_chapters,
    )

    if not retrieved or not ground_truth_chapters:
        return metrics

    # Chapters in the retrieved set (deduplicated, preserving first occurrence order)
    seen: set[str] = set()
    retrieved_chapters: list[str] = []
    for r in retrieved:
        ch = r["chapter_id"]
        if ch not in seen:
            seen.add(ch)
            retrieved_chapters.append(ch)
    metrics.chapters_retrieved = sorted(retrieved_chapters, key=_chapter_sort_key)

    gt_set = set(ground_truth_chapters)

    # Coverage: fraction of ground truth chapters represented
    covered = gt_set & seen
    metrics.coverage = len(covered) / len(gt_set) if gt_set else 0.0

    # Kendall's tau: correlation between retrieved chapter order and true sequence
    # Assign rank positions based on ground truth order
    gt_rank = {ch: i for i, ch in enumerate(ground_truth_chapters)}

    # Filter retrieved chapters to those in ground truth, in retrieved order
    retrieved_in_gt = [ch for ch in metrics.chapters_retrieved if ch in gt_rank]
    if len(retrieved_in_gt) >= 2:
        retrieved_ranks = [gt_rank[ch] for ch in retrieved_in_gt]
        # Compare against the natural ordering (0, 1, 2, ...)
        natural_order = list(range(len(retrieved_ranks)))
        # Sort retrieved_ranks and compare to see if they're in order
        tau_result = kendalltau(retrieved_ranks, natural_order)
        metrics.kendall_tau = float(tau_result.statistic)  # type: ignore[union-attr]
        metrics.kendall_pvalue = float(tau_result.pvalue)  # type: ignore[union-attr]
    else:
        metrics.kendall_tau = float("nan")
        metrics.kendall_pvalue = float("nan")

    # Arc endpoint coverage: first quarter and last quarter
    n_gt = len(ground_truth_chapters)
    first_quarter_cutoff = max(1, n_gt // 4)
    last_quarter_start = n_gt - max(1, n_gt // 4)

    first_quarter_chapters = set(ground_truth_chapters[:first_quarter_cutoff])
    last_quarter_chapters = set(ground_truth_chapters[last_quarter_start:])

    metrics.first_quarter_covered = bool(first_quarter_chapters & seen)
    metrics.last_quarter_covered = bool(last_quarter_chapters & seen)

    endpoints_hit = sum(
        [metrics.first_quarter_covered, metrics.last_quarter_covered]
    )
    metrics.arc_endpoint_coverage = endpoints_hit / 2.0

    return metrics


def format_report(
    all_metrics: list[ArcMetrics],
    tag: str,
) -> str:
    """Format a human-readable summary report."""
    lines: list[str] = []
    lines.append("Character Arc Retrieval Experiment (Experiment 6)")
    lines.append(f"Tag: {tag}")
    lines.append(f"Generated: {datetime.now(tz=timezone.utc).isoformat()}")
    lines.append("=" * 72)
    lines.append("")

    # Group by character
    by_character: dict[str, list[ArcMetrics]] = defaultdict(list)
    for m in all_metrics:
        by_character[m.character].append(m)

    for character, metrics_list in by_character.items():
        lines.append(f"Character: {character}")
        gt = metrics_list[0].ground_truth_chapters
        lines.append(f"  Ground truth chapters ({len(gt)}): {', '.join(gt)}")
        lines.append("")

        for m in metrics_list:
            lines.append(f"  Strategy: {m.strategy}")
            lines.append(f"    Retrieved passages: {m.num_retrieved}")
            lines.append(
                f"    Chapters retrieved ({len(m.chapters_retrieved)}): "
                f"{', '.join(m.chapters_retrieved)}"
            )
            lines.append(f"    Coverage: {m.coverage:.3f}")
            tau_str = f"{m.kendall_tau:.3f}" if not np.isnan(m.kendall_tau) else "N/A"
            pval_str = (
                f"{m.kendall_pvalue:.4f}"
                if not np.isnan(m.kendall_pvalue)
                else "N/A"
            )
            lines.append(f"    Kendall's tau: {tau_str} (p={pval_str})")
            lines.append(f"    First quarter covered: {m.first_quarter_covered}")
            lines.append(f"    Last quarter covered: {m.last_quarter_covered}")
            lines.append(f"    Arc endpoint coverage: {m.arc_endpoint_coverage:.3f}")
            lines.append("")

        lines.append("-" * 72)
        lines.append("")

    # Summary table
    lines.append("SUMMARY")
    lines.append(
        f"{'Character':<25} {'Strategy':<25} {'Coverage':>8} {'Tau':>8} "
        f"{'Endpoints':>10}"
    )
    lines.append("-" * 80)
    for m in all_metrics:
        tau_str = f"{m.kendall_tau:.3f}" if not np.isnan(m.kendall_tau) else "N/A"
        lines.append(
            f"{m.character:<25} {m.strategy:<25} {m.coverage:>8.3f} "
            f"{tau_str:>8} {m.arc_endpoint_coverage:>10.3f}"
        )
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    load_dotenv()

    REPORTS_DIR.mkdir(exist_ok=True)
    tag = make_tag()

    # Load data
    passages = load_passages(PASSAGES_PATH)
    character_arcs = load_character_arcs(ARCS_PATH)
    enrichment_index = build_enrichment_index(passages)
    logger.info("Built enrichment index: %d passages", len(enrichment_index))

    # Connect to LanceDB
    logger.info("Connecting to LanceDB at %s", DB_PATH)
    db = lancedb.connect(str(DB_PATH))
    table = db.open_table(TABLE_NAME)

    all_metrics: list[ArcMetrics] = []
    all_results: dict[str, dict] = {}

    for character, query in CHARACTER_QUERIES.items():
        logger.info("Processing character: %s", character)
        logger.info("  Query: %s", query)

        gt_chapters = get_ground_truth_chapters(
            character, character_arcs, enrichment_index
        )
        logger.info("  Ground truth chapters: %d", len(gt_chapters))

        # Strategy (a): Vector retrieval
        vector_results = vector_retrieval(table, query, TOP_K)
        vector_metrics = compute_metrics(
            character, "vector_retrieval", vector_results, gt_chapters
        )
        all_metrics.append(vector_metrics)
        logger.info(
            "  Vector retrieval: %d passages, coverage=%.3f, tau=%.3f",
            len(vector_results),
            vector_metrics.coverage,
            vector_metrics.kendall_tau
            if not np.isnan(vector_metrics.kendall_tau)
            else 0.0,
        )

        # Strategy (b): Metadata-filtered retrieval
        meta_results = metadata_filtered_retrieval(character, enrichment_index)
        meta_metrics = compute_metrics(
            character, "metadata_filtered", meta_results, gt_chapters
        )
        all_metrics.append(meta_metrics)
        logger.info(
            "  Metadata filtered: %d passages, coverage=%.3f, tau=%.3f",
            len(meta_results),
            meta_metrics.coverage,
            meta_metrics.kendall_tau
            if not np.isnan(meta_metrics.kendall_tau)
            else 0.0,
        )

        all_results[character] = {
            "query": query,
            "ground_truth_chapters": gt_chapters,
            "vector_retrieval": {
                "passages": vector_results,
                "metrics": asdict(vector_metrics),
            },
            "metadata_filtered": {
                "passages": [
                    {"passage_id": r["passage_id"], "chapter_id": r["chapter_id"]}
                    for r in meta_results
                ],
                "metrics": asdict(meta_metrics),
            },
        }

    # Save JSON results
    OUTPUT_PATH.write_text(json.dumps(all_results, indent=2))
    logger.info("Saved results to %s", OUTPUT_PATH)

    # Save text report
    report = format_report(all_metrics, tag)
    report_path = REPORTS_DIR / f"character_arcs_experiment_{tag}.txt"
    report_path.write_text(report)
    logger.info("Saved report to %s", report_path)


if __name__ == "__main__":
    main()
