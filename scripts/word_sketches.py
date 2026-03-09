"""Kilgarriff-style word sketches: grammatical relations per variant.

Uses spaCy dependency parsing to extract (relation_type, head, dependent)
triples, then applies G2 log-likelihood to find distinctive relations
per variant vs the pooled rest.
"""

import json
import math
from collections import Counter
from pathlib import Path

import spacy
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

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

# Relation types we care about (Sketch Engine style)
SKETCH_RELATIONS = {
    "amod":    "ADJ + NOUN",      # adjective modifying noun
    "nsubj":   "SUBJ + VERB",     # nominal subject
    "dobj":    "VERB + OBJ",      # direct object
    "pobj":    "PREP + NOUN",     # prepositional object
    "advmod":  "ADV + VERB",      # adverb modifying verb
    "compound": "COMPOUND",       # compound nouns
}

# Skip these lemmas in relations
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


def extract_utterance_texts(variant: str) -> list[str]:
    path = RUNS_DIR / variant / "phase3_episode.json"
    episode = json.load(open(path))
    texts = []
    for seg in episode["segments"]:
        for turn in seg["turns"]:
            for utt in turn["utterances"]:
                texts.append(utt["text"])
    return texts


def extract_relations(doc) -> list[str]:
    """Extract grammatical relation triples from a spaCy Doc.

    Returns relation strings like:
      "amod:dark+secret"  (adjective dark modifies noun secret)
      "nsubj:esther+discovers"  (subject esther of verb discovers)
      "dobj:reveals+truth"  (verb reveals takes object truth)
    """
    relations = []
    for token in doc:
        dep = token.dep_
        head_lemma = token.head.lemma_.lower()
        token_lemma = token.lemma_.lower()

        # Skip short words, punctuation, stop lemmas
        if len(token_lemma) < 3 or len(head_lemma) < 3:
            continue
        if token_lemma in STOP_LEMMAS or head_lemma in STOP_LEMMAS:
            continue
        if not token_lemma.isalpha() or not head_lemma.isalpha():
            continue

        if dep == "amod" and token.head.pos_ == "NOUN":
            # ADJ modifies NOUN
            relations.append(f"amod:{token_lemma}+{head_lemma}")
        elif dep == "nsubj" and token.head.pos_ == "VERB":
            # NOUN is subject of VERB
            relations.append(f"nsubj:{token_lemma}+{head_lemma}")
        elif dep == "dobj" and token.head.pos_ == "VERB":
            # VERB takes NOUN as object
            relations.append(f"dobj:{head_lemma}+{token_lemma}")
        elif dep == "pobj":
            # PREP + NOUN (use the preposition as head)
            prep_lemma = token.head.lemma_.lower()
            if len(prep_lemma) >= 2 and prep_lemma.isalpha():
                relations.append(f"pobj:{prep_lemma}+{token_lemma}")
        elif dep == "advmod" and token.pos_ == "ADV" and token.head.pos_ == "VERB":
            relations.append(f"advmod:{token_lemma}+{head_lemma}")
        elif dep == "compound" and token.head.pos_ == "NOUN":
            relations.append(f"compound:{token_lemma}+{head_lemma}")

    return relations


def build_relation_corpus(variant: str, nlp) -> Counter:
    texts = extract_utterance_texts(variant)
    full_text = " ".join(texts)
    # Process in chunks to avoid memory issues
    relations: list[str] = []
    for doc in nlp.pipe([full_text], n_process=1, batch_size=1):
        relations.extend(extract_relations(doc))
    return Counter(relations)


def log_likelihood(a: int, b: int, c: int, d: int) -> float:
    """G2 log-likelihood ratio for 2x2 contingency table."""
    def safe_log(x):
        return math.log(x) if x > 0 else 0
    e1 = c * (a + b) / (c + d)
    e2 = d * (a + b) / (c + d)
    if e1 == 0 or e2 == 0:
        return 0.0
    return 2 * (a * safe_log(a / e1) + b * safe_log(b / e2))


def keywords_vs_reference(target: Counter, reference: Counter, top_n: int = 30):
    c = sum(target.values())
    d = sum(reference.values())
    results = []
    for rel in target:
        a = target[rel]
        b = reference.get(rel, 0)
        if a / c <= (b + 0.5) / (d + 0.5):
            continue
        g2 = log_likelihood(a, b, c, d)
        if a >= 2:  # require at least 2 occurrences
            results.append((rel, g2, a, b))
    results.sort(key=lambda x: -x[1])
    return results[:top_n]


def format_relation(rel_str: str) -> str:
    """Format 'amod:dark+secret' as 'dark secret [ADJ+NOUN]'."""
    rel_type, pair = rel_str.split(":", 1)
    w1, w2 = pair.split("+", 1)
    labels = {
        "amod": "ADJ+NOUN",
        "nsubj": "SUBJ+VERB",
        "dobj": "VERB+OBJ",
        "pobj": "PREP+NOUN",
        "advmod": "ADV+VERB",
        "compound": "COMPOUND",
    }
    label = labels.get(rel_type, rel_type)
    return f"{w1} {w2} [{label}]"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

print("Loading spaCy en_core_web_md...")
nlp = spacy.load("en_core_web_md")

print("Extracting grammatical relations per variant...")
corpora = {}
for v in VARIANTS:
    print(f"  Processing {v}...")
    corpora[v] = build_relation_corpus(v, nlp)
    print(f"    {sum(corpora[v].values())} relations, {len(corpora[v])} unique")

# Pooled reference
pooled = Counter()
for c in corpora.values():
    pooled += c

# ---------------------------------------------------------------------------
# Distinctive relations per variant (word sketches)
# ---------------------------------------------------------------------------

print("\n=== Word Sketches: Distinctive Grammatical Relations ===\n")
report_lines = []
sketch_data = {}  # variant -> list of (formatted_rel, g2, count)

for v in VARIANTS:
    target = corpora[v]
    ref = pooled - target
    kws = keywords_vs_reference(target, ref, top_n=30)

    header = f"--- {v} ---"
    print(header)
    report_lines.append(header)

    sketch_data[v] = []

    # Group by relation type
    by_type: dict[str, list] = {}
    for rel_str, g2, tf, rf in kws:
        rel_type = rel_str.split(":")[0]
        by_type.setdefault(rel_type, []).append((rel_str, g2, tf, rf))

    for rel_type in ["amod", "nsubj", "dobj", "pobj", "advmod", "compound"]:
        if rel_type not in by_type:
            continue
        label = {
            "amod": "ADJ + NOUN",
            "nsubj": "SUBJ + VERB",
            "dobj": "VERB + OBJ",
            "pobj": "PREP + NOUN",
            "advmod": "ADV + VERB",
            "compound": "COMPOUND",
        }[rel_type]
        subheader = f"  [{label}]"
        print(subheader)
        report_lines.append(subheader)
        for rel_str, g2, tf, rf in by_type[rel_type][:5]:
            _, pair = rel_str.split(":", 1)
            w1, w2 = pair.split("+", 1)
            line = f"    {w1:15s} + {w2:15s}  G2={g2:6.1f}  n={tf}"
            print(line)
            report_lines.append(line)
            sketch_data[v].append((f"{w1}+{w2}", g2, tf))
    print()
    report_lines.append("")

# Save report
with open(OUT_DIR / "word_sketches.txt", "w") as f:
    f.write("\n".join(report_lines))
print(f"Saved: {OUT_DIR / 'word_sketches.txt'}")

# ---------------------------------------------------------------------------
# Visualization: relation heatmap by type
# ---------------------------------------------------------------------------

print("\nGenerating sketch visualizations...")

# Collect top relations per variant for a summary table
fig, axes = plt.subplots(2, 4, figsize=(28, 14))
axes_flat = axes.flatten()

for idx, v in enumerate(VARIANTS):
    ax = axes_flat[idx]

    # Get top 20 relations for this variant
    target = corpora[v]
    ref = pooled - target
    kws = keywords_vs_reference(target, ref, top_n=20)

    if not kws:
        ax.set_title(v, fontsize=10)
        ax.axis("off")
        continue

    # Bar chart of top relations
    labels = []
    scores = []
    colors = []
    color_map = {
        "amod": "#e41a1c",
        "nsubj": "#377eb8",
        "dobj": "#4daf4a",
        "pobj": "#984ea3",
        "advmod": "#ff7f00",
        "compound": "#a65628",
    }

    for rel_str, g2, tf, rf in kws[:12]:
        rel_type, pair = rel_str.split(":", 1)
        w1, w2 = pair.split("+", 1)
        labels.append(f"{w1}+{w2}")
        scores.append(g2)
        colors.append(color_map.get(rel_type, "#999999"))

    y_pos = range(len(labels) - 1, -1, -1)
    ax.barh(list(y_pos), scores, color=colors, height=0.7)
    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("G2 score", fontsize=8)
    ax.set_title(v, fontsize=10, fontweight="bold")

# Legend
from matplotlib.patches import Patch
legend_elements = [
    Patch(facecolor="#e41a1c", label="ADJ+NOUN"),
    Patch(facecolor="#377eb8", label="SUBJ+VERB"),
    Patch(facecolor="#4daf4a", label="VERB+OBJ"),
    Patch(facecolor="#984ea3", label="PREP+NOUN"),
    Patch(facecolor="#ff7f00", label="ADV+VERB"),
    Patch(facecolor="#a65628", label="COMPOUND"),
]
fig.legend(handles=legend_elements, loc="lower center", ncol=6, fontsize=10)

plt.suptitle("Distinctive Grammatical Relations by Variant (Kilgarriff G2 Word Sketches)",
             fontsize=14, fontweight="bold")
plt.tight_layout(rect=[0, 0.04, 1, 0.96])
plt.savefig(OUT_DIR / "word_sketches.png", dpi=150, bbox_inches="tight")
print(f"Saved: {OUT_DIR / 'word_sketches.png'}")
