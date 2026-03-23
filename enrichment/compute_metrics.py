"""Compute evaluation metrics across pipeline runs.

Outputs CSV files and text reports for:
  - Aggregate quality (words, quotes, characters, entropy)
  - Quote verification (fuzzy match against source text)
  - Expert airtime
  - Conversational design features
  - Material disjointness (passage/chapter Jaccard between conditions)

Usage:
    uv run python -m enrichment.compute_metrics [--runs-dir data/runs] [--out-dir reports]
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import re
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

RUNS_DIR = Path("data/runs")
REPORTS_DIR = Path("reports")


# ---------------------------------------------------------------------------
# Episode parsing
# ---------------------------------------------------------------------------

@dataclass
class EpisodeMetrics:
    """Metrics extracted from a single episode."""
    run_name: str
    novel: str
    condition: str
    panel: str
    total_words: int = 0
    total_segments: int = 0
    total_turns: int = 0
    total_utterances: int = 0
    quote_count: int = 0
    character_mentions: int = 0
    unique_characters: set = field(default_factory=set)
    speaker_words: dict = field(default_factory=lambda: defaultdict(int))
    # Conversational design
    expert_to_expert_transitions: int = 0
    total_transitions: int = 0
    host_turns: int = 0
    quote_pattern_ok: int = 0  # quotes with [reading] or passage_ref
    total_quotes: int = 0
    cross_expert_refs: int = 0
    tts_rates: list = field(default_factory=list)
    reactive_markers: int = 0
    # Passage references
    passage_ids: set = field(default_factory=set)
    chapter_ids: set = field(default_factory=set)


# Known character names per novel for mention counting
CHARACTERS = {
    "bleak_house": [
        "Esther", "Lady Dedlock", "Dedlock", "Richard", "Carstone", "Ada",
        "Jarndyce", "Tulkinghorn", "Guppy", "Snagsby", "Jo", "Bucket",
        "Woodcourt", "Skimpole", "Jellyby", "Krook", "Miss Flite",
        "Hortense", "Charley", "Caddy", "Nemo", "Hawdon", "Vholes",
        "Boythorn", "Smallweed", "Rosa",
    ],
    "our_mutual_friend": [
        "Bella", "Harmon", "Boffin", "Wegg", "Lizzie", "Hexam", "Wrayburn",
        "Headstone", "Podsnap", "Lammle", "Veneering", "Riderhood",
        "Jenny Wren", "Riah", "Lightwood", "Twemlow", "Wilfer",
    ],
    "mill_on_the_floss": [
        "Maggie", "Tom", "Tulliver", "Philip", "Wakem", "Stephen",
        "Guest", "Lucy", "Deane", "Glegg", "Pullet", "Moss", "Bob Jakin",
    ],
    "north_and_south": [
        "Margaret", "Thornton", "Higgins", "Hale", "Bessy", "Boucher",
        "Bell", "Lennox", "Shaw", "Dixon",
    ],
    "passage_to_india": [
        "Aziz", "Fielding", "Adela", "Mrs Moore", "Godbole", "Ronny",
        "McBryde", "Hamidullah", "Turton", "Quested",
    ],
}

REACTIVE_PATTERNS = re.compile(
    r"\b(yes|exactly|absolutely|right|indeed|precisely|that\'s|I agree|"
    r"building on|to add|what strikes me|interesting)\b",
    re.IGNORECASE,
)


def classify_run(name: str) -> tuple[str, str, str]:
    """Return (novel, condition, panel) from run name."""
    # Cross-novel: motf_trn_v01_baseline, omf_emb_v11_...
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
            rest = name[len(prefix):]
            cond = prefix.split("_")[1]
            return novel, cond, rest

    # BH conditions
    for prefix, cond in [
        ("arc_", "trn"), ("hia_", "hia"), ("emb_", "emb"), ("nop_", "nop"),
        ("rag_", "rag"), ("rand_", "rand"), ("ext_", "ext"),
    ]:
        if name.startswith(prefix):
            return "bleak_house", cond, name[len(prefix):]

    return "unknown", "unknown", name


def extract_metrics(run_dir: Path) -> EpisodeMetrics | None:
    """Extract metrics from a single run's phase3_episode.json."""
    ep_path = run_dir / "phase3_episode.json"
    if not ep_path.exists():
        return None

    name = run_dir.name
    novel, condition, panel = classify_run(name)
    m = EpisodeMetrics(
        run_name=name, novel=novel, condition=condition, panel=panel,
    )

    try:
        ep = json.loads(ep_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    segments = ep.get("segments", [])
    m.total_segments = len(segments)

    # Character list for this novel
    chars = CHARACTERS.get(novel, [])

    prev_speaker = None
    prev_role = None

    for seg in segments:
        turns = seg.get("turns", [])
        for turn in turns:
            speaker = turn.get("speaker", "")
            role = turn.get("role", "expert")
            utterances = turn.get("utterances", [])
            m.total_turns += 1

            if role == "host" or speaker == "Host":
                m.host_turns += 1

            # Transitions
            if prev_speaker is not None and speaker != prev_speaker:
                m.total_transitions += 1
                if prev_role == "expert" and role == "expert":
                    m.expert_to_expert_transitions += 1
            prev_speaker = speaker
            prev_role = role

            turn_words = 0
            for utt in utterances:
                text = utt.get("text", "")
                words = len(text.split())
                turn_words += words
                m.total_words += words
                m.total_utterances += 1

                # TTS rate
                rate = utt.get("rate")
                if rate is not None:
                    m.tts_rates.append(rate)

                # Quotes
                is_quote = utt.get("is_quote", False)
                if is_quote:
                    m.total_quotes += 1
                    m.quote_count += 1
                    ref = utt.get("passage_ref", "")
                    mode = utt.get("quote_mode", "")
                    if ref or mode == "reading":
                        m.quote_pattern_ok += 1

                # Passage refs
                ref = utt.get("passage_ref", "")
                if ref:
                    m.passage_ids.add(ref)
                    # Extract chapter from ref like "c1:p5"
                    ch = ref.split(":")[0] if ":" in ref else ""
                    if ch:
                        m.chapter_ids.add(ch)

                # Character mentions
                for char in chars:
                    if char.lower() in text.lower():
                        m.character_mentions += 1
                        m.unique_characters.add(char)

                # Reactive markers
                m.reactive_markers += len(REACTIVE_PATTERNS.findall(text))

                # Cross-expert passage refs (expert referencing another expert's passage)
                if role == "expert" and ref:
                    m.cross_expert_refs += 1

            m.speaker_words[speaker] += turn_words

    return m


def character_entropy(m: EpisodeMetrics) -> float:
    """Shannon entropy of character mention distribution."""
    if not m.unique_characters:
        return 0.0
    # Simple: use speaker word counts as proxy
    # Actually use unique_characters count and their mention frequencies
    # We don't track per-character mention counts, so use uniform approx
    n = len(m.unique_characters)
    if n <= 1:
        return 0.0
    return math.log2(n)  # upper bound (uniform)


def compute_char_entropy_from_text(run_dir: Path, novel: str) -> float:
    """More accurate: count actual character mentions."""
    ep_path = run_dir / "phase3_episode.json"
    if not ep_path.exists():
        return 0.0
    ep = json.loads(ep_path.read_text())
    chars = CHARACTERS.get(novel, [])
    counts: Counter = Counter()
    for seg in ep.get("segments", []):
        for turn in seg.get("turns", []):
            for utt in turn.get("utterances", []):
                text = utt.get("text", "").lower()
                for char in chars:
                    c = text.count(char.lower())
                    if c > 0:
                        counts[char] += c
    total = sum(counts.values())
    if total == 0:
        return 0.0
    entropy = 0.0
    for count in counts.values():
        p = count / total
        if p > 0:
            entropy -= p * math.log2(p)
    return entropy


# ---------------------------------------------------------------------------
# Quote verification (fuzzy subsequence match)
# ---------------------------------------------------------------------------

def load_source_text(novel: str, runs_dir: Path) -> str:
    """Load the novel's source text for quote verification.

    Uses passages_enriched.json for BH, or collects passage text from
    phase1_assignments.json across all runs for that novel.
    """
    if novel == "bleak_house":
        path = Path("data/passages_enriched.json")
        if path.exists():
            passages = json.loads(path.read_text())
            return " ".join(p.get("text", "") for p in passages).lower()

    # For cross-novel: collect text from phase1 assignments
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


def verify_quotes(run_dir: Path, _novel: str, source_text: str) -> tuple[int, int]:
    """Return (verified_count, total_quote_count)."""
    ep_path = run_dir / "phase3_episode.json"
    if not ep_path.exists():
        return 0, 0
    ep = json.loads(ep_path.read_text())
    verified = 0
    total = 0
    for seg in ep.get("segments", []):
        for turn in seg.get("turns", []):
            for utt in turn.get("utterances", []):
                if utt.get("is_quote"):
                    total += 1
                    text = utt.get("text", "")
                    # Strip quote markers
                    text = text.strip().lstrip("> ").strip('"').strip("'")
                    if fuzzy_quote_match(text, source_text):
                        verified += 1
    return verified, total


# ---------------------------------------------------------------------------
# Material disjointness
# ---------------------------------------------------------------------------

def passage_jaccard(set_a: set, set_b: set) -> float:
    """Jaccard similarity between two passage ID sets."""
    if not set_a and not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Compute metrics across runs")
    parser.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    parser.add_argument("--out-dir", type=Path, default=REPORTS_DIR)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    runs_dir = args.runs_dir
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # Get git tag
    try:
        git_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True,
        ).strip()
    except subprocess.CalledProcessError:
        git_hash = "unknown"
    from datetime import datetime
    tag = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{git_hash}"

    # Extract metrics from all runs
    all_metrics: list[EpisodeMetrics] = []
    run_dirs = sorted(d for d in runs_dir.iterdir() if d.is_dir())
    logger.info("Processing %d runs...", len(run_dirs))

    for rd in run_dirs:
        m = extract_metrics(rd)
        if m:
            all_metrics.append(m)

    logger.info("Extracted metrics from %d runs", len(all_metrics))

    # --- CSV: per-run metrics ---
    csv_path = out_dir / "cross_novel_aggregate" / "run_metrics.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    # Collect all speaker names
    all_speakers: set[str] = set()
    for m in all_metrics:
        all_speakers.update(m.speaker_words.keys())
    speaker_cols = sorted(s for s in all_speakers if s != "Host")

    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        header = [
            "novel", "condition", "panel_id", "total_words", "total_segments",
            "total_turns", "total_utterances", "quote_count", "quote_density",
            "character_mentions", "char_density", "unique_characters",
            "character_entropy",
        ] + [f"airtime_{s}" for s in speaker_cols]
        w.writerow(header)

        for m in sorted(all_metrics, key=lambda x: (x.novel, x.condition, x.panel)):
            entropy = compute_char_entropy_from_text(
                runs_dir / m.run_name, m.novel,
            )
            qd = (m.quote_count / m.total_words * 1000) if m.total_words else 0
            cd = (m.character_mentions / m.total_words * 1000) if m.total_words else 0
            row = [
                m.novel, m.condition, m.panel, m.total_words, m.total_segments,
                m.total_turns, m.total_utterances, m.quote_count,
                round(qd, 3), m.character_mentions, round(cd, 3),
                len(m.unique_characters), round(entropy, 3),
            ] + [m.speaker_words.get(s, 0) for s in speaker_cols]
            w.writerow(row)

    logger.info("Wrote %s", csv_path)

    # --- Aggregate table (by condition, BH vs cross-novel) ---
    by_condition: dict[str, list[EpisodeMetrics]] = defaultdict(list)
    for m in all_metrics:
        by_condition[m.condition].append(m)

    lines: list[str] = []
    lines.append(f"EVALUATION METRICS REPORT — {tag}")
    lines.append("=" * 72)
    lines.append("")

    # Table 3: Aggregate quality
    lines.append("TABLE 3: AGGREGATE QUALITY")
    lines.append("-" * 72)
    lines.append(f"{'Condition':>12s} {'N':>4s} {'Words/ep':>10s} {'Quotes/ep':>10s} "
                 f"{'Char/1Kw':>10s} {'UniqChar':>10s} {'CharEnt':>10s}")

    for cond in ["trn", "hia", "emb", "rag", "nop", "rand", "ext"]:
        runs = by_condition.get(cond, [])
        if not runs:
            continue
        n = len(runs)
        avg_words = sum(m.total_words for m in runs) / n
        avg_quotes = sum(m.quote_count for m in runs) / n
        avg_char_density = sum(
            m.character_mentions / m.total_words * 1000
            if m.total_words else 0 for m in runs
        ) / n
        avg_uniq = sum(len(m.unique_characters) for m in runs) / n
        avg_entropy = sum(
            compute_char_entropy_from_text(runs_dir / m.run_name, m.novel)
            for m in runs
        ) / n
        lines.append(
            f"{cond:>12s} {n:>4d} {avg_words:>10.0f} {avg_quotes:>10.1f} "
            f"{avg_char_density:>10.1f} {avg_uniq:>10.1f} {avg_entropy:>10.2f}"
        )
    lines.append("")

    # BH-only aggregate
    lines.append("TABLE 3a: BH-ONLY AGGREGATE")
    lines.append("-" * 72)
    lines.append(f"{'Condition':>12s} {'N':>4s} {'Words/ep':>10s} {'Quotes/ep':>10s} "
                 f"{'Char/1Kw':>10s} {'UniqChar':>10s} {'CharEnt':>10s}")
    for cond in ["trn", "hia", "emb", "rag", "nop", "rand"]:
        runs = [m for m in by_condition.get(cond, []) if m.novel == "bleak_house"]
        if not runs:
            continue
        n = len(runs)
        avg_words = sum(m.total_words for m in runs) / n
        avg_quotes = sum(m.quote_count for m in runs) / n
        avg_char_density = sum(
            m.character_mentions / m.total_words * 1000
            if m.total_words else 0 for m in runs
        ) / n
        avg_uniq = sum(len(m.unique_characters) for m in runs) / n
        avg_entropy = sum(
            compute_char_entropy_from_text(runs_dir / m.run_name, m.novel)
            for m in runs
        ) / n
        lines.append(
            f"{cond:>12s} {n:>4d} {avg_words:>10.0f} {avg_quotes:>10.1f} "
            f"{avg_char_density:>10.1f} {avg_uniq:>10.1f} {avg_entropy:>10.2f}"
        )
    lines.append("")

    # --- Quote verification ---
    lines.append("TABLE 4: QUOTE VERIFICATION (fuzzy 5-word subsequence)")
    lines.append("-" * 72)

    # Cache source texts
    source_cache: dict[str, str] = {}
    for novel_key in ["bleak_house", "our_mutual_friend", "mill_on_the_floss",
                      "north_and_south", "passage_to_india"]:
        source_cache[novel_key] = load_source_text(novel_key, runs_dir)
        logger.info("Loaded source text for %s (%d chars)", novel_key,
                     len(source_cache[novel_key]))

    # BH quote verification by condition
    lines.append("Bleak House:")
    for cond in ["trn", "hia", "emb", "rag", "nop", "rand"]:
        runs = [m for m in by_condition.get(cond, []) if m.novel == "bleak_house"]
        if not runs:
            continue
        total_verified = 0
        total_quotes = 0
        for m in runs:
            v, t = verify_quotes(runs_dir / m.run_name, m.novel, source_cache["bleak_house"])
            total_verified += v
            total_quotes += t
        rate = total_verified / total_quotes * 100 if total_quotes else 0
        lines.append(f"  {cond:>8s}: {rate:5.1f}% ({total_verified}/{total_quotes})")
    lines.append("")

    # Cross-novel quote verification
    lines.append("Cross-novel:")
    for novel_key, novel_name in [
        ("bleak_house", "Bleak House"),
        ("our_mutual_friend", "Our Mutual Friend"),
        ("mill_on_the_floss", "Mill on the Floss"),
        ("north_and_south", "North and South"),
        ("passage_to_india", "A Passage to India"),
    ]:
        source = source_cache.get(novel_key, "")
        if not source:
            continue
        rates = {}
        for cond in ["trn", "emb", "nop"]:
            runs = [m for m in all_metrics
                    if m.novel == novel_key and m.condition == cond]
            if not runs:
                continue
            tv, tq = 0, 0
            for m in runs:
                v, t = verify_quotes(runs_dir / m.run_name, m.novel, source)
                tv += v
                tq += t
            rates[cond] = (tv / tq * 100 if tq else 0, tv, tq)
        if rates:
            parts = []
            for c in ["trn", "emb", "nop"]:
                if c in rates:
                    r, v, t = rates[c]
                    parts.append(f"{c}={r:.0f}%")
            gap = 0
            grounded = max(rates.get("trn", (0,))[0], rates.get("emb", (0,))[0])
            ungrounded = rates.get("nop", (0,))[0]
            gap = grounded - ungrounded
            lines.append(f"  {novel_name:25s} {' '.join(parts):30s} gap=+{gap:.0f}")
    lines.append("")

    # --- Expert airtime ---
    lines.append("TABLE 8: EXPERT AIRTIME (transport condition, % of expert words)")
    lines.append("-" * 72)
    for novel_key, novel_name in [
        ("our_mutual_friend", "OMF"),
        ("mill_on_the_floss", "MoF"),
        ("north_and_south", "NaS"),
        ("passage_to_india", "PtI"),
    ]:
        runs = [m for m in all_metrics
                if m.novel == novel_key and m.condition == "trn"]
        if not runs:
            continue
        # Aggregate speaker words
        total_expert_words: Counter = Counter()
        for m in runs:
            for speaker, words in m.speaker_words.items():
                if speaker != "Host":
                    total_expert_words[speaker] += words
        grand_total = sum(total_expert_words.values())
        if grand_total == 0:
            continue
        lines.append(f"  {novel_name}:")
        for speaker, words in total_expert_words.most_common():
            pct = words / grand_total * 100
            lines.append(f"    {speaker:30s} {pct:5.1f}%")
    lines.append("")

    # --- Conversational design ---
    lines.append("TABLE 9: CONVERSATIONAL DESIGN")
    lines.append("-" * 72)
    all_with_transitions = [m for m in all_metrics if m.total_transitions > 0]
    if all_with_transitions:
        n = len(all_with_transitions)
        avg_e2e = sum(
            m.expert_to_expert_transitions / m.total_transitions * 100
            if m.total_transitions else 0
            for m in all_with_transitions
        ) / n
        avg_host = sum(
            m.host_turns / m.total_turns * 100 if m.total_turns else 0
            for m in all_with_transitions
        ) / n
        avg_quote_pattern = sum(
            m.quote_pattern_ok / m.total_quotes * 100 if m.total_quotes else 0
            for m in all_with_transitions
        ) / n
        avg_reactive = sum(m.reactive_markers for m in all_with_transitions) / n
        tts_all = [r for m in all_with_transitions for r in m.tts_rates]
        tts_sigma = (
            (sum((r - sum(tts_all) / len(tts_all)) ** 2 for r in tts_all) / len(tts_all)) ** 0.5
            if tts_all else 0
        )
        lines.append(f"  Episodes analyzed: {n}")
        lines.append(f"  Expert→expert transitions:  {avg_e2e:.1f}%")
        lines.append(f"  Host turn fraction:         {avg_host:.1f}%")
        lines.append(f"  Quote pattern compliance:   {avg_quote_pattern:.1f}%")
        lines.append(f"  TTS rate σ:                 {tts_sigma:.3f}")
        lines.append(f"  Reactive markers/episode:   {avg_reactive:.1f}")
    lines.append("")

    # --- Material disjointness (transport vs embedding, BH) ---
    lines.append("TABLE 6: MATERIAL DISJOINTNESS (BH, transport↔embedding)")
    lines.append("-" * 72)
    # Match panels between transport and embedding
    trn_runs = {m.panel: m for m in all_metrics
                if m.novel == "bleak_house" and m.condition == "trn"}
    emb_runs = {m.panel: m for m in all_metrics
                if m.novel == "bleak_house" and m.condition == "emb"}
    common_panels = set(trn_runs.keys()) & set(emb_runs.keys())

    if common_panels:
        jaccards_passage = []
        jaccards_chapter = []
        for panel in sorted(common_panels):
            t = trn_runs[panel]
            e = emb_runs[panel]
            jp = passage_jaccard(t.passage_ids, e.passage_ids)
            jc = passage_jaccard(t.chapter_ids, e.chapter_ids)
            jaccards_passage.append(jp)
            jaccards_chapter.append(jc)
        avg_jp = sum(jaccards_passage) / len(jaccards_passage)
        avg_jc = sum(jaccards_chapter) / len(jaccards_chapter)
        lines.append(f"  Panels compared: {len(common_panels)}")
        lines.append(f"  Passage Jaccard (mean): {avg_jp:.3f}")
        lines.append(f"  Chapter Jaccard (mean): {avg_jc:.3f}")
    else:
        lines.append("  No matching panels between transport and embedding")
    lines.append("")

    # Cross-novel disjointness
    lines.append("TABLE 7: MATERIAL DISJOINTNESS (cross-novel)")
    lines.append("-" * 72)
    for novel_key, novel_name in [
        ("bleak_house", "Bleak House"),
        ("our_mutual_friend", "Our Mutual Friend"),
        ("mill_on_the_floss", "Mill on the Floss"),
        ("north_and_south", "North and South"),
        ("passage_to_india", "A Passage to India"),
    ]:
        t_runs = {m.panel: m for m in all_metrics
                  if m.novel == novel_key and m.condition == "trn"}
        e_runs = {m.panel: m for m in all_metrics
                  if m.novel == novel_key and m.condition == "emb"}
        common = set(t_runs.keys()) & set(e_runs.keys())
        if not common:
            continue
        jps = [passage_jaccard(t_runs[p].passage_ids, e_runs[p].passage_ids)
               for p in common]
        jcs = [passage_jaccard(t_runs[p].chapter_ids, e_runs[p].chapter_ids)
               for p in common]
        lines.append(f"  {novel_name:25s} Pass.J={sum(jps)/len(jps):.3f}  "
                     f"Ch.J={sum(jcs)/len(jcs):.3f}  (n={len(common)})")
    lines.append("")

    # --- Write report ---
    report_path = out_dir / f"evaluation_{tag}.txt"
    report_text = "\n".join(lines)
    report_path.write_text(report_text)
    logger.info("Wrote %s", report_path)

    # Also write condition summary CSV
    summary_path = out_dir / "cross_novel_aggregate" / "novel_condition_summary.csv"
    with open(summary_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["novel", "condition", "n_runs", "avg_words", "avg_quotes",
                     "avg_char_density", "avg_uniq_chars", "avg_entropy",
                     "quote_verification_pct"])
        for novel_key in ["bleak_house", "our_mutual_friend", "mill_on_the_floss",
                          "north_and_south", "passage_to_india"]:
            source = source_cache.get(novel_key, "")
            for cond in ["trn", "hia", "emb", "rag", "nop", "rand", "ext"]:
                runs = [m for m in all_metrics
                        if m.novel == novel_key and m.condition == cond]
                if not runs:
                    continue
                n = len(runs)
                avg_w = sum(m.total_words for m in runs) / n
                avg_q = sum(m.quote_count for m in runs) / n
                avg_cd = sum(
                    m.character_mentions / m.total_words * 1000
                    if m.total_words else 0 for m in runs
                ) / n
                avg_uc = sum(len(m.unique_characters) for m in runs) / n
                avg_ent = sum(
                    compute_char_entropy_from_text(runs_dir / m.run_name, m.novel)
                    for m in runs
                ) / n
                # Quote verification
                tv, tq = 0, 0
                if source:
                    for m in runs:
                        v, t = verify_quotes(runs_dir / m.run_name, m.novel, source)
                        tv += v
                        tq += t
                qv_pct = tv / tq * 100 if tq else 0
                w.writerow([novel_key, cond, n, f"{avg_w:.0f}", f"{avg_q:.1f}",
                           f"{avg_cd:.1f}", f"{avg_uc:.1f}", f"{avg_ent:.2f}",
                           f"{qv_pct:.1f}"])
    logger.info("Wrote %s", summary_path)

    print(report_text)


if __name__ == "__main__":
    main()
