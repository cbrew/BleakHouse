"""Experiment H5: Quote verification rates across grounding conditions.

H5 claims: "Any form of passage grounding (transport, embedding, random,
plain RAG) achieves > 90% quote verification, while ungrounded generation
drops below 50%."

This script measures quote verification rates across all existing runs for
5 novels and 5+ pipeline types, using both Panel A (v01_baseline) and
Panel B (v19_all_swapped).

Verification method: fuzzy 5-word subsequence matching against source text,
replicating the logic in enrichment/compute_metrics.py.

Usage:
    uv run python -m enrichment.experiment_h5_grounding [--runs-dir data/runs]
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

RUNS_DIR = Path("data/runs")
REPORTS_DIR = Path("reports")

# ---------------------------------------------------------------------------
# Novel source text
# ---------------------------------------------------------------------------

NOVEL_LABELS = {
    "bleak_house": "Bleak House",
    "mill_on_the_floss": "Mill on the Floss",
    "north_and_south": "North and South",
    "our_mutual_friend": "Our Mutual Friend",
    "passage_to_india": "A Passage to India",
}

CONDITION_LABELS = {
    "ext": "transport",
    "trn": "transport(trn)",
    "emb": "embedding",
    "rag": "RAG",
    "rand": "random",
    "nop": "no-passages",
    "hia": "hierarchical",
    "arc": "arc",
}

# Grounded conditions for H5 analysis
GROUNDED = {"ext", "trn", "emb", "rag", "rand", "hia"}
UNGROUNDED = {"nop"}


def load_source_text(novel: str, runs_dir: Path) -> str:
    """Load concatenated passage text for fuzzy matching.

    BH: data/passages_enriched.json
    Others: data/novels/<key>/passages_enriched.json
    Fallback: collect from phase1_assignments.json across runs.
    """
    if novel == "bleak_house":
        path = Path("data/passages_enriched.json")
        if path.exists():
            passages = json.loads(path.read_text())
            return " ".join(p.get("text", "") for p in passages).lower()

    # Cross-novel enriched passages
    novel_path = Path("data/novels") / novel / "passages_enriched.json"
    if novel_path.exists():
        passages = json.loads(novel_path.read_text())
        return " ".join(p.get("text", "") for p in passages).lower()

    # Fallback: collect from phase1 assignments
    texts: set[str] = set()
    for rd in runs_dir.iterdir():
        if not rd.is_dir():
            continue
        rn, _, _ = classify_run(rd.name)
        if rn != novel:
            continue
        p1_path = rd / "phase1_assignments.json"
        if not p1_path.exists():
            continue
        try:
            p1 = json.loads(p1_path.read_text())
            for a in p1.get("assignments", []):
                t = a.get("text", "")
                if t:
                    texts.add(t)
        except (json.JSONDecodeError, OSError):
            continue
    return " ".join(texts).lower()


# ---------------------------------------------------------------------------
# Run classification (mirrors compute_metrics.py)
# ---------------------------------------------------------------------------

def classify_run(name: str) -> tuple[str, str, str]:
    """Return (novel, condition, panel_id) from run name."""
    for prefix, novel in [
        ("motf_trn_", "mill_on_the_floss"), ("motf_emb_", "mill_on_the_floss"),
        ("motf_nop_", "mill_on_the_floss"), ("motf_ext_", "mill_on_the_floss"),
        ("motf_hia_", "mill_on_the_floss"),
        ("nas_trn_", "north_and_south"), ("nas_emb_", "north_and_south"),
        ("nas_nop_", "north_and_south"), ("nas_ext_", "north_and_south"),
        ("nas_hia_", "north_and_south"),
        ("omf_trn_", "our_mutual_friend"), ("omf_emb_", "our_mutual_friend"),
        ("omf_nop_", "our_mutual_friend"), ("omf_ext_", "our_mutual_friend"),
        ("omf_hia_", "our_mutual_friend"),
        ("pti_trn_", "passage_to_india"), ("pti_emb_", "passage_to_india"),
        ("pti_nop_", "passage_to_india"), ("pti_ext_", "passage_to_india"),
        ("pti_hia_", "passage_to_india"),
    ]:
        if name.startswith(prefix):
            rest = name[len(prefix):]
            cond = prefix.split("_")[1]
            return novel, cond, rest

    for prefix, cond in [
        ("arc_", "arc"), ("hia_", "hia"), ("emb_", "emb"), ("nop_", "nop"),
        ("rag_", "rag"), ("rand_", "rand"), ("ext_", "ext"),
    ]:
        if name.startswith(prefix):
            return "bleak_house", cond, name[len(prefix):]

    return "unknown", "unknown", name


def classify_panel(panel_id: str) -> str:
    """Classify panel_id into Panel A or Panel B.

    Panel A (v01_baseline): Hartley, Blackstone, Woodcourt
    Panel B (v19_all_swapped): Trevelyan, Leigh, Rosen
    """
    if panel_id.startswith("v01"):
        return "A"
    elif panel_id.startswith("v19"):
        return "B"
    else:
        return "other"


# ---------------------------------------------------------------------------
# Quote verification (fuzzy subsequence match)
# ---------------------------------------------------------------------------

def fuzzy_quote_match(quote: str, source: str, window: int = 5) -> bool:
    """Check if any 5-word subsequence of the quote appears in the source."""
    words = quote.lower().split()
    if len(words) < window:
        return quote.lower().strip('" >') in source
    for i in range(len(words) - window + 1):
        subseq = " ".join(words[i:i + window])
        if subseq in source:
            return True
    return False


def verify_quotes_detailed(
    run_dir: Path, source_text: str,
) -> tuple[int, int, list[dict]]:
    """Return (verified_count, total_quote_count, quote_details)."""
    ep_path = run_dir / "phase3_episode.json"
    if not ep_path.exists():
        return 0, 0, []
    try:
        ep = json.loads(ep_path.read_text())
    except (json.JSONDecodeError, OSError):
        return 0, 0, []

    verified = 0
    total = 0
    details: list[dict] = []

    for seg in ep.get("segments", []):
        for turn in seg.get("turns", []):
            for utt in turn.get("utterances", []):
                if utt.get("is_quote"):
                    total += 1
                    text = utt.get("text", "")
                    clean = text.strip().lstrip("> ").strip('"').strip("'")
                    matched = fuzzy_quote_match(clean, source_text)
                    if matched:
                        verified += 1
                    details.append({
                        "text": clean[:120],
                        "matched": matched,
                        "quote_mode": utt.get("quote_mode", ""),
                        "passage_ref": utt.get("passage_ref", ""),
                    })
    return verified, total, details


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="H5 quote verification analysis")
    parser.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    parser.add_argument("--out-dir", type=Path, default=REPORTS_DIR)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    runs_dir = args.runs_dir
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # Git tag
    try:
        git_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True,
        ).strip()
    except subprocess.CalledProcessError:
        git_hash = "unknown"
    tag = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{git_hash}"

    # -----------------------------------------------------------------------
    # 1. Discover all runs with phase3_episode.json
    # -----------------------------------------------------------------------
    run_dirs = sorted(d for d in runs_dir.iterdir() if d.is_dir())
    logger.info("Found %d run directories", len(run_dirs))

    # Classify each run
    runs_info: list[dict] = []
    for rd in run_dirs:
        ep_path = rd / "phase3_episode.json"
        if not ep_path.exists():
            continue
        novel, condition, panel_id = classify_run(rd.name)
        panel_ab = classify_panel(panel_id)
        runs_info.append({
            "dir": rd,
            "name": rd.name,
            "novel": novel,
            "condition": condition,
            "panel_id": panel_id,
            "panel_ab": panel_ab,
        })

    logger.info("Found %d runs with phase3_episode.json", len(runs_info))

    # -----------------------------------------------------------------------
    # 2. Load source texts
    # -----------------------------------------------------------------------
    novels = sorted({r["novel"] for r in runs_info if r["novel"] != "unknown"})
    source_cache: dict[str, str] = {}
    for novel in novels:
        src = load_source_text(novel, runs_dir)
        source_cache[novel] = src
        logger.info("Source text for %-25s: %d chars", novel, len(src))

    # -----------------------------------------------------------------------
    # 3. Verify quotes per run
    # -----------------------------------------------------------------------
    results: list[dict] = []
    for ri in runs_info:
        novel = ri["novel"]
        source = source_cache.get(novel, "")
        v, t, details = verify_quotes_detailed(ri["dir"], source)
        rate = v / t * 100 if t > 0 else float("nan")
        results.append({
            **ri,
            "verified": v,
            "total_quotes": t,
            "rate_pct": rate,
            "has_source": len(source) > 0,
        })

    # -----------------------------------------------------------------------
    # 4. Build output tables
    # -----------------------------------------------------------------------
    lines: list[str] = []
    lines.append(f"EXPERIMENT H5: QUOTE VERIFICATION ANALYSIS -- {tag}")
    lines.append("=" * 90)
    lines.append("")
    lines.append("H5 claim: Grounded conditions (transport, embedding, random, RAG) > 90%")
    lines.append("          Ungrounded (nop) < 50%")
    lines.append("")
    lines.append("Method: fuzzy 5-word subsequence match against source passages")
    lines.append("")

    # --- Table 1: Coverage matrix (novel x condition x panel) ---
    lines.append("TABLE 1: DATA AVAILABILITY (runs with phase3_episode.json)")
    lines.append("-" * 90)

    all_conditions = sorted({r["condition"] for r in results})
    all_novels_found = sorted({r["novel"] for r in results if r["novel"] != "unknown"})

    # Count runs per novel x condition
    coverage: dict[tuple[str, str], int] = defaultdict(int)
    coverage_ab: dict[tuple[str, str, str], int] = defaultdict(int)
    for r in results:
        if r["novel"] == "unknown":
            continue
        coverage[(r["novel"], r["condition"])] += 1
        coverage_ab[(r["novel"], r["condition"], r["panel_ab"])] += 1

    header = f"{'Novel':>22s}"
    for cond in all_conditions:
        header += f" {cond:>6s}"
    header += "  TOTAL"
    lines.append(header)

    for novel in all_novels_found:
        row = f"{NOVEL_LABELS.get(novel, novel):>22s}"
        total = 0
        for cond in all_conditions:
            n = coverage[(novel, cond)]
            total += n
            row += f" {n:>6d}"
        row += f" {total:>6d}"
        lines.append(row)

    # Totals row
    row = f"{'TOTAL':>22s}"
    grand = 0
    for cond in all_conditions:
        n = sum(coverage[(nov, cond)] for nov in all_novels_found)
        grand += n
        row += f" {n:>6d}"
    row += f" {grand:>6d}"
    lines.append(row)
    lines.append("")

    # Panel A/B breakdown
    lines.append("Panel breakdown (A=v01_baseline, B=v19_all_swapped):")
    for panel_ab in ["A", "B"]:
        row = f"  Panel {panel_ab}:"
        for cond in all_conditions:
            n = sum(coverage_ab[(nov, cond, panel_ab)] for nov in all_novels_found)
            if n > 0:
                row += f" {cond}={n}"
        lines.append(row)
    lines.append("")

    # --- Table 2: Quote verification by condition (all novels aggregated) ---
    lines.append("TABLE 2: QUOTE VERIFICATION BY CONDITION (all novels)")
    lines.append("-" * 90)
    lines.append(f"{'Condition':>14s} {'Label':>16s} {'Runs':>5s} {'Verified':>9s} "
                 f"{'Total':>7s} {'Rate%':>7s} {'Grounded?':>10s}")

    cond_agg: dict[str, dict] = defaultdict(lambda: {"v": 0, "t": 0, "n": 0})
    for r in results:
        if r["novel"] == "unknown" or not r["has_source"]:
            continue
        ca = cond_agg[r["condition"]]
        ca["v"] += r["verified"]
        ca["t"] += r["total_quotes"]
        ca["n"] += 1

    for cond in ["ext", "trn", "emb", "rag", "rand", "hia", "arc", "nop"]:
        ca = cond_agg.get(cond)
        if not ca or ca["n"] == 0:
            continue
        rate = ca["v"] / ca["t"] * 100 if ca["t"] > 0 else 0
        grounded = "YES" if cond in GROUNDED else ("NO" if cond in UNGROUNDED else "?")
        label = CONDITION_LABELS.get(cond, cond)
        lines.append(f"{cond:>14s} {label:>16s} {ca['n']:>5d} {ca['v']:>9d} "
                     f"{ca['t']:>7d} {rate:>7.1f} {grounded:>10s}")
    lines.append("")

    # --- Table 3: Quote verification by novel x condition ---
    lines.append("TABLE 3: QUOTE VERIFICATION BY NOVEL x CONDITION")
    lines.append("-" * 90)

    # H5-relevant conditions
    h5_conds = ["ext", "trn", "emb", "rag", "rand", "nop", "hia"]
    header = f"{'Novel':>22s}"
    for cond in h5_conds:
        header += f" {cond:>10s}"
    lines.append(header + "  (% verified / total quotes)")

    for novel in all_novels_found:
        row = f"{NOVEL_LABELS.get(novel, novel):>22s}"
        for cond in h5_conds:
            runs = [r for r in results
                    if r["novel"] == novel and r["condition"] == cond
                    and r["has_source"]]
            if not runs:
                row += f" {'--':>10s}"
                continue
            v = sum(r["verified"] for r in runs)
            t = sum(r["total_quotes"] for r in runs)
            rate = v / t * 100 if t > 0 else 0
            row += f" {rate:>5.1f}/{t:<4d}"
        lines.append(row)
    lines.append("")

    # --- Table 4: Panel A vs Panel B comparison ---
    lines.append("TABLE 4: PANEL A vs PANEL B COMPARISON")
    lines.append("-" * 90)
    lines.append(f"{'Condition':>14s} {'Panel':>6s} {'Runs':>5s} {'Verified':>9s} "
                 f"{'Total':>7s} {'Rate%':>7s}")

    for cond in ["ext", "trn", "emb", "rag", "rand", "nop", "hia"]:
        for panel in ["A", "B"]:
            runs = [r for r in results
                    if r["condition"] == cond and r["panel_ab"] == panel
                    and r["has_source"] and r["novel"] != "unknown"]
            if not runs:
                continue
            v = sum(r["verified"] for r in runs)
            t = sum(r["total_quotes"] for r in runs)
            rate = v / t * 100 if t > 0 else 0
            lines.append(f"{cond:>14s} {panel:>6s} {len(runs):>5d} {v:>9d} "
                         f"{t:>7d} {rate:>7.1f}")
    lines.append("")

    # --- Table 5: Detailed novel x condition x panel ---
    lines.append("TABLE 5: DETAILED RESULTS (novel x condition x panel)")
    lines.append("-" * 90)
    lines.append(f"{'Novel':>22s} {'Cond':>5s} {'Panel':>6s} {'Runs':>5s} "
                 f"{'Verified':>9s} {'Total':>7s} {'Rate%':>7s}")

    for novel in all_novels_found:
        for cond in h5_conds:
            for panel in ["A", "B", "other"]:
                runs = [r for r in results
                        if r["novel"] == novel and r["condition"] == cond
                        and r["panel_ab"] == panel and r["has_source"]]
                if not runs:
                    continue
                v = sum(r["verified"] for r in runs)
                t = sum(r["total_quotes"] for r in runs)
                rate = v / t * 100 if t > 0 else 0
                lines.append(
                    f"{NOVEL_LABELS.get(novel, novel):>22s} {cond:>5s} "
                    f"{panel:>6s} {len(runs):>5d} {v:>9d} {t:>7d} {rate:>7.1f}"
                )
    lines.append("")

    # --- Summary: H5 verdict ---
    lines.append("=" * 90)
    lines.append("H5 VERDICT")
    lines.append("=" * 90)

    grounded_v = sum(
        r["verified"] for r in results
        if r["condition"] in GROUNDED and r["has_source"] and r["novel"] != "unknown"
    )
    grounded_t = sum(
        r["total_quotes"] for r in results
        if r["condition"] in GROUNDED and r["has_source"] and r["novel"] != "unknown"
    )
    ungrounded_v = sum(
        r["verified"] for r in results
        if r["condition"] in UNGROUNDED and r["has_source"] and r["novel"] != "unknown"
    )
    ungrounded_t = sum(
        r["total_quotes"] for r in results
        if r["condition"] in UNGROUNDED and r["has_source"] and r["novel"] != "unknown"
    )

    grounded_rate = grounded_v / grounded_t * 100 if grounded_t > 0 else 0
    ungrounded_rate = ungrounded_v / ungrounded_t * 100 if ungrounded_t > 0 else 0

    lines.append(f"  Grounded conditions (ext/trn/emb/rag/rand/hia):")
    lines.append(f"    Rate: {grounded_rate:.1f}%  ({grounded_v}/{grounded_t} quotes)")
    lines.append(f"    Claim: > 90%  -->  {'SUPPORTED' if grounded_rate > 90 else 'NOT SUPPORTED'}")
    lines.append(f"")
    lines.append(f"  Ungrounded condition (nop):")
    lines.append(f"    Rate: {ungrounded_rate:.1f}%  ({ungrounded_v}/{ungrounded_t} quotes)")
    lines.append(f"    Claim: < 50%  -->  {'SUPPORTED' if ungrounded_rate < 50 else 'NOT SUPPORTED'}")
    lines.append(f"")
    lines.append(f"  Gap: {grounded_rate - ungrounded_rate:+.1f} percentage points")
    lines.append(f"")

    # Per-condition breakdown for verdict
    lines.append("  Per-condition rates:")
    for cond in ["ext", "trn", "emb", "rag", "rand", "hia", "nop"]:
        ca = cond_agg.get(cond)
        if not ca or ca["t"] == 0:
            continue
        rate = ca["v"] / ca["t"] * 100
        label = CONDITION_LABELS.get(cond, cond)
        marker = "  <-- UNGROUNDED" if cond in UNGROUNDED else ""
        lines.append(f"    {label:>16s}: {rate:5.1f}% ({ca['v']}/{ca['t']}){marker}")
    lines.append("")

    # -----------------------------------------------------------------------
    # 5. Write report
    # -----------------------------------------------------------------------
    report_text = "\n".join(lines)
    report_path = out_dir / f"h5_grounding_{tag}.txt"
    report_path.write_text(report_text)
    logger.info("Wrote %s", report_path)

    print(report_text)


if __name__ == "__main__":
    main()
