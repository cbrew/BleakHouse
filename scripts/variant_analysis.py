"""Kilgarriff-style keyword analysis + word clouds for 8 podcast variants."""

import json
import math
import re
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from wordcloud import WordCloud

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

# Stop words: common English + podcast boilerplate
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


def extract_utterance_texts(variant: str) -> list[str]:
    """Extract all utterance texts from a variant's episode."""
    path = RUNS_DIR / variant / "phase3_episode.json"
    episode = json.load(open(path))
    texts = []
    for seg in episode["segments"]:
        for turn in seg["turns"]:
            for utt in turn["utterances"]:
                texts.append(utt["text"])
    return texts


def tokenize(text: str) -> list[str]:
    """Simple word tokenizer, lowercased, alpha-only."""
    return [w for w in re.findall(r"[a-z]+(?:'[a-z]+)?", text.lower())
            if w not in STOP and len(w) > 2]


def build_corpus(variant: str) -> Counter:
    texts = extract_utterance_texts(variant)
    words = []
    for t in texts:
        words.extend(tokenize(t))
    return Counter(words)


# ---------------------------------------------------------------------------
# Kilgarriff log-likelihood keywords
# ---------------------------------------------------------------------------

def log_likelihood(a: int, b: int, c: int, d: int) -> float:
    """Log-likelihood ratio (G2) for a 2x2 contingency table.
    a = freq in target, b = freq in reference
    c = total target tokens, d = total reference tokens
    """
    def safe_log(x):
        return math.log(x) if x > 0 else 0

    e1 = c * (a + b) / (c + d)
    e2 = d * (a + b) / (c + d)
    if e1 == 0 or e2 == 0:
        return 0.0
    g2 = 2 * (a * safe_log(a / e1) + b * safe_log(b / e2))
    return g2


def keywords_vs_reference(target: Counter, reference: Counter, top_n: int = 30) -> list[tuple[str, float, int, int]]:
    """Find words distinctively frequent in target vs reference corpus.
    Returns (word, G2_score, target_freq, reference_freq) sorted by G2.
    """
    c = sum(target.values())
    d = sum(reference.values())
    results = []
    for word in target:
        a = target[word]
        b = reference.get(word, 0)
        # Only keywords that are MORE frequent in target (relative)
        if a / c <= (b + 0.5) / (d + 0.5):
            continue
        g2 = log_likelihood(a, b, c, d)
        results.append((word, g2, a, b))
    results.sort(key=lambda x: -x[1])
    return results[:top_n]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

print("Loading corpora...")
corpora = {v: build_corpus(v) for v in VARIANTS}

# Build pooled reference (all variants combined)
pooled = Counter()
for c in corpora.values():
    pooled += c

# Per-variant stats
print("\n=== Corpus sizes ===\n")
for v in VARIANTS:
    total = sum(corpora[v].values())
    vocab = len(corpora[v])
    utts = len(extract_utterance_texts(v))
    print(f"  {v:35s}  {total:5d} tokens  {vocab:4d} types  {utts:3d} utterances")

# Kilgarriff keywords: each variant vs all-others
print("\n=== Kilgarriff Keywords (each variant vs pooled rest) ===\n")
keyword_report_lines = []
keyword_freqs = {}  # variant -> {word: G2}

for v in VARIANTS:
    target = corpora[v]
    # Reference = pooled minus target
    ref = pooled - target
    kws = keywords_vs_reference(target, ref, top_n=25)
    keyword_freqs[v] = {w: g2 for w, g2, _, _ in kws}

    header = f"--- {v} ---"
    print(header)
    keyword_report_lines.append(header)
    for word, g2, tf, rf in kws[:15]:
        line = f"  {word:20s}  G2={g2:7.1f}  target={tf:3d}  rest={rf:3d}"
        print(line)
        keyword_report_lines.append(line)
    print()
    keyword_report_lines.append("")

# Save keyword report
with open(OUT_DIR / "keywords.txt", "w") as f:
    f.write("\n".join(keyword_report_lines))

# ---------------------------------------------------------------------------
# Word clouds: one per variant, sized by G2 keyword score
# ---------------------------------------------------------------------------

print("Generating word clouds...")

fig, axes = plt.subplots(2, 4, figsize=(24, 12))
axes_flat = axes.flatten()

for idx, v in enumerate(VARIANTS):
    freqs = keyword_freqs[v]
    if not freqs:
        continue
    wc = WordCloud(
        width=600, height=400,
        background_color="white",
        max_words=40,
        colormap="Dark2",
        prefer_horizontal=0.7,
    ).generate_from_frequencies(freqs)
    ax = axes_flat[idx]
    ax.imshow(wc, interpolation="bilinear")
    # Short label
    label = v.replace("v01_", "").replace("v02_", "").replace("v05_", "").replace("v10_", "").replace("v12_", "").replace("v14_", "").replace("v18_", "").replace("v19_", "")
    ax.set_title(v, fontsize=11, fontweight="bold")
    ax.axis("off")

plt.suptitle("Distinctive Keywords by Variant (Kilgarriff G2)", fontsize=14, fontweight="bold")
plt.tight_layout()
plt.savefig(OUT_DIR / "keyword_clouds.png", dpi=150, bbox_inches="tight")
print(f"  Saved: {OUT_DIR / 'keyword_clouds.png'}")

# ---------------------------------------------------------------------------
# Pairwise comparison: most different pairs
# ---------------------------------------------------------------------------

print("\n=== Pairwise Lexical Distance (Kilgarriff chi-squared) ===\n")

def chi_sq_distance(c1: Counter, c2: Counter, top_n: int = 500) -> float:
    """Kilgarriff chi-squared distance between two frequency profiles."""
    # Use the top_n most frequent words across both
    combined = c1 + c2
    top_words = [w for w, _ in combined.most_common(top_n)]
    n1 = sum(c1.values())
    n2 = sum(c2.values())
    if n1 == 0 or n2 == 0:
        return 0.0
    dist = 0.0
    for w in top_words:
        f1 = c1.get(w, 0) / n1
        f2 = c2.get(w, 0) / n2
        expected = (f1 + f2) / 2
        if expected > 0:
            dist += (f1 - f2) ** 2 / expected
    return dist

pairs = []
for i, v1 in enumerate(VARIANTS):
    for v2 in VARIANTS[i+1:]:
        d = chi_sq_distance(corpora[v1], corpora[v2])
        pairs.append((v1, v2, d))

pairs.sort(key=lambda x: -x[2])

print("Most DIFFERENT:")
for v1, v2, d in pairs[:5]:
    print(f"  {v1:35s} vs {v2:35s}  chi2={d:.4f}")

print("\nMost SIMILAR:")
for v1, v2, d in pairs[-5:]:
    print(f"  {v1:35s} vs {v2:35s}  chi2={d:.4f}")

# ---------------------------------------------------------------------------
# Speaker distribution per variant
# ---------------------------------------------------------------------------

print("\n=== Speaker Distribution (turns per speaker) ===\n")

for v in VARIANTS:
    path = RUNS_DIR / v / "phase3_episode.json"
    episode = json.load(open(path))
    speaker_turns = Counter()
    speaker_utts = Counter()
    for seg in episode["segments"]:
        for turn in seg["turns"]:
            speaker_turns[turn["speaker"]] += 1
            speaker_utts[turn["speaker"]] += len(turn["utterances"])
    parts = []
    for spk in sorted(speaker_turns, key=lambda s: -speaker_utts[s]):
        parts.append(f"{spk}={speaker_turns[spk]}t/{speaker_utts[spk]}u")
    print(f"  {v:35s}  {', '.join(parts)}")

print(f"\nAll outputs saved to {OUT_DIR}/")
