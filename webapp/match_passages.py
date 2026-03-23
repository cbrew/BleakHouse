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
    return "confabulation"


def find_best_match(
    quote_text: str,
    passages: list[dict],
) -> tuple[str, float, dict] | None:
    """Find the passage that best matches a quote.

    Returns (passage_id, match_ratio, passage_dict) or None if no passages.
    """
    quote_words = _normalise(quote_text)
    if len(quote_words) < 3:
        return None

    best_id = ""
    best_ratio = 0.0
    best_passage = {}

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

    if not best_id:
        return None
    return best_id, best_ratio, best_passage


def match_episode_quotes(
    episode: dict,
    passages: list[dict],
) -> dict:
    """Match all quotes in an episode to source passages.

    Returns a dict with:
      matched_passages: {passage_id: {text, chapter_id, ..., match_ratio, match_category, matched_quotes}}
      utterance_matches: [(seg_idx, turn_idx, utt_idx, passage_id, match_ratio, match_category)]
    """
    matched_passages: dict[str, dict] = {}
    utterance_matches: list[tuple[int, int, int, str, float, str]] = []

    for si, seg in enumerate(episode.get("segments", [])):
        for ti, turn in enumerate(seg.get("turns", [])):
            for ui, utt in enumerate(turn.get("utterances", [])):
                is_quote = utt.get("is_quote", False)
                quote_mode = utt.get("quote_mode", "none")
                if not is_quote and quote_mode != "reading":
                    continue

                text = utt.get("text", "").strip().lstrip("> ").strip('"').strip("'")
                result = find_best_match(text, passages)
                if result is None:
                    utterance_matches.append((si, ti, ui, "", 0.0, "confabulation"))
                    continue

                pid, ratio, passage = result
                category = categorise(ratio)
                utterance_matches.append((si, ti, ui, pid, ratio, category))

                if pid not in matched_passages:
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
