"""Pre-compute quote verification rates for all runs.

Caches results as quote_verification.json in each run directory.
Fast to re-run — skips runs that already have a cache file.

Usage:
    uv run python -m enrichment.precompute_quote_verification
    uv run python -m enrichment.precompute_quote_verification --force
"""

import argparse
import json
import logging
from pathlib import Path

from enrichment.experiment_h5_grounding import (  # pyright: ignore[reportMissingImports]
    fuzzy_quote_match,
    load_source_text,
)

logger = logging.getLogger(__name__)

RUNS_DIR = Path("data/runs")
CACHE_FILE = "quote_verification.json"

NOVEL_FROM_PREFIX = {
    "omf": "our_mutual_friend", "motf": "mill_on_the_floss",
    "nas": "north_and_south", "pti": "passage_to_india",
    "ht": "hard_times", "mid": "middlemarch", "dd": "daniel_deronda",
    "dc": "david_copperfield", "cran": "cranford", "noname": "no_name",
    "ngs": "new_grub_street", "oddw": "odd_women",
    "mmar": "miss_marjoribanks", "hest": "hester",
}


def detect_novel(run_name: str) -> str:
    """Infer novel key from run directory name."""
    for prefix, novel in sorted(NOVEL_FROM_PREFIX.items(), key=lambda x: -len(x[0])):
        if run_name.startswith(prefix + "_"):
            return novel
    return "bleak_house"


def verify_run(run_dir: Path, source_text: str) -> dict:
    """Verify all quotes in a run against source text."""
    ep_path = run_dir / "phase3_episode.json"
    if not ep_path.exists():
        return {"verified": 0, "total": 0, "rate": 0}

    ep = json.loads(ep_path.read_text())
    verified = 0
    total = 0

    for seg in ep.get("segments", []):
        for turn in seg.get("turns", []):
            for utt in turn.get("utterances", []):
                if utt.get("is_quote"):
                    total += 1
                    text = utt.get("text", "").strip().lstrip("> ").strip('"').strip("'")
                    if fuzzy_quote_match(text, source_text):
                        verified += 1

    rate = round(verified / total * 100, 1) if total > 0 else 0
    return {"verified": verified, "total": total, "rate": rate}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Recompute even if cached")
    args = parser.parse_args()

    # Load source texts once per novel
    source_cache: dict[str, str] = {}
    computed = 0
    skipped = 0

    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir():
            continue
        if not (run_dir / "phase3_episode.json").exists():
            continue

        cache_path = run_dir / CACHE_FILE
        if cache_path.exists() and not args.force:
            skipped += 1
            continue

        novel = detect_novel(run_dir.name)
        if novel not in source_cache:
            logger.info("Loading source text for %s", novel)
            source_cache[novel] = load_source_text(novel, RUNS_DIR)

        result = verify_run(run_dir, source_cache[novel])
        cache_path.write_text(json.dumps(result))
        computed += 1
        logger.info(
            "%s: %d/%d verified (%.1f%%)",
            run_dir.name, result["verified"], result["total"], result["rate"],
        )

    logger.info("Done: %d computed, %d skipped (cached)", computed, skipped)


if __name__ == "__main__":
    main()
