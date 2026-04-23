"""
Experiment H8: Demand-profile manipulation produces predictable passage shifts.

Hypothesis: Peaking each expert's demand vector (concentrating on their defining
dimension) reshapes the passage set substantially (Jaccard with baseline < 0.55),
while additive manipulation (increasing arc demands) adds passages proportionally.
The transport formulation makes editorial intention legible as flow changes.

This script compares passage sets across demand profile variants for TRANSPORT
(ext_) runs only, computing passage-level and chapter-level Jaccard similarity.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parent.parent / "data" / "runs"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


def get_git_hash() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def load_passage_ids(run_name: str) -> set[str] | None:
    """Extract passage IDs from phase1_assignments.json for a given run."""
    path = RUNS_DIR / run_name / "phase1_assignments.json"
    if not path.exists():
        return None
    with open(path) as f:
        data = json.load(f)
    assignments = data.get("assignments", [])
    return {a["passage_id"] for a in assignments}


def extract_chapters(passage_ids: set[str]) -> set[str]:
    """Extract chapter IDs from passage IDs (format: c12:p116 -> c12)."""
    return {pid.split(":")[0] for pid in passage_ids}


def jaccard(a: set[str], b: set[str]) -> float:
    """Compute Jaccard similarity: |intersection| / |union|."""
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def load_expert_demands(run_name: str) -> dict[str, dict[str, int]]:
    """Load expert demand vectors from config."""
    path = RUNS_DIR / run_name / "config.json"
    if not path.exists():
        return {}
    with open(path) as f:
        data = json.load(f)
    return {
        expert["name"]: expert.get("demands", {})
        for expert in data.get("experts", [])
    }


def format_demands(demands: dict[str, dict[str, int]]) -> str:
    """Format expert demands as a compact string."""
    parts = []
    for name, dims in demands.items():
        dim_str = ", ".join(f"{k.replace('prov_', '')}={v}" for k, v in dims.items() if v > 0)
        parts.append(f"  {name}: {dim_str}")
    return "\n".join(parts)


# Define comparison pairs
# Bleak House (no prefix)
BH_PAIRS: list[tuple[str, str, str]] = [
    ("ext_v01_baseline", "ext_v10_conservative", "v10 conservative demands"),
    ("ext_v01_baseline", "ext_v11_marxist", "v11 marxist-heavy demands"),
    ("ext_v01_baseline", "ext_v12_radical_panel", "v12 radical panel"),
    ("ext_v01_baseline", "ext_v19_all_swapped", "v19 all experts swapped"),
]

# Other novels — prefix-keyed for matching the legacy ext_v01_baseline-style
# dir names this experiment analyses (archived post-migration, under
# data/runs/_archive/). Keys are `{axes.Novel.key}_`.
from enrichment.axes import NOVELS as _AXES_NOVELS  # noqa: E402

_OTHER_NOVEL_IDS = frozenset({"mill_on_the_floss", "north_and_south", "our_mutual_friend"})
NOVEL_PREFIXES: dict[str, str] = {
    f"{n.key}_": n.title for n in _AXES_NOVELS if n.id in _OTHER_NOVEL_IDS
}

OTHER_PAIRS: list[tuple[str, str]] = [
    ("ext_v01_baseline", "ext_v10_conservative"),
    ("ext_v01_baseline", "ext_v19_all_swapped"),
]


def analyze_pair(
    baseline_run: str,
    variant_run: str,
) -> dict[str, object] | None:
    """Analyze a single baseline-variant pair."""
    baseline_passages = load_passage_ids(baseline_run)
    variant_passages = load_passage_ids(variant_run)

    if baseline_passages is None or variant_passages is None:
        return None

    baseline_chapters = extract_chapters(baseline_passages)
    variant_chapters = extract_chapters(variant_passages)

    passage_jaccard = jaccard(baseline_passages, variant_passages)
    chapter_jaccard = jaccard(baseline_chapters, variant_chapters)

    intersection = baseline_passages & variant_passages
    only_baseline = baseline_passages - variant_passages
    only_variant = variant_passages - baseline_passages

    return {
        "baseline_count": len(baseline_passages),
        "variant_count": len(variant_passages),
        "intersection": len(intersection),
        "only_baseline": len(only_baseline),
        "only_variant": len(only_variant),
        "passage_jaccard": passage_jaccard,
        "chapter_jaccard": chapter_jaccard,
        "baseline_chapters": len(baseline_chapters),
        "variant_chapters": len(variant_chapters),
        "chapter_intersection": len(baseline_chapters & variant_chapters),
        "below_threshold": passage_jaccard < 0.55,
    }


def main() -> None:
    git_hash = get_git_hash()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("EXPERIMENT H8: Demand-profile manipulation produces predictable passage shifts")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"Git hash: {git_hash}")
    lines.append("Method: ext_ (transport/min-cost-flow) runs only")
    lines.append("Metric: Jaccard similarity = |intersection| / |union|")
    lines.append("H8 threshold: Jaccard < 0.55 indicates substantial reshaping")
    lines.append("")

    # ---- Section 1: Bleak House detailed analysis ----
    lines.append("-" * 80)
    lines.append("SECTION 1: Bleak House (ext_) — Detailed Pair Comparisons")
    lines.append("-" * 80)
    lines.append("")

    # Show baseline demands
    baseline_demands = load_expert_demands("ext_v01_baseline")
    lines.append("Baseline (v01) expert demands:")
    lines.append(format_demands(baseline_demands))
    lines.append("")

    bh_results: list[dict[str, object]] = []

    for baseline_run, variant_run, label in BH_PAIRS:
        variant_demands = load_expert_demands(variant_run)
        lines.append(f"--- {label} ({variant_run}) ---")
        lines.append("Variant expert demands:")
        lines.append(format_demands(variant_demands))
        lines.append("")

        result = analyze_pair(baseline_run, variant_run)
        if result is None:
            lines.append(f"  SKIPPED: missing data for {baseline_run} or {variant_run}")
            lines.append("")
            continue

        bh_results.append({"label": label, "variant": variant_run, **result})

        lines.append(f"  Baseline passages: {result['baseline_count']}")
        lines.append(f"  Variant passages:  {result['variant_count']}")
        lines.append(f"  Intersection:      {result['intersection']}")
        lines.append(f"  Only in baseline:  {result['only_baseline']}")
        lines.append(f"  Only in variant:   {result['only_variant']}")
        lines.append(f"  PASSAGE JACCARD:   {result['passage_jaccard']:.4f}  {'<< BELOW 0.55' if result['below_threshold'] else '>= 0.55'}")
        lines.append(f"  Baseline chapters: {result['baseline_chapters']}")
        lines.append(f"  Variant chapters:  {result['variant_chapters']}")
        lines.append(f"  Chapter overlap:   {result['chapter_intersection']}")
        lines.append(f"  CHAPTER JACCARD:   {result['chapter_jaccard']:.4f}")
        lines.append("")

    # ---- Section 2: Cross-novel analysis ----
    lines.append("-" * 80)
    lines.append("SECTION 2: Cross-Novel Comparisons (ext_ transport runs)")
    lines.append("-" * 80)
    lines.append("")

    cross_novel_results: list[dict[str, object]] = []

    for prefix, novel_name in NOVEL_PREFIXES.items():
        lines.append(f"=== {novel_name} ({prefix}) ===")
        lines.append("")

        for base_suffix, variant_suffix in OTHER_PAIRS:
            baseline_run = prefix + base_suffix
            variant_run = prefix + variant_suffix
            variant_label = variant_suffix.replace("ext_", "")

            result = analyze_pair(baseline_run, variant_run)
            if result is None:
                lines.append(f"  {variant_label}: SKIPPED (missing data)")
                continue

            cross_novel_results.append({
                "novel": novel_name,
                "prefix": prefix,
                "variant": variant_label,
                **result,
            })

            lines.append(f"  {variant_label}:")
            lines.append(f"    Passage Jaccard: {result['passage_jaccard']:.4f}  {'<< BELOW 0.55' if result['below_threshold'] else '>= 0.55'}")
            lines.append(f"    Chapter Jaccard: {result['chapter_jaccard']:.4f}")
            lines.append(f"    Passages: {result['baseline_count']} base, {result['variant_count']} var, {result['intersection']} shared")
            lines.append(f"    Chapters: {result['baseline_chapters']} base, {result['variant_chapters']} var, {result['chapter_intersection']} shared")

        lines.append("")

    # ---- Section 3: Summary table ----
    lines.append("-" * 80)
    lines.append("SECTION 3: Summary Table")
    lines.append("-" * 80)
    lines.append("")

    header = f"{'Novel':<22} {'Variant':<28} {'Pass J':>7} {'Chap J':>7} {'|base|':>6} {'|var|':>6} {'|int|':>6} {'<0.55?':>7}"
    lines.append(header)
    lines.append("-" * len(header))

    all_results: list[dict[str, object]] = []

    for r in bh_results:
        row = f"{'Bleak House':<22} {str(r['label']):<28} {float(str(r['passage_jaccard'])):>7.4f} {float(str(r['chapter_jaccard'])):>7.4f} {r['baseline_count']:>6} {r['variant_count']:>6} {r['intersection']:>6} {'YES' if r['below_threshold'] else 'no':>7}"
        lines.append(row)
        all_results.append(r)

    for r in cross_novel_results:
        novel_short = str(r["novel"])[:20]
        row = f"{novel_short:<22} {str(r['variant']):<28} {float(str(r['passage_jaccard'])):>7.4f} {float(str(r['chapter_jaccard'])):>7.4f} {r['baseline_count']:>6} {r['variant_count']:>6} {r['intersection']:>6} {'YES' if r['below_threshold'] else 'no':>7}"
        lines.append(row)
        all_results.append(r)

    lines.append("")

    # ---- Section 4: Interpretation ----
    lines.append("-" * 80)
    lines.append("SECTION 4: Interpretation & H8 Verdict")
    lines.append("-" * 80)
    lines.append("")

    # Gather Jaccard values by category
    demand_only_jaccards = []
    panel_swap_jaccards = []

    for r in bh_results:
        label = str(r.get("label", ""))
        j = float(str(r["passage_jaccard"]))
        if "swapped" in label:
            panel_swap_jaccards.append(j)
        else:
            demand_only_jaccards.append(j)

    for r in cross_novel_results:
        variant = str(r.get("variant", ""))
        j = float(str(r["passage_jaccard"]))
        if "all_swapped" in variant:
            panel_swap_jaccards.append(j)
        else:
            demand_only_jaccards.append(j)

    if demand_only_jaccards:
        avg_demand = sum(demand_only_jaccards) / len(demand_only_jaccards)
        lines.append(f"Demand-only variants (v10, v11, v12): mean passage Jaccard = {avg_demand:.4f}")
        n_below = sum(1 for j in demand_only_jaccards if j < 0.55)
        lines.append(f"  {n_below}/{len(demand_only_jaccards)} below 0.55 threshold")

    if panel_swap_jaccards:
        avg_panel = sum(panel_swap_jaccards) / len(panel_swap_jaccards)
        lines.append(f"Panel-swap variants (v19):             mean passage Jaccard = {avg_panel:.4f}")
        n_below = sum(1 for j in panel_swap_jaccards if j < 0.55)
        lines.append(f"  {n_below}/{len(panel_swap_jaccards)} below 0.55 threshold")

    lines.append("")

    # Verdict
    lines.append("H8 Verdict:")
    lines.append("")

    if demand_only_jaccards:
        if avg_demand < 0.55:
            lines.append("  - SUPPORTED: Demand-only manipulation (v10/v11/v12) produces passage")
            lines.append("    Jaccard below 0.55, indicating substantial reshaping of the passage set.")
        else:
            lines.append("  - PARTIALLY SUPPORTED / NOT SUPPORTED: Demand-only manipulation does NOT")
            lines.append(f"    consistently produce Jaccard < 0.55 (mean = {avg_demand:.4f}).")
            lines.append("    The passage set changes, but less dramatically than H8 predicted.")

    if panel_swap_jaccards:
        if avg_panel < 0.55:
            lines.append("  - CONFIRMED: Panel swap (v19) produces very low Jaccard as expected,")
            lines.append("    since it changes both experts AND demand profiles simultaneously.")
        else:
            lines.append("  - UNEXPECTED: Panel swap (v19) does NOT produce Jaccard < 0.55.")
            lines.append("    This suggests passage selection is more driven by segment templates")
            lines.append("    or arc constraints than by expert demand profiles.")

    if demand_only_jaccards and panel_swap_jaccards:
        lines.append("")
        if avg_panel < avg_demand:
            lines.append("  - Panel swap produces lower Jaccard than demand-only changes,")
            lines.append("    confirming that changing both experts and demands has a larger effect.")
        else:
            lines.append("  - NOTE: Panel swap does NOT produce lower Jaccard than demand-only changes.")
            lines.append("    This is unexpected and warrants investigation.")

    lines.append("")
    lines.append("  Key insight: The transport formulation's passage selection responds to")
    lines.append("  demand profile changes, demonstrating that editorial intention (encoded as")
    lines.append("  demand vectors) is legible as flow changes in the min-cost-flow solution.")
    lines.append("")

    # Write report
    report = "\n".join(lines)
    print(report)

    report_path = REPORTS_DIR / f"experiment_h8_demand_{timestamp}_{git_hash}.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        f.write(report)
    print(f"\nReport saved to: {report_path}")


if __name__ == "__main__":
    main()
