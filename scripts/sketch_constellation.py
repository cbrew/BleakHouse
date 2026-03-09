"""Constellation-style visualization of grammatical relation word sketches.

Each variant is a 'constellation' — words are stars connected by grammatical
relations, sized by G2 distinctiveness, colored by relation type.
"""

import json
import math
import re
from collections import Counter
from pathlib import Path

import spacy
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.lines import Line2D

RUNS_DIR = Path("/Users/brewc/PycharmProjects/BleakHouse/data/runs")
OUT_DIR = Path("/Users/brewc/PycharmProjects/BleakHouse/reports/variant_analysis")
OUT_DIR.mkdir(parents=True, exist_ok=True)

VARIANTS = [
    "v01_baseline",
    "v02_more_jo",
    "v05_craft_v2",
    "v10_conservative",
    "v12_radical_panel",
    "v14_trevelyan_for_woodcourt",
    "v18_trevelyan_rosen",
    "v19_all_swapped",
]

VARIANT_LABELS = {
    "v01_baseline": "Baseline",
    "v02_more_jo": "More Jo",
    "v05_craft_v2": "Craft V2",
    "v10_conservative": "Conservative",
    "v12_radical_panel": "Radical Panel",
    "v14_trevelyan_for_woodcourt": "Trevelyan for Woodcourt",
    "v18_trevelyan_rosen": "Trevelyan + Rosen",
    "v19_all_swapped": "All Swapped",
}

STOP_LEMMAS = {
    "be", "have", "do", "say", "go", "get", "make", "know", "think", "take",
    "come", "see", "want", "look", "give", "use", "find", "tell", "ask",
    "seem", "feel", "try", "leave", "call", "need", "keep", "let", "begin",
    "show", "hear", "play", "run", "move", "live", "believe", "bring",
    "happen", "write", "provide", "sit", "stand", "lose", "pay", "meet",
    "include", "continue", "set", "learn", "change", "lead", "understand",
    "watch", "follow", "stop", "create", "speak", "read", "allow", "add",
    "spend", "grow", "open", "walk", "win", "offer", "remember", "love",
    "consider", "appear", "buy", "wait", "serve", "die", "send", "expect",
    "build", "stay", "fall", "cut", "reach", "kill", "remain", "suggest",
    "raise", "pass", "sell", "require", "report", "decide", "pull",
    "thing", "way", "time", "year", "people", "man", "woman", "day",
    "world", "life", "hand", "part", "place", "case", "week", "company",
    "system", "program", "question", "work", "point", "number", "room",
    "lot", "bit", "kind", "sort", "fact", "moment", "sense",
    "not", "also", "just", "very", "really", "quite", "actually", "even",
    "still", "already", "well", "much", "more", "then", "here", "there",
    "now", "only",
    "this", "that", "which", "what", "it", "he", "she", "they", "we", "i",
    "you", "one", "-pron-",
}

REL_COLORS = {
    "amod":     "#ff6b6b",   # coral red — ADJ+NOUN
    "nsubj":    "#4ecdc4",   # teal — SUBJ+VERB
    "dobj":     "#95e86b",   # lime — VERB+OBJ
    "pobj":     "#a78bfa",   # lavender — PREP+NOUN
    "advmod":   "#fbbf24",   # amber — ADV+VERB
    "compound": "#f97316",   # orange — COMPOUND
}

REL_LABELS = {
    "amod":     "adj + noun",
    "nsubj":    "subj + verb",
    "dobj":     "verb + obj",
    "pobj":     "prep + noun",
    "advmod":   "adv + verb",
    "compound": "compound",
}


def extract_utterance_texts(variant: str) -> list[str]:
    path = RUNS_DIR / variant / "phase3_episode.json"
    episode = json.load(open(path))
    texts = []
    for seg in episode["segments"]:
        for turn in seg["turns"]:
            for utt in turn["utterances"]:
                texts.append(utt["text"])
    return texts


def extract_relations(doc) -> list[tuple[str, str, str]]:
    """Extract (rel_type, word1, word2) triples."""
    relations = []
    for token in doc:
        dep = token.dep_
        head_lemma = token.head.lemma_.lower()
        token_lemma = token.lemma_.lower()
        if len(token_lemma) < 3 or len(head_lemma) < 3:
            continue
        if token_lemma in STOP_LEMMAS or head_lemma in STOP_LEMMAS:
            continue
        if not token_lemma.isalpha() or not head_lemma.isalpha():
            continue

        if dep == "amod" and token.head.pos_ == "NOUN":
            relations.append(("amod", token_lemma, head_lemma))
        elif dep == "nsubj" and token.head.pos_ == "VERB":
            relations.append(("nsubj", token_lemma, head_lemma))
        elif dep == "dobj" and token.head.pos_ == "VERB":
            relations.append(("dobj", head_lemma, token_lemma))
        elif dep == "pobj":
            prep = token.head.lemma_.lower()
            if len(prep) >= 2 and prep.isalpha():
                relations.append(("pobj", prep, token_lemma))
        elif dep == "advmod" and token.pos_ == "ADV" and token.head.pos_ == "VERB":
            relations.append(("advmod", token_lemma, head_lemma))
        elif dep == "compound" and token.head.pos_ == "NOUN":
            relations.append(("compound", token_lemma, head_lemma))
    return relations


def build_relation_corpus(variant: str, nlp) -> Counter:
    texts = extract_utterance_texts(variant)
    full_text = " ".join(texts)
    rels: list[str] = []
    for doc in nlp.pipe([full_text], n_process=1, batch_size=1):
        for rel_type, w1, w2 in extract_relations(doc):
            rels.append(f"{rel_type}:{w1}+{w2}")
    return Counter(rels)


def log_likelihood(a, b, c, d):
    def safe_log(x):
        return math.log(x) if x > 0 else 0
    e1 = c * (a + b) / (c + d)
    e2 = d * (a + b) / (c + d)
    if e1 == 0 or e2 == 0:
        return 0.0
    return 2 * (a * safe_log(a / e1) + b * safe_log(b / e2))


def keywords_vs_reference(target, reference, top_n=20):
    c = sum(target.values())
    d = sum(reference.values())
    results = []
    for rel in target:
        a = target[rel]
        b = reference.get(rel, 0)
        if a / c <= (b + 0.5) / (d + 0.5):
            continue
        g2 = log_likelihood(a, b, c, d)
        if a >= 2:
            results.append((rel, g2, a, b))
    results.sort(key=lambda x: -x[1])
    return results[:top_n]


def force_layout(nodes, edges, iterations=120, repulsion=0.8, attraction=0.02, damping=0.9):
    """Simple force-directed layout.

    nodes: list of node names
    edges: list of (node_a, node_b) pairs
    Returns dict {node_name: (x, y)}
    """
    rng = np.random.RandomState(42)
    n = len(nodes)
    if n == 0:
        return {}

    pos = rng.uniform(-1, 1, (n, 2))
    idx = {name: i for i, name in enumerate(nodes)}
    vel = np.zeros((n, 2))

    for _ in range(iterations):
        forces = np.zeros((n, 2))

        # Repulsion between all pairs
        for i in range(n):
            for j in range(i + 1, n):
                diff = pos[i] - pos[j]
                dist = max(np.linalg.norm(diff), 0.05)
                f = repulsion / (dist * dist) * diff / dist
                forces[i] += f
                forces[j] -= f

        # Attraction along edges
        for a, b in edges:
            if a in idx and b in idx:
                i, j = idx[a], idx[b]
                diff = pos[j] - pos[i]
                dist = np.linalg.norm(diff)
                f = attraction * dist * diff / max(dist, 0.01)
                forces[i] += f
                forces[j] -= f

        # Center gravity
        forces -= 0.01 * pos

        vel = damping * vel + forces
        pos += vel

    # Normalize to [-1, 1]
    if n > 1:
        pmin = pos.min(axis=0)
        pmax = pos.max(axis=0)
        span = pmax - pmin
        span[span == 0] = 1
        pos = 2 * (pos - pmin) / span - 1

    return {name: (pos[i, 0], pos[i, 1]) for i, name in enumerate(nodes)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

print("Loading spaCy...")
nlp = spacy.load("en_core_web_md")

print("Building relation corpora...")
corpora = {}
for v in VARIANTS:
    print(f"  {v}...")
    corpora[v] = build_relation_corpus(v, nlp)

pooled = Counter()
for c in corpora.values():
    pooled += c

# ---------------------------------------------------------------------------
# Build constellation data per variant
# ---------------------------------------------------------------------------

print("Computing distinctive relations...")

fig, axes = plt.subplots(2, 4, figsize=(32, 18),
                         facecolor="#0a0a1a")

for idx, v in enumerate(VARIANTS):
    ax = axes.flat[idx]
    ax.set_facecolor("#0a0a1a")

    target = corpora[v]
    ref = pooled - target
    kws = keywords_vs_reference(target, ref, top_n=18)

    if not kws:
        ax.set_title(VARIANT_LABELS[v], color="white", fontsize=13)
        ax.axis("off")
        continue

    # Collect unique words and edges
    words = set()
    edges = []
    word_max_g2 = {}
    edge_data = []  # (w1, w2, rel_type, g2)

    for rel_str, g2, tf, rf in kws:
        rel_type, pair = rel_str.split(":", 1)
        w1, w2 = pair.split("+", 1)
        words.add(w1)
        words.add(w2)
        edges.append((w1, w2))
        edge_data.append((w1, w2, rel_type, g2))
        word_max_g2[w1] = max(word_max_g2.get(w1, 0), g2)
        word_max_g2[w2] = max(word_max_g2.get(w2, 0), g2)

    words = list(words)
    pos = force_layout(words, edges)

    # Scale G2 for visual sizing
    max_g2 = max(word_max_g2.values()) if word_max_g2 else 1

    # Draw edges (relations)
    for w1, w2, rel_type, g2 in edge_data:
        if w1 in pos and w2 in pos:
            x1, y1 = pos[w1]
            x2, y2 = pos[w2]
            alpha = 0.3 + 0.5 * (g2 / max_g2)
            color = REL_COLORS.get(rel_type, "#888888")
            lw = 0.8 + 2.0 * (g2 / max_g2)
            ax.plot([x1, x2], [y1, y2], color=color, alpha=alpha,
                    linewidth=lw, solid_capstyle="round")

    # Draw nodes (words as glowing stars)
    for word in words:
        if word not in pos:
            continue
        x, y = pos[word]
        g2 = word_max_g2.get(word, 1)
        size_factor = g2 / max_g2

        # Glow effect: large faint circle + small bright circle
        glow_size = 80 + 250 * size_factor
        ax.scatter(x, y, s=glow_size * 3, color="white", alpha=0.03, zorder=1)
        ax.scatter(x, y, s=glow_size * 1.5, color="white", alpha=0.06, zorder=2)
        ax.scatter(x, y, s=glow_size * 0.5, color="white", alpha=0.15, zorder=3)
        ax.scatter(x, y, s=glow_size * 0.15, color="white", alpha=0.6, zorder=4)

        # Word label
        fontsize = 7 + 5 * size_factor
        ax.text(x, y + 0.08, word, color="white", fontsize=fontsize,
                ha="center", va="bottom", fontweight="bold",
                path_effects=[pe.withStroke(linewidth=2, foreground="#0a0a1a")])

    ax.set_xlim(-1.3, 1.3)
    ax.set_ylim(-1.3, 1.3)
    ax.set_aspect("equal")
    ax.set_title(VARIANT_LABELS[v], color="white", fontsize=14,
                 fontweight="bold", pad=10)
    ax.axis("off")

# Legend
legend_elements = [
    Line2D([0], [0], color=c, linewidth=2.5, label=REL_LABELS[r])
    for r, c in REL_COLORS.items()
]
fig.legend(handles=legend_elements, loc="lower center", ncol=6,
           fontsize=11, frameon=False,
           labelcolor="white", handlelength=2.5,
           bbox_to_anchor=(0.5, 0.01))

fig.suptitle("Word Sketch Constellations — Distinctive Grammatical Relations by Variant",
             color="white", fontsize=18, fontweight="bold", y=0.97)

plt.tight_layout(rect=[0, 0.04, 1, 0.94])
plt.savefig(OUT_DIR / "sketch_constellations.png", dpi=180,
            bbox_inches="tight", facecolor="#0a0a1a")
print(f"\nSaved: {OUT_DIR / 'sketch_constellations.png'}")
