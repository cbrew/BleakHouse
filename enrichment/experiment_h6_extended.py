"""Experiment H6 (Extended): Expert prominence adapts to textual affordance.

H6 claims that expert airtime (word count fraction) varies across novels
in ways that correlate with each novel's provision dimension supply.

This extended analysis covers all novels with enrichment data (up to 15),
not just the original 5.  For novels without pipeline runs, we still
compute the provision profile (useful for H13).

Expert demand profiles (primary dimension each expert cares about):
  Panel A: Hartley -> narrative_technique,
           Blackstone -> social_critique,
           Woodcourt -> humor_entertainment
  Panel B: Trevelyan -> humor_entertainment,
           Leigh -> character_development,
           Rosen -> social_critique

Usage:
    uv run python -m enrichment.experiment_h6_extended [--runs-dir data/runs]
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

RUNS_DIR = Path("data/runs")
REPORTS_DIR = Path("reports")

# ---------------------------------------------------------------------------
# Novel metadata
# ---------------------------------------------------------------------------

NOVEL_LABELS: dict[str, str] = {
    "bleak_house": "Bleak House",
    "mill_on_the_floss": "Mill on the Floss",
    "north_and_south": "North and South",
    "our_mutual_friend": "Our Mutual Friend",
    "passage_to_india": "A Passage to India",
    "cranford": "Cranford",
    "daniel_deronda": "Daniel Deronda",
    "david_copperfield": "David Copperfield",
    "hard_times": "Hard Times",
    "hester": "Hester",
    "middlemarch": "Middlemarch",
    "miss_marjoribanks": "Miss Marjoribanks",
    "new_grub_street": "New Grub Street",
    "no_name": "No Name",
    "odd_women": "The Odd Women",
}

PROVISION_DIMS = [
    "prov_character_development",
    "prov_plot_advancement",
    "prov_thematic_depth",
    "prov_social_critique",
    "prov_humor_entertainment",
    "prov_atmosphere_setting",
    "prov_narrative_technique",
]

DIM_SHORT = {
    "prov_character_development": "char_dev",
    "prov_plot_advancement": "plot_adv",
    "prov_thematic_depth": "thematic",
    "prov_social_critique": "soc_crit",
    "prov_humor_entertainment": "humor",
    "prov_atmosphere_setting": "atmos",
    "prov_narrative_technique": "narr_tech",
}

# Expert -> primary dimension (demand profile)
EXPERT_DEMAND_A: dict[str, str] = {
    "Eleanor Hartley": "prov_narrative_technique",
    "James Blackstone": "prov_social_critique",
    "Caroline Woodcourt": "prov_humor_entertainment",
}

EXPERT_DEMAND_B: dict[str, str] = {
    "Oliver Trevelyan": "prov_humor_entertainment",
    "Edmund Leigh": "prov_character_development",
    "Daniel Rosen": "prov_social_critique",
}


# ---------------------------------------------------------------------------
# Run classification (mirrors other experiment scripts)
# ---------------------------------------------------------------------------

def classify_run(name: str) -> tuple[str, str, str]:
    """Return (novel, condition, panel_id) from run directory name."""
    for prefix, novel in [
        ("motf_trn_", "mill_on_the_floss"), ("motf_ext_", "mill_on_the_floss"),
        ("motf_emb_", "mill_on_the_floss"), ("motf_nop_", "mill_on_the_floss"),
        ("motf_hia_", "mill_on_the_floss"),
        ("nas_trn_", "north_and_south"), ("nas_ext_", "north_and_south"),
        ("nas_emb_", "north_and_south"), ("nas_nop_", "north_and_south"),
        ("nas_hia_", "north_and_south"),
        ("omf_trn_", "our_mutual_friend"), ("omf_ext_", "our_mutual_friend"),
        ("omf_emb_", "our_mutual_friend"), ("omf_nop_", "our_mutual_friend"),
        ("omf_hia_", "our_mutual_friend"),
        ("pti_trn_", "passage_to_india"), ("pti_ext_", "passage_to_india"),
        ("pti_emb_", "passage_to_india"), ("pti_nop_", "passage_to_india"),
        ("pti_hia_", "passage_to_india"),
        ("cran_trn_", "cranford"), ("cran_ext_", "cranford"),
        ("dd_trn_", "daniel_deronda"), ("dd_ext_", "daniel_deronda"),
        ("dc_trn_", "david_copperfield"), ("dc_ext_", "david_copperfield"),
        ("ht_trn_", "hard_times"), ("ht_ext_", "hard_times"),
        ("hest_trn_", "hester"), ("hest_ext_", "hester"),
        ("mid_trn_", "middlemarch"), ("mid_ext_", "middlemarch"),
        ("mmar_trn_", "miss_marjoribanks"), ("mmar_ext_", "miss_marjoribanks"),
        ("ngs_trn_", "new_grub_street"), ("ngs_ext_", "new_grub_street"),
        ("noname_trn_", "no_name"), ("noname_ext_", "no_name"),
        ("oddw_trn_", "odd_women"), ("oddw_ext_", "odd_women"),
    ]:
        if name.startswith(prefix):
            cond = prefix.split("_")[1]
            rest = name[len(prefix):]
            return novel, cond, rest

    for prefix, cond in [
        ("ext_", "ext"), ("trn_", "trn"), ("emb_", "emb"),
        ("nop_", "nop"), ("arc_", "arc"), ("hia_", "hia"),
        ("rag_", "rag"), ("rand_", "rand"),
    ]:
        if name.startswith(prefix):
            return "bleak_house", cond, name[len(prefix):]

    return "unknown", "unknown", name


def classify_panel(panel_id: str) -> str:
    """Classify into Panel A or Panel B."""
    if panel_id.startswith("v01"):
        return "A"
    elif panel_id.startswith("v19"):
        return "B"
    return "other"


# ---------------------------------------------------------------------------
# Episode word counting
# ---------------------------------------------------------------------------

HOST_NAMES = {"Host", "host"}


def count_expert_words(episode: dict) -> dict[str, int]:
    """Count words per speaker (excluding host) from phase3_episode.json."""
    counts: dict[str, int] = defaultdict(int)
    for segment in episode.get("segments", []):
        for turn in segment.get("turns", []):
            speaker = turn.get("speaker", "")
            if speaker in HOST_NAMES:
                continue
            wc = 0
            for utt in turn.get("utterances", []):
                text = utt.get("text", "")
                wc += len(text.split())
            counts[speaker] += wc
    return dict(counts)


# ---------------------------------------------------------------------------
# Provision profiles
# ---------------------------------------------------------------------------

def load_provision_profile(novel: str) -> dict[str, float] | None:
    """Load enriched passages and compute % of passages rated 'strong' per dim."""
    if novel == "bleak_house":
        path = Path("data/passages_enriched.json")
    else:
        path = Path("data/novels") / novel / "passages_enriched.json"

    if not path.exists():
        return None

    try:
        passages = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    n_total = len(passages)
    if n_total == 0:
        return None

    counts: dict[str, int] = {d: 0 for d in PROVISION_DIMS}
    for p in passages:
        enrichment = p.get("enrichment", p)
        for d in PROVISION_DIMS:
            val = enrichment.get(d, "none")
            if val == "strong":
                counts[d] += 1

    return {d: 100.0 * counts[d] / n_total for d in PROVISION_DIMS}


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def find_transport_runs(
    runs_dir: Path,
) -> dict[str, dict[str, Path]]:
    """Find transport runs with phase3_episode.json for v01 and v19.

    Returns: {novel: {"A": path, "B": path}}
    """
    results: dict[str, dict[str, Path]] = {}
    for rd in sorted(runs_dir.iterdir()):
        if not rd.is_dir():
            continue
        ep_path = rd / "phase3_episode.json"
        if not ep_path.exists():
            continue

        novel, cond, panel_id = classify_run(rd.name)
        if cond not in ("ext", "trn"):
            continue
        panel = classify_panel(panel_id)
        if panel not in ("A", "B"):
            continue

        # Only accept clean baseline / all_swapped panel ids
        if panel_id not in ("v01_baseline", "v19_all_swapped"):
            continue

        if novel not in results:
            results[novel] = {}
        # Prefer ext over trn if both exist
        if panel in results[novel]:
            existing = results[novel][panel]
            existing_cond = classify_run(existing.parent.name)[1]
            if existing_cond == "ext":
                continue  # keep ext
        results[novel][panel] = rd

    return results


def compute_airtime_table(
    runs: dict[str, dict[str, Path]],
) -> dict[str, dict[str, dict[str, float]]]:
    """Compute per-expert word fraction for each novel/panel.

    Returns: {novel: {"A": {expert: pct, ...}, "B": {expert: pct, ...}}}
    """
    results: dict[str, dict[str, dict[str, float]]] = {}
    for novel, panels in runs.items():
        results[novel] = {}
        for panel_label, run_dir in panels.items():
            ep_path = run_dir / "phase3_episode.json"
            try:
                episode = json.loads(ep_path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            word_counts = count_expert_words(episode)
            total = sum(word_counts.values())
            if total == 0:
                continue
            fractions = {
                speaker: 100.0 * wc / total
                for speaker, wc in word_counts.items()
            }
            results[novel][panel_label] = fractions
    return results


def pearson_r(xs: list[float], ys: list[float]) -> float | None:
    """Compute Pearson correlation coefficient. Returns None if n < 3."""
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    if sx == 0 or sy == 0:
        return None
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    return cov / (sx * sy)


def run(runs_dir: Path = RUNS_DIR) -> str:
    """Execute the full H6 extended analysis and return the report text."""
    lines: list[str] = []

    def out(s: str = "") -> None:
        lines.append(s)

    out("=" * 78)
    out("EXPERIMENT H6 (EXTENDED): Expert Prominence Adapts to Textual Affordance")
    out("=" * 78)
    out()
    out("Hypothesis: Expert airtime (word count fraction) varies across novels")
    out("in ways that correlate with each novel's provision dimension supply.")
    out()

    # 1. Find all transport runs
    transport_runs = find_transport_runs(runs_dir)

    out("--- Transport Runs Found ---")
    out()
    for novel in sorted(transport_runs.keys()):
        panels = transport_runs[novel]
        panel_strs = []
        for p in ("A", "B"):
            if p in panels:
                panel_strs.append(f"Panel {p}: {panels[p].name}")
        out(f"  {NOVEL_LABELS.get(novel, novel)}: {', '.join(panel_strs)}")
    out()

    # 2. Compute airtime
    airtime = compute_airtime_table(transport_runs)

    out("=" * 78)
    out("PANEL A (Hartley, Blackstone, Woodcourt) -- Expert Airtime (% of expert words)")
    out("=" * 78)
    out()

    panel_a_experts = ["Eleanor Hartley", "James Blackstone", "Caroline Woodcourt"]
    panel_b_experts = ["Oliver Trevelyan", "Edmund Leigh", "Daniel Rosen"]

    def print_airtime_table(
        panel: str, experts: list[str],
    ) -> dict[str, dict[str, float]]:
        """Print and return airtime data for a panel."""
        header = f"{'Novel':<25s}" + "".join(f"{e.split()[1]:>15s}" for e in experts) + f"{'Total wc':>12s}"
        out(header)
        out("-" * len(header))

        data: dict[str, dict[str, float]] = {}
        for novel in sorted(airtime.keys()):
            if panel not in airtime[novel]:
                continue
            fracs = airtime[novel][panel]
            row_vals: dict[str, float] = {}
            total_wc = sum(
                wc
                for sp, wc in count_expert_words(
                    json.loads(
                        (transport_runs[novel][panel] / "phase3_episode.json").read_text()
                    )
                ).items()
            )
            row = f"{NOVEL_LABELS.get(novel, novel):<25s}"
            for expert in experts:
                pct = fracs.get(expert, 0.0)
                row_vals[expert] = pct
                row += f"{pct:>14.1f}%"
            row += f"{total_wc:>12d}"
            out(row)
            data[novel] = row_vals
        out()
        return data

    data_a = print_airtime_table("A", panel_a_experts)

    out("=" * 78)
    out("PANEL B (Trevelyan, Leigh, Rosen) -- Expert Airtime (% of expert words)")
    out("=" * 78)
    out()

    data_b = print_airtime_table("B", panel_b_experts)

    # 3. Provision profiles for ALL novels with enrichment data
    out("=" * 78)
    out("PROVISION PROFILES: % passages rated 'strong' per dimension")
    out("(Covers all enriched novels, including those without pipeline runs)")
    out("=" * 78)
    out()

    all_novels = ["bleak_house"] + sorted(
        [d.name for d in Path("data/novels").iterdir() if d.is_dir()]
    )

    profiles: dict[str, dict[str, float]] = {}
    for novel in all_novels:
        prof = load_provision_profile(novel)
        if prof is not None:
            profiles[novel] = prof

    # Print table
    dim_headers = [DIM_SHORT[d] for d in PROVISION_DIMS]
    header = f"{'Novel':<25s}" + "".join(f"{h:>10s}" for h in dim_headers) + f"{'N_pass':>10s}"
    out(header)
    out("-" * len(header))

    for novel in sorted(profiles.keys()):
        prof = profiles[novel]
        # Get passage count
        if novel == "bleak_house":
            ppath = Path("data/passages_enriched.json")
        else:
            ppath = Path("data/novels") / novel / "passages_enriched.json"
        try:
            n_passages = len(json.loads(ppath.read_text()))
        except (json.JSONDecodeError, OSError):
            n_passages = 0

        row = f"{NOVEL_LABELS.get(novel, novel):<25s}"
        for d in PROVISION_DIMS:
            row += f"{prof[d]:>9.1f}%"
        row += f"{n_passages:>10d}"
        out(row)

    out()
    out(f"Total novels with provision data: {len(profiles)}")
    out()

    # 4. Correlation analysis: expert primary dim supply vs airtime
    out("=" * 78)
    out("CORRELATION: Expert Primary Dimension Supply vs Airtime")
    out("=" * 78)
    out()

    def compute_correlations(
        panel: str,
        expert_demand: dict[str, str],
        airtime_data: dict[str, dict[str, float]],
    ) -> None:
        out(f"Panel {panel}:")
        out()

        for expert, dim in expert_demand.items():
            novels_with_both: list[str] = []
            dim_supply: list[float] = []
            expert_airtime: list[float] = []

            for novel in sorted(airtime_data.keys()):
                if novel not in profiles:
                    continue
                pct = airtime_data[novel].get(expert, 0.0)
                supply = profiles[novel][dim]
                novels_with_both.append(novel)
                dim_supply.append(supply)
                expert_airtime.append(pct)

            out(f"  {expert} (primary dim: {DIM_SHORT[dim]}):")
            if len(novels_with_both) < 3:
                out(f"    Insufficient data (n={len(novels_with_both)}, need >= 3)")
                out()
                continue

            # Show per-novel data
            out(f"    {'Novel':<25s} {'Supply %':>10s} {'Airtime %':>10s}")
            for i, novel in enumerate(novels_with_both):
                out(
                    f"    {NOVEL_LABELS.get(novel, novel):<25s}"
                    f" {dim_supply[i]:>9.1f}%"
                    f" {expert_airtime[i]:>9.1f}%"
                )

            r = pearson_r(dim_supply, expert_airtime)
            if r is not None:
                out(f"    Pearson r = {r:+.3f}  (n={len(novels_with_both)})")
                direction = "positive" if r > 0 else "negative"
                strength = (
                    "strong" if abs(r) >= 0.7
                    else "moderate" if abs(r) >= 0.4
                    else "weak"
                )
                out(f"    Interpretation: {strength} {direction} correlation")
            else:
                out("    Pearson r: could not compute")
            out()

    compute_correlations("A", EXPERT_DEMAND_A, data_a)
    compute_correlations("B", EXPERT_DEMAND_B, data_b)

    # 5. Cross-panel comparison (same dimension, different experts)
    out("=" * 78)
    out("CROSS-PANEL: Same Dimension, Different Expert")
    out("=" * 78)
    out()

    # social_critique: Blackstone (A) vs Rosen (B)
    out("Social critique dimension: Blackstone (Panel A) vs Rosen (Panel B)")
    novels_both = sorted(
        set(data_a.keys()) & set(data_b.keys()) & set(profiles.keys())
    )
    if novels_both:
        out(f"  {'Novel':<25s} {'Supply %':>10s} {'Blackstone':>12s} {'Rosen':>12s}")
        for novel in novels_both:
            supply = profiles[novel]["prov_social_critique"]
            b_air = data_a.get(novel, {}).get("James Blackstone", 0.0)
            r_air = data_b.get(novel, {}).get("Daniel Rosen", 0.0)
            out(
                f"  {NOVEL_LABELS.get(novel, novel):<25s}"
                f" {supply:>9.1f}%"
                f" {b_air:>11.1f}%"
                f" {r_air:>11.1f}%"
            )
        out()

    # humor_entertainment: Woodcourt (A) vs Trevelyan (B)
    out("Humor/entertainment dimension: Woodcourt (Panel A) vs Trevelyan (Panel B)")
    if novels_both:
        out(f"  {'Novel':<25s} {'Supply %':>10s} {'Woodcourt':>12s} {'Trevelyan':>12s}")
        for novel in novels_both:
            supply = profiles[novel]["prov_humor_entertainment"]
            w_air = data_a.get(novel, {}).get("Caroline Woodcourt", 0.0)
            t_air = data_b.get(novel, {}).get("Oliver Trevelyan", 0.0)
            out(
                f"  {NOVEL_LABELS.get(novel, novel):<25s}"
                f" {supply:>9.1f}%"
                f" {w_air:>11.1f}%"
                f" {t_air:>11.1f}%"
            )
        out()

    # 6. Summary
    out("=" * 78)
    out("SUMMARY")
    out("=" * 78)
    out()
    out(f"Novels with enrichment data:  {len(profiles)}")
    out(f"Novels with Panel A runs:     {sum(1 for v in airtime.values() if 'A' in v)}")
    out(f"Novels with Panel B runs:     {sum(1 for v in airtime.values() if 'B' in v)}")
    out(f"Novels with both panels:      {len(novels_both)}")
    out()

    novels_only_enriched = sorted(set(profiles.keys()) - set(airtime.keys()))
    if novels_only_enriched:
        out("Novels with enrichment but NO transport runs (pipeline needed):")
        for n in novels_only_enriched:
            out(f"  - {NOVEL_LABELS.get(n, n)}")
        out()

    out("Note: For a fully powered H6 test, transport pipeline runs are")
    out("needed for all enriched novels. Currently only a subset have runs.")
    out()

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="H6 Extended: Expert prominence analysis")
    parser.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    report = run(runs_dir=args.runs_dir)

    # Save report
    REPORTS_DIR.mkdir(exist_ok=True)
    git_hash = "unknown"
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        git_hash = result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_name = f"experiment_h6_extended_{timestamp}_{git_hash}.txt"
    report_path = REPORTS_DIR / report_name
    report_path.write_text(report)

    print(report)
    print()
    print(f"Report saved to: {report_path}")


if __name__ == "__main__":
    main()
