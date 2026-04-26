"""Carry out the migration described in `data/runs/_migration_plan.json`.

For each action:
  rename  -> move the run dir to its canonical name; add `axes` block to
             config.json; patch manifest.json's run_id field.
  archive -> move the run dir under `data/runs/_archive/`.

Uses os.rename (fast; Git detects renames via content similarity at commit
time). Run `git add data/runs/` afterwards, inspect, then commit.

Use --dry-run to see planned operations without touching the filesystem.
Use --no-manifest-patch to skip run_id patching (useful if you plan to
rebuild manifests via post_phase3.py in a follow-up step).

Usage:
    uv run python -m enrichment.migration_execute --dry-run
    uv run python -m enrichment.migration_execute
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from collections import Counter
from pathlib import Path
from typing import Any

from enrichment.axes import NOVEL_BY_KEY

BASE_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = BASE_DIR / "data" / "runs"

logger = logging.getLogger(__name__)


def _load_plan() -> dict[str, Any]:
    p = RUNS_DIR / "_migration_plan.json"
    if not p.exists():
        raise RuntimeError(
            f"{p} not found; run `uv run python -m enrichment.migration_dry_run` first"
        )
    with open(p) as f:
        return json.load(f)


def _update_config(new_dir: Path, axes: dict[str, Any]) -> None:
    """Write the `axes` block into config.json; ensure novel/pipeline/host_prep
    scalars also reflect the canonical values for human readability."""
    cfg_path = new_dir / "config.json"
    if not cfg_path.exists():
        logger.debug("  no config.json in %s; skipping axes update", new_dir)
        return
    with open(cfg_path) as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        logger.warning("  config.json in %s is not an object; skipping", new_dir)
        return
    cfg["axes"] = axes
    # Legacy scalars — keep them consistent with the axes block.
    novel_key = axes["novel"]
    if novel_key in NOVEL_BY_KEY:
        cfg["novel"] = NOVEL_BY_KEY[novel_key].id
    # Canonicalise the pipeline field (drop legacy names like "transport").
    cfg["pipeline"] = axes["pipeline"]
    cfg["host_prep"] = axes["hostprep"]
    cfg["generator"] = axes["generator"]
    with open(cfg_path, "w") as f:
        json.dump(cfg, f, indent=2)


def _patch_manifest(new_dir: Path, new_name: str) -> bool:
    mpath = new_dir / "manifest.json"
    if not mpath.exists():
        return False
    try:
        with open(mpath) as f:
            m = json.load(f)
    except json.JSONDecodeError as e:
        logger.warning("  %s: manifest.json unreadable (%s)", new_dir.name, e)
        return False
    if not isinstance(m, dict) or "run_id" not in m:
        return False
    if m["run_id"] == new_name:
        return False
    m["run_id"] = new_name
    with open(mpath, "w") as f:
        json.dump(m, f, indent=2)
    return True


def execute_plan(plan: dict[str, Any], *, dry_run: bool, patch_manifests: bool) -> dict[str, int]:
    counts: Counter[str] = Counter()
    failures: list[tuple[str, str]] = []

    archive_root = RUNS_DIR / "_archive"
    if not dry_run:
        archive_root.mkdir(exist_ok=True)

    for action in plan["actions"]:
        old_path = RUNS_DIR / action["old_path"]
        new_path = RUNS_DIR / action["new_path"]
        kind = action["action"]
        counts[f"{kind}_planned"] += 1

        if not old_path.exists():
            failures.append((action["old_path"], "source directory missing"))
            counts[f"{kind}_skipped"] += 1
            continue

        if dry_run:
            logger.info("DRY-RUN  %-8s %s -> %s",
                        kind, old_path.name, new_path.relative_to(RUNS_DIR))
            continue

        if new_path.exists():
            failures.append((action["old_path"], f"target already exists: {new_path}"))
            counts[f"{kind}_skipped"] += 1
            continue

        new_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.rename(old_path, new_path)
        except OSError as e:
            failures.append((action["old_path"], f"rename failed: {e}"))
            counts[f"{kind}_skipped"] += 1
            continue

        if kind == "rename":
            if action.get("axes"):
                _update_config(new_path, action["axes"])
            if patch_manifests:
                if _patch_manifest(new_path, action["new_path"]):
                    counts["manifests_patched"] += 1

        counts[f"{kind}_done"] += 1

    if failures:
        logger.warning("%d failures:", len(failures))
        for oldp, reason in failures[:20]:
            logger.warning("  %s: %s", oldp, reason)
        if len(failures) > 20:
            logger.warning("  ... and %d more", len(failures) - 20)

    return dict(counts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print planned operations without touching the filesystem.")
    parser.add_argument("--no-manifest-patch", action="store_true",
                        help="Skip manifest.json run_id patching on rename targets.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    plan = _load_plan()
    counts = execute_plan(plan, dry_run=args.dry_run,
                          patch_manifests=not args.no_manifest_patch)

    print()
    if args.dry_run:
        print("DRY-RUN complete. No filesystem changes made.")
    else:
        print("Migration complete.")
    for k in sorted(counts):
        print(f"  {k:25s} {counts[k]}")
    if not args.dry_run:
        print()
        print("Next: review `git status data/runs/` and commit when satisfied.")


if __name__ == "__main__":
    main()
