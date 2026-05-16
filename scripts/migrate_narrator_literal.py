"""Migrate the `narrator` enrichment field from the legacy Bleak-House-
specific literal `"esther"` to the generic `"first_person"`.

Why this exists
---------------
Before the de-Bleak-House cleanup, `FieldReportEnrichment.narrator`
was a `Literal["esther", "omniscient", "unclear"]` — Bleak House's
first-person narrator's name was hard-coded as a valid value, which
leaked into every other novel's enrichment output. The schema is now
`Literal["first_person", "omniscient", "unclear"]` — provider-neutral
and novel-neutral. Every existing on-disk artifact that carries the
old literal needs to be re-emitted with the new one.

Files this touches
------------------
- data/novels/<novel>/passages_enriched.json
- data/novels/<novel>/passages_contextual.json
- data/runs/*/manifest.json
- data/runs/*/phase1_assignments.json
- data/runs/*/phase2_plan.json
- data/experiment_ablation.json
- data/experiment_contextual.json
- data/experiment_retrieval_precision.json

(The data/runs files derive their `narrator` from passages_enriched
indirectly — they were produced by re-running build_manifest /
expdb scan over enrichment at some point in the past. The experiment
JSONs were captured before the schema change. We don't try to
regenerate any of them; we just patch the literal in place.)

Idempotency
-----------
Re-running this script on already-migrated data is a no-op: it scans
for `"esther"` only. Already-`"first_person"` values pass through
untouched. Any unexpected narrator literal logs a warning and is
left alone for human review.

Atomicity
---------
Each file is written via a temp file + rename. If the script is
killed mid-run, no file is left half-written.

Usage
-----
    uv run python scripts/migrate_narrator_literal.py [--dry-run]

`--dry-run` lists what would change without writing.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

logger = logging.getLogger("migrate_narrator")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OLD_LITERAL = "esther"
NEW_LITERAL = "first_person"
VALID_AFTER = frozenset({"first_person", "omniscient", "unclear"})


def _candidate_files() -> Iterator[Path]:
    """Files this migration touches. Order is just for stable reporting.

    Allow-list rather than walking the data tree so we don't accidentally
    rewrite something with a surprise structure (probe outputs, caches,
    etc.). Adding a new file type means an explicit entry here."""
    # Novel-level enrichment + context outputs
    novels = DATA / "novels"
    if novels.is_dir():
        for nd in sorted(novels.iterdir()):
            if not nd.is_dir():
                continue
            for name in ("passages_enriched.json", "passages_contextual.json"):
                p = nd / name
                if p.exists():
                    yield p
    # Run-level derived artifacts
    runs = DATA / "runs"
    if runs.is_dir():
        for rd in sorted(runs.iterdir()):
            if not rd.is_dir():
                continue
            for name in ("manifest.json", "phase1_assignments.json",
                         "phase2_plan.json"):
                p = rd / name
                if p.exists():
                    yield p
    # Top-level experiment outputs. The schema changes that prompted
    # this migration predate these experiment captures, so the literal
    # has to be rewritten here too. Explicit list; new experiments
    # default to the post-migration literal and don't need entries.
    for name in (
        "experiment_ablation.json",
        "experiment_contextual.json",
        "experiment_retrieval_precision.json",
    ):
        p = DATA / name
        if p.exists():
            yield p


def _migrate_one(value: Any, ctx_path: str) -> tuple[Any, int]:
    """Walk a JSON document and rewrite every "narrator": "esther" to
    "narrator": "first_person". Returns (new_value, replacements).

    Detects any other unexpected narrator value and logs a warning —
    won't rewrite it. Future-proofs against silent literal drift."""
    replacements = 0

    def walk(node: Any, path: str) -> Any:
        nonlocal replacements
        if isinstance(node, dict):
            out: dict[str, Any] = {}
            for k, v in node.items():
                if k == "narrator" and isinstance(v, str):
                    if v == OLD_LITERAL:
                        out[k] = NEW_LITERAL
                        replacements += 1
                    elif v in VALID_AFTER:
                        out[k] = v
                    else:
                        logger.warning(
                            "%s%s: unexpected narrator literal %r — left alone",
                            ctx_path, path, v,
                        )
                        out[k] = v
                else:
                    out[k] = walk(v, f"{path}.{k}")
            return out
        if isinstance(node, list):
            return [walk(item, f"{path}[{i}]") for i, item in enumerate(node)]
        return node

    return walk(value, ""), replacements


def _atomic_write(path: Path, data: Any) -> None:
    """Write JSON to `path` via a same-directory tmp file + rename so
    the destination is never observed in a partially-written state."""
    tmp = path.with_suffix(path.suffix + ".migrate.tmp")
    text = json.dumps(data, indent=2, ensure_ascii=False)
    tmp.write_text(text + "\n" if not text.endswith("\n") else text)
    os.replace(tmp, path)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would change; do not write.",
    )
    args = parser.parse_args()

    total_files = 0
    files_changed = 0
    total_replacements = 0

    for path in _candidate_files():
        total_files += 1
        rel = path.relative_to(ROOT)
        try:
            doc = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            logger.error("%s: JSON parse failed: %s — skipped", rel, exc)
            continue

        new_doc, n = _migrate_one(doc, str(rel))
        if n == 0:
            continue
        files_changed += 1
        total_replacements += n
        if args.dry_run:
            logger.info("DRY-RUN  %s: %d replacement(s)", rel, n)
        else:
            _atomic_write(path, new_doc)
            logger.info("WROTE    %s: %d replacement(s)", rel, n)

    logger.info(
        "Scanned %d files; %s %d files; %d total replacements.",
        total_files,
        "would change" if args.dry_run else "changed",
        files_changed,
        total_replacements,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
