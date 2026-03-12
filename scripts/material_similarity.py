"""Are transport and embedding passages for the same expert functionally similar?

Tier 1: Provision centroids, character JSD, theme JSD, chapter Jaccard
Tier 2: TF-IDF nearest-neighbor analysis
Tier 3: Script-level convergence (vocabulary cosine, character Jaccard)
Tier 4: Embedding-space centroid distance and MMD
"""

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import lancedb
import numpy as np
from scipy.spatial.distance import cosine as cosine_dist
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RUNS_DIR = Path(__file__).resolve().parent.parent / "data" / "runs"
OUT_DIR = Path(__file__).resolve().parent.parent / "reports" / "material_similarity"
OUT_DIR.mkdir(parents=True, exist_ok=True)

ALL_EXPERTS = [
    "Eleanor Hartley", "James Blackstone", "Caroline Woodcourt",
    "Edmund Leigh", "Daniel Rosen", "Oliver Trevelyan",
]

PROVISION_DIMS = [
    "prov_character_development", "prov_plot_advancement",
    "prov_thematic_depth", "prov_social_critique",
    "prov_humor_entertainment", "prov_atmosphere_setting",
    "prov_narrative_technique",
]

BLEAK_CHARACTERS = {
    "Esther", "Summerson", "Jarndyce", "Richard", "Carstone", "Ada", "Clare",
    "Dedlock", "Lady Dedlock", "Sir Leicester", "Tulkinghorn", "Bucket",
    "Guppy", "Skimpole", "Jo", "Nemo", "Hawdon", "Woodcourt", "Jellyby",
    "Caddy", "Snagsby", "Krook", "Miss Flite", "Flite", "Vholes",
    "Hortense", "Rosa", "Boythorn", "Chadband", "Turveydrop",
    "Smallweed", "Charley", "Neckett", "Gridley", "George", "Rouncewell",
    "Kenge", "Pardiggle", "Bagnet", "Volumnia", "Peepy",
}
_char_pat = "|".join(re.escape(c) for c in sorted(BLEAK_CHARACTERS, key=len, reverse=True))
CHAR_RE = re.compile(rf"\b({_char_pat})\b", re.IGNORECASE)


def prov_score(val: str) -> float:
    return 2.0 if val == "strong" else 1.0 if val == "weak" else 0.0


def jsd(p: np.ndarray, q: np.ndarray) -> float:
    """Jensen-Shannon divergence."""
    p = p / (p.sum() + 1e-12)
    q = q / (q.sum() + 1e-12)
    m = 0.5 * (p + q)
    def kl(a: np.ndarray, b: np.ndarray) -> float:
        mask = a > 0
        return float(np.sum(a[mask] * np.log(a[mask] / b[mask])))
    return 0.5 * kl(p, m) + 0.5 * kl(q, m)


def load_run(variant: str) -> tuple[dict | None, list[dict], str]:
    config_path = RUNS_DIR / variant / "config.json"
    assign_path = RUNS_DIR / variant / "phase1_assignments.json"
    if not config_path.exists() or not assign_path.exists():
        return None, [], ""
    with open(config_path) as f:
        config = json.load(f)
    with open(assign_path) as f:
        assignments = json.load(f)["assignments"]
    return config, assignments, config.get("pipeline_type", "transport")


def load_episode(variant: str) -> dict | None:
    path = RUNS_DIR / variant / "phase3_episode.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def expert_panel_key(config: dict) -> tuple[str, ...]:
    return tuple(sorted(e["name"] for e in config["experts"]))


# ---------------------------------------------------------------------------
# Load all runs
# ---------------------------------------------------------------------------

variants = sorted(d.name for d in RUNS_DIR.iterdir() if d.is_dir())

# Per (expert, panel) -> pipeline -> list of assignment dicts
epp_assigns: dict[tuple[str, tuple], dict[str, list]] = defaultdict(
    lambda: defaultdict(list)
)
# Per (expert, panel) -> pipeline -> list of turn texts
epp_turns: dict[tuple[str, tuple], dict[str, list]] = defaultdict(
    lambda: defaultdict(list)
)
# Also flat: expert -> pipeline -> list of assignments
expert_assigns: dict[str, dict[str, list]] = {
    e: defaultdict(list) for e in ALL_EXPERTS
}
expert_turns: dict[str, dict[str, list]] = {
    e: defaultdict(list) for e in ALL_EXPERTS
}

run_count = 0
script_count = 0

for variant in variants:
    config, assignments, pipeline = load_run(variant)
    if not config or not assignments:
        continue
    run_count += 1
    panel = expert_panel_key(config)
    expert_names = {e["name"] for e in config["experts"]}
    episode = load_episode(variant)
    if episode:
        script_count += 1

    by_expert: dict[str, list[dict]] = defaultdict(list)
    for a in assignments:
        exp = a.get("expert", "")
        if exp and exp != "_episode_structure" and exp in expert_names:
            by_expert[exp].append(a)

    for exp, assigns in by_expert.items():
        if exp not in expert_assigns:
            continue
        epp_assigns[(exp, panel)][pipeline].extend(assigns)
        expert_assigns[exp][pipeline].extend(assigns)

    if episode:
        speaker_turns: dict[str, list[str]] = defaultdict(list)
        for seg in episode["segments"]:
            for turn in seg["turns"]:
                speaker = turn.get("speaker", "")
                text = " ".join(u["text"] for u in turn["utterances"])
                speaker_turns[speaker].append(text)
        for exp in expert_names:
            if exp in speaker_turns and exp in expert_turns:
                epp_turns[(exp, panel)][pipeline].extend(speaker_turns[exp])
                expert_turns[exp][pipeline].extend(speaker_turns[exp])

print(f"Loaded {run_count} runs, {script_count} with scripts\n")

lines: list[str] = []


def out(s: str = "") -> None:
    print(s)
    lines.append(s)


out("=" * 78)
out("MATERIAL SIMILARITY: TRANSPORT vs EMBEDDING PER EXPERT")
out(f"({run_count} runs, preliminary)")
out("=" * 78)

# ===================================================================
# TIER 1: Metadata profiles
# ===================================================================

out("\n" + "=" * 78)
out("TIER 1: METADATA PROFILE COMPARISON")
out("=" * 78)

# --- 1a: Provision vector centroids ---
out("\n--- 1a: Provision Vector Centroid Distance ---")
out("  Euclidean distance between transport and embedding centroids per expert")
out("  (7-dim space, scale 0–2 per dim; max possible ~5.3)\n")

out(f"  {'Expert':<22s} {'Panels':>7s} {'MeanDist':>9s} {'MinDist':>9s} {'MaxDist':>9s}")
out(f"  {'-'*22} {'-'*7} {'-'*9} {'-'*9} {'-'*9}")

prov_distances_all: list[float] = []
for e in ALL_EXPERTS:
    dists = []
    for (exp, panel), pipelines in epp_assigns.items():
        if exp != e:
            continue
        t_assigns = pipelines["transport"]
        e_assigns = pipelines["embedding"]
        if not t_assigns or not e_assigns:
            continue
        # Compute centroids
        t_centroid = np.zeros(7)
        for a in t_assigns:
            provs = a.get("provisions", {})
            for i, d in enumerate(PROVISION_DIMS):
                t_centroid[i] += prov_score(provs.get(d, "none"))
        t_centroid /= len(t_assigns)

        e_centroid = np.zeros(7)
        for a in e_assigns:
            provs = a.get("provisions", {})
            for i, d in enumerate(PROVISION_DIMS):
                e_centroid[i] += prov_score(provs.get(d, "none"))
        e_centroid /= len(e_assigns)

        dist = float(np.linalg.norm(t_centroid - e_centroid))
        dists.append(dist)
        prov_distances_all.append(dist)

    if dists:
        out(f"  {e:<22s} {len(dists):>7d} {sum(dists)/len(dists):>9.3f} {min(dists):>9.3f} {max(dists):>9.3f}")
    else:
        out(f"  {e:<22s} {'—':>7s}")

if prov_distances_all:
    out(f"\n  Overall mean provision centroid distance: {sum(prov_distances_all)/len(prov_distances_all):.3f}")

# --- 1b: Character distribution JSD ---
out("\n\n--- 1b: Character Distribution JSD ---")
out("  Jensen-Shannon divergence of character frequencies (0=identical, ln2≈0.69=disjoint)\n")

all_chars_sorted = sorted(BLEAK_CHARACTERS)
char_idx = {c: i for i, c in enumerate(all_chars_sorted)}
n_chars = len(all_chars_sorted)

out(f"  {'Expert':<22s} {'Panels':>7s} {'MeanJSD':>9s} {'MinJSD':>9s} {'MaxJSD':>9s}")
out(f"  {'-'*22} {'-'*7} {'-'*9} {'-'*9} {'-'*9}")

char_jsds_all: list[float] = []
for e in ALL_EXPERTS:
    jsds = []
    for (exp, panel), pipelines in epp_assigns.items():
        if exp != e:
            continue
        t_assigns = pipelines["transport"]
        e_assigns = pipelines["embedding"]
        if not t_assigns or not e_assigns:
            continue

        t_vec = np.zeros(n_chars)
        for a in t_assigns:
            for ch in a.get("characters_present", []):
                for known in all_chars_sorted:
                    if known.lower() in ch.lower():
                        t_vec[char_idx[known]] += 1

        e_vec = np.zeros(n_chars)
        for a in e_assigns:
            for ch in a.get("characters_present", []):
                for known in all_chars_sorted:
                    if known.lower() in ch.lower():
                        e_vec[char_idx[known]] += 1

        if t_vec.sum() > 0 and e_vec.sum() > 0:
            j = jsd(t_vec, e_vec)
            jsds.append(j)
            char_jsds_all.append(j)

    if jsds:
        out(f"  {e:<22s} {len(jsds):>7d} {sum(jsds)/len(jsds):>9.3f} {min(jsds):>9.3f} {max(jsds):>9.3f}")
    else:
        out(f"  {e:<22s} {'—':>7s}")

if char_jsds_all:
    out(f"\n  Overall mean character JSD: {sum(char_jsds_all)/len(char_jsds_all):.3f}")

# --- 1c: Theme distribution JSD ---
out("\n\n--- 1c: Theme Distribution JSD ---\n")

# Collect all themes first
all_themes: set[str] = set()
for e in ALL_EXPERTS:
    for pipeline in ["transport", "embedding"]:
        for a in expert_assigns[e][pipeline]:
            all_themes.update(a.get("themes", []))
all_themes_sorted = sorted(all_themes)
theme_idx = {t: i for i, t in enumerate(all_themes_sorted)}
n_themes = len(all_themes_sorted)

out(f"  {n_themes} unique themes across all passages\n")
out(f"  {'Expert':<22s} {'Panels':>7s} {'MeanJSD':>9s} {'MinJSD':>9s} {'MaxJSD':>9s}")
out(f"  {'-'*22} {'-'*7} {'-'*9} {'-'*9} {'-'*9}")

theme_jsds_all: list[float] = []
for e in ALL_EXPERTS:
    jsds = []
    for (exp, panel), pipelines in epp_assigns.items():
        if exp != e:
            continue
        t_assigns = pipelines["transport"]
        e_assigns = pipelines["embedding"]
        if not t_assigns or not e_assigns:
            continue

        t_vec = np.zeros(n_themes)
        for a in t_assigns:
            for th in a.get("themes", []):
                if th in theme_idx:
                    t_vec[theme_idx[th]] += 1

        e_vec = np.zeros(n_themes)
        for a in e_assigns:
            for th in a.get("themes", []):
                if th in theme_idx:
                    e_vec[theme_idx[th]] += 1

        if t_vec.sum() > 0 and e_vec.sum() > 0:
            j = jsd(t_vec, e_vec)
            jsds.append(j)
            theme_jsds_all.append(j)

    if jsds:
        out(f"  {e:<22s} {len(jsds):>7d} {sum(jsds)/len(jsds):>9.3f} {min(jsds):>9.3f} {max(jsds):>9.3f}")
    else:
        out(f"  {e:<22s} {'—':>7s}")

if theme_jsds_all:
    out(f"\n  Overall mean theme JSD: {sum(theme_jsds_all)/len(theme_jsds_all):.3f}")

# --- 1d: Chapter Jaccard ---
out("\n\n--- 1d: Chapter Overlap (Jaccard) per Expert ---\n")

out(f"  {'Expert':<22s} {'Panels':>7s} {'MeanJ':>8s} {'MinJ':>8s} {'MaxJ':>8s}")
out(f"  {'-'*22} {'-'*7} {'-'*8} {'-'*8} {'-'*8}")

ch_jaccards_all: list[float] = []
for e in ALL_EXPERTS:
    jacs = []
    for (exp, panel), pipelines in epp_assigns.items():
        if exp != e:
            continue
        t_assigns = pipelines["transport"]
        e_assigns = pipelines["embedding"]
        if not t_assigns or not e_assigns:
            continue
        t_ch = {a["chapter_id"] for a in t_assigns}
        e_ch = {a["chapter_id"] for a in e_assigns}
        inter = len(t_ch & e_ch)
        union = len(t_ch | e_ch)
        j = inter / union if union else 0
        jacs.append(j)
        ch_jaccards_all.append(j)

    if jacs:
        out(f"  {e:<22s} {len(jacs):>7d} {sum(jacs)/len(jacs):>8.3f} {min(jacs):>8.3f} {max(jacs):>8.3f}")
    else:
        out(f"  {e:<22s} {'—':>7s}")

if ch_jaccards_all:
    out(f"\n  Overall mean chapter Jaccard: {sum(ch_jaccards_all)/len(ch_jaccards_all):.3f}")


# ===================================================================
# TIER 2: TF-IDF nearest neighbor
# ===================================================================

out("\n\n" + "=" * 78)
out("TIER 2: TF-IDF NEAREST-NEIGHBOR ANALYSIS")
out("=" * 78)

out("\n  For each transport passage, find most similar embedding passage (same expert).")
out("  Baselines: (a) nearest from different expert's embedding, (b) within-transport.\n")

# Build per-(expert, panel, pipeline) text lists
epp_texts: dict[tuple[str, tuple], dict[str, list[tuple[str, str]]]] = defaultdict(
    lambda: {"transport": [], "embedding": []}
)
for (exp, panel), pipelines in epp_assigns.items():
    for pipeline in ["transport", "embedding"]:
        for a in pipelines[pipeline]:
            epp_texts[(exp, panel)][pipeline].append((a["passage_id"], a.get("text", "")))

out(f"  {'Expert':<22s} {'Panels':>7s} {'SameExp':>8s} {'DiffExp':>8s} {'Within':>8s} {'Interp':>30s}")
out(f"  {'-'*22} {'-'*7} {'-'*8} {'-'*8} {'-'*8} {'-'*30}")

nn_results: dict[str, list[tuple[float, float, float]]] = {e: [] for e in ALL_EXPERTS}

for e in ALL_EXPERTS:
    for (exp, panel), pipelines in epp_texts.items():
        if exp != e:
            continue
        t_texts = pipelines["transport"]
        e_texts = pipelines["embedding"]
        if len(t_texts) < 2 or len(e_texts) < 2:
            continue

        # Collect all embedding texts from other experts in this panel
        other_e_texts = []
        for (exp2, panel2), pipelines2 in epp_texts.items():
            if panel2 == panel and exp2 != e:
                other_e_texts.extend(pipelines2["embedding"])

        # Fit TF-IDF on all texts
        all_raw = [t for _, t in t_texts] + [t for _, t in e_texts] + [t for _, t in other_e_texts]
        if len(all_raw) < 4:
            continue
        try:
            vectorizer = TfidfVectorizer(max_features=2000, stop_words="english")
            tfidf = vectorizer.fit_transform(all_raw)
        except ValueError:
            continue

        n_t = len(t_texts)
        n_e = len(e_texts)
        n_o = len(other_e_texts)

        t_vecs = tfidf[:n_t]
        e_vecs = tfidf[n_t:n_t + n_e]
        o_vecs = tfidf[n_t + n_e:]

        # Same-expert NN: transport -> embedding
        if e_vecs.shape[0] > 0:
            sim_same = cosine_similarity(t_vecs, e_vecs)
            same_nn = float(sim_same.max(axis=1).mean())
        else:
            same_nn = 0.0

        # Different-expert NN: transport -> other experts' embedding
        if o_vecs.shape[0] > 0:
            sim_diff = cosine_similarity(t_vecs, o_vecs)
            diff_nn = float(sim_diff.max(axis=1).mean())
        else:
            diff_nn = 0.0

        # Within-transport NN: each transport passage's NN among other transport passages
        if t_vecs.shape[0] > 1:
            sim_within = cosine_similarity(t_vecs, t_vecs)
            np.fill_diagonal(sim_within, -1)
            within_nn = float(sim_within.max(axis=1).mean())
        else:
            within_nn = 0.0

        nn_results[e].append((same_nn, diff_nn, within_nn))

for e in ALL_EXPERTS:
    results = nn_results[e]
    if not results:
        out(f"  {e:<22s} {'—':>7s}")
        continue
    same = sum(r[0] for r in results) / len(results)
    diff = sum(r[1] for r in results) / len(results)
    within = sum(r[2] for r in results) / len(results)
    if diff > 0:
        ratio_str = f"same/diff={same/diff:.2f}x"
    else:
        ratio_str = ""
    out(f"  {e:<22s} {len(results):>7d} {same:>8.3f} {diff:>8.3f} {within:>8.3f} {ratio_str:>30s}")

# Summary
all_same = [r[0] for e in ALL_EXPERTS for r in nn_results[e]]
all_diff = [r[1] for e in ALL_EXPERTS for r in nn_results[e]]
all_within = [r[2] for e in ALL_EXPERTS for r in nn_results[e]]
if all_same:
    out(f"\n  Overall means: same-expert NN={sum(all_same)/len(all_same):.3f}, "
        f"diff-expert NN={sum(all_diff)/len(all_diff):.3f}, "
        f"within-transport NN={sum(all_within)/len(all_within):.3f}")
    out(f"  Interpretation: same-expert > diff-expert means embedding selects material")
    out(f"  that is at least somewhat specific to the expert, not random.")
    out(f"  same-expert < within-transport means cross-pipeline material is less similar")
    out(f"  than within-pipeline diversity.")


# ===================================================================
# TIER 3: Script-level convergence
# ===================================================================

out("\n\n" + "=" * 78)
out("TIER 3: SCRIPT-LEVEL CONVERGENCE")
out("=" * 78)

# --- 3a: Vocabulary cosine ---
out("\n--- 3a: Vocabulary Cosine Similarity (expert's turns: transport vs embedding) ---\n")

out(f"  {'Expert':<22s} {'Panels':>7s} {'MeanCos':>8s} {'MinCos':>8s} {'MaxCos':>8s}")
out(f"  {'-'*22} {'-'*7} {'-'*8} {'-'*8} {'-'*8}")

vocab_cosines_all: list[float] = []
for e in ALL_EXPERTS:
    cosines = []
    for (exp, panel), pipelines in epp_turns.items():
        if exp != e:
            continue
        t_turns = pipelines["transport"]
        e_turns_list = pipelines["embedding"]
        if not t_turns or not e_turns_list:
            continue
        t_text = " ".join(t_turns)
        e_text = " ".join(e_turns_list)
        try:
            vec = TfidfVectorizer(max_features=2000, stop_words="english")
            tfidf = vec.fit_transform([t_text, e_text])
            cos = float(cosine_similarity(tfidf[0:1], tfidf[1:2])[0, 0])
            cosines.append(cos)
            vocab_cosines_all.append(cos)
        except ValueError:
            continue

    if cosines:
        out(f"  {e:<22s} {len(cosines):>7d} {sum(cosines)/len(cosines):>8.3f} {min(cosines):>8.3f} {max(cosines):>8.3f}")
    else:
        out(f"  {e:<22s} {'—':>7s}")

if vocab_cosines_all:
    out(f"\n  Overall mean vocabulary cosine: {sum(vocab_cosines_all)/len(vocab_cosines_all):.3f}")

# --- 3b: Character Jaccard in scripts ---
out("\n\n--- 3b: Character Mention Jaccard (expert's turns: transport vs embedding) ---\n")

out(f"  {'Expert':<22s} {'Panels':>7s} {'MeanJ':>8s} {'MinJ':>8s} {'MaxJ':>8s}")
out(f"  {'-'*22} {'-'*7} {'-'*8} {'-'*8} {'-'*8}")

script_char_jacs_all: list[float] = []
for e in ALL_EXPERTS:
    jacs = []
    for (exp, panel), pipelines in epp_turns.items():
        if exp != e:
            continue
        t_turns = pipelines["transport"]
        e_turns_list = pipelines["embedding"]
        if not t_turns or not e_turns_list:
            continue
        t_text = " ".join(t_turns)
        e_text = " ".join(e_turns_list)
        t_chars = {m.title() for m in CHAR_RE.findall(t_text)}
        e_chars = {m.title() for m in CHAR_RE.findall(e_text)}
        inter = len(t_chars & e_chars)
        union = len(t_chars | e_chars)
        j = inter / union if union else 0
        jacs.append(j)
        script_char_jacs_all.append(j)

    if jacs:
        out(f"  {e:<22s} {len(jacs):>7d} {sum(jacs)/len(jacs):>8.3f} {min(jacs):>8.3f} {max(jacs):>8.3f}")
    else:
        out(f"  {e:<22s} {'—':>7s}")

if script_char_jacs_all:
    out(f"\n  Overall mean character Jaccard in scripts: {sum(script_char_jacs_all)/len(script_char_jacs_all):.3f}")


# ===================================================================
# TIER 4: Embedding-space comparison
# ===================================================================

out("\n\n" + "=" * 78)
out("TIER 4: EMBEDDING-SPACE COMPARISON")
out("=" * 78)
out("\n  (Complementary to text-level measures; not a substitute.)\n")

# Load LanceDB vectors
db = lancedb.connect(str(Path(__file__).resolve().parent.parent / "data" / "bleak_house_vectors"))
table = db.open_table("passages")
df = table.to_pandas()
# Build passage_id -> vector lookup
pid_to_vec: dict[str, np.ndarray] = {}
for _, row in df.iterrows():
    pid_to_vec[row["passage_id"]] = np.array(row["vector"], dtype=np.float32)

out(f"  Loaded {len(pid_to_vec)} passage vectors from LanceDB\n")

# --- 4a: Centroid distance in embedding space ---
out("--- 4a: Embedding-Space Centroid Distance ---\n")

out(f"  {'Expert':<22s} {'Panels':>7s} {'MeanDist':>9s} {'MinDist':>9s} {'MaxDist':>9s}")
out(f"  {'-'*22} {'-'*7} {'-'*9} {'-'*9} {'-'*9}")

emb_dists_all: list[float] = []
for e in ALL_EXPERTS:
    dists = []
    for (exp, panel), pipelines in epp_assigns.items():
        if exp != e:
            continue
        t_assigns = pipelines["transport"]
        e_assigns = pipelines["embedding"]
        if not t_assigns or not e_assigns:
            continue

        t_vecs = [pid_to_vec[a["passage_id"]] for a in t_assigns if a["passage_id"] in pid_to_vec]
        e_vecs = [pid_to_vec[a["passage_id"]] for a in e_assigns if a["passage_id"] in pid_to_vec]
        if not t_vecs or not e_vecs:
            continue

        t_centroid = np.mean(t_vecs, axis=0)
        e_centroid = np.mean(e_vecs, axis=0)
        dist = float(cosine_dist(t_centroid, e_centroid))
        dists.append(dist)
        emb_dists_all.append(dist)

    if dists:
        out(f"  {e:<22s} {len(dists):>7d} {sum(dists)/len(dists):>9.4f} {min(dists):>9.4f} {max(dists):>9.4f}")
    else:
        out(f"  {e:<22s} {'—':>7s}")

if emb_dists_all:
    out(f"\n  Overall mean embedding centroid distance (cosine): {sum(emb_dists_all)/len(emb_dists_all):.4f}")

# --- 4b: MMD (Maximum Mean Discrepancy) ---
out("\n\n--- 4b: MMD (Maximum Mean Discrepancy) in Embedding Space ---")
out("  Gaussian kernel, bandwidth = median pairwise distance\n")


def compute_mmd(X: np.ndarray, Y: np.ndarray) -> float:
    """Compute MMD^2 with Gaussian kernel, median bandwidth."""
    XY = np.vstack([X, Y])
    # Compute pairwise distances for bandwidth
    from scipy.spatial.distance import pdist, squareform
    dists = pdist(XY, metric="euclidean")
    sigma = float(np.median(dists)) + 1e-8
    gamma = 1.0 / (2 * sigma ** 2)

    def kernel_mean(A: np.ndarray, B: np.ndarray) -> float:
        sq = np.sum((A[:, None, :] - B[None, :, :]) ** 2, axis=2)
        return float(np.mean(np.exp(-gamma * sq)))

    return kernel_mean(X, X) - 2 * kernel_mean(X, Y) + kernel_mean(Y, Y)


out(f"  {'Expert':<22s} {'Panels':>7s} {'MeanMMD':>9s} {'MinMMD':>9s} {'MaxMMD':>9s}")
out(f"  {'-'*22} {'-'*7} {'-'*9} {'-'*9} {'-'*9}")

mmd_all: list[float] = []
for e in ALL_EXPERTS:
    mmds = []
    for (exp, panel), pipelines in epp_assigns.items():
        if exp != e:
            continue
        t_assigns = pipelines["transport"]
        e_assigns = pipelines["embedding"]
        if not t_assigns or not e_assigns:
            continue

        t_vecs = np.array([pid_to_vec[a["passage_id"]] for a in t_assigns if a["passage_id"] in pid_to_vec])
        e_vecs = np.array([pid_to_vec[a["passage_id"]] for a in e_assigns if a["passage_id"] in pid_to_vec])
        if len(t_vecs) < 2 or len(e_vecs) < 2:
            continue

        mmd = compute_mmd(t_vecs, e_vecs)
        mmds.append(mmd)
        mmd_all.append(mmd)

    if mmds:
        out(f"  {e:<22s} {len(mmds):>7d} {sum(mmds)/len(mmds):>9.4f} {min(mmds):>9.4f} {max(mmds):>9.4f}")
    else:
        out(f"  {e:<22s} {'—':>7s}")

if mmd_all:
    out(f"\n  Overall mean MMD: {sum(mmd_all)/len(mmd_all):.4f}")
    out(f"  (MMD > 0 suggests distributional difference; magnitude depends on kernel bandwidth)")

# --- 4c: Null comparison: same expert, random split within transport ---
out("\n\n--- 4c: Null Model — Random Split Within Transport ---")
out("  Split each expert's transport passages in half, compute same metrics.\n")

rng = np.random.RandomState(42)
null_centroid_dists: list[float] = []
null_mmds: list[float] = []

for e in ALL_EXPERTS:
    for (exp, panel), pipelines in epp_assigns.items():
        if exp != e:
            continue
        t_assigns = pipelines["transport"]
        if len(t_assigns) < 4:
            continue
        t_vecs = np.array([pid_to_vec[a["passage_id"]] for a in t_assigns if a["passage_id"] in pid_to_vec])
        if len(t_vecs) < 4:
            continue
        idx = rng.permutation(len(t_vecs))
        half = len(idx) // 2
        a_vecs = t_vecs[idx[:half]]
        b_vecs = t_vecs[idx[half:]]
        c_dist = float(cosine_dist(a_vecs.mean(axis=0), b_vecs.mean(axis=0)))
        null_centroid_dists.append(c_dist)
        null_mmds.append(compute_mmd(a_vecs, b_vecs))

if null_centroid_dists:
    out(f"  Null centroid distance: {sum(null_centroid_dists)/len(null_centroid_dists):.4f} "
        f"(vs cross-pipeline: {sum(emb_dists_all)/len(emb_dists_all):.4f})")
    out(f"  Null MMD: {sum(null_mmds)/len(null_mmds):.4f} "
        f"(vs cross-pipeline: {sum(mmd_all)/len(mmd_all):.4f})")
    ratio_c = (sum(emb_dists_all)/len(emb_dists_all)) / (sum(null_centroid_dists)/len(null_centroid_dists) + 1e-12)
    ratio_m = (sum(mmd_all)/len(mmd_all)) / (sum(null_mmds)/len(null_mmds) + 1e-12)
    out(f"  Cross-pipeline / null ratio: centroid={ratio_c:.1f}x, MMD={ratio_m:.1f}x")

# ===================================================================
# SUMMARY
# ===================================================================

out("\n\n" + "=" * 78)
out("SUMMARY")
out("=" * 78)

out("""
  TIER 1 (metadata): The two pipelines select passages with [see values above]
  provision profile distance, character distribution divergence, theme divergence,
  and chapter overlap for each expert. Compare to within-pipeline null to assess
  whether the metadata-level difference is larger than sampling noise.

  TIER 2 (text): Each transport passage's nearest embedding neighbor (same expert)
  has cosine similarity [see values above]. Compare same-expert vs diff-expert NN
  to assess whether expert identity constrains the embedding pipeline's selections
  toward similar textual territory.

  TIER 3 (scripts): Despite different input passages, the script generator produces
  vocabulary with cosine similarity [see values above] and mentions overlapping
  character sets with Jaccard [see values above]. High values here mean the
  downstream output converges regardless of passage selection method.

  TIER 4 (embedding space): Centroid distance and MMD compared to within-pipeline
  null model. A ratio > 1 means cross-pipeline difference exceeds within-pipeline
  sampling variance.
""")


# ===================================================================
# Visualizations
# ===================================================================

# Tier summary bar chart
fig, axes = plt.subplots(2, 2, figsize=(14, 10))

# 1a: Provision centroid distance per expert
ax = axes[0, 0]
expert_prov_means = []
for e in ALL_EXPERTS:
    dists = []
    for (exp, panel), pipelines in epp_assigns.items():
        if exp != e:
            continue
        t_a = pipelines["transport"]
        e_a = pipelines["embedding"]
        if not t_a or not e_a:
            continue
        t_c = np.zeros(7)
        for a in t_a:
            provs = a.get("provisions", {})
            for i, d in enumerate(PROVISION_DIMS):
                t_c[i] += prov_score(provs.get(d, "none"))
        t_c /= len(t_a)
        e_c = np.zeros(7)
        for a in e_a:
            provs = a.get("provisions", {})
            for i, d in enumerate(PROVISION_DIMS):
                e_c[i] += prov_score(provs.get(d, "none"))
        e_c /= len(e_a)
        dists.append(float(np.linalg.norm(t_c - e_c)))
    expert_prov_means.append(sum(dists)/len(dists) if dists else 0)

ax.barh([e.split()[0] for e in ALL_EXPERTS], expert_prov_means, color="#42A5F5")
ax.set_xlabel("Euclidean distance")
ax.set_title("1a: Provision Centroid Distance")

# 1b: Character JSD per expert
ax = axes[0, 1]
expert_char_jsd_means = []
for e in ALL_EXPERTS:
    jsds = []
    for (exp, panel), pipelines in epp_assigns.items():
        if exp != e:
            continue
        t_a = pipelines["transport"]
        e_a = pipelines["embedding"]
        if not t_a or not e_a:
            continue
        t_v = np.zeros(n_chars)
        for a in t_a:
            for ch in a.get("characters_present", []):
                for known in all_chars_sorted:
                    if known.lower() in ch.lower():
                        t_v[char_idx[known]] += 1
        e_v = np.zeros(n_chars)
        for a in e_a:
            for ch in a.get("characters_present", []):
                for known in all_chars_sorted:
                    if known.lower() in ch.lower():
                        e_v[char_idx[known]] += 1
        if t_v.sum() > 0 and e_v.sum() > 0:
            jsds.append(jsd(t_v, e_v))
    expert_char_jsd_means.append(sum(jsds)/len(jsds) if jsds else 0)

ax.barh([e.split()[0] for e in ALL_EXPERTS], expert_char_jsd_means, color="#66BB6A")
ax.set_xlabel("JSD (0=identical, 0.69=disjoint)")
ax.set_title("1b: Character Distribution JSD")

# 3a: Vocabulary cosine per expert
ax = axes[1, 0]
expert_vocab_means = []
for e in ALL_EXPERTS:
    cosines = []
    for (exp, panel), pipelines in epp_turns.items():
        if exp != e:
            continue
        t_t = pipelines["transport"]
        e_t = pipelines["embedding"]
        if not t_t or not e_t:
            continue
        try:
            vec = TfidfVectorizer(max_features=2000, stop_words="english")
            tfidf = vec.fit_transform([" ".join(t_t), " ".join(e_t)])
            cosines.append(float(cosine_similarity(tfidf[0:1], tfidf[1:2])[0, 0]))
        except ValueError:
            continue
    expert_vocab_means.append(sum(cosines)/len(cosines) if cosines else 0)

ax.barh([e.split()[0] for e in ALL_EXPERTS], expert_vocab_means, color="#FFA726")
ax.set_xlabel("Cosine similarity")
ax.set_title("3a: Script Vocabulary Convergence")
ax.set_xlim(0, 1)

# 4a: Embedding centroid distance per expert
ax = axes[1, 1]
expert_emb_means = []
for e in ALL_EXPERTS:
    dists = []
    for (exp, panel), pipelines in epp_assigns.items():
        if exp != e:
            continue
        t_a = pipelines["transport"]
        e_a = pipelines["embedding"]
        if not t_a or not e_a:
            continue
        t_vs = [pid_to_vec[a["passage_id"]] for a in t_a if a["passage_id"] in pid_to_vec]
        e_vs = [pid_to_vec[a["passage_id"]] for a in e_a if a["passage_id"] in pid_to_vec]
        if t_vs and e_vs:
            dists.append(float(cosine_dist(np.mean(t_vs, axis=0), np.mean(e_vs, axis=0))))
    expert_emb_means.append(sum(dists)/len(dists) if dists else 0)

ax.barh([e.split()[0] for e in ALL_EXPERTS], expert_emb_means, color="#AB47BC")
ax.set_xlabel("Cosine distance")
ax.set_title("4a: Embedding Centroid Distance")

fig.suptitle("Material Similarity: Transport vs Embedding per Expert", fontsize=14)
plt.tight_layout()
plt.savefig(OUT_DIR / "tier_summary.png", dpi=150, bbox_inches="tight")
out(f"\nSummary chart saved to {OUT_DIR / 'tier_summary.png'}")

# Save report
with open(OUT_DIR / "full_report.txt", "w") as f:
    f.write("\n".join(lines))
out(f"Report saved to {OUT_DIR / 'full_report.txt'}")
