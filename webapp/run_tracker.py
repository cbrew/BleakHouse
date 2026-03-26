"""Generate a run-tracking HTML page showing the 120-run experiment matrix.

Inspired by the evaluation tables in Croft, Metzler & Strohman's
*Search Engines: Information Retrieval in Practice* — topics down the
rows, systems across the columns, scores in each cell.

Usage:
    uv run python -m webapp.run_tracker
    # Opens data/run_tracker.html
"""

import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = BASE_DIR / "data" / "runs"
OUTPUT_PATH = BASE_DIR / "data" / "run_tracker.html"

REACTIVE = re.compile(
    r"\b(exactly|absolutely|that's|I agree|but I|yes but|I think|"
    r"you're right|that reminds|building on|to add to|I'd push back|"
    r"that's a great|fair point|interesting)\b",
    re.I,
)

NOVELS = [
    ("bleak_house", "Bleak House", "Dickens", 1853),
    ("our_mutual_friend", "Our Mutual Friend", "Dickens", 1865),
    ("david_copperfield", "David Copperfield", "Dickens", 1850),
    ("hard_times", "Hard Times", "Dickens", 1854),
    ("mill_on_the_floss", "Mill on the Floss", "Eliot", 1860),
    ("middlemarch", "Middlemarch", "Eliot", 1871),
    ("daniel_deronda", "Daniel Deronda", "Eliot", 1876),
    ("north_and_south", "North and South", "Gaskell", 1855),
    ("cranford", "Cranford", "Gaskell", 1853),
    ("passage_to_india", "Passage to India", "Forster", 1924),
    ("no_name", "No Name", "Collins", 1862),
    ("new_grub_street", "New Grub Street", "Gissing", 1891),
    ("odd_women", "The Odd Women", "Gissing", 1893),
    ("miss_marjoribanks", "Miss Marjoribanks", "Oliphant", 1866),
    ("hester", "Hester", "Oliphant", 1883),
]

NOVEL_PREFIXES = {
    "bleak_house": "",
    "our_mutual_friend": "omf",
    "mill_on_the_floss": "motf",
    "north_and_south": "nas",
    "passage_to_india": "pti",
    "hard_times": "ht",
    "middlemarch": "mid",
    "daniel_deronda": "dd",
    "david_copperfield": "dc",
    "cranford": "cran",
    "no_name": "noname",
    "new_grub_street": "ngs",
    "odd_women": "oddw",
    "miss_marjoribanks": "mmar",
    "hester": "hest",
}

CONDITIONS = [
    ("trn", "v01_baseline", False, "Transport A"),
    ("trn", "v01_baseline", True, "Transport A + HP"),
    ("trn", "v19_all_swapped", False, "Transport B"),
    ("trn", "v19_all_swapped", True, "Transport B + HP"),
    ("emb", "v01_baseline", False, "Embedding A"),
    ("emb", "v01_baseline", True, "Embedding A + HP"),
    ("emb", "v19_all_swapped", False, "Embedding B"),
    ("emb", "v19_all_swapped", True, "Embedding B + HP"),
]


def run_dir_name(novel_key: str, pipeline_prefix: str, panel: str, hostprep: bool) -> str:
    """Build the run directory name."""
    np = NOVEL_PREFIXES[novel_key]
    # Bleak House uses 'ext' for transport
    if novel_key == "bleak_house" and pipeline_prefix == "trn":
        pipeline_prefix = "ext"
    if np:
        name = f"{np}_{pipeline_prefix}_{panel}"
    else:
        name = f"{pipeline_prefix}_{panel}"
    if hostprep:
        name += "_hostprep"
    return name


def measure_episode(path: str) -> dict | None:
    """Extract key metrics from a phase3_episode.json."""
    try:
        ep = json.load(open(path))
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


def cell_html(metrics: dict | None, run_name: str) -> str:
    """Render one cell of the matrix."""
    if metrics is None:
        return '<td class="missing" title="Not yet generated">—</td>'

    q = metrics["q_per_seg"]
    r = metrics["react_per_seg"]
    w = metrics["words"]

    # Color by Q/seg: higher = more conversational
    if q >= 5:
        cls = "high"
    elif q >= 2:
        cls = "mid"
    else:
        cls = "low"

    tooltip = (
        f"{run_name}\n"
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


def generate_html() -> str:
    """Build the full tracking page."""
    rows = []
    total = 0
    done = 0

    for novel_key, title, author, year in NOVELS:
        cells = []
        for pipeline_prefix, panel, hostprep, _label in CONDITIONS:
            total += 1
            rn = run_dir_name(novel_key, pipeline_prefix, panel, hostprep)
            ep_path = RUNS_DIR / rn / "phase3_episode.json"
            metrics = measure_episode(str(ep_path))
            if metrics:
                done += 1
            cells.append(cell_html(metrics, rn))

        rows.append(
            f"<tr>"
            f'<td class="novel">{title}</td>'
            f'<td class="author">{author}</td>'
            f'<td class="year">{year}</td>'
            f"{''.join(cells)}"
            f"</tr>"
        )

    col_headers = "".join(
        f"<th>{label}</th>" for _, _, _, label in CONDITIONS
    )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>BleakHouse Experiment Matrix — {done}/{total}</title>
<style>
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    margin: 2em;
    background: #f8f9fa;
    color: #1a1a1a;
}}
h1 {{ font-size: 1.4em; margin-bottom: 0.3em; }}
.subtitle {{ color: #666; margin-bottom: 1.5em; font-size: 0.9em; }}
table {{
    border-collapse: collapse;
    font-size: 0.8em;
    width: 100%;
}}
th, td {{
    border: 1px solid #ccc;
    padding: 4px 6px;
    text-align: center;
    vertical-align: middle;
}}
th {{
    background: #2c3e50;
    color: white;
    font-weight: 500;
    font-size: 0.85em;
}}
th.group {{
    background: #34495e;
}}
td.novel {{
    text-align: left;
    font-weight: 600;
    background: #fff;
    white-space: nowrap;
}}
td.author {{
    text-align: left;
    color: #666;
    background: #fff;
    white-space: nowrap;
}}
td.year {{
    color: #888;
    background: #fff;
}}
td.missing {{
    background: #f5f5f5;
    color: #ccc;
}}
td.done {{
    cursor: help;
}}
td.done.high {{
    background: #d4edda;
}}
td.done.mid {{
    background: #fff3cd;
}}
td.done.low {{
    background: #f8d7da;
}}
span.q {{
    font-weight: 700;
    font-size: 1.1em;
}}
span.r {{
    color: #555;
    font-size: 0.85em;
}}
span.w {{
    color: #999;
    font-size: 0.8em;
}}
.legend {{
    margin-top: 1em;
    font-size: 0.8em;
    color: #666;
}}
.legend span {{
    display: inline-block;
    width: 14px;
    height: 14px;
    margin-right: 3px;
    vertical-align: middle;
    border: 1px solid #ccc;
}}
.progress {{
    font-size: 1.1em;
    margin-bottom: 1em;
}}
.progress .bar {{
    display: inline-block;
    height: 20px;
    background: #27ae60;
    border-radius: 3px;
    vertical-align: middle;
}}
.progress .bar-bg {{
    display: inline-block;
    height: 20px;
    width: 300px;
    background: #eee;
    border-radius: 3px;
    vertical-align: middle;
}}
</style>
</head>
<body>
<h1>BleakHouse Experiment Matrix</h1>
<div class="subtitle">15 novels &times; 2 panels &times; 2 pipelines &times; 2 host-prep = 120 runs &mdash; Generated {now}</div>

<div class="progress">
    <strong>{done}/{total}</strong> runs complete ({done*100//total}%)
    <div class="bar-bg"><div class="bar" style="width: {done*300//total}px"></div></div>
</div>

<table>
<thead>
<tr>
    <th rowspan="2">Novel</th>
    <th rowspan="2">Author</th>
    <th rowspan="2">Year</th>
    <th colspan="4" class="group">Transport</th>
    <th colspan="4" class="group">Embedding</th>
</tr>
<tr>
    {col_headers}
</tr>
</thead>
<tbody>
{"".join(rows)}
</tbody>
</table>

<div class="legend">
    <p>Each cell shows: <strong>Q/seg</strong> (questions per segment) / reactive markers per seg / word count.
    Hover for details.</p>
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
    html = generate_html()
    OUTPUT_PATH.write_text(html)
    print(f"Written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
