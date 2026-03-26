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


def _phase_timings(rd: Path) -> dict:
    """Extract phase durations from file modification times."""
    from datetime import datetime, timezone

    files = {
        "config": rd / "config.json",
        "p0": rd / "phase0_segments.json",
        "p1": rd / "phase1_assignments.json",
        "p2": rd / "phase2_plan.json",
        "hp": rd / "phase2_5_host_briefs.json",
        "p3": rd / "phase3_episode.json",
    }

    mtimes: dict[str, float] = {}
    for key, path in files.items():
        if path.exists():
            mtimes[key] = path.stat().st_mtime

    result: dict = {}

    if "config" in mtimes:
        result["started"] = datetime.fromtimestamp(
            mtimes["config"], tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M")

    # Phase durations (minutes) — only if timestamps are plausible
    # (files created in sequence, not copied from elsewhere)
    def _dur(a: str, b: str) -> float | None:
        if a in mtimes and b in mtimes:
            d = (mtimes[b] - mtimes[a]) / 60
            return round(d, 1) if 0 < d < 60 else None
        return None

    result["p0_min"] = _dur("config", "p0")
    result["p1_min"] = _dur("p0", "p1")
    result["p2_min"] = _dur("p1", "p2")
    result["p25_min"] = _dur("p2", "hp") if "hp" in mtimes else None
    if "hp" in mtimes:
        result["p3_min"] = _dur("hp", "p3")
    else:
        result["p3_min"] = _dur("p2", "p3")

    if "config" in mtimes and "p3" in mtimes:
        total = (mtimes["p3"] - mtimes["config"]) / 60
        if 0 < total < 120:
            result["total_min"] = round(total, 1)

    return result


def _run_detail(runs_dir: Path, rn: str) -> dict:
    """Get status and detail for a run directory."""
    import time

    rd = runs_dir / rn
    if (rd / "phase3_episode.json").exists():
        m = _measure(rd / "phase3_episode.json")
        timings = _phase_timings(rd)
        return {"name": rn, "status": "done", **(m or {}), "timings": timings}
    if not (rd / "config.json").exists():
        return {"name": rn, "status": "missing"}

    # In progress — determine phase and progress
    has_p0 = (rd / "phase0_segments.json").exists()
    has_p1 = (rd / "phase1_assignments.json").exists()
    has_p2 = (rd / "phase2_plan.json").exists()
    has_hp = (rd / "phase2_5_host_briefs.json").exists()

    expects_hp = False
    try:
        cfg = json.load(open(rd / "config.json"))
        expects_hp = bool(cfg.get("host_prep"))
    except (json.JSONDecodeError, KeyError):
        pass

    if has_p2 and (has_hp or not expects_hp):
        phase = "Phase 3"
    elif has_p2 and expects_hp and not has_hp:
        phase = "Phase 2.5"
    elif has_p1:
        phase = "Phase 2"
    elif has_p0:
        phase = "Phase 1"
    else:
        phase = "Phase 0"

    # Start time from config.json mtime
    start_ts = rd / "config.json"
    started = int(start_ts.stat().st_mtime)

    # Elapsed time
    elapsed_min = round((time.time() - started) / 60, 1)

    # Estimate progress within Phase 3
    phase3_pct = 0
    total_segs = 0
    if phase == "Phase 3" and has_p0:
        try:
            segs = json.load(open(rd / "phase0_segments.json"))
            total_segs = len(segs)
        except (json.JSONDecodeError, KeyError):
            pass
        if total_segs > 0:
            # Count how many report.txt lines mention completed segments
            # Use the most recently modified file's mtime as a heartbeat
            mtimes = []
            for f in rd.iterdir():
                mtimes.append(f.stat().st_mtime)
            # Rough estimate: each segment takes ~90s in Phase 3
            elapsed_in_p3 = time.time() - (rd / "phase2_5_host_briefs.json" if has_hp
                                           else rd / "phase2_plan.json").stat().st_mtime
            segs_done_est = min(int(elapsed_in_p3 / 90), total_segs - 1)
            phase3_pct = round(segs_done_est / total_segs * 100)

    return {
        "name": rn, "status": "running", "phase": phase,
        "elapsed_min": elapsed_min, "started": started,
        "phase3_pct": phase3_pct, "total_segs": total_segs,
    }


def _check_process_alive() -> dict | None:
    """Check if a pipeline process is running and what it's doing."""
    import subprocess
    try:
        result = subprocess.run(
            ["pgrep", "-fl", "enrichment.run_pipeline|enrichment.embedding_run|enrichment.run_novel|run_full_matrix"],
            capture_output=True, text=True, timeout=5,
        )
        lines = [ln for ln in result.stdout.strip().split("\n") if ln and "pgrep" not in ln]
        if not lines:
            return None
        # Extract the run name from the command line
        for line in lines:
            m = re.search(r"--name\s+(\S+)", line)
            if m:
                return {"pid": line.split()[0], "run": m.group(1), "alive": True}
        return {"pid": lines[0].split()[0], "run": "unknown", "alive": True}
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _compute_phase_histograms() -> dict:
    """Compute timing histograms from completed runs."""
    runs_dir = DATA_DIR / "runs"
    p25_times: list[float] = []
    p3_times: list[float] = []

    for rd in runs_dir.iterdir():
        if not rd.is_dir():
            continue
        config_f = rd / "config.json"
        hp_briefs = rd / "phase2_5_host_briefs.json"
        episode = rd / "phase3_episode.json"

        if not (config_f.exists() and episode.exists()):
            continue

        cfg_mtime = config_f.stat().st_mtime
        ep_mtime = episode.stat().st_mtime

        if hp_briefs.exists():
            hp_mtime = hp_briefs.stat().st_mtime
            p25_dur = (hp_mtime - cfg_mtime) / 60
            p3_dur = (ep_mtime - hp_mtime) / 60
            if 1 < p25_dur < 30 and 5 < p3_dur < 30:
                p25_times.append(round(p25_dur, 1))
                p3_times.append(round(p3_dur, 1))
        else:
            total = (ep_mtime - cfg_mtime) / 60
            if 5 < total < 30:
                p3_times.append(round(total, 1))

    return {"p25": sorted(p25_times), "p3": sorted(p3_times)}


def _build_matrix_data() -> dict:
    runs_dir = DATA_DIR / "runs"
    rows = []
    total = 0
    done = 0
    running_count = 0
    running_names = []
    for novel_key, title, author, year in TRACKER_NOVELS:
        cells = []
        for pp, panel, hp in TRACKER_CONDITIONS:
            total += 1
            rn = _tracker_run_name(novel_key, pp, panel, hp)
            detail = _run_detail(runs_dir, rn)
            if detail["status"] == "done":
                done += 1
            elif detail["status"] == "running":
                running_count += 1
                running_names.append(rn)
            cells.append(detail)
        rows.append({"key": novel_key, "title": title, "author": author, "year": year, "cells": cells})

    process = _check_process_alive()
    histograms = _compute_phase_histograms()
    return {
        "rows": rows, "total": total, "done": done,
        "running": running_count, "running_names": running_names,
        "process": process, "histograms": histograms,
    }


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
td.run { background:#cce5ff; color:#004085; animation: pulse 2s ease-in-out infinite; }
@keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.6; } }
td.d { cursor:pointer; }
.popover {
    position:absolute; background:white; border:1px solid #999; border-radius:6px;
    padding:10px 14px; box-shadow:0 4px 12px rgba(0,0,0,.15); font-size:0.85em;
    z-index:100; max-width:320px; line-height:1.5;
}
.popover h3 { margin:0 0 6px; font-size:1em; color:#2c3e50; }
.popover .timing { color:#555; }
.popover .timing strong { color:#1a1a1a; }
.popover .close { float:right; cursor:pointer; color:#999; font-size:1.2em; }
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
<div id="procinfo" style="font-size:0.85em; color:#555; margin-bottom:1em;"></div>
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
<div id="histograms" style="display:flex; gap:2em; margin-bottom:1.5em;"></div>
<div class="legend">
<p><strong>Cell values</strong> (top to bottom):</p>
<table style="width:auto; margin:0.5em 0; font-size:1em;">
<tr><td style="border:none; text-align:left; padding:2px 8px;"><span class="q">5.1</span></td>
    <td style="border:none; text-align:left; padding:2px 8px;">Questions per segment &mdash; measures how conversational the host is</td></tr>
<tr><td style="border:none; text-align:left; padding:2px 8px;"><span class="r">14.3</span></td>
    <td style="border:none; text-align:left; padding:2px 8px;">Reactive markers per segment &mdash; cross-expert engagement (agreement, disagreement, building on)</td></tr>
<tr><td style="border:none; text-align:left; padding:2px 8px;"><span class="w">8k</span></td>
    <td style="border:none; text-align:left; padding:2px 8px;">Total episode word count (thousands)</td></tr>
</table>
<p><strong>Cell colours:</strong>
   <span style="background:#d4edda"></span> Q/seg &ge; 5 (strong dialogue)
   <span style="background:#fff3cd"></span> 2&ndash;5 (moderate)
   <span style="background:#f8d7da"></span> &lt; 2 (monologue-like)
   <span style="background:#cce5ff"></span> running
   <span style="background:#f5f5f5"></span> pending
</p>
<p><strong>Column abbreviations:</strong> A = Panel A (Hartley/Blackstone/Woodcourt),
   B = Panel B (Trevelyan/Leigh/Rosen), HP = host preparation (Phase 2.5)</p>
</div>
<script>
function render(data) {
    const pct = Math.round(data.done * 100 / data.total);
    const remaining = data.total - data.done;
    let status = `<strong>${data.done}/${data.total}</strong> (${pct}%) &mdash; ${remaining} remaining `;
    if (data.running > 0) status += `<span style="color:#004085">&bull; ${data.running} in progress</span> `;
    status += `<br><span class="bar-bg"><span class="bar" style="width:${data.done*300/data.total}px"></span></span>`;
    document.getElementById('progress').innerHTML = status;
    // Process info
    let pinfo = '';
    if (data.process && data.process.alive) {
        pinfo = `&#9654; Pipeline process alive (PID ${data.process.pid}), current run: <strong>${data.process.run}</strong>`;
        // Find the running cell to show details
        for (const row of data.rows) {
            for (const c of row.cells) {
                if (c.status === 'running' && c.phase === 'Phase 3') {
                    const pct = c.phase3_pct || 0;
                    const segs = c.total_segs || '?';
                    pinfo += ` &mdash; ${c.phase} (${segs} segments, ~${pct}% est.) &mdash; ${c.elapsed_min} min elapsed`;
                    break;
                } else if (c.status === 'running') {
                    pinfo += ` &mdash; ${c.phase} &mdash; ${c.elapsed_min} min elapsed`;
                    break;
                }
            }
        }
    } else if (data.running > 0) {
        pinfo = '&#9888; Runs in progress but no pipeline process detected &mdash; may have crashed';
    } else if (data.done < data.total) {
        pinfo = '&#9744; No pipeline process running. Use <code>uv run python -m enrichment.run_full_matrix --only-missing</code> to continue.';
    } else {
        pinfo = '&#9989; All 120 runs complete!';
    }
    document.getElementById('procinfo').innerHTML = pinfo;
    let html = '';
    for (const row of data.rows) {
        html += `<tr><td class="n">${row.title}</td><td class="a">${row.author}</td><td class="y">${row.year}</td>`;
        for (const c of row.cells) {
            if (c.status === 'missing') {
                html += '<td class="m">&mdash;</td>';
            } else if (c.status === 'running') {
                const ph = c.phase || '?';
                const pct = c.phase3_pct || 0;
                const elapsed = c.elapsed_min || 0;
                let inner = `<span style="font-size:0.75em;font-weight:600">${ph}</span>`;
                if (ph === 'Phase 3' && pct > 0) {
                    inner += `<br><span style="display:inline-block;width:90%;height:4px;background:#b8daff;border-radius:2px">` +
                        `<span style="display:inline-block;width:${pct}%;height:4px;background:#004085;border-radius:2px"></span></span>`;
                }
                inner += `<br><span style="font-size:0.7em;color:#004085">${elapsed}m</span>`;
                html += `<td class="run" title="${c.name} — ${ph} — ${elapsed} min">${inner}</td>`;
            } else {
                const cls = c.q >= 5 ? 'hi' : c.q >= 2 ? 'mi' : 'lo';
                const cdata = encodeURIComponent(JSON.stringify(c));
                html += `<td class="d ${cls}" onclick="showPopover(event, '${cdata}')">` +
                    `<span class="q">${c.q}</span><br>` +
                    `<span class="r">${c.r}</span><br>` +
                    `<span class="w">${Math.round(c.w/1000)}k</span></td>`;
            }
        }
        html += '</tr>';
    }
    document.getElementById('tbody').innerHTML = html;
    // Histograms
    if (data.histograms) renderHistograms(data.histograms);
}
function renderHistograms(h) {
    const container = document.getElementById('histograms');
    container.innerHTML = '';
    for (const [key, label] of [['p25','Phase 2.5 (host prep)'], ['p3','Phase 3 (script gen)']]) {
        const vals = h[key];
        if (!vals || vals.length === 0) continue;
        // Bucket into 1-min bins
        const min = Math.floor(Math.min(...vals));
        const max = Math.ceil(Math.max(...vals));
        const nbins = Math.max(max - min, 1);
        const bins = Array(nbins).fill(0);
        for (const v of vals) bins[Math.min(Math.floor(v) - min, nbins-1)]++;
        const peak = Math.max(...bins);
        const w = 220, h2 = 80, bw = Math.min(Math.floor(w / nbins), 20);
        const mean = (vals.reduce((a,b)=>a+b,0)/vals.length).toFixed(1);
        const median = vals[Math.floor(vals.length/2)].toFixed(1);
        let svg = `<div style="font-size:0.8em"><strong>${label}</strong><br>` +
            `<span style="color:#888">n=${vals.length}, mean=${mean}m, median=${median}m</span><br>` +
            `<svg width="${w+30}" height="${h2+20}" style="margin-top:4px">`;
        for (let i = 0; i < nbins; i++) {
            const bh = peak > 0 ? (bins[i]/peak) * h2 : 0;
            const x = i * bw + 20;
            const y = h2 - bh;
            svg += `<rect x="${x}" y="${y}" width="${bw-1}" height="${bh}" fill="#5b9bd5"/>`;
            if (i % 2 === 0 || nbins <= 10) {
                svg += `<text x="${x+bw/2}" y="${h2+12}" text-anchor="middle" font-size="9" fill="#888">${min+i}</text>`;
            }
        }
        svg += `<text x="10" y="${h2/2}" text-anchor="middle" transform="rotate(-90,10,${h2/2})" font-size="9" fill="#888">runs</text>`;
        svg += `</svg></div>`;
        container.innerHTML += svg;
    }
}
function showPopover(evt, encoded) {
    // Remove existing popover
    const old = document.getElementById('pop');
    if (old) old.remove();

    const c = JSON.parse(decodeURIComponent(encoded));
    const t = c.timings || {};

    let rows = '';
    const phases = [
        ['Phase 0 (segment design)', t.p0_min],
        ['Phase 1 (passage selection)', t.p1_min],
        ['Phase 2 (segment assignment)', t.p2_min],
        ['Phase 2.5 (host prep)', t.p25_min],
        ['Phase 3 (script generation)', t.p3_min],
    ];
    for (const [label, val] of phases) {
        if (val != null) {
            rows += `<div class="timing">${label}: <strong>${val} min</strong></div>`;
        }
    }
    if (t.total_min) {
        rows += `<div class="timing" style="margin-top:4px;border-top:1px solid #eee;padding-top:4px">Total: <strong>${t.total_min} min</strong></div>`;
    }
    if (!rows) {
        rows = '<div class="timing" style="color:#999">Timing data unavailable (files may have been copied)</div>';
    }

    const metrics = `<div style="margin-top:6px;border-top:1px solid #eee;padding-top:6px">` +
        `Q/seg: <strong>${c.q}</strong> &bull; React/seg: <strong>${c.r}</strong> &bull; ` +
        `Words: <strong>${c.w?.toLocaleString()}</strong> &bull; Quotes: <strong>${c.quotes}</strong></div>`;

    const started = t.started ? `<div style="color:#888;font-size:0.9em">Started: ${t.started}</div>` : '';

    const div = document.createElement('div');
    div.id = 'pop';
    div.className = 'popover';
    div.innerHTML = `<span class="close" onclick="this.parentElement.remove()">&times;</span>` +
        `<h3>${c.name}</h3>${started}${rows}${metrics}`;
    div.style.left = Math.min(evt.pageX + 10, window.innerWidth - 340) + 'px';
    div.style.top = (evt.pageY + 10) + 'px';
    document.body.appendChild(div);

    // Close on outside click
    setTimeout(() => {
        document.addEventListener('click', function handler(e) {
            if (!div.contains(e.target)) { div.remove(); document.removeEventListener('click', handler); }
        });
    }, 100);
}
const es = new EventSource('/tracker/stream');
es.onmessage = e => { render(JSON.parse(e.data)); document.getElementById('status').textContent = 'live'; };
es.onerror = () => { document.getElementById('status').textContent = 'reconnecting...'; };
fetch('/tracker/data').then(r => r.json()).then(render);
</script>
</body>
</html>
"""
