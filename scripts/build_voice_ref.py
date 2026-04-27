"""Build a designed reference clip for one persona by stitching slot-matched clips.

Replaces the old per-run extract_refs.py approach (which always took the first
15 s of the first turn — an opener, content-keyed, prosodically narrow) with
a frozen ref that covers a designed set of *prosodic* slots: opener,
panelist-address, double-em-dash rhetorical aside, multi-clause sentence,
synthesis-starter, pivot. Slots are matched on punctuation/structure, not
keywords, so the ref generalises beyond Bleak House.

Inputs:
    pool/manifest.json + pool/wavs/*.wav   (from scripts/build_voice_pool.py)

Outputs:
    <out>/ref.wav      (24 kHz mono, ~45-70 s)
    <out>/ref.json     (per-slot provenance + concatenated transcript)

Usage:
    uv run python scripts/build_voice_ref.py \\
        --pool data/voice_pools/Host \\
        --out  data/voice_refs/v1/Host \\
        --persona Host
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf


# Each slot describes a prosodic pattern we want the speaker encoder to see.
# Content is deliberately not in the predicates — they fire on punctuation,
# structure, and a few function words that mark register.
@dataclass(frozen=True)
class Slot:
    name: str
    description: str
    matches: Callable[[str], bool]


def _starts_with_re(rx: str, *, ignore_case: bool = False) -> Callable[[str], bool]:
    flags = re.IGNORECASE if ignore_case else 0
    pat = re.compile(rx, flags)
    return lambda s: bool(pat.search(s))


HOST_SLOTS: list[Slot] = [
    Slot(
        name="opener",
        description="Intro/welcome cadence — statement register, often slower",
        matches=_starts_with_re(r"^Welcome\b", ignore_case=True),
    ),
    Slot(
        name="address",
        description="Vocative + statement — 'Name, ...' (Host's question proxy)",
        matches=_starts_with_re(r"^[A-Z][a-z]+,\s"),
    ),
    Slot(
        name="double_emdash",
        description="Rhetorical aside — '... — ... — ...' (parenthetical weight)",
        matches=_starts_with_re(r" — .*? — "),
    ),
    Slot(
        name="multi_clause",
        description="Long sentence with internal structure (>=3 commas)",
        matches=lambda t: t.count(",") >= 3,
    ),
    Slot(
        name="synthesis",
        description="Connective register — 'And', 'What', 'But' opener",
        matches=_starts_with_re(r"^(And|What|But) ", ignore_case=True),
    ),
    Slot(
        name="pivot",
        description="Explicit segment/topic transition",
        matches=_starts_with_re(r"\b(let me|brings (us|me|you))\b", ignore_case=True),
    ),
]


# Blackstone (social/legal historian, male). Different register from Host —
# never opens an episode, never uses vocative addresses, instead responds
# to the host with hedged claims and historical grounding.
BLACKSTONE_SLOTS: list[Slot] = [
    Slot(
        name="response_opener",
        description="Blackstone replying to the host — 'Thank you —', 'I'd add', etc.",
        matches=_starts_with_re(r"^(Thank you|I'd add|What I'd add|I want to|I'd say|Indeed)\b"),
    ),
    Slot(
        name="long_sentence",
        description=">30 words — Blackstone's multi-clause register",
        matches=lambda t: len(t.split()) > 30,
    ),
    Slot(
        name="double_emdash",
        description="Rhetorical aside — same role as for Host",
        matches=_starts_with_re(r" — .*? — "),
    ),
    Slot(
        name="historical_grounding",
        description="Historical / institutional reference",
        matches=_starts_with_re(
            r"\b(historically|Victorian|institution|systemic|legal|economy|Court|Act\b|"
            r"document|workhouse|Chancery|reform|industrial)",
            ignore_case=True,
        ),
    ),
    Slot(
        name="hedge_nuance",
        description="Push-back / nuanced agreement",
        matches=_starts_with_re(
            r"\b(push back|but I|uncomfortable|complicated|on the other hand|"
            r"although|however|but also)\b",
            ignore_case=True,
        ),
    ),
    Slot(
        name="synthesis",
        description="Continuative register — 'And', 'And that'",
        matches=_starts_with_re(r"^(And|But) ", ignore_case=True),
    ),
]


# Lookup table used by main(); add new personas here.
PERSONA_SLOTS: dict[str, list[Slot]] = {
    "Host": HOST_SLOTS,
    "James Blackstone": BLACKSTONE_SLOTS,
}


def pick_per_slot(items: list[dict], slots: list[Slot]) -> list[tuple[Slot, dict]]:
    """For each slot, pick the longest clip that matches it AND hasn't been
    used yet. Slots filled in order; clips are not re-used.

    Returns the list of (slot, clip) pairs, in slot order. Slots with no
    matching clip are silently skipped.
    """
    used: set[str] = set()
    chosen: list[tuple[Slot, dict]] = []
    for slot in slots:
        candidates = [
            r for r in items
            if r["audio_file"] not in used and slot.matches(r["text"])
        ]
        if not candidates:
            print(f"  skip slot '{slot.name}' — no match in pool")
            continue
        candidates.sort(key=lambda r: -r["duration_s"])
        best = candidates[0]
        used.add(best["audio_file"])
        chosen.append((slot, best))
    return chosen


def stitch(chosen: list[tuple[Slot, dict]], gap_ms: int = 250, sr: int = 24000) -> np.ndarray:
    gap = np.zeros(int(gap_ms / 1000 * sr), dtype=np.float32)
    pieces: list[np.ndarray] = []
    for i, (_, clip) in enumerate(chosen):
        y, clip_sr = sf.read(clip["audio_file"])
        if clip_sr != sr:
            raise SystemExit(f"sample rate mismatch: {clip_sr} != {sr} on {clip['audio_file']}")
        pieces.append(np.asarray(y, dtype=np.float32))
        if i < len(chosen) - 1:
            pieces.append(gap)
    return np.concatenate(pieces) if pieces else np.zeros(0, dtype=np.float32)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pool", required=True, type=Path,
                   help="pool dir with manifest.json + wavs/")
    p.add_argument("--out", required=True, type=Path,
                   help="output dir; writes ref.wav + ref.json")
    p.add_argument("--persona", required=True,
                   help="persona name for ref.json metadata, e.g. Host")
    p.add_argument("--gap-ms", type=int, default=250)
    args = p.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((args.pool / "manifest.json").read_text())
    items = manifest["items"]
    print(f"pool: {len(items)} clips, {manifest['total_minutes']} min")

    if args.persona not in PERSONA_SLOTS:
        raise SystemExit(
            f"no slot taxonomy for persona {args.persona!r}; known: {sorted(PERSONA_SLOTS)}"
        )
    slots = PERSONA_SLOTS[args.persona]
    chosen = pick_per_slot(items, slots)
    print(f"chose {len(chosen)} slots:")
    for slot, clip in chosen:
        print(f"  {slot.name:14s} ({clip['duration_s']:4.1f}s)  "
              f"f0={clip['f0_median_hz']:.0f}Hz  {clip['text'][:65]}")

    audio = stitch(chosen, gap_ms=args.gap_ms)
    sr = 24000
    ref_wav = args.out / "ref.wav"
    sf.write(str(ref_wav), audio, sr)

    transcript = " ".join(clip["text"].rstrip() for _, clip in chosen)
    ref_json = {
        "persona": args.persona,
        "version": "v1",
        "duration_s": round(len(audio) / sr, 2),
        "sample_rate": sr,
        "transcript": transcript,
        "gap_ms": args.gap_ms,
        "slots": [
            {
                "slot": slot.name,
                "description": slot.description,
                "duration_s": clip["duration_s"],
                "text": clip["text"],
                "source_run": clip["source_run"],
                "source_turn_start_ms": clip["source_turn_start_ms"],
                "f0_median_hz": clip["f0_median_hz"],
                "wav": clip["audio_file"].rsplit("/", 1)[-1],
            }
            for slot, clip in chosen
        ],
    }
    (args.out / "ref.json").write_text(json.dumps(ref_json, indent=2))
    print()
    print(f"ref.wav: {len(audio)/sr:.1f}s @ {sr} Hz -> {ref_wav}")
    print(f"ref.json -> {args.out / 'ref.json'}")


if __name__ == "__main__":
    main()
