"""Experiment H13: Provision dimension schema transfer across novels.

H13 claims: "The seven provision dimensions capture different balances across
Victorian and modernist novels but remain usable without schema redesign. No
dimension is systematically empty or saturated for any novel."

Failure criterion: any dimension has < 5% strong for any novel.

Computes:
  - Per novel x dimension: % strong, % weak, % none
  - Cross-novel coefficient of variation for each dimension's strong %
  - Cosine similarity between all novel pairs' provision profiles
  - Identifies most/least variable dimensions
"""

from __future__ import annotations

import json
import math
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

NOVELS: dict[str, Path] = {
    "Bleak House": PROJECT_ROOT / "data" / "passages_enriched.json",
    "Mill on the Floss": PROJECT_ROOT / "data" / "novels" / "mill_on_the_floss" / "passages_enriched.json",
    "North and South": PROJECT_ROOT / "data" / "novels" / "north_and_south" / "passages_enriched.json",
    "Our Mutual Friend": PROJECT_ROOT / "data" / "novels" / "our_mutual_friend" / "passages_enriched.json",
    "Passage to India": PROJECT_ROOT / "data" / "novels" / "passage_to_india" / "passages_enriched.json",
}

DIMENSIONS = [
    "prov_character_development",
    "prov_plot_advancement",
    "prov_thematic_depth",
    "prov_social_critique",
    "prov_humor_entertainment",
    "prov_atmosphere_setting",
    "prov_narrative_technique",
]

VALUES = ["strong", "weak", "none"]


def short_dim(dim: str) -> str:
    """Shorten dimension name for display."""
    return dim.replace("prov_", "")


def load_passages(path: Path) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def compute_distributions(passages: list[dict]) -> dict[str, dict[str, float]]:
    """For each dimension, compute % strong/weak/none."""
    counts: dict[str, dict[str, int]] = {d: {v: 0 for v in VALUES} for d in DIMENSIONS}
    total = 0
    for p in passages:
        enr = p.get("enrichment", {})
        if "prov_character_development" not in enr:
            continue
        total += 1
        for dim in DIMENSIONS:
            val = enr.get(dim, "none")
            if val in counts[dim]:
                counts[dim][val] += 1
            else:
                counts[dim]["none"] += 1

    result: dict[str, dict[str, float]] = {}
    for dim in DIMENSIONS:
        result[dim] = {}
        for v in VALUES:
            result[dim][v] = (counts[dim][v] / total * 100) if total > 0 else 0.0
    return result


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def coefficient_of_variation(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    if mean == 0:
        return float("inf")
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return math.sqrt(variance) / mean


def main() -> None:
    # Load data
    novel_data: dict[str, list[dict]] = {}
    for name, path in NOVELS.items():
        novel_data[name] = load_passages(path)

    # Compute distributions
    distributions: dict[str, dict[str, dict[str, float]]] = {}
    for name, passages in novel_data.items():
        distributions[name] = compute_distributions(passages)

    novel_names = list(NOVELS.keys())
    short_names = ["BH", "MotF", "N&S", "OMF", "PtI"]

    # ── Table 1: Per-novel passage counts ──
    print("=" * 80)
    print("EXPERIMENT H13: PROVISION DIMENSION SCHEMA TRANSFER")
    print("=" * 80)
    print()
    print("── Passage counts ──")
    for name, sn in zip(novel_names, short_names):
        n_total = len(novel_data[name])
        n_enriched = sum(
            1 for p in novel_data[name]
            if "prov_character_development" in p.get("enrichment", {})
        )
        print(f"  {sn:5s} ({name:20s}): {n_total:5d} total, {n_enriched:5d} with provision dims")
    print()

    # ── Table 2: Strong % for each novel x dimension ──
    print("── Table: % STRONG by novel x dimension ──")
    header = f"{'Dimension':30s}" + "".join(f"{sn:>8s}" for sn in short_names)
    print(header)
    print("-" * len(header))
    for dim in DIMENSIONS:
        row = f"{short_dim(dim):30s}"
        for name in novel_names:
            row += f"{distributions[name][dim]['strong']:7.1f}%"
        print(row)
    print()

    # ── Table 3: Weak % ──
    print("── Table: % WEAK by novel x dimension ──")
    print(header)
    print("-" * len(header))
    for dim in DIMENSIONS:
        row = f"{short_dim(dim):30s}"
        for name in novel_names:
            row += f"{distributions[name][dim]['weak']:7.1f}%"
        print(row)
    print()

    # ── Table 4: None % ──
    print("── Table: % NONE by novel x dimension ──")
    print(header)
    print("-" * len(header))
    for dim in DIMENSIONS:
        row = f"{short_dim(dim):30s}"
        for name in novel_names:
            row += f"{distributions[name][dim]['none']:7.1f}%"
        print(row)
    print()

    # ── Failure criterion: any dimension < 5% strong for any novel ──
    print("── H13 FAILURE CRITERION: any dimension < 5% strong for any novel ──")
    failures: list[tuple[str, str, float]] = []
    for name, sn in zip(novel_names, short_names):
        for dim in DIMENSIONS:
            pct = distributions[name][dim]["strong"]
            if pct < 5.0:
                failures.append((sn, short_dim(dim), pct))
    if failures:
        print(f"  FAILURES FOUND ({len(failures)}):")
        for sn, dim, pct in failures:
            print(f"    {sn:5s} | {dim:30s} | {pct:.1f}% strong")
    else:
        print("  NO FAILURES: all dimensions >= 5% strong for all novels.")
    print()

    # ── Cross-novel CV for each dimension's strong % ──
    print("── Cross-novel coefficient of variation (CV) for strong % ──")
    dim_cvs: list[tuple[str, float, float]] = []
    for dim in DIMENSIONS:
        strongs = [distributions[name][dim]["strong"] for name in novel_names]
        cv = coefficient_of_variation(strongs)
        mean_strong = sum(strongs) / len(strongs)
        dim_cvs.append((short_dim(dim), cv, mean_strong))
        print(f"  {short_dim(dim):30s}: CV = {cv:.3f}  (mean strong = {mean_strong:.1f}%)")
    print()

    dim_cvs_sorted = sorted(dim_cvs, key=lambda x: x[1], reverse=True)
    print("  Most variable dimension:  ", dim_cvs_sorted[0][0], f"(CV={dim_cvs_sorted[0][1]:.3f})")
    print("  Least variable dimension: ", dim_cvs_sorted[-1][0], f"(CV={dim_cvs_sorted[-1][1]:.3f})")
    print()

    # ── Provision profiles (strong % vectors) ──
    print("── Provision profiles (strong % vectors) ──")
    profiles: dict[str, list[float]] = {}
    for name, sn in zip(novel_names, short_names):
        profile = [distributions[name][dim]["strong"] for dim in DIMENSIONS]
        profiles[name] = profile
        dim_labels = [short_dim(d)[:8] for d in DIMENSIONS]
        vals = " ".join(f"{v:5.1f}" for v in profile)
        print(f"  {sn:5s}: [{vals}]")
    print(f"  {'dims':5s}: [{' '.join(f'{d:>5s}' for d in dim_labels)}]")
    print()

    # ── Cosine similarity matrix ──
    print("── Cosine similarity between novel provision profiles ──")
    cos_header = f"{'':6s}" + "".join(f"{sn:>8s}" for sn in short_names)
    print(cos_header)
    for i, (name_i, sn_i) in enumerate(zip(novel_names, short_names)):
        row = f"{sn_i:6s}"
        for j, name_j in enumerate(novel_names):
            sim = cosine_similarity(profiles[name_i], profiles[name_j])
            row += f"{sim:8.3f}"
        print(row)
    print()

    # ── Summary verdict ──
    print("=" * 80)
    print("VERDICT")
    print("=" * 80)
    if failures:
        print(f"H13 PARTIALLY FAILS: {len(failures)} dimension(s) below 5% strong threshold.")
        print("Dimensions that may need redesign or recalibration:")
        failing_dims = sorted(set(d for _, d, _ in failures))
        for d in failing_dims:
            affected = [(sn, pct) for sn, dim, pct in failures if dim == d]
            print(f"  - {d}: failing in {', '.join(f'{sn} ({pct:.1f}%)' for sn, pct in affected)}")
    else:
        print("H13 SUPPORTED: All seven provision dimensions maintain >= 5% strong")
        print("ratings across all five novels. The schema transfers without redesign.")
    print()
    avg_cos = []
    for i in range(len(novel_names)):
        for j in range(i + 1, len(novel_names)):
            avg_cos.append(cosine_similarity(profiles[novel_names[i]], profiles[novel_names[j]]))
    print(f"Mean pairwise cosine similarity: {sum(avg_cos)/len(avg_cos):.3f}")
    print(f"Min pairwise cosine similarity:  {min(avg_cos):.3f}")
    print(f"Max pairwise cosine similarity:  {max(avg_cos):.3f}")
    print()
    print(f"Most discriminating dimension:   {dim_cvs_sorted[0][0]} (CV={dim_cvs_sorted[0][1]:.3f})")
    print(f"Most stable dimension:           {dim_cvs_sorted[-1][0]} (CV={dim_cvs_sorted[-1][1]:.3f})")


if __name__ == "__main__":
    main()
