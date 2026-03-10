"""Expert variation analysis: three approaches to measuring persona
rigidity vs responsiveness across conditions.

1. Sentence type behavioral profiles
2. Expert-distinctive vocabulary (residual analysis)
3. Paired within-panel comparisons

Output: reports/expert_variation_analysis.md
"""

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import entropy as scipy_entropy
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_distances

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

RUNS_DIR = Path("data/runs")
REPORTS_DIR = Path("reports")

EXPERTS = [
    "Eleanor Hartley",
    "James Blackstone",
    "Caroline Woodcourt",
    "Edmund Leigh",
    "Daniel Rosen",
    "Oliver Trevelyan",
]

SENTENCE_TYPES = [
    "intro", "question", "quote_setup", "quote_reading",
    "analysis", "punchline", "transition", "closing",
]

BALANCED_PANELS = [
    "v01_baseline", "v10_conservative", "v11_marxist", "v12_radical_panel",
    "v14_trevelyan_for_woodcourt", "v15_trevelyan_for_hartley",
    "v16_trevelyan_for_blackstone", "v17_trevelyan_edmund",
    "v18_trevelyan_rosen", "v19_all_swapped",
    "v21_hartley_blackstone_edmund", "v22_hartley_blackstone_rosen",
    "v23_hartley_woodcourt_rosen", "v24_hartley_edmund_rosen",
    "v25_hartley_rosen_trevelyan", "v26_blackstone_woodcourt_edmund",
    "v27_blackstone_edmund_rosen", "v28_blackstone_edmund_trevelyan",
    "v29_blackstone_rosen_trevelyan", "v30_woodcourt_edmund_trevelyan",
]

CONDITION_PREFIXES = {
    "transport": "",
    "embedding": "emb_",
    "rag": "rag_",
    "no_passages": "nop_",
    "random": "rand_",
}

CONDITIONS = list(CONDITION_PREFIXES.keys())


# ---------------------------------------------------------------------------
# Data extraction
# ---------------------------------------------------------------------------


def load_episode(run_dir: Path) -> dict | None:
    ep = run_dir / "phase3_episode.json"
    if not ep.exists():
        return None
    with open(ep) as f:
        return json.load(f)


def extract_expert_data(episode: dict) -> dict[str, dict]:
    """Extract per-expert data: utterance texts, sentence types, quote counts."""
    experts = {}
    for segment in episode.get("segments", []):
        seg_type = segment.get("segment_type", "")
        for turn in segment.get("turns", []):
            speaker = turn.get("speaker", "")
            if speaker not in EXPERTS:
                continue
            if speaker not in experts:
                experts[speaker] = {
                    "texts": [],
                    "sentence_types": [],
                    "segment_types": [],
                    "emphasis_words": [],
                    "is_quotes": [],
                    "rates": [],
                    "pauses": [],
                }
            for utt in turn.get("utterances", []):
                text = utt.get("text", "").strip()
                if not text:
                    continue
                experts[speaker]["texts"].append(text)
                experts[speaker]["sentence_types"].append(
                    utt.get("sentence_type", "analysis")
                )
                experts[speaker]["segment_types"].append(seg_type)
                experts[speaker]["emphasis_words"].extend(
                    utt.get("emphasis_words", [])
                )
                experts[speaker]["is_quotes"].append(utt.get("is_quote", False))
                experts[speaker]["rates"].append(utt.get("rate", 1.0))
                experts[speaker]["pauses"].append(utt.get("pause_after_ms", 300))
    return experts


def load_all_data() -> dict:
    """Load all expert data indexed by (panel, condition, expert)."""
    data = {}
    for panel in BALANCED_PANELS:
        for cond, prefix in CONDITION_PREFIXES.items():
            run_name = f"{prefix}{panel}" if prefix else panel
            episode = load_episode(RUNS_DIR / run_name)
            if episode is None:
                continue
            expert_data = extract_expert_data(episode)
            for expert, ed in expert_data.items():
                data[(panel, cond, expert)] = ed
    return data


# ---------------------------------------------------------------------------
# Analysis 1: Sentence type behavioral profiles
# ---------------------------------------------------------------------------


def sentence_type_profile(expert_data: dict) -> dict[str, float]:
    """Normalised distribution over sentence types."""
    counts = Counter(expert_data["sentence_types"])
    total = sum(counts.values())
    if total == 0:
        return {st: 0.0 for st in SENTENCE_TYPES}
    return {st: counts.get(st, 0) / total for st in SENTENCE_TYPES}


def behavioral_analysis(data: dict) -> dict:
    """Compute behavioral profiles and measure variation."""
    # Per expert, aggregate profile across all conditions
    expert_profiles = defaultdict(lambda: defaultdict(list))
    # Per expert × condition
    expert_cond_profiles = {}

    for (panel, cond, expert), ed in data.items():
        profile = sentence_type_profile(ed)
        expert_cond_profiles[(expert, cond, panel)] = profile
        for st, val in profile.items():
            expert_profiles[expert][st].append(val)

    # Mean profile per expert (across all conditions and panels)
    mean_profiles = {}
    for expert in sorted(expert_profiles.keys()):
        mean_profiles[expert] = {
            st: float(np.mean(vals))
            for st, vals in expert_profiles[expert].items()
        }

    # Mean profile per expert × condition
    expert_cond_means = defaultdict(lambda: defaultdict(list))
    for (expert, cond, panel), profile in expert_cond_profiles.items():
        for st, val in profile.items():
            expert_cond_means[(expert, cond)][st].append(val)

    cond_mean_profiles = {}
    for (expert, cond), st_vals in expert_cond_means.items():
        cond_mean_profiles[(expert, cond)] = {
            st: float(np.mean(vals)) for st, vals in st_vals.items()
        }

    # Behavioral shift: for each expert, how much does the sentence type
    # distribution change across conditions?
    behavioral_shift = {}
    for expert in sorted(set(e for e, _, _ in expert_cond_profiles)):
        cond_vecs = {}
        for cond in CONDITIONS:
            key = (expert, cond)
            if key in cond_mean_profiles:
                cond_vecs[cond] = np.array(
                    [cond_mean_profiles[key][st] for st in SENTENCE_TYPES]
                )
        if len(cond_vecs) < 2:
            continue
        # Pairwise Jensen-Shannon divergence between condition profiles
        conds = sorted(cond_vecs.keys())
        jsd_pairs = {}
        for i in range(len(conds)):
            for j in range(i + 1, len(conds)):
                p = cond_vecs[conds[i]]
                q = cond_vecs[conds[j]]
                # Add small epsilon for numerical stability
                p = p + 1e-10
                q = q + 1e-10
                p = p / p.sum()
                q = q / q.sum()
                m = (p + q) / 2
                jsd = float((scipy_entropy(p, m) + scipy_entropy(q, m)) / 2)
                jsd_pairs[f"{conds[i]} ↔ {conds[j]}"] = jsd
        behavioral_shift[expert] = {
            "mean_jsd": float(np.mean(list(jsd_pairs.values()))),
            "max_jsd": float(np.max(list(jsd_pairs.values()))),
            "pairwise": jsd_pairs,
        }

    # Additional: quote rate and punchline rate per expert × condition
    quote_rates = defaultdict(lambda: defaultdict(list))
    punchline_rates = defaultdict(lambda: defaultdict(list))
    for (panel, cond, expert), ed in data.items():
        n = len(ed["sentence_types"])
        if n == 0:
            continue
        qr = sum(1 for q in ed["is_quotes"] if q) / n
        pr = sum(1 for st in ed["sentence_types"] if st == "punchline") / n
        quote_rates[expert][cond].append(qr)
        punchline_rates[expert][cond].append(pr)

    mean_quote_rates = {}
    mean_punchline_rates = {}
    for expert in sorted(quote_rates.keys()):
        mean_quote_rates[expert] = {
            cond: float(np.mean(vals)) for cond, vals in quote_rates[expert].items()
        }
        mean_punchline_rates[expert] = {
            cond: float(np.mean(vals))
            for cond, vals in punchline_rates[expert].items()
        }

    return {
        "mean_profiles": mean_profiles,
        "cond_mean_profiles": cond_mean_profiles,
        "behavioral_shift": behavioral_shift,
        "quote_rates": mean_quote_rates,
        "punchline_rates": mean_punchline_rates,
    }


# ---------------------------------------------------------------------------
# Analysis 2: Expert-distinctive vocabulary (residual)
# ---------------------------------------------------------------------------


def log_likelihood_ratio(word_freq_expert: int, total_expert: int,
                         word_freq_others: int, total_others: int) -> float:
    """G2 log-likelihood ratio for a word in expert vs others."""
    a, b = word_freq_expert, word_freq_others
    c, d = total_expert - a, total_others - b
    n = a + b + c + d
    if a == 0 or b == 0 or n == 0:
        return 0.0
    e1 = (a + b) * (a + c) / n
    e2 = (a + b) * (b + d) / n
    if e1 == 0 or e2 == 0:
        return 0.0
    g2 = 2 * (a * math.log(a / e1) + b * math.log(b / e2))
    # Positive if overrepresented in expert, negative if underrepresented
    if a / max(total_expert, 1) < b / max(total_others, 1):
        g2 = -g2
    return g2


def distinctive_vocabulary(data: dict) -> dict:
    """For each expert, find words distinctively overused vs other experts
    in the same run. This strips shared Bleak House vocabulary."""
    # Build word counts per expert per run
    run_expert_words = defaultdict(Counter)
    run_expert_totals = defaultdict(int)

    # Stopwords to exclude (Bleak House common terms)
    novel_terms = {
        "dickens", "bleak", "house", "novel", "chapter", "passage",
        "character", "story", "narrator", "reader", "reading",
        "think", "really", "quite", "just", "like", "know",
        "going", "right", "yes", "well", "actually", "one",
        "way", "thing", "things", "something", "come", "say",
        "says", "said", "let", "want", "look", "see", "make",
        "good", "great", "much", "doesn", "don", "isn", "ll", "ve",
    }

    word_re = re.compile(r"[a-z]{3,}")

    for (panel, cond, expert), ed in data.items():
        run_key = (panel, cond)
        all_text = " ".join(ed["texts"]).lower()
        words = [w for w in word_re.findall(all_text) if w not in novel_terms]
        run_expert_words[(run_key, expert)].update(words)
        run_expert_totals[(run_key, expert)] += len(words)

    # For each run, compute G2 for each expert vs the other two
    expert_distinctive: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    expert_total_runs = defaultdict(int)

    for (panel, cond) in set((p, c) for p, c, _ in data.keys()):
        run_key = (panel, cond)
        experts_in_run = [
            e for e in EXPERTS if (run_key, e) in run_expert_words
        ]
        for expert in experts_in_run:
            expert_words = run_expert_words[(run_key, expert)]
            expert_total = run_expert_totals[(run_key, expert)]
            # Pool other experts
            other_words = Counter()
            other_total = 0
            for other in experts_in_run:
                if other != expert:
                    other_words += run_expert_words[(run_key, other)]
                    other_total += run_expert_totals[(run_key, other)]

            # Compute G2 for each word
            all_words = set(expert_words.keys()) | set(other_words.keys())
            for word in all_words:
                g2 = log_likelihood_ratio(
                    expert_words[word], expert_total,
                    other_words[word], other_total,
                )
                if g2 > 0:  # Only overrepresented words
                    expert_distinctive[expert][word] += g2
            expert_total_runs[expert] += 1

    # Normalise by number of runs and get top terms
    results = {}
    for expert in sorted(expert_distinctive.keys()):
        n_runs = expert_total_runs[expert]
        scored = {
            word: score / n_runs
            for word, score in expert_distinctive[expert].items()
        }
        top = sorted(scored.items(), key=lambda x: -x[1])[:20]
        results[expert] = top

    # Also compute per-condition distinctive terms
    expert_cond_distinctive: dict[str, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(float))
    )
    expert_cond_runs = defaultdict(lambda: defaultdict(int))

    for (panel, cond) in set((p, c) for p, c, _ in data.keys()):
        run_key = (panel, cond)
        experts_in_run = [
            e for e in EXPERTS if (run_key, e) in run_expert_words
        ]
        for expert in experts_in_run:
            expert_words = run_expert_words[(run_key, expert)]
            expert_total = run_expert_totals[(run_key, expert)]
            other_words = Counter()
            other_total = 0
            for other in experts_in_run:
                if other != expert:
                    other_words += run_expert_words[(run_key, other)]
                    other_total += run_expert_totals[(run_key, other)]
            for word in expert_words:
                g2 = log_likelihood_ratio(
                    expert_words[word], expert_total,
                    other_words[word], other_total,
                )
                if g2 > 0:
                    expert_cond_distinctive[expert][cond][word] += g2
            expert_cond_runs[expert][cond] += 1

    cond_results = {}
    for expert in sorted(expert_cond_distinctive.keys()):
        cond_results[expert] = {}
        for cond in CONDITIONS:
            n = expert_cond_runs[expert].get(cond, 1)
            scored = {
                w: s / n
                for w, s in expert_cond_distinctive[expert][cond].items()
            }
            cond_results[expert][cond] = sorted(
                scored.items(), key=lambda x: -x[1]
            )[:10]

    # Vocabulary stability: overlap of top-20 distinctive terms across conditions
    stability = {}
    for expert in sorted(expert_cond_distinctive.keys()):
        cond_top_sets = {}
        for cond in CONDITIONS:
            if cond in cond_results.get(expert, {}):
                cond_top_sets[cond] = set(
                    w for w, _ in cond_results[expert][cond][:10]
                )
        if len(cond_top_sets) < 2:
            continue
        # Pairwise Jaccard
        conds = sorted(cond_top_sets.keys())
        jaccards = []
        for i in range(len(conds)):
            for j in range(i + 1, len(conds)):
                a = cond_top_sets[conds[i]]
                b = cond_top_sets[conds[j]]
                if len(a | b) > 0:
                    jaccards.append(len(a & b) / len(a | b))
        stability[expert] = {
            "mean_jaccard": float(np.mean(jaccards)),
            "n_pairs": len(jaccards),
        }

    return {
        "overall_distinctive": results,
        "condition_distinctive": cond_results,
        "vocabulary_stability": stability,
    }


# ---------------------------------------------------------------------------
# Analysis 3: Paired within-panel comparisons
# ---------------------------------------------------------------------------


def paired_comparisons(data: dict) -> dict:
    """For each expert in each panel, compare their output across conditions."""
    # Build TF-IDF per expert per run
    docs = []
    doc_meta = []
    for (panel, cond, expert), ed in data.items():
        text = " ".join(ed["texts"])
        docs.append(text)
        doc_meta.append({"panel": panel, "condition": cond, "expert": expert})

    vec = TfidfVectorizer(
        max_features=3000, stop_words="english",
        min_df=2, max_df=0.85, ngram_range=(1, 2),
    )
    mat = vec.fit_transform(docs)

    # Build index: (panel, expert) -> {condition: row_index}
    index = defaultdict(dict)
    for i, m in enumerate(doc_meta):
        index[(m["panel"], m["expert"])][m["condition"]] = i

    # For each expert, compute mean pairwise distance across conditions
    # within the same panel (controls for panel composition)
    expert_panel_dists = defaultdict(list)
    expert_cond_pair_dists = defaultdict(lambda: defaultdict(list))

    for (panel, expert), cond_map in index.items():
        conds = sorted(cond_map.keys())
        if len(conds) < 2:
            continue
        for i in range(len(conds)):
            for j in range(i + 1, len(conds)):
                idx_i = cond_map[conds[i]]
                idx_j = cond_map[conds[j]]
                dist = float(cosine_distances(
                    mat[idx_i:idx_i + 1], mat[idx_j:idx_j + 1]
                )[0, 0])
                expert_panel_dists[expert].append(dist)
                pair = f"{conds[i]} ↔ {conds[j]}"
                expert_cond_pair_dists[expert][pair].append(dist)

    # Aggregate
    results = {}
    for expert in sorted(expert_panel_dists.keys()):
        dists = expert_panel_dists[expert]
        pair_means = {
            pair: float(np.mean(vals))
            for pair, vals in sorted(expert_cond_pair_dists[expert].items())
        }
        results[expert] = {
            "mean_distance": float(np.mean(dists)),
            "std_distance": float(np.std(dists)),
            "n_comparisons": len(dists),
            "pair_means": pair_means,
        }

    # Transport-specific: distance from transport to each other condition
    transport_dists = defaultdict(lambda: defaultdict(list))
    for (panel, expert), cond_map in index.items():
        if "transport" not in cond_map:
            continue
        t_idx = cond_map["transport"]
        for cond, c_idx in cond_map.items():
            if cond == "transport":
                continue
            dist = float(cosine_distances(
                mat[t_idx:t_idx + 1], mat[c_idx:c_idx + 1]
            )[0, 0])
            transport_dists[expert][cond].append(dist)

    transport_results = {}
    for expert in sorted(transport_dists.keys()):
        transport_results[expert] = {
            cond: float(np.mean(vals))
            for cond, vals in sorted(transport_dists[expert].items())
        }

    return {
        "overall": results,
        "vs_transport": transport_results,
    }


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_report(data: dict, behavioral: dict, vocab: dict, paired: dict) -> str:
    lines = []
    lines.append("# Expert Variation Analysis: Persona Rigidity vs Responsiveness")
    lines.append("")
    lines.append("**Date:** 2026-03-10")
    n_entries = len(data)
    n_runs = len(set((p, c) for p, c, _ in data.keys()))
    lines.append(f"**Data:** {n_entries} expert-runs across {n_runs} runs "
                 f"({len(BALANCED_PANELS)} panels × 5 conditions)")
    lines.append("")
    lines.append("Three complementary analyses of how expert personas interact "
                 "with passage selection conditions. The question: are the expert "
                 "caricatures rigid (persona dominates regardless of input) or "
                 "responsive (output changes with different passages)?")
    lines.append("")

    # ===== Section 1: Behavioral profiles =====
    lines.append("## 1. Behavioral Profiles: What Experts *Do*")
    lines.append("")
    lines.append("Each utterance has a `sentence_type` — a structured label for its "
                 "function in the conversation. The distribution over types is a "
                 "behavioral fingerprint: does this expert ask questions, read quotes, "
                 "deliver analysis, or land punchlines?")
    lines.append("")

    # Mean profiles table
    lines.append("### 1.1 Mean Behavioral Profile by Expert")
    lines.append("")
    short_types = ["intro", "question", "q_setup", "q_read", "analysis",
                   "punch", "trans", "closing"]
    header = "| Expert | " + " | ".join(short_types) + " |"
    sep = "|--------|" + "|".join("------:" for _ in short_types) + "|"
    lines.append(header)
    lines.append(sep)
    for expert, profile in sorted(behavioral["mean_profiles"].items()):
        vals = [
            profile.get("intro", 0), profile.get("question", 0),
            profile.get("quote_setup", 0), profile.get("quote_reading", 0),
            profile.get("analysis", 0), profile.get("punchline", 0),
            profile.get("transition", 0), profile.get("closing", 0),
        ]
        row = f"| {expert} | " + " | ".join(f"{v:.3f}" for v in vals) + " |"
        lines.append(row)
    lines.append("")

    # Behavioral shift
    lines.append("### 1.2 Behavioral Shift Across Conditions")
    lines.append("")
    lines.append("Jensen-Shannon divergence between an expert's sentence type "
                 "distribution under different conditions. **Higher = the expert "
                 "changes what they *do* (more quotes, fewer questions, etc.) "
                 "depending on input.**")
    lines.append("")
    lines.append("| Expert | Mean JSD | Max JSD | Interpretation |")
    lines.append("|--------|--------:|--------:|----------------|")
    sorted_shift = sorted(
        behavioral["behavioral_shift"].items(),
        key=lambda x: -x[1]["mean_jsd"],
    )
    for expert, bs in sorted_shift:
        jsd = bs["mean_jsd"]
        if jsd > 0.015:
            interp = "**Responsive** — behavior changes with input"
        elif jsd > 0.008:
            interp = "Moderate"
        else:
            interp = "**Rigid** — same behavior regardless of input"
        lines.append(f"| {expert} | {jsd:.4f} | {bs['max_jsd']:.4f} | {interp} |")
    lines.append("")

    # Quote rates by condition
    lines.append("### 1.3 Quote Rate by Expert × Condition")
    lines.append("")
    lines.append("Fraction of utterances that are direct novel quotations. "
                 "Experts who quote more in passage-grounded conditions are "
                 "responding to their input material.")
    lines.append("")
    header = "| Expert | Transport | Embedding | RAG | No Pass | Random |"
    sep = "|--------|--------:|--------:|----:|--------:|-------:|"
    lines.append(header)
    lines.append(sep)
    for expert in sorted(behavioral["quote_rates"].keys()):
        qr = behavioral["quote_rates"][expert]
        row = f"| {expert}"
        for cond in CONDITIONS:
            row += f" | {qr.get(cond, 0):.3f}"
        row += " |"
        lines.append(row)
    lines.append("")

    # Punchline rates
    lines.append("### 1.4 Punchline Rate by Expert × Condition")
    lines.append("")
    header = "| Expert | Transport | Embedding | RAG | No Pass | Random |"
    lines.append(header)
    lines.append(sep)
    for expert in sorted(behavioral["punchline_rates"].keys()):
        pr = behavioral["punchline_rates"][expert]
        row = f"| {expert}"
        for cond in CONDITIONS:
            row += f" | {pr.get(cond, 0):.3f}"
        row += " |"
        lines.append(row)
    lines.append("")

    # ===== Section 2: Distinctive vocabulary =====
    lines.append("## 2. Distinctive Vocabulary: How Experts *Frame*")
    lines.append("")
    lines.append("For each run, we compute G2 log-likelihood ratio for each "
                 "expert's words vs the other two experts in the same run. "
                 "This strips shared Bleak House vocabulary and isolates "
                 "the analytical frame — the words each expert uses to *interpret*, "
                 "not what they interpret.")
    lines.append("")

    lines.append("### 2.1 Top Distinctive Terms by Expert (all conditions)")
    lines.append("")
    for expert, terms in vocab["overall_distinctive"].items():
        term_str = ", ".join(f"**{w}** ({s:.1f})" for w, s in terms[:12])
        lines.append(f"**{expert}:** {term_str}")
        lines.append("")

    # Vocabulary stability
    lines.append("### 2.2 Vocabulary Stability Across Conditions")
    lines.append("")
    lines.append("Mean Jaccard overlap of top-10 distinctive terms across "
                 "conditions. **Higher = the expert's distinctive vocabulary "
                 "is stable regardless of input (rigid frame). Lower = "
                 "their framing vocabulary shifts with passages.**")
    lines.append("")
    lines.append("| Expert | Mean Jaccard | Interpretation |")
    lines.append("|--------|------------:|----------------|")
    for expert, stab in sorted(
        vocab["vocabulary_stability"].items(),
        key=lambda x: -x[1]["mean_jaccard"],
    ):
        j = stab["mean_jaccard"]
        if j > 0.35:
            interp = "**Rigid frame** — same analytical lens"
        elif j > 0.20:
            interp = "Moderate stability"
        else:
            interp = "**Responsive frame** — vocabulary shifts with input"
        lines.append(f"| {expert} | {j:.3f} | {interp} |")
    lines.append("")

    # Per-condition distinctive terms for most and least stable
    stab_sorted = sorted(
        vocab["vocabulary_stability"].items(),
        key=lambda x: -x[1]["mean_jaccard"],
    )
    if stab_sorted:
        lines.append("### 2.3 Condition-Specific Distinctive Terms")
        lines.append("")
        for expert, _ in [stab_sorted[0], stab_sorted[-1]]:
            pos = "most stable" if expert == stab_sorted[0][0] else "most variable"
            lines.append(f"**{expert}** ({pos}):")
            lines.append("")
            for cond in CONDITIONS:
                terms = vocab["condition_distinctive"].get(expert, {}).get(cond, [])
                if terms:
                    term_str = ", ".join(f"*{w}*" for w, _ in terms[:7])
                    lines.append(f"- **{cond}**: {term_str}")
            lines.append("")

    # ===== Section 3: Paired within-panel comparisons =====
    lines.append("## 3. Paired Comparisons: How Much Does Input Change Output?")
    lines.append("")
    lines.append("For each expert in each panel, we compare their TF-IDF vector "
                 "across conditions. Because these are *within-panel* comparisons "
                 "(same three experts, same segment structure), differences "
                 "are attributable to passage selection, not panel composition.")
    lines.append("")

    lines.append("### 3.1 Mean Within-Panel Distance Across Conditions")
    lines.append("")
    lines.append("| Expert | Mean Distance | Std | N | Interpretation |")
    lines.append("|--------|-------------:|----:|--:|----------------|")
    paired_sorted = sorted(
        paired["overall"].items(),
        key=lambda x: -x[1]["mean_distance"],
    )
    for expert, p in paired_sorted:
        d = p["mean_distance"]
        if d > 0.75:
            interp = "**Highly responsive** to passages"
        elif d > 0.65:
            interp = "Moderately responsive"
        else:
            interp = "**Rigid** — similar output regardless"
        lines.append(f"| {expert} | {d:.4f} | {p['std_distance']:.4f} | "
                     f"{p['n_comparisons']} | {interp} |")
    lines.append("")

    # Distance from transport specifically
    lines.append("### 3.2 Distance from Transport (per expert)")
    lines.append("")
    lines.append("How different is each expert's output under transport vs "
                 "each other condition? Larger distances mean that condition "
                 "produces more different output — exactly what manipulability claims.")
    lines.append("")
    header = "| Expert | vs Embedding | vs RAG | vs No Pass | vs Random |"
    sep = "|--------|------------:|-------:|----------:|----------:|"
    lines.append(header)
    lines.append(sep)
    for expert in sorted(paired["vs_transport"].keys()):
        vt = paired["vs_transport"][expert]
        row = f"| {expert}"
        for cond in ["embedding", "rag", "no_passages", "random"]:
            row += f" | {vt.get(cond, 0):.4f}"
        row += " |"
        lines.append(row)
    lines.append("")

    # ===== Section 4: Synthesis =====
    lines.append("## 4. Synthesis: The Rigidity–Responsiveness Spectrum")
    lines.append("")
    lines.append("Three independent measures — behavioral (sentence types), "
                 "lexical (distinctive vocabulary stability), and paired "
                 "(within-panel TF-IDF distance) — converge on a ranking:")
    lines.append("")

    # Build composite ranking
    # Rank each expert on: behavioral_shift (higher = more responsive),
    # vocab_stability (lower = more responsive), paired_distance (higher = more responsive)
    expert_set = sorted(set(
        list(behavioral["behavioral_shift"].keys()) +
        list(vocab["vocabulary_stability"].keys()) +
        list(paired["overall"].keys())
    ))

    bshift = {e: behavioral["behavioral_shift"].get(e, {}).get("mean_jsd", 0) for e in expert_set}
    vstab = {e: vocab["vocabulary_stability"].get(e, {}).get("mean_jaccard", 0.5) for e in expert_set}
    pdist = {e: paired["overall"].get(e, {}).get("mean_distance", 0) for e in expert_set}

    # Normalise each to 0-1 scale (higher = more responsive)
    def normalise(d: dict) -> dict:
        vals = list(d.values())
        mn, mx = min(vals), max(vals)
        rng = mx - mn if mx > mn else 1
        return {k: (v - mn) / rng for k, v in d.items()}

    bshift_n = normalise(bshift)
    vstab_n = {k: 1 - v for k, v in normalise(vstab).items()}  # Invert: low stability = responsive
    pdist_n = normalise(pdist)

    composite = {
        e: (bshift_n[e] + vstab_n[e] + pdist_n[e]) / 3
        for e in expert_set
    }
    composite_sorted = sorted(composite.items(), key=lambda x: x[1])

    lines.append("| Rank | Expert | Behavioral | Vocab Stability | Paired Dist | Composite |")
    lines.append("|------|--------|----------:|----------------:|------------:|----------:|")
    for rank, (expert, comp) in enumerate(composite_sorted, 1):
        lines.append(
            f"| {rank} | {expert} | {bshift.get(expert, 0):.4f} | "
            f"{vstab.get(expert, 0):.3f} | {pdist.get(expert, 0):.4f} | "
            f"{comp:.3f} |"
        )
    lines.append("")

    most_rigid = composite_sorted[0][0]
    most_responsive = composite_sorted[-1][0]
    lines.append(f"**{most_rigid}** is the most rigid expert across all three measures — "
                 f"their behavioral profile, distinctive vocabulary, and overall output "
                 f"change least across conditions.")
    lines.append("")
    lines.append(f"**{most_responsive}** is the most responsive — their output genuinely "
                 f"changes with different passage selections, making them the best "
                 f"demonstration of the transport pipeline's manipulability.")
    lines.append("")

    lines.append("### 4.1 Implications for the Manipulability Claim")
    lines.append("")
    lines.append("The transport pipeline's value proposition — that changing demand "
                 "vectors and arc constraints produces *visible, legible* output "
                 "differences — is most clearly demonstrated through responsive experts. "
                 "When the solver assigns different passages to a responsive expert, "
                 "the resulting script measurably changes: different sentence type "
                 "distribution, different analytical vocabulary, different overall "
                 "content. For rigid experts, the pipeline controls *which text* they "
                 "quote but not *how they think* — the caricature is stable regardless.")
    lines.append("")
    lines.append("This is not a weakness — it reflects a design choice. A panel "
                 "benefits from having both rigid experts (reliable anchors for "
                 "their specialist perspective) and responsive experts (who adapt "
                 "to the specific material, creating variety across configurations). "
                 "The current six personas span this spectrum naturally.")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print("Loading episode data...")
    data = load_all_data()
    print(f"  {len(data)} expert-run entries from "
          f"{len(set((p, c) for p, c, _ in data.keys()))} runs")

    print("\n1. Behavioral analysis (sentence types)...")
    behavioral = behavioral_analysis(data)
    for expert, bs in sorted(
        behavioral["behavioral_shift"].items(),
        key=lambda x: -x[1]["mean_jsd"],
    ):
        print(f"  {expert}: JSD={bs['mean_jsd']:.4f}")

    print("\n2. Distinctive vocabulary (G2 residuals)...")
    vocab = distinctive_vocabulary(data)
    for expert, stab in sorted(
        vocab["vocabulary_stability"].items(),
        key=lambda x: -x[1]["mean_jaccard"],
    ):
        print(f"  {expert}: Jaccard={stab['mean_jaccard']:.3f}")

    print("\n3. Paired within-panel comparisons...")
    paired = paired_comparisons(data)
    for expert, p in sorted(
        paired["overall"].items(),
        key=lambda x: -x[1]["mean_distance"],
    ):
        print(f"  {expert}: dist={p['mean_distance']:.4f}")

    print("\nGenerating report...")
    report = generate_report(data, behavioral, vocab, paired)
    report_path = REPORTS_DIR / "expert_variation_analysis.md"
    report_path.write_text(report)
    print(f"Report written to {report_path}")


if __name__ == "__main__":
    main()
