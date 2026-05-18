"""Convert the Tier L pairings (BleakHouse-dll8, symmetric N-way) into
the JSONL input format Potato expects for a pairwise comparison task.

Per BleakHouse-kl4f.2: read the existing
data/eval/stage2_tier_l_prose/blinding_manifest.json (the audit key
produced by scripts/render_eval_pairings.py) and reuse the same
text-rendering rules used by the markdown variant — title stripped to
`[Segment N]`, only speaker + role + utterance text emitted, no TTS
delivery metadata.

Output one JSONL line per pair_id, in the Potato pairwise format
(verified against examples/classification/pairwise-comparison/
data/pairwise-example.json from upstream master):

    {"id": "<pair_id>",
     "text": ["<A side rendered text>", "<B side rendered text>"]}

The `id` field MUST equal manifest.pair_id so the Potato output TSV
(`instance_id` column) joins back trivially.

The full pair-instructions block from the markdown variant is omitted —
Potato's UI provides the framing (sidebar instructions + A/B tile
buttons + optional tie). The intra-pair text is just the two rendered
segments, separated only by the Potato A/B tile UI.

Output:
- data/eval/stage2_tier_l_prose/potato/pairs.jsonl  (100 lines)
- data/eval/stage2_tier_l_prose/potato/README.md   (audit pointer)

Usage:
    uv run python scripts/render_eval_pairings_potato.py
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ROOT = REPO_ROOT / "data" / "eval" / "stage2_tier_l_prose"
MANIFEST_PATH = ROOT / "blinding_manifest.json"
POTATO_DIR = ROOT / "potato"
JSONL_PATH = POTATO_DIR / "pairs.jsonl"
POTATO_README = POTATO_DIR / "README.md"


def _load_segment(candidate_id: str, run_id: str, seg_idx: int) -> dict:
    p = ROOT / candidate_id / f"segment_{run_id}_{seg_idx}.json"
    d = json.loads(p.read_text())
    if not d.get("schema_valid", True):
        raise ValueError(
            f"{p} is schema_valid=False; cannot include in Potato run"
        )
    out = d.get("output")
    if not isinstance(out, dict):
        raise ValueError(f"{p} has no 'output' dict")
    return out


def _render_blind_segment(seg: dict, segment_number: int) -> str:
    """Same rules as scripts/render_eval_pairings.py (kept in sync by
    convention — keep these two helpers identical so the markdown
    variant and the Potato variant present the listener with the same
    text)."""
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


def main() -> None:
    if not MANIFEST_PATH.exists():
        raise SystemExit(
            f"missing {MANIFEST_PATH}. Run scripts/render_eval_pairings.py first."
        )
    manifest = json.loads(MANIFEST_PATH.read_text())

    # Pre-cache all (candidate, run_id, seg_idx) segments needed by any
    # pair so we don't re-read disk per pair.
    seg_cache: dict[tuple[str, str, int], dict] = {}
    for p in manifest["pairs"]:
        for who in (p["a_is"], p["b_is"]):
            key = (who, p["run_id"], p["seg_idx"])
            if key not in seg_cache:
                seg_cache[key] = _load_segment(*key)

    POTATO_DIR.mkdir(parents=True, exist_ok=True)
    with JSONL_PATH.open("w", encoding="utf-8") as fh:
        for p in manifest["pairs"]:
            a_text = _render_blind_segment(
                seg_cache[(p["a_is"], p["run_id"], p["seg_idx"])],
                p["seg_idx"],
            )
            b_text = _render_blind_segment(
                seg_cache[(p["b_is"], p["run_id"], p["seg_idx"])],
                p["seg_idx"],
            )
            line = {"id": p["pair_id"], "text": [a_text, b_text]}
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")

    POTATO_README.write_text(
        "# Potato pairwise input (BleakHouse-dll8 / kl4f)\n\n"
        f"`pairs.jsonl` contains {len(manifest['pairs'])} pair "
        "presentations rendered from the same blinding manifest "
        "(`../blinding_manifest.json`, "
        f"rng_seed={manifest['rng_seed']}) that the markdown variant "
        "in `../blind_pairs/` uses. The `id` field on each line is the "
        "manifest `pair_id` (already shuffled), so the Potato output "
        "TSV (`instance_id` column) joins back trivially.\n\n"
        "Do NOT open `../blinding_manifest.json` before completing the "
        "listening session — it's the audit key that maps pair_id back "
        "to (run_id, seg_idx, a_is, b_is) and would un-blind the test.\n"
    )
    print(f"Wrote {len(manifest['pairs'])} pairs -> {JSONL_PATH}")


if __name__ == "__main__":
    main()
