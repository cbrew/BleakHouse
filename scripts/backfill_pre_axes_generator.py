"""Backfill the `axes` block on pre-axes-block run configs.

The `axes` block (novel/pipeline/panel/hostprep/generator/length) was
introduced in commit 8153853f (2026-05-02). Runs created before that —
specifically the retrofit_* runs from late April 2026 — have flat
configs without an `axes` block and without an explicit `generator`
field. The expdb scanner falls back to `generator="unknown"` for them,
which surfaces on /scripts as an "unknown" entry in the generator
dropdown.

User direction (2026-05-16): "assume that all pre-axes runs were done
with haiku and sonnet, same versions as the runs for which that
information is available." Translated:

  - The Phase 3 prose generator was Sonnet 4.6, so axes.generator =
    "anthropic_sonnet_4_6".
  - Everything else can be inferred from the existing flat config:
    * novel        — top-level `novel` (long form) → short via NOVEL_BY_ID
    * pipeline     — top-level `pipeline` (long form) → short via the
                     CANONICAL_PIPELINES inverse map
    * panel        — derived from `experts` list via panel_for_experts
    * hostprep     — top-level `host_prep`
    * length       — heuristic from run_id ("_short" suffix → "short",
                     otherwise "long"). All known retrofit runs are long.

The script writes BOTH a new axes block AND a top-level `generator`
field so the result matches the shape that post-axes-block run_pipeline
emits today.

Idempotency
-----------
Skips any run whose config already has an axes block AND a generator
that isn't "unknown". Re-running on a backfilled tree is a no-op.

Atomicity
---------
Each config.json is written via a same-directory tmp file + os.replace
so a kill mid-run never leaves a half-written file.

Usage
-----
  uv run python scripts/backfill_pre_axes_generator.py [--apply]

Default is dry-run: reports the patches that would be applied without
writing. Use --apply to commit changes to disk.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("backfill_axes")

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "data" / "runs"

DEFAULT_GENERATOR = "anthropic_sonnet_4_6"
DEFAULT_LENGTH = "long"

# pipeline long→short mirror of CANONICAL_PIPELINES / PIPELINES in
# enrichment/axes.py. Kept local so this script doesn't pull the
# import for a 4-entry table.
_PIPELINE_LONG_TO_SHORT = {
    "transport": "trn",
    "embedding": "emb",
    "no_passages": "nop",
    "no-passages": "nop",  # the hyphenated form used by pre-axes-block CLI
    "rag": "rag",
}


def _short_novel(long_form: str) -> str | None:
    """Look up the short novel key from a long-form id (e.g. 'bleak_house' → 'bh')."""
    from enrichment import axes  # local import to honour CLAUDE.md test isolation
    nv = axes.NOVEL_BY_ID.get(long_form)
    return nv.key if nv else None


def _derive_axes(cfg: dict[str, Any], run_id: str) -> dict[str, Any] | None:
    """Build an axes block from a flat (pre-axes) config. Returns None
    if the config is too far gone — caller logs and skips."""
    from enrichment.axes import panel_for_experts  # type: ignore

    novel_long = cfg.get("novel")
    pipeline_long = cfg.get("pipeline")
    if not isinstance(novel_long, str) or not isinstance(pipeline_long, str):
        logger.warning(
            "%s: config missing novel/pipeline — skipped (was novel=%r pipeline=%r)",
            run_id, novel_long, pipeline_long,
        )
        return None

    novel_short = _short_novel(novel_long)
    if novel_short is None:
        logger.warning(
            "%s: unknown novel id %r — skipped",
            run_id, novel_long,
        )
        return None

    pipeline_short = _PIPELINE_LONG_TO_SHORT.get(pipeline_long)
    if pipeline_short is None:
        logger.warning(
            "%s: unknown pipeline %r — skipped",
            run_id, pipeline_long,
        )
        return None

    experts = cfg.get("experts") or []
    expert_names: list[str] = [
        e["name"] for e in experts
        if isinstance(e, dict) and isinstance(e.get("name"), str)
    ]
    panel = panel_for_experts(expert_names)
    if panel is None:
        logger.warning(
            "%s: experts %r don't match any registered panel — skipped",
            run_id, expert_names,
        )
        return None

    hostprep = bool(cfg.get("host_prep"))

    # length: heuristic. The retrofit cohort is all long; check the
    # run_id suffix anyway so a future short-variant retrofit comes
    # through correctly.
    length = "short" if run_id.endswith("_short") else DEFAULT_LENGTH

    return {
        "novel":     novel_short,
        "pipeline":  pipeline_short,
        "panel":     panel,
        "hostprep":  hostprep,
        "generator": DEFAULT_GENERATOR,
        "length":    length,
    }


def _atomic_write_json(path: Path, payload: dict) -> None:
    """Write JSON via tmp + rename so the destination is never partial."""
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if not text.endswith("\n"):
        text += "\n"
    tmp = path.with_suffix(path.suffix + ".backfill.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Write changes. Default is dry-run.",
    )
    args = parser.parse_args()

    if not RUNS_DIR.is_dir():
        logger.error("No data/runs/ directory at %s", RUNS_DIR)
        return 1

    scanned = 0
    skipped_already_axed = 0
    skipped_no_config = 0
    patched = 0

    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir():
            continue
        config_path = run_dir / "config.json"
        if not config_path.exists():
            skipped_no_config += 1
            continue
        scanned += 1

        run_id = run_dir.name
        try:
            cfg = json.loads(config_path.read_text())
        except json.JSONDecodeError as exc:
            logger.warning("%s: config.json parse failed: %s", run_id, exc)
            continue
        if not isinstance(cfg, dict):
            logger.warning("%s: config.json isn't a JSON object", run_id)
            continue

        # Idempotency: skip if axes block already has a non-unknown generator.
        existing_axes = cfg.get("axes")
        existing_gen = (
            existing_axes.get("generator")
            if isinstance(existing_axes, dict) else None
        ) or cfg.get("generator")
        if isinstance(existing_axes, dict) and existing_gen and existing_gen != "unknown":
            skipped_already_axed += 1
            continue

        axes_block = _derive_axes(cfg, run_id)
        if axes_block is None:
            continue

        new_cfg = dict(cfg)
        new_cfg["axes"] = axes_block
        # Mirror the axes generator at top level so legacy readers
        # (build_content_db's flat-shape fallback) see it too.
        new_cfg["generator"] = DEFAULT_GENERATOR

        action = "WOULD PATCH" if not args.apply else "PATCHED"
        logger.info(
            "%s %s → axes=%s",
            action, run_id, axes_block,
        )
        if args.apply:
            _atomic_write_json(config_path, new_cfg)
        patched += 1

    logger.info(
        "Scanned %d run configs; patched %d; skipped %d (already axed); "
        "%d had no config.json. %s",
        scanned, patched, skipped_already_axed, skipped_no_config,
        "DRY RUN — pass --apply to write." if not args.apply else "DONE.",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
