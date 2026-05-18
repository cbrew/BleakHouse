"""Side-by-side host_prep run on North & South alternatives panel.

Runs Phase 2.5 (pre-interviews with reference tools + question-plan briefs)
twice on the same input: once under the host_prep_qwen profile (qwen3-235b on
DeepInfra for all 5 host_prep tasks), once under the production profile
(Anthropic Haiku + Sonnet).

Inputs are reused from data/runs/nas_trn_alternatives_hostprep/
(alternatives panel: Edmund Leigh, Daniel Rosen, Oliver Trevelyan).
Scoped to the first 3 segments out of 7 to keep cost and wall-clock bounded
for a one-off comparison.

Outputs to two sibling run dirs:
  data/runs/nas_trn_alternatives_hostprep_qwen_2026_05_17/
  data/runs/nas_trn_alternatives_hostprep_anthropic_2026_05_17/

Each contains: phase2_5_host_briefs.json, phase2_5_interviews.json, plus
the recorded timings/cost.

USAGE:
    uv run python scripts/probe_host_prep_qwen_vs_anthropic.py
"""
from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_RUN = REPO_ROOT / "data" / "runs" / "nas_trn_alternatives_hostprep"
RUNS_DIR = REPO_ROOT / "data" / "runs"

QWEN_RUN = RUNS_DIR / "nas_trn_alternatives_hostprep_qwen_2026_05_17"
ANTH_RUN = RUNS_DIR / "nas_trn_alternatives_hostprep_anthropic_2026_05_17"

N_SEGMENTS = 3

NOVEL_KEY = "north_and_south"

logger = logging.getLogger("probe")


def _prep_run_dir(target: Path) -> tuple[dict, list, list]:
    """Copy phase 0/1/2 artefacts; truncate plan to first N_SEGMENTS.

    Returns (phase2_plan_truncated, segments, assignments_by_segment).
    """
    target.mkdir(parents=True, exist_ok=True)
    for fname in ("config.json", "phase0_segments.json",
                  "phase1_assignments.json", "phase2_plan.json"):
        src = SOURCE_RUN / fname
        if src.exists():
            shutil.copy2(src, target / fname)

    # Load and truncate phase2 plan
    plan = json.loads((target / "phase2_plan.json").read_text())
    plan["segments"] = plan["segments"][:N_SEGMENTS]
    (target / "phase2_plan.json").write_text(json.dumps(plan, indent=2))

    # Build assignments-by-segment list (same shape as run_pipeline does it)
    raw_assignments = json.loads((target / "phase1_assignments.json").read_text())
    if isinstance(raw_assignments, dict):
        assignments = raw_assignments.get("assignments", raw_assignments)
    else:
        assignments = raw_assignments
    pa_lookup = {a["passage_id"]: a for a in assignments}

    segments = plan["segments"]
    assignments_by_segment = []
    for seg in segments:
        seg_assignments = []
        for a in seg.get("assignments", []):
            full = pa_lookup.get(a.get("passage_id", ""), a)
            seg_assignments.append(full)
        assignments_by_segment.append(seg_assignments)

    return plan, segments, assignments_by_segment


def _alternatives_personas():
    """Return the alternatives-panel personas that the source run used."""
    from enrichment.podcast_types import ALTERNATIVE_PERSONAS
    return [
        ALTERNATIVE_PERSONAS["sir_edmund"],     # Edmund Leigh
        ALTERNATIVE_PERSONAS["dr_rosen"],       # Daniel Rosen
        ALTERNATIVE_PERSONAS["trevelyan"],      # Oliver Trevelyan
    ]


def _run_one(profile: str, run_dir: Path, novel_title: str, novel_author: str) -> dict:
    """Activate `profile`, run Phase 2.5 with refs, save artefacts. Return timings."""
    import enrichment.llm.settings as S
    from enrichment.host_prep import run_host_prep

    S.activate(profile)
    logger.info("=== profile=%s → run_dir=%s ===", profile, run_dir.name)
    for task in ("host_prep_pre_interview", "host_prep_pre_interview_structured",
                 "host_prep_brief", "reading_list_winnow", "reference_tools_winnow"):
        spec = S.for_task(task)
        logger.info("  %s → %s/%s/%s", task, spec.provider, spec.hosting, spec.model)

    _plan, segments, assignments_by_segment = _prep_run_dir(run_dir)
    personas = _alternatives_personas()

    t0 = time.monotonic()
    briefs, interviews = run_host_prep(
        personas, segments, assignments_by_segment,
        novel_title, novel_author,
        use_reference_tools=True,
        run_dir=run_dir,
    )
    elapsed = time.monotonic() - t0

    # Persist artefacts in the same shape the production runner uses.
    (run_dir / "phase2_5_host_briefs.json").write_text(
        json.dumps([b.model_dump() for b in briefs], indent=2)
    )
    (run_dir / "phase2_5_interviews.json").write_text(
        json.dumps(
            [[iv.model_dump() for iv in seg_ivs] for seg_ivs in interviews],
            indent=2,
        )
    )

    n_questions = sum(len(b.questions) for b in briefs)
    n_refs = sum(len(iv.proposed_references)
                 for seg_ivs in interviews for iv in seg_ivs)
    logger.info(
        "  done in %.1fs — %d briefs, %d total questions, %d proposed_references",
        elapsed, len(briefs), n_questions, n_refs,
    )
    return {
        "profile": profile,
        "run_dir": str(run_dir.relative_to(REPO_ROOT)),
        "elapsed_s": round(elapsed, 1),
        "n_segments": len(briefs),
        "n_questions_total": n_questions,
        "n_proposed_references_total": n_refs,
    }


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )
    load_dotenv(REPO_ROOT / ".env")

    from enrichment.novel_prompts import get_active_novel
    import os
    os.environ["BLEAKHOUSE_NOVEL"] = NOVEL_KEY
    cfg = get_active_novel(NOVEL_KEY)
    logger.info("novel: %s (%s)", cfg.title, cfg.author)
    logger.info("source: %s", SOURCE_RUN.relative_to(REPO_ROOT))
    logger.info("scope: first %d segments of 7", N_SEGMENTS)

    qwen_stats = _run_one("host_prep_qwen", QWEN_RUN, cfg.title, cfg.author)
    anth_stats = _run_one("production", ANTH_RUN, cfg.title, cfg.author)

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for s in (qwen_stats, anth_stats):
        print(f"  {s['profile']:18s}  {s['elapsed_s']:6.1f}s  "
              f"{s['n_questions_total']:3d} questions  "
              f"{s['n_proposed_references_total']:3d} refs  "
              f"→ {s['run_dir']}")
    (REPO_ROOT / "data" / "runs" / "_nas_alternatives_host_prep_comparison.json").write_text(
        json.dumps({"qwen": qwen_stats, "anthropic": anth_stats}, indent=2)
    )


if __name__ == "__main__":
    main()
