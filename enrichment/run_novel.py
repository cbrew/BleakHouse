"""Run the pipeline on a non-Bleak-House novel.

Sets BLEAKHOUSE_NOVEL env var so transport_podcast, embedding_podcast, and
embedding_run modules read from data/novels/<novel_key>/ instead of data/.

Usage:
    uv run python -m enrichment.run_novel --novel our_mutual_friend \
        --condition transport --panel literary

    uv run python -m enrichment.run_novel --novel passage_to_india \
        --condition no-passages --panel alternatives --hostprep

    # Run all 3 conditions × 3 panels for one novel:
    uv run python -m enrichment.run_novel --novel north_and_south --all
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

from enrichment.axes import NOVEL_BY_ID, PANEL_BY_ID, RunAxes

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

# Non-Bleak-House novels supported by this runner; keys are axes.Novel.id.
NOVEL_KEYS = [
    "our_mutual_friend",
    "mill_on_the_floss",
    "north_and_south",
    "passage_to_india",
    "hard_times",
    "middlemarch",
    "daniel_deronda",
    "david_copperfield",
    "cranford",
    "no_name",
    "new_grub_street",
    "odd_women",
    "miss_marjoribanks",
    "hester",
]

# CLI condition names map 1-1 to axes.PIPELINES values.
CONDITION_TO_PIPELINE: dict[str, str] = {
    "transport": "trn",
    "embedding": "emb",
    "no-passages": "nop",
}
CONDITIONS = list(CONDITION_TO_PIPELINE)

# Panel → list of --replace-expert args for run_pipeline.
# `literary` is the default persona set (no replacements); the other panels
# swap the three default experts with their canonical counterparts.
PANEL_REPLACEMENTS: dict[str, list[str]] = {
    "literary": [],
    "alternatives": [
        "Eleanor Hartley=trevelyan",
        "James Blackstone=sir_edmund",
        "Caroline Woodcourt=dr_rosen",
    ],
    "interdisciplinary": [
        "Eleanor Hartley=chen_nlp",
        "James Blackstone=martinez_astro",
        "Caroline Woodcourt=volkov_music",
    ],
}
# Legacy panel aliases kept so existing .sh scripts don't need a flag-day rename.
LEGACY_PANEL_ALIAS: dict[str, str] = {
    "v01_baseline": "literary",
    "v19_all_swapped": "alternatives",
}


def _resolve_panel(panel_arg: str) -> str:
    """Accept canonical panel ids (literary|alternatives|interdisciplinary)
    or legacy labels (v01_baseline, v19_all_swapped); raise on anything else."""
    if panel_arg in PANEL_REPLACEMENTS:
        return panel_arg
    if panel_arg in LEGACY_PANEL_ALIAS:
        return LEGACY_PANEL_ALIAS[panel_arg]
    raise ValueError(
        f"unknown panel {panel_arg!r}; expected one of "
        f"{sorted(PANEL_REPLACEMENTS) + sorted(LEGACY_PANEL_ALIAS)}"
    )


def build_run_name(
    novel_key: str,
    condition: str,
    panel: str,
    *,
    hostprep: bool = False,
    length: str = "long",
) -> str:
    """Canonical run-dir name via `axes.RunAxes.dir_name()`."""
    if novel_key not in NOVEL_BY_ID:
        raise ValueError(f"unknown novel {novel_key!r}")
    if condition not in CONDITION_TO_PIPELINE:
        raise ValueError(f"unknown condition {condition!r}; one of {CONDITIONS}")
    panel_id = _resolve_panel(panel)
    if panel_id not in PANEL_BY_ID:
        raise ValueError(f"unknown panel {panel_id!r}")
    axes = RunAxes(
        novel=NOVEL_BY_ID[novel_key].key,
        pipeline=CONDITION_TO_PIPELINE[condition],
        panel=panel_id,
        hostprep=hostprep,
        length=length,
    )
    return axes.dir_name()


def run_condition(
    novel_key: str,
    condition: str,
    panel: str,
    prompt_version: int,
    hostprep: bool = False,
    length: str = "long",
) -> None:
    """Run a single condition, setting BLEAKHOUSE_NOVEL in the environment."""
    panel_id = _resolve_panel(panel)
    name = build_run_name(novel_key, condition, panel_id,
                          hostprep=hostprep, length=length)

    novel_dir = DATA_DIR / "novels" / novel_key
    enriched = novel_dir / "passages_enriched.json"
    if not enriched.exists():
        logger.error("No enriched passages at %s", enriched)
        sys.exit(1)

    if condition == "embedding":
        vectors = novel_dir / "vectors"
        if not vectors.exists():
            logger.error(
                "No vector index at %s. "
                "Run submit_passage_contexts/collect_passage_contexts and embed_passages.py first.",
                vectors,
            )
            sys.exit(1)

    cmd = [
        sys.executable, "-m", "enrichment.run_pipeline",
        "--name", name,
        "--novel", novel_key,
        "--pipeline", condition,
        "--prompt-version", str(prompt_version),
        "--length", length,
    ]
    for replacement in PANEL_REPLACEMENTS[panel_id]:
        cmd.extend(["--replace-expert", replacement])
    if hostprep:
        cmd.append("--host-prep")

    env = {**os.environ, "BLEAKHOUSE_NOVEL": novel_key}
    logger.info("Running: BLEAKHOUSE_NOVEL=%s %s", novel_key, " ".join(cmd[1:]))
    subprocess.run(cmd, env=env, check=True)


_PANEL_CHOICES = sorted(set(PANEL_REPLACEMENTS) | set(LEGACY_PANEL_ALIAS))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run pipeline on a novel")
    parser.add_argument(
        "--novel", required=True, choices=NOVEL_KEYS, help="Novel to process"
    )
    parser.add_argument(
        "--condition", choices=CONDITIONS, help="Selection condition"
    )
    parser.add_argument(
        "--panel", choices=_PANEL_CHOICES,
        help="Expert panel (canonical: literary|alternatives|interdisciplinary; "
             "legacy aliases: v01_baseline→literary, v19_all_swapped→alternatives).",
    )
    parser.add_argument(
        "--prompt-version", type=int, default=3, help="Prompt version (default: 3)"
    )
    parser.add_argument("--hostprep", action="store_true",
                        help="Enable Phase 2.5 host preparation.")
    parser.add_argument(
        "--length", choices=("long", "short"), default="long",
        help="Episode length variant. 'long' (~90 min) is the legacy "
             "default; 'short' (~30 min) writes to a sibling _short run dir.",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Run all conditions × panels",
    )
    parser.add_argument(
        "--panels", nargs="+", choices=_PANEL_CHOICES,
        help="Subset of panels to run with --all (default: all canonical panels).",
    )
    parser.add_argument(
        "--skip-embedding", action="store_true",
        help="Skip embedding condition (if no vector index yet)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    if args.all:
        conditions = CONDITIONS
        if args.skip_embedding:
            conditions = [c for c in conditions if c != "embedding"]
        panels = args.panels or list(PANEL_REPLACEMENTS)
        for panel in panels:
            for condition in conditions:
                try:
                    run_condition(args.novel, condition, panel,
                                  args.prompt_version, hostprep=args.hostprep,
                                  length=args.length)
                except subprocess.CalledProcessError as e:
                    logger.error(
                        "FAILED: %s %s %s (exit %d)",
                        args.novel, condition, panel, e.returncode,
                    )
    elif args.condition and args.panel:
        run_condition(args.novel, args.condition, args.panel,
                      args.prompt_version, hostprep=args.hostprep,
                      length=args.length)
    else:
        parser.error("Provide --condition and --panel, or use --all")


if __name__ == "__main__":
    main()
