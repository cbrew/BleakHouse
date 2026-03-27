"""Post-hoc passage matching for ungrounded podcast runs.

For each quote utterance in a no-passages episode, finds the best matching
passage from the novel's enriched corpus and scores the match quality.

Match categories:
  verified     — ratio >= 0.6, genuine quote from the novel
  paraphrase   — ratio 0.3–0.6, recognisable but altered
  confabulation — ratio < 0.3, no real source found
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

# Novel title → enriched passages path
_NOVEL_PATHS: dict[str, str] = {
    "Bleak House": "passages_enriched.json",
    "Our Mutual Friend": "novels/our_mutual_friend/passages_enriched.json",
    "The Mill on the Floss": "novels/mill_on_the_floss/passages_enriched.json",
    "North and South": "novels/north_and_south/passages_enriched.json",
    "A Passage to India": "novels/passage_to_india/passages_enriched.json",
    "Hard Times": "novels/hard_times/passages_enriched.json",
    "Middlemarch": "novels/middlemarch/passages_enriched.json",
    "Daniel Deronda": "novels/daniel_deronda/passages_enriched.json",
    "David Copperfield": "novels/david_copperfield/passages_enriched.json",
    "Cranford": "novels/cranford/passages_enriched.json",
    "No Name": "novels/no_name/passages_enriched.json",
    "New Grub Street": "novels/new_grub_street/passages_enriched.json",
    "The Odd Women": "novels/odd_women/passages_enriched.json",
    "Miss Marjoribanks": "novels/miss_marjoribanks/passages_enriched.json",
    "Hester": "novels/hester/passages_enriched.json",
}


def load_enriched_passages(novel_title: str) -> list[dict]:
    """Load all enriched passages for a novel."""
    novel = novel_title.replace(": A Literary Discussion", "")
    rel_path = _NOVEL_PATHS.get(novel)
    if not rel_path:
        return []
    path = DATA_DIR / rel_path
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


def _normalise(text: str) -> list[str]:
    """Lowercase, strip punctuation, split into words."""
    cleaned = text.lower()
    for ch in '.,;:!?"\'-—()[]{}…""''':
        cleaned = cleaned.replace(ch, " ")
    return cleaned.split()


def score_match(quote_words: list[str], passage_words: list[str], window: int = 5) -> float:
    """Score how well a quote matches a passage.

    Returns the fraction of quote windows that match somewhere in the passage.
    """
    if len(quote_words) < window:
        # Short quote: check if all words appear in passage
        passage_set = set(passage_words)
        if not quote_words:
            return 0.0
        hits = sum(1 for w in quote_words if w in passage_set)
        return hits / len(quote_words)

    passage_text = " ".join(passage_words)
    total_windows = len(quote_words) - window + 1
    matched = 0
    for i in range(total_windows):
        subseq = " ".join(quote_words[i:i + window])
        if subseq in passage_text:
            matched += 1
    return matched / total_windows if total_windows > 0 else 0.0


def categorise(ratio: float) -> str:
    if ratio >= 0.6:
        return "verified"
    if ratio >= 0.3:
        return "paraphrase"
    if ratio >= 0.1:
        return "distant_echo"
    if ratio > 0:
        return "no_clear_source"
    return "invented"


def _build_autopsy(quote_text: str, passages: list[dict]) -> dict:
    """Build a confabulation autopsy for a zero-match quote.

    Reports how many words from the quote appear anywhere in the novel,
    which distinctive words (length >= 5) are absent, and finds the
    thematically closest passage by character/theme overlap.
    """
    quote_words = _normalise(quote_text)
    quote_set = set(quote_words)

    # Build vocabulary of all words across all passages
    novel_vocab: set[str] = set()
    for p in passages:
        novel_vocab.update(_normalise(p.get("text", "")))

    words_in_novel = quote_set & novel_vocab
    words_absent = quote_set - novel_vocab
    # "Distinctive" = 5+ chars, not common function words
    distinctive_absent = sorted(
        w for w in words_absent if len(w) >= 5
    )

    return {
        "quote_words": len(quote_set),
        "words_in_novel": len(words_in_novel),
        "words_absent": len(words_absent),
        "distinctive_absent": distinctive_absent[:10],
        "pct_in_novel": round(len(words_in_novel) / max(len(quote_set), 1) * 100),
    }


def find_best_match(
    quote_text: str,
    passages: list[dict],
) -> tuple[str, float, dict, dict | None]:
    """Find the passage that best matches a quote.

    Always returns (passage_id, match_ratio, passage_dict, autopsy_or_none).
    Returns ("", 0.0, {}, None) only if quote is too short or no passages exist.
    """
    quote_words = _normalise(quote_text)
    if not quote_words or not passages:
        return ("", 0.0, {}, None)

    best_id = ""
    best_ratio = 0.0
    best_passage: dict = {}

    # Also track the best passage by individual word overlap (for ratio=0 fallback)
    quote_set = set(quote_words)
    best_word_overlap = 0
    best_overlap_id = ""
    best_overlap_passage: dict = {}

    for p in passages:
        p_text = p.get("text", "")
        if not p_text:
            continue
        p_words = _normalise(p_text)
        ratio = score_match(quote_words, p_words)

        if ratio > best_ratio:
            best_ratio = ratio
            best_id = p.get("passage_id", "")
            best_passage = p

        # Track word overlap for thematic fallback
        overlap = len(quote_set & set(p_words))
        if overlap > best_word_overlap:
            best_word_overlap = overlap
            best_overlap_id = p.get("passage_id", "")
            best_overlap_passage = p

    # If window matching found something, use it
    if best_id and best_ratio > 0:
        return (best_id, best_ratio, best_passage, None)

    # Zero window-match: use the passage with most individual word overlap
    # and build an autopsy
    autopsy = _build_autopsy(quote_text, passages)
    if best_overlap_id:
        autopsy["fallback_reason"] = "word_overlap"
        autopsy["shared_words"] = best_word_overlap
        return (best_overlap_id, 0.0, best_overlap_passage, autopsy)

    # No word overlap at all — use first passage with text as arbitrary fallback
    autopsy["fallback_reason"] = "no_overlap"
    for p in passages:
        if p.get("text") and p.get("passage_id"):
            return (p["passage_id"], 0.0, p, autopsy)

    return ("", 0.0, {}, autopsy)


def match_episode_quotes(
    episode: dict,
    passages: list[dict],
) -> dict:
    """Match all quotes in an episode to source passages.

    Every quote gets a passage_ref (even at ratio 0) so there is always
    something clickable for drill-down.

    Returns a dict with:
      matched_passages: {passage_id: {text, chapter_id, ..., match_ratio, match_category, ...}}
      utterance_matches: [(seg_idx, turn_idx, utt_idx, passage_id, match_ratio, match_category, autopsy)]
    """
    matched_passages: dict[str, dict] = {}
    utterance_matches: list[tuple[int, int, int, str, float, str, dict | None]] = []

    for si, seg in enumerate(episode.get("segments", [])):
        for ti, turn in enumerate(seg.get("turns", [])):
            for ui, utt in enumerate(turn.get("utterances", [])):
                is_quote = utt.get("is_quote", False)
                quote_mode = utt.get("quote_mode", "none")
                if not is_quote and quote_mode != "reading":
                    continue

                text = utt.get("text", "").strip().lstrip("> ").strip('"').strip("'")
                pid, ratio, passage, autopsy = find_best_match(text, passages)
                category = categorise(ratio)
                utterance_matches.append((si, ti, ui, pid, ratio, category, autopsy))

                if pid and pid not in matched_passages:
                    e = passage.get("enrichment", {})
                    matched_passages[pid] = {
                        "text": passage.get("text", ""),
                        "summary": e.get("summary", ""),
                        "best_quote": e.get("best_quote", ""),
                        "chapter_id": passage.get("chapter_id", ""),
                        "characters_present": e.get("characters_present", []),
                        "themes": e.get("themes", []),
                        "emotional_register": e.get("emotional_register", []),
                        "narrator": e.get("narrator", ""),
                        "matched_quotes": [],
                    }
                if pid:
                    matched_passages[pid]["matched_quotes"].append({
                        "text": text,
                        "match_ratio": round(ratio, 3),
                        "match_category": category,
                    })

    # Add the best match_ratio and category to each passage entry
    for pid, pdata in matched_passages.items():
        quotes = pdata["matched_quotes"]
        best = max(quotes, key=lambda q: q["match_ratio"])
        pdata["match_ratio"] = best["match_ratio"]
        pdata["match_category"] = best["match_category"]

    return {
        "matched_passages": matched_passages,
        "utterance_matches": utterance_matches,
    }
