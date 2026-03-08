"""Experiment 5: Embedding Input Ablation Study.

Tests how different embedding input compositions affect retrieval precision.
Creates 3 additional LanceDB tables with different embedding inputs and
compares retrieval performance across all 4 variants using the same 30
probe queries from Experiment 3.

Variants:
  (a) text_only        — just the passage text
  (b) context_text     — context + text (no metadata)
  (c) all_metadata     — context + text + characters/themes/summary (existing `passages` table)
  (d) selected_meta    — context + text + characters/themes/summary + prov_* descriptions

Usage:
    uv run python -m enrichment.experiment_ablation [--rebuild]
"""

import argparse
import json
import logging
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import lancedb  # pyright: ignore[reportMissingImports]
import numpy as np
from dotenv import load_dotenv

from enrichment.experiment_retrieval_precision import (  # pyright: ignore[reportMissingImports]
    PROBE_QUERIES,
    compute_precision,
    load_enrichment_lookup,
)
from enrichment.retrieval_schema import ContextualPassage  # pyright: ignore[reportMissingImports]

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
REPORTS_DIR = Path("reports")
DB_PATH = DATA_DIR / "bleak_house_vectors"
CONTEXTUAL_PATH = DATA_DIR / "passages_contextual.json"
ENRICHED_PATH = DATA_DIR / "passages_enriched.json"
OUTPUT_PATH = DATA_DIR / "experiment_ablation.json"

BATCH_SIZE = 500
K_VALUES = [10, 20]

# Variant definitions: name -> (table_name, description)
VARIANTS: dict[str, tuple[str, str]] = {
    "text_only": ("passages_text_only", "text only"),
    "context_text": ("passages_context_text", "context + text"),
    "all_metadata": ("passages", "context + text + all metadata (existing)"),
    "selected_meta": ("passages_selected_meta", "context + text + selected metadata + prov descriptions"),
}

# Tables that this script creates (excludes the existing `passages` table)
TABLES_TO_CREATE = ["passages_text_only", "passages_context_text", "passages_selected_meta"]


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


# ---------------------------------------------------------------------------
# Embedding input builders
# ---------------------------------------------------------------------------


def build_embedding_text_only(passage: dict) -> str:
    """Variant (a): just the passage text."""
    return passage.get("text", "")


def build_embedding_context_text(passage: dict) -> str:
    """Variant (b): context + text."""
    context = passage.get("context", "")
    text = passage.get("text", "")
    parts = []
    if context:
        parts.append(context)
    parts.append(text)
    return "\n\n".join(parts)


def build_embedding_selected_meta(passage: dict) -> str:
    """Variant (d): context + text + characters/themes/summary + prov descriptions."""
    enrichment = passage.get("enrichment") or {}
    context = passage.get("context", "")
    text = passage.get("text", "")
    characters = ", ".join(enrichment.get("characters_present", []))
    themes = ", ".join(enrichment.get("themes", []))
    summary = enrichment.get("summary", "")

    parts = []
    if context:
        parts.append(context)
    parts.append(text)
    if characters:
        parts.append(f"Characters: {characters}")
    if themes:
        parts.append(f"Themes: {themes}")
    if summary:
        parts.append(f"Summary: {summary}")

    # Add textual descriptions of prov_* fields
    prov_fields = [
        ("Character development", "prov_character_development"),
        ("Plot advancement", "prov_plot_advancement"),
        ("Thematic depth", "prov_thematic_depth"),
        ("Social critique", "prov_social_critique"),
        ("Humor/entertainment", "prov_humor_entertainment"),
        ("Atmosphere/setting", "prov_atmosphere_setting"),
        ("Narrative technique", "prov_narrative_technique"),
    ]
    prov_parts = []
    for label, field in prov_fields:
        value = enrichment.get(field, "none")
        prov_parts.append(f"{label}: {value}")
    parts.append(". ".join(prov_parts) + ".")

    return "\n\n".join(parts)


EMBEDDING_BUILDERS: dict[str, callable] = {  # type: ignore[type-arg]
    "passages_text_only": build_embedding_text_only,
    "passages_context_text": build_embedding_context_text,
    "passages_selected_meta": build_embedding_selected_meta,
}


# ---------------------------------------------------------------------------
# Record building
# ---------------------------------------------------------------------------


def passage_to_record(passage: dict, embedding_input: str) -> dict:
    """Convert a passage dict to a ContextualPassage-compatible record."""
    enrichment = passage.get("enrichment") or {}
    return {
        "passage_id": passage["passage_id"],
        "chapter_id": passage["chapter_id"],
        "chapter_title": passage.get("chapter_title", ""),
        "paragraph_index": passage["paragraph_index"],
        "narrator": enrichment.get("narrator", "unknown"),
        "interest_score": enrichment.get("interest_score", 0),
        "themes": ", ".join(enrichment.get("themes", [])),
        "characters": ", ".join(enrichment.get("characters_present", [])),
        "summary": enrichment.get("summary", ""),
        "text": passage.get("text", ""),
        "context": passage.get("context", ""),
        "embedding_input": embedding_input,
    }


# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------


def create_variant_tables(
    db: lancedb.DBConnection,  # type: ignore[name-defined]
    passages: list[dict],
    rebuild: bool,
) -> None:
    """Create the 3 new variant tables in LanceDB."""
    existing_tables = set(db.table_names())

    for table_name in TABLES_TO_CREATE:
        if table_name in existing_tables and not rebuild:
            logger.info("Table '%s' already exists, skipping (use --rebuild to recreate)", table_name)
            continue

        if table_name in existing_tables and rebuild:
            logger.info("Dropping existing table '%s' for rebuild", table_name)
            db.drop_table(table_name)

        builder = EMBEDDING_BUILDERS[table_name]
        logger.info("Creating table '%s' with %d passages", table_name, len(passages))

        records = [
            passage_to_record(p, builder(p))
            for p in passages
        ]

        table = db.create_table(table_name, schema=ContextualPassage)

        for start in range(0, len(records), BATCH_SIZE):
            batch = records[start : start + BATCH_SIZE]
            table.add(batch)
            logger.info(
                "  Embedded batch %d-%d (%d records)",
                start,
                start + len(batch),
                len(batch),
            )

        logger.info("Table '%s' created with %d records", table_name, len(records))


# ---------------------------------------------------------------------------
# Diversity metrics
# ---------------------------------------------------------------------------


def compute_chapter_spread(result_ids: list[str], passage_lookup: dict[str, dict]) -> int:
    """Count unique chapters in the result set."""
    chapters = set()
    for pid in result_ids:
        p = passage_lookup.get(pid)
        if p:
            chapters.add(p.get("chapter_id", ""))
    return len(chapters)


def compute_narrator_balance(result_ids: list[str], enrichment_lookup: dict[str, dict]) -> dict[str, float]:
    """Compute fraction of results from each narrator."""
    if not result_ids:
        return {}
    counts: dict[str, int] = defaultdict(int)
    for pid in result_ids:
        enr = enrichment_lookup.get(pid, {})
        narrator = enr.get("narrator", "unknown")
        counts[narrator] += 1
    total = len(result_ids)
    return {narrator: round(count / total, 4) for narrator, count in sorted(counts.items())}


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def vector_search(
    table: lancedb.table.Table,  # type: ignore[name-defined]
    query: str,
    k: int,
) -> list[str]:
    """Pure vector search, return top-k passage_ids."""
    results = table.search(query, query_type="vector").limit(k).to_pandas()
    return results["passage_id"].tolist()


# ---------------------------------------------------------------------------
# Main experiment
# ---------------------------------------------------------------------------


def run_experiment(
    db: lancedb.DBConnection,  # type: ignore[name-defined]
    enrichment_lookup: dict[str, dict],
    passage_lookup: dict[str, dict],
) -> dict:
    """Run all probe queries against all variants at all k values."""
    # Open all variant tables
    tables: dict[str, lancedb.table.Table] = {}  # type: ignore[name-defined]
    for variant_name, (table_name, _) in VARIANTS.items():
        tables[variant_name] = db.open_table(table_name)
        logger.info("Opened table '%s' for variant '%s'", table_name, variant_name)

    variant_names = list(VARIANTS.keys())

    results: dict = {
        "variants": {vn: VARIANTS[vn][1] for vn in variant_names},
        "queries": [],
        "summary": {},
    }

    # Accumulators: variant -> k -> list of precisions
    precision_accum: dict[str, dict[int, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    # Diversity accumulators: variant -> k -> chapter_spreads, narrator_balances
    chapter_spread_accum: dict[str, dict[int, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    narrator_balance_accum: dict[str, dict[int, list[dict[str, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for qi, probe in enumerate(PROBE_QUERIES):
        logger.info(
            "Query %d/%d: %s",
            qi + 1,
            len(PROBE_QUERIES),
            probe.query[:60],
        )

        query_result: dict = {
            "query": probe.query,
            "description": probe.description,
            "expected": {
                k: v if not isinstance(v, list) else v
                for k, v in probe.expected.items()
            },
            "variants": {},
        }

        for k in K_VALUES:
            k_results: dict[str, dict] = {}

            for variant_name in variant_names:
                table = tables[variant_name]
                pids = vector_search(table, probe.query, k)
                prec = compute_precision(pids, probe.expected, enrichment_lookup)
                chapter_spread = compute_chapter_spread(pids, passage_lookup)
                narrator_bal = compute_narrator_balance(pids, enrichment_lookup)

                k_results[variant_name] = {
                    "precision": round(prec, 4),
                    "n_results": len(pids),
                    "chapter_spread": chapter_spread,
                    "narrator_balance": narrator_bal,
                    "passage_ids": pids,
                }

                precision_accum[variant_name][k].append(prec)
                chapter_spread_accum[variant_name][k].append(chapter_spread)
                narrator_balance_accum[variant_name][k].append(narrator_bal)

            log_parts = [f"{vn}={k_results[vn]['precision']:.2f}" for vn in variant_names]
            logger.info("  k=%d  %s", k, "  ".join(log_parts))

            query_result["variants"][f"k={k}"] = k_results

        results["queries"].append(query_result)

    # Compute summary
    summary: dict[str, dict] = {}
    for variant_name in variant_names:
        variant_summary: dict = {}
        for k in K_VALUES:
            prec_vals = precision_accum[variant_name][k]
            spread_vals = chapter_spread_accum[variant_name][k]
            mean_prec = float(np.mean(prec_vals)) if prec_vals else 0.0
            mean_spread = float(np.mean(spread_vals)) if spread_vals else 0.0
            variant_summary[f"k={k}"] = {
                "mean_precision": round(mean_prec, 4),
                "mean_chapter_spread": round(mean_spread, 2),
            }
        summary[variant_name] = variant_summary
    results["summary"] = summary

    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def write_report(results: dict, tag: str) -> Path:
    """Write a human-readable summary report."""
    REPORTS_DIR.mkdir(exist_ok=True)
    report_path = REPORTS_DIR / f"ablation_{tag}.txt"

    variant_names = list(results["variants"].keys())

    lines: list[str] = []
    lines.append("=" * 90)
    lines.append("Experiment 5: Embedding Input Ablation Study")
    lines.append(f"Tag: {tag}")
    lines.append(f"Probe queries: {len(PROBE_QUERIES)}")
    lines.append(f"k values: {K_VALUES}")
    lines.append("=" * 90)
    lines.append("")

    # Variant descriptions
    lines.append("VARIANTS:")
    for vn in variant_names:
        lines.append(f"  {vn:<20} {results['variants'][vn]}")
    lines.append("")

    # Summary table: precision
    lines.append("SUMMARY: Mean Precision by Variant")
    lines.append("-" * 60)
    header = f"{'Variant':<20}"
    for k in K_VALUES:
        header += f"  {'k=' + str(k):>10}"
    lines.append(header)
    lines.append("-" * 60)

    summary = results["summary"]
    for vn in variant_names:
        row = f"{vn:<20}"
        for k in K_VALUES:
            val = summary[vn][f"k={k}"]["mean_precision"]
            row += f"  {val:>10.4f}"
        lines.append(row)
    lines.append("-" * 60)
    lines.append("")

    # Summary table: chapter spread
    lines.append("SUMMARY: Mean Chapter Spread by Variant")
    lines.append("-" * 60)
    header = f"{'Variant':<20}"
    for k in K_VALUES:
        header += f"  {'k=' + str(k):>10}"
    lines.append(header)
    lines.append("-" * 60)

    for vn in variant_names:
        row = f"{vn:<20}"
        for k in K_VALUES:
            val = summary[vn][f"k={k}"]["mean_chapter_spread"]
            row += f"  {val:>10.2f}"
        lines.append(row)
    lines.append("-" * 60)
    lines.append("")

    # Per-query breakdown
    lines.append("PER-QUERY BREAKDOWN")
    lines.append("=" * 90)
    for qi, qr in enumerate(results["queries"]):
        lines.append(f"\n[{qi + 1}] {qr['query']}")
        lines.append(f"    Description: {qr['description']}")
        lines.append(f"    Expected: {qr['expected']}")
        for k_label, variants_data in qr["variants"].items():
            parts = []
            for vn in variant_names:
                v = variants_data[vn]
                parts.append(f"{vn}={v['precision']:.2f}(spread={v['chapter_spread']})")
            lines.append(f"    {k_label}: {', '.join(parts)}")

    lines.append("")
    lines.append("=" * 90)

    report_text = "\n".join(lines) + "\n"
    report_path.write_text(report_text)
    return report_path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Experiment 5: Embedding Input Ablation Study"
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Force recreation of variant tables even if they already exist",
    )
    args = parser.parse_args()

    load_dotenv()

    tag = f"{make_timestamp()}_{git_short_hash()}"
    logger.info("Experiment 5: Embedding Input Ablation Study")
    logger.info("Tag: %s", tag)

    # Load contextual passages (source for table creation)
    logger.info("Loading contextual passages from %s", CONTEXTUAL_PATH)
    contextual_raw = json.loads(CONTEXTUAL_PATH.read_text())
    passages = [p for p in contextual_raw if p.get("enrichment") and p.get("context")]
    logger.info("%d passages with enrichment + context", len(passages))

    # Load enrichment lookup (for precision checking)
    logger.info("Loading enrichment data from %s", ENRICHED_PATH)
    enrichment_lookup = load_enrichment_lookup(ENRICHED_PATH)
    logger.info("Enrichment lookup: %d passages", len(enrichment_lookup))

    # Build passage_lookup for diversity metrics (passage_id -> passage dict)
    passage_lookup: dict[str, dict] = {}
    for p in contextual_raw:
        passage_lookup[p["passage_id"]] = p

    # Connect to LanceDB
    logger.info("Connecting to LanceDB at %s", DB_PATH)
    db = lancedb.connect(str(DB_PATH))

    # Create variant tables
    create_variant_tables(db, passages, rebuild=args.rebuild)

    # Run experiment
    results = run_experiment(db, enrichment_lookup, passage_lookup)

    # Save JSON results
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(results, indent=2))
    logger.info("Saved results to %s", OUTPUT_PATH)

    # Save human-readable report
    report_path = write_report(results, tag)
    logger.info("Saved report to %s", report_path)

    # Print summary
    logger.info("\n--- Summary: Mean Precision ---")
    variant_names = list(VARIANTS.keys())
    for vn in variant_names:
        vals = results["summary"][vn]
        parts = [f"{kl}: prec={v['mean_precision']:.4f} spread={v['mean_chapter_spread']:.1f}" for kl, v in vals.items()]
        logger.info("  %-20s %s", vn, "  ".join(parts))

    logger.info("\nDone.")


if __name__ == "__main__":
    main()
