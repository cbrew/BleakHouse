"""Five-way pipeline comparison: character arcs and expert profile analysis.

Compares Transport, Embedding, Plain RAG, No Passages, and Random pipelines
across matched panels to assess how passage selection affects:
- Character mention density and coverage
- Expert vocabulary distinctiveness
- Quote usage patterns
"""

import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Optional: sklearn for TF-IDF
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

RUNS_DIR = Path(__file__).resolve().parent.parent / "data" / "runs"
OUT_DIR = Path(__file__).resolve().parent.parent / "reports" / "five_way_preliminary"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Pipeline prefixes -> human-readable names
PIPELINE_PREFIXES = {
    "v": "transport",
    "emb_v": "embedding",
    "rag_v": "rag",
    "nop_v": "no_passages",
    "rand_v": "random",
}

# Characters to track (case-insensitive matching)
CHARACTERS = [
    "Esther", "Richard", "Ada", "Lady Dedlock", "Sir Leicester",
    "Jarndyce", "Tulkinghorn", "Jo", "Bucket", "Guppy",
    "Skimpole", "Woodcourt", "Caddy", "Krook", "Nemo",
    "Hortense", "Charley", "Rosa", "George", "Smallweed",
    "Snagsby", "Jellyby", "Dedlock",
]

# Build regex patterns for characters (word boundary matching)
CHAR_PATTERNS = {}
for name in CHARACTERS:
    # "Dedlock" is a substring of "Lady Dedlock" and "Sir Leicester Dedlock"
    # We handle this by matching all occurrences; Lady Dedlock / Sir Leicester
    # get their own patterns so overlap is acceptable.
    CHAR_PATTERNS[name] = re.compile(r'\b' + re.escape(name) + r'\b', re.IGNORECASE)

# Known expert names (all possible across panels)
ALL_EXPERTS = {
    "Eleanor Hartley", "James Blackstone", "Caroline Woodcourt",
    "Edmund Leigh", "Daniel Rosen", "Oliver Trevelyan",
    "Host",
}

# Stop words for vocabulary analysis
STOP_WORDS = set("""
a an the and or but in on at to for of is it that this was were be been
being have has had do does did will would shall should may might can could
not no nor so if then than too very just about above after again all also
am are as because before between both by down during each few from further
get got had has he her here hers herself him himself his how i its itself
let like me more most my myself now off only other our ours ourselves out
own re s same she some such t their theirs them themselves there these they
through under until up us was we what when where which while who whom why
with you your yours yourself yourselves d ll m o ve wasn t don doesn didn
couldn wouldn shouldn isn aren haven hasn hadn mustn needn shan won
about actually already always another any anything back been before being
between both came come could course day did didn different does doing done
each enough even every everything fact few find first found from going good
got great had has have here him how i into its just keep kind know last
left let life like little long look made make man many may me might mind
more most much must my never new next no not nothing now off often oh old
one only or other our out over own part people place point put quite
rather read real really right said same say see seem she should show since
small so some something sometimes still such take tell than that the their
them then there these they thing think this those though thought three
through time to too two under up us use used using very want was way we
well went were what when where which while who why will with without work
world would year yet you your ve ll re
much well think know really going want right thing way make things
it s he s she s don t didn t can t won t wouldn t couldn t
what s that s there s here s
""".split())


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def classify_run(dirname: str) -> tuple[str, str] | None:
    """Return (pipeline_type, panel_id) or None if not classifiable."""
    # Try longest prefix first to avoid "v" matching "emb_v..."
    for prefix in sorted(PIPELINE_PREFIXES.keys(), key=len, reverse=True):
        if dirname.startswith(prefix):
            rest = dirname[len(prefix):]
            # Extract panel number: e.g. "01_baseline" -> "01", "10_conservative" -> "10"
            m = re.match(r'(\d+)', rest)
            if m:
                panel_num = m.group(1)
                suffix = rest[len(panel_num):]
                if suffix.startswith('_'):
                    suffix = suffix[1:]
                panel_id = f"v{panel_num}_{suffix}"
                return PIPELINE_PREFIXES[prefix], panel_id
    return None


def load_episode(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def extract_turns(episode: dict) -> list[dict]:
    """Extract all turns with speaker and concatenated text."""
    turns = []
    for seg in episode.get("segments", []):
        for turn in seg.get("turns", []):
            speaker = turn.get("speaker", "Unknown")
            utterances = turn.get("utterances", [])
            texts = [u["text"] for u in utterances if "text" in u]
            full_text = " ".join(texts)
            quote_count = sum(1 for u in utterances if u.get("is_quote", False))
            turns.append({
                "speaker": speaker,
                "role": turn.get("role", ""),
                "text": full_text,
                "quote_count": quote_count,
                "word_count": len(full_text.split()),
            })
    return turns


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def count_characters(text: str) -> Counter:
    """Count character mentions in text."""
    counts = Counter()
    for name, pattern in CHAR_PATTERNS.items():
        n = len(pattern.findall(text))
        if n > 0:
            counts[name] = n
    return counts


def shannon_entropy(counts: Counter) -> float:
    """Shannon entropy of a distribution."""
    total = sum(counts.values())
    if total == 0:
        return 0.0
    h = 0.0
    for c in counts.values():
        if c > 0:
            p = c / total
            h -= p * math.log2(p)
    return h


def get_vocab_words(text: str) -> list[str]:
    """Tokenize text into lowercase words, filtering stopwords and short words."""
    words = re.findall(r"[a-z]+(?:'[a-z]+)?", text.lower())
    return [w for w in words if w not in STOP_WORDS and len(w) > 2]


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def main():
    # 1. Discover all runs with phase3_episode.json
    all_runs = {}  # (pipeline, panel_id) -> path
    for d in sorted(os.listdir(RUNS_DIR)):
        p3 = RUNS_DIR / d / "phase3_episode.json"
        if p3.exists():
            result = classify_run(d)
            if result:
                pipeline, panel_id = result
                all_runs[(pipeline, panel_id)] = p3

    # Group by panel
    panels: dict[str, dict[str, Path]] = defaultdict(dict)
    for (pipeline, panel_id), path in all_runs.items():
        panels[panel_id][pipeline] = path

    # Show coverage
    print(f"Total runs found: {len(all_runs)}")
    print(f"Unique panels: {len(panels)}")
    print()

    # Identify panels with multiple conditions
    multi_panels = {pid: pipes for pid, pipes in panels.items() if len(pipes) >= 2}
    five_way = {pid: pipes for pid, pipes in panels.items() if len(pipes) >= 5}
    three_plus = {pid: pipes for pid, pipes in panels.items() if len(pipes) >= 3}

    print(f"Panels with 5 conditions: {sorted(five_way.keys())}")
    print(f"Panels with 3+ conditions: {sorted(three_plus.keys())}")
    print()

    # 2. Load and analyze all episodes in matched panels (3+)
    # Structure: results[panel_id][pipeline] = analysis_dict
    results = {}

    for panel_id in sorted(three_plus.keys()):
        results[panel_id] = {}
        for pipeline, path in sorted(three_plus[panel_id].items()):
            episode = load_episode(path)
            turns = extract_turns(episode)

            # Per-expert stats
            expert_stats = {}
            all_text = ""
            total_words = 0
            total_quotes = 0

            for turn in turns:
                speaker = turn["speaker"]
                all_text += " " + turn["text"]
                total_words += turn["word_count"]
                total_quotes += turn["quote_count"]

                if speaker not in expert_stats:
                    expert_stats[speaker] = {
                        "text": "",
                        "word_count": 0,
                        "quote_count": 0,
                        "char_mentions": Counter(),
                    }
                expert_stats[speaker]["text"] += " " + turn["text"]
                expert_stats[speaker]["word_count"] += turn["word_count"]
                expert_stats[speaker]["quote_count"] += turn["quote_count"]
                expert_stats[speaker]["char_mentions"] += count_characters(turn["text"])

            # Episode-level character analysis
            episode_chars = count_characters(all_text)
            char_density = sum(episode_chars.values()) / max(total_words, 1) * 1000
            unique_chars = len(episode_chars)
            char_entropy = shannon_entropy(episode_chars)

            # Per-expert vocabulary (raw words for later TF-IDF)
            expert_vocab = {}
            for speaker, stats in expert_stats.items():
                if speaker == "Host":
                    continue
                words = get_vocab_words(stats["text"])
                expert_vocab[speaker] = words

            results[panel_id][pipeline] = {
                "total_words": total_words,
                "total_quotes": total_quotes,
                "char_mentions": episode_chars,
                "char_density": char_density,
                "unique_chars": unique_chars,
                "char_entropy": char_entropy,
                "expert_stats": expert_stats,
                "expert_vocab": expert_vocab,
            }

    # 3. Aggregate across panels by pipeline type
    pipeline_agg: dict[str, dict] = defaultdict(lambda: {
        "char_densities": [],
        "unique_chars": [],
        "char_entropies": [],
        "total_words": [],
        "total_quotes": [],
        "char_totals": Counter(),
        "panel_count": 0,
    })

    for panel_id, pipelines in results.items():
        for pipeline, data in pipelines.items():
            agg = pipeline_agg[pipeline]
            agg["char_densities"].append(data["char_density"])
            agg["unique_chars"].append(data["unique_chars"])
            agg["char_entropies"].append(data["char_entropy"])
            agg["total_words"].append(data["total_words"])
            agg["total_quotes"].append(data["total_quotes"])
            agg["char_totals"] += data["char_mentions"]
            agg["panel_count"] += 1

    # 4. TF-IDF vocabulary analysis across conditions for same expert
    # Collect all text per (expert_name_normalized, pipeline) across panels
    expert_pipeline_text: dict[tuple[str, str], str] = defaultdict(str)
    for panel_id, pipelines in results.items():
        for pipeline, data in pipelines.items():
            for speaker, words in data["expert_vocab"].items():
                expert_pipeline_text[(speaker, pipeline)] += " " + " ".join(words)

    # For cross-condition comparison, group by expert base name
    # Map specific names to role categories for comparison
    # We'll compare the same named expert across conditions
    expert_names_seen = set()
    for (speaker, _) in expert_pipeline_text:
        expert_names_seen.add(speaker)

    # 5. Generate reports
    lines = []
    lines.append("=" * 80)
    lines.append("FIVE-WAY PIPELINE COMPARISON: PRELIMINARY ANALYSIS")
    lines.append("=" * 80)
    lines.append("")

    # Coverage summary
    lines.append("COVERAGE SUMMARY")
    lines.append("-" * 40)
    for pid in sorted(panels.keys()):
        pipes = sorted(panels[pid].keys())
        lines.append(f"  {pid}: {', '.join(pipes)} ({len(pipes)} conditions)")
    lines.append("")

    # Aggregate pipeline comparison
    lines.append("AGGREGATE PIPELINE COMPARISON (panels with 3+ conditions)")
    lines.append("-" * 70)
    header = f"{'Pipeline':<15} {'Panels':>6} {'Avg Words':>10} {'Avg Quotes':>11} {'CharDens/1k':>12} {'Uniq Chars':>11} {'Entropy':>8}"
    lines.append(header)
    lines.append("-" * 70)

    csv_lines = ["pipeline,panels,avg_words,avg_quotes,char_density_per_1k,unique_chars,char_entropy"]

    for pipeline in ["transport", "embedding", "rag", "no_passages", "random"]:
        if pipeline not in pipeline_agg:
            continue
        agg = pipeline_agg[pipeline]
        n = agg["panel_count"]
        avg_words = sum(agg["total_words"]) / n
        avg_quotes = sum(agg["total_quotes"]) / n
        avg_density = sum(agg["char_densities"]) / n
        avg_uniq = sum(agg["unique_chars"]) / n
        avg_entropy = sum(agg["char_entropies"]) / n

        line = f"{pipeline:<15} {n:>6} {avg_words:>10.0f} {avg_quotes:>11.1f} {avg_density:>12.2f} {avg_uniq:>11.1f} {avg_entropy:>8.3f}"
        lines.append(line)
        csv_lines.append(f"{pipeline},{n},{avg_words:.0f},{avg_quotes:.1f},{avg_density:.2f},{avg_uniq:.1f},{avg_entropy:.3f}")

    lines.append("")

    # Character mention breakdown by pipeline
    lines.append("TOP CHARACTER MENTIONS BY PIPELINE (total across all matched panels)")
    lines.append("-" * 70)
    for pipeline in ["transport", "embedding", "rag", "no_passages", "random"]:
        if pipeline not in pipeline_agg:
            continue
        agg = pipeline_agg[pipeline]
        top = agg["char_totals"].most_common(15)
        chars_str = ", ".join(f"{name}({c})" for name, c in top)
        lines.append(f"  {pipeline}: {chars_str}")
    lines.append("")

    # Panel-by-panel comparison for 5-way panels
    lines.append("PANEL-BY-PANEL COMPARISON (5-way panels)")
    lines.append("=" * 70)
    for panel_id in sorted(five_way.keys()):
        lines.append(f"\n  Panel: {panel_id}")
        lines.append(f"  {'Pipeline':<15} {'Words':>7} {'Quotes':>7} {'CharDens':>9} {'UniqCh':>7} {'Entropy':>8}")
        lines.append(f"  {'-'*55}")
        for pipeline in ["transport", "embedding", "rag", "no_passages", "random"]:
            if pipeline not in results.get(panel_id, {}):
                continue
            d = results[panel_id][pipeline]
            lines.append(f"  {pipeline:<15} {d['total_words']:>7} {d['total_quotes']:>7} {d['char_density']:>9.2f} {d['unique_chars']:>7} {d['char_entropy']:>8.3f}")
    lines.append("")

    # Panel-by-panel for 3+ panels
    lines.append("PANEL-BY-PANEL COMPARISON (3+ conditions)")
    lines.append("=" * 70)
    for panel_id in sorted(three_plus.keys()):
        if panel_id in five_way:
            continue  # already shown above
        lines.append(f"\n  Panel: {panel_id}")
        lines.append(f"  {'Pipeline':<15} {'Words':>7} {'Quotes':>7} {'CharDens':>9} {'UniqCh':>7} {'Entropy':>8}")
        lines.append(f"  {'-'*55}")
        for pipeline in ["transport", "embedding", "rag", "no_passages", "random"]:
            if pipeline not in results.get(panel_id, {}):
                continue
            d = results[panel_id][pipeline]
            lines.append(f"  {pipeline:<15} {d['total_words']:>7} {d['total_quotes']:>7} {d['char_density']:>9.2f} {d['unique_chars']:>7} {d['char_entropy']:>8.3f}")
    lines.append("")

    # Per-expert character mentions for 5-way panels
    lines.append("PER-EXPERT CHARACTER MENTIONS (5-way panels)")
    lines.append("=" * 70)
    for panel_id in sorted(five_way.keys()):
        lines.append(f"\n  Panel: {panel_id}")
        for pipeline in ["transport", "embedding", "rag", "no_passages", "random"]:
            if pipeline not in results.get(panel_id, {}):
                continue
            d = results[panel_id][pipeline]
            lines.append(f"    [{pipeline}]")
            for speaker, stats in sorted(d["expert_stats"].items()):
                if speaker == "Host":
                    continue
                top_chars = stats["char_mentions"].most_common(8)
                chars_str = ", ".join(f"{n}({c})" for n, c in top_chars) if top_chars else "(none)"
                lines.append(f"      {speaker:<25} words={stats['word_count']:>5}  quotes={stats['quote_count']:>3}  chars: {chars_str}")
    lines.append("")

    # TF-IDF vocabulary analysis
    lines.append("EXPERT VOCABULARY ANALYSIS (TF-IDF distinctive words)")
    lines.append("=" * 70)

    if HAS_SKLEARN:
        # For each expert that appears in multiple conditions, compute TF-IDF
        # Group texts by expert name
        expert_texts: dict[str, dict[str, str]] = defaultdict(dict)
        for (speaker, pipeline), text in expert_pipeline_text.items():
            if speaker != "Host" and len(text.strip()) > 0:
                expert_texts[speaker][pipeline] = text

        for expert in sorted(expert_texts.keys()):
            pipe_texts = expert_texts[expert]
            if len(pipe_texts) < 2:
                continue

            lines.append(f"\n  Expert: {expert} (appears in {len(pipe_texts)} conditions)")

            # TF-IDF across conditions for this expert
            pipe_names = sorted(pipe_texts.keys())
            docs = [pipe_texts[p] for p in pipe_names]

            vectorizer = TfidfVectorizer(max_features=500, min_df=1, max_df=0.9)
            try:
                tfidf_matrix = vectorizer.fit_transform(docs)
            except ValueError:
                lines.append("    (insufficient vocabulary)")
                continue

            feature_names = vectorizer.get_feature_names_out()

            for i, pipe in enumerate(pipe_names):
                scores = tfidf_matrix[i].toarray().flatten()
                top_indices = scores.argsort()[-10:][::-1]
                top_words = [(feature_names[j], scores[j]) for j in top_indices if scores[j] > 0]
                words_str = ", ".join(f"{w}({s:.3f})" for w, s in top_words)
                lines.append(f"    {pipe:<15}: {words_str}")

            # Cross-condition cosine similarity
            if len(pipe_names) >= 2:
                sim_matrix = cosine_similarity(tfidf_matrix)
                lines.append(f"    Cosine similarities:")
                for i in range(len(pipe_names)):
                    for j in range(i + 1, len(pipe_names)):
                        lines.append(f"      {pipe_names[i]} vs {pipe_names[j]}: {sim_matrix[i][j]:.3f}")
        lines.append("")
    else:
        # Fallback: simple word frequency ratios
        lines.append("  (sklearn not available; using simple frequency analysis)")
        lines.append("")

        expert_texts: dict[str, dict[str, list[str]]] = defaultdict(dict)
        for (speaker, pipeline), text in expert_pipeline_text.items():
            if speaker != "Host":
                words = text.split()
                if words:
                    expert_texts[speaker][pipeline] = words

        for expert in sorted(expert_texts.keys()):
            pipe_words = expert_texts[expert]
            if len(pipe_words) < 2:
                continue
            lines.append(f"\n  Expert: {expert} (appears in {len(pipe_words)} conditions)")

            # Overall frequency across all conditions
            all_words = Counter()
            for words in pipe_words.values():
                all_words.update(words)

            for pipe, words in sorted(pipe_words.items()):
                freq = Counter(words)
                # Find words most distinctive to this condition
                # Score = freq_in_condition / freq_overall (higher = more distinctive)
                scored = []
                for w, c in freq.items():
                    if c >= 2:  # at least 2 occurrences
                        distinctiveness = c / all_words[w]
                        scored.append((w, c, distinctiveness))
                scored.sort(key=lambda x: x[2], reverse=True)
                top = scored[:10]
                words_str = ", ".join(f"{w}({c})" for w, c, _ in top)
                lines.append(f"    {pipe:<15}: {words_str}")
        lines.append("")

    # Per-expert quote counts summary
    lines.append("QUOTE COUNTS BY EXPERT AND PIPELINE (all 3+ panels)")
    lines.append("-" * 70)
    # Aggregate
    expert_quote_agg: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    expert_word_agg: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for panel_id, pipelines in results.items():
        for pipeline, data in pipelines.items():
            for speaker, stats in data["expert_stats"].items():
                if speaker == "Host":
                    continue
                expert_quote_agg[speaker][pipeline].append(stats["quote_count"])
                expert_word_agg[speaker][pipeline].append(stats["word_count"])

    for expert in sorted(expert_quote_agg.keys()):
        lines.append(f"\n  {expert}:")
        for pipeline in ["transport", "embedding", "rag", "no_passages", "random"]:
            quotes = expert_quote_agg[expert].get(pipeline, [])
            words = expert_word_agg[expert].get(pipeline, [])
            if quotes:
                avg_q = sum(quotes) / len(quotes)
                avg_w = sum(words) / len(words)
                lines.append(f"    {pipeline:<15}: avg_quotes={avg_q:>5.1f}  avg_words={avg_w:>6.0f}  (n={len(quotes)})")
    lines.append("")

    # Key findings
    lines.append("KEY OBSERVATIONS")
    lines.append("=" * 70)

    # Compare transport vs others on key metrics
    if "transport" in pipeline_agg and len(pipeline_agg) >= 2:
        t = pipeline_agg["transport"]
        t_density = sum(t["char_densities"]) / t["panel_count"]
        t_entropy = sum(t["char_entropies"]) / t["panel_count"]
        t_words = sum(t["total_words"]) / t["panel_count"]
        t_quotes = sum(t["total_quotes"]) / t["panel_count"]

        for pipeline in ["embedding", "rag", "no_passages", "random"]:
            if pipeline not in pipeline_agg:
                continue
            o = pipeline_agg[pipeline]
            o_density = sum(o["char_densities"]) / o["panel_count"]
            o_entropy = sum(o["char_entropies"]) / o["panel_count"]
            o_words = sum(o["total_words"]) / o["panel_count"]
            o_quotes = sum(o["total_quotes"]) / o["panel_count"]

            density_diff = (o_density - t_density) / t_density * 100
            entropy_diff = (o_entropy - t_entropy) / t_entropy * 100
            word_diff = (o_words - t_words) / t_words * 100
            quote_diff = (o_quotes - t_quotes) / t_quotes * 100 if t_quotes > 0 else 0

            lines.append(f"\n  Transport vs {pipeline}:")
            lines.append(f"    Character density: {density_diff:+.1f}%")
            lines.append(f"    Character entropy: {entropy_diff:+.1f}%")
            lines.append(f"    Word count:        {word_diff:+.1f}%")
            lines.append(f"    Quote count:       {quote_diff:+.1f}%")

    lines.append("")

    # Write report
    report_text = "\n".join(lines)
    report_path = OUT_DIR / "preliminary_report.txt"
    report_path.write_text(report_text)
    print(report_text)
    print(f"\nReport written to: {report_path}")

    # Write CSV
    csv_path = OUT_DIR / "pipeline_comparison.csv"
    csv_path.write_text("\n".join(csv_lines))
    print(f"CSV written to: {csv_path}")

    # Write detailed per-panel CSV
    detail_lines = ["panel_id,pipeline,total_words,total_quotes,char_density_per_1k,unique_chars,char_entropy"]
    for panel_id in sorted(results.keys()):
        for pipeline in ["transport", "embedding", "rag", "no_passages", "random"]:
            if pipeline not in results[panel_id]:
                continue
            d = results[panel_id][pipeline]
            detail_lines.append(f"{panel_id},{pipeline},{d['total_words']},{d['total_quotes']},{d['char_density']:.2f},{d['unique_chars']},{d['char_entropy']:.3f}")
    detail_path = OUT_DIR / "panel_detail.csv"
    detail_path.write_text("\n".join(detail_lines))
    print(f"Detail CSV written to: {detail_path}")


if __name__ == "__main__":
    main()
