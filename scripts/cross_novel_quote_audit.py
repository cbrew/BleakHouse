#!/usr/bin/env python3
"""Quote fidelity audit across all cross-novel runs.

Simplified version of quote_audit.py for the cross-novel experiment.
Each novel needs its own source text for verification. No spaCy, no n-gram
inverted index -- just straightforward substring + difflib fuzzy matching.

Output:
  reports/cross_novel_quote_audit/per_run_summary.csv
  reports/cross_novel_quote_audit/grounding_gap.csv
  Console: verification rates by novel x condition

Usage:
    uv run python scripts/cross_novel_quote_audit.py [--threshold 0.75]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from cross_novel_loader import (
    COND_PREFIXES,
    NOVELS_DIR,
    NOVEL_TITLES,
    discover_runs,
    load_episode,
    parse_run_name,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPORT_DIR = Path("reports/cross_novel_quote_audit")

# Inline quote regex: text between quotation marks, >= 8 words
INLINE_QUOTE_RE = re.compile(
    r'["\u201c]'  # opening quote
    r"([^\"'\u201d]{10,}?)"  # content
    r'["\u201d]',  # closing quote
    re.DOTALL,
)

MIN_INLINE_WORDS = 8


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ExtractedQuote:
    text: str
    source: str  # "tagged" or "inline"


@dataclass
class VerifiedQuote:
    text: str
    source: str
    verified: bool
    best_ratio: float


@dataclass
class RunResult:
    novel: str
    condition: str
    panel: str
    total_quotes: int = 0
    tagged_quotes: int = 0
    inline_quotes: int = 0
    verified_count: int = 0
    verification_rate: float = 0.0
    confabulation_count: int = 0


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------


def normalise(text: str) -> str:
    """Normalise text for comparison: NFKD, collapse whitespace, lowercase."""
    text = unicodedata.normalize("NFKD", text)
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2014", "--").replace("\u2013", "-")
    text = re.sub(r"\s+", " ", text)
    return text.lower().strip()


def strip_outer_quotes(text: str) -> str:
    """Remove surrounding quotation marks if present."""
    text = text.strip()
    if len(text) >= 2:
        if (text[0] in '"\u201c' and text[-1] in '"\u201d') or (
            text[0] in "'\u2018" and text[-1] in "'\u2019"
        ):
            text = text[1:-1].strip()
    return text


# ---------------------------------------------------------------------------
# Step 1: Build per-novel text index
# ---------------------------------------------------------------------------


def load_novel_text(novel_key: str) -> dict[str, str]:
    """Load novel source text grouped by chapter from passages_enriched.json.

    Returns dict[chapter_id, full_chapter_text].
    """
    path = NOVELS_DIR / novel_key / "passages_enriched.json"
    if not path.exists():
        print(f"  WARNING: {path} not found")
        return {}
    passages = json.loads(path.read_text())

    chapters: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for p in passages:
        cid = p["chapter_id"]
        chapters[cid].append((p["paragraph_index"], p["text"]))

    result = {}
    for cid, parts in chapters.items():
        parts.sort(key=lambda x: x[0])
        result[cid] = "\n".join(text for _, text in parts)
    return result


# ---------------------------------------------------------------------------
# Step 2: Extract quotes from episode
# ---------------------------------------------------------------------------


def extract_quotes(episode: dict) -> list[ExtractedQuote]:
    """Extract tagged and inline quotes from a phase3 episode."""
    quotes: list[ExtractedQuote] = []
    seen: set[str] = set()

    for segment in episode.get("segments", []):
        for turn in segment.get("turns", []):
            for utt in turn.get("utterances", []):
                text = utt.get("text", "")
                is_quote = utt.get("is_quote", False)
                stype = utt.get("sentence_type", "")
                quote_mode = utt.get("quote_mode", "none")

                # Tagged quotes
                if is_quote or stype == "quote_reading" or quote_mode == "reading":
                    clean = strip_outer_quotes(text)
                    if len(clean) >= 15:
                        norm = normalise(clean)
                        if norm not in seen:
                            seen.add(norm)
                            quotes.append(ExtractedQuote(text=clean, source="tagged"))

                # Inline quotes (from non-quote utterances)
                if not is_quote and stype != "quote_reading":
                    for m in INLINE_QUOTE_RE.finditer(text):
                        fragment = m.group(1).strip()
                        words = fragment.split()
                        if len(words) >= MIN_INLINE_WORDS:
                            norm = normalise(fragment)
                            if norm not in seen:
                                seen.add(norm)
                                quotes.append(
                                    ExtractedQuote(text=fragment, source="inline")
                                )

    return quotes


# ---------------------------------------------------------------------------
# Step 3: Verify quotes against source text
# ---------------------------------------------------------------------------


def verify_quote(
    quote: ExtractedQuote,
    chapters_normalised: dict[str, str],
    threshold: float,
) -> VerifiedQuote:
    """Verify a single quote against the novel's source text.

    1. Try exact substring match (normalised).
    2. Fall back to difflib.SequenceMatcher with windowed comparison.
    """
    q_norm = normalise(quote.text)
    q_len = len(q_norm)

    # Phase 1: exact substring
    for _cid, chapter_text in chapters_normalised.items():
        if q_norm in chapter_text:
            return VerifiedQuote(
                text=quote.text,
                source=quote.source,
                verified=True,
                best_ratio=1.0,
            )

    # Phase 2: fuzzy match with windowed SequenceMatcher
    best_ratio = 0.0
    for _cid, chapter_text in chapters_normalised.items():
        ch_len = len(chapter_text)
        if ch_len == 0:
            continue

        # Use SequenceMatcher to find the longest common substring,
        # then score a window around that alignment point.
        sm = SequenceMatcher(None, q_norm, chapter_text)
        match = sm.find_longest_match(0, q_len, 0, ch_len)
        if match.size == 0:
            continue

        # Extract a window around the match in the chapter
        centre = match.b + match.size // 2
        margin = q_len // 4
        window_start = max(0, centre - q_len // 2 - margin)
        window_end = min(ch_len, window_start + q_len + 2 * margin)
        window_start = max(0, window_end - q_len - 2 * margin)
        window = chapter_text[window_start:window_end]

        ratio = SequenceMatcher(None, q_norm, window).ratio()
        if ratio > best_ratio:
            best_ratio = ratio

        if best_ratio >= 0.95:
            break

    return VerifiedQuote(
        text=quote.text,
        source=quote.source,
        verified=best_ratio >= threshold,
        best_ratio=best_ratio,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cross-novel quote fidelity audit"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.75,
        help="Fuzzy match ratio threshold for verification (default: 0.75)",
    )
    args = parser.parse_args()

    # Discover runs
    runs = discover_runs()
    print(f"Found {len(runs)} cross-novel runs")

    # Collect novel keys that appear in runs
    novel_keys = sorted({nk for nk, _c, _p in runs})
    print(f"Novels: {', '.join(novel_keys)}")

    # Load and normalise source texts per novel
    print("\nLoading novel source texts...")
    novel_chapters: dict[str, dict[str, str]] = {}
    novel_chapters_norm: dict[str, dict[str, str]] = {}
    for nk in novel_keys:
        chapters = load_novel_text(nk)
        novel_chapters[nk] = chapters
        novel_chapters_norm[nk] = {
            cid: normalise(text) for cid, text in chapters.items()
        }
        total_chars = sum(len(t) for t in chapters.values())
        print(f"  {nk}: {len(chapters)} chapters, {total_chars:,} chars")

    # Process each run
    print("\nProcessing runs...")
    results: list[RunResult] = []

    for (novel_key, condition, panel_id), run_dir in sorted(runs.items()):
        episode = load_episode(run_dir)
        quotes = extract_quotes(episode)

        if not quotes:
            results.append(
                RunResult(novel=novel_key, condition=condition, panel=panel_id)
            )
            continue

        tagged = sum(1 for q in quotes if q.source == "tagged")
        inline = sum(1 for q in quotes if q.source == "inline")

        # Verify against this novel's source text
        ch_norm = novel_chapters_norm.get(novel_key, {})
        verified_quotes = [
            verify_quote(q, ch_norm, args.threshold) for q in quotes
        ]
        n_verified = sum(1 for vq in verified_quotes if vq.verified)
        rate = n_verified / len(verified_quotes) if verified_quotes else 0.0

        results.append(
            RunResult(
                novel=novel_key,
                condition=condition,
                panel=panel_id,
                total_quotes=len(quotes),
                tagged_quotes=tagged,
                inline_quotes=inline,
                verified_count=n_verified,
                verification_rate=rate,
                confabulation_count=len(quotes) - n_verified,
            )
        )
        run_name = run_dir.name
        print(
            f"  {run_name}: {len(quotes)} quotes "
            f"({tagged}T/{inline}I), "
            f"{n_verified}/{len(quotes)} verified ({rate:.0%})"
        )

    # ---------------------------------------------------------------------------
    # Output
    # ---------------------------------------------------------------------------

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # -- per_run_summary.csv --
    run_csv = REPORT_DIR / "per_run_summary.csv"
    with run_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "novel", "condition", "panel", "total_quotes", "tagged_quotes",
            "inline_quotes", "verified_count", "verification_rate",
            "confabulation_count",
        ])
        for r in sorted(results, key=lambda x: (x.novel, x.condition, x.panel)):
            w.writerow([
                r.novel, r.condition, r.panel, r.total_quotes,
                r.tagged_quotes, r.inline_quotes, r.verified_count,
                f"{r.verification_rate:.3f}", r.confabulation_count,
            ])
    print(f"\nPer-run summary: {run_csv}")

    # -- grounding_gap.csv --
    # Per novel: mean verification rate for transport, embedding, no_passages
    # grounding_gap = mean(transport, embedding) - no_passages
    novel_cond_rates: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for r in results:
        if r.total_quotes > 0:
            novel_cond_rates[r.novel][r.condition].append(r.verification_rate)

    gap_csv = REPORT_DIR / "grounding_gap.csv"
    with gap_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "novel", "transport_rate", "embedding_rate", "no_passages_rate",
            "grounding_gap",
        ])
        for nk in sorted(novel_cond_rates):
            rates = {}
            for cond in ("transport", "embedding", "no_passages"):
                vals = novel_cond_rates[nk].get(cond, [])
                rates[cond] = sum(vals) / len(vals) if vals else 0.0

            grounded_mean = (rates["transport"] + rates["embedding"]) / 2
            gap = grounded_mean - rates["no_passages"]

            w.writerow([
                nk,
                f"{rates['transport']:.3f}",
                f"{rates['embedding']:.3f}",
                f"{rates['no_passages']:.3f}",
                f"{gap:.3f}",
            ])
    print(f"Grounding gap: {gap_csv}")

    # -- Console: formatted table of verification rates by novel x condition --
    print(f"\n{'=' * 72}")
    print("VERIFICATION RATES BY NOVEL x CONDITION")
    print("=" * 72)

    conditions = ["transport", "embedding", "no_passages"]
    header = f"{'Novel':<25}" + "".join(f" {c:>14}" for c in conditions) + "   Gap"
    print(header)
    print("-" * len(header))

    for nk in sorted(novel_cond_rates):
        title = NOVEL_TITLES.get(nk, nk)
        parts = [f"{title:<25}"]
        rates = {}
        for cond in conditions:
            vals = novel_cond_rates[nk].get(cond, [])
            mean_rate = sum(vals) / len(vals) if vals else 0.0
            rates[cond] = mean_rate
            n_runs = len(vals)
            parts.append(f" {mean_rate:>6.1%} (n={n_runs:>2})")

        grounded_mean = (rates["transport"] + rates["embedding"]) / 2
        gap = grounded_mean - rates["no_passages"]
        parts.append(f" {gap:>+6.1%}")
        print("".join(parts))

    # -- Console: aggregate across all novels --
    print(f"\n{'=' * 72}")
    print("AGGREGATE ACROSS ALL NOVELS")
    print("=" * 72)

    agg: dict[str, dict[str, int]] = defaultdict(
        lambda: {"runs": 0, "total": 0, "tagged": 0, "inline": 0, "verified": 0}
    )
    for r in results:
        a = agg[r.condition]
        a["runs"] += 1
        a["total"] += r.total_quotes
        a["tagged"] += r.tagged_quotes
        a["inline"] += r.inline_quotes
        a["verified"] += r.verified_count

    header2 = (
        f"{'Condition':<15} {'Runs':>5} {'Total':>7} {'Tagged':>7} "
        f"{'Inline':>7} {'Verified':>9} {'Rate':>7}"
    )
    print(header2)
    print("-" * len(header2))
    for cond in conditions:
        a = agg[cond]
        rate = a["verified"] / a["total"] if a["total"] else 0.0
        print(
            f"{cond:<15} {a['runs']:>5} {a['total']:>7} {a['tagged']:>7} "
            f"{a['inline']:>7} {a['verified']:>9} {rate:>6.1%}"
        )

    # Overall grounding gap
    grounded_total = agg["transport"]["verified"] + agg["embedding"]["verified"]
    grounded_denom = agg["transport"]["total"] + agg["embedding"]["total"]
    nop_total = agg["no_passages"]["total"]
    nop_verified = agg["no_passages"]["verified"]

    grounded_rate = grounded_total / grounded_denom if grounded_denom else 0.0
    nop_rate = nop_verified / nop_total if nop_total else 0.0
    overall_gap = grounded_rate - nop_rate

    print(f"\nOverall grounding gap: {overall_gap:+.1%}")
    print(f"  Grounded (trn+emb): {grounded_rate:.1%}")
    print(f"  No passages:        {nop_rate:.1%}")


if __name__ == "__main__":
    main()
