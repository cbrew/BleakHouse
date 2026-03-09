"""Compare two pipeline runs to show exactly what changed and why.

Usage:
    uv run python -m enrichment.diff_runs baseline strict
    uv run python -m enrichment.diff_runs baseline more_jo --save
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from enrichment.run_config import (  # pyright: ignore[reportMissingImports]
    RUNS_DIR,
    RunConfig,
)

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = BASE_DIR / "reports"


# ---------------------------------------------------------------------------
# Phase 1 diff: passage selection
# ---------------------------------------------------------------------------


def _load_phase1(name: str) -> dict[str, dict]:
    """Load phase1 assignments as {passage_id: assignment_dict}."""
    path = RUNS_DIR / name / "phase1_assignments.json"
    with open(path) as f:
        data = json.load(f)
    return {a["passage_id"]: a for a in data["assignments"]}


def diff_phase1(name_a: str, name_b: str) -> list[str]:
    """Diff passage selection between two runs."""
    a = _load_phase1(name_a)
    b = _load_phase1(name_b)

    ids_a = set(a.keys())
    ids_b = set(b.keys())

    added = sorted(ids_b - ids_a)
    removed = sorted(ids_a - ids_b)
    common = sorted(ids_a & ids_b)

    # Check for reassignments (same passage, different expert/dimension)
    reassigned = []
    for pid in common:
        if a[pid]["expert"] != b[pid]["expert"]:
            reassigned.append(
                f"  {pid}: {a[pid]['expert']} → {b[pid]['expert']}"
            )
        elif a[pid]["dimension"] != b[pid]["dimension"]:
            reassigned.append(
                f"  {pid}: dim {a[pid]['dimension']} → {b[pid]['dimension']}"
            )

    lines: list[str] = []
    lines.append("=== Phase 1: Passage Selection ===")
    lines.append(f"  {name_a}: {len(a)} passages")
    lines.append(f"  {name_b}: {len(b)} passages")
    lines.append("")

    if added:
        lines.append(f"  ADDED in {name_b} ({len(added)}):")
        for pid in added:
            pa = b[pid]
            lines.append(
                f"    {pid} ch={pa['chapter_id']} "
                f"dim={pa['dimension']} interest={pa['interest_score']} "
                f"→ {pa['expert']}"
            )
        lines.append("")

    if removed:
        lines.append(f"  REMOVED from {name_a} ({len(removed)}):")
        for pid in removed:
            pa = a[pid]
            lines.append(
                f"    {pid} ch={pa['chapter_id']} "
                f"dim={pa['dimension']} interest={pa['interest_score']} "
                f"→ {pa['expert']}"
            )
        lines.append("")

    if reassigned:
        lines.append(f"  REASSIGNED ({len(reassigned)}):")
        lines.extend(reassigned)
        lines.append("")

    lines.append(f"  UNCHANGED: {len(common) - len(reassigned)} passages")
    lines.append("")

    return lines


# ---------------------------------------------------------------------------
# Phase 2 diff: segment assignment
# ---------------------------------------------------------------------------


def _load_phase2(name: str) -> list[dict]:
    """Load phase2 segments."""
    path = RUNS_DIR / name / "phase2_plan.json"
    with open(path) as f:
        data = json.load(f)
    return data["segments"]


def diff_phase2(name_a: str, name_b: str) -> list[str]:
    """Diff segment assignments between two runs."""
    segs_a = _load_phase2(name_a)
    segs_b = _load_phase2(name_b)

    lines: list[str] = []
    lines.append("=== Phase 2: Segment Assignment ===")

    affected = []
    identical = []

    for sa, sb in zip(segs_a, segs_b):
        seg_name = sa["template"]["name"]
        pids_a = {a["passage_id"] for a in sa["assignments"]}
        pids_b = {a["passage_id"] for a in sb["assignments"]}

        if pids_a == pids_b:
            identical.append(seg_name)
        else:
            added = sorted(pids_b - pids_a)
            removed = sorted(pids_a - pids_b)
            affected.append((seg_name, added, removed))

    if affected:
        lines.append(f"  Segments AFFECTED: {len(affected)} of {len(segs_a)}")
        for seg_name, added, removed in affected:
            lines.append(f"    {seg_name}:")
            for pid in added:
                lines.append(f"      + {pid}")
            for pid in removed:
                lines.append(f"      - {pid}")
        lines.append("")

    lines.append(f"  Segments identical: {len(identical)} of {len(segs_a)}")
    if identical:
        for seg_name in identical:
            lines.append(f"    {seg_name}")
    lines.append("")

    return lines


# ---------------------------------------------------------------------------
# Config diff
# ---------------------------------------------------------------------------


def diff_config(name_a: str, name_b: str) -> list[str]:
    """Summarize config differences."""
    config_a = RunConfig.load(name_a)
    config_b = RunConfig.load(name_b)
    desc = config_a.describe_diff(config_b)

    lines: list[str] = []
    lines.append("=== Config Diff ===")
    lines.append(f"  {name_a} vs {name_b}: {desc}")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Full diff
# ---------------------------------------------------------------------------


def full_diff(name_a: str, name_b: str) -> str:
    """Generate a complete diff report across all phases."""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append(f"DIFF: {name_a} vs {name_b}")
    lines.append("=" * 72)
    lines.append("")

    lines.extend(diff_config(name_a, name_b))

    # Phase 1
    p1_a = RUNS_DIR / name_a / "phase1_assignments.json"
    p1_b = RUNS_DIR / name_b / "phase1_assignments.json"
    if p1_a.exists() and p1_b.exists():
        lines.extend(diff_phase1(name_a, name_b))
    else:
        lines.append("=== Phase 1: (data missing for one or both runs) ===")
        lines.append("")

    # Phase 2
    p2_a = RUNS_DIR / name_a / "phase2_plan.json"
    p2_b = RUNS_DIR / name_b / "phase2_plan.json"
    if p2_a.exists() and p2_b.exists():
        lines.extend(diff_phase2(name_a, name_b))
    else:
        lines.append("=== Phase 2: (data missing for one or both runs) ===")
        lines.append("")

    # Phase 3 — just flag whether scripts exist and differ
    p3_a = RUNS_DIR / name_a / "phase3_episode.json"
    p3_b = RUNS_DIR / name_b / "phase3_episode.json"
    lines.append("=== Phase 3: Script Generation ===")
    if p3_a.exists() and p3_b.exists():
        lines.append("  Both runs have generated scripts.")
        # Count utterances
        with open(p3_a) as f:
            ep_a = json.load(f)
        with open(p3_b) as f:
            ep_b = json.load(f)
        utts_a = sum(
            len(t["utterances"])
            for s in ep_a["segments"]
            for t in s["turns"]
        )
        utts_b = sum(
            len(t["utterances"])
            for s in ep_b["segments"]
            for t in s["turns"]
        )
        lines.append(f"  {name_a}: {utts_a} utterances")
        lines.append(f"  {name_b}: {utts_b} utterances")
    elif p3_a.exists():
        lines.append(f"  Only {name_a} has a generated script.")
    elif p3_b.exists():
        lines.append(f"  Only {name_b} has a generated script.")
    else:
        lines.append("  Neither run has a generated script yet.")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two pipeline runs")
    parser.add_argument("run_a", help="First run name")
    parser.add_argument("run_b", help="Second run name")
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save diff report to reports/",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    report = full_diff(args.run_a, args.run_b)
    print(report)

    if args.save:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORTS_DIR / f"diff_{args.run_a}_vs_{args.run_b}.txt"
        with open(path, "w") as f:
            f.write(report)
        logger.info("Saved to %s", path)


if __name__ == "__main__":
    main()
