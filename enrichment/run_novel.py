"""Run the pipeline on a non-Bleak-House novel.

Sets BLEAKHOUSE_NOVEL env var so transport_podcast, embedding_podcast, and
embedding_run modules read from data/novels/<novel_key>/ instead of data/.

Usage:
    uv run python -m enrichment.run_novel --novel our_mutual_friend \
        --condition transport --panel v01_baseline

    uv run python -m enrichment.run_novel --novel passage_to_india \
        --condition no-passages --panel v30_woodcourt_edmund_trevelyan

    # Run all 6 conditions for one novel:
    uv run python -m enrichment.run_novel --novel north_and_south --all
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

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

CONDITIONS = ["transport", "embedding", "no-passages"]

# Panel definitions: name -> list of --replace-expert args
PANELS: dict[str, list[str]] = {
    "v01_baseline": [],
    "v11_rosen_blackstone_woodcourt": [
        "Eleanor Hartley=dr_rosen",
    ],
    "v21_hartley_blackstone_edmund": [
        "Caroline Woodcourt=sir_edmund",
    ],
    "v22_hartley_blackstone_rosen": [
        "Caroline Woodcourt=dr_rosen",
    ],
    "v23_hartley_rosen_woodcourt": [
        "James Blackstone=dr_rosen",
    ],
    "v26_blackstone_woodcourt_edmund": [
        "Eleanor Hartley=sir_edmund",
    ],
    "v29_rosen_blackstone_trevelyan": [
        "Eleanor Hartley=dr_rosen",
        "Caroline Woodcourt=trevelyan",
    ],
    "v19_all_swapped": [
        "Eleanor Hartley=trevelyan",
        "James Blackstone=sir_edmund",
        "Caroline Woodcourt=dr_rosen",
    ],
    "v30_woodcourt_edmund_trevelyan": [
        "Eleanor Hartley=trevelyan",
        "James Blackstone=sir_edmund",
    ],
}

NOVEL_PREFIXES = {
    "our_mutual_friend": "omf",
    "mill_on_the_floss": "motf",
    "north_and_south": "nas",
    "passage_to_india": "pti",
    "hard_times": "ht",
    "middlemarch": "mid",
    "daniel_deronda": "dd",
    "david_copperfield": "dc",
    "cranford": "cran",
    "no_name": "noname",
    "new_grub_street": "ngs",
    "odd_women": "oddw",
    "miss_marjoribanks": "mmar",
    "hester": "hest",
}

COND_PREFIXES = {
    "transport": "trn",
    "embedding": "emb",
    "no-passages": "nop",
}


def build_run_name(novel_key: str, condition: str, panel: str) -> str:
    return f"{NOVEL_PREFIXES[novel_key]}_{COND_PREFIXES[condition]}_{panel}"


def run_condition(
    novel_key: str, condition: str, panel: str, prompt_version: int,
) -> None:
    """Run a single condition, setting BLEAKHOUSE_NOVEL in the environment."""
    name = build_run_name(novel_key, condition, panel)

    # Check prerequisites
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
                "Run generate_contexts.py and embed_passages.py first.",
                vectors,
            )
            sys.exit(1)

    # run_pipeline.py works for transport but its embedding/no-passages
    # paths are incomplete. Dispatch to the per-condition modules directly.
    modules = {
        "transport": "enrichment.run_pipeline",
        "embedding": "enrichment.embedding_run",
        "no-passages": "enrichment.no_passages_run",
    }
    module = modules[condition]

    cmd = [
        sys.executable, "-m", module,
        "--name", name,
        "--novel", novel_key,
        "--prompt-version", str(prompt_version),
    ]
    if module == "enrichment.run_pipeline":
        cmd.extend(["--pipeline", condition])
    for replacement in PANELS.get(panel, []):
        cmd.extend(["--replace-expert", replacement])

    # Set env var for data path redirection
    env = {**os.environ, "BLEAKHOUSE_NOVEL": novel_key}

    logger.info("Running: BLEAKHOUSE_NOVEL=%s %s", novel_key, " ".join(cmd[1:]))
    subprocess.run(cmd, env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run pipeline on a novel")
    parser.add_argument(
        "--novel", required=True, choices=NOVEL_KEYS, help="Novel to process"
    )
    parser.add_argument(
        "--condition", choices=CONDITIONS, help="Selection condition"
    )
    parser.add_argument(
        "--panel", choices=list(PANELS.keys()), help="Expert panel"
    )
    parser.add_argument(
        "--prompt-version", type=int, default=3, help="Prompt version (default: 3)"
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Run all conditions × panels",
    )
    parser.add_argument(
        "--panels", nargs="+", choices=list(PANELS.keys()),
        help="Subset of panels to run with --all (default: all panels)",
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
        panels = args.panels or list(PANELS.keys())
        for panel in panels:
            for condition in conditions:
                try:
                    run_condition(args.novel, condition, panel, args.prompt_version)
                except subprocess.CalledProcessError as e:
                    logger.error(
                        "FAILED: %s %s %s (exit %d)",
                        args.novel, condition, panel, e.returncode,
                    )
    elif args.condition and args.panel:
        run_condition(args.novel, args.condition, args.panel, args.prompt_version)
    else:
        parser.error("Provide --condition and --panel, or use --all")


if __name__ == "__main__":
    main()
