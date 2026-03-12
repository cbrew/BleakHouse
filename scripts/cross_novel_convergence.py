"""Cross-novel convergence paradox test.

Do transport and embedding select disjoint passages but produce convergent
scripts?  For each novel and panel that has both transport and embedding runs,
compute passage-level divergence metrics and script-level convergence metrics.

Outputs:
  reports/cross_novel_convergence/convergence_by_novel.csv
  reports/cross_novel_convergence/convergence_summary.csv
  Console formatted table of per-novel means.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from cross_novel_loader import (
    ALL_EXPERTS,
    NOVEL_TITLES,
    PANEL_IDS,
    PROVISION_DIMS,
    discover_runs,
    extract_turns,
    get_vocab_words,
    load_assignments,
    load_episode,
    load_novel_characters,
    build_char_patterns,
)

OUT_DIR = Path(__file__).resolve().parent.parent / "reports" / "cross_novel_convergence"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PROV_MAP = {"none": 0, "weak": 1, "strong": 2}


# ── passage-level metrics ──────────────────────────────────────────────


def passage_jaccard(trn_assigns: list[dict], emb_assigns: list[dict]) -> float:
    trn_pids = {a["passage_id"] for a in trn_assigns}
    emb_pids = {a["passage_id"] for a in emb_assigns}
    if not trn_pids and not emb_pids:
        return float("nan")
    return len(trn_pids & emb_pids) / len(trn_pids | emb_pids)


def chapter_jaccard(trn_assigns: list[dict], emb_assigns: list[dict]) -> float:
    trn_ch = {a["chapter_id"] for a in trn_assigns}
    emb_ch = {a["chapter_id"] for a in emb_assigns}
    if not trn_ch and not emb_ch:
        return float("nan")
    return len(trn_ch & emb_ch) / len(trn_ch | emb_ch)


def _provision_vector(assigns: list[dict]) -> np.ndarray:
    """Mean provision vector for a set of assignments (7 dims)."""
    if not assigns:
        return np.zeros(len(PROVISION_DIMS))
    vecs = []
    for a in assigns:
        provs = a.get("provisions", {})
        vec = [PROV_MAP.get(provs.get(dim, "none"), 0) for dim in PROVISION_DIMS]
        vecs.append(vec)
    return np.array(vecs, dtype=float).mean(axis=0)


def provision_centroid_distance(
    trn_assigns: list[dict], emb_assigns: list[dict]
) -> float:
    if not trn_assigns or not emb_assigns:
        return float("nan")
    trn_c = _provision_vector(trn_assigns)
    emb_c = _provision_vector(emb_assigns)
    return float(np.linalg.norm(trn_c - emb_c))


# ── script-level metrics ───────────────────────────────────────────────


def _expert_texts(episode: dict) -> dict[str, str]:
    """Concatenated text per expert from episode turns."""
    texts: dict[str, list[str]] = {}
    for turn in extract_turns(episode):
        speaker = turn["speaker"]
        if speaker in ALL_EXPERTS:
            texts.setdefault(speaker, []).append(turn["text"])
    return {k: " ".join(v) for k, v in texts.items()}


def _cosine_sim(vec_a: dict[str, int], vec_b: dict[str, int]) -> float:
    """Cosine similarity between two word-count dicts."""
    all_words = set(vec_a) | set(vec_b)
    if not all_words:
        return float("nan")
    a = np.array([vec_a.get(w, 0) for w in all_words], dtype=float)
    b = np.array([vec_b.get(w, 0) for w in all_words], dtype=float)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return float("nan")
    return float(np.dot(a, b) / denom)


def vocab_cosine_per_expert(
    trn_episode: dict, emb_episode: dict
) -> tuple[float, dict[str, float]]:
    """Mean vocabulary cosine across shared experts, plus per-expert detail."""
    trn_texts = _expert_texts(trn_episode)
    emb_texts = _expert_texts(emb_episode)
    shared = set(trn_texts) & set(emb_texts)
    per_expert: dict[str, float] = {}
    for expert in sorted(shared):
        trn_words = Counter(get_vocab_words(trn_texts[expert]))
        emb_words = Counter(get_vocab_words(emb_texts[expert]))
        per_expert[expert] = _cosine_sim(trn_words, emb_words)
    vals = [v for v in per_expert.values() if v == v]  # exclude nan
    mean_cos = sum(vals) / len(vals) if vals else float("nan")
    return mean_cos, per_expert


def _full_text(episode: dict) -> str:
    """All turn text concatenated."""
    return " ".join(t["text"] for t in extract_turns(episode))


def character_jaccard_script(
    trn_episode: dict, emb_episode: dict, novel_key: str
) -> float:
    """Jaccard of character names mentioned in each script."""
    characters = load_novel_characters(novel_key)
    if not characters:
        return float("nan")
    patterns = build_char_patterns(characters)
    trn_text = _full_text(trn_episode)
    emb_text = _full_text(emb_episode)
    trn_chars = {name for name, pat in patterns.items() if pat.search(trn_text)}
    emb_chars = {name for name, pat in patterns.items() if pat.search(emb_text)}
    if not trn_chars and not emb_chars:
        return float("nan")
    return len(trn_chars & emb_chars) / len(trn_chars | emb_chars)


# ── main ────────────────────────────────────────────────────────────────


def main() -> None:
    runs = discover_runs()

    # Group by (novel, panel) and find pairs with both transport + embedding
    pairs: dict[tuple[str, str], dict[str, Path]] = {}
    for (novel, cond, panel), run_dir in runs.items():
        if cond in ("transport", "embedding"):
            pairs.setdefault((novel, panel), {})[cond] = run_dir

    rows: list[dict[str, object]] = []

    for (novel, panel), cond_dirs in sorted(pairs.items()):
        if "transport" not in cond_dirs or "embedding" not in cond_dirs:
            continue

        trn_dir = cond_dirs["transport"]
        emb_dir = cond_dirs["embedding"]

        trn_assigns = load_assignments(trn_dir)
        emb_assigns = load_assignments(emb_dir)
        trn_episode = load_episode(trn_dir)
        emb_episode = load_episode(emb_dir)

        pj = passage_jaccard(trn_assigns, emb_assigns)
        cj = chapter_jaccard(trn_assigns, emb_assigns)
        pd = provision_centroid_distance(trn_assigns, emb_assigns)
        vc, vc_detail = vocab_cosine_per_expert(trn_episode, emb_episode)
        cc = character_jaccard_script(trn_episode, emb_episode, novel)

        rows.append({
            "novel": novel,
            "novel_title": NOVEL_TITLES.get(novel, novel),
            "panel": panel,
            "passage_jaccard": pj,
            "chapter_jaccard": cj,
            "provision_distance": pd,
            "vocab_cosine": vc,
            "char_jaccard": cc,
        })

    if not rows:
        print("No transport/embedding pairs found.")
        sys.exit(0)

    # ── write per-panel CSV ─────────────────────────────────────────────

    fieldnames = [
        "novel", "novel_title", "panel",
        "passage_jaccard", "chapter_jaccard", "provision_distance",
        "vocab_cosine", "char_jaccard",
    ]
    by_novel_path = OUT_DIR / "convergence_by_novel.csv"
    with open(by_novel_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {by_novel_path}")

    # ── compute per-novel means ─────────────────────────────────────────

    novel_groups: dict[str, list[dict[str, object]]] = {}
    for r in rows:
        novel_groups.setdefault(str(r["novel"]), []).append(r)

    metric_keys = [
        "passage_jaccard", "chapter_jaccard", "provision_distance",
        "vocab_cosine", "char_jaccard",
    ]
    summary_rows: list[dict[str, object]] = []
    for novel in sorted(novel_groups):
        group = novel_groups[novel]
        means: dict[str, object] = {
            "novel": novel,
            "novel_title": NOVEL_TITLES.get(novel, novel),
            "n_panels": len(group),
        }
        for mk in metric_keys:
            vals = [float(r[mk]) for r in group if r[mk] == r[mk]]  # type: ignore[arg-type]
            means[mk] = sum(vals) / len(vals) if vals else float("nan")
        summary_rows.append(means)

    summary_path = OUT_DIR / "convergence_summary.csv"
    summary_fields = ["novel", "novel_title", "n_panels"] + metric_keys
    with open(summary_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=summary_fields)
        w.writeheader()
        w.writerows(summary_rows)
    print(f"Wrote {summary_path}")

    # ── console table ───────────────────────────────────────────────────

    col_headers = [
        ("Novel", 25),
        ("N", 4),
        ("Pass Jacc", 10),
        ("Chap Jacc", 10),
        ("Prov Dist", 10),
        ("Vocab Cos", 10),
        ("Char Jacc", 10),
    ]
    header_line = "  ".join(h.ljust(w) for h, w in col_headers)
    print()
    print(header_line)
    print("-" * len(header_line))

    def _fmt(v: object) -> str:
        if isinstance(v, float) and v != v:
            return "  ---"
        return f"{float(v):.3f}"  # type: ignore[arg-type]

    for sr in summary_rows:
        title = str(sr["novel_title"])[:25]
        n = str(sr["n_panels"])
        vals = [_fmt(sr[mk]) for mk in metric_keys]
        parts = [title.ljust(25), n.ljust(4)] + [v.ljust(10) for v in vals]
        print("  ".join(parts))

    print()
    print("Low passage/chapter Jaccard + high vocab cosine = convergence paradox.")


if __name__ == "__main__":
    main()
