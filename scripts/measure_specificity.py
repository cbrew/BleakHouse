"""Measure textual engagement specificity: transport vs embedding pipeline.

Metrics:
1. Quote recovery rate: fraction of assigned passages' best_quote appearing in script
2. Character mention density: character-name mentions per 1,000 words
3. Unique characters per episode
4. Chapter reference density: chapter references per 1,000 words
5. Sentence specificity: proportion of sentences with proper nouns or quoted phrases
"""

import json
import re
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parent.parent / "data" / "runs"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

PAIRS = [
    ("v01_baseline", "emb_v01_baseline", "baseline"),
    ("v02_more_jo", "emb_v02_more_jo", "more_jo"),
    ("v05_craft_v2", "emb_v05_craft_v2", "craft_v2"),
    ("v10_conservative", "emb_v10_conservative", "conservative"),
    ("v12_radical_panel", "emb_v12_radical_panel", "radical_panel"),
    ("v14_trevelyan_for_woodcourt", "emb_v14_trevelyan_for_woodcourt", "trevelyan_woodcourt"),
    ("v18_trevelyan_rosen", "emb_v18_trevelyan_rosen", "trevelyan_rosen"),
    ("v19_all_swapped", "emb_v19_all_swapped", "all_swapped"),
]

# Bleak House character names (first or last names that are distinctive)
CHARACTERS = {
    "Esther", "Summerson", "Jarndyce", "Richard", "Carstone", "Ada", "Clare",
    "Dedlock", "Lady Dedlock", "Sir Leicester", "Tulkinghorn", "Bucket",
    "Guppy", "Skimpole", "Jo", "Nemo", "Hawdon", "Woodcourt", "Jellyby",
    "Caddy", "Snagsby", "Mrs Snagsby", "Krook", "Miss Flite", "Flite",
    "Vholes", "Hortense", "Rosa", "Boythorn", "Chadband", "Mrs Chadband",
    "Turveydrop", "Prince", "Smallweed", "Grandfather Smallweed",
    "Charley", "Neckett", "Gridley", "George", "Rouncewell", "Trooper George",
    "Kenge", "Quale", "Pardiggle", "Mrs Pardiggle", "Watt",
    "Phil", "Squod", "Mercury", "Volumnia", "Bagnet",
    "Mrs Bagnet", "Peepy", "Tony Jobling",
}
# Build regex: match any character name as whole word
_char_pattern = "|".join(re.escape(c) for c in sorted(CHARACTERS, key=len, reverse=True))
CHAR_RE = re.compile(rf"\b({_char_pattern})\b", re.IGNORECASE)

CHAPTER_RE = re.compile(r"\b[Cc]hapter\s+(?:[A-Z][a-z]+|[IVXLCDM]+|\d+)\b")
PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-z]{2,}")
QUOTED_RE = re.compile(r'["\u201c].+?["\u201d]')


def load_episode(variant: str) -> dict | None:
    path = RUNS_DIR / variant / "phase3_episode.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def load_assignments(variant: str) -> list[dict]:
    path = RUNS_DIR / variant / "phase1_assignments.json"
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)["assignments"]


def episode_text(episode: dict) -> str:
    parts = []
    for seg in episode["segments"]:
        for turn in seg["turns"]:
            for utt in turn["utterances"]:
                parts.append(utt["text"])
    return " ".join(parts)


def word_count(text: str) -> int:
    return len(text.split())


def quote_recovery(assignments: list[dict], text: str) -> tuple[int, int]:
    """Check how many best_quotes appear as 5-word subsequences in text."""
    text_lower = text.lower()
    found = 0
    total = 0
    for a in assignments:
        bq = a.get("best_quote", "")
        if not bq or len(bq) < 10:
            continue
        total += 1
        words = bq.lower().split()
        if len(words) >= 5:
            # Check 5-word subsequence
            subseq = " ".join(words[:5])
            if subseq in text_lower:
                found += 1
            else:
                # Try middle 5 words
                mid = len(words) // 2 - 2
                subseq2 = " ".join(words[max(0, mid):max(0, mid) + 5])
                if subseq2 in text_lower:
                    found += 1
        elif bq.lower() in text_lower:
            found += 1
    return found, total


def character_mentions(text: str) -> tuple[int, set[str]]:
    matches = CHAR_RE.findall(text)
    count = len(matches)
    unique = {m.title() for m in matches}
    return count, unique


def chapter_references(text: str) -> int:
    return len(CHAPTER_RE.findall(text))


def sentence_specificity(text: str) -> float:
    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
    if not sentences:
        return 0.0
    specific = 0
    for s in sentences:
        if PROPER_NOUN_RE.search(s) or QUOTED_RE.search(s):
            specific += 1
    return specific / len(sentences)


def textual_deixis(text: str) -> int:
    """Count phrases like 'that line', 'notice how', 'Dickens gives'."""
    patterns = [
        r"\bthat line\b", r"\bthat passage\b", r"\bnotice how\b",
        r"\bDickens gives\b", r"\bDickens shows\b", r"\bDickens uses\b",
        r"\blook at\b", r"\bhere we see\b", r"\bthis moment\b",
        r"\bthat phrase\b", r"\bthis line\b",
    ]
    count = 0
    for p in patterns:
        count += len(re.findall(p, text, re.IGNORECASE))
    return count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

print("=" * 78)
print("TEXTUAL ENGAGEMENT SPECIFICITY: TRANSPORT vs EMBEDDING")
print("=" * 78)

t_totals = {"qr_found": 0, "qr_total": 0, "char_mentions": 0, "words": 0,
            "unique_chars": [], "chapter_refs": 0, "specificity": [],
            "deixis": 0, "quotes_direct": 0}
e_totals = {"qr_found": 0, "qr_total": 0, "char_mentions": 0, "words": 0,
            "unique_chars": [], "chapter_refs": 0, "specificity": [],
            "deixis": 0, "quotes_direct": 0}

header = f"  {'Config':<22s} {'Metric':<28s} {'Transport':>10s} {'Embedding':>10s} {'Winner':>10s}"

for tv, ev, label in PAIRS:
    t_ep = load_episode(tv)
    e_ep = load_episode(ev)
    if not t_ep or not e_ep:
        print(f"\n  [SKIP] {label}")
        continue

    t_assigns = load_assignments(tv)
    e_assigns = load_assignments(ev)

    t_text = episode_text(t_ep)
    e_text = episode_text(e_ep)
    t_wc = word_count(t_text)
    e_wc = word_count(e_text)

    # 1. Quote recovery
    t_qf, t_qt = quote_recovery(t_assigns, t_text)
    e_qf, e_qt = quote_recovery(e_assigns, e_text)
    t_qr = t_qf / t_qt if t_qt else 0
    e_qr = e_qf / e_qt if e_qt else 0

    # 2. Character mentions
    t_cm, t_cu = character_mentions(t_text)
    e_cm, e_cu = character_mentions(e_text)
    t_cmd = t_cm / t_wc * 1000
    e_cmd = e_cm / e_wc * 1000

    # 3. Chapter refs
    t_cr = chapter_references(t_text)
    e_cr = chapter_references(e_text)
    t_crd = t_cr / t_wc * 1000
    e_crd = e_cr / e_wc * 1000

    # 4. Sentence specificity
    t_ss = sentence_specificity(t_text)
    e_ss = sentence_specificity(e_text)

    # 5. Deixis
    t_dx = textual_deixis(t_text)
    e_dx = textual_deixis(e_text)
    t_dxd = t_dx / t_wc * 1000
    e_dxd = e_dx / e_wc * 1000

    # Accumulate
    t_totals["qr_found"] += t_qf; t_totals["qr_total"] += t_qt
    e_totals["qr_found"] += e_qf; e_totals["qr_total"] += e_qt
    t_totals["char_mentions"] += t_cm; t_totals["words"] += t_wc
    e_totals["char_mentions"] += e_cm; e_totals["words"] += e_wc
    t_totals["unique_chars"].append(len(t_cu))
    e_totals["unique_chars"].append(len(e_cu))
    t_totals["chapter_refs"] += t_cr; e_totals["chapter_refs"] += e_cr
    t_totals["specificity"].append(t_ss); e_totals["specificity"].append(e_ss)
    t_totals["deixis"] += t_dx; e_totals["deixis"] += e_dx

    print(f"\n  --- {label} (T:{t_wc} words, E:{e_wc} words) ---")
    print(f"    Quote recovery:     T={t_qf}/{t_qt} ({t_qr:.0%})   E={e_qf}/{e_qt} ({e_qr:.0%})   {'T' if t_qr > e_qr else 'E' if e_qr > t_qr else '='}")
    print(f"    Char mentions/1k:   T={t_cmd:.1f}   E={e_cmd:.1f}   {'T' if t_cmd > e_cmd else 'E'}")
    print(f"    Unique characters:  T={len(t_cu)}   E={len(e_cu)}   {'T' if len(t_cu) > len(e_cu) else 'E' if len(e_cu) > len(t_cu) else '='}")
    print(f"    Chapter refs/1k:    T={t_crd:.2f}   E={e_crd:.2f}   {'T' if t_crd > e_crd else 'E'}")
    print(f"    Sentence specif.:   T={t_ss:.3f}   E={e_ss:.3f}   {'T' if t_ss > e_ss else 'E'}")
    print(f"    Deixis/1k:          T={t_dxd:.1f}   E={e_dxd:.1f}   {'T' if t_dxd > e_dxd else 'E'}")

# Summary
print("\n" + "=" * 78)
print("AGGREGATE (8 pairs)")
print("=" * 78)

t_qr_agg = t_totals["qr_found"] / t_totals["qr_total"] if t_totals["qr_total"] else 0
e_qr_agg = e_totals["qr_found"] / e_totals["qr_total"] if e_totals["qr_total"] else 0
t_cmd_agg = t_totals["char_mentions"] / t_totals["words"] * 1000
e_cmd_agg = e_totals["char_mentions"] / e_totals["words"] * 1000
t_uc_agg = sum(t_totals["unique_chars"]) / len(t_totals["unique_chars"])
e_uc_agg = sum(e_totals["unique_chars"]) / len(e_totals["unique_chars"])
t_cr_agg = t_totals["chapter_refs"] / t_totals["words"] * 1000
e_cr_agg = e_totals["chapter_refs"] / e_totals["words"] * 1000
t_ss_agg = sum(t_totals["specificity"]) / len(t_totals["specificity"])
e_ss_agg = sum(e_totals["specificity"]) / len(e_totals["specificity"])
t_dx_agg = t_totals["deixis"] / t_totals["words"] * 1000
e_dx_agg = e_totals["deixis"] / e_totals["words"] * 1000

rows = [
    ("Quote recovery rate",
     f"{t_totals['qr_found']}/{t_totals['qr_total']} ({t_qr_agg:.0%})",
     f"{e_totals['qr_found']}/{e_totals['qr_total']} ({e_qr_agg:.0%})",
     "T" if t_qr_agg > e_qr_agg else "E"),
    ("Char mentions / 1k words", f"{t_cmd_agg:.1f}", f"{e_cmd_agg:.1f}",
     f"T (+{(t_cmd_agg/e_cmd_agg - 1)*100:.0f}%)" if t_cmd_agg > e_cmd_agg else f"E (+{(e_cmd_agg/t_cmd_agg - 1)*100:.0f}%)"),
    ("Unique chars per episode", f"{t_uc_agg:.1f}", f"{e_uc_agg:.1f}",
     "T" if t_uc_agg > e_uc_agg else "E"),
    ("Chapter refs / 1k words", f"{t_cr_agg:.2f}", f"{e_cr_agg:.2f}",
     "T" if t_cr_agg > e_cr_agg else "E"),
    ("Sentence specificity", f"{t_ss_agg:.3f}", f"{e_ss_agg:.3f}",
     "T" if t_ss_agg > e_ss_agg else "E"),
    ("Deixis / 1k words", f"{t_dx_agg:.1f}", f"{e_dx_agg:.1f}",
     "T" if t_dx_agg > e_dx_agg else "E"),
]

print(f"\n  {'Metric':<28s} {'Transport':>18s} {'Embedding':>18s} {'Winner':>12s}")
print(f"  {'-'*28} {'-'*18} {'-'*18} {'-'*12}")
for metric, tv, ev, w in rows:
    print(f"  {metric:<28s} {tv:>18s} {ev:>18s} {w:>12s}")

print(f"\n  Total words: T={t_totals['words']:,}, E={e_totals['words']:,}")
