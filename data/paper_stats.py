#!/usr/bin/env python3
"""Extract comprehensive statistics from BleakHouse experiment data for paper revision."""

import json
import sys
from collections import defaultdict
from pathlib import Path

RUNS = Path("/Users/brewc/PycharmProjects/BleakHouse/data/runs")
NOVELS_DIR = Path("/Users/brewc/PycharmProjects/BleakHouse/data/novels")
BH_ENRICHED = Path("/Users/brewc/PycharmProjects/BleakHouse/data/passages_enriched.json")

# Prefix-keyed lookup derived from enrichment.axes.NOVELS.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from enrichment.axes import NOVELS, parse_run_dir_name  # noqa: E402

NOVEL_PREFIXES: dict[str, str] = {n.key: n.id for n in NOVELS}

# Legacy pre-migration pipeline prefixes, kept so we can still classify runs
# living under data/runs/_archive/. Active runs now always use canonical
# single-letter pipelines (trn/emb/nop/rag) matching axes.PIPELINES.
LEGACY_PIPELINE_PREFIXES: dict[str, str] = {
    "ext": "transport",
    "emb": "embedding",
    "nop": "no_passages",
    "arc": "transport",
    "hia": "transport",
    "rag": "plain_rag",
    "rand": "random",
    "trn": "transport",
}
# Canonical pipelines → paper-label display names.
PIPELINE_DISPLAY: dict[str, str] = {
    "trn": "transport",
    "emb": "embedding",
    "nop": "no_passages",
    "rag": "plain_rag",
}


def classify_run(run_id: str) -> tuple[str, str, str, bool]:
    """Return (novel, pipeline, panel_version, is_hostprep) for a run_id.

    Canonical names parse via axes.parse_run_dir_name; legacy pre-migration
    names (under data/runs/_archive/) fall back to the historical prefix
    matcher.
    """
    # Canonical path first.
    try:
        axes_t = parse_run_dir_name(run_id)
    except ValueError:
        pass
    else:
        novel_id = next((n.id for n in NOVELS if n.key == axes_t.novel), axes_t.novel)
        return (
            novel_id,
            PIPELINE_DISPLAY.get(axes_t.pipeline, axes_t.pipeline) or axes_t.pipeline,
            axes_t.panel,
            axes_t.hostprep,
        )

    # Legacy fallback for archived dirs.
    is_hostprep = run_id.endswith("_hostprep")
    base = run_id.removesuffix("_hostprep")

    for prefix, novel in sorted(NOVEL_PREFIXES.items(), key=lambda x: -len(x[0])):
        if base.startswith(prefix + "_"):
            rest = base[len(prefix) + 1:]
            parts = rest.split("_", 1)
            pipe_code = parts[0]
            version = parts[1] if len(parts) > 1 else ""
            pipeline = LEGACY_PIPELINE_PREFIXES.get(pipe_code, pipe_code)
            return novel, pipeline, version, is_hostprep

    for prefix, pipeline in sorted(LEGACY_PIPELINE_PREFIXES.items(), key=lambda x: -len(x[0])):
        if base.startswith(prefix + "_"):
            version = base[len(prefix) + 1:]
            return "bleak_house", pipeline, version, is_hostprep

    return "unknown", "unknown", base, is_hostprep


def load_json(path: Path):
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def hr(title: str):
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}")


def compute_manifest_stats(manifest: dict) -> dict:
    """Extract word count, question count, reactive markers, segments, expert airtime."""
    segments = manifest.get("segments", [])
    total_words = 0
    question_count = 0
    reactive_count = 0
    expert_words = defaultdict(int)
    host_words = 0
    sentence_types = defaultdict(int)

    for seg in segments:
        for turn in seg.get("turns", []):
            speaker = turn.get("speaker", "")
            role = turn.get("role", "")
            turn_words = 0
            for u in turn.get("utterances", []):
                text = u.get("text", "")
                wc = len(text.split())
                turn_words += wc
                total_words += wc
                st = u.get("sentence_type", "")
                sentence_types[st] += 1
                if "?" in text or st == "question":
                    question_count += 1
                if st in ("follow_up", "challenge", "redirect", "probe"):
                    reactive_count += 1
            if role == "host" or speaker == "Host":
                host_words += turn_words
            else:
                expert_words[speaker] += turn_words

    total_duration_ms = manifest.get("total_duration_ms", 0)

    return {
        "segments": len(segments),
        "total_words": total_words,
        "question_count": question_count,
        "reactive_count": reactive_count,
        "host_words": host_words,
        "expert_words": dict(expert_words),
        "total_duration_ms": total_duration_ms,
        "sentence_types": dict(sentence_types),
    }


def main():
    # =========================================================================
    # Collect all run data
    # =========================================================================
    runs = {}
    for run_dir in sorted(RUNS.iterdir()):
        if not run_dir.is_dir():
            continue
        run_id = run_dir.name
        novel, pipeline, version, is_hostprep = classify_run(run_id)
        runs[run_id] = {
            "novel": novel,
            "pipeline": pipeline,
            "version": version,
            "is_hostprep": is_hostprep,
            "dir": run_dir,
        }

    print(f"Total runs found: {len(runs)}")
    novel_counts = defaultdict(int)
    pipeline_counts = defaultdict(int)
    for r in runs.values():
        novel_counts[r["novel"]] += 1
        pipeline_counts[r["pipeline"]] += 1
    print(f"Novels: {len(novel_counts)}")
    for n in sorted(novel_counts):
        print(f"  {n}: {novel_counts[n]} runs")
    print(f"Pipelines: {dict(pipeline_counts)}")

    # =========================================================================
    # 1. Quote verification by pipeline and novel
    # =========================================================================
    hr("1. QUOTE VERIFICATION BY PIPELINE AND NOVEL")

    qv_data = {}  # (novel, pipeline) -> list of rates
    for run_id, info in runs.items():
        qv = load_json(info["dir"] / "quote_verification.json")
        if qv and "rate" in qv:
            key = (info["novel"], info["pipeline"])
            if key not in qv_data:
                qv_data[key] = []
            qv_data[key].append(qv["rate"])

    # Print table: novels as rows, pipelines as columns
    pipelines_for_qv = sorted({p for _, p in qv_data})
    novels_for_qv = sorted({n for n, _ in qv_data})

    print(f"\n{'Novel':<25}", end="")
    for p in pipelines_for_qv:
        print(f"  {p:>12}", end="")
    print()
    print("-" * (25 + 14 * len(pipelines_for_qv)))

    for novel in novels_for_qv:
        print(f"{novel:<25}", end="")
        for pipeline in pipelines_for_qv:
            rates = qv_data.get((novel, pipeline), [])
            if rates:
                avg = sum(rates) / len(rates)
                print(f"  {avg:>8.1f}% ({len(rates):>1})", end="")
            else:
                print(f"  {'---':>12}", end="")
        print()

    # Summary by pipeline
    print(f"\n{'Pipeline summary':}")
    for p in pipelines_for_qv:
        all_rates = []
        for (n, pp), rates in qv_data.items():
            if pp == p:
                all_rates.extend(rates)
        if all_rates:
            avg = sum(all_rates) / len(all_rates)
            min_r = min(all_rates)
            max_r = max(all_rates)
            perfect = sum(1 for r in all_rates if r == 100.0)
            print(f"  {p:<20}: mean={avg:.1f}%, min={min_r:.1f}%, max={max_r:.1f}%, "
                  f"n={len(all_rates)}, perfect={perfect}/{len(all_rates)}")

    # =========================================================================
    # 2. Host prep effect on conversational quality
    # =========================================================================
    hr("2. HOST PREP EFFECT ON CONVERSATIONAL QUALITY")

    hostprep_pairs = defaultdict(dict)  # base_key -> {True: stats, False: stats}
    for run_id, info in runs.items():
        manifest = load_json(info["dir"] / "manifest.json")
        if not manifest:
            continue
        stats = compute_manifest_stats(manifest)
        base_key = (info["novel"], info["pipeline"], info["version"])
        hostprep_pairs[base_key][info["is_hostprep"]] = stats

    # Aggregate comparisons
    hp_q_per_seg = {"hostprep": [], "no_hostprep": []}
    hp_reactive = {"hostprep": [], "no_hostprep": []}
    hp_words = {"hostprep": [], "no_hostprep": []}

    for base_key, pair in hostprep_pairs.items():
        if True in pair and False in pair:
            for is_hp, label in [(True, "hostprep"), (False, "no_hostprep")]:
                s = pair[is_hp]
                if s["segments"] > 0:
                    hp_q_per_seg[label].append(s["question_count"] / s["segments"])
                    hp_reactive[label].append(s["reactive_count"])
                    hp_words[label].append(s["total_words"])

    print("\nPaired comparisons (runs that have both hostprep and non-hostprep):")
    print(f"  Pairs found: {len([k for k, v in hostprep_pairs.items() if True in v and False in v])}")
    for metric, data in [("Q/segment", hp_q_per_seg), ("Reactive markers", hp_reactive), ("Total words", hp_words)]:
        for label in ["no_hostprep", "hostprep"]:
            vals = data[label]
            if vals:
                avg = sum(vals) / len(vals)
                print(f"  {metric:<20} {label:<15}: mean={avg:.2f}, n={len(vals)}")

    # Also show sentence_type breakdown for hostprep vs not
    hp_stypes = {"hostprep": defaultdict(int), "no_hostprep": defaultdict(int)}
    hp_stype_n = {"hostprep": 0, "no_hostprep": 0}
    for base_key, pair in hostprep_pairs.items():
        if True in pair and False in pair:
            for is_hp, label in [(True, "hostprep"), (False, "no_hostprep")]:
                s = pair[is_hp]
                hp_stype_n[label] += 1
                for st, count in s["sentence_types"].items():
                    hp_stypes[label][st] += count

    print("\n  Sentence type distribution (aggregated):")
    all_stypes = sorted(set(hp_stypes["hostprep"]) | set(hp_stypes["no_hostprep"]))
    print(f"    {'type':<20} {'no_hostprep':>12} {'hostprep':>12}")
    for st in all_stypes:
        nh = hp_stypes["no_hostprep"].get(st, 0)
        hp = hp_stypes["hostprep"].get(st, 0)
        print(f"    {st:<20} {nh:>12} {hp:>12}")

    # =========================================================================
    # 3. Word counts and episode lengths by pipeline
    # =========================================================================
    hr("3. WORD COUNTS AND EPISODE LENGTHS BY PIPELINE")

    pipeline_words = defaultdict(list)
    pipeline_duration = defaultdict(list)
    pipeline_segs = defaultdict(list)

    for run_id, info in runs.items():
        if info["is_hostprep"]:
            continue  # skip hostprep variants for clean comparison
        manifest = load_json(info["dir"] / "manifest.json")
        if not manifest:
            continue
        stats = compute_manifest_stats(manifest)
        pipeline_words[info["pipeline"]].append(stats["total_words"])
        pipeline_duration[info["pipeline"]].append(stats["total_duration_ms"])
        pipeline_segs[info["pipeline"]].append(stats["segments"])

    print(f"\n{'Pipeline':<20} {'n':>4} {'mean_words':>12} {'min':>8} {'max':>8} {'mean_segs':>10} {'mean_dur_min':>13}")
    print("-" * 85)
    for p in sorted(pipeline_words):
        words = pipeline_words[p]
        dur = pipeline_duration[p]
        segs = pipeline_segs[p]
        avg_w = sum(words) / len(words) if words else 0
        avg_d = (sum(dur) / len(dur) / 60000) if dur else 0
        avg_s = sum(segs) / len(segs) if segs else 0
        print(f"{p:<20} {len(words):>4} {avg_w:>12.0f} {min(words):>8} {max(words):>8} {avg_s:>10.1f} {avg_d:>13.1f}")

    # Also break down by novel for the 3 main pipelines
    print("\nWord counts by novel x pipeline (non-hostprep, all panels):")
    main_pipes = ["transport", "embedding", "no_passages"]
    all_novels_wc = sorted({info["novel"] for info in runs.values()})

    print(f"{'Novel':<25}", end="")
    for p in main_pipes:
        print(f"  {p:>15}", end="")
    print()
    print("-" * (25 + 17 * len(main_pipes)))

    for novel in all_novels_wc:
        print(f"{novel:<25}", end="")
        for pipeline in main_pipes:
            wcs = []
            for run_id, info in runs.items():
                if info["novel"] == novel and info["pipeline"] == pipeline and not info["is_hostprep"]:
                    manifest = load_json(info["dir"] / "manifest.json")
                    if manifest:
                        stats = compute_manifest_stats(manifest)
                        wcs.append(stats["total_words"])
            if wcs:
                avg = sum(wcs) / len(wcs)
                print(f"  {avg:>10.0f} ({len(wcs):>2})", end="")
            else:
                print(f"  {'---':>15}", end="")
        print()

    # =========================================================================
    # 4. Expert airtime across novels
    # =========================================================================
    hr("4. EXPERT AIRTIME ACROSS NOVELS (v01_baseline transport runs)")

    print(f"\n{'Novel':<25} {'Expert':<25} {'Words':>8} {'% of total':>12}")
    print("-" * 70)

    airtime_by_novel = {}
    for run_id, info in runs.items():
        if info["pipeline"] != "transport" or info["is_hostprep"]:
            continue
        if info["version"] != "v01_baseline":
            continue
        manifest = load_json(info["dir"] / "manifest.json")
        if not manifest:
            continue
        stats = compute_manifest_stats(manifest)
        novel = info["novel"]
        total_expert_words = sum(stats["expert_words"].values())
        expert_pcts = {}
        for expert, wc in sorted(stats["expert_words"].items()):
            pct = (wc / total_expert_words * 100) if total_expert_words > 0 else 0
            expert_pcts[expert] = pct
            print(f"{novel:<25} {expert:<25} {wc:>8} {pct:>11.1f}%")
        airtime_by_novel[novel] = expert_pcts

    # Summary: std dev of expert percentages across novels
    print("\nAirtime stability across novels:")
    all_experts = set()
    for pcts in airtime_by_novel.values():
        all_experts.update(pcts.keys())
    for expert in sorted(all_experts):
        vals = [pcts.get(expert, 0) for pcts in airtime_by_novel.values() if expert in pcts]
        if len(vals) > 1:
            mean = sum(vals) / len(vals)
            variance = sum((v - mean) ** 2 for v in vals) / len(vals)
            std = variance ** 0.5
            print(f"  {expert:<25}: mean={mean:.1f}%, std={std:.1f}%, range=[{min(vals):.1f}%, {max(vals):.1f}%], n={len(vals)}")

    # =========================================================================
    # 5. Passage overlap between transport and embedding
    # =========================================================================
    hr("5. PASSAGE OVERLAP: TRANSPORT vs EMBEDDING (Jaccard similarity)")

    # For matched novel x panel pairs, compare passage_ids
    passage_sets = {}  # (novel, pipeline, version) -> set of passage_ids
    for run_id, info in runs.items():
        if info["pipeline"] not in ("transport", "embedding"):
            continue
        if info["is_hostprep"]:
            continue
        assignments = load_json(info["dir"] / "phase1_assignments.json")
        if assignments and "assignments" in assignments:
            pids = {a["passage_id"] for a in assignments["assignments"]}
            passage_sets[(info["novel"], info["pipeline"], info["version"])] = pids

    # Find matched pairs
    jaccard_results = []
    print(f"\n{'Novel':<25} {'Version':<30} {'Trn#':>5} {'Emb#':>5} {'Overlap':>8} {'Jaccard':>8}")
    print("-" * 85)

    matched = set()
    for (novel, pipeline, version), pids in passage_sets.items():
        if pipeline == "transport":
            emb_key = (novel, "embedding", version)
            if emb_key in passage_sets:
                trn_pids = pids
                emb_pids = passage_sets[emb_key]
                overlap = len(trn_pids & emb_pids)
                union = len(trn_pids | emb_pids)
                jaccard = overlap / union if union > 0 else 0
                jaccard_results.append(jaccard)
                match_key = (novel, version)
                if match_key not in matched:
                    matched.add(match_key)
                    print(f"{novel:<25} {version:<30} {len(trn_pids):>5} {len(emb_pids):>5} {overlap:>8} {jaccard:>8.3f}")

    if jaccard_results:
        avg_j = sum(jaccard_results) / len(jaccard_results)
        min_j = min(jaccard_results)
        max_j = max(jaccard_results)
        print(f"\nSummary: mean Jaccard={avg_j:.3f}, min={min_j:.3f}, max={max_j:.3f}, n={len(jaccard_results)}")

    # =========================================================================
    # 6. Enrichment dimension variation across novels
    # =========================================================================
    hr("6. ENRICHMENT DIMENSION VARIATION ACROSS NOVELS")

    PROV_DIMS = [
        "prov_character_development", "prov_plot_advancement", "prov_thematic_depth",
        "prov_social_critique", "prov_humor_entertainment", "prov_atmosphere_setting",
        "prov_narrative_technique",
    ]
    STRENGTH_MAP = {"strong": 2, "weak": 1, "none": 0}

    novel_dim_scores = {}  # novel -> {dim -> mean_score}

    # Bleak House
    bh_data = load_json(BH_ENRICHED)
    if bh_data:
        scores = defaultdict(list)
        for p in bh_data:
            e = p.get("enrichment", {})
            for dim in PROV_DIMS:
                val = e.get(dim)
                if val in STRENGTH_MAP:
                    scores[dim].append(STRENGTH_MAP[val])
        novel_dim_scores["bleak_house"] = {d: sum(v)/len(v) if v else 0 for d, v in scores.items()}

    # Other novels
    for novel_key in sorted(NOVEL_PREFIXES.values()):
        enriched_path = NOVELS_DIR / novel_key / "passages_enriched.json"
        data = load_json(enriched_path)
        if not data:
            continue
        scores = defaultdict(list)
        for p in data:
            e = p.get("enrichment", {})
            for dim in PROV_DIMS:
                val = e.get(dim)
                if val in STRENGTH_MAP:
                    scores[dim].append(STRENGTH_MAP[val])
        novel_dim_scores[novel_key] = {d: sum(v)/len(v) if v else 0 for d, v in scores.items()}

    # Print table
    short_dims = [d.replace("prov_", "") for d in PROV_DIMS]
    print("\nMean provision scores (0=none, 1=weak, 2=strong):")
    print(f"{'Novel':<25}", end="")
    for sd in short_dims:
        print(f"  {sd[:10]:>10}", end="")
    print(f"  {'n_passages':>10}")
    print("-" * (25 + 12 * (len(PROV_DIMS) + 1)))

    for novel in sorted(novel_dim_scores):
        dims = novel_dim_scores[novel]
        # count passages
        if novel == "bleak_house":
            n_pass = len(bh_data) if bh_data else 0
        else:
            ep = NOVELS_DIR / novel / "passages_enriched.json"
            d = load_json(ep)
            n_pass = len(d) if d else 0
        print(f"{novel:<25}", end="")
        for dim in PROV_DIMS:
            print(f"  {dims.get(dim, 0):>10.3f}", end="")
        print(f"  {n_pass:>10}")

    # Dimension-level summary
    print("\nDimension summary across novels:")
    for dim, short in zip(PROV_DIMS, short_dims):
        vals = [novel_dim_scores[n].get(dim, 0) for n in novel_dim_scores]
        if vals:
            mean = sum(vals) / len(vals)
            variance = sum((v - mean) ** 2 for v in vals) / len(vals)
            std = variance ** 0.5
            print(f"  {short:<25}: mean={mean:.3f}, std={std:.3f}, range=[{min(vals):.3f}, {max(vals):.3f}]")

    # =========================================================================
    # Summary counts
    # =========================================================================
    hr("SUMMARY")
    n_with_qv = sum(1 for r in runs.values() if (r["dir"] / "quote_verification.json").exists())
    n_with_manifest = sum(1 for r in runs.values() if (r["dir"] / "manifest.json").exists())
    n_hostprep = sum(1 for r in runs.values() if r["is_hostprep"])
    print(f"Total run directories: {len(runs)}")
    print(f"Runs with quote_verification.json: {n_with_qv}")
    print(f"Runs with manifest.json: {n_with_manifest}")
    print(f"Hostprep runs: {n_hostprep}")
    print(f"Novels with enrichment data: {len(novel_dim_scores)}")


if __name__ == "__main__":
    main()
