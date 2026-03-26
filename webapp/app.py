"""Podcast player web application with live experiment tracker.

Serves audio files, timing manifests, and a live-updating experiment
matrix via Server-Sent Events (SSE).

Usage:
    uv run uvicorn webapp.app:app --reload --port 8080
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import StreamingResponse

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Literary Podcast Player")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _discover_runs() -> dict[str, list[dict]]:
    """Find runs grouped by novel title."""
    novels: dict[str, list[dict]] = {}
    runs_dir = DATA_DIR / "runs"
    if not runs_dir.exists():
        return novels
    for run_dir in sorted(runs_dir.iterdir()):
        manifest_path = run_dir / "audio" / "manifest.json"
        podcast_path = run_dir / "audio" / "podcast.mp3"
        if manifest_path.exists() and podcast_path.exists():
            with open(manifest_path) as f:
                manifest = json.load(f)
            title = manifest.get("title", run_dir.name)
            novel = title.replace(": A Literary Discussion", "")
            # Determine pipeline condition from run name
            name = run_dir.name
            if "_nop_" in name or name.startswith("nop_"):
                condition = "no passages"
            elif "_emb_" in name or name.startswith("emb_"):
                condition = "embedding"
            elif "_rag_" in name or name.startswith("rag_"):
                condition = "RAG"
            elif "_rand_" in name or name.startswith("rand_"):
                condition = "random"
            else:
                condition = "transport"

            run_info = {
                "run_id": run_dir.name,
                "title": title,
                "novel": novel,
                "condition": condition,
                "passage_source": manifest.get("passage_source", "unknown"),
                "experts": manifest.get("experts", []),
                "total_duration_ms": manifest.get("total_duration_ms", 0),
            }
            novels.setdefault(novel, []).append(run_info)
    return novels


@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/novels")
async def list_novels():
    return _discover_runs()


@app.get("/api/runs/{run_id}/manifest")
async def get_manifest(run_id: str):
    manifest_path = DATA_DIR / "runs" / run_id / "audio" / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(404, f"No manifest for run {run_id}")
    with open(manifest_path) as f:
        return json.load(f)


@app.get("/audio/{run_id}/{filename}")
async def serve_audio(run_id: str, filename: str):
    if ".." in run_id or ".." in filename:
        raise HTTPException(400, "Invalid path")
    audio_path = DATA_DIR / "runs" / run_id / "audio" / filename
    if not audio_path.exists():
        raise HTTPException(404, f"Audio file not found: {filename}")
    return FileResponse(str(audio_path), media_type="audio/mpeg")


# ---------------------------------------------------------------------------
# Experiment tracker (SSE)
# ---------------------------------------------------------------------------

REACTIVE_RE = re.compile(
    r"\b(exactly|absolutely|that's|I agree|but I|yes but|I think|"
    r"you're right|that reminds|building on|to add to|I'd push back|"
    r"that's a great|fair point|interesting)\b",
    re.I,
)

TRACKER_NOVELS = [
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

TRACKER_PREFIXES = {
    "bleak_house": "", "our_mutual_friend": "omf", "mill_on_the_floss": "motf",
    "north_and_south": "nas", "passage_to_india": "pti", "hard_times": "ht",
    "middlemarch": "mid", "daniel_deronda": "dd", "david_copperfield": "dc",
    "cranford": "cran", "no_name": "noname", "new_grub_street": "ngs",
    "odd_women": "oddw", "miss_marjoribanks": "mmar", "hester": "hest",
}

TRACKER_CONDITIONS = [
    ("trn", "v01_baseline", False), ("trn", "v01_baseline", True),
    ("trn", "v19_all_swapped", False), ("trn", "v19_all_swapped", True),
    ("emb", "v01_baseline", False), ("emb", "v01_baseline", True),
    ("emb", "v19_all_swapped", False), ("emb", "v19_all_swapped", True),
]


def _tracker_run_name(novel_key: str, pp: str, panel: str, hp: bool) -> str:
    np = TRACKER_PREFIXES[novel_key]
    if novel_key == "bleak_house" and pp == "trn":
        pp = "ext"
    name = f"{np}_{pp}_{panel}" if np else f"{pp}_{panel}"
    if hp:
        name += "_hostprep"
    return name


def _measure(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        ep = json.load(open(path))
    except (json.JSONDecodeError, KeyError):
        return None
    segs = ep.get("segments", [])
    n = len(segs)
    if n == 0:
        return None
    words = 0
    questions = 0
    reactive = 0
    quotes = 0
    for seg in segs:
        for turn in seg.get("turns", []):
            text = " ".join(u.get("text", "") for u in turn.get("utterances", []))
            words += len(text.split())
            questions += text.count("?")
            reactive += len(REACTIVE_RE.findall(text))
            quotes += sum(1 for u in turn.get("utterances", []) if u.get("is_quote"))
    return {
        "w": words, "q": round(questions / n, 1),
        "r": round(reactive / n, 1), "quotes": quotes,
    }


def _build_matrix_data() -> dict:
    runs_dir = DATA_DIR / "runs"
    rows = []
    total = 0
    done = 0
    for novel_key, title, author, year in TRACKER_NOVELS:
        cells = []
        for pp, panel, hp in TRACKER_CONDITIONS:
            total += 1
            rn = _tracker_run_name(novel_key, pp, panel, hp)
            m = _measure(runs_dir / rn / "phase3_episode.json")
            if m:
                done += 1
                cells.append({"name": rn, "status": "done", **m})
            else:
                cells.append({"name": rn, "status": "missing"})
        rows.append({"key": novel_key, "title": title, "author": author, "year": year, "cells": cells})
    return {"rows": rows, "total": total, "done": done}


@app.get("/tracker", response_class=HTMLResponse)
async def tracker_page():
    return HTMLResponse(TRACKER_HTML)


@app.get("/tracker/data")
async def tracker_data():
    return _build_matrix_data()


@app.get("/tracker/stream")
async def tracker_stream():
    async def event_generator():
        prev = ""
        while True:
            data = _build_matrix_data()
            payload = json.dumps(data)
            if payload != prev:
                yield f"data: {payload}\n\n"
                prev = payload
            await asyncio.sleep(30)
    return StreamingResponse(event_generator(), media_type="text/event-stream")


TRACKER_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>BleakHouse Experiment Tracker</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    margin: 2em; background: #f8f9fa; color: #1a1a1a;
}
h1 { font-size: 1.4em; margin-bottom: 0.2em; }
.sub { color: #666; font-size: 0.9em; margin-bottom: 1em; }
#progress { font-size: 1.1em; margin-bottom: 1em; }
.bar-bg { display:inline-block; width:300px; height:20px; background:#eee; border-radius:3px; vertical-align:middle; }
.bar { display:inline-block; height:20px; background:#27ae60; border-radius:3px; }
table { border-collapse:collapse; font-size:0.8em; width:100%; }
th, td { border:1px solid #ccc; padding:4px 6px; text-align:center; vertical-align:middle; }
th { background:#2c3e50; color:white; font-weight:500; font-size:0.85em; }
th.g { background:#34495e; }
td.n { text-align:left; font-weight:600; background:#fff; white-space:nowrap; }
td.a { text-align:left; color:#666; background:#fff; }
td.y { color:#888; background:#fff; }
td.m { background:#f5f5f5; color:#ccc; }
td.d { cursor:help; }
td.hi { background:#d4edda; }
td.mi { background:#fff3cd; }
td.lo { background:#f8d7da; }
.q { font-weight:700; font-size:1.1em; }
.r { color:#555; font-size:0.85em; }
.w { color:#999; font-size:0.8em; }
.legend { margin-top:1em; font-size:0.8em; color:#666; }
.legend span { display:inline-block; width:14px; height:14px; margin-right:3px; vertical-align:middle; border:1px solid #ccc; }
#status { color:#27ae60; font-size:0.85em; }
</style>
</head>
<body>
<h1>BleakHouse Experiment Matrix</h1>
<div class="sub">15 novels &times; 2 panels &times; 2 pipelines &times; 2 host-prep = 120 runs
 &mdash; <span id="status">connecting...</span></div>
<div id="progress"></div>
<table>
<thead>
<tr>
    <th rowspan="2">Novel</th><th rowspan="2">Author</th><th rowspan="2">Year</th>
    <th colspan="4" class="g">Transport</th>
    <th colspan="4" class="g">Embedding</th>
</tr>
<tr>
    <th>A</th><th>A+HP</th><th>B</th><th>B+HP</th>
    <th>A</th><th>A+HP</th><th>B</th><th>B+HP</th>
</tr>
</thead>
<tbody id="tbody"></tbody>
</table>
<div class="legend">
<p>Each cell: <strong>Q/seg</strong> / reactive/seg / word count. Hover for run name.</p>
<p><span style="background:#d4edda"></span> Q/seg &ge;5
   <span style="background:#fff3cd"></span> 2&ndash;5
   <span style="background:#f8d7da"></span> &lt;2
   <span style="background:#f5f5f5"></span> pending</p>
</div>
<script>
function render(data) {
    const pct = Math.round(data.done * 100 / data.total);
    document.getElementById('progress').innerHTML =
        `<strong>${data.done}/${data.total}</strong> (${pct}%) ` +
        `<span class="bar-bg"><span class="bar" style="width:${data.done*300/data.total}px"></span></span>`;
    let html = '';
    for (const row of data.rows) {
        html += `<tr><td class="n">${row.title}</td><td class="a">${row.author}</td><td class="y">${row.year}</td>`;
        for (const c of row.cells) {
            if (c.status === 'missing') {
                html += '<td class="m">&mdash;</td>';
            } else {
                const cls = c.q >= 5 ? 'hi' : c.q >= 2 ? 'mi' : 'lo';
                html += `<td class="d ${cls}" title="${c.name}">` +
                    `<span class="q">${c.q}</span><br>` +
                    `<span class="r">${c.r}</span><br>` +
                    `<span class="w">${Math.round(c.w/1000)}k</span></td>`;
            }
        }
        html += '</tr>';
    }
    document.getElementById('tbody').innerHTML = html;
}
const es = new EventSource('/tracker/stream');
es.onmessage = e => { render(JSON.parse(e.data)); document.getElementById('status').textContent = 'live'; };
es.onerror = () => { document.getElementById('status').textContent = 'reconnecting...'; };
fetch('/tracker/data').then(r => r.json()).then(render);
</script>
</body>
</html>
"""
