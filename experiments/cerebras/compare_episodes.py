"""Build a cross-panel/model comparison from full-episode JSONs.

Scans for `phase3_cerebras_native_*_episode.json` under each panel run dir
and alongside it reads `phase3_episode.json` (the Anthropic baseline, if
present). Emits per-episode aggregate stats in a markdown table.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _iter_segments(episode: dict[str, Any]) -> list[dict[str, Any]]:
    """Yield EpisodeSegment dicts from either our episode wrapper or the Anthropic one."""
    if "segments" in episode and isinstance(episode["segments"], list):
        # Our wrapper: segments[*].episode_segment OR Anthropic: segments[*] is the EpisodeSegment itself
        out: list[dict[str, Any]] = []
        for s in episode["segments"]:
            if isinstance(s, dict) and "episode_segment" in s:
                seg = s.get("episode_segment")
                if seg:
                    out.append(seg)
            elif isinstance(s, dict) and "turns" in s:
                out.append(s)
        return out
    return []


def _words(text: str) -> int:
    return len(text.split())


def summarise(episode: dict[str, Any], label: str, model: str) -> dict[str, Any]:
    segs = _iter_segments(episode)
    n_valid = len(segs)
    n_total = len(episode.get("segments", [])) or n_valid
    turns = [t for seg in segs for t in seg.get("turns", [])]
    utts = [u for t in turns for u in t.get("utterances", [])]
    quotes = [u for u in utts if u.get("is_quote")]
    passages_used = {u.get("passage_ref") for u in utts if u.get("passage_ref")}
    speakers = Counter(t.get("speaker", "?") for t in turns)
    host_turns = speakers.get("Host", 0)
    expert_turns = sum(v for k, v in speakers.items() if k != "Host")
    words_total = sum(_words(u.get("text", "")) for u in utts)
    words_per_utt = words_total / len(utts) if utts else 0.0
    host_share = host_turns / len(turns) if turns else 0.0

    totals = episode.get("totals") or {}
    return {
        "label": label,
        "model": model,
        "segments_valid": n_valid,
        "segments_total": n_total,
        "turns": len(turns),
        "utterances": len(utts),
        "words": words_total,
        "words_per_utt": round(words_per_utt, 1),
        "quotes": len(quotes),
        "passages_used": len(passages_used),
        "speakers": dict(speakers),
        "host_share": round(host_share, 2),
        "expert_turns": expert_turns,
        "tokens_in": totals.get("input_tokens"),
        "tokens_out": totals.get("output_tokens"),
        "elapsed_seconds": round(totals.get("elapsed_seconds") or 0, 1),
        "cost_usd": round(totals.get("cost_usd") or 0, 4) if totals else None,
    }


def collect(panel_dirs: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for panel in panel_dirs:
        label = panel.name
        # Anthropic baseline: phase3_episode.json
        anth = panel / "phase3_episode.json"
        if anth.exists():
            with open(anth) as f:
                rows.append(summarise(json.load(f), label, "claude-sonnet-4-6 (baseline)"))
        # Cerebras full-episode outputs: phase3_cerebras_native_<slug>_episode.json
        for p in sorted(panel.glob("phase3_cerebras_native_*_episode.json")):
            with open(p) as f:
                data = json.load(f)
            model = data.get("model_id", p.stem)
            rows.append(summarise(data, label, model))
    return rows


def print_markdown(rows: list[dict[str, Any]]) -> None:
    cols = [
        ("panel", "label"),
        ("model", "model"),
        ("segs", "segments_valid"),
        ("turns", "turns"),
        ("utts", "utterances"),
        ("words", "words"),
        ("w/utt", "words_per_utt"),
        ("quotes", "quotes"),
        ("psgs", "passages_used"),
        ("host%", "host_share"),
        ("in_tok", "tokens_in"),
        ("out_tok", "tokens_out"),
        ("elapsed_s", "elapsed_seconds"),
        ("cost_$", "cost_usd"),
    ]
    header = "| " + " | ".join(h for h, _ in cols) + " |"
    sep = "|" + "|".join("---" for _ in cols) + "|"
    print(header)
    print(sep)
    for r in rows:
        vals = []
        for _, k in cols:
            v = r.get(k)
            vals.append("—" if v is None else str(v))
        print("| " + " | ".join(vals) + " |")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--panels",
        nargs="+",
        type=Path,
        required=True,
        help="Run directories for each panel (e.g. data/runs/arc_v01_baseline ...)",
    )
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path")
    args = parser.parse_args()

    rows = collect(args.panels)
    print_markdown(rows)
    if args.output:
        args.output.write_text(json.dumps(rows, indent=2))
        print(f"\nWrote {args.output}")


if __name__ == "__main__":
    main()
