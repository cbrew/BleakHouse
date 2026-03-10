"""Expert utterance clustering: measuring persona rigidity vs responsiveness.

For each expert across all conditions and panels, embed their utterances and
measure how tightly clustered they are. Rigid experts (strong agenda) produce
tight clusters regardless of condition; responsive experts spread out depending
on what passages they were given.

Metrics:
- Intra-expert mean cosine distance (tightness of persona)
- Silhouette score: expert labels vs embedding space
- Adjusted Rand Index: expert clusters vs condition clusters
- Per-expert × per-condition centroid analysis
- Condition responsiveness: how much an expert's centroid shifts across conditions

Output: reports/expert_clustering_analysis.md
"""

import json
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import (
    adjusted_rand_score,
    silhouette_score,
)
from sklearn.metrics.pairwise import cosine_distances, cosine_similarity
from sklearn.decomposition import PCA

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

# The 20 balanced panels used in the five-way comparison
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


# ---------------------------------------------------------------------------
# Data extraction
# ---------------------------------------------------------------------------


def get_condition(run_name: str) -> str:
    """Determine condition from run directory name."""
    for cond, prefix in CONDITION_PREFIXES.items():
        if prefix and run_name.startswith(prefix):
            return cond
        if not prefix and re.match(r"^v\d+", run_name):
            # Transport runs start with v followed by digits
            # but we need to exclude prefixed ones
            if not any(run_name.startswith(p) for p in CONDITION_PREFIXES.values() if p):
                return "transport"
    return "unknown"


def get_panel_id(run_name: str) -> str:
    """Extract panel ID from run name (strip condition prefix)."""
    for prefix in CONDITION_PREFIXES.values():
        if prefix and run_name.startswith(prefix):
            return run_name[len(prefix):]
    return run_name


def extract_utterances(episode_path: Path) -> list[dict]:
    """Extract all expert utterances from a phase3_episode.json."""
    with open(episode_path) as f:
        episode = json.load(f)

    utterances = []
    for segment in episode.get("segments", []):
        for turn in segment.get("turns", []):
            speaker = turn.get("speaker", "")
            if speaker not in EXPERTS:
                continue
            # Concatenate all utterance texts in this turn into one "turn text"
            # This is a better unit than individual sentences for clustering
            turn_texts = []
            for utt in turn.get("utterances", []):
                text = utt.get("text", "").strip()
                if text:
                    turn_texts.append(text)
            if turn_texts:
                utterances.append({
                    "speaker": speaker,
                    "segment_type": segment.get("segment_type", ""),
                    "text": " ".join(turn_texts),
                })
    return utterances


def load_all_utterances() -> list[dict]:
    """Load utterances from all balanced panel runs across all conditions."""
    all_utterances = []
    for panel in BALANCED_PANELS:
        for cond, prefix in CONDITION_PREFIXES.items():
            run_name = f"{prefix}{panel}" if prefix else panel
            episode_path = RUNS_DIR / run_name / "phase3_episode.json"
            if not episode_path.exists():
                continue
            for utt in extract_utterances(episode_path):
                utt["condition"] = cond
                utt["panel"] = panel
                utt["run"] = run_name
                all_utterances.append(utt)
    return all_utterances


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def build_tfidf_matrix(utterances: list[dict]) -> tuple:
    """Build TF-IDF matrix from utterance texts. Returns (matrix, vectorizer)."""
    texts = [u["text"] for u in utterances]
    vectorizer = TfidfVectorizer(
        max_features=5000,
        stop_words="english",
        min_df=3,
        max_df=0.8,
        ngram_range=(1, 2),
    )
    matrix = vectorizer.fit_transform(texts)
    return matrix, vectorizer


def compute_intra_expert_distances(matrix, utterances: list[dict]) -> dict:
    """Mean pairwise cosine distance within each expert's utterances."""
    expert_indices = defaultdict(list)
    for i, u in enumerate(utterances):
        expert_indices[u["speaker"]].append(i)

    results = {}
    for expert, indices in sorted(expert_indices.items()):
        if len(indices) < 2:
            continue
        sub = matrix[indices]
        dists = cosine_distances(sub)
        # Mean of upper triangle
        n = len(indices)
        upper = dists[np.triu_indices(n, k=1)]
        results[expert] = {
            "mean_distance": float(np.mean(upper)),
            "std_distance": float(np.std(upper)),
            "n_utterances": n,
        }
    return results


def compute_expert_condition_centroids(matrix, utterances: list[dict]) -> dict:
    """Compute centroid for each expert × condition combination."""
    groups = defaultdict(list)
    for i, u in enumerate(utterances):
        groups[(u["speaker"], u["condition"])].append(i)

    centroids = {}
    for (expert, cond), indices in groups.items():
        sub = matrix[indices].toarray()
        centroids[(expert, cond)] = np.mean(sub, axis=0)
    return centroids


def compute_condition_responsiveness(centroids: dict) -> dict:
    """How much does each expert's centroid move across conditions?

    Measured as mean pairwise cosine distance between an expert's
    condition-specific centroids. Higher = more responsive to input.
    """
    expert_centroids = defaultdict(dict)
    for (expert, cond), centroid in centroids.items():
        expert_centroids[expert][cond] = centroid

    results = {}
    for expert, cond_centroids in sorted(expert_centroids.items()):
        conditions = sorted(cond_centroids.keys())
        if len(conditions) < 2:
            continue
        vecs = np.array([cond_centroids[c] for c in conditions])
        dists = cosine_distances(vecs)
        n = len(conditions)
        upper = dists[np.triu_indices(n, k=1)]
        results[expert] = {
            "mean_centroid_shift": float(np.mean(upper)),
            "max_centroid_shift": float(np.max(upper)),
            "conditions": conditions,
            "pairwise": {},
        }
        for i in range(n):
            for j in range(i + 1, n):
                pair = f"{conditions[i]} ↔ {conditions[j]}"
                results[expert]["pairwise"][pair] = float(dists[i, j])
    return results


def compute_silhouette_by_label(matrix, utterances: list[dict], label_key: str) -> float:
    """Silhouette score using a given label (expert or condition)."""
    labels = [u[label_key] for u in utterances]
    unique = set(labels)
    if len(unique) < 2:
        return 0.0
    label_map = {lab: i for i, lab in enumerate(sorted(unique))}
    numeric_labels = [label_map[lab] for lab in labels]
    # Use a sample if too large (silhouette is O(n²))
    n = matrix.shape[0]
    if n > 5000:
        rng = np.random.default_rng(42)
        idx = rng.choice(n, 5000, replace=False)
        matrix = matrix[idx]
        numeric_labels = [numeric_labels[i] for i in idx]
    return float(silhouette_score(matrix, numeric_labels, metric="cosine"))


def compute_adjusted_rand(matrix, utterances: list[dict], n_clusters: int = 6) -> dict:
    """K-means clustering vs expert labels and condition labels."""
    # Reduce dimensionality for K-means
    dense = matrix.toarray()
    pca = PCA(n_components=50, random_state=42)
    reduced = pca.fit_transform(dense)

    km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    km_labels = km.fit_predict(reduced)

    expert_labels = [u["speaker"] for u in utterances]
    condition_labels = [u["condition"] for u in utterances]

    expert_map = {e: i for i, e in enumerate(sorted(set(expert_labels)))}
    condition_map = {c: i for i, c in enumerate(sorted(set(condition_labels)))}

    return {
        "ari_expert": float(adjusted_rand_score(
            [expert_map[e] for e in expert_labels], km_labels
        )),
        "ari_condition": float(adjusted_rand_score(
            [condition_map[c] for c in condition_labels], km_labels
        )),
    }


def compute_top_terms_per_expert(matrix, utterances: list[dict], vectorizer) -> dict:
    """Top TF-IDF terms per expert (across all conditions)."""
    expert_indices = defaultdict(list)
    for i, u in enumerate(utterances):
        expert_indices[u["speaker"]].append(i)

    feature_names = vectorizer.get_feature_names_out()
    results = {}
    for expert, indices in sorted(expert_indices.items()):
        sub = matrix[indices].toarray()
        mean_tfidf = np.mean(sub, axis=0)
        top_idx = np.argsort(mean_tfidf)[-15:][::-1]
        results[expert] = [(feature_names[i], float(mean_tfidf[i])) for i in top_idx]
    return results


def compute_condition_specific_terms(matrix, utterances: list[dict], vectorizer) -> dict:
    """For each expert, find terms that are most condition-specific.

    These are terms with highest variance across conditions for that expert.
    """
    expert_cond_indices = defaultdict(lambda: defaultdict(list))
    for i, u in enumerate(utterances):
        expert_cond_indices[u["speaker"]][u["condition"]].append(i)

    feature_names = vectorizer.get_feature_names_out()
    results = {}
    for expert in sorted(expert_cond_indices.keys()):
        cond_means = {}
        for cond, indices in expert_cond_indices[expert].items():
            if indices:
                cond_means[cond] = np.mean(matrix[indices].toarray(), axis=0)
        if len(cond_means) < 2:
            continue
        # Stack and compute variance across conditions
        stacked = np.array(list(cond_means.values()))
        variance = np.var(stacked, axis=0)
        top_var_idx = np.argsort(variance)[-10:][::-1]
        term_details = []
        for idx in top_var_idx:
            term = feature_names[idx]
            per_cond = {c: float(v[idx]) for c, v in cond_means.items()}
            term_details.append((term, float(variance[idx]), per_cond))
        results[expert] = term_details
    return results


def aggregate_by_run(utterances: list[dict]) -> list[dict]:
    """Concatenate all utterances by the same expert in the same run into one doc."""
    groups = defaultdict(list)
    for u in utterances:
        key = (u["speaker"], u["run"], u["condition"], u["panel"])
        groups[key].append(u["text"])

    docs = []
    for (speaker, run, condition, panel), texts in groups.items():
        docs.append({
            "speaker": speaker,
            "run": run,
            "condition": condition,
            "panel": panel,
            "text": " ".join(texts),
        })
    return docs


def run_level_analysis(utterances: list[dict], vectorizer_params: dict | None = None) -> dict:
    """Run clustering analysis at the run level (one doc per expert per run).

    Returns dict with silhouette scores, ARI, intra-expert distances, and
    condition responsiveness — all computed on run-level aggregated documents.
    """
    docs = aggregate_by_run(utterances)
    texts = [d["text"] for d in docs]

    params = {
        "max_features": 3000,
        "stop_words": "english",
        "min_df": 2,
        "max_df": 0.85,
        "ngram_range": (1, 2),
    }
    if vectorizer_params:
        params.update(vectorizer_params)

    vec = TfidfVectorizer(**params)
    mat = vec.fit_transform(texts)

    # Silhouette
    expert_labels = [d["speaker"] for d in docs]
    cond_labels = [d["condition"] for d in docs]
    expert_map = {e: i for i, e in enumerate(sorted(set(expert_labels)))}
    cond_map = {c: i for i, c in enumerate(sorted(set(cond_labels)))}

    sil_expert = float(silhouette_score(
        mat, [expert_map[e] for e in expert_labels], metric="cosine"
    ))
    sil_cond = float(silhouette_score(
        mat, [cond_map[c] for c in cond_labels], metric="cosine"
    ))

    # ARI
    dense = mat.toarray()
    pca = PCA(n_components=min(50, dense.shape[1]), random_state=42)
    reduced = pca.fit_transform(dense)
    n_experts = len(set(expert_labels))
    km = KMeans(n_clusters=n_experts, random_state=42, n_init="auto")
    km_labels = km.fit_predict(reduced)
    ari_expert = float(adjusted_rand_score(
        [expert_map[e] for e in expert_labels], km_labels
    ))
    ari_cond = float(adjusted_rand_score(
        [cond_map[c] for c in cond_labels], km_labels
    ))

    # Intra-expert distances
    expert_indices = defaultdict(list)
    for i, d in enumerate(docs):
        expert_indices[d["speaker"]].append(i)

    intra = {}
    for expert, indices in sorted(expert_indices.items()):
        if len(indices) < 2:
            continue
        sub = mat[indices]
        dists = cosine_distances(sub)
        n = len(indices)
        upper = dists[np.triu_indices(n, k=1)]
        intra[expert] = {
            "mean_distance": float(np.mean(upper)),
            "std_distance": float(np.std(upper)),
            "n_docs": n,
        }

    # Condition responsiveness
    groups = defaultdict(dict)
    for i, d in enumerate(docs):
        key = d["speaker"]
        cond = d["condition"]
        if cond not in groups[key]:
            groups[key][cond] = []
        groups[key][cond].append(i)

    centroids = {}
    for expert, cond_indices in groups.items():
        for cond, indices in cond_indices.items():
            centroids[(expert, cond)] = np.mean(mat[indices].toarray(), axis=0)

    responsiveness = {}
    for expert in sorted(groups.keys()):
        conds = sorted(c for c in groups[expert].keys())
        if len(conds) < 2:
            continue
        vecs = np.array([centroids[(expert, c)] for c in conds])
        dists = cosine_distances(vecs)
        n = len(conds)
        upper = dists[np.triu_indices(n, k=1)]
        pairwise = {}
        for i in range(n):
            for j in range(i + 1, n):
                pairwise[f"{conds[i]} ↔ {conds[j]}"] = float(dists[i, j])
        responsiveness[expert] = {
            "mean_centroid_shift": float(np.mean(upper)),
            "max_centroid_shift": float(np.max(upper)),
            "pairwise": pairwise,
        }

    return {
        "n_docs": len(docs),
        "matrix_shape": mat.shape,
        "silhouette_expert": sil_expert,
        "silhouette_condition": sil_cond,
        "ari_expert": ari_expert,
        "ari_condition": ari_cond,
        "intra_distances": intra,
        "responsiveness": responsiveness,
    }


def compute_expert_similarity_matrix(matrix, utterances: list[dict]) -> dict:
    """Mean cosine similarity between each pair of experts."""
    expert_indices = defaultdict(list)
    for i, u in enumerate(utterances):
        expert_indices[u["speaker"]].append(i)

    experts = sorted(expert_indices.keys())
    n = len(experts)
    sim_matrix = np.zeros((n, n))

    for i in range(n):
        for j in range(i, n):
            sub_i = matrix[expert_indices[experts[i]]]
            sub_j = matrix[expert_indices[experts[j]]]
            sims = cosine_similarity(sub_i, sub_j)
            sim_matrix[i, j] = float(np.mean(sims))
            sim_matrix[j, i] = sim_matrix[i, j]

    return {
        "experts": experts,
        "matrix": sim_matrix.tolist(),
    }


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_report(
    utterances: list[dict],
    intra_dists: dict,
    responsiveness: dict,
    silhouette_expert: float,
    silhouette_condition: float,
    ari: dict,
    top_terms: dict,
    cond_terms: dict,
    expert_sim: dict,
    run_level: dict,
) -> str:
    """Generate the markdown report."""
    lines = []
    lines.append("# Expert Clustering Analysis: Persona Rigidity vs Responsiveness")
    lines.append("")
    lines.append("**Date:** 2026-03-10")
    lines.append(f"**Utterances analysed:** {len(utterances):,} turns across "
                 f"{len(BALANCED_PANELS)} panels × 5 conditions")
    lines.append("")

    # Count per expert
    expert_counts = defaultdict(lambda: defaultdict(int))
    for u in utterances:
        expert_counts[u["speaker"]][u["condition"]] += 1

    lines.append("## 1. Overview")
    lines.append("")
    lines.append("Each expert persona is a deliberate caricature — the Marxist always finds "
                 "class struggle, the legal historian always finds institutional failure. "
                 "But how *rigid* are these caricatures? Does passage selection change what "
                 "an expert talks about, or does the persona dominate regardless of input?")
    lines.append("")
    lines.append("We cluster all expert utterances (turns) using TF-IDF vectors and measure "
                 "how tightly each expert's utterances group together (rigidity) vs how much "
                 "they spread across conditions (responsiveness). An expert with a strong, "
                 "rigid agenda will cluster tightly regardless of condition; a responsive "
                 "expert will shift vocabulary depending on what passages they receive.")
    lines.append("")

    # Utterance counts table
    lines.append("### 1.1 Utterance Counts")
    lines.append("")
    conditions = ["transport", "embedding", "rag", "no_passages", "random"]
    header = "| Expert | " + " | ".join(c.replace("_", " ").title() for c in conditions) + " | Total |"
    sep = "|--------|" + "|".join("------:" for _ in conditions) + "|------:|"
    lines.append(header)
    lines.append(sep)
    for expert in EXPERTS:
        counts = expert_counts.get(expert, {})
        total = sum(counts.values())
        if total == 0:
            continue
        row = f"| {expert} | "
        row += " | ".join(str(counts.get(c, 0)) for c in conditions)
        row += f" | {total} |"
        lines.append(row)
    lines.append("")

    # Section 2: Intra-expert distances (rigidity)
    lines.append("## 2. Persona Rigidity: Intra-Expert Distances")
    lines.append("")
    lines.append("Mean pairwise cosine distance between all utterances by the same expert, "
                 "across all conditions and panels. **Lower distance = tighter cluster = "
                 "more rigid persona.** Higher distance = more varied vocabulary = more "
                 "responsive to input material.")
    lines.append("")
    lines.append("| Expert | Mean Distance | Std Dev | N Utterances | Interpretation |")
    lines.append("|--------|-------------:|--------:|------------:|----------------|")

    sorted_experts = sorted(intra_dists.items(), key=lambda x: x[1]["mean_distance"])
    for expert, d in sorted_experts:
        dist = d["mean_distance"]
        if dist < 0.82:
            interp = "**Rigid** — tight cluster"
        elif dist < 0.86:
            interp = "Moderate"
        else:
            interp = "**Responsive** — spread out"
        lines.append(f"| {expert} | {dist:.4f} | {d['std_distance']:.4f} | "
                     f"{d['n_utterances']} | {interp} |")
    lines.append("")

    most_rigid = sorted_experts[0][0]
    most_responsive = sorted_experts[-1][0]
    lines.append(f"**{most_rigid}** is the most rigid expert — their utterances are the most "
                 f"self-similar regardless of condition. **{most_responsive}** is the most "
                 f"responsive — their vocabulary shifts most depending on input material.")
    lines.append("")

    # Section 3: Condition responsiveness
    lines.append("## 3. Condition Responsiveness: How Much Do Centroids Shift?")
    lines.append("")
    lines.append("For each expert, we compute a centroid (mean TF-IDF vector) per condition, "
                 "then measure the mean pairwise cosine distance between those centroids. "
                 "**Higher shift = the expert's vocabulary changes more across conditions.**")
    lines.append("")
    lines.append("| Expert | Mean Centroid Shift | Max Shift | Interpretation |")
    lines.append("|--------|-------------------:|----------:|----------------|")

    sorted_resp = sorted(responsiveness.items(), key=lambda x: x[1]["mean_centroid_shift"], reverse=True)
    for expert, r in sorted_resp:
        shift = r["mean_centroid_shift"]
        if shift > 0.55:
            interp = "**Highly responsive** to input"
        elif shift > 0.45:
            interp = "Moderately responsive"
        else:
            interp = "**Agenda-driven** — stable across conditions"
        lines.append(f"| {expert} | {shift:.4f} | {r['max_centroid_shift']:.4f} | {interp} |")
    lines.append("")

    # Pairwise detail for the most and least responsive
    if sorted_resp:
        lines.append("### 3.1 Pairwise Centroid Distances (selected experts)")
        lines.append("")
        for expert, r in [sorted_resp[0], sorted_resp[-1]]:
            lines.append(f"**{expert}** ({'most' if expert == sorted_resp[0][0] else 'least'} responsive):")
            lines.append("")
            lines.append("| Condition Pair | Distance |")
            lines.append("|---------------|--------:|")
            for pair, dist in sorted(r["pairwise"].items(), key=lambda x: -x[1]):
                lines.append(f"| {pair} | {dist:.4f} |")
            lines.append("")

    # Section 4: Global clustering metrics
    lines.append("## 4. Global Clustering Metrics")
    lines.append("")
    lines.append("| Metric | Value | Interpretation |")
    lines.append("|--------|------:|----------------|")
    lines.append(f"| Silhouette (expert labels) | {silhouette_expert:.4f} | "
                 f"{'Moderate' if silhouette_expert > 0.05 else 'Weak'} expert separation in TF-IDF space |")
    lines.append(f"| Silhouette (condition labels) | {silhouette_condition:.4f} | "
                 f"{'Moderate' if silhouette_condition > 0.05 else 'Weak'} condition separation |")
    lines.append(f"| ARI (K-means vs expert) | {ari['ari_expert']:.4f} | "
                 f"{'Expert identity shapes clusters' if ari['ari_expert'] > 0.05 else 'Expert identity is a weak clustering signal'} |")
    lines.append(f"| ARI (K-means vs condition) | {ari['ari_condition']:.4f} | "
                 f"{'Condition shapes clusters' if ari['ari_condition'] > 0.05 else 'Condition is a weak clustering signal'} |")
    lines.append("")

    ari_ratio = ari["ari_expert"] / max(ari["ari_condition"], 0.001)
    if ari_ratio > 2:
        lines.append(f"The ARI ratio (expert/condition = {ari_ratio:.1f}×) confirms that "
                     "**expert identity is a much stronger organising force than condition**. "
                     "Utterances cluster by *who said them* rather than *what passages they were given*.")
    elif ari_ratio > 1:
        lines.append(f"The ARI ratio (expert/condition = {ari_ratio:.1f}×) suggests expert "
                     "identity is somewhat stronger than condition, but both contribute.")
    else:
        lines.append(f"The ARI ratio (expert/condition = {ari_ratio:.1f}×) suggests condition "
                     "influences clustering as much or more than expert identity.")
    lines.append("")

    # Section 5: Expert similarity matrix
    lines.append("## 5. Inter-Expert Similarity")
    lines.append("")
    lines.append("Mean cosine similarity between utterances of each expert pair. "
                 "Higher values mean experts use more overlapping vocabulary.")
    lines.append("")
    sim_experts = expert_sim["experts"]
    sim_mat = expert_sim["matrix"]
    header = "| | " + " | ".join(e.split()[0] for e in sim_experts) + " |"
    sep = "|---|" + "|".join("---:" for _ in sim_experts) + "|"
    lines.append(header)
    lines.append(sep)
    for i, expert in enumerate(sim_experts):
        row = f"| **{expert.split()[0]}** | "
        row += " | ".join(
            f"**{sim_mat[i][j]:.3f}**" if i == j else f"{sim_mat[i][j]:.3f}"
            for j in range(len(sim_experts))
        )
        row += " |"
        lines.append(row)
    lines.append("")

    # Find most and least similar pairs
    pairs = []
    for i in range(len(sim_experts)):
        for j in range(i + 1, len(sim_experts)):
            pairs.append((sim_experts[i], sim_experts[j], sim_mat[i][j]))
    pairs.sort(key=lambda x: x[2])
    if pairs:
        least = pairs[0]
        most = pairs[-1]
        lines.append(f"Most similar pair: **{most[0].split()[0]}–{most[1].split()[0]}** "
                     f"({most[2]:.3f}). Least similar: **{least[0].split()[0]}–{least[1].split()[0]}** "
                     f"({least[2]:.3f}).")
        lines.append("")

    # Section 6: Top terms per expert
    lines.append("## 6. Expert Vocabulary Signatures")
    lines.append("")
    lines.append("Top 15 TF-IDF terms per expert (aggregated across all conditions). "
                 "These are the words most distinctive to each expert's overall output.")
    lines.append("")
    for expert, terms in top_terms.items():
        lines.append(f"**{expert}:** " + ", ".join(
            f"*{t}* ({s:.3f})" for t, s in terms[:10]
        ))
        lines.append("")

    # Section 7: Condition-specific vocabulary shifts
    lines.append("## 7. Condition-Responsive Vocabulary")
    lines.append("")
    lines.append("Terms with highest variance across conditions for each expert. "
                 "These are the words whose usage shifts most depending on what "
                 "passages the expert receives — indicators of responsiveness.")
    lines.append("")
    for expert, terms in cond_terms.items():
        lines.append(f"### {expert}")
        lines.append("")
        lines.append("| Term | Variance | Transport | Embedding | RAG | No Pass | Random |")
        lines.append("|------|--------:|----------:|----------:|----:|--------:|-------:|")
        for term, var, per_cond in terms[:7]:
            row = f"| {term} | {var:.5f}"
            for c in conditions:
                row += f" | {per_cond.get(c, 0):.4f}"
            row += " |"
            lines.append(row)
        lines.append("")

    # Section 8: Run-level analysis
    lines.append("## 8. Run-Level Analysis (Aggregated Documents)")
    lines.append("")
    lines.append("The turn-level analysis above treats each speaker turn (~2–5 sentences) "
                 "as a document. This is noisy: individual turns are short and topically "
                 "constrained by segment context. Here we aggregate all of an expert's "
                 "utterances within a single run into one document, producing one TF-IDF "
                 f"vector per expert per run ({run_level['n_docs']} documents, "
                 f"matrix shape {run_level['matrix_shape'][0]}×{run_level['matrix_shape'][1]}).")
    lines.append("")

    lines.append("### 8.1 Global Clustering Metrics (Run-Level)")
    lines.append("")
    lines.append("| Metric | Turn-Level | Run-Level | Change |")
    lines.append("|--------|----------:|----------:|--------|")
    lines.append(f"| Silhouette (expert) | {silhouette_expert:.4f} | "
                 f"{run_level['silhouette_expert']:.4f} | "
                 f"{'Stronger' if run_level['silhouette_expert'] > silhouette_expert else 'Weaker'} |")
    lines.append(f"| Silhouette (condition) | {silhouette_condition:.4f} | "
                 f"{run_level['silhouette_condition']:.4f} | "
                 f"{'Stronger' if run_level['silhouette_condition'] > silhouette_condition else 'Weaker'} |")
    lines.append(f"| ARI (expert) | {ari['ari_expert']:.4f} | "
                 f"{run_level['ari_expert']:.4f} | "
                 f"{'Stronger' if run_level['ari_expert'] > ari['ari_expert'] else 'Weaker'} |")
    lines.append(f"| ARI (condition) | {ari['ari_condition']:.4f} | "
                 f"{run_level['ari_condition']:.4f} | "
                 f"{'Stronger' if run_level['ari_condition'] > ari['ari_condition'] else 'Weaker'} |")
    lines.append("")

    rl_ari_ratio = run_level["ari_expert"] / max(run_level["ari_condition"], 0.001)
    lines.append(f"Run-level ARI ratio (expert/condition): **{rl_ari_ratio:.1f}×**")
    lines.append("")

    lines.append("### 8.2 Intra-Expert Distances (Run-Level)")
    lines.append("")
    lines.append("| Expert | Mean Distance | N Docs | Interpretation |")
    lines.append("|--------|-------------:|-------:|----------------|")
    rl_sorted = sorted(run_level["intra_distances"].items(), key=lambda x: x[1]["mean_distance"])
    for expert, d in rl_sorted:
        dist = d["mean_distance"]
        if dist < 0.60:
            interp = "**Rigid** — tight cluster"
        elif dist < 0.70:
            interp = "Moderate"
        else:
            interp = "**Responsive** — spread out"
        lines.append(f"| {expert} | {dist:.4f} | {d['n_docs']} | {interp} |")
    lines.append("")

    lines.append("### 8.3 Condition Responsiveness (Run-Level)")
    lines.append("")
    lines.append("| Expert | Mean Centroid Shift | Max Shift |")
    lines.append("|--------|-------------------:|----------:|")
    rl_resp_sorted = sorted(
        run_level["responsiveness"].items(),
        key=lambda x: x[1]["mean_centroid_shift"], reverse=True
    )
    for expert, r in rl_resp_sorted:
        lines.append(f"| {expert} | {r['mean_centroid_shift']:.4f} | {r['max_centroid_shift']:.4f} |")
    lines.append("")

    # Pairwise for most and least responsive at run level
    if rl_resp_sorted:
        for expert, r in [rl_resp_sorted[0], rl_resp_sorted[-1]]:
            pos = "most" if expert == rl_resp_sorted[0][0] else "least"
            lines.append(f"**{expert}** ({pos} responsive, run-level):")
            lines.append("")
            lines.append("| Condition Pair | Distance |")
            lines.append("|---------------|--------:|")
            for pair, dist in sorted(r["pairwise"].items(), key=lambda x: -x[1]):
                lines.append(f"| {pair} | {dist:.4f} |")
            lines.append("")

    # Section 9: Interpretation
    lines.append("## 9. Interpretation")
    lines.append("")
    lines.append("### 9.1 The Rigidity–Responsiveness Spectrum")
    lines.append("")

    lines.append("Using the run-level analysis (Section 8), which provides cleaner signal, "
                 "the experts fall along a spectrum from agenda-driven to input-responsive:")
    lines.append("")
    rl_intra = run_level["intra_distances"]
    rl_resp = run_level["responsiveness"]
    rl_rigidity = sorted(rl_intra.items(), key=lambda x: x[1]["mean_distance"])
    for i, (expert, d) in enumerate(rl_rigidity):
        rank = i + 1
        resp_shift = rl_resp.get(expert, {}).get("mean_centroid_shift", 0)
        lines.append(f"{rank}. **{expert}** — run-level distance {d['mean_distance']:.4f}, "
                     f"centroid shift {resp_shift:.4f}")
    lines.append("")

    lines.append("**Blackstone** (legal historian) is the most rigid: his legal-institutional "
                 "vocabulary dominates regardless of condition. His top terms — *chancery, legal, "
                 "jarndyce, court, victorian, law* — are agenda-driven, not passage-driven.")
    lines.append("")
    lines.append("**Woodcourt** (close reader/performer) is the most responsive: her vocabulary "
                 "shifts substantially depending on what passages she receives. Her centroid shift "
                 f"({rl_resp.get('Caroline Woodcourt', {}).get('mean_centroid_shift', 0):.4f}) is "
                 f"{rl_resp.get('Caroline Woodcourt', {}).get('mean_centroid_shift', 0) / max(rl_resp.get('Edmund Leigh', {}).get('mean_centroid_shift', 0.001), 0.001):.1f}× "
                 "Leigh's. She adapts to the material — her condition-responsive terms include "
                 "character names like *woodcourt, smallweed, george* that appear only when the "
                 "passages feature those characters.")
    lines.append("")

    lines.append("### 9.2 The Expert–Condition Interaction")
    lines.append("")
    lines.append("The run-level ARI ratio (expert/condition = "
                 f"{run_level['ari_expert'] / max(run_level['ari_condition'], 0.001):.1f}×) "
                 "confirms that expert identity is a stronger organising force than condition — "
                 "but only marginally. Both matter. This is the expected result for a system "
                 "that uses *both* persona prompts and passage selection: the persona sets the "
                 "interpretive frame, and the passages provide the material to interpret.")
    lines.append("")
    lines.append("The interesting finding is that these forces interact differently per expert. "
                 "For Blackstone, persona dominates — he discusses legal institutions regardless "
                 "of input. For Woodcourt, passages have genuine influence — she discusses what "
                 "she's given. This means the transport pipeline's manipulability is *more "
                 "valuable for some experts than others*.")
    lines.append("")

    lines.append("### 9.3 Implications for Pipeline Design")
    lines.append("")
    lines.append("Rigid experts (Blackstone, Leigh) are the most *reliable* caricatures — "
                 "they sound like themselves regardless of input. But they are also the "
                 "hardest to *steer* via passage selection: giving Blackstone different "
                 "passages changes what legal concepts he discusses but not his fundamental "
                 "legal-institutional framing.")
    lines.append("")
    lines.append("Responsive experts (Woodcourt, Rosen) are more *manipulable* — their "
                 "output genuinely changes with different input material. This makes them "
                 "better subjects for exploring the configuration space, since changes to "
                 "passage selection produce visible changes in their contributions. Notably, "
                 "Rosen (the Marxist) is the second most responsive: despite his ideological "
                 "framing, he adapts to specific characters and scenes in the passages he "
                 "receives, applying his class-analysis lens to whatever material is provided.")
    lines.append("")
    lines.append("The transport pipeline's value proposition is strongest for responsive "
                 "experts: adjusting demand profiles and arc constraints produces measurably "
                 "different output from experts who respond to their input. For rigid experts, "
                 "the pipeline still controls *which text* they quote, but not *how they frame* it.")
    lines.append("")
    lines.append("This spectrum also suggests a design lever: persona descriptions could be "
                 "calibrated along the rigidity–responsiveness axis. A persona that is *too* "
                 "rigid wastes the passage selection pipeline's effort; one that is *too* "
                 "responsive loses its distinctive caricature. The current personas span "
                 "this range naturally, which produces varied and interesting panel dynamics.")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print("Loading utterances from all balanced panel runs...")
    utterances = load_all_utterances()
    print(f"  Loaded {len(utterances):,} turns from {len(set(u['run'] for u in utterances))} runs")

    # Count per expert
    expert_counts = defaultdict(int)
    for u in utterances:
        expert_counts[u["speaker"]] += 1
    for expert, count in sorted(expert_counts.items(), key=lambda x: -x[1]):
        print(f"  {expert}: {count} turns")

    print("\nBuilding TF-IDF matrix...")
    matrix, vectorizer = build_tfidf_matrix(utterances)
    print(f"  Matrix shape: {matrix.shape}")

    print("\nComputing intra-expert distances...")
    intra_dists = compute_intra_expert_distances(matrix, utterances)
    for expert, d in sorted(intra_dists.items(), key=lambda x: x[1]["mean_distance"]):
        print(f"  {expert}: mean={d['mean_distance']:.4f} (n={d['n_utterances']})")

    print("\nComputing condition centroids and responsiveness...")
    centroids = compute_expert_condition_centroids(matrix, utterances)
    responsiveness = compute_condition_responsiveness(centroids)
    for expert, r in sorted(responsiveness.items(), key=lambda x: -x[1]["mean_centroid_shift"]):
        print(f"  {expert}: shift={r['mean_centroid_shift']:.4f}")

    print("\nComputing silhouette scores...")
    sil_expert = compute_silhouette_by_label(matrix, utterances, "speaker")
    sil_condition = compute_silhouette_by_label(matrix, utterances, "condition")
    print(f"  Expert silhouette: {sil_expert:.4f}")
    print(f"  Condition silhouette: {sil_condition:.4f}")

    print("\nComputing adjusted Rand indices...")
    ari = compute_adjusted_rand(matrix, utterances)
    print(f"  ARI (expert): {ari['ari_expert']:.4f}")
    print(f"  ARI (condition): {ari['ari_condition']:.4f}")

    print("\nComputing top terms per expert...")
    top_terms = compute_top_terms_per_expert(matrix, utterances, vectorizer)

    print("\nComputing condition-specific vocabulary shifts...")
    cond_terms = compute_condition_specific_terms(matrix, utterances, vectorizer)

    print("\nComputing inter-expert similarity matrix...")
    expert_sim = compute_expert_similarity_matrix(matrix, utterances)

    print("\nRunning run-level aggregated analysis...")
    run_level = run_level_analysis(utterances)
    print(f"  {run_level['n_docs']} docs, shape {run_level['matrix_shape']}")
    print(f"  Silhouette: expert={run_level['silhouette_expert']:.4f}, "
          f"condition={run_level['silhouette_condition']:.4f}")
    print(f"  ARI: expert={run_level['ari_expert']:.4f}, "
          f"condition={run_level['ari_condition']:.4f}")
    for expert, d in sorted(run_level["intra_distances"].items(),
                            key=lambda x: x[1]["mean_distance"]):
        print(f"  {expert}: run-level dist={d['mean_distance']:.4f}")

    print("\nGenerating report...")
    report = generate_report(
        utterances, intra_dists, responsiveness,
        sil_expert, sil_condition, ari,
        top_terms, cond_terms, expert_sim,
        run_level,
    )

    report_path = REPORTS_DIR / "expert_clustering_analysis.md"
    report_path.write_text(report)
    print(f"\nReport written to {report_path}")


if __name__ == "__main__":
    main()
