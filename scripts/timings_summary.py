"""Roll up per-call timing for an entire pipeline run.

Reads every phase<N>_timings.json sidecar in <run_dir>, tags each event
with its phase, writes a consolidated run_timings.json, and prints
per-phase + per-model cost in dollars.

Usage:
    uv run python scripts/timings_summary.py <run_dir>
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from enrichment.pricing import ESTIMATED_RATES, event_cost  # pyright: ignore[reportMissingImports]

_PHASE_FILE_RE = re.compile(r"phase(\d+(?:_\d+)?)_timings\.json")


def _collect_phase_timings(run_dir: Path) -> list[dict]:
    """Tag every event in every phase<N>_timings.json with its phase id."""
    out: list[dict] = []
    for path in sorted(run_dir.glob("phase*_timings.json")):
        m = _PHASE_FILE_RE.fullmatch(path.name)
        if not m:
            continue
        phase = m.group(1)
        events = json.loads(path.read_text()).get("events", [])
        for e in events:
            e = dict(e)
            e["phase"] = phase
            out.append(e)
    return out


def _collect_novel_enrichment(run_dir: Path) -> list[dict]:
    """Find the run's novel and pull its passage_enrichment_timings.json.

    Returns empty list if the run isn't transport-mode, or if the novel's
    enrichment sidecar doesn't exist yet. Events get phase='enrichment'.
    """
    config_path = run_dir / "config.json"
    if not config_path.exists():
        return []
    try:
        config = json.loads(config_path.read_text())
    except json.JSONDecodeError:
        return []
    novel = config.get("novel")
    if not novel:
        return []
    sidecar = run_dir.parent.parent / "novels" / novel / "passage_enrichment_timings.json"
    if not sidecar.exists():
        return []
    events = json.loads(sidecar.read_text()).get("events", [])
    out = []
    for e in events:
        e = dict(e)
        e["phase"] = "enrichment"
        out.append(e)
    return out


def _write_run_timings(run_dir: Path, events: list[dict]) -> Path:
    path = run_dir / "run_timings.json"
    path.write_text(json.dumps({"events": events}, indent=2))
    return path


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: timings_summary.py <run_dir>")
    run_dir = Path(sys.argv[1])
    events = _collect_phase_timings(run_dir) + _collect_novel_enrichment(run_dir)
    if not events:
        sys.exit(f"FAIL: no phase*_timings.json files in {run_dir}")
    out = _write_run_timings(run_dir, events)
    print(f"{run_dir.name}: {len(events)} events across "
          f"{len({e['phase'] for e in events})} phases  →  {out.name}\n")

    # ---- by phase ---------------------------------------------------------
    by_phase: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "duration": 0.0, "cost": 0.0}
    )
    total_cost = 0.0
    total_duration = 0.0
    for e in events:
        b = by_phase[e["phase"]]
        b["count"] += 1
        b["duration"] += e["duration_s"]
        c = event_cost(e)
        b["cost"] += c
        total_cost += c
        total_duration += e["duration_s"]

    print(f"{'phase':<10} {'n':>5} {'cpu_s':>9} {'cost':>10}")
    print("-" * 40)
    for phase in sorted(by_phase):
        b = by_phase[phase]
        print(f"phase{phase:<5} {b['count']:>5d} {b['duration']:>9.1f} ${b['cost']:>8.3f}")
    print("-" * 40)
    print(f"{'TOTAL':<10} {sum(b['count'] for b in by_phase.values()):>5d} "
          f"{total_duration:>9.1f} ${total_cost:>8.3f}\n")

    # ---- by kind / name ---------------------------------------------------
    by_name: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"count": 0, "duration": 0.0,
                 "in_tok": 0, "out_tok": 0,
                 "in_chars": 0, "audio_ms": 0,
                 "cost": 0.0}
    )
    for e in events:
        key = (e["kind"], e["name"])
        b = by_name[key]
        b["count"] += 1
        b["duration"] += e["duration_s"]
        b["in_tok"] += e.get("input_tokens", 0)
        b["out_tok"] += e.get("output_tokens", 0)
        b["in_chars"] += e.get("input_chars", 0)
        b["audio_ms"] += e.get("output_audio_ms", 0)
        b["cost"] += event_cost(e)

    print(f"{'kind':<6} {'name':<35} {'n':>4} {'sum_s':>8} "
          f"{'in_tok':>9} {'out_tok':>8} {'in_chars':>9} "
          f"{'audio_s':>8} {'cost':>9}")
    print("-" * 105)
    has_estimated = False
    for (kind, name), b in sorted(
        by_name.items(), key=lambda kv: -kv[1]["cost"]
    ):
        flag = "*" if name in ESTIMATED_RATES else " "
        if name in ESTIMATED_RATES:
            has_estimated = True
        print(
            f"{kind:<6} {(name + flag)[:35]:<35} {b['count']:>4d} "
            f"{b['duration']:>8.1f} "
            f"{b['in_tok']:>9,} {b['out_tok']:>8,} "
            f"{b['in_chars']:>9,} {b['audio_ms']/1000:>8.1f} "
            f"${b['cost']:>7.3f}"
        )
    if has_estimated:
        print("\n* = pricing is an estimate (provider has not published "
              "rates for this model yet); see enrichment/pricing.py.")


if __name__ == "__main__":
    main()
