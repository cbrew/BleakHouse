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


def _write_run_cost_db(
    run_dir: Path,
    by_stage: dict[str, dict],
) -> int | None:
    """Persist the per-stage rollup into experiments.db's run_cost table.

    Returns the number of rows upserted, or None if the DB isn't present.
    """
    db_path = run_dir.parent.parent / "experiments.db"
    if not db_path.exists():
        return None
    from enrichment.expdb.store import Store  # pyright: ignore[reportMissingImports]
    store = Store(db_path)
    store.init_schema()

    novel: str | None = None
    config_path = run_dir / "config.json"
    if config_path.exists():
        try:
            novel = json.loads(config_path.read_text()).get("novel")
        except json.JSONDecodeError:
            pass

    for stage, b in by_stage.items():
        # Match the human-readable label the printer uses, so DB queries
        # round-trip with what users see in the report.
        stage_label = stage if stage == "enrichment" else f"phase{stage}"
        store.upsert_run_cost(
            run_label=run_dir.name,
            stage=stage_label,
            n_calls=b["count"],
            cpu_s=b["cpu_s"],
            wall_s=b["wall_s"],
            in_tok=b["in_tok"],
            cache_w_tok=b["cache_w"],
            cache_r_tok=b["cache_r"],
            out_tok=b["out_tok"],
            in_chars=b["in_chars"],
            audio_ms=b["audio_ms"],
            cost_usd=b["cost"],
            novel=novel,
        )
    return len(by_stage)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: timings_summary.py <run_dir>")
    run_dir = Path(sys.argv[1])
    events = _collect_phase_timings(run_dir) + _collect_novel_enrichment(run_dir)
    if not events:
        sys.exit(f"FAIL: no phase*_timings.json files in {run_dir}")
    out = _write_run_timings(run_dir, events)
    print(f"{run_dir.name}: {len(events)} events across "
          f"{len({e['phase'] for e in events})} stages  →  {out.name}\n")

    # ---- stage-by-stage rollup ------------------------------------------
    # Phases sort lexically; "enrichment" first as the per-novel prep step.
    def _phase_sort_key(p: str) -> tuple[int, list]:
        if p == "enrichment":
            return (0, [])
        nums = [int(s) for s in p.split("_")]
        return (1, nums)

    by_stage: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "cpu_s": 0.0, "wall_s": 0.0,
                 "in_tok": 0, "cache_w": 0, "cache_r": 0, "out_tok": 0,
                 "in_chars": 0, "audio_ms": 0, "cost": 0.0,
                 "_min_t0": float("inf"), "_max_t1": float("-inf"),
                 "_models": set()}
    )
    for e in events:
        b = by_stage[e["phase"]]
        b["count"] += 1
        b["cpu_s"] += e.get("duration_s", 0)
        b["in_tok"] += e.get("input_tokens", 0)
        b["cache_w"] += e.get("cache_creation_input_tokens", 0)
        b["cache_r"] += e.get("cache_read_input_tokens", 0)
        b["out_tok"] += e.get("output_tokens", 0)
        b["in_chars"] += e.get("input_chars", 0)
        b["audio_ms"] += e.get("output_audio_ms", 0)
        b["cost"] += event_cost(e)
        t0 = e.get("started_at", 0) or 0
        if t0:
            b["_min_t0"] = min(b["_min_t0"], t0)
            b["_max_t1"] = max(b["_max_t1"], t0 + e.get("duration_s", 0))
        b["_models"].add(e.get("name", "?"))
    for b in by_stage.values():
        b["wall_s"] = (
            b["_max_t1"] - b["_min_t0"]
            if b["_min_t0"] != float("inf") else 0
        )

    has_estimated = any(
        m in ESTIMATED_RATES
        for b in by_stage.values() for m in b["_models"]
    )

    cols = ("stage", "n", "cpu_s", "wall_s", "in_tok",
            "cache_w", "cache_r", "out_tok", "in_chars", "audio_s", "cost")
    widths = (12, 4, 8, 8, 10, 10, 11, 9, 9, 8, 9)
    header = "  ".join(f"{c:>{w}}" for c, w in zip(cols, widths))
    print(header)
    print("-" * len(header))

    totals: dict[str, float] = defaultdict(float)
    for stage in sorted(by_stage, key=_phase_sort_key):
        b = by_stage[stage]
        flag = "*" if any(m in ESTIMATED_RATES for m in b["_models"]) else ""
        label = stage if stage == "enrichment" else f"phase{stage}"
        row = (
            f"{(label + flag):>{widths[0]}}",
            f"{b['count']:>{widths[1]}d}",
            f"{b['cpu_s']:>{widths[2]}.1f}",
            f"{b['wall_s']:>{widths[3]}.1f}",
            f"{b['in_tok']:>{widths[4]},d}",
            f"{b['cache_w']:>{widths[5]},d}",
            f"{b['cache_r']:>{widths[6]},d}",
            f"{b['out_tok']:>{widths[7]},d}",
            f"{b['in_chars']:>{widths[8]},d}",
            f"{b['audio_ms']/1000:>{widths[9]}.1f}",
            f"${b['cost']:>{widths[10]-1}.4f}",
        )
        print("  ".join(row))
        for k in ("count", "cpu_s", "in_tok", "cache_w", "cache_r",
                  "out_tok", "in_chars", "audio_ms", "cost"):
            totals[k] += b[k]
    print("-" * len(header))
    print("  ".join((
        f"{'TOTAL':>{widths[0]}}",
        f"{int(totals['count']):>{widths[1]}d}",
        f"{totals['cpu_s']:>{widths[2]}.1f}",
        f"{'':>{widths[3]}}",
        f"{int(totals['in_tok']):>{widths[4]},d}",
        f"{int(totals['cache_w']):>{widths[5]},d}",
        f"{int(totals['cache_r']):>{widths[6]},d}",
        f"{int(totals['out_tok']):>{widths[7]},d}",
        f"{int(totals['in_chars']):>{widths[8]},d}",
        f"{totals['audio_ms']/1000:>{widths[9]}.1f}",
        f"${totals['cost']:>{widths[10]-1}.4f}",
    )))
    print()
    print("Columns: cpu_s = sum of per-call durations (parallel work "
          "double-counts).")
    print("         wall_s = max(end) - min(start) within the stage "
          "(true elapsed).")
    print("         cache_w = cache_creation_input_tokens (billed at "
          "1.25x base rate).")
    print("         cache_r = cache_read_input_tokens (billed at 0.10x "
          "base rate).")
    if has_estimated:
        print()
        print("* = stage uses a model whose pricing is an estimate; see "
              "enrichment/pricing.py.")

    n_db_rows = _write_run_cost_db(run_dir, by_stage)
    if n_db_rows is not None:
        print(f"\nUpserted {n_db_rows} rows into experiments.db run_cost.")


if __name__ == "__main__":
    main()
