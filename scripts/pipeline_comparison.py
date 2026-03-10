"""Compare transport vs embedding pipeline variants across matched configurations.

Produces:
- Passage overlap (Jaccard) between matched transport/embedding pairs
- Chapter coverage comparison
- Provision strength comparison
- Expert balance comparison
- Kilgarriff G2 keywords: transport vs embedding for each config
- Summary statistics
"""

import json
import math
import re
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RUNS_DIR = Path(__file__).resolve().parent.parent / "data" / "runs"
OUT_DIR = Path(__file__).resolve().parent.parent / "reports" / "pipeline_comparison"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Matched pairs: (transport_variant, embedding_variant, short_label)
PAIRS = [
    ("v01_baseline",                "emb_v01_baseline",                "baseline"),
    ("v02_more_jo",                 "emb_v02_more_jo",                 "more_jo"),
    ("v05_craft_v2",                "emb_v05_craft_v2",                "craft_v2"),
    ("v10_conservative",            "emb_v10_conservative",            "conservative"),
    ("v12_radical_panel",           "emb_v12_radical_panel",           "radical_panel"),
    ("v14_trevelyan_for_woodcourt", "emb_v14_trevelyan_for_woodcourt", "trevelyan_woodcourt"),
    ("v18_trevelyan_rosen",         "emb_v18_trevelyan_rosen",         "trevelyan_rosen"),
    ("v19_all_swapped",             "emb_v19_all_swapped",             "all_swapped"),
]

STOP = set("""
the a an and or but in on at to for of is it that this with from by as be
was were are been has have had do does did will would could should may might
can shall not no nor so if then than too very just also how what when where
who which its i you he she we they me him her us them my your his our their
one two three s t d ll ve re m don doesn isn wasn weren didn wouldn couldn
about after all before between each even more much most other some such
than these those through under until up well here there now out over back
think know say see go come make like get take want look give find tell
said says think going really quite something actually know well right
yes yeah oh ah um uh okay course think mean
""".split())

PROVISION_DIMS = [
    "prov_character_development", "prov_plot_advancement",
    "prov_thematic_depth", "prov_social_critique",
    "prov_humor_entertainment", "prov_atmosphere_setting",
    "prov_narrative_technique",
]


def load_assignments(variant: str) -> list[dict]:
    path = RUNS_DIR / variant / "phase1_assignments.json"
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)["assignments"]


def load_episode(variant: str) -> dict | None:
    path = RUNS_DIR / variant / "phase3_episode.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def passage_ids(assignments: list[dict]) -> set[str]:
    return {a["passage_id"] for a in assignments}


def chapter_ids(assignments: list[dict]) -> set[str]:
    return {a["chapter_id"] for a in assignments}


def provision_strength(assignments: list[dict]) -> float:
    """Mean total provision strength across assignments."""
    if not assignments:
        return 0.0
    strengths = []
    for a in assignments:
        provs = a.get("provisions", {})
        total = sum(
            2 if v == "strong" else 1 if v == "weak" else 0
            for d in PROVISION_DIMS
            for v in [provs.get(d, "none")]
        )
        strengths.append(total)
    return sum(strengths) / len(strengths)


def expert_distribution(assignments: list[dict]) -> Counter:
    return Counter(a["expert"] for a in assignments)


def tokenize(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]+(?:'[a-z]+)?", text.lower())
            if w not in STOP and len(w) > 2]


def build_corpus_from_episode(episode: dict) -> Counter:
    words: list[str] = []
    for seg in episode["segments"]:
        for turn in seg["turns"]:
            for utt in turn["utterances"]:
                words.extend(tokenize(utt["text"]))
    return Counter(words)


def log_likelihood(a: int, b: int, c: int, d: int) -> float:
    def safe_log(x: float) -> float:
        return math.log(x) if x > 0 else 0.0
    e1 = c * (a + b) / (c + d)
    e2 = d * (a + b) / (c + d)
    if e1 == 0 or e2 == 0:
        return 0.0
    return 2 * (a * safe_log(a / e1) + b * safe_log(b / e2))


def keywords_vs_reference(target: Counter, reference: Counter, top_n: int = 20) -> list[tuple[str, float, int, int]]:
    c = sum(target.values())
    d = sum(reference.values())
    results = []
    for word in target:
        a = target[word]
        b = reference.get(word, 0)
        if a / c <= (b + 0.5) / (d + 0.5):
            continue
        g2 = log_likelihood(a, b, c, d)
        results.append((word, g2, a, b))
    results.sort(key=lambda x: -x[1])
    return results[:top_n]


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

lines: list[str] = []


def out(s: str = "") -> None:
    print(s)
    lines.append(s)


out("=" * 70)
out("TRANSPORT vs EMBEDDING PIPELINE COMPARISON")
out("=" * 70)

# Check which pairs are available
available_pairs = []
for tv, ev, label in PAIRS:
    t_assigns = load_assignments(tv)
    e_assigns = load_assignments(ev)
    if t_assigns and e_assigns:
        available_pairs.append((tv, ev, label, t_assigns, e_assigns))
    else:
        out(f"  [SKIP] {label}: missing data (transport={bool(t_assigns)}, embedding={bool(e_assigns)})")

out(f"\n{len(available_pairs)} of {len(PAIRS)} matched pairs available\n")

# ---------------------------------------------------------------------------
# 1. Passage overlap
# ---------------------------------------------------------------------------
out("\n--- 1. Passage Overlap (Jaccard) ---\n")
out(f"  {'Config':<22s} {'Transport':<10s} {'Embedding':<10s} {'Overlap':<8s} {'Jaccard':<8s}")
out(f"  {'-'*22} {'-'*10} {'-'*10} {'-'*8} {'-'*8}")

all_jaccard = []
for tv, ev, label, t_a, e_a in available_pairs:
    t_ids = passage_ids(t_a)
    e_ids = passage_ids(e_a)
    overlap = len(t_ids & e_ids)
    union = len(t_ids | e_ids)
    j = overlap / union if union > 0 else 0
    all_jaccard.append(j)
    out(f"  {label:<22s} {len(t_ids):<10d} {len(e_ids):<10d} {overlap:<8d} {j:<8.3f}")

if all_jaccard:
    out(f"\n  Mean Jaccard: {sum(all_jaccard)/len(all_jaccard):.3f}")

# ---------------------------------------------------------------------------
# 2. Chapter coverage
# ---------------------------------------------------------------------------
out("\n\n--- 2. Chapter Coverage ---\n")
out(f"  {'Config':<22s} {'Transport':<10s} {'Embedding':<10s} {'Shared':<8s}")
out(f"  {'-'*22} {'-'*10} {'-'*10} {'-'*8}")

for tv, ev, label, t_a, e_a in available_pairs:
    t_ch = chapter_ids(t_a)
    e_ch = chapter_ids(e_a)
    shared = len(t_ch & e_ch)
    out(f"  {label:<22s} {len(t_ch):<10d} {len(e_ch):<10d} {shared:<8d}")

# ---------------------------------------------------------------------------
# 3. Provision strength
# ---------------------------------------------------------------------------
out("\n\n--- 3. Mean Provision Strength ---\n")
out(f"  {'Config':<22s} {'Transport':<10s} {'Embedding':<10s} {'Delta':<8s}")
out(f"  {'-'*22} {'-'*10} {'-'*10} {'-'*8}")

for tv, ev, label, t_a, e_a in available_pairs:
    t_str = provision_strength(t_a)
    e_str = provision_strength(e_a)
    delta = t_str - e_str
    out(f"  {label:<22s} {t_str:<10.2f} {e_str:<10.2f} {delta:+.2f}")

# ---------------------------------------------------------------------------
# 4. Expert balance
# ---------------------------------------------------------------------------
out("\n\n--- 4. Expert Distribution ---\n")

for tv, ev, label, t_a, e_a in available_pairs:
    t_dist = expert_distribution(t_a)
    e_dist = expert_distribution(e_a)
    all_experts = sorted(set(t_dist) | set(e_dist))
    out(f"  {label}:")
    for exp in all_experts:
        out(f"    {exp:<30s}  transport={t_dist.get(exp, 0):2d}  embedding={e_dist.get(exp, 0):2d}")
    out()

# ---------------------------------------------------------------------------
# 5. Vocabulary comparison (needs Phase 3 episodes)
# ---------------------------------------------------------------------------
out("\n--- 5. Kilgarriff Keywords: Transport vs Embedding ---\n")

for tv, ev, label, t_a, e_a in available_pairs:
    t_ep = load_episode(tv)
    e_ep = load_episode(ev)
    if not t_ep or not e_ep:
        out(f"  {label}: [SKIP - missing episode]")
        continue

    t_corpus = build_corpus_from_episode(t_ep)
    e_corpus = build_corpus_from_episode(e_ep)

    out(f"  {label} — transport tokens={sum(t_corpus.values())}, embedding tokens={sum(e_corpus.values())}")

    t_kws = keywords_vs_reference(t_corpus, e_corpus, top_n=10)
    e_kws = keywords_vs_reference(e_corpus, t_corpus, top_n=10)

    out(f"    Transport keywords: {', '.join(w for w,_,_,_ in t_kws[:8])}")
    out(f"    Embedding keywords: {', '.join(w for w,_,_,_ in e_kws[:8])}")
    out()

# ---------------------------------------------------------------------------
# 6. Arc coverage (which arcs are represented)
# ---------------------------------------------------------------------------
out("\n--- 6. Arc Coverage ---\n")
out(f"  {'Config':<22s} {'Pipeline':<12s} Arcs")
out(f"  {'-'*22} {'-'*12} {'-'*40}")

for tv, ev, label, t_a, e_a in available_pairs:
    t_arcs = Counter(a.get("arc_name", "") for a in t_a if a.get("arc_name"))
    e_arcs = Counter(a.get("arc_name", "") for a in e_a if a.get("arc_name"))
    t_arc_str = ", ".join(f"{k}={v}" for k, v in sorted(t_arcs.items()))
    e_arc_str = ", ".join(f"{k}={v}" for k, v in sorted(e_arcs.items()))
    out(f"  {label:<22s} {'transport':<12s} {t_arc_str}")
    out(f"  {'':<22s} {'embedding':<12s} {e_arc_str}")
    out()

# ---------------------------------------------------------------------------
# 7. Summary
# ---------------------------------------------------------------------------
out("\n" + "=" * 70)
out("SUMMARY")
out("=" * 70)

if all_jaccard:
    out(f"\nPassage selection overlap is {'low' if sum(all_jaccard)/len(all_jaccard) < 0.2 else 'moderate' if sum(all_jaccard)/len(all_jaccard) < 0.5 else 'high'} "
        f"(mean Jaccard = {sum(all_jaccard)/len(all_jaccard):.3f})")
    out("The two pipelines select substantially different passages for the same configurations.")

out()

# Save report
with open(OUT_DIR / "comparison_report.txt", "w") as f:
    f.write("\n".join(lines))
out(f"\nReport saved to {OUT_DIR / 'comparison_report.txt'}")

# ---------------------------------------------------------------------------
# Visualization: passage overlap heatmap
# ---------------------------------------------------------------------------

if len(available_pairs) >= 2:
    labels = [label for _, _, label, _, _ in available_pairs]
    n = len(labels) * 2  # transport + embedding for each
    all_variants = []
    all_assigns = []
    for tv, ev, label, t_a, e_a in available_pairs:
        all_variants.append(f"T:{label}")
        all_assigns.append(passage_ids(t_a))
        all_variants.append(f"E:{label}")
        all_assigns.append(passage_ids(e_a))

    # Jaccard matrix
    import numpy as np
    matrix = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if i == j:
                matrix[i][j] = 1.0
            else:
                inter = len(all_assigns[i] & all_assigns[j])
                union = len(all_assigns[i] | all_assigns[j])
                matrix[i][j] = inter / union if union > 0 else 0

    fig, ax = plt.subplots(figsize=(14, 12))
    im = ax.imshow(matrix, cmap="YlOrRd", vmin=0, vmax=1)
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(all_variants, rotation=45, ha="right", fontsize=8)
    ax.set_yticklabels(all_variants, fontsize=8)
    for i in range(n):
        for j in range(n):
            ax.text(j, i, f"{matrix[i][j]:.2f}", ha="center", va="center",
                    fontsize=6, color="white" if matrix[i][j] > 0.5 else "black")
    plt.colorbar(im, label="Jaccard Similarity")
    ax.set_title("Passage Selection Overlap: Transport (T) vs Embedding (E) Variants")
    plt.tight_layout()
    plt.savefig(OUT_DIR / "overlap_heatmap.png", dpi=150, bbox_inches="tight")
    out(f"Heatmap saved to {OUT_DIR / 'overlap_heatmap.png'}")
