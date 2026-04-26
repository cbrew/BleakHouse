"""Dispatcher for `dvc repro` — regenerate a specific phase for a specific run.

DVC stages in dvc.yaml use this as their `cmd:`. It reads the run's
config.json (which carries the axes block) and invokes the right
pipeline module. Every declared stage has a real handler — no
"regenerate manually" stubs.

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


def _load_cfg(run_id: str) -> dict:
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists():
        print(f"  [dvc-regenerate] {run_dir} does not exist", file=sys.stderr)
        sys.exit(2)
    cfg_path = run_dir / "config.json"
    if not cfg_path.exists():
        print(f"  [dvc-regenerate] missing config.json at {cfg_path}", file=sys.stderr)
        sys.exit(2)
    return json.loads(cfg_path.read_text())


def _set_novel_env(cfg: dict) -> None:
    """run_pipeline and post_phase3 read BLEAKHOUSE_NOVEL for non-bh novels."""
    import os
    novel = cfg.get("novel")
    if novel:
        os.environ["BLEAKHOUSE_NOVEL"] = novel


def _pipeline_argv(run_id: str, cfg: dict, *, phase: int, resume_from: int | None) -> list[str]:
    """Build the argv for enrichment.run_pipeline based on the run's config."""
    axes = cfg.get("axes") or {}
    pipeline_axis = axes.get("pipeline", "transport")
    # Axis value → --pipeline flag name used by run_pipeline.
    pipeline_map = {
        "trn": "transport",
        "transport": "transport",
        "nop": "no-passages",
        "no-passages": "no-passages",
        "emb": "embedding",
        "embedding": "embedding",
    }
    pipeline = pipeline_map.get(pipeline_axis, pipeline_axis)
    argv = [
        "--name", run_id,
        "--novel", cfg.get("novel") or axes.get("novel") or "bleak_house",
        "--pipeline", pipeline,
        "--phase", str(phase),
    ]
    if resume_from is not None:
        argv.extend(["--resume-from", str(resume_from)])
    if axes.get("hostprep") or cfg.get("host_prep"):
        argv.append("--host-prep")
    gen = axes.get("generator") or cfg.get("generator")
    if gen:
        argv.extend(["--generator", gen])
    return argv


def _run_pipeline(argv: list[str]) -> None:
    """Invoke enrichment.run_pipeline.main() with argv. Raises on non-zero exit."""
    import subprocess
    cmd = ["uv", "run", "python", "-m", "enrichment.run_pipeline", *argv]
    print(f"  [dvc-regenerate] $ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=BASE_DIR)


def _regenerate_phase_n(run_id: str, n: int) -> None:
    cfg = _load_cfg(run_id)
    _set_novel_env(cfg)
    # `--phase n --resume-from n` produces exactly phase n's output,
    # skipping earlier phases (they're their own DVC stages).
    argv = _pipeline_argv(run_id, cfg, phase=n, resume_from=n)
    _run_pipeline(argv)


def regenerate_phase0(run_id: str) -> None:
    _regenerate_phase_n(run_id, 0)


def regenerate_phase1(run_id: str) -> None:
    _regenerate_phase_n(run_id, 1)


def regenerate_phase2(run_id: str) -> None:
    _regenerate_phase_n(run_id, 2)


def regenerate_phase3(run_id: str) -> None:
    _regenerate_phase_n(run_id, 3)


def regenerate_phase2_5(run_id: str) -> None:
    """Phase 2.5: host briefs + pre-interviews.

    Runs via `enrichment.run_pipeline --only-host-prep`, which loads
    phases 0/1/2 from disk and executes only Phase 2.5, stopping
    before Phase 3.
    """
    cfg = _load_cfg(run_id)
    _set_novel_env(cfg)
    argv = _pipeline_argv(run_id, cfg, phase=3, resume_from=3)
    # --only-host-prep implies --host-prep internally.
    if "--host-prep" not in argv:
        argv.append("--host-prep")
    argv.append("--only-host-prep")
    _run_pipeline(argv)


def regenerate_phase2_5_reading_list(run_id: str) -> None:
    """Phase 2.5 reading_list — produced only when --reference-tools is set.

    Runs `--only-host-prep --reference-tools` so the reference-tool
    verification + winnowing path writes phase2_5_reading_list.json.
    """
    cfg = _load_cfg(run_id)
    _set_novel_env(cfg)
    argv = _pipeline_argv(run_id, cfg, phase=3, resume_from=3)
    if "--host-prep" not in argv:
        argv.append("--host-prep")
    argv.extend(["--only-host-prep", "--reference-tools"])
    _run_pipeline(argv)


def regenerate_phase4_post(run_id: str) -> None:
    from enrichment.post_phase3 import run_post_phase3

    cfg = _load_cfg(run_id)
    _set_novel_env(cfg)
    run_post_phase3(RUNS_DIR / run_id, run_id)


def regenerate_phase4_audio(run_id: str) -> None:
    """Re-render audio for a run.

    Gemini-only for now — Qwen renderer has its own stage (phase4_audio_qwen,
    not yet declared; BleakHouse-lmb).
    """
    import subprocess
    cfg = _load_cfg(run_id)
    _set_novel_env(cfg)
    cmd = [
        "uv", "run", "python", "-m", "enrichment.render_audio",
        "--run", run_id,
        "--model", "flash",
        "--concurrency", "4",
    ]
    print(f"  [dvc-regenerate] $ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=BASE_DIR)


def regenerate_phase4_audio_qwen(run_id: str) -> None:
    """Render Qwen audio for a run via render_qwen_remote.sh on pop-os.

    Per-run ref source: defaults to data/runs/<run>/audio/podcast.mp3
    if it exists locally (the Gemini DVC-tracked render). For runs
    without a current Gemini render committed (e.g.
    bh_trn_alternatives_hostprep), the dispatcher consults a
    hand-maintained map below.
    """
    import subprocess
    cfg = _load_cfg(run_id)  # noqa: F841 (sanity check that the run exists)

    # Per-run ref-source override map. Speaker names verified to match
    # the run's current phase3 before adding an entry here.
    REF_SOURCE_OVERRIDES: dict[str, str] = {
        "bh_trn_alternatives_hostprep":
            "/Volumes/Crucial X9/bleakhouse_audio/_audio_archive/"
            "ext_v19_all_swapped_hostprep/podcast.mp3",
    }
    cmd = ["bash", "scripts/render_qwen_remote.sh", run_id]
    if run_id in REF_SOURCE_OVERRIDES:
        cmd.extend(["--ref-source", REF_SOURCE_OVERRIDES[run_id]])
    print(f"  [dvc-regenerate] $ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=BASE_DIR)


def regenerate_phase4_audio_trevelyan_v2(run_id: str) -> None:
    """Render audio for a run using the trevelyan_v2 (Gemini 3.1 Flash) profile."""
    import subprocess
    cfg = _load_cfg(run_id)
    _set_novel_env(cfg)
    cmd = [
        "uv", "run", "python", "-m", "enrichment.render_audio",
        "--run", run_id,
        "--profile", "trevelyan_v2",
        "--concurrency", "4",
    ]
    print(f"  [dvc-regenerate] $ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=BASE_DIR)


PHASES = {
    "phase0": regenerate_phase0,
    "phase1": regenerate_phase1,
    "phase2": regenerate_phase2,
    "phase2_5": regenerate_phase2_5,
    "phase2_5_reading_list": regenerate_phase2_5_reading_list,
    "phase3": regenerate_phase3,
    "phase4_post": regenerate_phase4_post,
    "phase4_audio": regenerate_phase4_audio,
    "phase4_audio_qwen": regenerate_phase4_audio_qwen,
    "phase4_audio_trevelyan_v2": regenerate_phase4_audio_trevelyan_v2,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=sorted(PHASES))
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    PHASES[args.phase](args.run)


if __name__ == "__main__":
    main()
