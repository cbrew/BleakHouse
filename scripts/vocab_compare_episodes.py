"""Vocabulary comparison across phase3_episode.json outputs.

For each episode: word count, type count, type-token ratio, mean word
length, mean sentence length. Pairwise Jaccard on the type set. Per-pair
Monroe-Colaresi-Quinn informative-Dirichlet log-odds for distinctive
words (with a tiny stopword list to suppress function-word noise).

Default panel is the qwen-plus / gpt-5.4 / Sonnet-baseline triple on
bh_trn_literary_hostprep; override with --episode name=path repeated.

Run:
    uv run python scripts/vocab_compare_episodes.py
    uv run python scripts/vocab_compare_episodes.py \\
        --episode foo=data/runs/foo/phase3_episode.json \\
        --episode bar=data/runs/bar/phase3_episode.json \\
        --pair foo,bar
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from itertools import combinations
from pathlib import Path

DEFAULT_EPISODES: dict[str, str] = {
    "qwen-plus":   "data/runs/bh_trn_literary_hostprep_alibaba_qwen_plus/phase3_episode.json",
    "gpt-5.4":     "data/runs/bh_trn_literary_hostprep_openai_5_4/phase3_episode.json",
    "sonnet-base": "data/runs/bh_trn_literary_hostprep/phase3_episode.json",
}

WORD_RE = re.compile(r"[A-Za-z‘’']+")
STOP = set(
    "the a an and or but if then so to of in on at by for with from as is are "
    "was were be been being have has had do does did i you he she we they it "
    "this that these those his her my your our their not no yes very just also "
    "which who what where when how why all any some more most other than there "
    "here".split()
)


def extract_text(ep_path: Path) -> str:
    """Concatenate every utterance/turn text body in an episode."""
    with open(ep_path) as f:
        ep = json.load(f)
    chunks: list[str] = []
    segs = ep.get("segments") or ep.get("episode_segments") or []
    for seg in segs:
        for turn in seg.get("turns", []):
            utts = turn.get("utterances")
            if utts:
                for u in utts:
                    t = u.get("text") or ""
                    if t:
                        chunks.append(t)
            elif turn.get("text"):
                chunks.append(turn["text"])
    return "\n".join(chunks)


def tokens(text: str) -> list[str]:
    # Curly apostrophes vary by model; normalise so "don't" and "don’t" merge.
    text = text.replace("’", "'").replace("‘", "'")
    return [w.lower() for w in WORD_RE.findall(text)]


def lengths_table(eps: dict[str, str]) -> None:
    print(f"{'episode':<16}{'words':>10}{'types':>10}{'TTR':>8}{'mean_len':>10}{'mean_sent':>11}")
    for name, p in eps.items():
        text = extract_text(Path(p))
        toks = tokens(text)
        types = set(toks)
        sents = re.split(r"[.!?]+", text)
        sent_lens = [len(s.split()) for s in sents if s.strip()]
        mean_sent = sum(sent_lens) / len(sent_lens) if sent_lens else 0.0
        mean_len = sum(len(t) for t in toks) / len(toks) if toks else 0.0
        ttr = len(types) / len(toks) if toks else 0.0
        print(f"{name:<16}{len(toks):>10}{len(types):>10}{ttr:>8.3f}{mean_len:>10.2f}{mean_sent:>11.2f}")


def log_odds_dirichlet(
    a: Counter, b: Counter, alpha: float = 0.01, min_total: int = 5
) -> list[tuple[str, float, int, int]]:
    """Monroe-Colaresi-Quinn informative-Dirichlet log-odds (a vs b).
    Words with combined count below min_total are dropped to suppress noise."""
    vocab = set(a) | set(b)
    n_a = sum(a.values())
    n_b = sum(b.values())
    a0 = alpha * len(vocab)
    out: list[tuple[str, float, int, int]] = []
    for w in vocab:
        ya, yb = a[w], b[w]
        if ya + yb < min_total:
            continue
        la = math.log((ya + alpha) / (n_a + a0 - ya - alpha))
        lb = math.log((yb + alpha) / (n_b + a0 - yb - alpha))
        diff = la - lb
        var = 1 / (ya + alpha) + 1 / (yb + alpha)
        z = diff / math.sqrt(var)
        out.append((w, z, ya, yb))
    out.sort(key=lambda r: r[1], reverse=True)
    return out


def distinctive(eps: dict[str, str], a: str, b: str, top: int = 25) -> None:
    text_a = tokens(extract_text(Path(eps[a])))
    text_b = tokens(extract_text(Path(eps[b])))
    ca = Counter(w for w in text_a if w not in STOP)
    cb = Counter(w for w in text_b if w not in STOP)
    lo = log_odds_dirichlet(ca, cb)
    print(f"\n--- distinctive of {a} vs {b} (top {top}) ---")
    for w, z, ya, yb in lo[:top]:
        print(f"  {z:+6.2f}  {w:<20} {a}:{ya:<4}  {b}:{yb}")
    print(f"\n--- distinctive of {b} vs {a} (top {top}) ---")
    for w, z, ya, yb in lo[-top:][::-1]:
        print(f"  {z:+6.2f}  {w:<20} {a}:{ya:<4}  {b}:{yb}")


def overlap(eps: dict[str, str]) -> None:
    sets = {name: set(tokens(extract_text(Path(p)))) for name, p in eps.items()}
    print("\n--- pairwise jaccard ---")
    for a, b in combinations(sets, 2):
        inter = len(sets[a] & sets[b])
        union = len(sets[a] | sets[b])
        only_a = len(sets[a] - sets[b])
        only_b = len(sets[b] - sets[a])
        print(f"  {a:<16} vs {b:<16}  jaccard={inter/union:.3f}  shared={inter}  only_{a}={only_a}  only_{b}={only_b}")


def _parse_episode_arg(s: str) -> tuple[str, str]:
    if "=" not in s:
        raise argparse.ArgumentTypeError(f"--episode expects name=path, got {s!r}")
    name, _, path = s.partition("=")
    return name, path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--episode", action="append", type=_parse_episode_arg, default=[],
        help="name=path/to/phase3_episode.json (repeatable). Replaces the default panel if used.",
    )
    ap.add_argument(
        "--pair", action="append", default=[],
        help="a,b — print distinctive words for this ordered pair (repeatable). "
             "Default: every pair in the panel.",
    )
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()

    eps = dict(args.episode) if args.episode else dict(DEFAULT_EPISODES)
    lengths_table(eps)
    overlap(eps)

    if args.pair:
        pairs = [tuple(p.split(",", 1)) for p in args.pair]
    else:
        pairs = list(combinations(eps, 2))
    for a, b in pairs:
        if a not in eps or b not in eps:
            raise SystemExit(f"unknown pair: {a},{b}")
        distinctive(eps, a, b, top=args.top)


if __name__ == "__main__":
    main()
