"""Generate a run-tracking HTML page showing the experiment matrix.

Inspired by the evaluation tables in Croft, Metzler & Strohman's
*Search Engines: Information Retrieval in Practice* — topics down the
rows, systems across the columns, scores in each cell.

Schema: axes are sourced from `enrichment.axes` (one place, no duplication).
Dir names follow `{novel}_{pipeline}_{panel}[_hostprep][_{generator}]`.
Cell tooltips show every axis explicitly so panel/novel/hostprep/generator
are never inferred from the name at display time.

Usage:
    uv run python -m webapp.run_tracker
    uv run python -m webapp.run_tracker --generator cerebras_qwen
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict

from enrichment import axes  # pyright: ignore[reportMissingImports]
from datetime import datetime, timezone
from pathlib import Path

from enrichment.axes import (
    DEFAULT_GENERATOR,
    GENERATOR_BY_ID,
    GENERATORS,
    NOVELS,
    PANELS_TUPLE,
    RunAxes,
    run_dir_name,
)

BASE_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = BASE_DIR / "data" / "runs"
OUTPUT_PATH = BASE_DIR / "data" / "run_tracker.html"

REACTIVE = re.compile(
    r"\b(exactly|absolutely|that's|I agree|but I|yes but|I think|"
    r"you're right|that reminds|building on|to add to|I'd push back|"
    r"that's a great|fair point|interesting)\b",
    re.I,
)

# Column order: pipelines × panels × hostprep, stable & wide.
# Pipelines: trn first (most-used) then emb, nop.
#
# `rag` and `rand` are paper-only baselines — plain-retrieval and random-
# passages respectively — used as ablation pairs against `emb`. They are
# intentionally *excluded* from the tracker: they don't belong on a
# generation-quality grid. Use --include-rag to force them in.
#
# Panels: literary, alternatives, interdisciplinary — matches the legacy
#   "A / B / Inter" ordering from the pre-migration CONDITIONS tuple.
DEFAULT_PIPELINE_ORDER: tuple[str, ...] = (
    axes.PIPELINE_TRANSPORT,
    axes.PIPELINE_EMBEDDING,
    axes.PIPELINE_NO_PASSAGES,
)
PIPELINE_ORDER_WITH_RAG: tuple[str, ...] = (
    *DEFAULT_PIPELINE_ORDER, axes.PIPELINE_RAG,
)
PANEL_ORDER: tuple[str, ...] = ("literary", "alternatives", "interdisciplinary")
PANEL_SHORT: dict[str, str] = {
    "literary": "Lit",
    "alternatives": "Alt",
    "interdisciplinary": "Int",
}
HOSTPREP_ORDER: tuple[bool, ...] = (False, True)
PIPELINE_DISPLAY: dict[str, str] = {
    axes.PIPELINE_TRANSPORT: "Transport",
    axes.PIPELINE_EMBEDDING: "Embedding (curated)",
    axes.PIPELINE_NO_PASSAGES: "No-passages",
    axes.PIPELINE_RAG: "RAG (plain)",
}


def measure_episode(path: Path) -> dict | None:
    """Extract key metrics from a phase3_episode.json."""
    try:
        with open(path) as f:
            ep = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None

    segments = ep.get("segments", [])
    n_segs = len(segments)
    if n_segs == 0:
        return None

    total_words = 0
    total_turns = 0
    total_questions = 0
    total_reactive = 0
    expert_words: dict[str, int] = defaultdict(int)
    host_words = 0
    quotes = 0

    for seg in segments:
        for turn in seg.get("turns", []):
            total_turns += 1
            speaker = turn.get("speaker", "")
            utterances = turn.get("utterances", [])
            turn_text = " ".join(u.get("text", "") for u in utterances)
            wc = len(turn_text.split())
            total_words += wc
            total_questions += turn_text.count("?")
            total_reactive += len(REACTIVE.findall(turn_text))

            if speaker == "Host" or "host" in turn.get("role", "").lower():
                host_words += wc
            else:
                expert_words[speaker] += wc

            for u in utterances:
                if u.get("is_quote"):
                    quotes += 1

    expert_total = sum(expert_words.values())

    return {
        "words": total_words,
        "segments": n_segs,
        "turns": total_turns,
        "q_per_seg": round(total_questions / n_segs, 1),
        "react_per_seg": round(total_reactive / n_segs, 1),
        "host_pct": round(host_words / total_words * 100, 1) if total_words else 0,
        "quotes": quotes,
        "expert_balance": _balance_score(expert_words) if expert_total else 0,
    }


def _balance_score(expert_words: dict[str, int]) -> float:
    """How evenly distributed is expert airtime? 1.0 = perfect equality."""
    if not expert_words:
        return 0
    vals = list(expert_words.values())
    total = sum(vals)
    n = len(vals)
    if n == 0 or total == 0:
        return 0
    equal_share = total / n
    deviation = sum(abs(v - equal_share) for v in vals) / total
    return round(1.0 - deviation, 2)


def _config_axes(run_dir: Path) -> RunAxes | None:
    """Read the `axes` block from config.json; None if missing or invalid."""
    cfg_path = run_dir / "config.json"
    if not cfg_path.exists():
        return None
    try:
        with open(cfg_path) as f:
            cfg = json.load(f)
    except json.JSONDecodeError:
        return None
    if not isinstance(cfg, dict) or "axes" not in cfg:
        return None
    try:
        return RunAxes.from_dict(cfg["axes"])
    except (KeyError, ValueError):
        return None


def cell_html(metrics: dict | None, axes: RunAxes, run_name: str) -> str:
    """Render one cell of the matrix."""
    if metrics is None:
        return '<td class="missing" title="Not yet generated">—</td>'

    q = metrics["q_per_seg"]
    r = metrics["react_per_seg"]
    w = metrics["words"]

    if q >= 5:
        cls = "high"
    elif q >= 2:
        cls = "mid"
    else:
        cls = "low"

    tooltip = (
        f"{run_name}\n"
        f"novel={axes.novel}, pipeline={axes.pipeline}, panel={axes.panel}, "
        f"hostprep={axes.hostprep}, generator={axes.generator}\n"
        f"{w:,} words, {metrics['segments']} segments, {metrics['turns']} turns\n"
        f"Q/seg: {q}, React/seg: {r}\n"
        f"Host: {metrics['host_pct']}%, Balance: {metrics['expert_balance']}\n"
        f"Quotes: {metrics['quotes']}"
    )

    return (
        f'<td class="done {cls}" title="{tooltip}">'
        f'<span class="q">{q}</span><br>'
        f'<span class="r">{r}</span><br>'
        f'<span class="w">{w//1000}k</span>'
        f"</td>"
    )


def _iter_columns(pipeline_order: tuple[str, ...]) -> list[tuple[str, str, bool, str]]:
    """(pipeline, panel, hostprep, short_label) in display order."""
    cols: list[tuple[str, str, bool, str]] = []
    for pipeline in pipeline_order:
        for panel in PANEL_ORDER:
            for hostprep in HOSTPREP_ORDER:
                short = f"{PIPELINE_DISPLAY[pipeline][:3]} {PANEL_SHORT[panel]}"
                if hostprep:
                    short += " +HP"
                cols.append((pipeline, panel, hostprep, short))
    return cols


def generate_html(generator: str, pipeline_order: tuple[str, ...]) -> str:
    """Build the tracking page for one generator."""
    if generator not in GENERATORS:
        raise ValueError(f"unknown generator {generator!r}; one of {sorted(GENERATORS)}")

    columns = _iter_columns(pipeline_order)
    rows: list[str] = []
    total = 0
    done = 0

    for novel in NOVELS:
        cells: list[str] = []
        for pipeline, panel, hostprep, _short in columns:
            total += 1
            rn = run_dir_name(
                novel=novel.key, pipeline=pipeline, panel=panel,
                hostprep=hostprep, generator=generator,
            )
            run_path = RUNS_DIR / rn
            axes_from_cfg = _config_axes(run_path)
            # Prefer axes from config.json (authoritative) over the name-derived
            # ones; fall back to constructed axes if config is missing but
            # phase3 exists (e.g. a freshly-created dir not yet configured).
            displayed_axes = axes_from_cfg or RunAxes(
                novel=novel.key, pipeline=pipeline, panel=panel,
                hostprep=hostprep, generator=generator,
            )
            metrics = measure_episode(run_path / "phase3_episode.json")
            if metrics:
                done += 1
            cells.append(cell_html(metrics, displayed_axes, rn))

        rows.append(
            f"<tr>"
            f'<td class="novel">{novel.title}</td>'
            f'<td class="author">{novel.author}</td>'
            f'<td class="year">{novel.year}</td>'
            f"{''.join(cells)}"
            f"</tr>"
        )

    # Two-row header: pipeline group, then pipeline×panel×hostprep.
    group_row = ""
    for pipeline in pipeline_order:
        span = len(PANEL_ORDER) * len(HOSTPREP_ORDER)
        group_row += f'<th colspan="{span}" class="group">{PIPELINE_DISPLAY[pipeline]}</th>'
    col_row = "".join(f"<th>{short}</th>" for _, _, _, short in columns)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    gen_info = GENERATOR_BY_ID[generator]
    other_gens = [g for g in sorted(GENERATORS) if g != generator]
    gen_links = " · ".join(
        f'<a href="run_tracker_{g}.html">{GENERATOR_BY_ID[g].display}</a>'
        for g in other_gens
    )

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>BleakHouse Experiment Matrix — {gen_info.display} ({done}/{total})</title>
<style>
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    margin: 2em;
    background: #f8f9fa;
    color: #1a1a1a;
}}
h1 {{ font-size: 1.4em; margin-bottom: 0.3em; }}
.subtitle {{ color: #666; margin-bottom: 1.5em; font-size: 0.9em; }}
table {{ border-collapse: collapse; font-size: 0.8em; width: 100%; }}
th, td {{
    border: 1px solid #ccc;
    padding: 4px 6px;
    text-align: center;
    vertical-align: middle;
}}
th {{ background: #2c3e50; color: white; font-weight: 500; font-size: 0.85em; }}
th.group {{ background: #34495e; }}
td.novel {{ text-align: left; font-weight: 600; background: #fff; white-space: nowrap; }}
td.author {{ text-align: left; color: #666; background: #fff; white-space: nowrap; }}
td.year {{ color: #888; background: #fff; }}
td.missing {{ background: #f5f5f5; color: #ccc; }}
td.done {{ cursor: help; }}
td.done.high {{ background: #d4edda; }}
td.done.mid {{ background: #fff3cd; }}
td.done.low {{ background: #f8d7da; }}
span.q {{ font-weight: 700; font-size: 1.1em; }}
span.r {{ color: #555; font-size: 0.85em; }}
span.w {{ color: #999; font-size: 0.8em; }}
.legend {{ margin-top: 1em; font-size: 0.8em; color: #666; }}
.legend span {{
    display: inline-block; width: 14px; height: 14px;
    margin-right: 3px; vertical-align: middle; border: 1px solid #ccc;
}}
.progress {{ font-size: 1.1em; margin-bottom: 1em; }}
.progress .bar {{ display: inline-block; height: 20px; background: #27ae60; border-radius: 3px; vertical-align: middle; }}
.progress .bar-bg {{ display: inline-block; height: 20px; width: 300px; background: #eee; border-radius: 3px; vertical-align: middle; }}
.gen-switch {{ margin-top: 0.5em; font-size: 0.85em; color: #666; }}
</style>
</head>
<body>
<h1>BleakHouse Experiment Matrix</h1>
<div class="subtitle">
    Generator: <strong>{gen_info.display}</strong> · {len(NOVELS)} novels &times; {len(pipeline_order)} pipelines &times; {len(PANEL_ORDER)} panels &times; {len(HOSTPREP_ORDER)} host-prep = {total} cells &mdash; Generated {now}
</div>

<div class="progress">
    <strong>{done}/{total}</strong> runs complete ({done*100//total if total else 0}%)
    <div class="bar-bg"><div class="bar" style="width: {done*300//total if total else 0}px"></div></div>
</div>

<div class="gen-switch">Other generators: {gen_links or '(none)'}</div>

<table>
<thead>
<tr>
    <th rowspan="2">Novel</th>
    <th rowspan="2">Author</th>
    <th rowspan="2">Year</th>
    {group_row}
</tr>
<tr>
    {col_row}
</tr>
</thead>
<tbody>
{"".join(rows)}
</tbody>
</table>

<div class="legend">
    <p>Each cell: <strong>Q/seg</strong> / reactive markers per seg / word count.
    Hover for all five axes + metrics.</p>
    <p>
        <span style="background:#d4edda"></span> Q/seg &ge; 5 (strong dialogue) &nbsp;
        <span style="background:#fff3cd"></span> Q/seg 2&ndash;5 (moderate) &nbsp;
        <span style="background:#f8d7da"></span> Q/seg &lt; 2 (monologue-like) &nbsp;
        <span style="background:#f5f5f5"></span> Not yet generated
    </p>
</div>

</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--generator",
        default=DEFAULT_GENERATOR,
        choices=sorted(GENERATORS),
        help=f"Which generator's matrix to render (default: {DEFAULT_GENERATOR}).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Render one file per generator: run_tracker.html (default) plus run_tracker_<gen>.html for each non-default.",
    )
    parser.add_argument(
        "--include-rag",
        action="store_true",
        help="Include the RAG (plain retrieval) pipeline column (paper-only baseline; hidden by default).",
    )
    args = parser.parse_args()

    # Quick sanity check that the canonical panel list aligns with axes.
    panel_ids = {p.id for p in PANELS_TUPLE}
    assert set(PANEL_ORDER) <= panel_ids, (
        f"PANEL_ORDER has panel ids not in axes.PANELS_TUPLE: {set(PANEL_ORDER) - panel_ids}"
    )

    pipeline_order = PIPELINE_ORDER_WITH_RAG if args.include_rag else DEFAULT_PIPELINE_ORDER

    if args.all:
        for g in sorted(GENERATORS):
            html = generate_html(g, pipeline_order)
            out = OUTPUT_PATH if g == DEFAULT_GENERATOR else OUTPUT_PATH.with_name(f"run_tracker_{g}.html")
            out.write_text(html)
            print(f"Written {out}")
    else:
        html = generate_html(args.generator, pipeline_order)
        out = OUTPUT_PATH if args.generator == DEFAULT_GENERATOR else OUTPUT_PATH.with_name(f"run_tracker_{args.generator}.html")
        out.write_text(html)
        print(f"Written {out}")


if __name__ == "__main__":
    main()
