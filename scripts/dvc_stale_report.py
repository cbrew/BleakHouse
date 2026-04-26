"""Summarise DVC-stale runs.

Wraps `dvc status --json`, groups the stale stages by phase and by
offending dep, and prints a human-readable table.

Usage:
    uv run python -m scripts.dvc_stale_report
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def main() -> None:
    proc = subprocess.run(
        ["uv", "run", "--no-sync", "dvc", "status", "--json"],
        capture_output=True, text=True, cwd=BASE_DIR,
    )
    if proc.returncode not in (0, 1):
        print(proc.stderr, file=sys.stderr)
        sys.exit(proc.returncode)

    data = json.loads(proc.stdout or "{}")
    if not data:
        print("All 194 runs are fresh.")
        return

    by_phase: dict[str, list[str]] = defaultdict(list)
    dep_freq: dict[str, int] = defaultdict(int)

    for stage_name, changes in data.items():
        if "@" not in stage_name:
            continue
        phase, run_id = stage_name.split("@", 1)
        by_phase[phase].append(run_id)
        for change in changes:
            if not isinstance(change, dict):
                continue
            if "changed deps" in change:
                for dep in change["changed deps"]:
                    dep_freq[dep] += 1
            if "changed outs" in change:
                for out in change["changed outs"]:
                    dep_freq[f"(out) {out}"] += 1

    total = sum(len(ids) for ids in by_phase.values())
    print(f"{total} stale stages across {len(by_phase)} phases:\n")
    for phase, runs in sorted(by_phase.items()):
        print(f"  {phase:18s} {len(runs):4d} runs")
    print()
    print("Most-frequent offenders:")
    for dep, n in sorted(dep_freq.items(), key=lambda x: -x[1])[:10]:
        print(f"  {n:4d}  {dep}")
    print()
    print("To re-baseline after regenerating artefacts: `uv run dvc commit`")


if __name__ == "__main__":
    main()
