"""Cluster passages by character co-occurrence (dramatis personae).

Builds a binary character-presence matrix from passages_enriched.json,
computes Jaccard distances, clusters with HDBSCAN, and produces:
  - data/clusters_characters.json   (passage_id -> cluster label)
  - data/character_arcs.json         (character_name -> [chapter_ids])
  - reports/clusters_characters_<ts>_<hash>.png  (UMAP visualization)

Usage:
    uv run python -m enrichment.cluster_characters
"""

import json
import logging
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import hdbscan  # pyright: ignore[reportMissingImports]
import matplotlib.pyplot as plt
import numpy as np
import umap  # pyright: ignore[reportMissingImports]
from dotenv import load_dotenv
from scipy.sparse import csr_matrix
from sklearn.metrics import pairwise_distances

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
REPORTS_DIR = Path("reports")
PASSAGES_PATH = DATA_DIR / "passages_enriched.json"
CLUSTERS_PATH = DATA_DIR / "clusters_characters.json"
ARCS_PATH = DATA_DIR / "character_arcs.json"

HDBSCAN_MIN_CLUSTER_SIZE = 15

# UMAP parameters
UMAP_N_NEIGHBORS = 15
UMAP_MIN_DIST = 0.1
UMAP_RANDOM_STATE = 42

DOT_SIZE = 3
DPI = 150
TOP_CLUSTERS_TO_PRINT = 15
MIN_PASSAGES_FOR_ARC = 10
TOP_CHARACTERS_TO_PRINT = 20


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


def load_passages(path: Path) -> list[dict]:
    """Load passages from JSON."""
    with open(path) as f:
        passages: list[dict] = json.load(f)
    logger.info("Loaded %d passages from %s", len(passages), path)
    return passages


def build_character_matrix(
    passages: list[dict],
) -> tuple[csr_matrix, list[str], list[str]]:
    """Build a sparse binary (passages x characters) matrix from characters_present.

    Returns:
        matrix: sparse binary matrix
        passage_ids: list of passage_id strings (row labels)
        characters: sorted list of unique character names (column labels)
    """
    # Collect all unique characters
    all_characters: set[str] = set()
    for p in passages:
        chars = p.get("enrichment", {}).get("characters_present", [])
        all_characters.update(chars)

    characters = sorted(all_characters)
    char_to_idx = {c: i for i, c in enumerate(characters)}
    logger.info("Found %d unique characters", len(characters))

    # Build sparse matrix
    rows: list[int] = []
    cols: list[int] = []
    passage_ids: list[str] = []

    for row_idx, p in enumerate(passages):
        passage_ids.append(p["passage_id"])
        chars = p.get("enrichment", {}).get("characters_present", [])
        for c in chars:
            rows.append(row_idx)
            cols.append(char_to_idx[c])

    data = np.ones(len(rows), dtype=np.float64)
    matrix = csr_matrix(
        (data, (rows, cols)),
        shape=(len(passages), len(characters)),
    )
    logger.info("Character matrix shape: %s, nnz: %d", matrix.shape, matrix.nnz)
    return matrix, passage_ids, characters


def cluster_passages(matrix: csr_matrix) -> np.ndarray:
    """Cluster passages using HDBSCAN on Jaccard distance.

    Computes the full distance matrix, then runs HDBSCAN with metric='precomputed'.
    """
    logger.info(
        "Computing Jaccard distance matrix (%d x %d)...",
        matrix.shape[0],
        matrix.shape[0],
    )
    dist = pairwise_distances(matrix.toarray(), metric="jaccard")
    logger.info(
        "Distance matrix computed. Running HDBSCAN (min_cluster_size=%d)...",
        HDBSCAN_MIN_CLUSTER_SIZE,
    )

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=HDBSCAN_MIN_CLUSTER_SIZE,
        metric="precomputed",
    )
    labels: np.ndarray = clusterer.fit_predict(dist)
    return labels


def print_cluster_summary(
    labels: np.ndarray,
    passages: list[dict],
    characters: list[str],
    matrix: csr_matrix,
) -> None:
    """Print cluster sizes and top characters per cluster."""
    label_counts = Counter(int(lb) for lb in labels)
    n_clusters = sum(1 for lb in label_counts if lb >= 0)
    noise_count = label_counts.get(-1, 0)

    logger.info("--- Cluster summary ---")
    logger.info("  Clusters: %d", n_clusters)
    logger.info("  Noise passages (label -1): %d", noise_count)

    # Sort clusters by size (excluding noise)
    sorted_clusters = sorted(
        ((lb, ct) for lb, ct in label_counts.items() if lb >= 0),
        key=lambda x: x[1],
        reverse=True,
    )

    dense = matrix.toarray()
    for lb, count in sorted_clusters[:TOP_CLUSTERS_TO_PRINT]:
        mask = labels == lb
        cluster_vectors = dense[mask]
        # Sum presence across passages in this cluster
        char_sums = cluster_vectors.sum(axis=0)
        # Top characters by frequency in cluster
        top_indices = np.argsort(char_sums)[::-1][:8]
        top_chars = [
            (characters[i], int(char_sums[i])) for i in top_indices if char_sums[i] > 0
        ]
        top_str = ", ".join(f"{name}({n})" for name, n in top_chars)
        logger.info("  Cluster %d: %d passages — %s", lb, count, top_str)


def save_cluster_assignments(
    labels: np.ndarray,
    passage_ids: list[str],
    output_path: Path,
) -> None:
    """Save {passage_id: cluster_label} to JSON."""
    assignments = {pid: int(lb) for pid, lb in zip(passage_ids, labels)}
    with open(output_path, "w") as f:
        json.dump(assignments, f, indent=2)
    logger.info("Saved cluster assignments to %s", output_path)


def extract_character_arcs(
    passages: list[dict],
    output_path: Path,
) -> None:
    """For each character appearing in >= MIN_PASSAGES_FOR_ARC passages,
    list sorted chapter_ids. Save to JSON and print top characters."""
    char_chapters: dict[str, set[str]] = {}
    char_passage_count: Counter[str] = Counter()

    for p in passages:
        chars = p.get("enrichment", {}).get("characters_present", [])
        chapter_id = p["chapter_id"]
        for c in chars:
            char_passage_count[c] += 1
            if c not in char_chapters:
                char_chapters[c] = set()
            char_chapters[c].add(chapter_id)

    # Filter to characters with enough passages
    arcs: dict[str, list[str]] = {}
    for char_name, count in char_passage_count.items():
        if count >= MIN_PASSAGES_FOR_ARC:
            arcs[char_name] = sorted(char_chapters[char_name])

    with open(output_path, "w") as f:
        json.dump(arcs, f, indent=2)
    logger.info("Saved %d character arcs to %s", len(arcs), output_path)

    # Print top characters
    logger.info("--- Top %d characters by passage count ---", TOP_CHARACTERS_TO_PRINT)
    for char_name, count in char_passage_count.most_common(TOP_CHARACTERS_TO_PRINT):
        chapters = sorted(char_chapters[char_name])
        span = f"{chapters[0]}..{chapters[-1]}" if chapters else "none"
        logger.info(
            "  %-30s %4d passages, %3d chapters, span %s",
            char_name,
            count,
            len(chapters),
            span,
        )


def plot_umap_clusters(
    matrix: csr_matrix,
    labels: np.ndarray,
    output_path: Path,
) -> None:
    """UMAP projection of the character-presence matrix, colored by cluster."""
    logger.info("Running UMAP on character-presence matrix...")
    reducer = umap.UMAP(
        n_neighbors=UMAP_N_NEIGHBORS,
        min_dist=UMAP_MIN_DIST,
        metric="jaccard",
        random_state=UMAP_RANDOM_STATE,
        n_components=2,
    )
    coords = reducer.fit_transform(matrix.toarray())
    logger.info("UMAP projection complete: shape %s", coords.shape)

    n_clusters = len(set(int(lb) for lb in labels if lb >= 0))
    cmap = plt.colormaps["tab20"]

    fig, ax = plt.subplots(figsize=(12, 9))

    # Plot noise first (grey, small)
    noise_mask = labels == -1
    if noise_mask.any():
        ax.scatter(
            coords[noise_mask, 0],
            coords[noise_mask, 1],
            c="#cccccc",
            s=1,
            alpha=0.3,
            label=f"noise ({noise_mask.sum()})",
        )

    # Plot each cluster
    unique_labels = sorted(set(int(lb) for lb in labels if lb >= 0))
    for lb in unique_labels:
        mask = labels == lb
        color = cmap(lb % 20 / 20)
        ax.scatter(
            coords[mask, 0],
            coords[mask, 1],
            c=[color],
            s=DOT_SIZE,
            alpha=0.6,
            label=f"C{lb} ({mask.sum()})",
        )

    ax.legend(
        markerscale=4,
        fontsize="x-small",
        ncol=2,
        loc="upper left",
        bbox_to_anchor=(1.01, 1),
    )
    ax.set_title(f"Character Co-occurrence Clusters ({n_clusters} clusters, HDBSCAN)")
    ax.set_xlabel("UMAP 1")
    ax.set_ylabel("UMAP 2")
    fig.tight_layout()
    fig.savefig(output_path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved UMAP plot to %s", output_path)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Cluster passages by character presence")
    parser.add_argument(
        "--novel", type=str, default=None,
        help="Novel key (reads from data/novels/<key>/)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    load_dotenv()

    DATA_DIR.mkdir(exist_ok=True)
    REPORTS_DIR.mkdir(exist_ok=True)
    tag = make_tag()

    # Resolve paths based on --novel
    if args.novel:
        novel_dir = DATA_DIR / "novels" / args.novel
        passages_path = novel_dir / "passages_enriched.json"
        clusters_path = novel_dir / "clusters_characters.json"
        arcs_path = novel_dir / "character_arcs.json"
    else:
        passages_path = PASSAGES_PATH
        clusters_path = CLUSTERS_PATH
        arcs_path = ARCS_PATH

    # Step 1: Load passages
    passages = load_passages(passages_path)

    # Step 2: Build character presence matrix
    matrix, passage_ids, characters = build_character_matrix(passages)

    # Step 3-4: Cluster with HDBSCAN on Jaccard distance
    labels = cluster_passages(matrix)

    # Step 5: Print summary and save assignments
    print_cluster_summary(labels, passages, characters, matrix)
    save_cluster_assignments(labels, passage_ids, clusters_path)

    # Step 6: Character arcs
    extract_character_arcs(passages, arcs_path)

    # Step 7: UMAP visualization
    plot_path = REPORTS_DIR / f"clusters_characters_{tag}.png"
    plot_umap_clusters(matrix, labels, plot_path)

    logger.info("Done.")


if __name__ == "__main__":
    main()
