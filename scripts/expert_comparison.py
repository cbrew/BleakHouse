"""Expert-level comparison across all available runs.

Phase 1 analyses (passage-level):
  A1: Provision profile per expert
  A2: Chapter/narrator diversity per expert
  C1: Demand satisfaction rate per expert

Runs on whatever data is currently available; reports completeness.
"""

import json
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

RUNS_DIR = Path(__file__).resolve().parent.parent / "data" / "runs"
OUT_DIR = Path(__file__).resolve().parent.parent / "reports" / "expert_comparison"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PROVISION_DIMS = [
    "prov_character_development", "prov_plot_advancement",
    "prov_thematic_depth", "prov_social_critique",
    "prov_humor_entertainment", "prov_atmosphere_setting",
    "prov_narrative_technique",
]
DIM_SHORT = {
    "prov_character_development": "char_dev",
    "prov_plot_advancement": "plot",
    "prov_thematic_depth": "theme",
    "prov_social_critique": "social",
    "prov_humor_entertainment": "humor",
    "prov_atmosphere_setting": "atmos",
    "prov_narrative_technique": "narrative",
}

ALL_EXPERTS = [
    "Eleanor Hartley", "James Blackstone", "Caroline Woodcourt",
    "Edmund Leigh", "Daniel Rosen", "Oliver Trevelyan",
]


def load_run(variant: str) -> tuple[dict | None, list[dict], str]:
    """Returns (config, assignments, pipeline_type)."""
    config_path = RUNS_DIR / variant / "config.json"
    assign_path = RUNS_DIR / variant / "phase1_assignments.json"
    if not config_path.exists() or not assign_path.exists():
        return None, [], ""
    with open(config_path) as f:
        config = json.load(f)
    with open(assign_path) as f:
        assignments = json.load(f)["assignments"]
    pipeline = config.get("pipeline_type", "transport")
    return config, assignments, pipeline


def prov_score(val: str) -> int:
    return 2 if val == "strong" else 1 if val == "weak" else 0


# ---------------------------------------------------------------------------
# Collect data from all runs
# ---------------------------------------------------------------------------

# Per-expert accumulations
expert_provisions: dict[str, dict[str, dict[str, list[float]]]] = {
    e: {"transport": {d: [] for d in PROVISION_DIMS},
        "embedding": {d: [] for d in PROVISION_DIMS}}
    for e in ALL_EXPERTS
}
expert_chapters: dict[str, dict[str, list[set[str]]]] = {
    e: {"transport": [], "embedding": []} for e in ALL_EXPERTS
}
expert_narrators: dict[str, dict[str, Counter]] = {
    e: {"transport": Counter(), "embedding": Counter()} for e in ALL_EXPERTS
}
expert_demand_satisfaction: dict[str, dict[str, list[float]]] = {
    e: {"transport": [], "embedding": []} for e in ALL_EXPERTS
}
expert_run_counts: dict[str, dict[str, int]] = {
    e: {"transport": 0, "embedding": 0} for e in ALL_EXPERTS
}

variants = sorted(d.name for d in RUNS_DIR.iterdir() if d.is_dir())
loaded = 0

for variant in variants:
    config, assignments, pipeline = load_run(variant)
    if not config or not assignments:
        continue
    loaded += 1

    # Build demand lookup from config
    expert_demands: dict[str, dict[str, int]] = {}
    for e in config["experts"]:
        expert_demands[e["name"]] = e.get("demands", {})

    # Group assignments by expert
    by_expert: dict[str, list[dict]] = defaultdict(list)
    for a in assignments:
        exp = a.get("expert", "")
        if exp and exp != "_episode_structure":
            by_expert[exp].append(a)

    for expert_name, expert_assigns in by_expert.items():
        if expert_name not in expert_provisions:
            continue

        expert_run_counts[expert_name][pipeline] += 1

        # A1: provisions
        for a in expert_assigns:
            provs = a.get("provisions", {})
            for d in PROVISION_DIMS:
                score = prov_score(provs.get(d, "none"))
                expert_provisions[expert_name][pipeline][d].append(score)

        # A2: chapters and narrators
        chapters = {a["chapter_id"] for a in expert_assigns}
        expert_chapters[expert_name][pipeline].append(chapters)
        for a in expert_assigns:
            narrator = a.get("narrator", "unknown")
            expert_narrators[expert_name][pipeline][narrator] += 1

        # C1: demand satisfaction
        demands = expert_demands.get(expert_name, {})
        if demands:
            total_demanded = sum(demands.values())
            satisfied = 0
            dim_counts: Counter = Counter()
            for a in expert_assigns:
                dim = a.get("dimension", "")
                if dim in demands:
                    dim_counts[dim] += 1
            for dim, need in demands.items():
                satisfied += min(dim_counts.get(dim, 0), need)
            rate = satisfied / total_demanded if total_demanded > 0 else 0
            expert_demand_satisfaction[expert_name][pipeline].append(rate)

print(f"Loaded {loaded} runs from {len(variants)} directories\n")

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

lines: list[str] = []


def out(s: str = "") -> None:
    print(s)
    lines.append(s)


out("=" * 70)
out("EXPERT-LEVEL COMPARISON (Phase 1: Passage-Level)")
out("=" * 70)

# Run counts
out("\n--- Run Counts per Expert ---\n")
out(f"  {'Expert':<22s} {'Transport':>10s} {'Embedding':>10s} {'Total':>8s}")
out(f"  {'-'*22} {'-'*10} {'-'*10} {'-'*8}")
for e in ALL_EXPERTS:
    t = expert_run_counts[e]["transport"]
    em = expert_run_counts[e]["embedding"]
    out(f"  {e:<22s} {t:>10d} {em:>10d} {t+em:>8d}")

# ---------------------------------------------------------------------------
# A1: Provision profiles
# ---------------------------------------------------------------------------
out("\n\n--- A1: Mean Provision Strength per Expert ---")
out("  (scale: 0=none, 1=weak, 2=strong)\n")

for pipeline in ["transport", "embedding"]:
    out(f"  [{pipeline.upper()}]")
    header = f"  {'Expert':<22s}" + "".join(f" {DIM_SHORT[d]:>8s}" for d in PROVISION_DIMS)
    out(header)
    out(f"  {'-'*22}" + "".join(f" {'-'*8}" for _ in PROVISION_DIMS))
    for e in ALL_EXPERTS:
        vals = []
        for d in PROVISION_DIMS:
            scores = expert_provisions[e][pipeline][d]
            vals.append(sum(scores) / len(scores) if scores else 0)
        row = f"  {e:<22s}" + "".join(f" {v:>8.2f}" for v in vals)
        out(row)
    out()

# ---------------------------------------------------------------------------
# A2: Chapter/narrator diversity
# ---------------------------------------------------------------------------
out("\n--- A2: Chapter & Narrator Diversity per Expert ---\n")

for pipeline in ["transport", "embedding"]:
    out(f"  [{pipeline.upper()}]")
    out(f"  {'Expert':<22s} {'Mean Ch':>8s} {'Min Ch':>8s} {'Max Ch':>8s} {'Esther%':>8s} {'Omni%':>8s}")
    out(f"  {'-'*22} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
    for e in ALL_EXPERTS:
        ch_sets = expert_chapters[e][pipeline]
        if not ch_sets:
            out(f"  {e:<22s} {'—':>8s} {'—':>8s} {'—':>8s} {'—':>8s} {'—':>8s}")
            continue
        ch_counts = [len(s) for s in ch_sets]
        narr = expert_narrators[e][pipeline]
        total_narr = sum(narr.values())
        esther_pct = narr.get("esther", 0) / total_narr * 100 if total_narr else 0
        omni_pct = narr.get("omniscient", 0) / total_narr * 100 if total_narr else 0
        out(f"  {e:<22s} {sum(ch_counts)/len(ch_counts):>8.1f} {min(ch_counts):>8d} {max(ch_counts):>8d} {esther_pct:>7.0f}% {omni_pct:>7.0f}%")
    out()

# ---------------------------------------------------------------------------
# C1: Demand satisfaction
# ---------------------------------------------------------------------------
out("\n--- C1: Demand Satisfaction Rate per Expert ---")
out("  (fraction of declared dimension demands filled)\n")

out(f"  {'Expert':<22s} {'T mean':>8s} {'T min':>8s} {'T max':>8s} {'E mean':>8s} {'E min':>8s} {'E max':>8s}")
out(f"  {'-'*22} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
for e in ALL_EXPERTS:
    parts = []
    for pipeline in ["transport", "embedding"]:
        rates = expert_demand_satisfaction[e][pipeline]
        if rates:
            parts.extend([
                f"{sum(rates)/len(rates):>8.0%}",
                f"{min(rates):>8.0%}",
                f"{max(rates):>8.0%}",
            ])
        else:
            parts.extend([f"{'—':>8s}"] * 3)
    out(f"  {e:<22s} {''.join(parts)}")

# ---------------------------------------------------------------------------
# Visualizations
# ---------------------------------------------------------------------------

# A1 heatmap: experts × dimensions, transport vs embedding side by side
fig, axes = plt.subplots(1, 2, figsize=(16, 5), sharey=True)
for idx, pipeline in enumerate(["transport", "embedding"]):
    ax = axes[idx]
    matrix = np.zeros((len(ALL_EXPERTS), len(PROVISION_DIMS)))
    for i, e in enumerate(ALL_EXPERTS):
        for j, d in enumerate(PROVISION_DIMS):
            scores = expert_provisions[e][pipeline][d]
            matrix[i, j] = sum(scores) / len(scores) if scores else 0
    im = ax.imshow(matrix, cmap="YlOrRd", vmin=0, vmax=2, aspect="auto")
    ax.set_xticks(range(len(PROVISION_DIMS)))
    ax.set_xticklabels([DIM_SHORT[d] for d in PROVISION_DIMS], rotation=45, ha="right", fontsize=9)
    ax.set_yticks(range(len(ALL_EXPERTS)))
    ax.set_yticklabels([e.split()[0] for e in ALL_EXPERTS], fontsize=9)
    for i in range(len(ALL_EXPERTS)):
        for j in range(len(PROVISION_DIMS)):
            ax.text(j, i, f"{matrix[i,j]:.2f}", ha="center", va="center",
                    fontsize=7, color="white" if matrix[i,j] > 1.2 else "black")
    ax.set_title(f"{pipeline.title()} Pipeline")

plt.colorbar(im, ax=axes, label="Mean Provision Strength", shrink=0.8)
fig.suptitle("A1: Expert Provision Profiles", fontsize=13)
plt.tight_layout()
plt.savefig(OUT_DIR / "a1_provision_heatmap.png", dpi=150, bbox_inches="tight")
out(f"\nHeatmap saved to {OUT_DIR / 'a1_provision_heatmap.png'}")

# C1 bar chart: demand satisfaction by expert and pipeline
fig, ax = plt.subplots(figsize=(10, 5))
x = np.arange(len(ALL_EXPERTS))
width = 0.35
t_means = []
e_means = []
for e in ALL_EXPERTS:
    t_rates = expert_demand_satisfaction[e]["transport"]
    e_rates = expert_demand_satisfaction[e]["embedding"]
    t_means.append(sum(t_rates) / len(t_rates) if t_rates else 0)
    e_means.append(sum(e_rates) / len(e_rates) if e_rates else 0)

ax.bar(x - width/2, t_means, width, label="Transport", color="#2196F3")
ax.bar(x + width/2, e_means, width, label="Embedding", color="#FF9800")
ax.set_xticks(x)
ax.set_xticklabels([e.split()[0] for e in ALL_EXPERTS], fontsize=9)
ax.set_ylabel("Demand Satisfaction Rate")
ax.set_ylim(0, 1.1)
ax.set_title("C1: Expert Demand Satisfaction Rate")
ax.legend()
ax.axhline(y=1.0, color="gray", linestyle="--", alpha=0.5)
plt.tight_layout()
plt.savefig(OUT_DIR / "c1_demand_satisfaction.png", dpi=150, bbox_inches="tight")
out(f"Bar chart saved to {OUT_DIR / 'c1_demand_satisfaction.png'}")

# Save report
with open(OUT_DIR / "phase1_report.txt", "w") as f:
    f.write("\n".join(lines))
out(f"\nReport saved to {OUT_DIR / 'phase1_report.txt'}")
