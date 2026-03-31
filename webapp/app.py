"""Podcast player web application with live experiment tracker.

Serves audio files, timing manifests, and a live-updating experiment
matrix via Server-Sent Events (SSE).

Usage:
    uv run uvicorn webapp.app:app --reload --port 8080
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Literary Podcast Player")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


VERSION_PATTERN = re.compile(r"_v1_(\d+)$")


def _parse_version(run_name: str) -> tuple[str, str]:
    """Extract (base_name, version) from a run name.

    Returns ("ext_v01_baseline_hostprep", "v1.0") for unversioned runs,
    ("ext_v01_baseline_hostprep", "v1.2") for runs ending in _v1_2.
    """
    m = VERSION_PATTERN.search(run_name)
    if m:
        return run_name[: m.start()], f"v1.{m.group(1)}"
    return run_name, "v1.0"


def _classify_run(name: str) -> tuple[str, str, bool]:
    """Return (condition, panel, hostprep) from a run directory name."""
    if "_nop_" in name or name.startswith("nop_"):
        condition = "no passages"
    elif "_emb_" in name or name.startswith("emb_"):
        condition = "embedding"
    elif "_rag_" in name or name.startswith("rag_"):
        condition = "RAG"
    elif "_rand_" in name or name.startswith("rand_"):
        condition = "random"
    elif "interdisciplinary" in name:
        condition = "interdisciplinary"
    else:
        condition = "transport"

    if "interdisciplinary" in name:
        panel = "Chen / Martinez / Volkov"
    elif "_v19_" in name:
        panel = "Panel B (Trevelyan / Leigh / Rosen)"
    else:
        panel = "Panel A (Hartley / Blackstone / Woodcourt)"

    hostprep = "_hostprep" in name
    return condition, panel, hostprep


def _discover_runs(*, include_scriptonly: bool = False) -> dict[str, list[dict]]:
    """Find runs grouped by novel title.

    Discovers runs with audio (audio/manifest.json) by default.
    If include_scriptonly=True, also includes runs with only a
    manifest.json (no audio) — these get has_audio=False.
    """
    novels: dict[str, list[dict]] = {}
    runs_dir = DATA_DIR / "runs"
    if not runs_dir.exists():
        return novels
    for run_dir in sorted(runs_dir.iterdir()):
        audio_manifest = run_dir / "audio" / "manifest.json"
        run_manifest = run_dir / "manifest.json"

        has_audio = audio_manifest.exists()
        if not has_audio and not include_scriptonly:
            continue

        manifest_path = audio_manifest if has_audio else run_manifest
        if not manifest_path.exists():
            continue

        with open(manifest_path) as f:
            mf = json.load(f)
        title = mf.get("title", run_dir.name)
        novel = title.replace(": A Literary Discussion", "")

        name = run_dir.name
        base_name, version = _parse_version(name)
        condition, panel, hostprep = _classify_run(name)

        run_info = {
            "run_id": name,
            "base_name": base_name,
            "version": version,
            "title": title,
            "novel": novel,
            "condition": condition,
            "panel": panel,
            "hostprep": hostprep,
            "passage_source": mf.get("passage_source", "unknown"),
            "experts": mf.get("experts", []),
            "total_duration_ms": mf.get("total_duration_ms", 0),
            "has_audio": has_audio,
            "has_host_prep": (run_dir / "phase2_5_host_briefs.json").exists(),
        }
        novels.setdefault(novel, []).append(run_info)
    return novels


PAGES_DIR = Path(__file__).resolve().parent / "pages"


@app.get("/", response_class=HTMLResponse)
async def landing():
    return FileResponse(str(PAGES_DIR / "landing.html"))


@app.get("/player", response_class=HTMLResponse)
async def player():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/about", response_class=HTMLResponse)
async def about_page():
    return FileResponse(str(PAGES_DIR / "about.html"))


@app.get("/blog", response_class=HTMLResponse)
async def blog_page():
    return FileResponse(str(PAGES_DIR / "blog.html"))


@app.get("/blog/{post_id}", response_class=HTMLResponse)
async def blog_post(post_id: str):
    if ".." in post_id:
        raise HTTPException(400, "Invalid path")
    path = PAGES_DIR / f"blog_{post_id}.html"
    if not path.exists():
        raise HTTPException(404, f"Blog post not found: {post_id}")
    return FileResponse(str(path))


@app.get("/prompts", response_class=HTMLResponse)
async def prompts_page():
    return FileResponse(str(PAGES_DIR / "prompts.html"))


@app.get("/metrics", response_class=HTMLResponse)
async def metrics_page():
    return FileResponse(str(PAGES_DIR / "metrics.html"))


@app.get("/examples", response_class=HTMLResponse)
async def examples_page():
    return FileResponse(str(PAGES_DIR / "examples.html"))


@app.get("/help", response_class=HTMLResponse)
async def help_page():
    return FileResponse(str(PAGES_DIR / "help.html"))


@app.get("/references", response_class=HTMLResponse)
async def references_page():
    return FileResponse(str(PAGES_DIR / "references.html"))


@app.get("/research", response_class=HTMLResponse)
async def research_page():
    return FileResponse(str(PAGES_DIR / "research.html"))


_tts_progress: dict[str, dict] = {}  # run_id/seg_idx -> {done, total, status}


@app.get("/api/tts/{run_id}/{segment_idx}/status")
async def tts_status(run_id: str, segment_idx: int):
    """Check rendering progress for a segment."""
    key = f"{run_id}/{segment_idx}"
    cache_dir = AUDIO_VOLUME / "kokoro_cache" if AUDIO_VOLUME.exists() else Path("/tmp/kokoro_cache")
    cache_path = cache_dir / run_id / f"segment_{segment_idx}.wav"
    if cache_path.exists():
        return {"status": "ready"}
    return _tts_progress.get(key, {"status": "pending", "done": 0, "total": 0})


@app.get("/api/tts/{run_id}/{segment_idx}")
async def tts_segment(run_id: str, segment_idx: int):
    """Render one segment via Kokoro TTS. Runs in a thread so status polls work."""
    import asyncio
    if ".." in run_id:
        raise HTTPException(400, "Invalid path")

    # Cache on volume (fly) or /tmp (local dev)
    cache_dir = AUDIO_VOLUME / "kokoro_cache" if AUDIO_VOLUME.exists() else Path("/tmp/kokoro_cache")
    cache_path = cache_dir / run_id / f"segment_{segment_idx}.wav"
    if cache_path.exists():
        return FileResponse(str(cache_path), media_type="audio/wav")

    # Load episode
    ep_path = DATA_DIR / "runs" / run_id / "phase3_episode.json"
    if not ep_path.exists():
        raise HTTPException(404, f"No episode for {run_id}")
    with open(ep_path) as f:
        episode = json.load(f)

    segments = episode.get("segments", [])
    if segment_idx < 0 or segment_idx >= len(segments):
        raise HTTPException(404, f"Segment {segment_idx} not found (have {len(segments)})")

    seg = segments[segment_idx]
    turns = seg.get("turns", [])
    total_turns = len(turns)
    progress_key = f"{run_id}/{segment_idx}"
    _tts_progress[progress_key] = {"status": "rendering", "done": 0, "total": total_turns}

    def _render():
        import numpy as np
        from webapp.kokoro_voices import get_kokoro_voice
        from webapp.kokoro_tts import synthesize_turn

        sample_rate = 24000
        all_samples = []

        for turn_i, turn in enumerate(turns):
            speaker = turn.get("speaker", "Host")
            voice, _lang = get_kokoro_voice(speaker)
            text = " ".join(u.get("text", "") for u in turn.get("utterances", []))
            if not text.strip():
                continue
            rate = 1.0
            if turn.get("utterances"):
                rate = turn["utterances"][0].get("rate", 1.0)
            try:
                samples, sr = synthesize_turn(text, voice, speed=rate)
                if sr != sample_rate:
                    samples = np.interp(
                        np.linspace(0, len(samples), int(len(samples) * sample_rate / sr)),
                        np.arange(len(samples)), samples
                    ).astype(np.float32)
                all_samples.append(samples)
            except Exception as e:
                logger.warning("TTS failed for %s turn by %s: %s", run_id, speaker, e)
                continue
            all_samples.append(np.zeros(int(sample_rate * 0.2), dtype=np.float32))
            _tts_progress[progress_key] = {"status": "rendering", "done": turn_i + 1, "total": total_turns}

        if not all_samples:
            return None
        combined = np.concatenate(all_samples)
        import soundfile as sf
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(cache_path), combined, sample_rate)
        logger.info("Kokoro: rendered %s segment %d (%.1fs audio)", run_id, segment_idx, len(combined) / sample_rate)
        return cache_path

    # Run in thread so status polls can be served concurrently
    result = await asyncio.get_event_loop().run_in_executor(None, _render)
    _tts_progress.pop(progress_key, None)

    if result is None:
        raise HTTPException(500, "No audio generated")
    return FileResponse(str(result), media_type="audio/wav")


@app.post("/api/pageview")
async def log_pageview(request: Request):
    """Log a page view to JSONL on the persistent volume."""
    import time
    try:
        body = await request.json()
    except Exception:
        return {"status": "ok"}
    page = (body.get("page") or "")[:200]
    ref = (body.get("ref") or "")[:500]
    if not page:
        return {"status": "ok"}
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "page": page,
        "ref": ref,
    }
    try:
        PAGEVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PAGEVIEW_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # volume not mounted locally
    return {"status": "ok"}


@app.post("/api/feedback")
async def submit_feedback(request: Request):
    """Append feedback to JSONL file on the persistent volume."""
    import time
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")
    rating = body.get("rating")  # "up" or "down"
    text = (body.get("text") or "")[:1000]  # cap at 1000 chars
    page = (body.get("page") or "")[:200]
    if rating not in ("up", "down", None):
        raise HTTPException(400, "rating must be 'up' or 'down'")
    if not rating and not text:
        raise HTTPException(400, "Provide rating and/or text")
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "page": page,
        "rating": rating,
        "text": text,
    }
    try:
        FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(FEEDBACK_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        # Volume might not be mounted locally
        logger.warning("Could not write feedback: %s", entry)
    return {"status": "ok"}


@app.get("/api/novels")
async def list_novels():
    return _discover_runs(include_scriptonly=True)


@app.get("/api/all-runs")
async def list_all_runs():
    """List ALL runs with scripts, grouped by novel. Includes audio state."""
    novels: dict[str, list[dict]] = {}
    runs_dir = DATA_DIR / "runs"
    if not runs_dir.exists():
        return novels
    for run_dir in sorted(runs_dir.iterdir()):
        ep_path = run_dir / "phase3_episode.json"
        if not ep_path.exists():
            continue

        # Load title from manifest or episode
        manifest_path = run_dir / "manifest.json"
        if manifest_path.exists():
            with open(manifest_path) as f:
                manifest = json.load(f)
            title = manifest.get("title", run_dir.name)
            experts = manifest.get("experts", [])
        else:
            with open(ep_path) as f:
                ep = json.load(f)
            title = ep.get("title", run_dir.name)
            experts = []

        novel = title.replace(": A Literary Discussion", "")
        name = run_dir.name

        # Determine condition and panel
        if "_nop_" in name or name.startswith("nop_"):
            condition = "no passages"
        elif "_emb_" in name or name.startswith("emb_"):
            condition = "embedding"
        elif "interdisciplinary" in name:
            condition = "interdisciplinary"
        else:
            condition = "transport"

        has_gemini = (run_dir / "audio" / "manifest.json").exists()
        audio_state = "gemini" if has_gemini else "kokoro"

        run_info = {
            "run_id": name,
            "title": title,
            "novel": novel,
            "condition": condition,
            "hostprep": "_hostprep" in name,
            "audio_state": audio_state,
            "experts": experts,
        }
        novels.setdefault(novel, []).append(run_info)
    return novels


@app.get("/api/runs/{run_id}/manifest")
async def get_manifest(run_id: str):
    # Check audio manifest first, then run-level manifest
    audio_manifest = DATA_DIR / "runs" / run_id / "audio" / "manifest.json"
    run_manifest = DATA_DIR / "runs" / run_id / "manifest.json"
    manifest_path = audio_manifest if audio_manifest.exists() else run_manifest
    if not manifest_path.exists():
        raise HTTPException(404, f"No manifest for run {run_id}")
    with open(manifest_path) as f:
        return json.load(f)


@app.get("/report/{run_id}", response_class=HTMLResponse)
async def report_viewer(run_id: str):
    if ".." in run_id:
        raise HTTPException(400, "Invalid path")
    report_path = DATA_DIR / "runs" / run_id / "report.html"
    if not report_path.exists():
        raise HTTPException(404, f"No report for run {run_id}")
    return FileResponse(str(report_path))


@app.get("/api/runs/{run_id}/episode")
async def get_episode(run_id: str):
    """Serve the raw phase3_episode.json for any run."""
    if ".." in run_id:
        raise HTTPException(400, "Invalid path")
    ep_path = DATA_DIR / "runs" / run_id / "phase3_episode.json"
    if not ep_path.exists():
        raise HTTPException(404, f"No episode for run {run_id}")
    with open(ep_path) as f:
        return json.load(f)


@app.get("/script/{run_id}", response_class=HTMLResponse)
async def script_viewer(run_id: str):
    """Serve the script viewer page for a run."""
    if ".." in run_id:
        raise HTTPException(400, "Invalid path")
    ep_path = DATA_DIR / "runs" / run_id / "phase3_episode.json"
    if not ep_path.exists():
        raise HTTPException(404, f"No episode for run {run_id}")
    return HTMLResponse(SCRIPT_VIEWER_HTML)


AUDIO_VOLUME = Path("/app/audio_volume")
FEEDBACK_FILE = AUDIO_VOLUME / "feedback.jsonl"  # on the persistent volume
PAGEVIEW_FILE = AUDIO_VOLUME / "pageviews.jsonl"
KOKORO_CACHE = AUDIO_VOLUME / "kokoro_cache"

@app.get("/audio/{run_id}/{filename}")
async def serve_audio(run_id: str, filename: str):
    if ".." in run_id or ".." in filename:
        raise HTTPException(400, "Invalid path")
    # Check run-local audio first, then fly volume
    audio_path = DATA_DIR / "runs" / run_id / "audio" / filename
    if not audio_path.exists():
        audio_path = AUDIO_VOLUME / run_id / filename
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
    ("nop", "v01_baseline", False), ("nop", "v01_baseline", True),
    ("nop", "v19_all_swapped", False), ("nop", "v19_all_swapped", True),
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
    quote_modes: dict[str, int] = {"setup": 0, "reading": 0, "commentary": 0}
    for seg in segs:
        for turn in seg.get("turns", []):
            text = " ".join(u.get("text", "") for u in turn.get("utterances", []))
            words += len(text.split())
            questions += text.count("?")
            reactive += len(REACTIVE_RE.findall(text))
            for u in turn.get("utterances", []):
                if u.get("is_quote"):
                    quotes += 1
                mode = u.get("quote_mode", "none")
                if mode in quote_modes:
                    quote_modes[mode] += 1
    return {
        "w": words, "q": round(questions / n, 1),
        "r": round(reactive / n, 1), "quotes": quotes,
        "quote_modes": quote_modes,
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
    # Phase 2.5: use config→hp duration if plausible (hostprep runs copy
    # phase2_plan from old runs, making p2→hp unreliable). A real Phase 2.5
    # takes 4-6 minutes, so config→hp should be < 30 min for a hostprep run.
    if "hp" in mtimes and "config" in mtimes:
        config_to_hp = (mtimes["hp"] - mtimes["config"]) / 60
        if 1 < config_to_hp < 30:
            # Subtract phases 0-2 time if available
            p012_time = sum(
                v for v in [result.get("p0_min"), result.get("p1_min"), result.get("p2_min")]
                if v is not None
            )
            p25_est = round(config_to_hp - p012_time, 1)
            result["p25_min"] = p25_est if p25_est > 0 else _dur("p2", "hp")
        else:
            result["p25_min"] = None  # implausible, probably copied files
    else:
        result["p25_min"] = None

    if "hp" in mtimes:
        result["p3_min"] = _dur("hp", "p3")
    else:
        result["p3_min"] = _dur("p2", "p3")

    if "config" in mtimes and "p3" in mtimes:
        total = (mtimes["p3"] - mtimes["config"]) / 60
        if 0 < total < 120:
            result["total_min"] = round(total, 1)

    return result


def _load_quote_verification(rd: Path) -> dict | None:
    """Load cached quote verification results."""
    qv_path = rd / "quote_verification.json"
    if qv_path.exists():
        try:
            return json.load(open(qv_path))
        except (json.JSONDecodeError, KeyError):
            pass
    return None


def _run_detail(runs_dir: Path, rn: str) -> dict:
    """Get status and detail for a run directory."""
    import time

    rd = runs_dir / rn
    if (rd / "phase3_episode.json").exists():
        m = _measure(rd / "phase3_episode.json")
        timings = _phase_timings(rd)
        qv = _load_quote_verification(rd)
        has_gemini = (rd / "audio" / "manifest.json").exists()
        # Also check the 'ext' variant name (older runs used ext instead of trn)
        if not has_gemini and "_trn_" in rn:
            alt_rd = runs_dir / rn.replace("_trn_", "_ext_")
            has_gemini = (alt_rd / "audio" / "manifest.json").exists()
        # audio_state: "gemini" (pre-rendered), "kokoro" (on-demand)
        audio_state = "gemini" if has_gemini else "kokoro"
        return {"name": rn, "status": "done", **(m or {}), "timings": timings, "qv": qv, "has_audio": has_gemini, "audio_state": audio_state}
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
    active_run = process["run"] if process and process.get("alive") else None

    # Distinguish actively-running from stalled (crashed) partial runs
    for row in rows:
        for cell in row["cells"]:
            if cell["status"] == "running":
                if active_run and cell["name"] == active_run:
                    pass  # genuinely running
                elif active_run and active_run != "unknown":
                    cell["status"] = "stalled"
                # If process alive but run unknown, leave as "running" (ambiguous)

    # Recount after reclassification
    running_count = sum(
        1 for row in rows for cell in row["cells"] if cell["status"] == "running"
    )
    stalled_count = sum(
        1 for row in rows for cell in row["cells"] if cell["status"] == "stalled"
    )

    histograms = _compute_phase_histograms()
    return {
        "rows": rows, "total": total, "done": done,
        "running": running_count, "stalled": stalled_count,
        "running_names": [c["name"] for row in rows for c in row["cells"] if c["status"] == "running"],
        "process": process, "histograms": histograms,
    }


@app.get("/tracker", response_class=HTMLResponse)
async def tracker_page():
    return HTMLResponse(TRACKER_HTML)


@app.get("/tracker/data")
async def tracker_data():
    return _build_matrix_data()


def _build_version_data() -> dict:
    """Build data for the version comparison view (v1.1+)."""
    runs_dir = DATA_DIR / "runs"
    if not runs_dir.exists():
        return {"versions": {}, "runs": []}

    runs_by_version: dict[str, list[dict]] = {}
    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        name = run_dir.name
        base, version = _parse_version(name)
        if version == "v1.0":
            continue  # Matrix handles v1.0

        episode = run_dir / "phase3_episode.json"
        reading_list_path = run_dir / "phase2_5_reading_list.json"
        report_path = run_dir / "report.html"

        # Classify
        condition, panel, hostprep = _classify_run(name)

        # Determine novel from config or name
        novel = "Unknown"
        config_path = run_dir / "config.json"
        if config_path.exists():
            with open(config_path) as f:
                cfg = json.load(f)
            novel = cfg.get("novel", "unknown").replace("_", " ").title()
        elif "pti_" in name or "passage_to_india" in name:
            novel = "Passage To India"
        elif name.startswith("ext_") or name.startswith("interdisciplinary"):
            novel = "Bleak House"

        # Metrics
        metrics: dict = {}
        if episode.exists():
            with open(episode) as f:
                ep = json.load(f)
            total_words = sum(
                len(u.get("text", "").split())
                for seg in ep.get("segments", [])
                for turn in seg.get("turns", [])
                for u in turn.get("utterances", [])
            )
            total_turns = sum(
                len(seg.get("turns", []))
                for seg in ep.get("segments", [])
            )
            metrics = {"words": total_words, "turns": total_turns,
                       "segments": len(ep.get("segments", []))}

        # Reading list summary
        reading: dict = {}
        if reading_list_path.exists():
            with open(reading_list_path) as f:
                rl = json.load(f)
            reading = {
                "verified": rl.get("total_verified", 0),
                "total": rl.get("total_proposed", 0),
                "rate": rl.get("verification_rate", 0),
                "recommended": rl.get("recommended", []),
            }

        run_info = {
            "run_id": name,
            "base_name": base,
            "version": version,
            "novel": novel,
            "condition": condition,
            "panel": panel,
            "hostprep": hostprep,
            "has_episode": episode.exists(),
            "has_report": report_path.exists(),
            "has_reading_list": reading_list_path.exists(),
            "has_audio": (run_dir / "audio" / "manifest.json").exists(),
            "metrics": metrics,
            "reading": reading,
        }
        runs_by_version.setdefault(version, []).append(run_info)

    return {"versions": {v: len(r) for v, r in runs_by_version.items()},
            "runs": [r for runs in runs_by_version.values() for r in runs]}


@app.get("/tracker/versions")
async def tracker_versions_data():
    return _build_version_data()


@app.get("/versions", response_class=HTMLResponse)
async def versions_page():
    return HTMLResponse(VERSIONS_HTML)


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
<script src="/static/nav.js" defer></script>
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
<div class="sub">15 novels &times; 2 panels &times; 3 pipelines &times; 2 host-prep = 180 runs
 &mdash; <span id="status">connecting...</span></div>
<div style="color:#8888aa;font-size:0.85em;margin-bottom:0.8em">Click any cell to see details and links. Columns: A/B = expert panels, HP = with host preparation. <a href="/help" style="color:#6fa8dc">More help</a> &middot; <a href="/versions" style="color:#e94560">Version comparison (v1.1+) &rarr;</a></div>
<div id="progress"></div>
<div id="procinfo" style="font-size:0.85em; color:#555; margin-bottom:1em;"></div>
<table>
<thead>
<tr>
    <th rowspan="2">Novel</th><th rowspan="2">Author</th><th rowspan="2">Year</th>
    <th colspan="4" class="g">Transport</th>
    <th colspan="4" class="g">Embedding</th>
    <th colspan="4" class="g">No Passages</th>
</tr>
<tr>
    <th>A</th><th>A+HP</th><th>B</th><th>B+HP</th>
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
   <span style="background:#ffe0b2"></span> stalled (crashed)
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
    if (data.stalled > 0) status += `<span style="color:#e65100">&bull; ${data.stalled} stalled</span> `;
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
            } else if (c.status === 'running' || c.status === 'stalled') {
                const ph = c.phase || '?';
                const pct = c.phase3_pct || 0;
                const elapsed = c.elapsed_min || 0;
                const isStalled = c.status === 'stalled';
                const bgColor = isStalled ? 'ffe0b2' : 'cce5ff';
                const fgColor = isStalled ? 'e65100' : '004085';
                const label = isStalled ? `${ph} &#9888;` : ph;
                let inner = `<span style="font-size:0.75em;font-weight:600;color:#${fgColor}">${label}</span>`;
                if (!isStalled && ph === 'Phase 3' && pct > 0) {
                    inner += `<br><span style="display:inline-block;width:90%;height:4px;background:#b8daff;border-radius:2px">` +
                        `<span style="display:inline-block;width:${pct}%;height:4px;background:#004085;border-radius:2px"></span></span>`;
                }
                inner += `<br><span style="font-size:0.7em;color:#${fgColor}">${elapsed}m</span>`;
                const statusLabel = isStalled ? 'stalled' : 'running';
                html += `<td style="background:#${bgColor}" title="${c.name} — ${ph} — ${statusLabel} — ${elapsed} min">${inner}</td>`;
            } else {
                const cls = c.q >= 5 ? 'hi' : c.q >= 2 ? 'mi' : 'lo';
                const cdata = encodeURIComponent(JSON.stringify(c));
                const audio = c.has_audio ? '<span style="font-size:0.7em;color:#27ae60" title="Audio available">&#9835;</span>' : '';
                html += `<td class="d ${cls}" onclick="showRunDetail(event, '${cdata}')">` +
                    `<span class="q">${c.q}</span>${audio}<br>` +
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
function showRunDetail(evt, encoded) {
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

    const qm = c.quote_modes || {};
    const quoteDetail = c.quotes > 0
        ? ` (setup: ${qm.setup||0}, reading: ${qm.reading||0}, commentary: ${qm.commentary||0})`
        : '';
    const qv = c.qv;
    const verif = qv
        ? `<br>Verified: <strong>${qv.verified}/${qv.total}</strong> (${qv.rate}%)`
        : '';
    const metrics = `<div style="margin-top:6px;border-top:1px solid #eee;padding-top:6px">` +
        `Q/seg: <strong>${c.q}</strong> &bull; React/seg: <strong>${c.r}</strong> &bull; ` +
        `Words: <strong>${c.w?.toLocaleString()}</strong><br>` +
        `Quotes: <strong>${c.quotes}</strong>${quoteDetail}${verif}</div>`;

    const started = t.started ? `<div style="color:#888;font-size:0.9em">Started: ${t.started}</div>` : '';

    const div = document.createElement('div');
    div.id = 'pop';
    div.className = 'popover';
    const reportLink = `<a href="/report/${c.name}" target="_blank" style="font-size:0.8em;color:#5b9bd5;text-decoration:none;margin-left:6px">&#9654; report</a>`;
    const audioLink = c.has_audio
        ? ` <a href="/player?run=${c.name}" target="_blank" style="font-size:0.8em;color:#27ae60;text-decoration:none;margin-left:4px">&#9835; audio</a>`
        : '';
    div.innerHTML = `<span class="close" onclick="this.parentElement.remove()">&times;</span>` +
        `<h3>${c.name}${reportLink}${audioLink}</h3>${started}${rows}${metrics}`;
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


SCRIPT_VIEWER_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Script Viewer</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
       margin: 0; background: #1a1a2e; color: #e0e0e0; }
header { background: #16213e; padding: 12px 20px; display: flex; align-items: center; gap: 12px;
         border-bottom: 1px solid #333; position: sticky; top: 0; z-index: 10; }
header h1 { font-size: 1.1em; color: #f0a500; }
header a { color: #88b; text-decoration: none; font-size: 0.85em; }
header a:hover { text-decoration: underline; }
.chips { display: flex; gap: 6px; margin-left: auto; }
.chip { font-size: 0.75em; padding: 2px 8px; border-radius: 10px; border: 1px solid; }
#transcript { max-width: 800px; margin: 0 auto; padding: 20px; }
.segment-header { font-size: 1.1em; font-weight: 600; color: #f0a500; margin: 24px 0 8px;
                   padding: 8px 0; border-bottom: 1px solid #333; }
.turn { padding: 6px 0; border-bottom: 1px solid #222; }
.speaker { font-weight: 600; font-size: 0.85em; margin-bottom: 2px; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }
.text { font-size: 0.9em; line-height: 1.5; color: #ccc; }
.text .quote { color: #c9a0dc; font-style: italic; }
.text .reading { color: #e8c170; font-style: italic; font-weight: 500; }
.meta { font-size: 0.75em; color: #666; margin-top: 16px; padding-top: 8px; border-top: 1px solid #222; }
</style>
</head>
<body>
<header>
    <h1 id="title">Loading...</h1>
    <a href="/tracker">&larr; Back to tracker</a>
    <div class="chips" id="chips"></div>
</header>
<div id="transcript"></div>
<div class="meta" id="meta"></div>
<script>
const COLORS = {
    "Host":"#f0a500","Eleanor Hartley":"#4ecdc4","James Blackstone":"#6c7b95",
    "Caroline Woodcourt":"#c06c84","Edmund Leigh":"#8e7cc3","Daniel Rosen":"#e07c5a",
    "Oliver Trevelyan":"#5cb85c","Dr. Sarah Chen":"#f0a500"
};
const runId = location.pathname.split('/').pop();
fetch(`/api/runs/${runId}/episode`).then(r => r.json()).then(ep => {
    document.getElementById('title').textContent = (ep.title || runId);
    document.title = (ep.title || runId) + ' — Script Viewer';

    // Expert chips
    const speakers = new Set();
    for (const seg of ep.segments) {
        for (const turn of seg.turns) {
            if (turn.speaker !== 'Host') speakers.add(turn.speaker);
        }
    }
    const chips = document.getElementById('chips');
    for (const s of speakers) {
        const c = document.createElement('span');
        c.className = 'chip';
        c.style.borderColor = COLORS[s] || '#666';
        c.style.color = COLORS[s] || '#ccc';
        c.textContent = s;
        chips.appendChild(c);
    }

    // Transcript
    const tx = document.getElementById('transcript');
    let totalWords = 0;
    for (const seg of ep.segments) {
        const h = document.createElement('div');
        h.className = 'segment-header';
        h.textContent = seg.title || seg.segment_type || '';
        tx.appendChild(h);
        for (const turn of seg.turns) {
            const div = document.createElement('div');
            div.className = 'turn';
            const color = COLORS[turn.speaker] || '#999';
            div.innerHTML = `<div class="speaker"><span class="dot" style="background:${color}"></span>` +
                `<span style="color:${color}">${turn.speaker}</span></div>`;
            let textHtml = '';
            for (const u of turn.utterances) {
                const words = u.text.split(/\\s+/).length;
                totalWords += words;
                if (u.quote_mode === 'reading') {
                    textHtml += `<span class="reading">${esc(u.text)}</span> `;
                } else if (u.is_quote) {
                    textHtml += `<span class="quote">${esc(u.text)}</span> `;
                } else {
                    textHtml += esc(u.text) + ' ';
                }
            }
            div.innerHTML += `<div class="text">${textHtml}</div>`;
            tx.appendChild(div);
        }
    }
    document.getElementById('meta').textContent =
        `${ep.segments.length} segments, ${totalWords.toLocaleString()} words`;
}).catch(e => {
    document.getElementById('title').textContent = 'Error loading ' + runId;
    document.getElementById('transcript').textContent = e.message;
});
function esc(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}
</script>
</body>
</html>
"""

VERSIONS_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Version Comparison — Not In Our Time</title>
<script src="/static/nav.js" defer></script>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #0a0f1e; color: #e8e8e8; padding: 2em;
}
h1 { font-size: 1.4em; margin-bottom: 0.3em; color: #e94560; }
.sub { color: #8888aa; font-size: 0.9em; margin-bottom: 1.5em; }
.sub a { color: #6fa8dc; }
.version-tabs { display: flex; gap: 0.5em; margin-bottom: 1.5em; flex-wrap: wrap; }
.vtab {
    padding: 0.4em 1em; border-radius: 16px; cursor: pointer;
    background: #1a2744; border: 1px solid #0f3460; color: #8888aa;
    font-size: 0.85em; font-family: inherit;
}
.vtab.active { background: #e94560; border-color: #e94560; color: white; }
.vtab:hover:not(.active) { border-color: #e94560; color: #e8e8e8; }
.vtab .count { font-size: 0.8em; opacity: 0.7; }
.novel-group { margin-bottom: 2em; }
.novel-group h2 { font-size: 1.1em; color: #d4c5a0; margin-bottom: 0.8em;
    border-bottom: 1px solid #1a2744; padding-bottom: 0.3em; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 1em; }
.card {
    background: #16213e; border: 1px solid #0f3460; border-radius: 8px;
    padding: 1em; font-size: 0.85em; transition: border-color 0.15s;
}
.card:hover { border-color: #e94560; }
.card-header { display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 0.6em; }
.card-panel { color: #e94560; font-weight: 600; font-size: 0.95em; }
.card-condition { color: #8888aa; font-size: 0.85em; }
.card-badges { display: flex; gap: 0.3em; flex-wrap: wrap; margin-bottom: 0.6em; }
.badge {
    display: inline-block; padding: 0.15em 0.5em; border-radius: 10px;
    font-size: 0.75em; font-weight: 500;
}
.badge-script { background: #1b4332; color: #95d5b2; }
.badge-refs { background: #3d2b1f; color: #e8a87c; }
.badge-report { background: #1a2744; color: #6fa8dc; }
.badge-audio { background: #2d1b2e; color: #d4a5d4; }
.card-metrics { color: #8888aa; font-size: 0.8em; margin-bottom: 0.5em; }
.card-reading { margin-top: 0.5em; }
.card-reading h4 { color: #d4c5a0; font-size: 0.85em; margin-bottom: 0.3em; }
.card-reading ul { list-style: none; padding: 0; }
.card-reading li { color: #aaa; font-size: 0.8em; padding: 0.15em 0;
    border-bottom: 1px solid #0f3460; }
.card-reading li:last-child { border-bottom: none; }
.card-links { margin-top: 0.6em; display: flex; gap: 0.5em; }
.card-links a {
    color: #6fa8dc; text-decoration: none; font-size: 0.8em;
    padding: 0.2em 0.6em; border: 1px solid #0f3460; border-radius: 4px;
}
.card-links a:hover { border-color: #6fa8dc; }
.empty { color: #555; font-style: italic; text-align: center; padding: 3em; }
</style>
</head>
<body>
<h1>Version Comparison</h1>
<div class="sub"><a href="/tracker">Back to v1.0 matrix</a></div>

<div style="max-width:800px;margin:0 auto 2em;line-height:1.7;font-size:0.92em;color:#bbb;">
<p>Each podcast episode is generated by a pipeline: passages are selected from the novel,
expert personas shape the discussion, and a host steers the conversation using
pre-interview research. These versions explore what happens when we change
how the experts are described, how they prepare, and what resources they can access.</p>

<p>All versions use the <strong>same passages</strong> (Phases 0&ndash;2 are identical).
What changes is Phases 2.5 and 3 &mdash; how the experts prepare and how the script
is generated.</p>

<details style="margin:1em 0;cursor:pointer;">
<summary style="color:#e94560;font-weight:600;">What changed in each version</summary>
<table style="width:100%;border-collapse:collapse;margin:0.8em 0;font-size:0.88em;">
<tr style="border-bottom:1px solid #1a2744;">
<td style="padding:0.5em;color:#e94560;font-weight:600;white-space:nowrap;vertical-align:top;">v1.0</td>
<td style="padding:0.5em;"><strong>Baseline.</strong> 180 runs across 15 novels.
Expert personas describe perspective and voice. The <a href="/tracker" style="color:#6fa8dc;">experiment matrix</a>
shows these results.</td></tr>
<tr style="border-bottom:1px solid #1a2744;">
<td style="padding:0.5em;color:#e94560;font-weight:600;vertical-align:top;">v1.1</td>
<td style="padding:0.5em;"><strong>Methods-aware personas.</strong> Each expert&rsquo;s description
was rewritten to include their actual disciplinary methods &mdash; what a
computational linguist, historian, or musicologist really does, not just
what they care about.</td></tr>
<tr style="border-bottom:1px solid #1a2744;">
<td style="padding:0.5em;color:#e94560;font-weight:600;vertical-align:top;">v1.2</td>
<td style="padding:0.5em;"><strong>Method decoupling.</strong> v1.1 backfired: experts
performed their methods repetitively (Chen said &ldquo;grammatical&rdquo; 22 times
per episode). Fix: experts keep the full method descriptions for
pre-interview research, but the script generation phase sees a shorter
description focused on perspective, not toolkit. Method markers dropped
60&ndash;88%.</td></tr>
<tr style="border-bottom:1px solid #1a2744;">
<td style="padding:0.5em;color:#e94560;font-weight:600;vertical-align:top;">v1.3</td>
<td style="padding:0.5em;"><strong>Reference tools.</strong> During pre-interviews, experts
can search <a href="https://openalex.org" style="color:#6fa8dc;">OpenAlex</a>
(scholarly works) and <a href="https://en.wikipedia.org" style="color:#6fa8dc;">Wikipedia</a>
(background context). Proposed citations are verified against these APIs.
Each episode gets a reading list with verification rates.</td></tr>
<tr>
<td style="padding:0.5em;color:#e94560;font-weight:600;vertical-align:top;">v1.5</td>
<td style="padding:0.5em;"><strong>Full pipeline.</strong> Search tools now return
actual content (abstracts, article extracts) so experts engage with real
scholarly arguments. Verified references flow into the host&rsquo;s question
planning. A winnowing step selects 3&ndash;5 works a listener could actually
find in a library. The host recommends these in the sign-off.</td></tr>
</table>
</details>

<p>Each card below shows one run. <strong>Badges</strong> indicate what&rsquo;s available:
<span style="color:#95d5b2;">script</span> (generated text),
<span style="color:#e8a87c;">refs</span> (verified reading list),
<span style="color:#6fa8dc;">report</span> (full inspectable report),
<span style="color:#d4a5d4;">audio</span> (Gemini TTS).
Click &ldquo;Report&rdquo; to read the transcript with passage reveals and host preparation details.</p>
</div>

<div class="version-tabs" id="vtabs"></div>
<div id="content"></div>
<script>
let allData = null;
let activeVersion = null;

async function init() {
    const resp = await fetch('/tracker/versions');
    allData = await resp.json();

    const versions = Object.entries(allData.versions).sort();
    if (versions.length === 0) {
        document.getElementById('content').innerHTML =
            '<div class="empty">No versioned runs found.</div>';
        return;
    }

    const tabs = document.getElementById('vtabs');
    const allTab = document.createElement('button');
    allTab.className = 'vtab active';
    allTab.innerHTML = 'All <span class="count">(' + allData.runs.length + ')</span>';
    allTab.onclick = () => selectVersion(null);
    tabs.appendChild(allTab);

    for (const [ver, count] of versions) {
        const btn = document.createElement('button');
        btn.className = 'vtab';
        btn.innerHTML = ver + ' <span class="count">(' + count + ')</span>';
        btn.onclick = () => selectVersion(ver);
        tabs.appendChild(btn);
    }
    selectVersion(null);
}

function selectVersion(ver) {
    activeVersion = ver;
    document.querySelectorAll('.vtab').forEach((t, i) => {
        t.classList.toggle('active', ver === null ? i === 0 : t.textContent.startsWith(ver));
    });
    renderCards();
}

function renderCards() {
    const runs = activeVersion
        ? allData.runs.filter(r => r.version === activeVersion)
        : allData.runs;

    if (runs.length === 0) {
        document.getElementById('content').innerHTML =
            '<div class="empty">No runs for this version.</div>';
        return;
    }

    const byNovel = {};
    for (const r of runs) {
        if (!byNovel[r.novel]) byNovel[r.novel] = [];
        byNovel[r.novel].push(r);
    }

    let html = '';
    for (const [novel, novelRuns] of Object.entries(byNovel).sort()) {
        html += '<div class="novel-group"><h2>' + novel + '</h2><div class="cards">';
        for (const r of novelRuns) { html += renderCard(r); }
        html += '</div></div>';
    }
    document.getElementById('content').innerHTML = html;
}

function renderCard(r) {
    let badges = '';
    if (r.has_episode) badges += '<span class="badge badge-script">script</span>';
    if (r.has_reading_list) badges += '<span class="badge badge-refs">refs</span>';
    if (r.has_report) badges += '<span class="badge badge-report">report</span>';
    if (r.has_audio) badges += '<span class="badge badge-audio">audio</span>';
    if (!r.has_episode && !r.has_reading_list)
        badges += '<span class="badge" style="background:#2a1a1a;color:#e88">in progress</span>';

    let metrics = '';
    if (r.metrics && r.metrics.words)
        metrics = r.metrics.segments + ' seg, ' + r.metrics.turns + ' turns, ' +
            Math.round(r.metrics.words / 1000) + 'k words';

    let reading = '';
    if (r.reading && r.reading.recommended && r.reading.recommended.length > 0) {
        reading = '<div class="card-reading"><h4>Recommended (' +
            r.reading.verified + '/' + r.reading.total +
            ' verified, ' + Math.round(r.reading.rate * 100) + '%)</h4><ul>';
        for (const ref of r.reading.recommended)
            reading += '<li>' + ref + '</li>';
        reading += '</ul></div>';
    } else if (r.reading && r.reading.verified > 0) {
        reading = '<div class="card-reading"><h4>' +
            r.reading.verified + '/' + r.reading.total + ' refs verified</h4></div>';
    }

    let links = '<div class="card-links">';
    if (r.has_report) links += '<a href="/report/' + r.run_id + '">Report</a>';
    if (r.has_audio) links += '<a href="/player?run=' + r.run_id + '">Listen</a>';
    links += '</div>';

    return '<div class="card">' +
        '<div class="card-header">' +
            '<span class="card-panel">' + r.panel + '</span>' +
            '<span class="card-condition">' + r.version + ' &middot; ' +
                r.condition + (r.hostprep ? ' +hp' : '') + '</span>' +
        '</div>' +
        '<div class="card-badges">' + badges + '</div>' +
        (metrics ? '<div class="card-metrics">' + metrics + '</div>' : '') +
        reading + links +
    '</div>';
}

init();
</script>
</body>
</html>
"""
