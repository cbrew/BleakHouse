"""Test whether expert vocabulary signatures and behavioral profiles are stable across novels.

Analyses:
1. Expert airtime by novel x condition (word-count proportions)
2. Cross-novel TF-IDF cosine similarity per expert
3. Top-10 keywords per expert (highest TF-IDF weight averaged across novels)
4. Sentence-type behavioral profiles per expert across novels
"""

from __future__ import annotations

import csv
import datetime
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from cross_novel_loader import (
    ALL_EXPERTS,
    NOVEL_TITLES,
    discover_runs,
    extract_turns,
    load_episode,
)

SCRIPTS_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPTS_DIR.parent
REPORT_DIR = BASE_DIR / "reports" / "cross_novel_expert_identity"

EXPERTS_NO_HOST = sorted(ALL_EXPERTS - {"Host"})


def _git_hash() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=BASE_DIR,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def _timestamp_tag() -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{ts}_{_git_hash()}"


# ── 1. Per-expert text and word counts by (novel, condition, panel) ──────────


def gather_expert_texts(
    runs: dict,
) -> tuple[
    dict[tuple[str, str, str], dict[str, str]],
    dict[tuple[str, str, str], dict[str, list[dict]]],
]:
    """Return per-run expert text and per-run utterance-level data.

    Returns:
        texts: {(novel, cond, panel): {expert: concatenated_text}}
        utterances: {(novel, cond, panel): {expert: [utterance_dicts]}}
    """
    texts: dict[tuple[str, str, str], dict[str, str]] = {}
    utterance_data: dict[tuple[str, str, str], dict[str, list[dict]]] = {}

    for key, run_dir in runs.items():
        episode = load_episode(run_dir)
        turns = extract_turns(episode)
        expert_text: dict[str, list[str]] = defaultdict(list)
        expert_utts: dict[str, list[dict]] = defaultdict(list)

        for seg in episode.get("segments", []):
            for turn in seg.get("turns", []):
                speaker = turn.get("speaker", "Unknown")
                if speaker == "Host" or speaker not in ALL_EXPERTS:
                    continue
                for u in turn.get("utterances", []):
                    if "text" in u:
                        expert_text[speaker].append(u["text"])
                        expert_utts[speaker].append(u)

        texts[key] = {exp: " ".join(expert_text[exp]) for exp in expert_text}
        utterance_data[key] = dict(expert_utts)

    return texts, utterance_data


# ── 2. Airtime by novel × condition ─────────────────────────────────────────


def compute_airtime(
    texts: dict[tuple[str, str, str], dict[str, str]],
) -> list[dict]:
    """Compute per-expert airtime proportions by novel × condition.

    For each (novel, condition), average across panels:
        expert_words / total_expert_words.
    """
    # Accumulate per (novel, cond, expert) word counts across panels
    agg: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for (novel, cond, panel), expert_texts in texts.items():
        total = sum(len(t.split()) for t in expert_texts.values())
        if total == 0:
            continue
        for expert in EXPERTS_NO_HOST:
            wc = len(expert_texts.get(expert, "").split()) if expert in expert_texts else 0
            agg[(novel, cond)][expert].append(wc / total)

    rows = []
    for (novel, cond), expert_proportions in sorted(agg.items()):
        for expert in EXPERTS_NO_HOST:
            vals = expert_proportions.get(expert, [])
            avg = sum(vals) / len(vals) if vals else 0.0
            rows.append({
                "novel": novel,
                "condition": cond,
                "expert": expert,
                "mean_airtime": round(avg, 4),
                "n_panels": len(vals),
            })
    return rows


# ── 3. TF-IDF cross-novel cosine similarity ─────────────────────────────────


def tfidf_analysis(
    texts: dict[tuple[str, str, str], dict[str, str]],
) -> tuple[list[dict], list[dict]] | None:
    """Compute cross-novel cosine similarity and top keywords per expert.

    Returns (cosine_rows, keyword_rows) or None if sklearn unavailable.
    """
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        import numpy as np
    except ImportError:
        print("[WARN] sklearn not available — skipping TF-IDF analysis")
        return None

    novels = sorted(NOVEL_TITLES.keys())

    # Pool all text per expert per novel (across all conditions and panels)
    expert_novel_text: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for (novel, _cond, _panel), expert_texts in texts.items():
        for expert, text in expert_texts.items():
            expert_novel_text[expert][novel].append(text)

    cosine_rows = []
    keyword_rows = []

    for expert in EXPERTS_NO_HOST:
        novel_texts = expert_novel_text.get(expert, {})
        available_novels = [n for n in novels if n in novel_texts and novel_texts[n]]
        if len(available_novels) < 2:
            continue

        docs = [" ".join(novel_texts[n]) for n in available_novels]
        vec = TfidfVectorizer(max_features=5000, stop_words="english")
        tfidf_matrix = vec.fit_transform(docs)
        features = vec.get_feature_names_out()

        # Pairwise cosine across novels
        sim = cosine_similarity(tfidf_matrix)
        n = len(available_novels)
        pairs = []
        for i in range(n):
            for j in range(i + 1, n):
                pairs.append(sim[i, j])
        mean_cos = float(np.mean(pairs)) if pairs else 0.0

        cosine_rows.append({
            "expert": expert,
            "mean_cosine": round(mean_cos, 4),
            "n_novels": n,
            "novels": ", ".join(available_novels),
        })

        # Top-10 keywords: average TF-IDF weight across novels
        mean_weights = np.asarray(tfidf_matrix.mean(axis=0)).ravel()
        top_idx = mean_weights.argsort()[::-1][:10]
        for rank, idx in enumerate(top_idx, 1):
            keyword_rows.append({
                "expert": expert,
                "rank": rank,
                "keyword": features[idx],
                "mean_tfidf": round(float(mean_weights[idx]), 4),
            })

    return cosine_rows, keyword_rows


# ── 4. Sentence-type behavioral profiles ────────────────────────────────────


def sentence_type_profiles(
    utterance_data: dict[tuple[str, str, str], dict[str, list[dict]]],
) -> dict[str, dict[str, dict[str, int]]]:
    """Compute per-expert per-novel sentence_type distributions.

    Returns {expert: {novel: {sentence_type: count}}}.
    """
    profiles: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )
    for (novel, _cond, _panel), expert_utts in utterance_data.items():
        for expert, utts in expert_utts.items():
            for u in utts:
                st = u.get("sentence_type", "unknown")
                profiles[expert][novel][st] += 1
    return profiles


def format_sentence_type_table(
    profiles: dict[str, dict[str, dict[str, int]]],
) -> list[dict]:
    """Flatten profiles into rows for CSV output."""
    rows = []
    for expert in EXPERTS_NO_HOST:
        if expert not in profiles:
            continue
        for novel in sorted(profiles[expert]):
            total = sum(profiles[expert][novel].values())
            if total == 0:
                continue
            for st, count in sorted(profiles[expert][novel].items()):
                rows.append({
                    "expert": expert,
                    "novel": novel,
                    "sentence_type": st,
                    "count": count,
                    "proportion": round(count / total, 4),
                })
    return rows


# ── Output helpers ───────────────────────────────────────────────────────────


def write_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote {path}")


def print_airtime_table(rows: list[dict]) -> None:
    """Print a formatted airtime table for the transport condition."""
    transport = [r for r in rows if r["condition"] == "transport"]
    if not transport:
        print("  (no transport-condition data)")
        return

    novels = sorted({r["novel"] for r in transport})
    experts = sorted({r["expert"] for r in transport})

    # Build lookup
    lookup: dict[tuple[str, str], float] = {}
    for r in transport:
        lookup[(r["expert"], r["novel"])] = r["mean_airtime"]

    # Header
    header = f"{'Expert':<25s}" + "".join(f"{NOVEL_TITLES.get(n, n):>20s}" for n in novels)
    print(header)
    print("-" * len(header))
    for expert in experts:
        line = f"{expert:<25s}"
        for novel in novels:
            val = lookup.get((expert, novel), 0.0)
            line += f"{val:>20.3f}"
        print(line)
    print()


def print_cosine_table(cosine_rows: list[dict]) -> None:
    print(f"{'Expert':<25s}{'Mean Cosine':>15s}{'N Novels':>10s}")
    print("-" * 50)
    for r in cosine_rows:
        print(f"{r['expert']:<25s}{r['mean_cosine']:>15.4f}{r['n_novels']:>10d}")
    print()


def print_keyword_table(keyword_rows: list[dict]) -> None:
    current_expert = None
    for r in keyword_rows:
        if r["expert"] != current_expert:
            current_expert = r["expert"]
            print(f"\n  {current_expert}:")
        print(f"    {r['rank']:2d}. {r['keyword']:<20s} (tfidf={r['mean_tfidf']:.4f})")
    print()


def print_sentence_type_summary(
    profiles: dict[str, dict[str, dict[str, int]]],
) -> None:
    """Print per-expert sentence-type distribution aggregated across novels."""
    for expert in EXPERTS_NO_HOST:
        if expert not in profiles:
            continue
        agg: dict[str, int] = defaultdict(int)
        for novel_counts in profiles[expert].values():
            for st, c in novel_counts.items():
                agg[st] += c
        total = sum(agg.values())
        if total == 0:
            continue
        print(f"  {expert}:")
        for st, c in sorted(agg.items(), key=lambda x: -x[1]):
            print(f"    {st:<20s} {c:>5d}  ({c/total:.1%})")
    print()


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    tag = _timestamp_tag()
    print(f"Cross-novel expert identity analysis  [{tag}]\n")

    runs = discover_runs()
    print(f"Discovered {len(runs)} runs across {len(set(k[0] for k in runs))} novels\n")

    if not runs:
        print("No runs found — exiting.")
        sys.exit(1)

    texts, utterance_data = gather_expert_texts(runs)

    # ── Airtime ──────────────────────────────────────────────────────────
    print("=" * 60)
    print("EXPERT AIRTIME BY NOVEL (transport condition)")
    print("=" * 60)
    airtime_rows = compute_airtime(texts)
    print_airtime_table(airtime_rows)
    write_csv(airtime_rows, REPORT_DIR / f"airtime_by_novel_{tag}.csv")

    # ── TF-IDF ───────────────────────────────────────────────────────────
    print("=" * 60)
    print("CROSS-NOVEL VOCABULARY COSINE SIMILARITY")
    print("=" * 60)
    tfidf_result = tfidf_analysis(texts)
    if tfidf_result is not None:
        cosine_rows, keyword_rows = tfidf_result
        print_cosine_table(cosine_rows)
        write_csv(cosine_rows, REPORT_DIR / f"cross_novel_cosine_{tag}.csv")

        print("=" * 60)
        print("TOP KEYWORDS PER EXPERT (by mean TF-IDF)")
        print("=" * 60)
        print_keyword_table(keyword_rows)
        write_csv(keyword_rows, REPORT_DIR / f"expert_keywords_{tag}.csv")
    else:
        print("  (skipped — sklearn not available)\n")

    # ── Sentence-type profiles ───────────────────────────────────────────
    print("=" * 60)
    print("SENTENCE-TYPE BEHAVIORAL PROFILES")
    print("=" * 60)
    profiles = sentence_type_profiles(utterance_data)
    print_sentence_type_summary(profiles)
    st_rows = format_sentence_type_table(profiles)
    write_csv(st_rows, REPORT_DIR / f"sentence_type_profiles_{tag}.csv")

    print("Done.")


if __name__ == "__main__":
    main()
