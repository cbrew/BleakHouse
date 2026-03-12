"""Cross-novel aggregate quality metrics.

Computes metrics across all 96 cross-novel runs (4 novels x 3 conditions x 8 panels)
and produces summary CSVs and console tables.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from scripts.cross_novel_loader import (
    ALL_EXPERTS,
    NOVEL_TITLES,
    build_char_patterns,
    count_characters,
    discover_runs,
    extract_turns,
    load_episode,
    load_novel_characters,
    shannon_entropy,
)

SCRIPTS_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPTS_DIR.parent
OUT_DIR = BASE_DIR / "reports" / "cross_novel_aggregate"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Experts excluding Host
PANEL_EXPERTS = sorted(ALL_EXPERTS - {"Host"})


def main() -> None:
    runs = discover_runs()
    print(f"Discovered {len(runs)} runs")
    print()

    # Pre-load character patterns per novel
    novel_patterns: dict[str, dict] = {}
    for novel_key in NOVEL_TITLES:
        chars = load_novel_characters(novel_key)
        novel_patterns[novel_key] = build_char_patterns(chars)

    # Compute per-run metrics
    run_rows: list[dict] = []

    for (novel_key, condition, panel_id), run_dir in sorted(runs.items()):
        episode = load_episode(run_dir)
        turns = extract_turns(episode)
        patterns = novel_patterns[novel_key]

        total_words = 0
        total_segments = len(episode.get("segments", []))
        total_turns = len(turns)
        total_utterances = 0
        quote_count = 0
        all_text = ""
        expert_words: dict[str, int] = defaultdict(int)

        for seg in episode.get("segments", []):
            for turn in seg.get("turns", []):
                utterances = turn.get("utterances", [])
                total_utterances += len(utterances)
                for u in utterances:
                    if u.get("is_quote", False):
                        quote_count += 1

        for turn in turns:
            total_words += turn["word_count"]
            all_text += " " + turn["text"]
            speaker = turn["speaker"]
            if speaker in PANEL_EXPERTS:
                expert_words[speaker] += turn["word_count"]

        char_counts = count_characters(all_text, patterns)
        char_mentions = sum(char_counts.values())
        unique_characters = len(char_counts)
        char_entropy = shannon_entropy(char_counts)
        char_density = char_mentions / max(total_words, 1) * 1000
        quote_density = quote_count / max(total_words, 1) * 1000

        row = {
            "novel": novel_key,
            "condition": condition,
            "panel_id": panel_id,
            "total_words": total_words,
            "total_segments": total_segments,
            "total_turns": total_turns,
            "total_utterances": total_utterances,
            "quote_count": quote_count,
            "quote_density": round(quote_density, 3),
            "character_mentions": char_mentions,
            "char_density": round(char_density, 3),
            "unique_characters": unique_characters,
            "character_entropy": round(char_entropy, 3),
        }

        # Add per-expert airtime columns
        for expert in PANEL_EXPERTS:
            row[f"airtime_{expert}"] = expert_words.get(expert, 0)

        run_rows.append(row)

    # -----------------------------------------------------------------------
    # Output 1: run_metrics.csv
    # -----------------------------------------------------------------------
    fieldnames = [
        "novel", "condition", "panel_id",
        "total_words", "total_segments", "total_turns", "total_utterances",
        "quote_count", "quote_density",
        "character_mentions", "char_density", "unique_characters", "character_entropy",
    ] + [f"airtime_{e}" for e in PANEL_EXPERTS]

    run_csv_path = OUT_DIR / "run_metrics.csv"
    with open(run_csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(run_rows)
    print(f"Written: {run_csv_path}")

    # -----------------------------------------------------------------------
    # Output 2: novel_condition_summary.csv (means grouped by novel x condition)
    # -----------------------------------------------------------------------
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in run_rows:
        grouped[(row["novel"], row["condition"])].append(row)

    summary_fields = [
        "novel", "condition", "n_runs",
        "mean_words", "mean_segments", "mean_turns", "mean_utterances",
        "mean_quote_count", "mean_quote_density",
        "mean_char_mentions", "mean_char_density",
        "mean_unique_characters", "mean_char_entropy",
    ]

    summary_rows: list[dict] = []
    for (novel_key, condition) in sorted(grouped.keys()):
        rows = grouped[(novel_key, condition)]
        n = len(rows)
        summary = {
            "novel": novel_key,
            "condition": condition,
            "n_runs": n,
            "mean_words": round(sum(r["total_words"] for r in rows) / n, 1),
            "mean_segments": round(sum(r["total_segments"] for r in rows) / n, 1),
            "mean_turns": round(sum(r["total_turns"] for r in rows) / n, 1),
            "mean_utterances": round(sum(r["total_utterances"] for r in rows) / n, 1),
            "mean_quote_count": round(sum(r["quote_count"] for r in rows) / n, 1),
            "mean_quote_density": round(sum(r["quote_density"] for r in rows) / n, 3),
            "mean_char_mentions": round(sum(r["character_mentions"] for r in rows) / n, 1),
            "mean_char_density": round(sum(r["char_density"] for r in rows) / n, 3),
            "mean_unique_characters": round(sum(r["unique_characters"] for r in rows) / n, 1),
            "mean_char_entropy": round(sum(r["character_entropy"] for r in rows) / n, 3),
        }
        summary_rows.append(summary)

    summary_csv_path = OUT_DIR / "novel_condition_summary.csv"
    with open(summary_csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=summary_fields)
        writer.writeheader()
        writer.writerows(summary_rows)
    print(f"Written: {summary_csv_path}")

    # -----------------------------------------------------------------------
    # Console table 1: novel x condition means for key metrics
    # -----------------------------------------------------------------------
    conditions = sorted({r["condition"] for r in run_rows})
    novels = sorted(NOVEL_TITLES.keys())

    print()
    print("=" * 90)
    print("NOVEL x CONDITION MEANS")
    print("=" * 90)

    for metric, label, fmt in [
        ("mean_words", "Words", ".0f"),
        ("mean_quote_count", "Quotes", ".1f"),
        ("mean_char_density", "Char Density /1K", ".2f"),
        ("mean_unique_characters", "Unique Chars", ".1f"),
    ]:
        print(f"\n  {label}")
        print(f"  {'Novel':<25}", end="")
        for cond in conditions:
            print(f"{cond:>15}", end="")
        print()
        print(f"  {'-' * (25 + 15 * len(conditions))}")

        for novel_key in novels:
            title = NOVEL_TITLES[novel_key]
            print(f"  {title:<25}", end="")
            for cond in conditions:
                match = [s for s in summary_rows
                         if s["novel"] == novel_key and s["condition"] == cond]
                if match:
                    val = match[0][metric]
                    print(f"{val:>15{fmt}}", end="")
                else:
                    print(f"{'--':>15}", end="")
            print()

    # -----------------------------------------------------------------------
    # Console table 2: expert airtime (transport condition, averaged across panels)
    # -----------------------------------------------------------------------
    print()
    print("=" * 90)
    print("EXPERT AIRTIME — TRANSPORT CONDITION (mean words per panel)")
    print("=" * 90)

    # Gather transport runs grouped by novel
    transport_by_novel: dict[str, list[dict]] = defaultdict(list)
    for row in run_rows:
        if row["condition"] == "transport":
            transport_by_novel[row["novel"]].append(row)

    # Find experts that actually appear
    active_experts = []
    for expert in PANEL_EXPERTS:
        col = f"airtime_{expert}"
        if any(r[col] > 0 for r in run_rows if r["condition"] == "transport"):
            active_experts.append(expert)

    print(f"\n  {'Novel':<25}", end="")
    for expert in active_experts:
        short = expert.split()[-1]
        print(f"{short:>14}", end="")
    print(f"{'Total':>14}")
    print(f"  {'-' * (25 + 14 * (len(active_experts) + 1))}")

    for novel_key in novels:
        title = NOVEL_TITLES[novel_key]
        rows = transport_by_novel.get(novel_key, [])
        if not rows:
            continue
        n = len(rows)
        print(f"  {title:<25}", end="")
        row_total = 0.0
        for expert in active_experts:
            col = f"airtime_{expert}"
            mean_val = sum(r[col] for r in rows) / n
            row_total += mean_val
            print(f"{mean_val:>14.0f}", end="")
        print(f"{row_total:>14.0f}")

    # Word share percentages
    print()
    print(f"  {'Novel (% share)':<25}", end="")
    for expert in active_experts:
        short = expert.split()[-1]
        print(f"{short:>14}", end="")
    print()
    print(f"  {'-' * (25 + 14 * len(active_experts))}")

    for novel_key in novels:
        title = NOVEL_TITLES[novel_key]
        rows = transport_by_novel.get(novel_key, [])
        if not rows:
            continue
        n = len(rows)
        means = {}
        for expert in active_experts:
            col = f"airtime_{expert}"
            means[expert] = sum(r[col] for r in rows) / n
        total = sum(means.values())
        if total == 0:
            continue
        print(f"  {title:<25}", end="")
        for expert in active_experts:
            pct = means[expert] / total * 100
            print(f"{pct:>13.1f}%", end="")
        print()

    print()
    print("Done.")


if __name__ == "__main__":
    main()
