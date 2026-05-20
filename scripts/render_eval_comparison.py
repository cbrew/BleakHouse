"""Render an eval run as a side-by-side markdown comparison for human eyes.

Walks data/eval/<run_id>/*.json, joins each candidate's per-paragraph
enrichments against the source passages, and writes a markdown file
per chapter showing the raw paragraph text plus each candidate's
enrichment in a compact summary table.

Output: data/eval/<run_id>/comparison/<novel>__<chapter>.md

Usage:
    uv run python scripts/render_eval_comparison.py --run-id v5_n1_smoke
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DATA = REPO_ROOT / "data"


def _load_chapter_passages(novel: str, chapter_id: str) -> list[dict]:
    """Load passages_enriched.json for one chapter (sorted by paragraph_index)."""
    path = DATA / "novels" / novel / "passages_enriched.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text())
    return sorted(
        [p for p in raw if p["chapter_id"] == chapter_id],
        key=lambda p: p["paragraph_index"],
    )


def _enrich_lines(e: dict | None) -> list[str]:
    """Render a FieldReportEnrichment dict as 4-5 markdown lines."""
    if e is None:
        return ["_(no output / failed)_"]
    lines: list[str] = []
    lines.append(
        f"- **interest:** {e.get('interest_score')} | "
        f"**narrator:** {e.get('narrator')} | "
        f"**plot:** {e.get('plot_function')} | "
        f"**accessibility:** {e.get('accessibility')} | "
        f"**quotability:** {e.get('quotability')}"
    )
    chars = e.get('characters_present') or []
    speaking = e.get('characters_speaking') or []
    lines.append(
        f"- **characters:** {', '.join(chars) if chars else '_none_'}"
        + (f" — *speaking:* {', '.join(speaking)}" if speaking else "")
    )
    lines.append(
        f"- **themes:** {', '.join(e.get('themes') or []) or '_none_'} | "
        f"**register:** {', '.join(e.get('emotional_register') or []) or '_none_'}"
    )
    summary = e.get('summary') or ''
    lines.append(f"- **summary:** {summary}")
    bq = e.get('best_quote')
    if bq:
        lines.append(f"- **best_quote:** {bq}")
    interest_rat = e.get('interest_rationale')
    if interest_rat:
        lines.append(f"- **rationale:** {interest_rat}")
    prov = {
        k.removeprefix("prov_"): v for k, v in e.items()
        if k.startswith("prov_") and v not in (None, "none")
    }
    if prov:
        provs = ", ".join(f"{k}={v}" for k, v in prov.items())
        lines.append(f"- **provisions:** {provs}")
    return lines


def render_chapter_md(
    *, novel: str, chapter_id: str, chapter_title: str,
    passages: list[dict],
    candidates_results: dict[str, dict],
    per_candidate_meta: dict[str, dict],
) -> str:
    """Build markdown for one chapter."""
    out: list[str] = []
    out.append(f"# {novel} / {chapter_id}: {chapter_title}")
    out.append("")
    out.append(f"**{len(passages)} paragraphs** | candidates: "
               + ", ".join(f"`{c}`" for c in candidates_results.keys()))
    out.append("")

    # Top-level metrics summary table
    out.append("## Per-candidate summary (this chapter)")
    out.append("")
    out.append("| candidate | shape | schema | cov | wall | cost | cache_read |")
    out.append("|---|---|---|---|---|---|---|")
    for cand, meta in per_candidate_meta.items():
        cache = meta.get("cache_read_tokens")
        cache_disp = f"{cache}" if cache is not None else "—"
        out.append(
            f"| `{cand}` | {meta.get('call_shape', '?')} | "
            f"{meta.get('schema_valid'):.2f} | "
            f"{meta.get('paragraph_coverage'):.2f} | "
            f"{meta.get('elapsed_seconds', 0):.1f}s | "
            f"${meta.get('cost_usd', 0):.4f} | {cache_disp} |"
        )
    out.append("")

    # Per-paragraph
    out.append("## Paragraphs")
    out.append("")
    for p in passages:
        idx = p["paragraph_index"]
        text = p["text"].strip()
        out.append(f"### P{idx}")
        out.append("")
        out.append("> " + text.replace("\n", "\n> "))
        out.append("")
        # Haiku baseline from passages_enriched.json (always)
        baseline = p.get("enrichment")
        if baseline:
            out.append(f"**baseline-on-disk (Haiku, existing per_chapter run):**")
            for line in _enrich_lines(baseline):
                out.append(line)
            out.append("")
        # Each candidate this eval produced
        for cand, results in candidates_results.items():
            enr = results.get(str(idx)) if results else None
            label = f"**{cand}** ({per_candidate_meta[cand].get('call_shape')}):"
            if enr is None:
                out.append(f"{label} _missing / failed_")
                out.append("")
                continue
            # candidate dicts in the eval are FieldReportEnrichment shape
            # (per_paragraph path) OR ParagraphEnrichment shape with
            # nested enrichment (per_chapter parse_candidate_output)
            if "enrichment" in enr and isinstance(enr["enrichment"], dict):
                enr_dict = enr["enrichment"]
            else:
                enr_dict = enr
            out.append(label)
            for line in _enrich_lines(enr_dict):
                out.append(line)
            out.append("")
    return "\n".join(out) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-id", required=True)
    args = p.parse_args()

    run_dir = DATA / "eval" / args.run_id
    if not run_dir.exists():
        raise SystemExit(f"no such run: {run_dir}")

    # Collect all candidate result files (skip summary)
    candidate_files = sorted(run_dir.glob("*.json"))
    candidate_files = [f for f in candidate_files if f.stem != "summary"]
    if not candidate_files:
        raise SystemExit(f"no candidate files found in {run_dir}")

    # Group results by chapter
    # chapter_key -> {candidate: per_chapter_meta_dict}
    # chapter_key -> {candidate: candidate_enrichments dict}
    chapters: dict[tuple[str, str], dict] = {}
    for cf in candidate_files:
        d = json.loads(cf.read_text())
        cand_name = cf.stem
        for pc in d.get("per_chapter", []):
            key = (pc["novel"], pc["chapter_id"])
            chapters.setdefault(key, {"meta": {}, "enrichments": {}})
            chapters[key]["meta"][cand_name] = pc
            chapters[key]["enrichments"][cand_name] = pc.get("candidate_enrichments") or {}

    out_dir = run_dir / "comparison"
    out_dir.mkdir(exist_ok=True)

    for (novel, chapter_id), info in chapters.items():
        passages = _load_chapter_passages(novel, chapter_id)
        if not passages:
            print(f"  skip {novel}/{chapter_id} (passages not found)")
            continue
        chapter_title = passages[0].get("chapter_title", "")
        md = render_chapter_md(
            novel=novel, chapter_id=chapter_id, chapter_title=chapter_title,
            passages=passages,
            candidates_results=info["enrichments"],
            per_candidate_meta=info["meta"],
        )
        out_path = out_dir / f"{novel}__{chapter_id}.md"
        out_path.write_text(md)
        print(f"  wrote {out_path}")

    print(f"\nDone. Open the .md files in {out_dir} to inspect side-by-side.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
