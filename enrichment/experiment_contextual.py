"""Experiment 4: Contextual Retrieval Validation.

Tests whether prepending LLM-generated situating context before embedding
improves retrieval for the Bleak House corpus. Compares vector search across
3 pre-existing LanceDB tables:
  (a) passages_text_only    — text only (no context)
  (b) passages_context_text — context + text (no metadata)
  (c) passages              — context + text + all metadata (reference)

For each of the 30 probe queries, measures:
  - Precision against enrichment fields (same as Experiment 3)
  - Chapter diversity: unique chapters in top-k
  - Chapter novelty: chapters surfaced by context variants but NOT text-only
  - Narrator diversity: unique narrators in top-k

Usage:
    uv run python -m enrichment.experiment_contextual
"""

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

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
REPORTS_DIR = Path("reports")
DB_PATH = DATA_DIR / "bleak_house_vectors"
ENRICHED_PATH = DATA_DIR / "passages_enriched.json"
CONTEXTUAL_PATH = DATA_DIR / "passages_contextual.json"
OUTPUT_PATH = DATA_DIR / "experiment_contextual.json"

K_VALUES = [10, 20]

# Variant definitions: name -> (table_name, description)
VARIANTS: dict[str, tuple[str, str]] = {
    "text_only": ("passages_text_only", "text only (no context)"),
    "context_text": ("passages_context_text", "context + text (no metadata)"),
    "all_metadata": ("passages", "context + text + all metadata (reference)"),
}


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
# Diversity and novelty metrics
# ---------------------------------------------------------------------------


def get_chapters_for_ids(
    result_ids: list[str],
    passage_lookup: dict[str, dict],
) -> set[str]:
    """Return set of unique chapter_ids for the given passage_ids."""
    chapters: set[str] = set()
    for pid in result_ids:
        p = passage_lookup.get(pid)
        if p:
            chapters.add(p.get("chapter_id", ""))
    return chapters


def compute_chapter_diversity(
    result_ids: list[str],
    passage_lookup: dict[str, dict],
) -> int:
    """Count unique chapters in the result set."""
    return len(get_chapters_for_ids(result_ids, passage_lookup))


def compute_narrator_diversity(
    result_ids: list[str],
    enrichment_lookup: dict[str, dict],
) -> int:
    """Count unique narrators in the result set."""
    narrators: set[str] = set()
    for pid in result_ids:
        enr = enrichment_lookup.get(pid, {})
        narrators.add(enr.get("narrator", "unknown"))
    return len(narrators)


def compute_chapter_novelty(
    text_only_chapters: set[str],
    context_chapters: set[str],
) -> int:
    """Count chapters in context results that do NOT appear in text-only results.

    This measures whether context surfaces passages from non-obvious chapters
    that text-only retrieval misses.
    """
    return len(context_chapters - text_only_chapters)


# ---------------------------------------------------------------------------
# Main experiment
# ---------------------------------------------------------------------------


def run_experiment(
    db: lancedb.DBConnection,  # type: ignore[name-defined]
    enrichment_lookup: dict[str, dict],
    passage_lookup: dict[str, dict],
) -> dict:
    """Run all probe queries against all 3 variants at all k values."""
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

    # Accumulators per variant -> k
    precision_accum: dict[str, dict[int, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    chapter_div_accum: dict[str, dict[int, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    narrator_div_accum: dict[str, dict[int, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    # Chapter novelty: context variant -> k -> list of novelty counts
    chapter_novelty_accum: dict[str, dict[int, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    # Per-query precision deltas: k -> list of (context_text - text_only)
    precision_delta_accum: dict[int, list[tuple[str, float]]] = defaultdict(list)

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

            # Collect chapter sets per variant for novelty computation
            chapter_sets: dict[str, set[str]] = {}

            for variant_name in variant_names:
                table = tables[variant_name]
                pids = vector_search(table, probe.query, k)
                prec = compute_precision(pids, probe.expected, enrichment_lookup)
                ch_div = compute_chapter_diversity(pids, passage_lookup)
                nr_div = compute_narrator_diversity(pids, enrichment_lookup)
                chapters = get_chapters_for_ids(pids, passage_lookup)
                chapter_sets[variant_name] = chapters

                k_results[variant_name] = {
                    "precision": round(prec, 4),
                    "n_results": len(pids),
                    "chapter_diversity": ch_div,
                    "narrator_diversity": nr_div,
                    "passage_ids": pids,
                }

                precision_accum[variant_name][k].append(prec)
                chapter_div_accum[variant_name][k].append(ch_div)
                narrator_div_accum[variant_name][k].append(nr_div)

            # Compute chapter novelty: chapters in context variants but not text-only
            text_only_chapters = chapter_sets["text_only"]
            for ctx_variant in ["context_text", "all_metadata"]:
                novelty = compute_chapter_novelty(
                    text_only_chapters, chapter_sets[ctx_variant]
                )
                k_results[ctx_variant]["chapter_novelty"] = novelty
                chapter_novelty_accum[ctx_variant][k].append(novelty)

            k_results["text_only"]["chapter_novelty"] = 0  # baseline, always 0

            # Track precision delta (context_text vs text_only) for per-query analysis
            delta = (
                k_results["context_text"]["precision"]
                - k_results["text_only"]["precision"]
            )
            precision_delta_accum[k].append((probe.query, delta))

            log_parts = [
                f"{vn}={k_results[vn]['precision']:.2f}" for vn in variant_names
            ]
            logger.info("  k=%d  %s", k, "  ".join(log_parts))

            query_result["variants"][f"k={k}"] = k_results

        results["queries"].append(query_result)

    # ---------------------------------------------------------------------------
    # Compute summary statistics
    # ---------------------------------------------------------------------------

    summary: dict[str, dict] = {}
    for variant_name in variant_names:
        variant_summary: dict = {}
        for k in K_VALUES:
            prec_vals = precision_accum[variant_name][k]
            ch_vals = chapter_div_accum[variant_name][k]
            nr_vals = narrator_div_accum[variant_name][k]
            mean_prec = float(np.mean(prec_vals)) if prec_vals else 0.0
            mean_ch = float(np.mean(ch_vals)) if ch_vals else 0.0
            mean_nr = float(np.mean(nr_vals)) if nr_vals else 0.0
            variant_summary[f"k={k}"] = {
                "mean_precision": round(mean_prec, 4),
                "mean_chapter_diversity": round(mean_ch, 2),
                "mean_narrator_diversity": round(mean_nr, 2),
            }
        # Chapter novelty only applies to context variants
        if variant_name in chapter_novelty_accum:
            for k in K_VALUES:
                nov_vals = chapter_novelty_accum[variant_name][k]
                mean_nov = float(np.mean(nov_vals)) if nov_vals else 0.0
                variant_summary[f"k={k}"]["mean_chapter_novelty"] = round(mean_nov, 2)
        summary[variant_name] = variant_summary
    results["summary"] = summary

    # Per-query delta analysis: best and worst context impact
    delta_analysis: dict[str, dict] = {}
    for k in K_VALUES:
        deltas = precision_delta_accum[k]
        deltas_sorted = sorted(deltas, key=lambda x: x[1], reverse=True)
        # Queries where context helps most (top 5)
        context_helps = [
            {"query": q, "delta": round(d, 4)} for q, d in deltas_sorted[:5] if d > 0
        ]
        # Queries where context hurts (bottom 5 with negative delta)
        context_hurts = [
            {"query": q, "delta": round(d, 4)}
            for q, d in reversed(deltas_sorted)
            if d < 0
        ][:5]
        mean_delta = float(np.mean([d for _, d in deltas]))
        pct_improved = sum(1 for _, d in deltas if d > 0) / len(deltas) * 100
        pct_degraded = sum(1 for _, d in deltas if d < 0) / len(deltas) * 100
        pct_unchanged = sum(1 for _, d in deltas if d == 0) / len(deltas) * 100

        # Relative improvement: mean precision change as % of text-only baseline
        text_only_mean = summary["text_only"][f"k={k}"]["mean_precision"]
        relative_improvement_pct = (
            round(mean_delta / text_only_mean * 100, 1) if text_only_mean > 0 else 0.0
        )

        delta_analysis[f"k={k}"] = {
            "mean_delta": round(mean_delta, 4),
            "relative_improvement_pct": relative_improvement_pct,
            "pct_queries_improved": round(pct_improved, 1),
            "pct_queries_degraded": round(pct_degraded, 1),
            "pct_queries_unchanged": round(pct_unchanged, 1),
            "context_helps_most": context_helps,
            "context_hurts_most": context_hurts,
        }
    results["delta_analysis"] = delta_analysis

    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def write_report(results: dict, tag: str) -> Path:
    """Write a human-readable summary report."""
    REPORTS_DIR.mkdir(exist_ok=True)
    report_path = REPORTS_DIR / f"contextual_retrieval_{tag}.txt"

    variant_names = list(results["variants"].keys())
    summary = results["summary"]
    delta_analysis = results["delta_analysis"]

    lines: list[str] = []
    lines.append("=" * 90)
    lines.append("Experiment 4: Contextual Retrieval Validation")
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

    # ---------------------------------------------------------------------------
    # Head-to-head: precision
    # ---------------------------------------------------------------------------

    lines.append("HEAD-TO-HEAD: Mean Precision (text_only vs context_text)")
    lines.append("-" * 70)
    header = f"{'Variant':<20}"
    for k in K_VALUES:
        header += f"  {'k=' + str(k):>12}"
    lines.append(header)
    lines.append("-" * 70)

    for vn in variant_names:
        row = f"{vn:<20}"
        for k in K_VALUES:
            val = summary[vn][f"k={k}"]["mean_precision"]
            row += f"  {val:>12.4f}"
        lines.append(row)
    lines.append("-" * 70)
    lines.append("")

    # Precision delta summary
    lines.append("CONTEXT IMPACT: context_text vs text_only precision delta")
    lines.append("-" * 70)
    for k in K_VALUES:
        da = delta_analysis[f"k={k}"]
        lines.append(f"  k={k}:")
        lines.append(f"    Mean absolute delta:      {da['mean_delta']:+.4f}")
        lines.append(f"    Relative improvement:     {da['relative_improvement_pct']:+.1f}%")
        lines.append(f"    Queries improved:         {da['pct_queries_improved']:.1f}%")
        lines.append(f"    Queries degraded:         {da['pct_queries_degraded']:.1f}%")
        lines.append(f"    Queries unchanged:        {da['pct_queries_unchanged']:.1f}%")
    lines.append("")

    # Anthropic claim assessment
    lines.append("ANTHROPIC CLAIM ASSESSMENT (35-67% improvement on generic corpora)")
    lines.append("-" * 70)
    for k in K_VALUES:
        da = delta_analysis[f"k={k}"]
        rel = da["relative_improvement_pct"]
        if rel >= 35:
            verdict = "WITHIN claimed range"
        elif rel > 0:
            verdict = "BELOW claimed range (improvement exists but smaller)"
        elif rel == 0:
            verdict = "NO EFFECT"
        else:
            verdict = "NEGATIVE (context hurts)"
        lines.append(f"  k={k}: {rel:+.1f}% relative improvement -> {verdict}")
    lines.append("")

    # ---------------------------------------------------------------------------
    # Queries where context helps most / hurts most
    # ---------------------------------------------------------------------------

    lines.append("QUERIES WHERE CONTEXT HELPS MOST (biggest precision gain)")
    lines.append("-" * 70)
    for k in K_VALUES:
        da = delta_analysis[f"k={k}"]
        lines.append(f"  k={k}:")
        for item in da["context_helps_most"]:
            lines.append(f"    {item['delta']:+.4f}  {item['query']}")
        if not da["context_helps_most"]:
            lines.append("    (none)")
    lines.append("")

    lines.append("QUERIES WHERE CONTEXT HURTS (precision drops)")
    lines.append("-" * 70)
    for k in K_VALUES:
        da = delta_analysis[f"k={k}"]
        lines.append(f"  k={k}:")
        for item in da["context_hurts_most"]:
            lines.append(f"    {item['delta']:+.4f}  {item['query']}")
        if not da["context_hurts_most"]:
            lines.append("    (none)")
    lines.append("")

    # ---------------------------------------------------------------------------
    # Chapter diversity
    # ---------------------------------------------------------------------------

    lines.append("CHAPTER DIVERSITY: Mean Unique Chapters in Top-k")
    lines.append("-" * 70)
    header = f"{'Variant':<20}"
    for k in K_VALUES:
        header += f"  {'k=' + str(k):>12}"
    lines.append(header)
    lines.append("-" * 70)

    for vn in variant_names:
        row = f"{vn:<20}"
        for k in K_VALUES:
            val = summary[vn][f"k={k}"]["mean_chapter_diversity"]
            row += f"  {val:>12.2f}"
        lines.append(row)
    lines.append("-" * 70)
    lines.append("")

    # ---------------------------------------------------------------------------
    # Chapter novelty
    # ---------------------------------------------------------------------------

    lines.append("CHAPTER NOVELTY: Mean New Chapters Surfaced (vs text_only)")
    lines.append("-" * 70)
    header = f"{'Variant':<20}"
    for k in K_VALUES:
        header += f"  {'k=' + str(k):>12}"
    lines.append(header)
    lines.append("-" * 70)

    for vn in ["context_text", "all_metadata"]:
        row = f"{vn:<20}"
        for k in K_VALUES:
            val = summary[vn][f"k={k}"].get("mean_chapter_novelty", 0.0)
            row += f"  {val:>12.2f}"
        lines.append(row)
    lines.append("-" * 70)
    lines.append("")

    # ---------------------------------------------------------------------------
    # Narrator diversity
    # ---------------------------------------------------------------------------

    lines.append("NARRATOR DIVERSITY: Mean Unique Narrators in Top-k")
    lines.append("-" * 70)
    header = f"{'Variant':<20}"
    for k in K_VALUES:
        header += f"  {'k=' + str(k):>12}"
    lines.append(header)
    lines.append("-" * 70)

    for vn in variant_names:
        row = f"{vn:<20}"
        for k in K_VALUES:
            val = summary[vn][f"k={k}"]["mean_narrator_diversity"]
            row += f"  {val:>12.2f}"
        lines.append(row)
    lines.append("-" * 70)
    lines.append("")

    # ---------------------------------------------------------------------------
    # Per-query breakdown
    # ---------------------------------------------------------------------------

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
                novelty_str = ""
                if vn != "text_only":
                    novelty_str = f",nov={v.get('chapter_novelty', 0)}"
                parts.append(
                    f"{vn}={v['precision']:.2f}"
                    f"(ch={v['chapter_diversity']},nr={v['narrator_diversity']}"
                    f"{novelty_str})"
                )
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

    load_dotenv()

    tag = f"{make_timestamp()}_{git_short_hash()}"
    logger.info("Experiment 4: Contextual Retrieval Validation")
    logger.info("Tag: %s", tag)

    # Load enrichment lookup (for precision checking)
    logger.info("Loading enrichment data from %s", ENRICHED_PATH)
    enrichment_lookup = load_enrichment_lookup(ENRICHED_PATH)
    logger.info("Enrichment lookup: %d passages", len(enrichment_lookup))

    # Build passage_lookup for diversity metrics (passage_id -> passage dict)
    logger.info("Loading contextual passages from %s", CONTEXTUAL_PATH)
    contextual_raw = json.loads(CONTEXTUAL_PATH.read_text())
    passage_lookup: dict[str, dict] = {}
    for p in contextual_raw:
        passage_lookup[p["passage_id"]] = p
    logger.info("Passage lookup: %d passages", len(passage_lookup))

    # Connect to LanceDB
    logger.info("Connecting to LanceDB at %s", DB_PATH)
    db = lancedb.connect(str(DB_PATH))

    # Verify required tables exist
    existing_tables = set(db.table_names())
    required_tables = [table_name for _, (table_name, _) in VARIANTS.items()]
    for table_name in required_tables:
        if table_name not in existing_tables:
            logger.error(
                "Required table '%s' not found in LanceDB. "
                "Run experiment_ablation first to create variant tables.",
                table_name,
            )
            raise SystemExit(1)

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
        parts = [
            f"{kl}: prec={v['mean_precision']:.4f} "
            f"ch_div={v['mean_chapter_diversity']:.1f} "
            f"nr_div={v['mean_narrator_diversity']:.1f}"
            for kl, v in vals.items()
        ]
        logger.info("  %-20s %s", vn, "  ".join(parts))

    logger.info("\n--- Context Impact ---")
    for k in K_VALUES:
        da = results["delta_analysis"][f"k={k}"]
        logger.info(
            "  k=%d: mean_delta=%+.4f  relative=%+.1f%%  improved=%.0f%%  degraded=%.0f%%",
            k,
            da["mean_delta"],
            da["relative_improvement_pct"],
            da["pct_queries_improved"],
            da["pct_queries_degraded"],
        )

    logger.info("\nDone.")


if __name__ == "__main__":
    main()
