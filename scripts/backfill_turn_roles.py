"""Backfill canonical turn roles in run JSON files.

Pre-2026-03-31 runs were generated before fix_turn_roles landed
(commit 50dc4595), so per-turn role labels can drift to whatever
the LLM emitted (e.g. Sarah Chen tagged 'literary_critic' in some
turns, 'computer_scientist' in others — BleakHouse-e9m). Persona
role strings have also been renamed since then (e.g. marxist_critic
→ marxist_cultural_historian). Both kinds of drift live in three
places per run:

  - phase3_episode.json     segments[].turns[].role
  - audio/manifest.json     experts[].role, segments[].turns[].role
  - audio/shards.json       experts[].role, shards[].role

This script rewrites every speaker's role to the canonical persona
role keyed on speaker name.

Default mode targets within-run inconsistency only (the e9m bug):
a speaker labelled with two or more different roles in the same
file. Runs that are internally consistent but use older persona
role strings are left alone unless --include-stale-personas is
given.

Idempotent: re-running on already-clean files is a no-op.

Usage:
    uv run python scripts/backfill_turn_roles.py --dry-run
    uv run python scripts/backfill_turn_roles.py
    uv run python scripts/backfill_turn_roles.py --run bh_nop_interdisciplinary_hostprep
    uv run python scripts/backfill_turn_roles.py --include-stale-personas
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from enrichment.personas import (
    ALTERNATIVE_PERSONAS,
    DEFAULT_PERSONAS,
)
RUNS_DIR = Path("data/runs")

FIXED_ROLES = {"Host": "host", "Narrator": "narrator"}


def name_to_role() -> dict[str, str]:
    out = {p.name: p.role for p in list(DEFAULT_PERSONAS) + list(ALTERNATIVE_PERSONAS.values())}
    out.update(FIXED_ROLES)
    return out


def _walk_turns(doc: dict):
    """Yield turn-shaped dicts ({'speaker', 'role', ...}) wherever they live."""
    for seg in doc.get("segments", []):
        for t in seg.get("turns", []):
            if "speaker" in t and "role" in t:
                yield t
    for s in doc.get("shards", []):
        if "speaker" in s and "role" in s:
            yield s


def _walk_experts(doc: dict):
    """Yield expert-shaped dicts ({'name', 'role', ...}) at the top level."""
    for e in doc.get("experts") or []:
        if "name" in e and "role" in e:
            yield e


def fix_doc(doc: dict, n2r: dict[str, str]) -> list[tuple[str, str, str]]:
    """Rewrite role fields in-place. Returns (name, old_role, new_role) tuples."""
    changes: list[tuple[str, str, str]] = []
    for t in _walk_turns(doc):
        canonical = n2r.get(t["speaker"])
        if canonical is not None and t.get("role") != canonical:
            changes.append((t["speaker"], t.get("role", ""), canonical))
            t["role"] = canonical
    for e in _walk_experts(doc):
        canonical = n2r.get(e["name"])
        if canonical is not None and e.get("role") != canonical:
            changes.append((e["name"], e.get("role", ""), canonical))
            e["role"] = canonical
    return changes


def inconsistent_speakers(doc: dict) -> set[str]:
    """Speakers whose `role` varies within this doc."""
    seen: dict[str, set[str]] = {}
    for t in _walk_turns(doc):
        sp = t["speaker"]
        if sp in FIXED_ROLES:
            continue
        seen.setdefault(sp, set()).add(t.get("role", ""))
    return {sp for sp, rs in seen.items() if len(rs) > 1}


def process_file(path: Path, *, dry_run: bool, include_stale_personas: bool, n2r: dict[str, str]) -> int:
    raw = path.read_text()
    doc = json.loads(raw)
    inconsistent = inconsistent_speakers(doc)
    if not include_stale_personas and not inconsistent:
        return 0

    all_changes = fix_doc(doc, n2r)
    if not include_stale_personas:
        # Keep only changes for speakers that were inconsistent in this file;
        # revert the rest by reloading and applying selectively.
        kept = [c for c in all_changes if c[0] in inconsistent]
        if len(kept) != len(all_changes):
            doc = json.loads(raw)
            for t in _walk_turns(doc):
                if t["speaker"] in inconsistent:
                    canonical = n2r.get(t["speaker"])
                    if canonical is not None:
                        t["role"] = canonical
            for e in _walk_experts(doc):
                if e["name"] in inconsistent:
                    canonical = n2r.get(e["name"])
                    if canonical is not None:
                        e["role"] = canonical
        all_changes = kept

    if not all_changes:
        return 0

    rel = path.relative_to(RUNS_DIR.parent)
    print(f"{rel}: {len(all_changes)} role rewrite(s)")
    summary: dict[tuple[str, str, str], int] = {}
    for c in all_changes:
        summary[c] = summary.get(c, 0) + 1
    for (sp, old, new), n in sorted(summary.items()):
        print(f"  {sp}: {old!r} → {new!r} (×{n})")
    if not dry_run:
        path.write_text(json.dumps(doc, indent=2))
    return len(all_changes)


def candidate_paths(run_filter: str | None) -> list[Path]:
    out: list[Path] = []
    run_dirs = (
        [RUNS_DIR / run_filter] if run_filter else sorted(RUNS_DIR.iterdir())
    )
    for d in run_dirs:
        if not d.is_dir():
            continue
        for sub in ("phase3_episode.json", "audio/manifest.json", "audio/shards.json"):
            p = d / sub
            if p.exists():
                out.append(p)
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--run", help="process a single run dir name (default: all)")
    p.add_argument(
        "--include-stale-personas",
        action="store_true",
        help="Also rewrite files that are internally consistent but use older "
             "persona role strings (e.g. marxist_critic → marxist_cultural_historian)",
    )
    args = p.parse_args()

    n2r = name_to_role()
    targets = candidate_paths(args.run)

    total_changes = 0
    files_touched = 0
    for path in targets:
        n = process_file(
            path,
            dry_run=args.dry_run,
            include_stale_personas=args.include_stale_personas,
            n2r=n2r,
        )
        if n:
            total_changes += n
            files_touched += 1

    verb = "would change" if args.dry_run else "changed"
    print(f"\n{verb} {total_changes} role(s) across {files_touched} file(s)")


if __name__ == "__main__":
    main()
