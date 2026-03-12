#!/usr/bin/env python3
"""Quote audit across all five pipeline conditions.

Two-phase analysis:
  1. Extract attempted quotes from podcast scripts (both tagged and inline)
  2. Verify each against the full Bleak House text using fuzzy matching

Output: reports/quote_audit/ with per-run details and aggregate summary.

Usage:
    uv run python scripts/quote_audit.py [--threshold 0.75] [--min-length 20]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import spacy

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DATA_DIR = Path("data")
RUNS_DIR = DATA_DIR / "runs"
PASSAGES_FILE = DATA_DIR / "passages_enriched.json"
REPORT_DIR = Path("reports/quote_audit")

# Pipeline prefixes → condition names
PIPELINE_MAP = {
    "v": "transport",
    "emb_v": "embedding",
    "rag_v": "rag",
    "nop_v": "no_passages",
    "rand_v": "random",
    "arc_v": "high_arc",
    "ext_v": "extreme",
}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ExtractedQuote:
    """A quote extracted from a podcast script."""

    run_id: str
    pipeline: str
    segment_title: str
    speaker: str
    text: str
    source: str  # "tagged" (is_quote/quote_reading) or "inline" (in quotation marks)
    sentence_type: str
    quote_intent: str  # "quotation", "emphasis", "topic", "uncertain"
    passage_ref: str | None = None


@dataclass
class VerifiedQuote(ExtractedQuote):
    """A quote with verification results."""

    best_match_ratio: float = 0.0
    best_match_chapter: str = ""
    best_match_snippet: str = ""
    verified: bool = False


@dataclass
class RunSummary:
    run_id: str
    pipeline: str
    total_quotes: int = 0
    tagged_quotes: int = 0
    inline_quotes: int = 0
    verified: int = 0
    unverified: int = 0
    verification_rate: float = 0.0


# ---------------------------------------------------------------------------
# Step 0: Build the reference corpus
# ---------------------------------------------------------------------------


def load_bleak_house_text() -> dict[str, str]:
    """Load full Bleak House text grouped by chapter from passages."""
    passages = json.load(PASSAGES_FILE.open())
    chapters: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for p in passages:
        cid = p["chapter_id"]
        if not cid.startswith("c"):
            continue
        chapters[cid].append((p["paragraph_index"], p["text"]))

    # Sort by paragraph index within each chapter, concatenate
    result = {}
    for cid, parts in chapters.items():
        parts.sort(key=lambda x: x[0])
        result[cid] = "\n".join(text for _, text in parts)
    return result


def normalise(text: str) -> str:
    """Normalise text for fuzzy comparison.

    Collapses whitespace, lowercases, strips punctuation variation,
    normalises unicode quotes/dashes to ASCII equivalents.
    """
    # Unicode normalisation
    text = unicodedata.normalize("NFKD", text)
    # Normalise quotes and dashes
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2014", "--").replace("\u2013", "-")
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    # Lowercase
    text = text.lower().strip()
    return text


# ---------------------------------------------------------------------------
# Step 1: Quote intent classification via spaCy
# ---------------------------------------------------------------------------
#
# Classification categories:
#   "quotation"  — genuine attempt to reproduce Dickens's words
#   "topic"      — phrase used as grammatical subject ("'Move on' is cruel")
#   "emphasis"   — fragment used for rhetorical emphasis, not verbatim claim
#   "repetition" — rhetorical X... X... X... pattern (0% verification rate, n=43)
#   "uncertain"  — cannot classify; treat as quotation for audit purposes
#
# Feature tiers:
#   HIGH-PRECISION LOW-RECALL — fire rarely but are nearly always correct.
#     Each has n >= 15 in training data to avoid noise from rare patterns.
#   ROBUST HEURISTIC — fire frequently with moderate precision; use in
#     combination or as defaults when high-precision features don't fire.

# Speech/writing verbs that signal genuine quotation attempt
SPEECH_VERBS = frozenset({
    "say", "write", "declare", "describe", "proclaim", "announce", "read",
    "exclaim", "cry", "whisper", "mutter", "observe", "remark", "note",
    "tell", "ask", "reply", "answer", "continue", "add", "state",
    "put", "phrase", "pen", "compose", "narrate", "intone", "recite",
})

# Nouns that introduce quotation context
INTRO_NOUNS = frozenset({
    "line", "lines", "passage", "phrase", "sentence", "words", "quote",
    "quotation", "description", "opening", "moment", "declaration",
})

# --- High-precision patterns (regex, compiled once) ---

# Ellipsis: 84% precision for non-quotation, n=75.
# Real Dickens occasionally uses "..." but the LLM's ellipsis almost always
# indicates paraphrase or rhetorical fragmentation.
_RE_ELLIPSIS = re.compile(r"\.\.\.|…")

# Word repetition with ellipsis: "which has... which has... which has"
# 86% precision, n=43. Almost always a rhetorical pattern, not Dickens.
_RE_REPETITION = re.compile(r"(\b\w{3,}\b).*\.\.\.\s*\1", re.IGNORECASE)

# Meta-framing: "Dickens writes/says", "He describes", etc. at sentence start.
# 55% precision overall BUT 95%+ precision for predicting confabulation
# when combined with no_passages condition. We classify as "quotation" but
# flag separately so the audit can weight it.
_RE_STARTS_META = re.compile(
    r"^(Dickens|He|She|The narrator|It|And (?:he|she|Dickens))\s+"
    r"(says?|writes?|describes?|tells?|gives?\s+us|puts?\s+it)",
    re.IGNORECASE,
)

# "Topic" pattern: quoted phrase followed by copula ("'Move on' is cruel")
_RE_TOPIC_AFTER = re.compile(
    r"""^["\u201d']\s*(is|was|seems?|appears?|becomes?|remains?|"""
    r"resonates?|echoes?|captures?|carries|does|runs|sounds|feels)",
    re.IGNORECASE,
)

# "Emphasis" pattern: short fragment preceded by dash/paren
_RE_EMPHASIS_BEFORE = re.compile(r"[—\u2014\-\(]\s*$")

# Colon or em-dash immediately before the quote
_RE_COLON_BEFORE = re.compile(r"[:—\u2014]\s*$")

# Speech verb at end of pre-quote text
_RE_VERB_BEFORE = re.compile(
    r"\b(writes?|says?|declares?|reads?|exclaims?|whispers?|"
    r"observes?|remarks?|puts?\s+it|wrote|said|described|adds?)\s*$",
    re.IGNORECASE,
)


def _load_nlp() -> spacy.language.Language:
    return spacy.load("en_core_web_sm", disable=["ner"])


def classify_quote_intent(
    nlp: spacy.language.Language,
    utterance_text: str,
    quote_text: str,
    source: str,
) -> str:
    """Classify whether a quoted fragment represents a genuine quotation attempt.

    Returns one of: "quotation", "topic", "emphasis", "repetition", "uncertain".

    Tagged quotes (is_quote=True) are always "quotation".
    For inline quotes, applies a cascade of features:
      1. High-precision pattern detectors (repetition, ellipsis, topic, emphasis)
      2. Quotation-positive detectors (speech verbs, colons, intro nouns)
      3. spaCy dependency parse for remaining cases
      4. Default to "uncertain"
    """
    if source == "tagged":
        return "quotation"

    # --- HIGH-PRECISION: non-quotation patterns ---

    # Repetition pattern: "X... X... X..." (precision 86%, n=43)
    if _RE_REPETITION.search(quote_text):
        return "repetition"

    # Locate quote within the utterance for context analysis
    q_idx = utterance_text.find(quote_text)
    before = utterance_text[:q_idx].rstrip() if q_idx > 0 else ""
    after_start = q_idx + len(quote_text) if q_idx >= 0 else len(utterance_text)
    after = utterance_text[after_start:after_start + 40].strip()

    # Topic pattern: quote followed by copula (precision ~90%, n=30+)
    # Match against text after the closing quote mark
    if _RE_TOPIC_AFTER.search(after):
        return "topic"

    # Emphasis: short fragment (<40 chars) preceded by dash/paren (precision ~80%, n=25+)
    if len(quote_text) < 40 and before and _RE_EMPHASIS_BEFORE.search(before):
        # But not if it ends with a speech verb (that's quotation)
        if not _RE_VERB_BEFORE.search(before):
            return "emphasis"

    # --- ROBUST HEURISTIC: quotation-positive patterns ---

    # Colon or em-dash immediately before → quotation
    if before and _RE_COLON_BEFORE.search(before):
        return "quotation"

    # Speech verb at end of pre-quote text → quotation
    if before and _RE_VERB_BEFORE.search(before):
        return "quotation"

    # Meta-framing at quote start ("Dickens writes that...")
    # This is a quotation *attempt* even if the content is paraphrased
    if _RE_STARTS_META.match(quote_text):
        return "quotation"

    # --- spaCy DEPENDENCY PARSE for remaining cases ---

    doc = nlp(utterance_text)

    # Speech/writing verb within 80 chars of the quote → quotation
    for token in doc:
        if token.lemma_.lower() in SPEECH_VERBS and token.pos_ == "VERB":
            if abs(token.idx - (q_idx if q_idx >= 0 else 0)) < 80:
                return "quotation"

    # Intro noun ("that phrase", "the passage", "these words") nearby → quotation
    for token in doc:
        if token.lemma_.lower() in INTRO_NOUNS:
            if abs(token.idx - (q_idx if q_idx >= 0 else 0)) < 50:
                return "quotation"

    # --- FALLBACK: structural heuristics ---

    # Ellipsis without repetition: often paraphrase, but sometimes real
    # (precision 84% for non-quotation, but 12 verified exceptions)
    # Classify as uncertain — let the verifier decide
    if _RE_ELLIPSIS.search(quote_text):
        return "uncertain"

    # Long inline quotes (60+ chars) without any speech-verb framing
    # are more likely to be real quotes embedded without attribution
    if len(quote_text) >= 60:
        return "quotation"

    return "uncertain"


# Regex for text inside quotation marks (curly or straight), min 15 chars
INLINE_QUOTE_RE = re.compile(
    r'["\u201c]'  # opening quote
    r"([^\"'\u201d]{15,}?)"  # content (at least 15 chars)
    r'["\u201d]',  # closing quote
    re.DOTALL,
)


def extract_quotes_from_episode(
    run_id: str,
    pipeline: str,
    episode: dict,
    min_length: int,
    nlp: spacy.language.Language,
) -> list[ExtractedQuote]:
    """Extract all attempted quotes from an episode."""
    quotes: list[ExtractedQuote] = []
    seen_texts: set[str] = set()

    for segment in episode.get("segments", []):
        seg_title = segment.get("title", "")
        for turn in segment.get("turns", []):
            speaker = turn.get("speaker", "")
            for utt in turn.get("utterances", []):
                text = utt.get("text", "")
                stype = utt.get("sentence_type", "")
                is_quote = utt.get("is_quote", False)
                quote_mode = utt.get("quote_mode", "none")
                pref = utt.get("passage_ref", None)

                # Tagged quotes: is_quote=True or sentence_type=quote_reading
                if is_quote or stype == "quote_reading" or quote_mode == "reading":
                    clean = _strip_outer_quotes(text)
                    if len(clean) >= min_length:
                        norm = normalise(clean)
                        if norm not in seen_texts:
                            seen_texts.add(norm)
                            quotes.append(
                                ExtractedQuote(
                                    run_id=run_id,
                                    pipeline=pipeline,
                                    segment_title=seg_title,
                                    speaker=speaker,
                                    text=clean,
                                    source="tagged",
                                    sentence_type=stype,
                                    quote_intent="quotation",
                                    passage_ref=pref,
                                )
                            )

                # Inline quotes: text in quotation marks within any utterance
                if not is_quote and stype != "quote_reading":
                    for m in INLINE_QUOTE_RE.finditer(text):
                        fragment = m.group(1).strip()
                        if len(fragment) >= min_length:
                            norm = normalise(fragment)
                            if norm not in seen_texts:
                                seen_texts.add(norm)
                                intent = classify_quote_intent(
                                    nlp, text, fragment, "inline"
                                )
                                quotes.append(
                                    ExtractedQuote(
                                        run_id=run_id,
                                        pipeline=pipeline,
                                        segment_title=seg_title,
                                        speaker=speaker,
                                        text=fragment,
                                        source="inline",
                                        sentence_type=stype,
                                        quote_intent=intent,
                                        passage_ref=pref,
                                    )
                                )

    return quotes


def _strip_outer_quotes(text: str) -> str:
    """Remove surrounding quotation marks if present."""
    text = text.strip()
    if len(text) >= 2:
        if (text[0] in '"\u201c' and text[-1] in '"\u201d') or (
            text[0] in "'\u2018" and text[-1] in "'\u2019"
        ):
            text = text[1:-1].strip()
    return text


# ---------------------------------------------------------------------------
# Step 2: Verify quotes against the source text
# ---------------------------------------------------------------------------

# N-gram index for fast candidate region lookup.
# We build an inverted index from word n-grams → (chapter_id, char_offset).
# For each quote, we look up its n-grams, find chapters with many hits in
# nearby positions, then run SequenceMatcher only on those small regions.

NGRAM_SIZE = 4  # 4-word shingles balance specificity vs robustness to edits


class CorpusIndex:
    """Inverted n-gram index over the normalised Bleak House text."""

    def __init__(
        self, chapters: dict[str, str], normalised_chapters: dict[str, str]
    ) -> None:
        self.chapters = chapters
        self.normalised = normalised_chapters
        # ngram → list of (chapter_id, char_offset)
        self.index: dict[str, list[tuple[str, int]]] = defaultdict(list)
        self._build()

    def _build(self) -> None:
        for cid, text in self.normalised.items():
            words = text.split()
            # Map word index → character offset
            offsets: list[int] = []
            pos = 0
            for w in words:
                idx = text.index(w, pos)
                offsets.append(idx)
                pos = idx + len(w)
            for i in range(len(words) - NGRAM_SIZE + 1):
                gram = " ".join(words[i : i + NGRAM_SIZE])
                self.index[gram].append((cid, offsets[i]))

    def find_candidates(
        self, q_norm: str, passage_ref: str | None
    ) -> list[tuple[str, int, int]]:
        """Find candidate regions (chapter, start, end) that might contain the quote.

        Returns regions sorted by number of n-gram hits (most promising first).
        """
        q_words = q_norm.split()
        q_len = len(q_norm)
        margin = max(50, q_len // 2)

        # Collect all n-gram hits
        hits: dict[str, list[int]] = defaultdict(list)  # chapter → [offsets]
        for i in range(len(q_words) - NGRAM_SIZE + 1):
            gram = " ".join(q_words[i : i + NGRAM_SIZE])
            for cid, offset in self.index.get(gram, []):
                hits[cid].append(offset)

        # Cluster nearby hits into candidate regions
        candidates: list[tuple[str, int, int, int]] = []  # (cid, start, end, n_hits)
        for cid, offsets in hits.items():
            offsets.sort()
            # Merge offsets within margin of each other
            clusters: list[list[int]] = []
            current: list[int] = [offsets[0]]
            for off in offsets[1:]:
                if off - current[-1] < q_len + margin:
                    current.append(off)
                else:
                    clusters.append(current)
                    current = [off]
            clusters.append(current)

            for cluster in clusters:
                start = max(0, cluster[0] - margin)
                end = min(len(self.normalised[cid]), cluster[-1] + q_len + margin)
                candidates.append((cid, start, end, len(cluster)))

        # Sort by hit count descending; prioritise referenced chapter
        ref_chapter = passage_ref.split(":")[0] if passage_ref else None
        candidates.sort(
            key=lambda x: (x[0] != ref_chapter, -x[3])
        )
        return [(c[0], c[1], c[2]) for c in candidates[:20]]


def _clean_quote_text(text: str) -> str:
    """Strip meta-commentary that the LLM appends to quotes.

    Tagged quotes often include framing like:
      "My Lady Dedlock, who is childless" — tucked into the sentence
      "Move on!" — the two cruelest words Dickens ever wrote
    We want only the part before the em-dash/bracket commentary.
    """
    # Split on em-dash followed by lowercase (commentary, not Dickens's own dashes)
    parts = re.split(r"\s*[—\u2014]\s+(?=[a-z])", text, maxsplit=1)
    cleaned = parts[0].strip()
    # Also strip trailing parenthetical commentary
    cleaned = re.sub(r"\s*\([^)]*\)\s*$", "", cleaned)
    return cleaned


def _extract_subquotes(text: str) -> list[str]:
    """If a tagged quote contains multiple quoted fragments, extract each.

    e.g. '"Smoke lowering." "Dogs, undistinguishable."' → two subquotes.
    Also handles a single quote with framing: 'He says: "Move on!"' → "Move on!"
    """
    # Find all quoted substrings
    fragments = re.findall(r'["\u201c]([^"\u201d]{8,}?)["\u201d]', text)
    if fragments:
        return [f.strip() for f in fragments if len(f.strip()) >= 15]
    return []


def _best_substring_ratio(
    q_norm: str, region: str
) -> tuple[float, int]:
    """Find the best-matching substring of region against q_norm.

    Instead of comparing q_norm against the entire (larger) region,
    use find_longest_match to locate the alignment point, then extract
    a window of ~q_len and score against that.

    Returns (ratio, offset_in_region).
    """
    q_len = len(q_norm)
    r_len = len(region)

    # If region is similar size to quote, compare directly
    if r_len <= q_len * 1.5:
        return SequenceMatcher(None, q_norm, region).ratio(), 0

    # Find the longest common substring to anchor alignment
    sm = SequenceMatcher(None, q_norm, region)
    match = sm.find_longest_match(0, q_len, 0, r_len)

    if match.size == 0:
        return 0.0, 0

    # The match tells us: q_norm[match.a:] aligns with region[match.b:]
    # Extract a window of q_len centred on the match in the region
    region_centre = match.b + match.size // 2
    window_start = max(0, region_centre - q_len // 2)
    window_end = min(r_len, window_start + q_len + q_len // 4)
    window_start = max(0, window_end - q_len - q_len // 4)

    window = region[window_start:window_end]
    ratio = SequenceMatcher(None, q_norm, window).ratio()
    return ratio, window_start


def verify_quote(
    quote: ExtractedQuote,
    corpus: CorpusIndex,
    threshold: float,
) -> VerifiedQuote:
    """Check whether a quote appears in the Bleak House text.

    Uses n-gram index for fast candidate lookup, then SequenceMatcher on
    focused windows. Tries the full quote first, then cleaned version,
    then sub-quotes if present.
    """
    # Build list of candidate query strings: full → cleaned → subquotes
    candidates_q: list[str] = []
    full_norm = normalise(quote.text)
    candidates_q.append(full_norm)

    cleaned = _clean_quote_text(quote.text)
    cleaned_norm = normalise(cleaned)
    if cleaned_norm != full_norm and len(cleaned_norm) >= 15:
        candidates_q.append(cleaned_norm)

    for subq in _extract_subquotes(quote.text):
        sub_norm = normalise(subq)
        if sub_norm not in candidates_q and len(sub_norm) >= 15:
            candidates_q.append(sub_norm)

    best_ratio = 0.0
    best_chapter = ""
    best_snippet = ""

    for q_norm in candidates_q:
        q_len = len(q_norm)

        # Phase 1: exact substring search
        for cid, text in corpus.normalised.items():
            if q_norm in text:
                idx = text.index(q_norm)
                orig = corpus.chapters[cid]
                snippet = orig[max(0, idx - 20) : idx + q_len + 20].strip()
                return VerifiedQuote(
                    **quote.__dict__,
                    best_match_ratio=1.0,
                    best_match_chapter=cid,
                    best_match_snippet=snippet,
                    verified=True,
                )

        # Phase 2: n-gram indexed fuzzy search with focused windowing
        regions = corpus.find_candidates(q_norm, quote.passage_ref)

        for cid, start, end in regions:
            region = corpus.normalised[cid][start:end]
            ratio, offset = _best_substring_ratio(q_norm, region)

            if ratio > best_ratio:
                best_ratio = ratio
                best_chapter = cid
                orig = corpus.chapters[cid]
                snip_start = start + offset
                snip_end = min(snip_start + q_len + 40, len(orig))
                best_snippet = orig[snip_start:snip_end].strip()

            if best_ratio >= 0.95:
                break

        if best_ratio >= 0.95:
            break

    return VerifiedQuote(
        **quote.__dict__,
        best_match_ratio=best_ratio,
        best_match_chapter=best_chapter,
        best_match_snippet=best_snippet[:200],
        verified=best_ratio >= threshold,
    )


# ---------------------------------------------------------------------------
# Pipeline classification
# ---------------------------------------------------------------------------


def classify_run(run_id: str) -> str | None:
    """Map a run directory name to a pipeline condition."""
    for prefix, pipeline in sorted(PIPELINE_MAP.items(), key=lambda x: -len(x[0])):
        if run_id.startswith(prefix):
            return pipeline
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Quote audit for five-way comparison")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.75,
        help="Fuzzy match ratio threshold for verification (default: 0.75)",
    )
    parser.add_argument(
        "--min-length",
        type=int,
        default=20,
        help="Minimum quote length in characters (default: 20)",
    )
    args = parser.parse_args()

    print("Loading spaCy model...")
    nlp = _load_nlp()

    print("Loading Bleak House text and building n-gram index...")
    chapters = load_bleak_house_text()
    normalised_chapters = {cid: normalise(text) for cid, text in chapters.items()}
    corpus = CorpusIndex(chapters, normalised_chapters)
    print(
        f"  {len(chapters)} chapters, {sum(len(t) for t in chapters.values()):,} chars, "
        f"{len(corpus.index):,} unique {NGRAM_SIZE}-grams"
    )

    # Find all runs with phase3_episode.json
    runs = sorted(RUNS_DIR.glob("*/phase3_episode.json"))
    print(f"  {len(runs)} runs found")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    all_verified: list[VerifiedQuote] = []
    summaries: list[RunSummary] = []

    for episode_path in runs:
        run_id = episode_path.parent.name
        pipeline = classify_run(run_id)
        if pipeline is None:
            continue

        episode = json.load(episode_path.open())
        quotes = extract_quotes_from_episode(
            run_id, pipeline, episode, args.min_length, nlp
        )

        if not quotes:
            summaries.append(RunSummary(run_id=run_id, pipeline=pipeline))
            continue

        tagged = sum(1 for q in quotes if q.source == "tagged")
        inline = sum(1 for q in quotes if q.source == "inline")

        # Verify each quote
        verified_quotes: list[VerifiedQuote] = []
        for q in quotes:
            vq = verify_quote(q, corpus, args.threshold)
            verified_quotes.append(vq)
        all_verified.extend(verified_quotes)

        n_verified = sum(1 for vq in verified_quotes if vq.verified)
        rate = n_verified / len(verified_quotes) if verified_quotes else 0.0

        summaries.append(
            RunSummary(
                run_id=run_id,
                pipeline=pipeline,
                total_quotes=len(quotes),
                tagged_quotes=tagged,
                inline_quotes=inline,
                verified=n_verified,
                unverified=len(quotes) - n_verified,
                verification_rate=rate,
            )
        )
        print(
            f"  {run_id}: {len(quotes)} quotes ({tagged} tagged, {inline} inline), "
            f"{n_verified}/{len(quotes)} verified ({rate:.0%})"
        )

    # Write detailed CSV
    detail_path = REPORT_DIR / "quote_details.csv"
    with detail_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "run_id", "pipeline", "segment", "speaker", "source", "sentence_type",
            "quote_intent", "passage_ref", "quote_text", "verified", "match_ratio",
            "match_chapter", "match_snippet",
        ])
        for vq in all_verified:
            w.writerow([
                vq.run_id, vq.pipeline, vq.segment_title, vq.speaker,
                vq.source, vq.sentence_type, vq.quote_intent, vq.passage_ref or "",
                vq.text[:300], vq.verified, f"{vq.best_match_ratio:.3f}",
                vq.best_match_chapter, vq.best_match_snippet[:200],
            ])
    print(f"\nDetailed results: {detail_path}")

    # Write per-run summary CSV
    run_path = REPORT_DIR / "per_run_summary.csv"
    with run_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "run_id", "pipeline", "total_quotes", "tagged", "inline",
            "verified", "unverified", "verification_rate",
        ])
        for s in sorted(summaries, key=lambda x: (x.pipeline, x.run_id)):
            w.writerow([
                s.run_id, s.pipeline, s.total_quotes, s.tagged_quotes,
                s.inline_quotes, s.verified, s.unverified,
                f"{s.verification_rate:.3f}",
            ])
    print(f"Per-run summary: {run_path}")

    # Aggregate by pipeline
    print("\n" + "=" * 72)
    print("AGGREGATE QUOTE AUDIT BY PIPELINE")
    print("=" * 72)
    pipeline_stats: dict[str, dict] = defaultdict(
        lambda: {"runs": 0, "total": 0, "tagged": 0, "inline": 0, "verified": 0}
    )
    for s in summaries:
        ps = pipeline_stats[s.pipeline]
        ps["runs"] += 1
        ps["total"] += s.total_quotes
        ps["tagged"] += s.tagged_quotes
        ps["inline"] += s.inline_quotes
        ps["verified"] += s.verified

    header = f"{'Pipeline':<15} {'Runs':>5} {'Total':>7} {'Tagged':>7} {'Inline':>7} {'Verified':>9} {'Rate':>7}"
    print(header)
    print("-" * len(header))
    for pipeline in ["transport", "embedding", "rag", "no_passages", "random"]:
        if pipeline not in pipeline_stats:
            continue
        ps = pipeline_stats[pipeline]
        rate = ps["verified"] / ps["total"] if ps["total"] else 0
        print(
            f"{pipeline:<15} {ps['runs']:>5} {ps['total']:>7} {ps['tagged']:>7} "
            f"{ps['inline']:>7} {ps['verified']:>9} {rate:>6.1%}"
        )

    # Aggregate summary CSV
    agg_path = REPORT_DIR / "pipeline_summary.csv"
    with agg_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "pipeline", "runs", "total_quotes", "tagged", "inline",
            "verified", "unverified", "verification_rate",
        ])
        for pipeline in sorted(pipeline_stats.keys()):
            if pipeline not in pipeline_stats:
                continue
            ps = pipeline_stats[pipeline]
            rate = ps["verified"] / ps["total"] if ps["total"] else 0
            w.writerow([
                pipeline, ps["runs"], ps["total"], ps["tagged"], ps["inline"],
                ps["verified"], ps["total"] - ps["verified"], f"{rate:.3f}",
            ])
    print(f"\nPipeline summary: {agg_path}")

    # Intent-based verification rates
    print(f"\n{'=' * 72}")
    print("VERIFICATION RATE BY QUOTE INTENT")
    print("=" * 72)
    intent_stats: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"total": 0, "verified": 0})
    )
    for vq in all_verified:
        intent_stats[vq.pipeline][vq.quote_intent]["total"] += 1
        if vq.verified:
            intent_stats[vq.pipeline][vq.quote_intent]["verified"] += 1

    intents = ["quotation", "topic", "emphasis", "repetition", "uncertain"]
    header = f"{'Pipeline':<15}" + "".join(f" {i:>12}" for i in intents)
    print(header)
    print("-" * len(header))
    for pipeline in ["transport", "embedding", "rag", "no_passages", "random"]:
        parts = [f"{pipeline:<15}"]
        for intent in intents:
            s = intent_stats[pipeline][intent]
            if s["total"] > 0:
                rate = s["verified"] / s["total"]
                parts.append(f" {rate:>5.0%} ({s['total']:>3})")
            else:
                parts.append(f" {'—':>11}")
        print("".join(parts))

    # Feedback loop analysis: compare verification rates by intent
    print(f"\n{'=' * 72}")
    print("INTENT CLASSIFICATION FEEDBACK")
    print("=" * 72)
    # Across all pipelines, what's the verification rate by intent?
    for intent in intents:
        total = sum(
            intent_stats[p][intent]["total"]
            for p in intent_stats
        )
        verified = sum(
            intent_stats[p][intent]["verified"]
            for p in intent_stats
        )
        if total > 0:
            rate = verified / total
            print(f"  {intent:<12}: {verified:>4}/{total:>4} verified ({rate:.0%})")
    print()
    print("  'topic', 'emphasis', and 'repetition' intents with low verification")
    print("  rates should be excluded from the confabulation count — they represent")
    print("  analytical use of phrases, not genuine quotation attempts.")
    print("  'uncertain' quotes should be included (they verify at a similar rate")
    print("  to 'quotation' when they are real quotes).")

    # --- Three-way classification of unverified quotes ---
    #
    # Not all unverified quotes are confabulations. We separate them into:
    #   1. Verifier false negatives: ratio >= 0.60, likely real but below threshold
    #   2. Detector false positives: short inline fragments or metacommentary
    #      misclassified as quotation attempts
    #   3. True confabulations: sentence-like text tagged as quotation with low ratio

    VERIFIER_FN_THRESHOLD = 0.60  # ratio cutoff for "probably real but fuzzy"
    MAX_DETECTOR_FP_LEN = 50  # short inline fragments are likely detector FPs
    META_RE = re.compile(
        r"(Dickens|the narrator|the novel|the text|he writes|she writes|this)",
        re.IGNORECASE,
    )

    def classify_unverified(vq: VerifiedQuote) -> str:
        """Classify an unverified quote into one of three categories."""
        # High ratio → verifier couldn't quite match but it's probably real
        if vq.best_match_ratio >= VERIFIER_FN_THRESHOLD:
            return "verifier_false_negative"
        # Short inline fragments or metacommentary → detector false positive
        if vq.source == "inline" and (
            len(vq.text) < MAX_DETECTOR_FP_LEN
            or META_RE.search(vq.text[:60])
        ):
            return "detector_false_positive"
        # Non-quotation intent → detector false positive by definition
        if vq.quote_intent not in ("quotation", "uncertain"):
            return "detector_false_positive"
        return "confabulation"

    unverified_all = [vq for vq in all_verified if not vq.verified]
    if unverified_all:
        # Classify each unverified quote
        categories: dict[str, list[VerifiedQuote]] = defaultdict(list)
        for vq in unverified_all:
            categories[classify_unverified(vq)].append(vq)

        print(f"\n{'=' * 72}")
        print("THREE-WAY CLASSIFICATION OF UNVERIFIED QUOTES")
        print("=" * 72)
        for cat in ["verifier_false_negative", "detector_false_positive", "confabulation"]:
            n = len(categories[cat])
            print(f"  {cat:<28}: {n:>4} quotes")
        print(f"  {'total unverified':<28}: {len(unverified_all):>4} quotes")

        # Adjusted verification rates per pipeline
        print(f"\n{'=' * 72}")
        print("ADJUSTED VERIFICATION RATES (excluding detector FPs & verifier FNs)")
        print("=" * 72)
        print("  Counts confabulations only against genuine quotation attempts.")
        print()

        # Build per-pipeline adjusted stats
        adj_header = f"{'Pipeline':<15} {'Total':>7} {'Verified':>9} {'Vrfr FN':>8} {'Det FP':>7} {'Confab':>7} {'Raw%':>6} {'Adj%':>6}"
        print(adj_header)
        print("-" * len(adj_header))
        for pipeline in sorted(pipeline_stats.keys()):
            pq = [vq for vq in all_verified if vq.pipeline == pipeline]
            if not pq:
                continue
            total = len(pq)
            verified = sum(1 for vq in pq if vq.verified)
            unv = [vq for vq in pq if not vq.verified]
            vfn = sum(1 for vq in unv if classify_unverified(vq) == "verifier_false_negative")
            dfp = sum(1 for vq in unv if classify_unverified(vq) == "detector_false_positive")
            confab = sum(1 for vq in unv if classify_unverified(vq) == "confabulation")
            raw_rate = verified / total if total else 0
            # Adjusted: (verified + verifier_FN) / (total - detector_FP)
            adj_denom = total - dfp
            adj_rate = (verified + vfn) / adj_denom if adj_denom else 0
            print(
                f"{pipeline:<15} {total:>7} {verified:>9} {vfn:>8} {dfp:>7} {confab:>7} "
                f"{raw_rate:>5.1%} {adj_rate:>5.1%}"
            )

        # Write three-way CSV
        threeway_path = REPORT_DIR / "unverified_classification.csv"
        with threeway_path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "run_id", "pipeline", "category", "source", "quote_intent",
                "match_ratio", "text_length", "quote_text",
            ])
            for vq in sorted(unverified_all, key=lambda x: (x.pipeline, x.best_match_ratio)):
                w.writerow([
                    vq.run_id, vq.pipeline, classify_unverified(vq),
                    vq.source, vq.quote_intent,
                    f"{vq.best_match_ratio:.3f}", len(vq.text), vq.text[:300],
                ])
        print(f"\nUnverified classification: {threeway_path}")

    # Show worst confabulations (only genuine quotation-intent, true confabulations)
    confabulations = [
        vq for vq in unverified_all
        if classify_unverified(vq) == "confabulation"
    ] if unverified_all else []
    if confabulations:
        confabulations.sort(key=lambda x: x.best_match_ratio)
        print(f"\n{'=' * 72}")
        print(f"WORST CONFABULATIONS (true confabulations only, n={len(confabulations)})")
        print("=" * 72)
        for vq in confabulations[:20]:
            print(
                f"  [{vq.pipeline}] {vq.run_id} ({vq.source})"
                f" ratio={vq.best_match_ratio:.3f}"
            )
            print(f"    Quote: {vq.text[:120]}")
            if vq.best_match_snippet:
                print(f"    Best:  {vq.best_match_snippet[:120]}")
            print()


if __name__ == "__main__":
    main()
