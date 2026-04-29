"""Summarise per-call timing for a host-prep run.

Reads `phase2_5_timings.json` (produced by host_prep when run_dir is
set), groups events by kind/name and by (expert, segment), prints a
breakdown of where time and tokens went.

Usage:
    uv run python scripts/timings_summary.py <run_dir>
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

# Haiku 4.5 / Sonnet 4.6 pricing ($/MTok). Update as pricing changes.
_PRICING = {
    "haiku": (1.00, 5.00),
    "sonnet": (3.00, 15.00),
}


def _model_family(name: str) -> str:
    n = name.lower()
    if "haiku" in n:
        return "haiku"
    if "sonnet" in n:
        return "sonnet"
    return "?"


def _cost(model: str, in_tok: int, out_tok: int) -> float:
    fam = _model_family(model)
    rates = _PRICING.get(fam)
    if rates is None:
        return 0.0
    in_rate, out_rate = rates
    return in_tok * in_rate / 1_000_000 + out_tok * out_rate / 1_000_000


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: timings_summary.py <run_dir>")
    run_dir = Path(sys.argv[1])
    p = run_dir / "phase2_5_timings.json"
    if not p.exists():
        sys.exit(f"FAIL: {p} not found")
    events = json.loads(p.read_text())["events"]
    print(f"{run_dir.name}: {len(events)} events\n")

    # ---- by kind / name ---------------------------------------------------
    by_name: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"count": 0, "duration": 0.0, "in_tok": 0, "out_tok": 0, "cost": 0.0}
    )
    total_duration = 0.0
    total_cost = 0.0
    for e in events:
        key = (e["kind"], e["name"])
        b = by_name[key]
        b["count"] += 1
        b["duration"] += e["duration_s"]
        b["in_tok"] += e.get("input_tokens", 0)
        b["out_tok"] += e.get("output_tokens", 0)
        if e["kind"] == "model":
            cost = _cost(e["name"], e.get("input_tokens", 0), e.get("output_tokens", 0))
            b["cost"] += cost
            total_cost += cost
        total_duration += e["duration_s"]

    print(f"{'kind':<6} {'name':<35} {'n':>4} {'sum_s':>8} {'avg_s':>7} "
          f"{'in_tok':>9} {'out_tok':>8} {'cost':>8}")
    print("-" * 95)
    for (kind, name), b in sorted(
        by_name.items(), key=lambda kv: -kv[1]["duration"]
    ):
        avg = b["duration"] / b["count"] if b["count"] else 0
        print(
            f"{kind:<6} {name[:35]:<35} {b['count']:>4d} "
            f"{b['duration']:>8.1f} {avg:>7.2f} "
            f"{b['in_tok']:>9,} {b['out_tok']:>8,} "
            f"${b['cost']:>7.3f}"
        )
    print("-" * 95)
    print(f"{'TOTAL':<6} {'':<35} {sum(b['count'] for b in by_name.values()):>4} "
          f"{total_duration:>8.1f}s (CPU)        "
          f"{sum(b['in_tok'] for b in by_name.values()):>9,} "
          f"{sum(b['out_tok'] for b in by_name.values()):>8,} "
          f"${total_cost:>7.3f}")
    print()

    # ---- by interview (expert × segment) ---------------------------------
    by_iv: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"events": 0, "duration": 0.0}
    )
    for e in events:
        key = (e.get("expert", ""), e.get("segment", ""))
        by_iv[key]["events"] += 1
        by_iv[key]["duration"] += e["duration_s"]
    print(f"{'expert':<25} {'segment':<40} {'n':>4} {'cpu_s':>8}")
    print("-" * 85)
    for (expert, segment), b in sorted(
        by_iv.items(), key=lambda kv: -kv[1]["duration"]
    )[:20]:
        if not expert and not segment:
            label = "(unattributed)"
            print(f"{label:<25} {'':<40} {b['events']:>4d} {b['duration']:>8.1f}")
        else:
            print(f"{(expert or '—')[:25]:<25} {(segment or '—')[:40]:<40} "
                  f"{b['events']:>4d} {b['duration']:>8.1f}")


if __name__ == "__main__":
    main()
