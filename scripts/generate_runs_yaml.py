"""Generate runs.yaml — the list of canonical runs DVC's dvc.yaml iterates over.

Scans data/runs/* (skipping _archive/, _inventory etc.), reads each
config.json, emits a YAML list with the run_id + axes + relevant bools
so downstream dvc.yaml `foreach` expressions can filter (e.g. only
hostprep runs, only runs with audio).

Usage:
    uv run python -m scripts.generate_runs_yaml

Output: runs.yaml at project root.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from enrichment.axes import NOVEL_BY_KEY  # pyright: ignore[reportMissingImports]

BASE_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = BASE_DIR / "data" / "runs"
OUT = BASE_DIR / "runs.yaml"


def _axes_for(run_dir: Path) -> dict | None:
    """Return the run's axes dict, or None if not discoverable.

    Canonical runs carry axes in config.json. Retrofit dirs (created
    via the post-hoc retrofit pipeline) leave config.json axes-less
    and write the axes into run_manifest.json instead. Fall back
    accordingly so retrofits join the canonical foreach lists.
    """
    cfg_path = run_dir / "config.json"
    if cfg_path.exists():
        with open(cfg_path) as f:
            cfg = json.load(f)
        axes = cfg.get("axes") if isinstance(cfg, dict) else None
        if isinstance(axes, dict):
            return axes
    rm_path = run_dir / "run_manifest.json"
    if rm_path.exists():
        with open(rm_path) as f:
            rm = json.load(f)
        axes = rm.get("axes") if isinstance(rm, dict) else None
        if isinstance(axes, dict):
            return axes
    return None


def collect_runs() -> list[dict[str, object]]:
    if not RUNS_DIR.exists():
        return []
    out: list[dict[str, object]] = []
    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir() or run_dir.name.startswith("_"):
            continue
        if not (run_dir / "config.json").exists():
            continue
        axes = _axes_for(run_dir)
        if axes is None:
            continue  # not a migrated canonical run and no fallback axes
        novel_key = axes.get("novel")
        novel = NOVEL_BY_KEY.get(novel_key) if isinstance(novel_key, str) else None
        entry: dict[str, object] = {
            "run_id": run_dir.name,
            "novel": novel_key,                                  # short axis (bh, motf, …)
            "novel_id": novel.id if novel else novel_key,        # filesystem id (bleak_house, …)
            "pipeline": axes.get("pipeline"),
            "panel": axes.get("panel"),
            "hostprep": bool(axes.get("hostprep")),
            "generator": axes.get("generator"),
            # Convenience booleans for DVC stage filtering:
            "has_phase3": (run_dir / "phase3_episode.json").exists(),
            "has_audio": (run_dir / "audio" / "podcast.mp3").exists(),
            "has_qwen_audio": (run_dir / "audio" / "podcast_qwen.mp3").exists(),
            "has_trevelyan_v2_audio": (run_dir / "audio" / "podcast_trevelyan_v2.mp3").exists(),
            "has_reading_list": (run_dir / "phase2_5_reading_list.json").exists(),
            "has_host_briefs": (run_dir / "phase2_5_host_briefs.json").exists(),
            "has_interviews": (run_dir / "phase2_5_interviews.json").exists(),
            "has_phase3_teaser": (run_dir / "phase3_teaser.json").exists(),
            "has_phase_timings": (run_dir / "phase_timings.json").exists(),
            "has_embedding_artifacts": (run_dir / "embedding_artifacts.json").exists(),
            "has_phase2_5_timings": (run_dir / "phase2_5_timings.json").exists(),
        }
        out.append(entry)
    return out


def main() -> None:
    runs = collect_runs()
    # Dict keyed by run_id → per-run metadata. DVC's foreach treats
    # dict values as `${item}` (so stages can reference e.g.
    # ${item.novel} for novel-specific deps like passages_enriched.json).
    runs_by_id = {r["run_id"]: r for r in runs}
    runs_by_id_hostprep = {rid: r for rid, r in runs_by_id.items() if r["hostprep"]}
    # phase2_5 stage only iterates over runs that have BOTH host_briefs
    # and interviews on disk. Hostprep runs missing one or both are
    # outside DVC's coverage until they are regenerated. (This is a
    # known retrofit gap — see Part B of the provenance plan.)
    runs_by_id_phase2_5 = {
        rid: r for rid, r in runs_by_id.items()
        if r["has_host_briefs"] and r["has_interviews"]
    }
    runs_by_id_phase2_5_briefs_only = {
        rid: r for rid, r in runs_by_id.items()
        if r["has_host_briefs"] and not r["has_interviews"]
    }
    runs_by_id_reading_list = {rid: r for rid, r in runs_by_id.items() if r["has_reading_list"]}
    runs_by_id_qwen = {rid: r for rid, r in runs_by_id.items() if r["has_qwen_audio"]}
    runs_by_id_trevelyan_v2 = {rid: r for rid, r in runs_by_id.items() if r["has_trevelyan_v2_audio"]}
    runs_by_id_embedding_artifacts = {
        rid: r for rid, r in runs_by_id.items() if r["has_embedding_artifacts"]
    }
    doc = {
        "runs": runs,
        "runs_by_id": runs_by_id,
        "runs_by_id_hostprep": runs_by_id_hostprep,
        "runs_by_id_phase2_5": runs_by_id_phase2_5,
        "runs_by_id_phase2_5_briefs_only": runs_by_id_phase2_5_briefs_only,
        "runs_by_id_reading_list": runs_by_id_reading_list,
        "runs_by_id_qwen": runs_by_id_qwen,
        "runs_by_id_trevelyan_v2": runs_by_id_trevelyan_v2,
        "runs_by_id_embedding_artifacts": runs_by_id_embedding_artifacts,
        # Index by id for quick jinja/templating use.
        "run_ids": [r["run_id"] for r in runs],
        "run_ids_phase3": [r["run_id"] for r in runs if r["has_phase3"]],
        "run_ids_audio": [r["run_id"] for r in runs if r["has_audio"]],
        "run_ids_qwen_audio": [r["run_id"] for r in runs if r["has_qwen_audio"]],
        "run_ids_trevelyan_v2_audio": [r["run_id"] for r in runs if r["has_trevelyan_v2_audio"]],
        "run_ids_hostprep": [r["run_id"] for r in runs if r["hostprep"]],
        "run_ids_phase3_teaser": [r["run_id"] for r in runs if r["has_phase3_teaser"]],
        "run_ids_phase_timings": [r["run_id"] for r in runs if r["has_phase_timings"]],
        "run_ids_phase2_5_timings": [r["run_id"] for r in runs if r["has_phase2_5_timings"]],
    }
    with open(OUT, "w") as f:
        yaml.safe_dump(doc, f, sort_keys=False, default_flow_style=False, width=200)
    print(f"Wrote {OUT} — {len(runs)} runs "
          f"({len(doc['run_ids_phase3'])} with phase3, "
          f"{len(doc['run_ids_audio'])} with audio, "
          f"{len(doc['run_ids_hostprep'])} hostprep).")


if __name__ == "__main__":
    main()
