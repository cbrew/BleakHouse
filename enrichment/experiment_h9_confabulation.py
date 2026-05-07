"""Experiment H9: Training-exposure correlation with confabulation rates.

H9 claims: "No-passages confabulation rates correlate with the LLM's likely
training exposure. Well-studied texts have higher ungrounded verification rates
than less-studied ones."

This script:
1. Computes per-novel nop (no-passages) quote verification rates across all
   panel configurations, reusing the verification logic from H5.
2. Fetches Wikipedia article word counts as a training-exposure proxy (via
   the MediaWiki API at runtime, with hard-coded fallbacks).
3. Computes Pearson correlation between Wikipedia article length and nop
   verification rate.

Usage:
    uv run python -m enrichment.experiment_h9_confabulation [--runs-dir data/runs]
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import subprocess
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

RUNS_DIR = Path("data/runs")
REPORTS_DIR = Path("reports")

# ---------------------------------------------------------------------------
# Novel metadata
# ---------------------------------------------------------------------------

NOVEL_LABELS = {
    "bleak_house": "Bleak House",
    "mill_on_the_floss": "Mill on the Floss",
    "north_and_south": "North and South",
    "our_mutual_friend": "Our Mutual Friend",
    "passage_to_india": "A Passage to India",
}

NOVEL_AUTHORS = {
    "bleak_house": "Dickens (1853)",
    "mill_on_the_floss": "Eliot (1860)",
    "north_and_south": "Gaskell (1855)",
    "our_mutual_friend": "Dickens (1865)",
    "passage_to_india": "Forster (1924)",
}

# Wikipedia article titles for each novel
WIKIPEDIA_TITLES = {
    "bleak_house": "Bleak_House",
    "mill_on_the_floss": "The_Mill_on_the_Floss",
    "north_and_south": "North_and_South_(Gaskell_novel)",
    "our_mutual_friend": "Our_Mutual_Friend",
    "passage_to_india": "A_Passage_to_India",
}

# Fallback word counts (from Wikipedia API, fetched 2026-03-24).
# These are used only if the live API fetch fails.
WIKIPEDIA_WORD_COUNTS_FALLBACK = {
    "bleak_house": 5401,
    "mill_on_the_floss": 1933,
    "north_and_south": 7113,
    "our_mutual_friend": 10004,
    "passage_to_india": 2167,
}


# ---------------------------------------------------------------------------
# Wikipedia article word count via MediaWiki API
# ---------------------------------------------------------------------------

def fetch_wikipedia_word_count(title: str) -> int | None:
    """Fetch approximate word count of a Wikipedia article via the API.

    Uses the TextExtracts API to get plain text, then counts words.
    Returns None on failure.
    """
    url = (
        "https://en.wikipedia.org/w/api.php?"
        + urllib.parse.urlencode({
            "action": "query",
            "titles": title,
            "prop": "extracts",
            "explaintext": "1",
            "format": "json",
        })
    )
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "BleakHouseResearch/1.0 (academic research)"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            text = page.get("extract", "")
            if text:
                return len(text.split())
    except Exception as e:
        logger.warning("Failed to fetch Wikipedia article %r: %s", title, e)
    return None


def get_wikipedia_word_counts(novels: list[str]) -> dict[str, int]:
    """Get word counts for all novels, with fallback to hard-coded values."""
    result: dict[str, int] = {}
    for novel in novels:
        title = WIKIPEDIA_TITLES.get(novel)
        if not title:
            continue
        wc = fetch_wikipedia_word_count(title)
        if wc is not None:
            result[novel] = wc
            logger.info("Wikipedia %s: %d words (live)", novel, wc)
        else:
            fallback = WIKIPEDIA_WORD_COUNTS_FALLBACK.get(novel, 0)
            result[novel] = fallback
            logger.info("Wikipedia %s: %d words (fallback)", novel, fallback)
    return result


# ---------------------------------------------------------------------------
# Source text loading (from H5)
# ---------------------------------------------------------------------------

def load_source_text(novel: str, runs_dir: Path) -> str:
    """Load concatenated passage text for fuzzy matching."""
    from cas import paths as cas_paths
    novel_path = cas_paths.passages_enriched(novel)
    if novel_path.exists():
        passages = json.loads(novel_path.read_text())
        return " ".join(p.get("text", "") for p in passages).lower()

    # Fallback: collect from phase1 assignments
    texts: set[str] = set()
    for rd in runs_dir.iterdir():
        if not rd.is_dir():
            continue
        rn, _, _ = classify_run(rd.name)
        if rn != novel:
            continue
        p1_path = rd / "phase1_assignments.json"
        if not p1_path.exists():
            continue
        try:
            p1 = json.loads(p1_path.read_text())
            for a in p1.get("assignments", []):
                t = a.get("text", "")
                if t:
                    texts.add(t)
        except (json.JSONDecodeError, OSError):
            continue
    return " ".join(texts).lower()


# ---------------------------------------------------------------------------
# Run classification (from H5)
# ---------------------------------------------------------------------------

def classify_run(name: str) -> tuple[str, str, str]:
    """Return (novel, condition, panel_id) from run directory name."""
    for prefix, novel in [
        ("motf_trn_", "mill_on_the_floss"), ("motf_emb_", "mill_on_the_floss"),
        ("motf_nop_", "mill_on_the_floss"), ("motf_ext_", "mill_on_the_floss"),
        ("motf_hia_", "mill_on_the_floss"),
        ("nas_trn_", "north_and_south"), ("nas_emb_", "north_and_south"),
        ("nas_nop_", "north_and_south"), ("nas_ext_", "north_and_south"),
        ("nas_hia_", "north_and_south"),
        ("omf_trn_", "our_mutual_friend"), ("omf_emb_", "our_mutual_friend"),
        ("omf_nop_", "our_mutual_friend"), ("omf_ext_", "our_mutual_friend"),
        ("omf_hia_", "our_mutual_friend"),
        ("pti_trn_", "passage_to_india"), ("pti_emb_", "passage_to_india"),
        ("pti_nop_", "passage_to_india"), ("pti_ext_", "passage_to_india"),
        ("pti_hia_", "passage_to_india"),
    ]:
        if name.startswith(prefix):
            cond = prefix.split("_")[1]
            rest = name[len(prefix):]
            return novel, cond, rest

    for prefix, cond in [
        ("arc_", "arc"), ("hia_", "hia"), ("emb_", "emb"), ("nop_", "nop"),
        ("rag_", "rag"), ("rand_", "rand"), ("ext_", "ext"),
    ]:
        if name.startswith(prefix):
            return "bleak_house", cond, name[len(prefix):]

    return "unknown", "unknown", name


# ---------------------------------------------------------------------------
# Quote verification (from H5)
# ---------------------------------------------------------------------------

def fuzzy_quote_match(quote: str, source: str, window: int = 5) -> bool:
    """Check if any 5-word subsequence of the quote appears in the source."""
    words = quote.lower().split()
    if len(words) < window:
        return quote.lower().strip('" >') in source
    for i in range(len(words) - window + 1):
        subseq = " ".join(words[i:i + window])
        if subseq in source:
            return True
    return False


def verify_quotes(run_dir: Path, source_text: str) -> tuple[int, int]:
    """Return (verified_count, total_quote_count) for a single run."""
    ep_path = run_dir / "phase3_episode.json"
    if not ep_path.exists():
        return 0, 0
    try:
        ep = json.loads(ep_path.read_text())
    except (json.JSONDecodeError, OSError):
        return 0, 0

    verified = 0
    total = 0
    for seg in ep.get("segments", []):
        for turn in seg.get("turns", []):
            for utt in turn.get("utterances", []):
                if utt.get("is_quote"):
                    total += 1
                    text = utt.get("text", "")
                    clean = text.strip().lstrip("> ").strip('"').strip("'")
                    if fuzzy_quote_match(clean, source_text):
                        verified += 1
    return verified, total


# ---------------------------------------------------------------------------
# Pearson correlation
# ---------------------------------------------------------------------------

def pearson_r(xs: list[float], ys: list[float]) -> float:
    """Compute Pearson correlation coefficient."""
    n = len(xs)
    if n < 2:
        return float("nan")
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    denom = math.sqrt(var_x * var_y)
    if denom == 0:
        return float("nan")
    return cov / denom


def t_statistic(r: float, n: int) -> float:
    """Compute t-statistic for Pearson r with n observations."""
    if n < 3 or abs(r) >= 1.0:
        return float("nan")
    return r * math.sqrt((n - 2) / (1 - r ** 2))


def p_value_approx(t: float, df: int) -> str:
    """Approximate significance level from t-statistic and degrees of freedom.

    Returns a string describing the p-value range. For n=5 (df=3):
      t > 5.841 => p < 0.01
      t > 3.182 => p < 0.05
      t > 2.353 => p < 0.10
    """
    if math.isnan(t) or df < 1:
        return "n/a"
    abs_t = abs(t)
    # Critical values for df=3 (two-tailed)
    if df == 3:
        if abs_t > 5.841:
            return "p < 0.01"
        elif abs_t > 3.182:
            return "p < 0.05"
        elif abs_t > 2.353:
            return "p < 0.10"
        else:
            return "p > 0.10 (n.s.)"
    # Generic approximation for small df
    # Use df=3 critical values as conservative bound
    if abs_t > 5.0:
        return "p < 0.01 (approx)"
    elif abs_t > 3.0:
        return "p < 0.05 (approx)"
    elif abs_t > 2.0:
        return "p < 0.10 (approx)"
    else:
        return "p > 0.10 (n.s.)"


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="H9: training-exposure correlation with confabulation rates",
    )
    parser.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    parser.add_argument("--out-dir", type=Path, default=REPORTS_DIR)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    runs_dir = args.runs_dir
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # Git tag
    try:
        git_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True,
        ).strip()
    except subprocess.CalledProcessError:
        git_hash = "unknown"
    tag = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{git_hash}"

    # -------------------------------------------------------------------
    # 1. Discover nop runs
    # -------------------------------------------------------------------
    run_dirs = sorted(d for d in runs_dir.iterdir() if d.is_dir())

    nop_runs: list[dict] = []
    for rd in run_dirs:
        ep_path = rd / "phase3_episode.json"
        if not ep_path.exists():
            continue
        novel, condition, panel_id = classify_run(rd.name)
        if condition != "nop" or novel == "unknown":
            continue
        nop_runs.append({
            "dir": rd,
            "name": rd.name,
            "novel": novel,
            "panel_id": panel_id,
        })

    logger.info("Found %d nop runs with phase3_episode.json", len(nop_runs))

    # -------------------------------------------------------------------
    # 2. Load source texts
    # -------------------------------------------------------------------
    novels = sorted({r["novel"] for r in nop_runs})
    source_cache: dict[str, str] = {}
    for novel in novels:
        src = load_source_text(novel, runs_dir)
        source_cache[novel] = src
        logger.info("Source text for %-25s: %d chars", novel, len(src))

    # -------------------------------------------------------------------
    # 3. Verify quotes per nop run
    # -------------------------------------------------------------------
    run_results: list[dict] = []
    for ri in nop_runs:
        novel = ri["novel"]
        source = source_cache.get(novel, "")
        v, t = verify_quotes(ri["dir"], source)
        rate = v / t * 100 if t > 0 else float("nan")
        run_results.append({
            **ri,
            "verified": v,
            "total_quotes": t,
            "rate_pct": rate,
        })

    # -------------------------------------------------------------------
    # 4. Aggregate per novel
    # -------------------------------------------------------------------
    novel_agg: dict[str, dict] = {}
    for novel in novels:
        runs = [r for r in run_results if r["novel"] == novel]
        total_v = sum(r["verified"] for r in runs)
        total_t = sum(r["total_quotes"] for r in runs)
        overall_rate = total_v / total_t * 100 if total_t > 0 else float("nan")

        # Per-run rates for mean/std
        per_run_rates = [r["rate_pct"] for r in runs if not math.isnan(r["rate_pct"])]
        mean_rate = sum(per_run_rates) / len(per_run_rates) if per_run_rates else float("nan")
        if len(per_run_rates) > 1:
            var = sum((x - mean_rate) ** 2 for x in per_run_rates) / (len(per_run_rates) - 1)
            std_rate = math.sqrt(var)
        else:
            std_rate = float("nan")

        novel_agg[novel] = {
            "n_runs": len(runs),
            "total_verified": total_v,
            "total_quotes": total_t,
            "pooled_rate": overall_rate,
            "mean_run_rate": mean_rate,
            "std_run_rate": std_rate,
            "per_run_rates": per_run_rates,
        }

    # -------------------------------------------------------------------
    # 5. Fetch Wikipedia word counts (training exposure proxy)
    # -------------------------------------------------------------------
    wiki_wc = get_wikipedia_word_counts(novels)

    # -------------------------------------------------------------------
    # 6. Compute Pearson correlation
    # -------------------------------------------------------------------
    # Use pooled verification rate (more stable with unequal run counts)
    xs_wiki = [float(wiki_wc.get(n, 0)) for n in novels]
    ys_pooled = [novel_agg[n]["pooled_rate"] for n in novels]
    ys_mean = [novel_agg[n]["mean_run_rate"] for n in novels]

    r_pooled = pearson_r(xs_wiki, ys_pooled)
    r_mean = pearson_r(xs_wiki, ys_mean)

    n_obs = len(novels)
    df = n_obs - 2

    t_pooled = t_statistic(r_pooled, n_obs)
    t_mean = t_statistic(r_mean, n_obs)

    p_pooled = p_value_approx(t_pooled, df)
    p_mean = p_value_approx(t_mean, df)

    # -------------------------------------------------------------------
    # 7. Build output report
    # -------------------------------------------------------------------
    lines: list[str] = []
    lines.append(f"EXPERIMENT H9: TRAINING-EXPOSURE vs CONFABULATION -- {tag}")
    lines.append("=" * 95)
    lines.append("")
    lines.append('H9 claim: "No-passages confabulation rates correlate with the LLM\'s')
    lines.append("likely training exposure. Well-studied texts have higher ungrounded")
    lines.append('verification rates than less-studied ones."')
    lines.append("")
    lines.append("Method:")
    lines.append("  - Verification: fuzzy 5-word sliding window match against source passages")
    lines.append("  - Training exposure proxy: Wikipedia article word count")
    lines.append("  - Correlation: Pearson r between Wikipedia word count and nop verification rate")
    lines.append("")

    # --- Table 1: Per-run detail ---
    lines.append("TABLE 1: PER-RUN NOP VERIFICATION DETAIL")
    lines.append("-" * 95)
    lines.append(f"{'Run':>45s} {'Novel':>22s} {'Verified':>9s} {'Total':>7s} {'Rate%':>7s}")

    for r in sorted(run_results, key=lambda x: (x["novel"], x["name"])):
        rate_str = f"{r['rate_pct']:.1f}" if not math.isnan(r["rate_pct"]) else "n/a"
        lines.append(
            f"{r['name']:>45s} {NOVEL_LABELS.get(r['novel'], r['novel']):>22s} "
            f"{r['verified']:>9d} {r['total_quotes']:>7d} {rate_str:>7s}"
        )
    lines.append(f"  ({len(run_results)} nop runs total)")
    lines.append("")

    # --- Table 2: Per-novel aggregated ---
    lines.append("TABLE 2: PER-NOVEL AGGREGATED NOP VERIFICATION")
    lines.append("-" * 95)
    lines.append(
        f"{'Novel':>22s} {'Author':>18s} {'Runs':>5s} {'Verified':>9s} "
        f"{'Total':>7s} {'Pooled%':>8s} {'Mean%':>7s} {'Std%':>7s}"
    )

    for novel in novels:
        agg = novel_agg[novel]
        std_str = f"{agg['std_run_rate']:.1f}" if not math.isnan(agg["std_run_rate"]) else "n/a"
        lines.append(
            f"{NOVEL_LABELS.get(novel, novel):>22s} {NOVEL_AUTHORS.get(novel, ''):>18s} "
            f"{agg['n_runs']:>5d} {agg['total_verified']:>9d} "
            f"{agg['total_quotes']:>7d} {agg['pooled_rate']:>8.1f} "
            f"{agg['mean_run_rate']:>7.1f} {std_str:>7s}"
        )
    lines.append("")

    # --- Table 3: Training exposure proxy ---
    lines.append("TABLE 3: TRAINING EXPOSURE PROXY (Wikipedia article word count)")
    lines.append("-" * 95)
    lines.append(
        f"{'Novel':>22s} {'Wikipedia title':>40s} {'Words':>8s} "
        f"{'NOP rate%':>10s}"
    )

    for novel in novels:
        wc = wiki_wc.get(novel, 0)
        rate = novel_agg[novel]["pooled_rate"]
        title = WIKIPEDIA_TITLES.get(novel, "?")
        lines.append(
            f"{NOVEL_LABELS.get(novel, novel):>22s} {title:>40s} {wc:>8d} "
            f"{rate:>10.1f}"
        )
    lines.append("")

    # --- Table 4: Correlation ---
    lines.append("TABLE 4: PEARSON CORRELATION (Wikipedia words vs NOP verification %)")
    lines.append("-" * 95)
    lines.append(f"  Observations (novels):     {n_obs}")
    lines.append(f"  Degrees of freedom:        {df}")
    lines.append("")
    lines.append("  Using pooled verification rate (total verified / total quotes):")
    lines.append(f"    Pearson r  = {r_pooled:+.4f}")
    lines.append(f"    t({df})       = {t_pooled:+.4f}")
    lines.append(f"    Significance: {p_pooled}")
    lines.append(f"    R-squared  = {r_pooled**2:.4f}")
    lines.append("")
    lines.append("  Using mean of per-run rates:")
    lines.append(f"    Pearson r  = {r_mean:+.4f}")
    lines.append(f"    t({df})       = {t_mean:+.4f}")
    lines.append(f"    Significance: {p_mean}")
    lines.append(f"    R-squared  = {r_mean**2:.4f}")
    lines.append("")

    # --- Scatter data for reference ---
    lines.append("SCATTER DATA (for plotting):")
    lines.append("-" * 95)
    lines.append(f"{'Novel':>22s} {'Wiki words (x)':>15s} {'Pooled rate (y)':>16s} "
                 f"{'Mean rate (y)':>14s}")
    for novel in novels:
        lines.append(
            f"{NOVEL_LABELS.get(novel, novel):>22s} "
            f"{wiki_wc.get(novel, 0):>15d} "
            f"{novel_agg[novel]['pooled_rate']:>16.1f} "
            f"{novel_agg[novel]['mean_run_rate']:>14.1f}"
        )
    lines.append("")

    # --- Verdict ---
    lines.append("=" * 95)
    lines.append("H9 VERDICT")
    lines.append("=" * 95)
    lines.append("")

    if r_pooled > 0:
        direction = "POSITIVE"
        interp = (
            "Novels with longer Wikipedia articles (proxy for greater training "
            "exposure) show HIGHER nop verification rates, consistent with H9."
        )
    else:
        direction = "NEGATIVE"
        interp = (
            "Novels with longer Wikipedia articles show LOWER nop verification "
            "rates, contradicting H9."
        )

    lines.append(f"  Correlation direction: {direction} (r = {r_pooled:+.4f})")
    lines.append(f"  {interp}")
    lines.append("")

    if not math.isnan(r_pooled) and abs(r_pooled) > 0.7:
        strength = "strong"
    elif not math.isnan(r_pooled) and abs(r_pooled) > 0.4:
        strength = "moderate"
    else:
        strength = "weak"

    lines.append(f"  Effect size: {strength} (|r| = {abs(r_pooled):.3f})")
    lines.append(f"  Statistical significance: {p_pooled}")
    lines.append("")

    if r_pooled > 0.4 and "n.s." not in p_pooled:
        verdict = "SUPPORTED"
    elif r_pooled > 0.4:
        verdict = "DIRECTIONALLY SUPPORTED (not statistically significant at p<0.10)"
    elif r_pooled > 0:
        verdict = "WEAKLY SUPPORTED (positive but small effect)"
    else:
        verdict = "NOT SUPPORTED"

    lines.append(f"  H9 verdict: {verdict}")
    lines.append("")
    lines.append("  Caveats:")
    lines.append("    - Only 5 novels (df=3), so statistical power is very limited")
    lines.append("    - Wikipedia article length is a rough proxy for training exposure")
    lines.append("    - All 5 novels are canonical texts; the range of 'obscurity' is narrow")
    lines.append("    - The candidate obscure novels (No Name, New Grub Street, Odd Women,")
    lines.append("      Miss Marjoribanks, Hester) do not yet have nop runs")
    lines.append("    - Extending to those novels would provide a much stronger test")
    lines.append("")

    # -------------------------------------------------------------------
    # 8. Write report
    # -------------------------------------------------------------------
    report_text = "\n".join(lines)
    report_path = out_dir / f"h9_confabulation_{tag}.txt"
    report_path.write_text(report_text)
    logger.info("Wrote %s", report_path)

    print(report_text)


if __name__ == "__main__":
    main()
