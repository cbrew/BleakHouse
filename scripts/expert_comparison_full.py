"""Full expert-level comparison across all available runs.

Passage-level: A3 (character exposure), A4 (interest scores), A5 (pipeline divergence),
               A6 (panel-mate effects), C2 (assignment type breakdown)
Script-level:  B1 (airtime), B2 (vocabulary signature), B3 (quote usage),
               B4 (character mention density), B5 (cross-expert agreement)

Runs on whatever data is currently available; reports completeness.
"""

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

RUNS_DIR = Path(__file__).resolve().parent.parent / "data" / "runs"
OUT_DIR = Path(__file__).resolve().parent.parent / "reports" / "expert_comparison"
OUT_DIR.mkdir(parents=True, exist_ok=True)

ALL_EXPERTS = [
    "Eleanor Hartley", "James Blackstone", "Caroline Woodcourt",
    "Edmund Leigh", "Daniel Rosen", "Oliver Trevelyan",
]

BLEAK_CHARACTERS = {
    "Esther", "Summerson", "Jarndyce", "Richard", "Carstone", "Ada", "Clare",
    "Dedlock", "Lady Dedlock", "Sir Leicester", "Tulkinghorn", "Bucket",
    "Guppy", "Skimpole", "Jo", "Nemo", "Hawdon", "Woodcourt", "Jellyby",
    "Caddy", "Snagsby", "Mrs Snagsby", "Krook", "Miss Flite", "Flite",
    "Vholes", "Hortense", "Rosa", "Boythorn", "Chadband", "Mrs Chadband",
    "Turveydrop", "Prince", "Smallweed", "Charley", "Neckett", "Gridley",
    "George", "Rouncewell", "Trooper George", "Kenge", "Quale",
    "Pardiggle", "Mrs Pardiggle", "Watt", "Phil", "Squod", "Mercury",
    "Volumnia", "Bagnet", "Mrs Bagnet", "Peepy", "Tony Jobling",
}
_char_pat = "|".join(re.escape(c) for c in sorted(BLEAK_CHARACTERS, key=len, reverse=True))
CHAR_RE = re.compile(rf"\b({_char_pat})\b", re.IGNORECASE)

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


def tokenize(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]+(?:'[a-z]+)?", text.lower())
            if w not in STOP and len(w) > 2]


def log_likelihood(a: int, b: int, c: int, d: int) -> float:
    def safe_log(x: float) -> float:
        return math.log(x) if x > 0 else 0.0
    e1 = c * (a + b) / (c + d)
    e2 = d * (a + b) / (c + d)
    if e1 == 0 or e2 == 0:
        return 0.0
    return 2 * (a * safe_log(a / e1) + b * safe_log(b / e2))


def keywords_vs_reference(target: Counter, reference: Counter, top_n: int = 15) -> list[tuple[str, float, int, int]]:
    c = sum(target.values())
    d = sum(reference.values())
    if c == 0 or d == 0:
        return []
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


def expert_panel_key(config: dict) -> tuple[str, ...]:
    return tuple(sorted(e["name"] for e in config["experts"]))


# ---------------------------------------------------------------------------
# Load all data
# ---------------------------------------------------------------------------

variants = sorted(d.name for d in RUNS_DIR.iterdir() if d.is_dir())
runs: list[tuple[str, dict, list[dict], str, dict | None]] = []

for variant in variants:
    config, assignments, pipeline = load_run(variant)
    if not config or not assignments:
        continue
    episode = load_episode(variant)
    runs.append((variant, config, assignments, pipeline, episode))

print(f"Loaded {len(runs)} runs ({sum(1 for _,_,_,p,_ in runs if p=='transport')} transport, "
      f"{sum(1 for _,_,_,p,_ in runs if p=='embedding')} embedding), "
      f"{sum(1 for _,_,_,_,e in runs if e)} with scripts\n")


# ---------------------------------------------------------------------------
# Group assignments and turns by expert
# ---------------------------------------------------------------------------

# passage-level: expert -> pipeline -> list of assignment dicts
expert_assigns: dict[str, dict[str, list[dict]]] = {
    e: {"transport": [], "embedding": []} for e in ALL_EXPERTS
}
# track which panels each expert appears in, and which passages per (expert, panel, pipeline)
expert_panel_passages: dict[str, dict[str, dict[tuple, set[str]]]] = {
    e: {"transport": defaultdict(set), "embedding": defaultdict(set)} for e in ALL_EXPERTS
}

# script-level: expert -> pipeline -> list of turn texts
expert_turns: dict[str, dict[str, list[str]]] = {
    e: {"transport": [], "embedding": []} for e in ALL_EXPERTS
}
# per-run turn counts and word counts
expert_airtime: dict[str, dict[str, list[tuple[int, int]]]] = {
    e: {"transport": [], "embedding": []} for e in ALL_EXPERTS
}
# per-run: expert -> pipeline -> list of (variant, assigned_quotes, turn_texts)
expert_quote_data: dict[str, dict[str, list[tuple[str, list[str], list[str]]]]] = {
    e: {"transport": [], "embedding": []} for e in ALL_EXPERTS
}

# Map expert persona names to config expert names for speaker matching
# In scripts, speakers are the persona names which match expert names
for variant, config, assignments, pipeline, episode in runs:
    panel = expert_panel_key(config)
    expert_names_in_run = {e["name"] for e in config["experts"]}

    # Group assignments
    by_expert: dict[str, list[dict]] = defaultdict(list)
    for a in assignments:
        exp = a.get("expert", "")
        if exp and exp != "_episode_structure" and exp in expert_names_in_run:
            by_expert[exp].append(a)

    for exp_name, exp_assigns in by_expert.items():
        if exp_name not in expert_assigns:
            continue
        expert_assigns[exp_name][pipeline].extend(exp_assigns)
        pids = {a["passage_id"] for a in exp_assigns}
        expert_panel_passages[exp_name][pipeline][panel] |= pids

    # Group turns by speaker
    if episode:
        speaker_turns: dict[str, list[str]] = defaultdict(list)
        speaker_turn_counts: dict[str, int] = defaultdict(int)
        speaker_word_counts: dict[str, int] = defaultdict(int)
        for seg in episode["segments"]:
            for turn in seg["turns"]:
                speaker = turn.get("speaker", "")
                texts = [u["text"] for u in turn["utterances"]]
                full = " ".join(texts)
                speaker_turns[speaker].append(full)
                speaker_turn_counts[speaker] += 1
                speaker_word_counts[speaker] += len(full.split())

        for exp_name in expert_names_in_run:
            if exp_name not in expert_turns:
                continue
            turns_for_exp = speaker_turns.get(exp_name, [])
            expert_turns[exp_name][pipeline].extend(turns_for_exp)
            tc = speaker_turn_counts.get(exp_name, 0)
            wc = speaker_word_counts.get(exp_name, 0)
            expert_airtime[exp_name][pipeline].append((tc, wc))

            # Quote data
            quotes = [a.get("best_quote", "") for a in by_expert.get(exp_name, [])
                      if a.get("best_quote", "")]
            expert_quote_data[exp_name][pipeline].append((variant, quotes, turns_for_exp))


lines: list[str] = []


def out(s: str = "") -> None:
    print(s)
    lines.append(s)


out("=" * 78)
out("EXPERT-LEVEL COMPARISON — FULL ANALYSIS")
out(f"({len(runs)} runs, preliminary)")
out("=" * 78)

# ---------------------------------------------------------------------------
# A3: Character exposure
# ---------------------------------------------------------------------------
out("\n\n--- A3: Character Exposure per Expert ---")
out("  (top characters from assigned passages, by frequency)\n")

for pipeline in ["transport", "embedding"]:
    out(f"  [{pipeline.upper()}]")
    for e in ALL_EXPERTS:
        assigns = [a for v, c, aa, p, _ in runs if p == pipeline
                   for a in aa
                   if a.get("expert") == e and a.get("expert") != "_episode_structure"]
        if not assigns:
            out(f"  {e}: (no data)")
            continue
        char_counts: Counter = Counter()
        for a in assigns:
            for ch in a.get("characters_present", []):
                char_counts[ch] += 1
        top = char_counts.most_common(10)
        top_str = ", ".join(f"{ch}({n})" for ch, n in top)
        out(f"  {e} ({len(assigns)} passages): {top_str}")
    out()

# ---------------------------------------------------------------------------
# A4: Interest score distribution
# ---------------------------------------------------------------------------
out("\n--- A4: Interest Score Distribution per Expert ---\n")

for pipeline in ["transport", "embedding"]:
    out(f"  [{pipeline.upper()}]")
    out(f"  {'Expert':<22s} {'Mean':>6s} {'Med':>6s} {'Min':>6s} {'Max':>6s} {'N':>6s} {'Dist (1/2/3/4/5)':>20s}")
    out(f"  {'-'*22} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*20}")
    for e in ALL_EXPERTS:
        scores = [a["interest_score"] for a in expert_assigns[e][pipeline]
                  if "interest_score" in a]
        if not scores:
            out(f"  {e:<22s} {'—':>6s}")
            continue
        dist = Counter(scores)
        dist_str = "/".join(str(dist.get(i, 0)) for i in range(1, 6))
        out(f"  {e:<22s} {sum(scores)/len(scores):>6.2f} {sorted(scores)[len(scores)//2]:>6d} "
            f"{min(scores):>6d} {max(scores):>6d} {len(scores):>6d} {dist_str:>20s}")
    out()

# ---------------------------------------------------------------------------
# A5: Pipeline divergence per expert (same panel)
# ---------------------------------------------------------------------------
out("\n--- A5: Pipeline Divergence per Expert (same panel) ---")
out("  Jaccard overlap of passage sets for same expert in same panel\n")

out(f"  {'Expert':<22s} {'Panels':>7s} {'Mean J':>8s} {'Min J':>8s} {'Max J':>8s}")
out(f"  {'-'*22} {'-'*7} {'-'*8} {'-'*8} {'-'*8}")

for e in ALL_EXPERTS:
    t_panels = expert_panel_passages[e]["transport"]
    e_panels = expert_panel_passages[e]["embedding"]
    shared_panels = set(t_panels.keys()) & set(e_panels.keys())
    if not shared_panels:
        out(f"  {e:<22s} {'0':>7s} {'—':>8s}")
        continue
    jaccards = []
    for panel in shared_panels:
        t_pids = t_panels[panel]
        e_pids = e_panels[panel]
        inter = len(t_pids & e_pids)
        union = len(t_pids | e_pids)
        j = inter / union if union > 0 else 0
        jaccards.append(j)
    out(f"  {e:<22s} {len(shared_panels):>7d} {sum(jaccards)/len(jaccards):>8.3f} "
        f"{min(jaccards):>8.3f} {max(jaccards):>8.3f}")

# ---------------------------------------------------------------------------
# A6: Panel-mate effects
# ---------------------------------------------------------------------------
out("\n\n--- A6: Panel-Mate Effects ---")
out("  How much does panel composition change what an expert gets?\n")

for pipeline in ["transport"]:  # Focus on transport where we have more data
    out(f"  [{pipeline.upper()}]")
    for e in ALL_EXPERTS:
        panels = expert_panel_passages[e][pipeline]
        if len(panels) < 2:
            out(f"  {e}: only {len(panels)} panel(s), skipping")
            continue
        # Pairwise Jaccard between the expert's passage sets across panels
        panel_list = list(panels.keys())
        jaccards = []
        for i in range(len(panel_list)):
            for j in range(i + 1, len(panel_list)):
                p1 = panels[panel_list[i]]
                p2 = panels[panel_list[j]]
                inter = len(p1 & p2)
                union = len(p1 | p2)
                jaccards.append(inter / union if union > 0 else 0)
        # Also count total unique passages across all panels
        all_pids = set()
        for pids in panels.values():
            all_pids |= pids
        out(f"  {e} ({len(panels)} panels, {len(all_pids)} unique passages):")
        out(f"    Mean pairwise Jaccard: {sum(jaccards)/len(jaccards):.3f} "
            f"(min={min(jaccards):.3f}, max={max(jaccards):.3f})")
        # Show which panel-mates correlate with the most/least distinctive passages
        # by showing the panel with highest and lowest passage count
        sizes = {p: len(pids) for p, pids in panels.items()}
        biggest = max(sizes, key=sizes.get)  # type: ignore[arg-type]
        smallest = min(sizes, key=sizes.get)  # type: ignore[arg-type]
        # Show panel-mate names (excluding the expert themselves)
        big_mates = [n for n in biggest if n != e]
        small_mates = [n for n in smallest if n != e]
        out(f"    Most passages ({sizes[biggest]}): with {', '.join(n.split()[0] for n in big_mates)}")
        out(f"    Fewest passages ({sizes[smallest]}): with {', '.join(n.split()[0] for n in small_mates)}")
    out()

# ---------------------------------------------------------------------------
# C2: Assignment type breakdown
# ---------------------------------------------------------------------------
out("\n--- C2: Assignment Type Breakdown per Expert ---")
out("  (fraction of passages by assignment_type)\n")

for pipeline in ["transport", "embedding"]:
    out(f"  [{pipeline.upper()}]")
    out(f"  {'Expert':<22s} {'expert%':>8s} {'arc%':>8s} {'struct%':>8s} {'N':>6s}")
    out(f"  {'-'*22} {'-'*8} {'-'*8} {'-'*8} {'-'*6}")
    for e in ALL_EXPERTS:
        assigns = expert_assigns[e][pipeline]
        if not assigns:
            out(f"  {e:<22s} {'—':>8s}")
            continue
        types = Counter(a.get("assignment_type", "expert") for a in assigns)
        total = sum(types.values())
        out(f"  {e:<22s} {types.get('expert',0)/total:>7.0%} {types.get('arc',0)/total:>7.0%} "
            f"{types.get('structure',0)/total:>7.0%} {total:>6d}")
    out()

# ===================================================================
# SCRIPT-LEVEL ANALYSES
# ===================================================================

out("\n" + "=" * 78)
out("SCRIPT-LEVEL ANALYSES")
out("=" * 78)

# ---------------------------------------------------------------------------
# B1: Airtime
# ---------------------------------------------------------------------------
out("\n--- B1: Airtime per Expert ---")
out("  (turns and words per episode, averaged across runs)\n")

for pipeline in ["transport", "embedding"]:
    out(f"  [{pipeline.upper()}]")
    out(f"  {'Expert':<22s} {'Runs':>5s} {'MeanTurns':>10s} {'MeanWords':>10s} {'Words%':>8s}")
    out(f"  {'-'*22} {'-'*5} {'-'*10} {'-'*10} {'-'*8}")
    # Compute total words per run for percentage
    run_total_words: dict[str, int] = {}
    for v, c, aa, p, ep in runs:
        if p == pipeline and ep:
            total = sum(len(u["text"].split()) for seg in ep["segments"]
                        for turn in seg["turns"] for u in turn["utterances"])
            run_total_words[v] = total

    for e in ALL_EXPERTS:
        data = expert_airtime[e][pipeline]
        if not data:
            out(f"  {e:<22s} {'0':>5s}")
            continue
        turns = [tc for tc, wc in data]
        words = [wc for tc, wc in data]
        # rough words% - expert words / total words in episodes where they appear
        # this is approximate since we're averaging across runs
        mean_w = sum(words) / len(words)
        out(f"  {e:<22s} {len(data):>5d} {sum(turns)/len(turns):>10.1f} "
            f"{mean_w:>10.0f} {'—':>8s}")
    out()

# ---------------------------------------------------------------------------
# B2: Vocabulary signature (Kilgarriff G2 keywords)
# ---------------------------------------------------------------------------
out("\n--- B2: Vocabulary Signature per Expert ---")
out("  (G2 keywords: this expert vs all other experts, pooled across runs)\n")

for pipeline in ["transport", "embedding"]:
    out(f"  [{pipeline.upper()}]")
    # Build per-expert corpus
    expert_corpora: dict[str, Counter] = {}
    all_corpus: Counter = Counter()
    for e in ALL_EXPERTS:
        corpus: Counter = Counter()
        for text in expert_turns[e][pipeline]:
            corpus.update(tokenize(text))
        expert_corpora[e] = corpus
        all_corpus += corpus

    for e in ALL_EXPERTS:
        if not expert_corpora[e]:
            out(f"  {e}: (no script data)")
            continue
        reference = all_corpus - expert_corpora[e]
        kws = keywords_vs_reference(expert_corpora[e], reference, top_n=12)
        kw_str = ", ".join(f"{w}" for w, _, _, _ in kws[:10])
        out(f"  {e} ({sum(expert_corpora[e].values())} tokens):")
        out(f"    {kw_str}")
    out()

# ---------------------------------------------------------------------------
# B3: Quote usage per expert
# ---------------------------------------------------------------------------
out("\n--- B3: Quote Recovery per Expert ---")
out("  (fraction of assigned best_quotes that appear in the expert's turns)\n")

for pipeline in ["transport", "embedding"]:
    out(f"  [{pipeline.upper()}]")
    out(f"  {'Expert':<22s} {'Found':>6s} {'Total':>6s} {'Rate':>8s}")
    out(f"  {'-'*22} {'-'*6} {'-'*6} {'-'*8}")
    for e in ALL_EXPERTS:
        total_found = 0
        total_quotes = 0
        for variant, quotes, turn_texts in expert_quote_data[e][pipeline]:
            if not quotes or not turn_texts:
                continue
            all_text = " ".join(turn_texts).lower()
            for q in quotes:
                if len(q) < 10:
                    continue
                total_quotes += 1
                words = q.lower().split()
                if len(words) >= 5:
                    sub1 = " ".join(words[:5])
                    mid = len(words) // 2 - 2
                    sub2 = " ".join(words[max(0, mid):max(0, mid) + 5])
                    if sub1 in all_text or sub2 in all_text:
                        total_found += 1
                elif q.lower() in all_text:
                    total_found += 1
        if total_quotes == 0:
            out(f"  {e:<22s} {'—':>6s}")
        else:
            out(f"  {e:<22s} {total_found:>6d} {total_quotes:>6d} {total_found/total_quotes:>7.0%}")
    out()

# ---------------------------------------------------------------------------
# B4: Character mention density per expert (in script turns)
# ---------------------------------------------------------------------------
out("\n--- B4: Character Mention Density per Expert (in script) ---")
out("  (character mentions per 1,000 words of that expert's dialogue)\n")

for pipeline in ["transport", "embedding"]:
    out(f"  [{pipeline.upper()}]")
    out(f"  {'Expert':<22s} {'Mentions':>9s} {'Words':>8s} {'Per 1k':>8s} {'Unique':>7s} {'Top characters':>30s}")
    out(f"  {'-'*22} {'-'*9} {'-'*8} {'-'*8} {'-'*7} {'-'*30}")
    for e in ALL_EXPERTS:
        all_text = " ".join(expert_turns[e][pipeline])
        if not all_text.strip():
            out(f"  {e:<22s} {'—':>9s}")
            continue
        wc = len(all_text.split())
        matches = CHAR_RE.findall(all_text)
        count = len(matches)
        unique = {m.title() for m in matches}
        char_freq = Counter(m.title() for m in matches)
        top3 = ", ".join(f"{c}" for c, _ in char_freq.most_common(3))
        density = count / wc * 1000 if wc else 0
        out(f"  {e:<22s} {count:>9d} {wc:>8d} {density:>8.1f} {len(unique):>7d} {top3:>30s}")
    out()

# ---------------------------------------------------------------------------
# B5: Cross-expert agreement
# ---------------------------------------------------------------------------
out("\n--- B5: Cross-Expert Agreement ---")
out("  When the same passage is assigned to different experts across runs,")
out("  do they mention the same characters?\n")

# Build: passage_id -> {expert -> set of character mentions in their turns}
# This is approximate: we track which characters the expert mentions in all turns
# for runs where they have that passage assigned

passage_expert_chars: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

for variant, config, assignments, pipeline, episode in runs:
    if not episode:
        continue
    expert_names = {e["name"] for e in config["experts"]}
    # Build passage->expert mapping
    pass_to_exp: dict[str, str] = {}
    for a in assignments:
        exp = a.get("expert", "")
        if exp and exp != "_episode_structure" and exp in expert_names:
            pass_to_exp[a["passage_id"]] = exp

    # Get character mentions per speaker
    speaker_chars: dict[str, set[str]] = defaultdict(set)
    for seg in episode["segments"]:
        for turn in seg["turns"]:
            speaker = turn.get("speaker", "")
            text = " ".join(u["text"] for u in turn["utterances"])
            chars_mentioned = {m.title() for m in CHAR_RE.findall(text)}
            speaker_chars[speaker] |= chars_mentioned

    for pid, exp in pass_to_exp.items():
        if exp in speaker_chars:
            passage_expert_chars[pid][exp] |= speaker_chars[exp]

# Find passages assigned to multiple experts across runs
multi_expert_passages = {pid: experts for pid, experts in passage_expert_chars.items()
                         if len(experts) >= 2}

if not multi_expert_passages:
    out("  No passages found assigned to multiple experts across runs.")
else:
    out(f"  {len(multi_expert_passages)} passages assigned to 2+ different experts across runs\n")
    # Compute pairwise Jaccard of character sets
    pair_jaccards: list[float] = []
    pair_details: list[tuple[str, str, str, float]] = []
    for pid, experts in multi_expert_passages.items():
        exp_list = list(experts.keys())
        for i in range(len(exp_list)):
            for j in range(i + 1, len(exp_list)):
                e1, e2 = exp_list[i], exp_list[j]
                c1 = experts[e1]
                c2 = experts[e2]
                inter = len(c1 & c2)
                union = len(c1 | c2)
                jacc = inter / union if union else 0
                pair_jaccards.append(jacc)
                pair_details.append((pid, e1, e2, jacc))

    out(f"  {len(pair_jaccards)} expert pairs across shared passages")
    out(f"  Mean character overlap (Jaccard): {sum(pair_jaccards)/len(pair_jaccards):.3f}")
    out(f"  Median: {sorted(pair_jaccards)[len(pair_jaccards)//2]:.3f}")

    # Show a few examples
    pair_details.sort(key=lambda x: -x[3])
    out(f"\n  Highest agreement:")
    for pid, e1, e2, j in pair_details[:3]:
        out(f"    {pid}: {e1.split()[0]} & {e2.split()[0]} → Jaccard={j:.2f}")
    pair_details.sort(key=lambda x: x[3])
    out(f"  Lowest agreement:")
    for pid, e1, e2, j in pair_details[:3]:
        out(f"    {pid}: {e1.split()[0]} & {e2.split()[0]} → Jaccard={j:.2f}")

# ---------------------------------------------------------------------------
# Visualizations
# ---------------------------------------------------------------------------

# A4: Interest score box plot
fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)
for idx, pipeline in enumerate(["transport", "embedding"]):
    ax = axes[idx]
    data_for_plot = []
    labels = []
    for e in ALL_EXPERTS:
        scores = [a["interest_score"] for a in expert_assigns[e][pipeline]
                  if "interest_score" in a]
        if scores:
            data_for_plot.append(scores)
            labels.append(e.split()[0])
    if data_for_plot:
        bp = ax.boxplot(data_for_plot, labels=labels, patch_artist=True)
        for patch in bp["boxes"]:
            patch.set_facecolor("#64B5F6" if pipeline == "transport" else "#FFB74D")
    ax.set_title(f"{pipeline.title()}")
    ax.set_ylabel("Interest Score")
    ax.set_ylim(0, 6)
fig.suptitle("A4: Interest Score Distribution per Expert", fontsize=13)
plt.tight_layout()
plt.savefig(OUT_DIR / "a4_interest_scores.png", dpi=150, bbox_inches="tight")
out(f"\nA4 box plot saved to {OUT_DIR / 'a4_interest_scores.png'}")

# B1: Airtime bar chart
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
for idx, pipeline in enumerate(["transport", "embedding"]):
    ax = axes[idx]
    names = []
    mean_words = []
    for e in ALL_EXPERTS:
        data = expert_airtime[e][pipeline]
        if data:
            names.append(e.split()[0])
            mean_words.append(sum(wc for _, wc in data) / len(data))
    if names:
        colors = plt.cm.Set2(np.linspace(0, 1, len(names)))  # type: ignore[attr-defined]
        ax.barh(names, mean_words, color=colors)
        ax.set_xlabel("Mean words per episode")
    ax.set_title(f"{pipeline.title()}")
fig.suptitle("B1: Expert Airtime (words per episode)", fontsize=13)
plt.tight_layout()
plt.savefig(OUT_DIR / "b1_airtime.png", dpi=150, bbox_inches="tight")
out(f"B1 bar chart saved to {OUT_DIR / 'b1_airtime.png'}")

# B4: Character mention density comparison
fig, ax = plt.subplots(figsize=(10, 5))
x = np.arange(len(ALL_EXPERTS))
width = 0.35
t_densities = []
e_densities = []
for e in ALL_EXPERTS:
    for pipeline, target in [("transport", t_densities), ("embedding", e_densities)]:
        text = " ".join(expert_turns[e][pipeline])
        wc = len(text.split())
        mentions = len(CHAR_RE.findall(text))
        target.append(mentions / wc * 1000 if wc else 0)

ax.bar(x - width/2, t_densities, width, label="Transport", color="#2196F3")
ax.bar(x + width/2, e_densities, width, label="Embedding", color="#FF9800")
ax.set_xticks(x)
ax.set_xticklabels([e.split()[0] for e in ALL_EXPERTS], fontsize=9)
ax.set_ylabel("Character mentions / 1k words")
ax.set_title("B4: Character Mention Density per Expert")
ax.legend()
plt.tight_layout()
plt.savefig(OUT_DIR / "b4_char_density.png", dpi=150, bbox_inches="tight")
out(f"B4 bar chart saved to {OUT_DIR / 'b4_char_density.png'}")

# Save report
with open(OUT_DIR / "full_report.txt", "w") as f:
    f.write("\n".join(lines))
out(f"\nFull report saved to {OUT_DIR / 'full_report.txt'}")
