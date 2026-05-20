"""Render blinded pair markdown for the Tier L text preference test
(symmetric N-way variant, dll8 update 2026-05-17).

Per the corrected methodology in docs/tier_l_judge_methodology.md:
Sonnet is **not** a presumed baseline — it competes on equal footing
with the other open-weight candidates. With 5 candidates total
(sonnet, gemma-4-31b, deepseek-v3-2, qwen3-235b-a22b, gpt-5-4):

- Per fixture entry: C(5,2) = 10 distinct unordered model pairs.
- Each unordered pair is presented in BOTH orders (X-as-A then Y-as-B,
  and Y-as-A then X-as-B). This controls for left/right (or
  first/second) reading bias.
- 5 fixture entries × 10 pairs × 2 orderings = **100 presentations**
  total.

Each presentation gets its own pair_id. The pair_ids are shuffled
under a recorded seed so the listener cannot infer the model identity
or the fixture entry from the pair number alone.

Blinding rules (text):
- Segment title replaced with `[Segment N]` (different models write
  different title styles — Sonnet's are more elaborate; this would be
  a giveaway).
- Only `speaker / role / utterance text` rendered. TTS delivery
  metadata (rate, pause_*_ms, emphasis_words, passage_ref,
  sentence_type, quote_mode, is_quote) is dropped — not prose-signal.
- No filename references that leak identity.

Outputs:
- data/eval/stage2_tier_l_prose/blind_pairs/pair_<NNN>.md
- data/eval/stage2_tier_l_prose/blinding_manifest.json
- data/eval/stage2_tier_l_prose/preferences.json  (template if absent)

Usage:
    uv run python scripts/render_eval_pairings.py
    uv run python scripts/render_eval_pairings.py --seed 42

The manifest stores the canonical pair_index → (run_id, seg_idx,
model_a, model_b) mapping; once shuffled, pair_id is just a label.
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
ROOT = REPO_ROOT / "data" / "eval" / "stage2_tier_l_prose"
OUT_DIR = ROOT / "blind_pairs"
MANIFEST_PATH = ROOT / "blinding_manifest.json"
PREF_PATH = ROOT / "preferences.json"

# All 5 candidates on equal footing — no baseline. Methodology
# correction 2026-05-17: Sonnet is one model among many for the
# preference test, not a presumed default.
ALL_CANDIDATES = (
    "sonnet",
    "gemma-4-31b",
    "deepseek-v3-2",
    "qwen3-235b-a22b",
    "gpt-5-4",
)

# Same fixture as scripts/run_eval_tier_l_prose.py.
FIXTURE: list[tuple[str, int]] = [
    ("bh_trn_literary_hostprep_short", 0),
    ("bh_trn_literary_hostprep_short", 2),
    ("bh_trn_literary_hostprep_short", 4),
    ("wh_trn_literary_short", 1),
    ("wh_trn_literary_short", 3),
]
DEFAULT_SEED = 20260517


@dataclass
class PairRecord:
    pair_id: str           # e.g. "pair_001"
    run_id: str
    seg_idx: int
    a_is: str              # model name on the A side
    b_is: str              # model name on the B side
    unordered_pair_key: str  # canonical key (alphabetical) so the two
                           # orderings of the same unordered pair share
                           # a key — used by the scorer to test
                           # order-consistency.
    rng_seed: int
    pair_md: str           # filename relative to OUT_DIR


def _load_segment(candidate_id: str, run_id: str, seg_idx: int) -> dict:
    p = ROOT / candidate_id / f"segment_{run_id}_{seg_idx}.json"
    d = json.loads(p.read_text())
    if not d.get("schema_valid", True):
        raise ValueError(
            f"{p} is schema_valid=False; cannot include in pair test"
        )
    out = d.get("output")
    if not isinstance(out, dict):
        raise ValueError(f"{p} has no 'output' dict")
    return out


def _render_blind_segment(seg: dict, segment_number: int) -> str:
    out: list[str] = []
    out.append(f"### [Segment {segment_number}]")
    out.append("")
    for turn in seg.get("turns") or []:
        speaker = turn.get("speaker", "?")
        role = turn.get("role", "")
        suffix = f" ({role})" if role else ""
        out.append(f"**{speaker}**{suffix}:")
        out.append("")
        for u in turn.get("utterances") or []:
            text = (u.get("text") or "").strip()
            if not text:
                continue
            out.append(text)
            out.append("")
    return "\n".join(out)


def _write_pair_md(
    *, pair_id: str, run_id: str, seg_idx: int,
    a_seg: dict, b_seg: dict,
) -> str:
    body: list[str] = []
    body.append(f"# {pair_id}")
    body.append("")
    body.append(
        f"> Same input given to two models. Read both, then record "
        f"your preference (A, B, or tie) in "
        f"`data/eval/stage2_tier_l_prose/preferences.json` under "
        f"the key `{pair_id}`. Fixture entry: `{run_id}` / segment "
        f"index {seg_idx}."
    )
    body.append("")
    body.append("---")
    body.append("")
    body.append("## A")
    body.append("")
    body.append(_render_blind_segment(a_seg, seg_idx))
    body.append("")
    body.append("---")
    body.append("")
    body.append("## B")
    body.append("")
    body.append(_render_blind_segment(b_seg, seg_idx))
    body.append("")
    return "\n".join(body)


def _unordered_key(x: str, y: str) -> str:
    """Canonical key for the unordered pair {x, y} — sorted, joined."""
    a, b = sorted([x, y])
    return f"{a}__vs__{b}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = ap.parse_args()

    # Pre-flight: confirm every (candidate, fixture) sample exists +
    # is valid. Loud failure now beats a half-rendered run.
    seg_cache: dict[tuple[str, str, int], dict] = {}
    for cand in ALL_CANDIDATES:
        for run_id, seg_idx in FIXTURE:
            seg_cache[(cand, run_id, seg_idx)] = _load_segment(
                cand, run_id, seg_idx,
            )

    # Build the full list of ORDERED presentations in canonical order.
    # Per fixture entry: 10 unordered pairs × 2 orderings = 20. ×5 = 100.
    presentations: list[tuple[str, int, str, str]] = []
    for run_id, seg_idx in FIXTURE:
        for x, y in itertools.combinations(ALL_CANDIDATES, 2):
            presentations.append((run_id, seg_idx, x, y))  # X as A, Y as B
            presentations.append((run_id, seg_idx, y, x))  # Y as A, X as B
    assert len(presentations) == 100, len(presentations)

    # Shuffle pair_id assignment under the seed. This decorrelates the
    # numeric label from fixture / model identity so the listener
    # can't infer either from the order they read pairs in.
    rng = random.Random(args.seed)
    shuffled_order = list(range(len(presentations)))
    rng.shuffle(shuffled_order)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    records: list[PairRecord] = []
    for pair_index, orig_idx in enumerate(shuffled_order, start=1):
        run_id, seg_idx, a_is, b_is = presentations[orig_idx]
        pair_id = f"pair_{pair_index:03d}"
        a_seg = seg_cache[(a_is, run_id, seg_idx)]
        b_seg = seg_cache[(b_is, run_id, seg_idx)]
        md_text = _write_pair_md(
            pair_id=pair_id, run_id=run_id, seg_idx=seg_idx,
            a_seg=a_seg, b_seg=b_seg,
        )
        pair_md_name = f"{pair_id}.md"
        (OUT_DIR / pair_md_name).write_text(md_text)
        records.append(PairRecord(
            pair_id=pair_id,
            run_id=run_id, seg_idx=seg_idx,
            a_is=a_is, b_is=b_is,
            unordered_pair_key=_unordered_key(a_is, b_is),
            rng_seed=args.seed,
            pair_md=pair_md_name,
        ))

    manifest: dict[str, Any] = {
        "doc": (
            "Audit key for the Tier L text-blinded preference test "
            "(BleakHouse-dll8, symmetric N-way variant). Do NOT read "
            "this before recording your preferences. "
            "docs/tier_l_judge_methodology.md is the protocol spec."
        ),
        "rng_seed": args.seed,
        "candidates": list(ALL_CANDIDATES),
        "n_pairs": len(records),
        "n_unordered_pairs": len(records) // 2,
        "design_note": (
            "All C(N,2) unordered candidate pairs per fixture entry, "
            "each presented twice with sides swapped. pair_id order "
            "shuffled under rng_seed for blinding."
        ),
        "pairs": [asdict(r) for r in records],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))

    if not PREF_PATH.exists() or not _has_user_choices(PREF_PATH):
        template = {
            "doc": (
                "Fill in 'A', 'B', or 'tie' per pair_id. Pair files "
                "live at data/eval/stage2_tier_l_prose/blind_pairs/. "
                "Do NOT open blinding_manifest.json before scoring."
            ),
            "listener": (
                "<your name or initials — recorded so results carry "
                "the known-bias caveat>"
            ),
            "preferences": {r.pair_id: "" for r in records},
        }
        PREF_PATH.write_text(json.dumps(template, indent=2))
        print(f"Wrote empty preferences template -> {PREF_PATH}")
    else:
        print(f"Preserved existing preferences -> {PREF_PATH}")
        # Even when preserving, add any new pair_ids as blanks so we
        # don't lose pairs after a re-render.
        existing = json.loads(PREF_PATH.read_text())
        ex_prefs = existing.get("preferences") or {}
        added = 0
        for r in records:
            if r.pair_id not in ex_prefs:
                ex_prefs[r.pair_id] = ""
                added += 1
        if added:
            existing["preferences"] = ex_prefs
            PREF_PATH.write_text(json.dumps(existing, indent=2))
            print(f"  added {added} new blank pair_id entries")

    print(f"Rendered {len(records)} pairs -> {OUT_DIR}")
    print(f"Manifest -> {MANIFEST_PATH}")


def _has_user_choices(path: Path) -> bool:
    """True if preferences.json has any non-empty preference values
    (i.e. the listener has started scoring). We don't want to clobber
    in-progress work on re-render."""
    try:
        d = json.loads(path.read_text())
    except json.JSONDecodeError:
        return False
    prefs = d.get("preferences") or {}
    return any(v for v in prefs.values())


if __name__ == "__main__":
    main()
