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

BASE_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = BASE_DIR / "data" / "runs"
OUT = BASE_DIR / "runs.yaml"


def collect_runs() -> list[dict[str, object]]:
    if not RUNS_DIR.exists():
        return []
    out: list[dict[str, object]] = []
    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir() or run_dir.name.startswith("_"):
            continue
        cfg_path = run_dir / "config.json"
        if not cfg_path.exists():
            continue
        with open(cfg_path) as f:
            cfg = json.load(f)
        axes = cfg.get("axes") if isinstance(cfg, dict) else None
        if not isinstance(axes, dict):
            continue  # not a migrated canonical run
        entry: dict[str, object] = {
            "run_id": run_dir.name,
            "novel": axes.get("novel"),
            "pipeline": axes.get("pipeline"),
            "panel": axes.get("panel"),
            "hostprep": bool(axes.get("hostprep")),
            "generator": axes.get("generator"),
            # Convenience booleans for DVC stage filtering:
            "has_phase3": (run_dir / "phase3_episode.json").exists(),
            "has_audio": (run_dir / "audio" / "podcast.mp3").exists(),
        }
        out.append(entry)
    return out


def main() -> None:
    runs = collect_runs()
    doc = {
        "runs": runs,
        # Index by id for quick jinja/templating use.
        "run_ids": [r["run_id"] for r in runs],
        "run_ids_phase3": [r["run_id"] for r in runs if r["has_phase3"]],
        "run_ids_audio": [r["run_id"] for r in runs if r["has_audio"]],
        "run_ids_hostprep": [r["run_id"] for r in runs if r["hostprep"]],
    }
    with open(OUT, "w") as f:
        yaml.safe_dump(doc, f, sort_keys=False, default_flow_style=False, width=200)
    print(f"Wrote {OUT} — {len(runs)} runs "
          f"({len(doc['run_ids_phase3'])} with phase3, "
          f"{len(doc['run_ids_audio'])} with audio, "
          f"{len(doc['run_ids_hostprep'])} hostprep).")


if __name__ == "__main__":
    main()
