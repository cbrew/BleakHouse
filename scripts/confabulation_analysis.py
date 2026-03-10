#!/usr/bin/env python3
"""Confabulation deep-dive: find the 5 closest source passages for each fabricated quote.

For each of the ~500 true confabulations identified by quote_audit.py, this script:
1. Searches the full Bleak House text for the 5 best fuzzy matches
2. Reports by expert × condition who fabricated what and when
3. Classifies confabulation type (blend, paraphrase, invention, misattribution)

Reuses the n-gram index and fuzzy matching from quote_audit.py.

Usage:
    uv run python scripts/confabulation_analysis.py [--top-k 5]
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

# Import shared infrastructure from quote_audit
sys.path.insert(0, str(Path(__file__).parent))
from quote_audit import (  # noqa: E402
    CorpusIndex,
    NGRAM_SIZE,
    REPORT_DIR,
    _best_substring_ratio,
    _clean_quote_text,
    _extract_subquotes,
    load_bleak_house_text,
    normalise,
)

DATA_DIR = Path("data")
RUNS_DIR = DATA_DIR / "runs"
OUTPUT_DIR = REPORT_DIR / "confabulation_detail"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class NearMatch:
    """A candidate source passage match."""

    chapter_id: str
    ratio: float
    snippet: str  # original (un-normalised) text from source
    offset: int  # char offset in normalised chapter text


@dataclass
class ConfabRecord:
    """A confabulation with its top-k near matches."""

    run_id: str
    pipeline: str
    speaker: str
    segment: str
    sentence_type: str
    passage_ref: str
    quote_text: str
    match_ratio: float  # best ratio from original audit
    near_matches: list[NearMatch] = field(default_factory=list)
    confab_type: str = ""  # blend, paraphrase, invention, misattribution


# ---------------------------------------------------------------------------
# Expert extraction from run config or episode
# ---------------------------------------------------------------------------


EXPERT_PRESETS = {
    "sir_edmund": "Edmund Leigh",
    "dr_rosen": "Daniel Rosen",
    "trevelyan": "Oliver Trevelyan",
}


def get_panel_experts(run_id: str) -> dict[str, str]:
    """Try to load expert assignments from config.json for a run."""
    config_path = RUNS_DIR / run_id / "config.json"
    if config_path.exists():
        config = json.load(config_path.open())
        return config.get("experts", {})
    return {}


# ---------------------------------------------------------------------------
# Top-K matching
# ---------------------------------------------------------------------------


def find_top_k_matches(
    quote_text: str,
    passage_ref: str | None,
    corpus: CorpusIndex,
    k: int = 5,
) -> list[NearMatch]:
    """Find the k best matching regions in the source text.

    Strategy:
    1. Try full quote, cleaned quote, and sub-quotes
    2. For each variant, gather candidates from n-gram index
    3. Also do a brute-force scan of all chapters for zero-ngram-hit quotes
    4. Score all candidates, deduplicate, return top k
    """
    candidates_q: list[str] = []
    full_norm = normalise(quote_text)
    candidates_q.append(full_norm)

    cleaned = _clean_quote_text(quote_text)
    cleaned_norm = normalise(cleaned)
    if cleaned_norm != full_norm and len(cleaned_norm) >= 15:
        candidates_q.append(cleaned_norm)

    for subq in _extract_subquotes(quote_text):
        sub_norm = normalise(subq)
        if sub_norm not in candidates_q and len(sub_norm) >= 15:
            candidates_q.append(sub_norm)

    # Collect all scored regions: (ratio, chapter, offset, snippet)
    all_scored: list[tuple[float, str, int, str]] = []
    seen_regions: set[tuple[str, int]] = set()  # deduplicate by (chapter, offset_bucket)

    for q_norm in candidates_q:
        q_len = len(q_norm)

        # Phase 1: n-gram indexed candidates (up to 40 regions)
        regions = corpus.find_candidates(q_norm, passage_ref)
        for cid, start, end in regions[:40]:
            bucket = (cid, start // 200)
            if bucket in seen_regions:
                continue
            seen_regions.add(bucket)

            region = corpus.normalised[cid][start:end]
            ratio, offset = _best_substring_ratio(q_norm, region)

            # Extract original snippet
            orig = corpus.chapters[cid]
            snip_start = max(0, start + offset - 10)
            snip_end = min(len(orig), snip_start + q_len + 60)
            snippet = orig[snip_start:snip_end].strip()

            all_scored.append((ratio, cid, start + offset, snippet))

        # Phase 2: brute-force for quotes with few n-gram hits
        # Only if we got < 3 candidates from the index (likely novel fabrication)
        if len(all_scored) < 3:
            for cid, text in corpus.normalised.items():
                # Sliding window with large step
                step = max(50, q_len // 3)
                for pos in range(0, len(text) - q_len, step):
                    bucket = (cid, pos // 200)
                    if bucket in seen_regions:
                        continue
                    seen_regions.add(bucket)

                    window = text[pos : pos + q_len + q_len // 4]
                    ratio = SequenceMatcher(None, q_norm, window).ratio()
                    if ratio > 0.30:
                        orig = corpus.chapters[cid]
                        snip_start = max(0, pos - 10)
                        snip_end = min(len(orig), pos + q_len + 60)
                        snippet = orig[snip_start:snip_end].strip()
                        all_scored.append((ratio, cid, pos, snippet))

    # Sort by ratio descending, deduplicate overlapping snippets, take top k
    all_scored.sort(key=lambda x: -x[0])
    results: list[NearMatch] = []
    used_snippets: set[str] = set()
    for ratio, cid, offset, snippet in all_scored:
        # Deduplicate near-identical snippets
        snip_key = snippet[:80].lower()
        if snip_key in used_snippets:
            continue
        used_snippets.add(snip_key)
        results.append(NearMatch(
            chapter_id=cid,
            ratio=ratio,
            snippet=snippet[:300],
            offset=offset,
        ))
        if len(results) >= k:
            break

    return results


# ---------------------------------------------------------------------------
# Confabulation type classification
# ---------------------------------------------------------------------------

# Patterns that suggest specific confabulation types
_RE_ARCHAIC = re.compile(
    r"\b(thou|thee|thy|hath|doth|wherefore|methinks|'tis|prithee)\b",
    re.IGNORECASE,
)


def classify_confabulation(
    quote_text: str, near_matches: list[NearMatch]
) -> str:
    """Classify a confabulation into one of four types.

    - blend: top match ratio >= 0.45, suggesting the LLM combined/modified real text
    - paraphrase: ratio 0.30-0.45, capturing the gist but not the words
    - misattribution: contains archaic/Dickensian language but no close match
      (the LLM generated plausible-sounding Dickens)
    - invention: ratio < 0.30, no real source — pure fabrication
    """
    best_ratio = near_matches[0].ratio if near_matches else 0.0

    if best_ratio >= 0.45:
        return "blend"
    if best_ratio >= 0.30:
        return "paraphrase"
    if _RE_ARCHAIC.search(quote_text):
        return "misattribution"
    # Check if it sounds like it's trying to be Dickens
    # (elaborate syntax, long sentences, specific character names)
    dickens_chars = re.compile(
        r"\b(Esther|Jarndyce|Dedlock|Tulkinghorn|Jo\b|Krook|Guppy|Snagsby|"
        r"Skimpole|Bucket|Ada|Richard|Woodcourt|Nemo|Lady Dedlock)\b"
    )
    if dickens_chars.search(quote_text) and best_ratio < 0.30:
        return "invention"

    return "invention"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Confabulation deep-dive analysis")
    parser.add_argument("--top-k", type=int, default=5, help="Number of near matches per quote")
    args = parser.parse_args()

    # Load confabulations from the unverified classification CSV
    confab_rows: list[dict[str, str]] = []
    with open(REPORT_DIR / "unverified_classification.csv") as f:
        for row in csv.DictReader(f):
            if row["category"] == "confabulation":
                confab_rows.append(row)
    print(f"Loaded {len(confab_rows)} confabulations")

    # Cross-reference with quote_details.csv for speaker/segment info
    detail_index: dict[tuple[str, str], dict[str, str]] = {}
    with open(REPORT_DIR / "quote_details.csv") as f:
        for row in csv.DictReader(f):
            key = (row["run_id"], row["quote_text"][:100])
            detail_index[key] = row

    # Build corpus index
    print("Building corpus index...")
    chapters = load_bleak_house_text()
    normalised_chapters = {cid: normalise(text) for cid, text in chapters.items()}
    corpus = CorpusIndex(chapters, normalised_chapters)
    print(f"  {len(chapters)} chapters, {len(corpus.index):,} unique {NGRAM_SIZE}-grams")

    # Process each confabulation
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    records: list[ConfabRecord] = []

    for i, crow in enumerate(confab_rows):
        run_id = crow["run_id"]
        pipeline = crow["pipeline"]
        quote_text = crow["quote_text"]

        # Look up speaker info from details
        detail = detail_index.get((run_id, quote_text[:100]), {})
        speaker = detail.get("speaker", "unknown")
        segment = detail.get("segment", "")
        stype = detail.get("sentence_type", "")
        pref = detail.get("passage_ref", "")
        match_ratio = float(crow["match_ratio"])

        # Find top-k matches
        matches = find_top_k_matches(quote_text, pref or None, corpus, k=args.top_k)

        # Classify confabulation type
        ctype = classify_confabulation(quote_text, matches)

        rec = ConfabRecord(
            run_id=run_id,
            pipeline=pipeline,
            speaker=speaker,
            segment=segment,
            sentence_type=stype,
            passage_ref=pref,
            quote_text=quote_text,
            match_ratio=match_ratio,
            near_matches=matches,
            confab_type=ctype,
        )
        records.append(rec)

        if (i + 1) % 50 == 0:
            print(f"  Processed {i + 1}/{len(confab_rows)} confabulations...")

    print(f"  Done: {len(records)} confabulations analysed")

    # --- Write detailed CSV ---
    detail_path = OUTPUT_DIR / "confabulation_near_matches.csv"
    with detail_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "run_id", "pipeline", "speaker", "segment", "confab_type",
            "quote_text", "original_ratio",
            "match_rank", "match_chapter", "match_ratio", "match_snippet",
        ])
        for rec in records:
            for rank, nm in enumerate(rec.near_matches, 1):
                w.writerow([
                    rec.run_id, rec.pipeline, rec.speaker, rec.segment,
                    rec.confab_type, rec.quote_text[:300], f"{rec.match_ratio:.3f}",
                    rank, nm.chapter_id, f"{nm.ratio:.3f}", nm.snippet[:300],
                ])
            # If no matches at all, still write one row
            if not rec.near_matches:
                w.writerow([
                    rec.run_id, rec.pipeline, rec.speaker, rec.segment,
                    rec.confab_type, rec.quote_text[:300], f"{rec.match_ratio:.3f}",
                    1, "", "0.000", "",
                ])
    print(f"\nDetailed near matches: {detail_path}")

    # --- Aggregate by expert × condition ---
    print(f"\n{'=' * 80}")
    print("CONFABULATIONS BY EXPERT × PIPELINE")
    print("=" * 80)

    expert_pipeline: dict[tuple[str, str], list[ConfabRecord]] = defaultdict(list)
    for rec in records:
        expert_pipeline[(rec.speaker, rec.pipeline)].append(rec)

    # Summary table
    experts = sorted({r.speaker for r in records})
    pipelines = ["transport", "embedding", "rag", "no_passages", "random"]

    header = f"{'Expert':<22}" + "".join(f" {p:>13}" for p in pipelines) + "  Total"
    print(header)
    print("-" * len(header))
    for expert in experts:
        parts = [f"{expert:<22}"]
        total = 0
        for p in pipelines:
            n = len(expert_pipeline.get((expert, p), []))
            total += n
            parts.append(f" {n:>13}" if n > 0 else f" {'—':>12}")
        parts.append(f"  {total:>5}")
        print("".join(parts))

    # Totals row
    parts = [f"{'TOTAL':<22}"]
    grand = 0
    for p in pipelines:
        n = sum(len(expert_pipeline.get((e, p), [])) for e in experts)
        grand += n
        parts.append(f" {n:>13}")
    parts.append(f"  {grand:>5}")
    print("-" * len(header))
    print("".join(parts))

    # --- Confabulation type breakdown ---
    print(f"\n{'=' * 80}")
    print("CONFABULATION TYPE BREAKDOWN")
    print("=" * 80)

    type_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for rec in records:
        type_counts[rec.pipeline][rec.confab_type] += 1

    ctypes = ["blend", "paraphrase", "misattribution", "invention"]
    header = f"{'Pipeline':<15}" + "".join(f" {ct:>15}" for ct in ctypes) + "  Total"
    print(header)
    print("-" * len(header))
    for p in pipelines:
        parts = [f"{p:<15}"]
        total = 0
        for ct in ctypes:
            n = type_counts[p][ct]
            total += n
            parts.append(f" {n:>15}")
        parts.append(f"  {total:>5}")
        print("".join(parts))

    # --- Confab type by expert ---
    print(f"\n{'=' * 80}")
    print("CONFABULATION TYPE BY EXPERT")
    print("=" * 80)

    expert_types: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for rec in records:
        expert_types[rec.speaker][rec.confab_type] += 1

    header = f"{'Expert':<22}" + "".join(f" {ct:>15}" for ct in ctypes) + "  Total"
    print(header)
    print("-" * len(header))
    for expert in experts:
        parts = [f"{expert:<22}"]
        total = 0
        for ct in ctypes:
            n = expert_types[expert][ct]
            total += n
            parts.append(f" {n:>15}")
        parts.append(f"  {total:>5}")
        print("".join(parts))

    # --- Best near-match ratio distribution ---
    print(f"\n{'=' * 80}")
    print("BEST NEAR-MATCH RATIO DISTRIBUTION (top-1 match for each confabulation)")
    print("=" * 80)

    ratio_buckets: dict[str, list[float]] = defaultdict(list)
    for rec in records:
        best = rec.near_matches[0].ratio if rec.near_matches else 0.0
        ratio_buckets[rec.pipeline].append(best)

    for p in pipelines:
        ratios = sorted(ratio_buckets.get(p, []))
        if not ratios:
            continue
        n = len(ratios)
        median = ratios[n // 2]
        mean = sum(ratios) / n
        p25 = ratios[n // 4]
        p75 = ratios[3 * n // 4]
        print(f"  {p:<15}: n={n:>3}, mean={mean:.3f}, median={median:.3f}, "
              f"p25={p25:.3f}, p75={p75:.3f}")

    # --- Write per-expert summary CSV ---
    summary_path = OUTPUT_DIR / "expert_pipeline_summary.csv"
    with summary_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["expert", "pipeline", "n_confabulations",
                     "n_blend", "n_paraphrase", "n_misattribution", "n_invention",
                     "mean_best_ratio", "median_best_ratio"])
        for expert in experts:
            for p in pipelines:
                recs = expert_pipeline.get((expert, p), [])
                if not recs:
                    continue
                ratios = [
                    r.near_matches[0].ratio if r.near_matches else 0.0
                    for r in recs
                ]
                ratios.sort()
                n = len(ratios)
                w.writerow([
                    expert, p, n,
                    sum(1 for r in recs if r.confab_type == "blend"),
                    sum(1 for r in recs if r.confab_type == "paraphrase"),
                    sum(1 for r in recs if r.confab_type == "misattribution"),
                    sum(1 for r in recs if r.confab_type == "invention"),
                    f"{sum(ratios) / n:.3f}",
                    f"{ratios[n // 2]:.3f}",
                ])
    print(f"\nExpert summary: {summary_path}")

    # --- Show most interesting examples per type ---
    for ctype in ctypes:
        typed = [r for r in records if r.confab_type == ctype]
        if not typed:
            continue
        # For blends, show highest-ratio (most instructive)
        # For inventions, show lowest-ratio (most egregious)
        if ctype in ("blend", "paraphrase"):
            typed.sort(key=lambda r: -(r.near_matches[0].ratio if r.near_matches else 0))
        else:
            typed.sort(key=lambda r: (r.near_matches[0].ratio if r.near_matches else 0))

        print(f"\n{'=' * 80}")
        print(f"EXAMPLES: {ctype.upper()} (n={len(typed)}, showing top 8)")
        print("=" * 80)
        for rec in typed[:8]:
            best = rec.near_matches[0] if rec.near_matches else None
            best_ratio = best.ratio if best else 0.0
            print(f"\n  [{rec.pipeline}] {rec.speaker} in {rec.run_id}")
            print(f"    Quote:  {rec.quote_text[:150]}")
            if best:
                print(f"    Best match (ratio={best_ratio:.3f}, {best.chapter_id}):")
                print(f"      {best.snippet[:150]}")
            for nm in rec.near_matches[1:3]:
                print(f"    Match #{rec.near_matches.index(nm)+1} "
                      f"(ratio={nm.ratio:.3f}, {nm.chapter_id}):")
                print(f"      {nm.snippet[:150]}")

    print(f"\nAll outputs in: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
