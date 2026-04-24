"""Dispatcher for `dvc repro` — regenerate a specific phase for a specific run.

DVC stages declared in dvc.yaml use this as their `cmd:`. It reads the
run's config.json (which carries the axes block) and dispatches to the
right pipeline module.

This is a stub for the first-pass DVC migration: the graph is declared
(so `dvc status` can flag stale artefacts) but automated regeneration
via `dvc repro` is not yet implemented for every phase. When DVC decides
an output is stale, use the existing pipeline CLIs to regenerate
manually — or extend this dispatcher.

Usage (invoked by DVC):
    uv run python scripts/dvc_regenerate.py <phase> --run <run_id>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = BASE_DIR / "data" / "runs"


def _not_yet(phase: str, run_id: str) -> None:
    """Print a helpful message when a phase isn't wired for auto-regen yet."""
    print(
        f"\n  [dvc-regenerate] Stage {phase!r} for run {run_id!r} is stale.\n"
        "  Automated regeneration via `dvc repro` is not wired for this phase\n"
        "  yet. Regenerate manually with the existing pipeline CLIs:\n\n"
        "    uv run python -m enrichment.run_pipeline --name "
        f"{run_id} --resume-from <phase-index> ...\n\n"
        "  Then `dvc commit` to register the new hashes.\n",
        file=sys.stderr,
    )
    sys.exit(3)


def regenerate_phase3(run_id: str) -> None:
    _not_yet("phase3", run_id)


def regenerate_phase4_post(run_id: str) -> None:
    """This one IS automatable — it's just post_phase3.run_post_phase3."""
    from enrichment.post_phase3 import run_post_phase3

    run_dir = RUNS_DIR / run_id
    if not run_dir.exists():
        print(f"  [dvc-regenerate] {run_dir} does not exist", file=sys.stderr)
        sys.exit(2)
    # post_phase3 consumes BLEAKHOUSE_NOVEL for non-bh novels.
    cfg_path = run_dir / "config.json"
    if cfg_path.exists():
        import os
        cfg = json.loads(cfg_path.read_text())
        novel = cfg.get("novel")
        if novel:
            os.environ["BLEAKHOUSE_NOVEL"] = novel
    run_post_phase3(run_dir, run_id)


def regenerate_phase4_audio(run_id: str) -> None:
    _not_yet("phase4_audio", run_id)


PHASES = {
    "phase3": regenerate_phase3,
    "phase4_post": regenerate_phase4_post,
    "phase4_audio": regenerate_phase4_audio,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=sorted(PHASES))
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    PHASES[args.phase](args.run)


if __name__ == "__main__":
    main()
