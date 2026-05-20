"""Re-enrich paragraphs that exceed the new bounded-schema caps.

Walks data/novels/*/passages_enriched.json, finds enrichments whose
list fields exceed the post-2026-05-13 caps (characters_present=8,
characters_speaking=4, emotional_register=4, themes=8), and re-calls
Haiku via the seam with the per_paragraph shape + full chapter
context. Replaces the failing enrichment in place and writes back.

Idempotent: only touches violators. Re-runnable. Backs up each
novel's file to .pre_overcap_migration before first write.

Usage:
    uv run python scripts/migrate_overcap_enrichments.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

from enrichment.llm import GenerationRequest, generate, settings  # noqa: E402
from enrichment.llm.types import ModelSpec  # noqa: E402
from enrichment.novel_prompts import build_enrichment_prompt  # noqa: E402
from enrichment.llm.schemas import FieldReportEnrichment, ParagraphEnrichment  # noqa: E402
from enrichment.submit_passages_enriched import format_chapter_text  # noqa: E402

DATA = REPO_ROOT / "data"

# Caps must match enrichment/schemas.py (kept in sync by hand).
CAPS: dict[str, int] = {
    "characters_present": 8,
    "characters_speaking": 4,
    "emotional_register": 4,
    "themes": 8,
}

HAIKU_SPEC = ModelSpec(
    provider="anthropic",
    model="claude-haiku-4-5-20251001",
    hosting="anthropic",
)


def is_violator(enr: dict) -> list[str]:
    """Return list of field names that exceed the cap. Empty list if clean."""
    bad: list[str] = []
    for field, cap in CAPS.items():
        v = enr.get(field, [])
        if isinstance(v, list) and len(v) > cap:
            bad.append(f"{field}({len(v)})")
    return bad


def re_enrich_paragraph(
    *, novel: str, chapter_id: str, chapter_title: str,
    chapter_passages: list[dict], target_paragraph: dict,
) -> dict | None:
    """Re-call Haiku for one paragraph, with chapter as cached context.
    Returns the FieldReportEnrichment dict on success, None on failure.
    """
    system_block = (
        f"{build_enrichment_prompt(novel)}\n\n<document>\n"
        f"Chapter: {chapter_id} - {chapter_title}\n\n"
        f"{format_chapter_text(chapter_passages)}\n</document>"
    )
    idx = target_paragraph["paragraph_index"]
    user_msg = (
        f"Return one `ParagraphEnrichment` object for paragraph "
        f"[P{idx}] of the chapter above. The enrichment must describe "
        f"ONLY this paragraph:\n\n"
        f"[P{idx}] {target_paragraph['text']}"
    )
    schema = ParagraphEnrichment.model_json_schema()
    result = generate(GenerationRequest(
        task="passage_enrichment",
        system=system_block,
        user=user_msg,
        max_tokens=2048,
        json_schema=schema,
        temperature=0.0,
        cache_system=True,
    ))
    try:
        obj = ParagraphEnrichment.model_validate_json(result.text)
        return obj.enrichment.model_dump()
    except Exception as exc:
        print(f"    parse failed: {type(exc).__name__}: {str(exc)[:120]}")
        return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true",
                   help="List violators without re-calling or writing.")
    p.add_argument("--novel", type=str, default=None,
                   help="Restrict to one novel.")
    args = p.parse_args()

    load_dotenv()
    settings.register_task("passage_enrichment", HAIKU_SPEC)

    novels_dir = DATA / "novels"
    novel_dirs = sorted(novels_dir.iterdir())
    if args.novel:
        novel_dirs = [d for d in novel_dirs if d.name == args.novel]

    total_violators = 0
    total_fixed = 0
    total_failed = 0
    total_cost = 0.0

    for nd in novel_dirs:
        path = nd / "passages_enriched.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text())

        # Group by chapter for cache reuse
        by_chapter: dict[str, list[dict]] = {}
        for p_ in data:
            by_chapter.setdefault(p_["chapter_id"], []).append(p_)
        for ch_list in by_chapter.values():
            ch_list.sort(key=lambda x: x["paragraph_index"])

        # Find violators in this novel
        novel_violators: list[tuple[str, dict]] = []
        for chapter_id, ch_paras in by_chapter.items():
            for p_ in ch_paras:
                enr = p_.get("enrichment")
                if not enr:
                    continue
                bad = is_violator(enr)
                if bad:
                    novel_violators.append((chapter_id, p_))

        if not novel_violators:
            continue

        print(f"\n=== {nd.name}: {len(novel_violators)} violators ===")
        for chapter_id, p_ in novel_violators:
            bad = is_violator(p_["enrichment"])
            print(f"  {chapter_id}:p{p_['paragraph_index']} — {', '.join(bad)}")
        total_violators += len(novel_violators)

        if args.dry_run:
            continue

        # Back up before modifying
        backup = path.with_suffix(".json.pre_overcap_migration")
        if not backup.exists():
            shutil.copy(path, backup)
            print(f"  backed up to {backup.name}")

        # Re-enrich each violator
        # Group violators by chapter for cache locality.
        violators_by_chapter: dict[str, list[dict]] = {}
        for chapter_id, p_ in novel_violators:
            violators_by_chapter.setdefault(chapter_id, []).append(p_)

        for chapter_id, viols in violators_by_chapter.items():
            ch_paras = by_chapter[chapter_id]
            chapter_title = ch_paras[0].get("chapter_title", "")
            for target in viols:
                idx = target["paragraph_index"]
                t0 = time.time()
                try:
                    new_enr = re_enrich_paragraph(
                        novel=nd.name, chapter_id=chapter_id,
                        chapter_title=chapter_title,
                        chapter_passages=ch_paras,
                        target_paragraph=target,
                    )
                except Exception as exc:
                    print(f"    {chapter_id}:p{idx} — call failed: "
                          f"{type(exc).__name__}: {str(exc)[:80]}")
                    total_failed += 1
                    continue
                elapsed = time.time() - t0

                if new_enr is None:
                    total_failed += 1
                    continue

                # Validate the new enrichment against the new schema
                try:
                    FieldReportEnrichment.model_validate(new_enr)
                except Exception as exc:
                    print(f"    {chapter_id}:p{idx} — new enrichment "
                          f"FAILS validation: {str(exc)[:120]}")
                    total_failed += 1
                    continue

                # Find target in `data` (passages list) and replace
                for entry in data:
                    if (entry["chapter_id"] == chapter_id
                            and entry["paragraph_index"] == idx):
                        entry["enrichment"] = new_enr
                        break
                total_fixed += 1
                print(f"    {chapter_id}:p{idx} fixed in {elapsed:.1f}s")

        # Atomic write
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(path)
        print(f"  wrote {path}")

    print()
    print(f"Total violators found: {total_violators}")
    if not args.dry_run:
        print(f"Total re-enriched:     {total_fixed}")
        print(f"Total failed:          {total_failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
