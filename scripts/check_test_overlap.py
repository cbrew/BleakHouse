"""Verify held-out test sentences are vocabulary-disjoint from a ref's transcript.

Tokenises the ref transcript and each test sentence, removes a small set of
function words, and reports any content-word overlap. Fails with non-zero
exit if any sentence has overlapping content words — the test set isn't
held-out if its words came from the training data.

Usage:
    uv run python scripts/check_test_overlap.py \\
        --ref data/voice_refs/v1/Host/ref.json \\
        --test data/voice_refs/v1/test_sentences.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


# Function words / common verbs / connectives. Overlap on these is unavoidable
# and not informative.
STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "and", "or", "but", "so", "as", "if", "then", "than", "that", "this",
    "these", "those", "it", "its", "of", "to", "in", "on", "at", "by",
    "for", "with", "from", "into", "out", "up", "down", "over", "under",
    "i", "you", "he", "she", "we", "they", "me", "him", "her", "us", "them",
    "my", "your", "his", "their", "our", "what", "who", "whom", "which",
    "where", "when", "why", "how", "not", "no", "yes", "all", "any", "some",
    "do", "does", "did", "have", "has", "had", "will", "would", "can",
    "could", "should", "shall", "may", "might", "must", "one", "two",
    "first", "second", "very", "just", "also", "only", "even", "because",
    "before", "after", "while", "until",
    # very common verbs / state words
    "is", "are", "was", "becomes", "became", "go", "goes", "went", "say",
    "says", "said", "see", "sees", "saw", "look", "looks", "know", "knew",
    "want", "wants", "wanted", "make", "makes", "made", "take", "takes",
    "took", "come", "comes", "came",
    # commonly used connecting words in our register
    "well", "actually", "really", "right", "okay", "ok",
    # very common adverbs that aren't accent diagnostics
    "about", "around", "across", "back",
}


def tokenize(text: str) -> set[str]:
    text = text.lower()
    # Replace em-dashes and hyphens with spaces, then split on non-letters.
    text = text.replace("—", " ").replace("-", " ")
    tokens = re.findall(r"[a-z']+", text)
    return {t for t in tokens if t and t not in STOPWORDS and len(t) > 2}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ref", required=True, type=Path)
    p.add_argument("--test", required=True, type=Path)
    p.add_argument("--max-overlap", type=int, default=0,
                   help="fail if any sentence has more overlap content words than this (default 0)")
    args = p.parse_args()

    ref = json.loads(args.ref.read_text())
    ref_vocab = tokenize(ref["transcript"])
    print(f"ref transcript content vocab: {len(ref_vocab)} words")

    test = json.loads(args.test.read_text())
    failed = 0
    for s in test["sentences"]:
        sent_vocab = tokenize(s["text"])
        overlap = sorted(sent_vocab & ref_vocab)
        diag_in_ref = sorted(set(d.lower() for d in s.get("diagnostics", [])) & ref_vocab)
        marker = "OK" if len(overlap) <= args.max_overlap else "FAIL"
        if marker == "FAIL":
            failed += 1
        print(f"\n  [{marker}] {s['id']:14s} ({s['category']})")
        print(f"          {s['text']}")
        print(f"          overlap ({len(overlap)}): {overlap if overlap else '—'}")
        if diag_in_ref:
            print(f"          DIAGNOSTIC IN REF: {diag_in_ref}")

    print()
    if failed:
        print(f"FAIL: {failed} of {len(test['sentences'])} sentences have overlap > {args.max_overlap}")
        sys.exit(1)
    print(f"OK: all {len(test['sentences'])} sentences are content-disjoint from the ref")


if __name__ == "__main__":
    main()
