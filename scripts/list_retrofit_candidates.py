"""List runs needing hostprep retrofit (BleakHouse-us0).

A run needs retrofit when:
  - run_manifest.json axes.hostprep is true
  - phase2_5_interviews.json or phase2_5_host_briefs.json is missing on disk
  - the dir has the phase 0/1/2 source files needed for retrofit
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED_PHASE_INPUTS = (
    "phase0_segments.json",
    "phase1_assignments.json",
    "phase2_plan.json",
    "config.json",
)


def find_candidates(repo: Path) -> list[Path]:
    out = []
    for rm in sorted((repo / "data" / "runs").glob("*/run_manifest.json")):
        try:
            m = json.loads(rm.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not m.get("axes", {}).get("hostprep"):
            continue
        d = rm.parent
        if (d / "phase2_5_interviews.json").exists() and (d / "phase2_5_host_briefs.json").exists():
            continue
        # Skip dirs that already look like retrofits.
        if d.name.endswith("_retrofit_v1"):
            continue
        # Skip if any required source file is missing — we can't retrofit it.
        if not all((d / f).exists() for f in REQUIRED_PHASE_INPUTS):
            continue
        out.append(d)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=Path("data/retrofit_candidates.txt"))
    args = p.parse_args()

    repo = Path(__file__).resolve().parent.parent
    candidates = find_candidates(repo)
    args.out.write_text("\n".join(c.name for c in candidates) + "\n")
    print(f"{len(candidates)} candidates → {args.out}")


if __name__ == "__main__":
    main()
