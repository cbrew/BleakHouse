"""Authoritative per-run status report.

Answers, for one run:
  - which artefacts exist on disk (FRESH / PARTIAL / MISSING)
  - one-line VERDICT for human consumption

Pre-CAS-migration this script also reported DVC stage staleness via
`dvc status --json`. With DVC retired (BleakHouse-zmlw), the script
now reports purely on file presence.

Usage:
    uv run python -m scripts.run_status <run_id>
    uv run python -m scripts.run_status <run_id> --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = BASE_DIR / "data" / "runs"

# Phase → list of expected artefacts (relative to the run dir).
PHASE_ARTEFACTS: dict[str, list[str]] = {
    "phase0_segments": ["phase0_segments.json"],
    "phase1_assignments": ["phase1_assignments.json"],
    "phase2_plan": ["phase2_plan.json"],
    "phase2_5": ["phase2_5_host_briefs.json", "phase2_5_interviews.json"],
    "phase2_5_briefs_only": ["phase2_5_host_briefs.json"],
    "phase2_5_reading_list": ["phase2_5_reading_list.json"],
    "phase3_episode": ["phase3_episode.json"],
    "phase4_post": ["manifest.json", "report.html"],
    "phase4_audio": ["audio/podcast.mp3"],
    "quote_verification": ["quote_verification.json"],
}


def status_for_run(run_id: str) -> dict:
    """Build a structured status report for `run_id`."""
    run_dir = RUNS_DIR / run_id

    stages: list[dict] = []
    for phase, files in PHASE_ARTEFACTS.items():
        files_present = [f for f in files if (run_dir / f).exists()]
        files_missing = [f for f in files if not (run_dir / f).exists()]
        if files and files_missing:
            state = "PARTIAL" if files_present else "MISSING"
            reasons = [{"missing_files": files_missing}]
        else:
            state = "FRESH"
            reasons = []
        stages.append({
            "phase": phase,
            "state": state,
            "files_present": files_present,
            "files_missing": files_missing,
            "reasons": reasons,
        })

    # Verdict: any MISSING/PARTIAL → INCOMPLETE; else FRESH.
    verdict = "FRESH"
    if any(s["state"] in ("MISSING", "PARTIAL") for s in stages):
        verdict = "INCOMPLETE"

    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "verdict": verdict,
        "stages": stages,
    }


def _format_text(report: dict) -> str:
    out = []
    out.append(f"run: {report['run_id']}")
    out.append(f"  dir:  {report['run_dir']}")
    out.append("")
    width = max(len(s["phase"]) for s in report["stages"]) if report["stages"] else 20
    for s in report["stages"]:
        line = f"  {s['phase']:<{width}}  {s['state']}"
        if s["files_missing"]:
            line += f"  (missing: {', '.join(s['files_missing'])})"
        out.append(line)
    out.append("")
    out.append(f"  VERDICT: {report['verdict']}")
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    args = parser.parse_args()

    if not (RUNS_DIR / args.run_id).is_dir():
        sys.stderr.write(f"no such run: {args.run_id}\n")
        sys.exit(2)

    report = status_for_run(args.run_id)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(_format_text(report))
    # Exit code: 0 if FRESH, 1 if INCOMPLETE.
    sys.exit({"FRESH": 0, "INCOMPLETE": 1}[report["verdict"]])


if __name__ == "__main__":
    main()
