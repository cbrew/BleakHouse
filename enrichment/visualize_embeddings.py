"""Visualize passage embeddings from LanceDB using UMAP projections.

Usage:
    uv run python -m enrichment.visualize_embeddings
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

import lancedb
import matplotlib.pyplot as plt
import numpy as np
import umap  # pyright: ignore[reportMissingImports]
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

DB_PATH = Path("data/bleak_house_vectors")
REPORTS_DIR = Path("reports")
TABLE_NAME = "passages"

# UMAP parameters
UMAP_N_NEIGHBORS = 15
UMAP_MIN_DIST = 0.1
UMAP_METRIC = "cosine"
UMAP_RANDOM_STATE = 42

DOT_SIZE = 3
DPI = 150


def load_data(db_path: Path) -> lancedb.table.Table:
    """Open LanceDB and return the passages table."""
    db = lancedb.connect(str(db_path))
    return db.open_table(TABLE_NAME)


def make_timestamp() -> str:
    """Return a compact UTC timestamp string for file naming."""
    return datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")


def plot_by_chapter(
    coords: np.ndarray,
    chapter_ids: list[str],
    output_path: Path,
) -> None:
    """Scatter plot colored by chapter_id using a gradient colormap."""
    unique_chapters = sorted(set(chapter_ids))
    chapter_to_idx = {ch: i for i, ch in enumerate(unique_chapters)}
    colors = [chapter_to_idx[ch] for ch in chapter_ids]

    fig, ax = plt.subplots(figsize=(10, 8))
    scatter = ax.scatter(
        coords[:, 0],
        coords[:, 1],
        c=colors,
        cmap="viridis",
        s=DOT_SIZE,
        alpha=0.6,
    )
    fig.colorbar(scatter, ax=ax, label="Chapter (ordinal index)")
    ax.set_title(f"Passage Embeddings — Color by Chapter ({len(unique_chapters)} chapters)")
    ax.set_xlabel("UMAP 1")
    ax.set_ylabel("UMAP 2")
    fig.tight_layout()
    fig.savefig(output_path, dpi=DPI)
    plt.close(fig)
    logger.info("Saved chapter plot to %s", output_path)


def plot_by_narrator(
    coords: np.ndarray,
    narrators: list[str],
    output_path: Path,
) -> None:
    """Scatter plot colored by narrator with legend."""
    narrator_colors = {
        "esther": "#e74c3c",
        "omniscient": "#3498db",
        "unclear": "#95a5a6",
    }
    fig, ax = plt.subplots(figsize=(10, 8))
    for label, color in narrator_colors.items():
        mask = np.array([n == label for n in narrators])
        if not mask.any():
            continue
        ax.scatter(
            coords[mask, 0],
            coords[mask, 1],
            c=color,
            s=DOT_SIZE,
            alpha=0.6,
            label=f"{label} ({mask.sum()})",
        )
    ax.legend(markerscale=4)
    ax.set_title("Passage Embeddings — Color by Narrator")
    ax.set_xlabel("UMAP 1")
    ax.set_ylabel("UMAP 2")
    fig.tight_layout()
    fig.savefig(output_path, dpi=DPI)
    plt.close(fig)
    logger.info("Saved narrator plot to %s", output_path)


def plot_by_interest(
    coords: np.ndarray,
    scores: list[int],
    output_path: Path,
) -> None:
    """Scatter plot colored by interest_score (0–5 continuous)."""
    fig, ax = plt.subplots(figsize=(10, 8))
    scatter = ax.scatter(
        coords[:, 0],
        coords[:, 1],
        c=scores,
        cmap="plasma",
        vmin=0,
        vmax=5,
        s=DOT_SIZE,
        alpha=0.6,
    )
    fig.colorbar(scatter, ax=ax, label="Interest Score")
    ax.set_title("Passage Embeddings — Color by Interest Score")
    ax.set_xlabel("UMAP 1")
    ax.set_ylabel("UMAP 2")
    fig.tight_layout()
    fig.savefig(output_path, dpi=DPI)
    plt.close(fig)
    logger.info("Saved interest score plot to %s", output_path)


def plot_by_plot_function(
    coords: np.ndarray,
    plot_functions: list[str],
    output_path: Path,
) -> None:
    """Scatter plot colored by plot_function with legend."""
    unique_funcs = sorted(set(plot_functions))
    cmap = plt.colormaps["tab10"]
    func_colors = {f: cmap(i / max(len(unique_funcs) - 1, 1)) for i, f in enumerate(unique_funcs)}

    fig, ax = plt.subplots(figsize=(10, 8))
    for label, color in func_colors.items():
        mask = np.array([pf == label for pf in plot_functions])
        if not mask.any():
            continue
        ax.scatter(
            coords[mask, 0],
            coords[mask, 1],
            c=[color],
            s=DOT_SIZE,
            alpha=0.6,
            label=f"{label} ({mask.sum()})",
        )
    ax.legend(markerscale=4, fontsize="small")
    ax.set_title("Passage Embeddings — Color by Plot Function")
    ax.set_xlabel("UMAP 1")
    ax.set_ylabel("UMAP 2")
    fig.tight_layout()
    fig.savefig(output_path, dpi=DPI)
    plt.close(fig)
    logger.info("Saved plot function plot to %s", output_path)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    load_dotenv()

    REPORTS_DIR.mkdir(exist_ok=True)
    timestamp = make_timestamp()

    # Load data from LanceDB
    logger.info("Connecting to LanceDB at %s", DB_PATH)
    table = load_data(DB_PATH)
    df = table.to_pandas()
    logger.info("Loaded %d passages", len(df))

    # Extract columns
    vectors: np.ndarray = np.stack(df["vector"].to_list())
    chapter_ids: list[str] = df["chapter_id"].tolist()
    narrators: list[str] = df["narrator"].tolist()
    interest_scores: list[int] = df["interest_score"].tolist()

    has_plot_function = "plot_function" in df.columns
    plot_functions: list[str] = df["plot_function"].tolist() if has_plot_function else []

    # Print stats
    logger.info("--- Stats ---")
    logger.info("  Passages: %d", len(df))
    logger.info("  Vector dim: %d", vectors.shape[1])
    logger.info("  Chapters: %d", len(set(chapter_ids)))
    logger.info("  Narrators: %s", dict(df["narrator"].value_counts()))
    logger.info("  Interest score range: %d–%d", min(interest_scores), max(interest_scores))
    if has_plot_function:
        logger.info("  Plot functions: %s", dict(df["plot_function"].value_counts()))
    else:
        logger.info("  plot_function column not present in table")

    # UMAP projection
    logger.info(
        "Running UMAP (n_neighbors=%d, min_dist=%s, metric=%s)",
        UMAP_N_NEIGHBORS,
        UMAP_MIN_DIST,
        UMAP_METRIC,
    )
    reducer = umap.UMAP(
        n_neighbors=UMAP_N_NEIGHBORS,
        min_dist=UMAP_MIN_DIST,
        metric=UMAP_METRIC,
        random_state=UMAP_RANDOM_STATE,
        n_components=2,
    )
    coords = reducer.fit_transform(vectors)
    logger.info("UMAP projection complete: shape %s", coords.shape)

    # Generate plots
    plot_by_chapter(
        coords,
        chapter_ids,
        REPORTS_DIR / f"embeddings_by_chapter_{timestamp}.png",
    )
    plot_by_narrator(
        coords,
        narrators,
        REPORTS_DIR / f"embeddings_by_narrator_{timestamp}.png",
    )
    plot_by_interest(
        coords,
        interest_scores,
        REPORTS_DIR / f"embeddings_by_interest_{timestamp}.png",
    )
    if has_plot_function:
        plot_by_plot_function(
            coords,
            plot_functions,
            REPORTS_DIR / f"embeddings_by_plot_function_{timestamp}.png",
        )

    logger.info("All plots saved to %s/", REPORTS_DIR)


if __name__ == "__main__":
    main()
