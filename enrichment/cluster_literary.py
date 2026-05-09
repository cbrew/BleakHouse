"""Cluster passages by their literary enrichment profile.

HDBSCAN clustering on a 24-dimensional feature matrix built from
plot_function (one-hot), emotional_register (multi-hot), and 7 prov_*
ordinal fields.

Usage:
    uv run python -m enrichment.cluster_literary

Dependencies: hdbscan (install separately if missing -- do NOT run uv add).
"""

import json
import logging
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import umap  # pyright: ignore[reportMissingImports]
from dotenv import load_dotenv
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

try:
    import hdbscan  # pyright: ignore[reportMissingImports]
except ImportError:
    raise SystemExit(
        "hdbscan is required but not installed.\n"
        "  uv add hdbscan   # or: pip install hdbscan"
    )

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
REPORTS_DIR = Path("reports")
INPUT_PATH = DATA_DIR / "passages_enriched.json"
OUTPUT_PATH = DATA_DIR / "clusters_literary.json"

PLOT_FUNCTIONS = [
    "action",
    "dialogue",
    "description",
    "exposition",
    "transition",
    "digression",
    "climax",
    "revelation",
]
EMOTIONAL_REGISTERS = [
    "comic",
    "tragic",
    "suspenseful",
    "satirical",
    "tender",
    "gothic",
    "polemical",
    "pastoral",
    "neutral",
]
PROV_FIELDS = [
    "prov_character_development",
    "prov_plot_advancement",
    "prov_thematic_depth",
    "prov_social_critique",
    "prov_humor_entertainment",
    "prov_atmosphere_setting",
    "prov_narrative_technique",
]
ORDINAL_MAP = {"none": 0, "weak": 1, "strong": 2}

# UMAP / HDBSCAN parameters
UMAP_N_NEIGHBORS = 15
UMAP_MIN_DIST = 0.1
UMAP_RANDOM_STATE = 42
MIN_CLUSTER_SIZE = 20
DPI = 150
DOT_SIZE = 3


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


def build_feature_matrix(
    passages: list[dict],
) -> tuple[np.ndarray, list[str]]:
    """Build a (N, 24) feature matrix from enrichment fields.

    Returns the matrix and the list of passage_ids in the same order.
    """
    n = len(passages)
    n_plot = len(PLOT_FUNCTIONS)
    n_emo = len(EMOTIONAL_REGISTERS)
    n_prov = len(PROV_FIELDS)
    total_cols = n_plot + n_emo + n_prov  # 8 + 9 + 7 = 24

    matrix = np.zeros((n, total_cols), dtype=np.float64)
    passage_ids: list[str] = []

    plot_idx = {pf: i for i, pf in enumerate(PLOT_FUNCTIONS)}
    emo_idx = {er: i + n_plot for i, er in enumerate(EMOTIONAL_REGISTERS)}

    for row, p in enumerate(passages):
        passage_ids.append(p["passage_id"])
        enr = p.get("enrichment") or {}

        # One-hot: plot_function
        pf = enr.get("plot_function", "")
        if pf in plot_idx:
            matrix[row, plot_idx[pf]] = 1.0

        # Multi-hot: emotional_register
        for er in enr.get("emotional_register", []):
            if er in emo_idx:
                matrix[row, emo_idx[er]] = 1.0

        # Ordinal: prov_* fields
        for j, field in enumerate(PROV_FIELDS):
            val = enr.get(field, "none")
            matrix[row, n_plot + n_emo + j] = float(ORDINAL_MAP.get(val, 0))

    return matrix, passage_ids


def characterize_cluster(
    passages: list[dict],
    indices: np.ndarray,
) -> dict:
    """Summarize the dominant features of a cluster."""
    pf_counter: Counter[str] = Counter()
    er_counter: Counter[str] = Counter()
    prov_sums = {f: 0.0 for f in PROV_FIELDS}

    for idx in indices:
        enr = passages[idx].get("enrichment") or {}
        pf_counter[enr.get("plot_function", "unknown")] += 1
        for er in enr.get("emotional_register", []):
            er_counter[er] += 1
        for f in PROV_FIELDS:
            prov_sums[f] += ORDINAL_MAP.get(enr.get(f, "none"), 0)

    n = len(indices)
    prov_means = {f: round(v / n, 2) for f, v in prov_sums.items()}

    return {
        "size": n,
        "dominant_plot_function": pf_counter.most_common(1)[0] if pf_counter else ("?", 0),
        "top_emotional_registers": er_counter.most_common(3),
        "prov_means": prov_means,
    }


def experiment_1_clustering(
    passages: list[dict],
    timestamp: str,
) -> None:
    """HDBSCAN clustering on the literary feature matrix."""
    logger.info("=== Experiment 1: Literary Feature Clustering ===")

    matrix, passage_ids = build_feature_matrix(passages)
    logger.info("Feature matrix shape: %s (passages x features)", matrix.shape)

    # Normalize
    scaler = StandardScaler()
    X = scaler.fit_transform(matrix)

    # HDBSCAN
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=MIN_CLUSTER_SIZE,
        metric="euclidean",
    )
    labels = clusterer.fit_predict(X)
    unique_labels = set(labels)
    n_clusters = len(unique_labels - {-1})
    n_noise = int(np.sum(labels == -1))

    logger.info("Clusters found: %d", n_clusters)
    logger.info("Noise points: %d / %d (%.1f%%)", n_noise, len(labels), 100 * n_noise / len(labels))

    # Silhouette score (excluding noise)
    mask_valid = labels != -1
    if n_clusters >= 2 and mask_valid.sum() > n_clusters:
        sil = silhouette_score(X[mask_valid], labels[mask_valid])
        logger.info("Silhouette score (excl. noise): %.3f", sil)
    else:
        sil = float("nan")
        logger.info("Silhouette score: N/A (too few clusters)")

    # Cluster sizes
    label_counts = Counter(labels)
    logger.info("Cluster sizes:")
    for lbl in sorted(label_counts):
        tag = f"  Cluster {lbl}" if lbl != -1 else "  Noise (-1)"
        logger.info("%s: %d passages", tag, label_counts[lbl])

    # Characterize each cluster
    logger.info("\n--- Cluster Profiles ---")
    for lbl in sorted(unique_labels - {-1}):
        indices = np.where(labels == lbl)[0]
        profile = characterize_cluster(passages, indices)
        pf_name, pf_count = profile["dominant_plot_function"]
        logger.info(
            "Cluster %d (%d passages): dominant plot_function=%s (%d), "
            "top emotions=%s",
            lbl,
            profile["size"],
            pf_name,
            pf_count,
            profile["top_emotional_registers"],
        )
        prov_str = ", ".join(
            f"{k.replace('prov_', '')}={v}"
            for k, v in profile["prov_means"].items()
        )
        logger.info("  prov means: %s", prov_str)

    # Save cluster assignments
    assignments = {pid: int(lbl) for pid, lbl in zip(passage_ids, labels)}
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(assignments, indent=2))
    logger.info("Saved cluster assignments to %s", OUTPUT_PATH)

    # UMAP visualization colored by cluster
    logger.info("Running UMAP on feature matrix for visualization...")
    reducer = umap.UMAP(
        n_neighbors=UMAP_N_NEIGHBORS,
        min_dist=UMAP_MIN_DIST,
        metric="euclidean",
        random_state=UMAP_RANDOM_STATE,
        n_components=2,
    )
    coords = reducer.fit_transform(X)

    REPORTS_DIR.mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(12, 9))

    # Plot noise first in grey
    noise_mask = labels == -1
    if noise_mask.any():
        ax.scatter(
            coords[noise_mask, 0],
            coords[noise_mask, 1],
            c="#cccccc",
            s=DOT_SIZE,
            alpha=0.3,
            label=f"noise ({noise_mask.sum()})",
        )

    # Plot each cluster
    cmap = plt.colormaps["tab20"]
    for lbl in sorted(unique_labels - {-1}):
        mask = labels == lbl
        color = cmap(lbl / max(n_clusters - 1, 1))
        ax.scatter(
            coords[mask, 0],
            coords[mask, 1],
            c=[color],
            s=DOT_SIZE,
            alpha=0.6,
            label=f"cluster {lbl} ({mask.sum()})",
        )

    ax.legend(markerscale=4, fontsize="small", loc="upper right")
    ax.set_title(
        f"Literary Feature Clusters (HDBSCAN, {n_clusters} clusters, "
        f"sil={sil:.3f})"
    )
    ax.set_xlabel("UMAP 1")
    ax.set_ylabel("UMAP 2")
    fig.tight_layout()

    plot_path = REPORTS_DIR / f"literary_clusters_{timestamp}.png"
    fig.savefig(plot_path, dpi=DPI)
    plt.close(fig)
    logger.info("Saved cluster visualization to %s", plot_path)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Cluster passages by literary features")
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

    REPORTS_DIR.mkdir(exist_ok=True)
    timestamp = f"{make_timestamp()}_{git_short_hash()}"

    # Resolve paths based on --novel
    global OUTPUT_PATH  # noqa: PLW0603
    if args.novel:
        novel_dir = DATA_DIR / "novels" / args.novel
        input_path = novel_dir / "passages_enriched.json"
        OUTPUT_PATH = novel_dir / "clusters_literary.json"
    else:
        input_path = INPUT_PATH

    # Load passages
    raw = json.loads(input_path.read_text())
    # Keep only passages with enrichment data
    passages = [p for p in raw if p.get("enrichment")]
    logger.info("Loaded %d passages with enrichment from %s", len(passages), input_path)

    experiment_1_clustering(passages, timestamp)

    logger.info("\nDone.")


if __name__ == "__main__":
    main()
