"""Plan the data/runs migration without touching the filesystem.

Consumes `data/runs/_inventory.json` (from `enrichment.inventory_runs`) and
emits `data/runs/_migration_plan.json`: a per-run action list
(rename | archive | review) with reasons.

Collision policy (option 1, approved): when N old dirs map to the same new
canonical name, pick one winner by heuristic and archive the rest. Winner
ranking:
  1. has phase3_episode.json (i.e. the episode was actually generated)
  2. prompt_version == 2 (current canonical prompt)
  3. config.json carries explicit novel + pipeline fields (newer schema)
  4. dir name has no trailing descriptor (_refs, _v1_X, _constrained, ...)
  5. has manifest.json
  6. most recently modified phase3_episode.json (fallback tiebreaker)

Manual overrides: optional `data/runs/_migration_overrides.json` maps old
dir names → {action, new_path?, reason?} and overrides the heuristic.

Usage: `uv run python -m enrichment.migration_dry_run`
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = BASE_DIR / "data" / "runs"
ARCHIVE_PREFIX = "_archive/"

# "Canonical-looking" means the dir name has no descriptor suffix after the
# standard {prefix}_{version}_{name}[_hostprep] pattern.
DESCRIPTOR_SUFFIX_TOKENS: frozenset[str] = frozenset({
    "refs", "constrained", "v1_1", "v1_2", "v1_3", "v1_4", "v1_5",
})

# Panel-specific canonical-label substrings. Used only as a tiebreaker in
# collision resolution: a dir whose name carries the right label for its
# inferred target panel is preferred.
CANONICAL_LABEL_BY_PANEL: dict[str, str] = {
    "literary": "v01_baseline",
    "alternatives": "v19_all_swapped",
    # interdisciplinary runs don't use a legacy label; mtime/has_config decide.
}

logger = logging.getLogger(__name__)


def _load_inventory() -> dict[str, Any]:
    inv_path = RUNS_DIR / "_inventory.json"
    if not inv_path.exists():
        raise RuntimeError(
            f"{inv_path} not found; run `uv run python -m enrichment.inventory_runs` first"
        )
    with open(inv_path) as f:
        return json.load(f)


def _load_overrides() -> dict[str, dict[str, Any]]:
    path = RUNS_DIR / "_migration_overrides.json"
    if not path.exists():
        return {}
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected object")
    result: dict[str, dict[str, Any]] = {}
    for k, v in data.items():
        if not isinstance(v, dict) or "action" not in v:
            raise ValueError(f"{path}: override {k!r} missing 'action'")
        result[str(k)] = v
    return result


def _has_descriptor_suffix(dir_name: str) -> bool:
    parts = dir_name.split("_")
    if not parts:
        return False
    if parts[-1] in DESCRIPTOR_SUFFIX_TOKENS:
        return True
    # multi-token descriptors like v1_5 live in the last two tokens
    if len(parts) >= 2 and "_".join(parts[-2:]) in DESCRIPTOR_SUFFIX_TOKENS:
        return True
    return False


def _phase3_mtime(run_name: str) -> float:
    p = RUNS_DIR / run_name / "phase3_episode.json"
    return p.stat().st_mtime if p.exists() else 0.0


def _winner_score(record: dict[str, Any]) -> tuple[int, int, int, int, int, int, float]:
    """Higher tuple = better candidate. See module docstring for ranking."""
    name = record["run_dir"]
    has_phase3 = (RUNS_DIR / name / "phase3_episode.json").exists()
    pv2 = record.get("prompt_version") == 2
    has_config = record["has_config"]
    axes = record.get("target_axes") or {}
    panel = axes.get("panel", "")
    label = CANONICAL_LABEL_BY_PANEL.get(panel, "")
    canonical_label = bool(label) and (label in name)
    no_descriptor = not _has_descriptor_suffix(name)
    has_manifest = (RUNS_DIR / name / "manifest.json").exists()
    mtime = _phase3_mtime(name)
    return (
        int(has_phase3),
        int(pv2),
        int(has_config),
        int(canonical_label),
        int(no_descriptor),
        int(has_manifest),
        mtime,
    )


def _pick_collision_winner(records: list[dict[str, Any]]) -> dict[str, Any]:
    return max(records, key=_winner_score)


def plan_migration(inventory: dict[str, Any],
                   overrides: dict[str, dict[str, Any]]) -> dict[str, Any]:
    by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unmapped: list[dict[str, Any]] = []
    for r in inventory["runs"]:
        tgt = r.get("target_dir_name")
        if tgt:
            by_target[tgt].append(r)
        else:
            unmapped.append(r)

    actions: list[dict[str, Any]] = []

    # Handle target groups: pick a winner for groups of size > 1.
    for target_name, group in sorted(by_target.items()):
        if len(group) == 1:
            actions.append({
                "action": "rename",
                "old_path": group[0]["run_dir"],
                "new_path": target_name,
                "axes": group[0]["target_axes"],
                "reason": f"canonical ({group[0]['confidence']}); unique target",
            })
            continue

        winner = _pick_collision_winner(group)
        actions.append({
            "action": "rename",
            "old_path": winner["run_dir"],
            "new_path": target_name,
            "axes": winner["target_axes"],
            "reason": f"canonical; winner of {len(group)}-way collision for {target_name}",
        })
        for loser in group:
            if loser["run_dir"] == winner["run_dir"]:
                continue
            actions.append({
                "action": "archive",
                "old_path": loser["run_dir"],
                "new_path": ARCHIVE_PREFIX + loser["run_dir"],
                "axes": None,
                "reason": f"collision loser vs {winner['run_dir']} (target {target_name})",
            })

    # Handle unmapped runs (resolution in inventory: archive or review).
    for r in unmapped:
        if r["archive_recommended"]:
            actions.append({
                "action": "archive",
                "old_path": r["run_dir"],
                "new_path": ARCHIVE_PREFIX + r["run_dir"],
                "axes": None,
                "reason": f"ambiguous+archive_recommended: {'; '.join(r['notes']) or 'no notes'}",
            })
        else:
            actions.append({
                "action": "review",
                "old_path": r["run_dir"],
                "new_path": None,
                "axes": None,
                "reason": f"ambiguous, needs human call: {'; '.join(r['notes']) or 'no notes'}",
            })

    # Apply manual overrides.
    action_by_old: dict[str, dict[str, Any]] = {a["old_path"]: a for a in actions}
    override_applied: list[str] = []
    for old, spec in overrides.items():
        if old not in action_by_old:
            raise ValueError(f"override for unknown run_dir {old!r}")
        action_by_old[old]["action"] = spec["action"]
        if "new_path" in spec:
            action_by_old[old]["new_path"] = spec["new_path"]
        action_by_old[old]["reason"] = (
            f"manual override: {spec.get('reason', 'no reason given')}"
        )
        override_applied.append(old)

    # Summary tallies.
    action_counts: dict[str, int] = defaultdict(int)
    collision_winners: list[str] = []
    for a in actions:
        action_counts[a["action"]] += 1
        if a["action"] == "rename" and "winner of" in a.get("reason", ""):
            collision_winners.append(a["old_path"])

    # Conflicts in new_path after applying actions (should be zero).
    new_path_counts: dict[str, list[str]] = defaultdict(list)
    for a in actions:
        if a["new_path"]:
            new_path_counts[a["new_path"]].append(a["old_path"])
    unresolved_collisions = {
        k: v for k, v in new_path_counts.items() if len(v) > 1
    }

    return {
        "version": "1",
        "source_inventory_version": inventory.get("version"),
        "summary": {
            "total": len(actions),
            "actions": dict(action_counts),
            "collision_groups_resolved": len(collision_winners),
            "unresolved_collisions_after_plan": unresolved_collisions,
            "overrides_applied": override_applied,
        },
        "actions": actions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=RUNS_DIR / "_migration_plan.json")
    parser.add_argument("--sample", type=int, default=5,
                        help="Number of sample actions of each kind to print.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    inv = _load_inventory()
    overrides = _load_overrides()
    plan = plan_migration(inv, overrides)
    args.output.write_text(json.dumps(plan, indent=2))

    s = plan["summary"]
    print(f"Migration plan: {s['total']} actions")
    for k, v in sorted(s["actions"].items()):
        print(f"  {k:10s} {v}")
    print(f"  collision groups resolved: {s['collision_groups_resolved']}")
    print(f"  overrides applied: {len(s['overrides_applied'])}")
    if s["unresolved_collisions_after_plan"]:
        print(f"  UNRESOLVED collisions remaining: {len(s['unresolved_collisions_after_plan'])}")
        for k, v in sorted(s["unresolved_collisions_after_plan"].items())[:5]:
            print(f"    {k}  <-  {v}")
    else:
        print("  no unresolved collisions")

    # Print samples of each action type.
    by_action: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for a in plan["actions"]:
        by_action[a["action"]].append(a)
    print()
    for action, items in sorted(by_action.items()):
        print(f"=== sample {action} ({len(items)} total, showing up to {args.sample}) ===")
        for a in items[:args.sample]:
            print(f"  {a['old_path']}  ->  {a['new_path'] or '(no new path)'}")
            print(f"    reason: {a['reason']}")

    print(f"\nWrote {args.output}")


if __name__ == "__main__":
    main()
