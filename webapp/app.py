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
import subprocess
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import StreamingResponse

from enrichment import axes

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = Path(__file__).resolve().parent / "static"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def get_git_sha() -> str:
    """Get short git SHA for cache-busting."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=BASE_DIR,
            stderr=subprocess.DEVNULL
        ).decode("ascii").strip()
    except Exception:
        return "unknown"


GIT_SHA = get_git_sha()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["v"] = GIT_SHA

# Audio lives at data/runs/<run>/audio/ — locally this is a symlink
# into the DVC cache; in the container it's a real file bundled from
# the staged demo_data/ tree. There used to be a PODCAST_AUDIO_DIR
# env override pointing at a separate volume; that layout has been
# folded into the canonical path.

app = FastAPI(title="Literary Podcast Player")


class NoCacheNavJs(BaseHTTPMiddleware):
    """Add no-store Cache-Control to nav.js so fly deploys are always fresh."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response = await call_next(request)
        if request.url.path == f"/static/nav.js?v={GIT_SHA}":
            response.headers["Cache-Control"] = "no-store"
        return response


app.add_middleware(NoCacheNavJs)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

POSTER_DIR = BASE_DIR / "poster"


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


def _version_sort_key(version: str) -> tuple[int, ...]:
    nums = [int(part) for part in re.findall(r"\d+", version)]
    return tuple(nums or [0])


# Human-readable labels for the display layer.
_PIPELINE_LABELS: dict[str, str] = {
    "trn": "transport",
    "emb": "embedding",
    "nop": "no passages",
    "rag": "RAG",
}
_PANEL_LABELS: dict[str, str] = {
    "literary": "Panel A (Hartley / Blackstone / Woodcourt)",
    "alternatives": "Panel B (Trevelyan / Leigh / Rosen)",
    "interdisciplinary": "Panel C (Chen / Martinez / Volkov)",
}


def _classify_run(run_dir: Path) -> tuple[str, str, bool, str]:
    """Return (condition, panel, hostprep, generator) from config.json['axes'].

    Post-migration this is a plain lookup — no dir-name string matching.
    Legacy dirs (under _archive/) with no axes block fall back to
    axes.parse_run_dir_name, which rejects anything that doesn't fit the
    canonical shape; in that case all fields are best-effort defaults.
    """
    cfg_path = run_dir / "config.json"
    run_axes = None
    if cfg_path.exists():
        try:
            with open(cfg_path) as f:
                cfg = json.load(f)
            if isinstance(cfg, dict) and isinstance(cfg.get("axes"), dict):
                run_axes = axes.RunAxes.from_dict(cfg["axes"])
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            run_axes = None
    if run_axes is None:
        try:
            run_axes = axes.parse_run_dir_name(run_dir.name)
        except ValueError:
            return "unknown", "unknown", "_hostprep" in run_dir.name, ""

    condition = _PIPELINE_LABELS.get(run_axes.pipeline) or run_axes.pipeline
    panel = _PANEL_LABELS.get(run_axes.panel) or run_axes.panel
    return condition, panel, run_axes.hostprep, run_axes.generator


def _load_json(path: Path) -> dict | list | None:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


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

        # Same audio-presence rule as _available_versions / has_audio.
        has_audio = bool(_available_versions(run_dir.name))
        if not has_audio and not include_scriptonly:
            continue

        # Prefer the per-render manifest under audio/, fall back to the
        # run-level one (older Gemini renders' metadata lives there).
        manifest_path = audio_manifest if audio_manifest.exists() else run_manifest
        if not manifest_path.exists():
            continue

        with open(manifest_path) as f:
            mf = json.load(f)
        title = mf.get("title", run_dir.name)
        novel = title.replace(": A Literary Discussion", "")

        name = run_dir.name
        base_name, version = _parse_version(name)
        condition, panel, hostprep, generator = _classify_run(run_dir)

        run_info = {
            "run_id": name,
            "base_name": base_name,
            "version": version,
            "title": title,
            "novel": novel,
            "condition": condition,
            "panel": panel,
            "hostprep": hostprep,
            "generator": generator,
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
async def landing(request: Request):
    return templates.TemplateResponse(request, "landing.html")


@app.get("/player", response_class=HTMLResponse)
async def player(request: Request):
    return templates.TemplateResponse(request, "player.html")


@app.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    return templates.TemplateResponse(request, "about.html")


@app.get("/blog", response_class=HTMLResponse)
async def blog_page(request: Request):
    return templates.TemplateResponse(request, "blog_index.html")


@app.get("/blog/{post_id}", response_class=HTMLResponse)
async def blog_post(request: Request, post_id: str):
    if ".." in post_id:
        raise HTTPException(400, "Invalid path")
    template_name = f"blog_{post_id}.html"
    if not (TEMPLATES_DIR / template_name).exists():
        raise HTTPException(404, f"Blog post not found: {post_id}")
    return templates.TemplateResponse(request, template_name)


@app.get("/prompts", response_class=HTMLResponse)
async def prompts_page(request: Request):
    return templates.TemplateResponse(request, "prompts.html")


@app.get("/metrics", response_class=HTMLResponse)
async def metrics_page(request: Request):
    return templates.TemplateResponse(request, "metrics.html")


@app.get("/examples", response_class=HTMLResponse)
async def examples_page(request: Request):
    return templates.TemplateResponse(request, "examples.html")


@app.get("/help", response_class=HTMLResponse)
async def help_page(request: Request):
    return templates.TemplateResponse(request, "help.html")


@app.get("/references", response_class=HTMLResponse)
async def references_page(request: Request):
    return templates.TemplateResponse(request, "references.html")


@app.get("/research", response_class=HTMLResponse)
async def research_page(request: Request):
    return templates.TemplateResponse(request, "research.html")


@app.get("/poster", response_class=HTMLResponse)
async def poster_page():
    """Pan/zoom viewer for the 40×30" poster.

    A transparent overlay captures all mouse events so drag-to-pan and
    wheel-to-zoom work across the full viewport, including over the iframe.
    Zoom buttons and a fit-width control are provided in the corner.
    """
    return HTMLResponse("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Poster — Not In Our Time</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0a0e1a; display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
#viewer {
  flex: 1;
  position: relative;
  overflow: hidden;
  background: #111;
  user-select: none;
}
#poster-container { position: absolute; transform-origin: 0 0; }
#poster-frame {
  width: 3840px; height: 2880px;
  border: none; display: block;
  pointer-events: none;
}
#overlay {
  position: absolute; inset: 0;
  cursor: grab; z-index: 10;
}
#overlay.dragging { cursor: grabbing; }
#zoom-controls {
  position: absolute; bottom: 60px; right: 16px;
  z-index: 20; display: flex; flex-direction: column; gap: 4px;
}
.zoom-btn {
  width: 36px; height: 36px;
  background: #1a2744; border: 1px solid #2a3754; border-radius: 6px;
  color: #e8e8e8; font-size: 18px; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: background 0.15s;
  font-family: -apple-system, sans-serif;
}
.zoom-btn:hover { background: #0f3460; }
#zoom-label {
  color: #8888aa; font-size: 0.75em;
  text-align: center; font-family: sans-serif;
}
</style>
</head>
<body>
<div id="viewer">
  <div id="poster-container">
    <iframe id="poster-frame" src="/poster/raw"
            title="MSLD 2026 Conference Poster" scrolling="no"></iframe>
  </div>
  <div id="overlay"></div>
  <div id="zoom-controls">
    <button class="zoom-btn" id="btn-in"  title="Zoom in">+</button>
    <button class="zoom-btn" id="btn-out" title="Zoom out">−</button>
    <button class="zoom-btn" id="btn-fit" title="Fit width"
            style="font-size:11px;">Fit</button>
    <div id="zoom-label">100%</div>
  </div>
</div>
<script src="/static/nav.js?v=2"></script>
<script>
(function () {
  var POSTER_W = 3840, POSTER_H = 2880;
  var viewer    = document.getElementById('viewer');
  var container = document.getElementById('poster-container');
  var overlay   = document.getElementById('overlay');
  var label     = document.getElementById('zoom-label');
  var scale = 1, tx = 0, ty = 0;

  function apply() {
    container.style.transform = 'translate(' + tx + 'px,' + ty + 'px) scale(' + scale + ')';
    label.textContent = Math.round(scale * 100) + '%';
  }

  function fitWidth() {
    scale = viewer.clientWidth / POSTER_W;
    tx = 0; ty = 0;
    apply();
  }

  function zoomAt(factor, cx, cy) {
    var ns = Math.max(0.1, Math.min(4, scale * factor));
    var sf = ns / scale;
    tx = cx - sf * (cx - tx);
    ty = cy - sf * (cy - ty);
    scale = ns;
    apply();
  }

  fitWidth();
  window.addEventListener('resize', fitWidth);

  // Wheel zoom toward cursor
  viewer.addEventListener('wheel', function (e) {
    e.preventDefault();
    var r = viewer.getBoundingClientRect();
    zoomAt(e.deltaY < 0 ? 1.1 : 0.9, e.clientX - r.left, e.clientY - r.top);
  }, { passive: false });

  // Drag to pan
  var dragging = false, ox, oy, stx, sty;
  overlay.addEventListener('mousedown', function (e) {
    dragging = true; ox = e.clientX; oy = e.clientY; stx = tx; sty = ty;
    overlay.classList.add('dragging'); e.preventDefault();
  });
  window.addEventListener('mousemove', function (e) {
    if (!dragging) return;
    tx = stx + e.clientX - ox; ty = sty + e.clientY - oy; apply();
  });
  window.addEventListener('mouseup', function () {
    dragging = false; overlay.classList.remove('dragging');
  });

  // Buttons (zoom toward viewport centre)
  function mid() { return { x: viewer.clientWidth / 2, y: viewer.clientHeight / 2 }; }
  document.getElementById('btn-in').onclick  = function () { var m = mid(); zoomAt(1.25, m.x, m.y); };
  document.getElementById('btn-out').onclick = function () { var m = mid(); zoomAt(0.8,  m.x, m.y); };
  document.getElementById('btn-fit').onclick = fitWidth;
})();
</script>
</body>
</html>""")


@app.get("/poster/raw", response_class=HTMLResponse)
async def poster_raw():
    """Raw poster HTML served inside the /poster viewer iframe (no nav, no zoom)."""
    html = (POSTER_DIR / "poster_print.html").read_text()
    html = html.replace("<head>", '<head>\n<base href="/poster/">', 1)
    return HTMLResponse(html)


app.mount("/poster/", StaticFiles(directory=str(POSTER_DIR)), name="poster-static")


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
    return await RUN_INDEX.get_novels()


@app.get("/api/all-runs")
async def list_all_runs():
    """List ALL runs with scripts, grouped by novel. Includes audio state."""
    return await RUN_INDEX.get_all_runs()


_PROFILE_RE = re.compile(r"^[a-z0-9_]+$")


def _load_run_manifest(run_id: str) -> dict | None:
    """Load the run-level manifest if it exists."""
    path = DATA_DIR / "runs" / run_id / "run_manifest.json"
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            logger.error(f"Failed to load run_manifest for {run_id}")
    return None


def _available_versions(run_id: str) -> list[str]:
    """Return the render versions a user can actually play.

    Single source of truth is run_manifest.json if it exists.
    Otherwise fall back to filesystem discovery.
    """
    manifest = _load_run_manifest(run_id)
    if manifest and "audio_variants" in manifest:
        # Check if the files actually exist before claiming they are available
        available = []
        for v in manifest["audio_variants"]:
            audio_path = BASE_DIR / v["audio_file"]
            if audio_path.exists():
                available.append(v["name"])
        return available

    # Fallback to filesystem convention
    local_dir = DATA_DIR / "runs" / run_id / "audio"
    if not local_dir.exists():
        return []
    files = {p.name for p in local_dir.iterdir()}
    found: set[str] = set()
    if "podcast.mp3" in files:
        found.add("classic")
    for f in files:
        if not (f.startswith("podcast_") and f.endswith(".mp3")):
            continue
        # ... rest of fallback logic ...
        profile = f.removeprefix("podcast_").removesuffix(".mp3")
        if profile.startswith("segment"):
            continue  # segment_NN.mp3 shards, not a render variant
        if f"manifest_{profile}.json" in files:
            found.add(profile)
    return sorted(found)


@app.get("/api/runs/{run_id}/manifest")
async def get_manifest(run_id: str, version: str = "classic"):
    if not _PROFILE_RE.match(version):
        raise HTTPException(400, "Invalid version")
    filename = "manifest.json" if version == "classic" else f"manifest_{version}.json"
    audio_manifest = DATA_DIR / "runs" / run_id / "audio" / filename
    # Only fall back to run-level manifest.json for the default classic version.
    run_manifest = (
        DATA_DIR / "runs" / run_id / "manifest.json"
        if version == "classic"
        else None
    )
    candidates = [audio_manifest]
    if run_manifest is not None:
        candidates.append(run_manifest)
    for candidate in candidates:
        if candidate.exists():
            with open(candidate) as f:
                data = json.load(f)
            data["version"] = version
            data["available_versions"] = _available_versions(run_id)
            return data
    raise HTTPException(404, f"No manifest for run {run_id} version {version}")


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


@app.get("/api/runs/{run_id}/prep")
async def get_prep(run_id: str):
    """Serve combined host-preparation data: interviews, briefs, reading list."""
    if ".." in run_id:
        raise HTTPException(400, "Invalid path")
    run_dir = DATA_DIR / "runs" / run_id
    interviews_path = run_dir / "phase2_5_interviews.json"
    briefs_path = run_dir / "phase2_5_host_briefs.json"
    reading_path = run_dir / "phase2_5_reading_list.json"
    config_path = run_dir / "config.json"
    if not interviews_path.exists():
        raise HTTPException(404, f"No host-prep data for run {run_id}")
    result: dict = {"run_id": run_id}
    with open(interviews_path) as f:
        result["interviews"] = json.load(f)
    if briefs_path.exists():
        with open(briefs_path) as f:
            result["briefs"] = json.load(f)
    if reading_path.exists():
        with open(reading_path) as f:
            result["reading_list"] = json.load(f)
    if config_path.exists():
        with open(config_path) as f:
            cfg = json.load(f)
            result["config"] = {
                "novel": cfg.get("novel", ""),
                "experts": cfg.get("experts", []),
            }
    return result


@app.get("/prep", response_class=HTMLResponse)
async def prep_page(request: Request):
    return templates.TemplateResponse(request, "prep.html")


@app.get("/script/{run_id}", response_class=HTMLResponse)
async def script_viewer(request: Request, run_id: str):
    """Serve the script viewer page for a run."""
    if ".." in run_id:
        raise HTTPException(400, "Invalid path")
    ep_path = DATA_DIR / "runs" / run_id / "phase3_episode.json"
    if not ep_path.exists():
        raise HTTPException(404, f"No episode for run {run_id}")
    return HTMLResponse(SCRIPT_VIEWER_HTML.replace("{{ v }}", GIT_SHA))


AUDIO_VOLUME = Path("/app/audio_volume")
FEEDBACK_FILE = AUDIO_VOLUME / "feedback.jsonl"  # on the persistent volume
PAGEVIEW_FILE = AUDIO_VOLUME / "pageviews.jsonl"
KOKORO_CACHE = AUDIO_VOLUME / "kokoro_cache"

@app.get("/audio/{run_id}/{filename}")
async def serve_audio(run_id: str, filename: str):
    if ".." in run_id or ".." in filename:
        raise HTTPException(400, "Invalid path")

    # Single source of truth: run_manifest.json
    manifest = _load_run_manifest(run_id)
    if manifest and "audio_variants" in manifest:
        # Map requested filename to the path in the manifest
        # (1) Exact match (e.g. manifest_qwen.json)
        for v in manifest["audio_variants"]:
            if v["audio_file"] and Path(v["audio_file"]).name == filename:
                return FileResponse(str(BASE_DIR / v["audio_file"]), media_type="audio/mpeg")
            if v["audio_manifest"] and Path(v["audio_manifest"]).name == filename:
                return FileResponse(str(BASE_DIR / v["audio_manifest"]), media_type="application/json")

        # (2) Alias match for "classic" (player.js asks for manifest.json and podcast.mp3)
        if filename in ("manifest.json", "podcast.mp3"):
            for v in manifest["audio_variants"]:
                if v["name"] == "classic":
                    if filename == "podcast.mp3" and v["audio_file"]:
                        return FileResponse(str(BASE_DIR / v["audio_file"]), media_type="audio/mpeg")
                    if filename == "manifest.json" and v["audio_manifest"]:
                        return FileResponse(str(BASE_DIR / v["audio_manifest"]), media_type="application/json")

    # Fallback to filesystem convention
    audio_path = DATA_DIR / "runs" / run_id / "audio" / filename
    if not audio_path.exists():
        # Fallback for Gemini renders where manifest sits at run-level
        if filename == "manifest.json":
            run_mf = DATA_DIR / "runs" / run_id / "manifest.json"
            if run_mf.exists():
                return FileResponse(str(run_mf), media_type="application/json")
        raise HTTPException(404, f"Audio/manifest file not found: {filename}")

    media_type = "audio/mpeg" if filename.endswith(".mp3") else "application/json"
    return FileResponse(str(audio_path), media_type=media_type)


# ---------------------------------------------------------------------------
# Admin: blob upload to the fly volume DVC cache.
# Bypasses fly ssh entirely; uses the standard HTTPS edge.
# ---------------------------------------------------------------------------

import hashlib  # noqa: E402
import os  # noqa: E402

_ADMIN_TOKEN = os.environ.get("ADMIN_UPLOAD_TOKEN", "")
_HASH_RE = re.compile(r"^[0-9a-f]{32}$")
VOLUME_CACHE = Path("/app/audio_volume/dvc-cache/files/md5")


def _check_admin(request: Request) -> None:
    if not _ADMIN_TOKEN:
        raise HTTPException(503, "admin endpoints disabled (no ADMIN_UPLOAD_TOKEN set)")
    if request.headers.get("x-admin-token") != _ADMIN_TOKEN:
        raise HTTPException(401, "invalid or missing X-Admin-Token")


@app.get("/api/_admin/list-blobs")
async def list_blobs(request: Request):
    _check_admin(request)
    if not VOLUME_CACHE.exists():
        return {"hashes": [], "machine_id": os.environ.get("FLY_MACHINE_ID", "")}
    hashes = []
    for prefix in VOLUME_CACHE.iterdir():
        if not prefix.is_dir() or len(prefix.name) != 2:
            continue
        for blob in prefix.iterdir():
            if blob.is_file() and not blob.name.startswith("."):
                hashes.append(prefix.name + blob.name)
    return {"hashes": sorted(hashes), "machine_id": os.environ.get("FLY_MACHINE_ID", "")}


@app.post("/api/_admin/upload-blob")
async def upload_blob(request: Request, hash: str):
    _check_admin(request)
    if not _HASH_RE.match(hash):
        raise HTTPException(400, "invalid hash format (expect 32 lowercase hex)")
    data = await request.body()
    actual = hashlib.md5(data, usedforsecurity=False).hexdigest()
    if actual != hash:
        raise HTTPException(
            400, f"md5 mismatch: declared {hash}, computed {actual}, size {len(data)}"
        )
    target = VOLUME_CACHE / hash[:2] / hash[2:]
    target.parent.mkdir(parents=True, exist_ok=True)
    # Write atomically: tmp file + rename, so a partial write doesn't
    # leave a corrupt-looking blob the next probe would mistake as done.
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.rename(target)
    return {
        "ok": True,
        "hash": hash,
        "size": len(data),
        "machine_id": os.environ.get("FLY_MACHINE_ID", ""),
    }


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
    (n.id, n.title, n.author, n.year) for n in axes.NOVELS
]

# Matrix axes: pipelines × panels × hostprep.
TRACKER_PIPELINES: tuple[str, ...] = ("trn", "emb", "nop")
TRACKER_PANELS: tuple[str, ...] = ("literary", "alternatives", "interdisciplinary")
TRACKER_PANEL_SHORT: dict[str, str] = {
    "literary": "Lit",
    "alternatives": "Alt",
    "interdisciplinary": "Int",
}
TRACKER_CONDITIONS = [
    (pp, panel, hp)
    for pp in TRACKER_PIPELINES
    for panel in TRACKER_PANELS
    for hp in (False, True)
]


def _tracker_run_name(novel_key: str, pp: str, panel: str, hp: bool) -> str:
    """Canonical dir name via axes.run_dir_name; novel_key may be the full id
    ('bleak_house') or the short axes key ('bh')."""
    nk = axes.NOVEL_BY_ID[novel_key].key if novel_key in axes.NOVEL_BY_ID else novel_key
    return axes.run_dir_name(novel=nk, pipeline=pp, panel=panel, hostprep=hp)


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


@app.get("/tracker", response_class=HTMLResponse)
async def tracker_page(request: Request):
    return HTMLResponse(TRACKER_HTML.replace("{{ v }}", GIT_SHA))


@app.get("/tracker/data")
async def tracker_data():
    return await RUN_INDEX.get_matrix()


def _summarize_run_dir(run_dir: Path) -> dict:
    """Build one cached summary for a run directory."""
    name = run_dir.name
    audio_manifest_path = run_dir / "audio" / "manifest.json"
    run_manifest_path = run_dir / "manifest.json"
    episode_path = run_dir / "phase3_episode.json"
    config_path = run_dir / "config.json"
    reading_list_path = run_dir / "phase2_5_reading_list.json"
    report_path = run_dir / "report.html"

    manifest = (
        _load_json(audio_manifest_path)
        or _load_json(run_manifest_path)
    )
    episode = _load_json(episode_path) if episode_path.exists() else None
    config = _load_json(config_path) if config_path.exists() else None

    title = (manifest or episode or {}).get("title", name)
    novel = title.replace(": A Literary Discussion", "")
    base_name, version = _parse_version(name)
    condition, panel, hostprep, _generator = _classify_run(run_dir)
    # has_audio is true if any playable render exists (Gemini classic
    # OR a profile render like Qwen). Driven by the same discovery
    # rule as _available_versions so the matrix and player agree.
    versions = _available_versions(name)
    has_audio = bool(versions)
    has_host_prep = (run_dir / "phase2_5_host_briefs.json").exists()

    summary = {
        "run_id": name,
        "name": name,
        "title": title,
        "novel": novel,
        "base_name": base_name,
        "version": version,
        "condition": condition,
        "panel": panel,
        "hostprep": hostprep,
        "passage_source": (manifest or {}).get("passage_source", "unknown"),
        "experts": (manifest or {}).get("experts", []),
        "total_duration_ms": (manifest or {}).get("total_duration_ms", 0),
        "has_audio": has_audio,
        "has_host_prep": has_host_prep,
        "audio_state": "gemini" if has_audio else "kokoro",
        "has_episode": episode_path.exists(),
        "has_report": report_path.exists(),
        "has_reading_list": reading_list_path.exists(),
        "reading": {},
        "metrics": {},
    }

    if reading_list_path.exists():
        rl = _load_json(reading_list_path) or {}
        # `recommended` is a list of structured CitationRecord dicts in the
        # new schema, or a list of strings in pre-correct-by-construction
        # files. The webapp's matrix card renderer accepts either.
        summary["reading"] = {
            "verified": rl.get("total_verified", 0),
            "total": rl.get("total_proposed", 0),
            "rate": rl.get("verification_rate", 0),
            "recommended": rl.get("recommended", []),
        }

    if episode_path.exists():
        m = _measure(episode_path)
        timings = _phase_timings(run_dir)
        qv = _load_quote_verification(run_dir)
        summary.update({"status": "done", **(m or {}), "timings": timings, "qv": qv})
        if isinstance(episode, dict):
            total_words = sum(
                len(u.get("text", "").split())
                for seg in episode.get("segments", [])
                for turn in seg.get("turns", [])
                for u in turn.get("utterances", [])
            )
            total_turns = sum(
                len(seg.get("turns", []))
                for seg in episode.get("segments", [])
            )
            summary["metrics"] = {
                "words": total_words,
                "turns": total_turns,
                "segments": len(episode.get("segments", [])),
            }
        return summary

    if not config_path.exists():
        summary["status"] = "missing"
        return summary

    has_p0 = (run_dir / "phase0_segments.json").exists()
    has_p1 = (run_dir / "phase1_assignments.json").exists()
    has_p2 = (run_dir / "phase2_plan.json").exists()
    has_hp = has_host_prep
    expects_hp = bool(config.get("host_prep")) if isinstance(config, dict) else False

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

    started = int(config_path.stat().st_mtime)
    elapsed_min = round((time.time() - started) / 60, 1)
    phase3_pct = 0
    total_segs = 0
    if phase == "Phase 3" and has_p0:
        segs = _load_json(run_dir / "phase0_segments.json")
        if isinstance(segs, list):
            total_segs = len(segs)
        if total_segs > 0:
            phase_start = (run_dir / "phase2_5_host_briefs.json" if has_hp else run_dir / "phase2_plan.json")
            elapsed_in_p3 = time.time() - phase_start.stat().st_mtime
            segs_done_est = min(int(elapsed_in_p3 / 90), total_segs - 1)
            phase3_pct = round(segs_done_est / total_segs * 100)

    summary.update(
        {
            "status": "running",
            "phase": phase,
            "elapsed_min": elapsed_min,
            "started": started,
            "phase3_pct": phase3_pct,
            "total_segs": total_segs,
        }
    )
    return summary


def _dvc_stale_runs() -> dict[str, list[str]]:
    """Return {run_id: [stale_stage_phase, ...]} by parsing `dvc status --json`.

    Each DVC stage name is `<phase>@<run_id>` (see dvc.yaml matrix).
    Empty dict means clean.

    `dvc` is expected on PATH (in the deploy container it's pip-
    installed; locally it's in the uv-managed project venv). Anything
    that prevents it from running cleanly degrades to {}.
    """
    import subprocess
    try:
        proc = subprocess.run(
            ["dvc", "status", "--json"],
            capture_output=True, text=True, timeout=20, cwd=BASE_DIR,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {}
    if proc.returncode != 0 and proc.returncode != 1:
        # dvc status returns 1 when the graph is dirty — that's fine.
        return {}
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    stale: dict[str, list[str]] = {}
    for stage_name in data:
        if "@" not in stage_name:
            continue
        phase, run_id = stage_name.split("@", 1)
        stale.setdefault(run_id, []).append(phase)
    return stale


def _build_tracker_matrix_from_db() -> dict:
    """Build the /tracker/data response from data/experiments.db.

    Replaces the filesystem-walk in _build_cached_snapshot for the
    matrix surface. The DB resolves (novel, panel, pipeline, hostprep,
    generator) to the freshest episode at that coordinate — so retrofit
    runs surface naturally without per-feature dir-name regex.

    Per-cell metrics (q/r/w/timings/quotes) still come from the run's
    phase3_episode.json on disk via _summarize_run_dir; the DB just
    decides which run_dir to read for each cell.

    Response shape matches _build_cached_snapshot()['matrix'] exactly so
    the existing tracker JS needs no changes.
    """
    from webapp.db_views import matrix_rows  # pyright: ignore[reportMissingImports]

    runs_dir = DATA_DIR / "runs"
    stale_by_run = _dvc_stale_runs()
    db_rows = matrix_rows()
    by_axes = {
        (r["novel"], r["panel"], r["pipeline"], int(r["hostprep"]), r["generator"]): r
        for r in db_rows
    }

    cell_cache: dict[str, dict] = {}

    def _cell_for(run_id: str) -> dict:
        cached = cell_cache.get(run_id)
        if cached is not None:
            return cached
        rd = runs_dir / run_id
        summary: dict = (
            _summarize_run_dir(rd) if rd.exists()
            else {"name": run_id, "run_id": run_id, "status": "missing"}
        )
        summary["dvc_stale_phases"] = stale_by_run.get(run_id, [])
        cell_cache[run_id] = summary
        return summary

    tracker_generators = sorted(axes.GENERATORS)
    rows_out: list[dict] = []
    totals_by_generator: dict[str, dict[str, int]] = {
        g: {"total": 0, "done": 0, "running": 0} for g in tracker_generators
    }
    total = 0
    done = 0
    running_count = 0
    p25_times: list[float] = []
    p3_times: list[float] = []

    for novel_key, title, author, year in TRACKER_NOVELS:
        nk_short = axes.NOVEL_BY_ID[novel_key].key if novel_key in axes.NOVEL_BY_ID else novel_key
        cells_by_generator: dict[str, list[dict]] = {}
        for gen in tracker_generators:
            cells: list[dict] = []
            for pp, panel, hp in TRACKER_CONDITIONS:
                key = (nk_short, panel, pp, 1 if hp else 0, gen)
                row = by_axes.get(key)
                if row is None:
                    name = axes.run_dir_name(
                        novel=nk_short, pipeline=pp, panel=panel,
                        hostprep=hp, generator=gen,
                    )
                    cell = {"name": name, "status": "missing"}
                else:
                    cell = _cell_for(row["run_id"])
                totals_by_generator[gen]["total"] += 1
                if cell["status"] == "done":
                    totals_by_generator[gen]["done"] += 1
                elif cell["status"] == "running":
                    totals_by_generator[gen]["running"] += 1
                cells.append(cell)
            cells_by_generator[gen] = cells

        default_cells = cells_by_generator[axes.DEFAULT_GENERATOR]
        total += len(default_cells)
        for c in default_cells:
            if c["status"] == "done":
                done += 1
            elif c["status"] == "running":
                running_count += 1
            timings = c.get("timings") or {}
            if timings.get("p25_min") is not None:
                p25_times.append(timings["p25_min"])
            if timings.get("p3_min") is not None:
                p3_times.append(timings["p3_min"])
        rows_out.append({
            "key": novel_key, "title": title, "author": author, "year": year,
            "cells": default_cells,
            "cells_by_generator": cells_by_generator,
        })

    # Interdisciplinary panel runs — every DB row with panel='interdisciplinary'
    # and a script. The view already keeps the freshest per coordinate, so no
    # extra dedup needed.
    inter_runs: list[dict] = []
    for r in db_rows:
        if r["panel"] != "interdisciplinary" or not r.get("has_episode"):
            continue
        cell = _cell_for(r["run_id"])
        inter_runs.append({
            "run_id": r["run_id"],
            "novel": cell.get("novel", r["novel"]),
            "condition": cell.get("condition", r["pipeline"]),
            "panel": cell.get("panel", r["panel"]),
            "hostprep": bool(r["hostprep"]),
            "has_audio": cell.get("has_audio", False),
            "has_episode": cell.get("has_episode", True),
            "has_report": cell.get("has_report", False),
            "q": cell.get("q", 0),
            "r": cell.get("r", 0),
            "w": cell.get("w", 0),
        })

    # Panel-scripts matrix: 2 novels × 3 panels, hardcoded run_ids. Look each
    # up by label; 'missing' if not in the runs dir.
    panel_scripts_runs = [
        ("Bleak House", "literary", "arc_v01_baseline"),
        ("Bleak House", "interdisciplinary", "interdisciplinary_trn_hostprep_refs"),
        ("Bleak House", "alternative", "arc_v19_all_swapped"),
        ("Hester", "literary", "hest_trn_v01_baseline_hostprep_refs"),
        ("Hester", "interdisciplinary", "hest_interdisciplinary_trn_hostprep_refs"),
        ("Hester", "alternative", "hest_trn_v19_all_swapped_hostprep_refs"),
    ]
    panel_scripts: list[dict] = []
    for novel_label, panel_key, run_id in panel_scripts_runs:
        cell = _cell_for(run_id)
        if cell.get("status") == "missing":
            panel_scripts.append({
                "novel": novel_label, "panel": panel_key, "run_id": run_id,
                "status": "missing",
            })
            continue
        panel_scripts.append({
            "novel": novel_label,
            "panel": panel_key,
            "run_id": run_id,
            "status": cell.get("status", "missing"),
            "phase": cell.get("phase"),
            "q": cell.get("q", 0),
            "r": cell.get("r", 0),
            "w": cell.get("w", 0),
            "has_audio": cell.get("has_audio", False),
            "has_episode": cell.get("has_episode", False),
            "has_report": cell.get("has_report", False),
            "has_reading_list": cell.get("has_reading_list", False),
            "reading": cell.get("reading", {}),
            "name": run_id,
            "condition": cell.get("condition", "transport"),
            "hostprep": cell.get("hostprep", False),
        })

    refreshed_at = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    running_names = [c["name"] for row in rows_out for c in row["cells"] if c["status"] == "running"]

    return {
        "rows": rows_out,
        "total": total,
        "done": done,
        "running": running_count,
        "stalled": 0,
        "running_names": running_names,
        "process": None,
        "histograms": {"p25": sorted(p25_times), "p3": sorted(p3_times)},
        "refreshed_at": refreshed_at,
        "interdisciplinary": inter_runs,
        "panel_scripts": panel_scripts,
        "generators": [
            {"id": g, "display": axes.GENERATOR_BY_ID[g].display}
            for g in tracker_generators
        ],
        "default_generator": axes.DEFAULT_GENERATOR,
        "totals_by_generator": totals_by_generator,
    }


def _build_cached_snapshot() -> dict:
    runs_dir = DATA_DIR / "runs"
    novels: dict[str, list[dict]] = {}
    all_runs: dict[str, list[dict]] = {}
    run_summaries: dict[str, dict] = {}
    p25_times: list[float] = []
    p3_times: list[float] = []
    versions_map: dict[str, list[dict]] = {}
    stale_by_run = _dvc_stale_runs()

    if runs_dir.exists():
        for run_dir in sorted(runs_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            summary = _summarize_run_dir(run_dir)
            summary["dvc_stale_phases"] = stale_by_run.get(summary["run_id"], [])
            run_summaries[summary["run_id"]] = summary

            if summary["title"] and summary["has_audio"]:
                novel_entry = {
                    "run_id": summary["run_id"],
                    "base_name": summary["base_name"],
                    "version": summary["version"],
                    "title": summary["title"],
                    "novel": summary["novel"],
                    "condition": summary["condition"],
                    "panel": summary["panel"],
                    "hostprep": summary["hostprep"],
                    "passage_source": summary["passage_source"],
                    "experts": summary["experts"],
                    "total_duration_ms": summary["total_duration_ms"],
                    "has_audio": summary["has_audio"],
                    "has_host_prep": summary["has_host_prep"],
                }
                novels.setdefault(summary["novel"], []).append(novel_entry)
                all_runs.setdefault(summary["novel"], []).append(
                    {
                        "run_id": summary["run_id"],
                        "title": summary["title"],
                        "novel": summary["novel"],
                        "condition": summary["condition"],
                        "hostprep": summary["hostprep"],
                        "audio_state": summary["audio_state"],
                        "experts": summary["experts"],
                    }
                )

            if summary["version"] != "v1.0":
                versions_map.setdefault(summary["version"], []).append(
                    {
                        "run_id": summary["run_id"],
                        "base_name": summary["base_name"],
                        "version": summary["version"],
                        "novel": summary["novel"],
                        "condition": summary["condition"],
                        "panel": summary["panel"],
                        "hostprep": summary["hostprep"],
                        "has_episode": summary["has_episode"],
                        "has_report": summary["has_report"],
                        "has_reading_list": summary["has_reading_list"],
                        "has_audio": summary["has_audio"],
                        "metrics": summary["metrics"],
                        "reading": summary["reading"],
                    }
                )

            timings = summary.get("timings") or {}
            if timings.get("p25_min") is not None:
                p25_times.append(timings["p25_min"])
            if timings.get("p3_min") is not None:
                p3_times.append(timings["p3_min"])

    # Per-generator matrix: each row holds cells_by_generator[gen_id] so the
    # client can switch dimensions without a refetch. Default generator's
    # cells are duplicated into `row.cells` for back-compat.
    tracker_generators = sorted(axes.GENERATORS)
    rows = []
    totals_by_generator: dict[str, dict[str, int]] = {
        g: {"total": 0, "done": 0, "running": 0} for g in tracker_generators
    }
    # Legacy scalar totals track the default generator.
    total = 0
    done = 0
    running_count = 0
    for novel_key, title, author, year in TRACKER_NOVELS:
        cells_by_generator: dict[str, list[dict]] = {}
        for gen in tracker_generators:
            cells: list[dict] = []
            nk_short = axes.NOVEL_BY_ID[novel_key].key if novel_key in axes.NOVEL_BY_ID else novel_key
            for pp, panel, hp in TRACKER_CONDITIONS:
                rn = axes.run_dir_name(novel=nk_short, pipeline=pp, panel=panel,
                                       hostprep=hp, generator=gen)
                detail = run_summaries.get(rn, {"name": rn, "status": "missing"})
                totals_by_generator[gen]["total"] += 1
                if detail["status"] == "done":
                    totals_by_generator[gen]["done"] += 1
                elif detail["status"] == "running":
                    totals_by_generator[gen]["running"] += 1
                cells.append(detail)
            cells_by_generator[gen] = cells

        default_cells = cells_by_generator[axes.DEFAULT_GENERATOR]
        total += len(default_cells)
        for c in default_cells:
            if c["status"] == "done":
                done += 1
            elif c["status"] == "running":
                running_count += 1
        rows.append({
            "key": novel_key, "title": title, "author": author, "year": year,
            "cells": default_cells,
            "cells_by_generator": cells_by_generator,
        })

    refreshed_at = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    versions = dict(
        sorted(
            ((v, len(runs)) for v, runs in versions_map.items()),
            key=lambda item: _version_sort_key(item[0]),
        )
    )
    version_runs = [
        run
        for _version, runs in sorted(
            versions_map.items(),
            key=lambda item: _version_sort_key(item[0]),
        )
        for run in runs
    ]

    # Interdisciplinary panel runs (not in the main 180-condition grid).
    # Keep only the latest version per (novel, grounding_condition).
    _inter_best: dict[tuple[str, str], dict] = {}
    for rid, s in sorted(run_summaries.items()):
        if "interdisciplinary" not in rid or not s.get("has_episode"):
            continue
        novel = s.get("novel", "")
        cond = s.get("condition", "")
        key = (novel, cond)
        entry = {
            "run_id": rid,
            "novel": novel,
            "condition": cond,
            "panel": s.get("panel", ""),
            "hostprep": s.get("hostprep", False),
            "has_audio": s.get("has_audio", False),
            "has_episode": s.get("has_episode", False),
            "has_report": s.get("has_report", False),
            "q": s.get("q", 0),
            "r": s.get("r", 0),
            "w": s.get("w", 0),
        }
        prev = _inter_best.get(key)
        # Prefer runs with audio; among those, prefer latest version
        prev_audio = prev.get("has_audio", False) if prev else False
        has_audio = s.get("has_audio", False)
        if prev is None or (has_audio and not prev_audio) or (
            has_audio == prev_audio
            and _version_sort_key(s.get("version", "v1.0")) > _version_sort_key(prev.get("_ver", "v1.0"))
        ):
            entry["_ver"] = s.get("version", "v1.0")
            _inter_best[key] = entry
    inter_runs = [v for v in _inter_best.values()]
    for r in inter_runs:
        r.pop("_ver", None)

    # Panel-scripts matrix: 2 novels × 3 panels, all with reference-tools.
    PANEL_SCRIPTS_RUNS = [
        ("Bleak House", "literary", "arc_v01_baseline"),
        ("Bleak House", "interdisciplinary", "interdisciplinary_trn_hostprep_refs"),
        ("Bleak House", "alternative", "arc_v19_all_swapped"),
        ("Hester", "literary", "hest_trn_v01_baseline_hostprep_refs"),
        ("Hester", "interdisciplinary", "hest_interdisciplinary_trn_hostprep_refs"),
        ("Hester", "alternative", "hest_trn_v19_all_swapped_hostprep_refs"),
    ]
    panel_scripts: list[dict] = []
    for novel_label, panel_key, run_id in PANEL_SCRIPTS_RUNS:
        s = run_summaries.get(run_id)
        if s is None:
            panel_scripts.append({
                "novel": novel_label, "panel": panel_key, "run_id": run_id,
                "status": "missing",
            })
            continue
        panel_scripts.append({
            "novel": novel_label,
            "panel": panel_key,
            "run_id": run_id,
            "status": s.get("status", "missing"),
            "phase": s.get("phase"),
            "q": s.get("q", 0),
            "r": s.get("r", 0),
            "w": s.get("w", 0),
            "has_audio": s.get("has_audio", False),
            "has_episode": s.get("has_episode", False),
            "has_report": s.get("has_report", False),
            "has_reading_list": s.get("has_reading_list", False),
            "reading": s.get("reading", {}),
            "name": run_id,
            "condition": s.get("condition", "transport"),
            "hostprep": s.get("hostprep", False),
        })

    return {
        "novels": novels,
        "all_runs": all_runs,
        "matrix": {
            "rows": rows,
            "total": total,
            "done": done,
            "running": running_count,
            "stalled": 0,
            "running_names": [c["name"] for row in rows for c in row["cells"] if c["status"] == "running"],
            "process": None,
            "histograms": {"p25": sorted(p25_times), "p3": sorted(p3_times)},
            "refreshed_at": refreshed_at,
            "interdisciplinary": inter_runs,
            "panel_scripts": panel_scripts,
            "generators": [
                {"id": g, "display": axes.GENERATOR_BY_ID[g].display}
                for g in tracker_generators
            ],
            "default_generator": axes.DEFAULT_GENERATOR,
            "totals_by_generator": totals_by_generator,
        },
        "versions": {"versions": versions, "runs": version_runs},
        "refreshed_at": refreshed_at,
    }


class RunIndexCache:
    def __init__(self, ttl_seconds: float = 30.0):
        self.ttl_seconds = ttl_seconds
        self._snapshot: dict | None = None
        self._last_refresh = 0.0
        self._schedule_lock = asyncio.Lock()
        self._refresh_task: asyncio.Task | None = None
        # Separate cache for the DB-backed tracker matrix (BleakHouse-17j).
        # Filesystem-snapshot still powers /api/runs, /api/novels, and
        # /tracker/versions until BleakHouse-q4e migrates them.
        self._matrix: dict | None = None
        self._matrix_last_refresh = 0.0
        self._matrix_lock = asyncio.Lock()
        self._matrix_task: asyncio.Task | None = None

    def _is_stale(self) -> bool:
        return (time.monotonic() - self._last_refresh) >= self.ttl_seconds

    def _matrix_is_stale(self) -> bool:
        return (time.monotonic() - self._matrix_last_refresh) >= self.ttl_seconds

    async def _run_refresh(self) -> None:
        try:
            snapshot = await asyncio.to_thread(_build_cached_snapshot)
            self._snapshot = snapshot
            self._last_refresh = time.monotonic()
        except Exception:
            logger.exception("Run index refresh failed")
        finally:
            self._refresh_task = None

    async def _ensure_refresh_started(self) -> asyncio.Task:
        async with self._schedule_lock:
            if self._refresh_task is None or self._refresh_task.done():
                self._refresh_task = asyncio.create_task(self._run_refresh())
            return self._refresh_task

    async def _run_matrix_refresh(self) -> None:
        try:
            matrix = await asyncio.to_thread(_build_tracker_matrix_from_db)
            self._matrix = matrix
            self._matrix_last_refresh = time.monotonic()
        except Exception:
            logger.exception("Tracker matrix refresh failed")
        finally:
            self._matrix_task = None

    async def _ensure_matrix_refresh_started(self) -> asyncio.Task:
        async with self._matrix_lock:
            if self._matrix_task is None or self._matrix_task.done():
                self._matrix_task = asyncio.create_task(self._run_matrix_refresh())
            return self._matrix_task

    async def get_snapshot(self) -> dict:
        if self._snapshot is None:
            task = await self._ensure_refresh_started()
            await task
        elif self._is_stale():
            await self._ensure_refresh_started()
        return self._snapshot or {
            "novels": {},
            "all_runs": {},
            "matrix": {
                "rows": [],
                "total": 0,
                "done": 0,
                "running": 0,
                "stalled": 0,
                "running_names": [],
                "process": None,
                "histograms": {"p25": [], "p3": []},
                "refreshed_at": "",
            },
            "versions": {"versions": {}, "runs": []},
            "refreshed_at": "",
        }

    async def prime(self) -> None:
        await self._ensure_refresh_started()
        await self._ensure_matrix_refresh_started()

    async def get_novels(self) -> dict[str, list[dict]]:
        return (await self.get_snapshot())["novels"]

    async def get_all_runs(self) -> dict[str, list[dict]]:
        return (await self.get_snapshot())["all_runs"]

    async def get_matrix(self) -> dict:
        if self._matrix is None:
            task = await self._ensure_matrix_refresh_started()
            await task
        elif self._matrix_is_stale():
            await self._ensure_matrix_refresh_started()
        return self._matrix or {
            "rows": [], "total": 0, "done": 0, "running": 0, "stalled": 0,
            "running_names": [], "process": None,
            "histograms": {"p25": [], "p3": []},
            "refreshed_at": "",
            "interdisciplinary": [], "panel_scripts": [],
            "generators": [], "default_generator": axes.DEFAULT_GENERATOR,
            "totals_by_generator": {},
        }

    async def get_versions(self) -> dict:
        return (await self.get_snapshot())["versions"]


RUN_INDEX = RunIndexCache(ttl_seconds=30.0)


@app.on_event("startup")
async def warm_run_index() -> None:
    await RUN_INDEX.prime()


@app.get("/tracker/versions")
async def tracker_versions_data():
    return await RUN_INDEX.get_versions()


@app.get("/script-versions", response_class=HTMLResponse)
async def versions_page(request: Request):
    return HTMLResponse(VERSIONS_HTML.replace("{{ v }}", GIT_SHA))


@app.get("/tracker/stream")
async def tracker_stream():
    async def event_generator():
        prev = ""
        while True:
            data = await RUN_INDEX.get_matrix()
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
<script src="/static/nav.js?v={{ v }}" defer></script>
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
<div class="sub">15 novels &times; 3 pipelines &times; 3 panels &times; 2 host-prep = 270 cells per generator
 &mdash; <span id="status">connecting...</span></div>
<div style="color:#8888aa;font-size:0.85em;margin-bottom:0.6em">Click any cell to see details and links. Columns: Lit/Alt/Int = literary, alternatives, interdisciplinary panels; HP = with host preparation. <a href="/help" style="color:#6fa8dc">More help</a> &middot; <a href="/script-versions" style="color:#e94560">Version comparison (v1.1+) &rarr;</a></div>
<div id="gen-select-container" style="margin-bottom:0.8em;font-size:0.9em;">
  <label for="gen-select" style="margin-right:6px;">Generator:</label>
  <select id="gen-select" style="font-size:1em;padding:2px 6px;"></select>
  <span id="gen-totals" style="margin-left:10px;color:#666;"></span>
</div>
<div id="progress"></div>
<div id="procinfo" style="font-size:0.85em; color:#555; margin-bottom:1em;"></div>
<table>
<thead>
<tr>
    <th rowspan="2">Novel</th><th rowspan="2">Author</th><th rowspan="2">Year</th>
    <th colspan="6" class="g">Transport</th>
    <th colspan="6" class="g">Embedding</th>
    <th colspan="6" class="g">No Passages</th>
</tr>
<tr>
    <th>Lit</th><th>Lit+HP</th><th>Alt</th><th>Alt+HP</th><th>Int</th><th>Int+HP</th>
    <th>Lit</th><th>Lit+HP</th><th>Alt</th><th>Alt+HP</th><th>Int</th><th>Int+HP</th>
    <th>Lit</th><th>Lit+HP</th><th>Alt</th><th>Alt+HP</th><th>Int</th><th>Int+HP</th>
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
<h2 style="margin-top:1.5em;font-size:1.1em;">Interdisciplinary Panel <span style="font-weight:normal;font-size:0.85em;color:#666;">(Chen / Martinez / Volkov)</span></h2>
<div style="color:#8888aa;font-size:0.85em;margin-bottom:0.5em;">Three non-literary experts discuss the same novels. Click any cell for details.</div>
<table id="inter-table" style="width:auto;">
<thead>
<tr><th>Novel</th><th>Transport</th><th>Embedding</th><th>No Passages</th></tr>
</thead>
<tbody id="inter-tbody"></tbody>
</table>
<h2 style="margin-top:1.5em;font-size:1.1em;">Panel Scripts with Reading Lists <span style="font-weight:normal;font-size:0.85em;color:#666;">reference-tools enabled</span></h2>
<div style="color:#8888aa;font-size:0.85em;margin-bottom:0.5em;">Three expert panels discuss two novels. Each run includes verified scholarly references. Click any cell for details.</div>
<table id="panel-scripts-table" style="width:auto;">
<thead>
<tr><th>Novel</th><th>Literary<br><span style="font-weight:normal;font-size:0.8em;">Hartley / Blackstone / Woodcourt</span></th><th>Interdisciplinary<br><span style="font-weight:normal;font-size:0.8em;">Chen / Martinez / Volkov</span></th><th>Alternative<br><span style="font-weight:normal;font-size:0.8em;">Trevelyan / Leigh / Rosen</span></th></tr>
</thead>
<tbody id="panel-scripts-tbody"></tbody>
</table>
<script>
let _lastData = null;
let _currentGen = null;

function render(data) {
    _lastData = data;
    const gens = data.generators || [];
    if (gens.length > 0) {
        const sel = document.getElementById('gen-select');
        if (sel && sel.options.length === 0) {
            sel.innerHTML = gens.map(g =>
                `<option value="${g.id}">${g.display}</option>`
            ).join('');
            sel.value = data.default_generator || gens[0].id;
            sel.addEventListener('change', () => {
                _currentGen = sel.value;
                _renderWithGenerator(_lastData, _currentGen);
            });
            _currentGen = sel.value;
        }
    }
    _renderWithGenerator(data, _currentGen || data.default_generator);
}

function _renderWithGenerator(data, gen) {
    const totals = (data.totals_by_generator || {})[gen] ||
                   { total: data.total, done: data.done, running: data.running };
    const pct = totals.total ? Math.round(totals.done * 100 / totals.total) : 0;
    const remaining = totals.total - totals.done;
    let status = `<strong>${totals.done}/${totals.total}</strong> (${pct}%) &mdash; ${remaining} remaining `;
    if (totals.running > 0) status += `<span style="color:#004085">&bull; ${totals.running} in progress</span> `;
    const barW = totals.total ? Math.round(totals.done * 300 / totals.total) : 0;
    status += `<br><span class="bar-bg"><span class="bar" style="width:${barW}px"></span></span>`;
    document.getElementById('progress').innerHTML = status;
    // Per-generator totals readout next to dropdown.
    const gtSpan = document.getElementById('gen-totals');
    if (gtSpan) gtSpan.textContent = `${totals.done}/${totals.total} runs for this generator`;
    // Process info
    let pinfo = '';
    if (data.running > 0) {
        pinfo = '&#9654; Latest filesystem snapshot shows ' + data.running + ' run(s) in progress';
        if (data.refreshed_at) pinfo += ` &mdash; refreshed ${data.refreshed_at}`;
    } else if (data.done < data.total) {
        pinfo = '&#9744; No active runs in the latest snapshot.';
        if (data.refreshed_at) pinfo += ` Refreshed ${data.refreshed_at}.`;
        pinfo += ' Use <code>uv run python -m enrichment.run_full_matrix --only-missing</code> to continue.';
    } else {
        pinfo = '&#9989; All ' + data.total + ' runs complete!';
        if (data.refreshed_at) pinfo += ` Snapshot refreshed ${data.refreshed_at}.`;
    }
    document.getElementById('procinfo').innerHTML = pinfo;
    let html = '';
    for (const row of data.rows) {
        html += `<tr><td class="n">${row.title}</td><td class="a">${row.author}</td><td class="y">${row.year}</td>`;
        const cells = (row.cells_by_generator && row.cells_by_generator[gen])
            ? row.cells_by_generator[gen]
            : row.cells;
        for (const c of cells) {
            if (c.status === 'missing') {
                html += '<td class="m">&mdash;</td>';
            } else if (c.status === 'running') {
                const ph = c.phase || '?';
                const pct = c.phase3_pct || 0;
                const elapsed = c.elapsed_min || 0;
                let inner = `<span style="font-size:0.75em;font-weight:600;color:#004085">${ph}</span>`;
                if (ph === 'Phase 3' && pct > 0) {
                    inner += `<br><span style="display:inline-block;width:90%;height:4px;background:#b8daff;border-radius:2px">` +
                        `<span style="display:inline-block;width:${pct}%;height:4px;background:#004085;border-radius:2px"></span></span>`;
                }
                inner += `<br><span style="font-size:0.7em;color:#004085">${elapsed}m</span>`;
                html += `<td style="background:#cce5ff" title="${c.name} — ${ph} — running — ${elapsed} min">${inner}</td>`;
            } else {
                const cls = c.q >= 5 ? 'hi' : c.q >= 2 ? 'mi' : 'lo';
                const cdata = encodeURIComponent(JSON.stringify(c));
                const audio = c.has_audio ? '<span style="font-size:0.7em;color:#27ae60" title="Audio available">&#9835;</span>' : '';
                const stalePhases = c.dvc_stale_phases || [];
                const stale = stalePhases.length > 0
                    ? `<span style="font-size:0.7em;color:#c0392b" title="DVC stale: ${stalePhases.join(', ')}">&#9888;</span>`
                    : '';
                html += `<td class="d ${cls}" onclick="showRunDetail(event, '${cdata}')">` +
                    `<span class="q">${c.q}</span>${audio}${stale}<br>` +
                    `<span class="r">${c.r}</span><br>` +
                    `<span class="w">${Math.round(c.w/1000)}k</span></td>`;
            }
        }
        html += '</tr>';
    }
    document.getElementById('tbody').innerHTML = html;
    // Histograms
    if (data.histograms) renderHistograms(data.histograms);
    // Interdisciplinary panel
    if (data.interdisciplinary) renderInterdisciplinary(data.interdisciplinary);
    // Panel scripts with reading lists
    if (data.panel_scripts) renderPanelScripts(data.panel_scripts);
}
function renderInterdisciplinary(runs) {
    if (!runs || runs.length === 0) {
        document.getElementById('inter-table').style.display = 'none';
        return;
    }
    // Group by novel, then by grounding condition
    const byNovel = {};
    for (const r of runs) {
        const key = r.novel || 'Unknown';
        if (!byNovel[key]) byNovel[key] = {};
        let cond = 'transport';
        if (r.run_id.includes('_nop_') || r.run_id.startsWith('interdisciplinary_nop')) cond = 'no passages';
        else if (r.run_id.includes('_emb_') || r.run_id.startsWith('interdisciplinary_emb')) cond = 'embedding';
        byNovel[key][cond] = r;
    }
    function interCell(r) {
        if (!r) return '<td class="m">&mdash;</td>';
        const cls = r.q >= 5 ? 'hi' : r.q >= 2 ? 'mi' : 'lo';
        const audio = r.has_audio ? '<span style="font-size:0.7em;color:#27ae60" title="Audio available">&#9835;</span>' : '';
        const cdata = encodeURIComponent(JSON.stringify(r));
        return `<td class="d ${cls}" onclick="showRunDetail(event, '${cdata}')">` +
            `<span class="q">${r.q}</span>${audio}<br>` +
            `<span class="r">${r.r}</span><br>` +
            `<span class="w">${Math.round(r.w/1000)}k</span></td>`;
    }
    let html = '';
    for (const [novel, conds] of Object.entries(byNovel).sort()) {
        html += '<tr><td class="n">' + novel + '</td>';
        html += interCell(conds['transport']);
        html += interCell(conds['embedding']);
        html += interCell(conds['no passages']);
        html += '</tr>';
    }
    document.getElementById('inter-tbody').innerHTML = html;
}
function renderPanelScripts(runs) {
    if (!runs || runs.length === 0) {
        document.getElementById('panel-scripts-table').style.display = 'none';
        return;
    }
    const byNovel = {};
    for (const r of runs) {
        const key = r.novel || 'Unknown';
        if (!byNovel[key]) byNovel[key] = {};
        byNovel[key][r.panel] = r;
    }
    function psCell(r) {
        if (!r || r.status === 'missing') return '<td class="m">&mdash;</td>';
        if (r.status === 'running') {
            const ph = r.phase || '?';
            return `<td style="background:#cce5ff" title="${r.run_id} — ${ph}"><span style="font-size:0.75em;font-weight:600;color:#004085">${ph}</span></td>`;
        }
        const cls = r.q >= 5 ? 'hi' : r.q >= 2 ? 'mi' : 'lo';
        const refs = r.has_reading_list ? '<span style="font-size:0.7em;color:#8e44ad" title="Reading list available">&#128218;</span>' : '';
        const cdata = encodeURIComponent(JSON.stringify(r));
        return `<td class="d ${cls}" onclick="showRunDetail(event, '${cdata}')">` +
            `<span class="q">${r.q}</span>${refs}<br>` +
            `<span class="r">${r.r}</span><br>` +
            `<span class="w">${Math.round(r.w/1000)}k</span></td>`;
    }
    let html = '';
    for (const [novel, panels] of Object.entries(byNovel).sort()) {
        html += '<tr><td class="n">' + novel + '</td>';
        html += psCell(panels['literary']);
        html += psCell(panels['interdisciplinary']);
        html += psCell(panels['alternative']);
        html += '</tr>';
    }
    document.getElementById('panel-scripts-tbody').innerHTML = html;
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
<script src="/static/nav.js?v={{ v }}" defer></script>
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

function escapeHTML(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function versionSortKey(version) {
    const nums = String(version).match(/[0-9]+/g);
    return (nums || ['0']).map(n => parseInt(n, 10));
}

function compareVersions(a, b) {
    const ak = versionSortKey(a);
    const bk = versionSortKey(b);
    const len = Math.max(ak.length, bk.length);
    for (let i = 0; i < len; i++) {
        const av = ak[i] || 0;
        const bv = bk[i] || 0;
        if (av !== bv) return av - bv;
    }
    return 0;
}

async function init() {
    const resp = await fetch('/tracker/versions');
    allData = await resp.json();

    const versions = Object.entries(allData.versions).sort((a, b) => compareVersions(a[0], b[0]));
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
    for (const [novel, novelRuns] of Object.entries(byNovel).sort((a, b) => a[0].localeCompare(b[0]))) {
        html += '<div class="novel-group"><h2>' + escapeHTML(novel) + '</h2><div class="cards">';
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
            r.reading.verified + ' refs)</h4><ul>';
        for (const ref of r.reading.recommended) {
            const authors = (ref.authors && ref.authors.length)
                ? escapeHTML(ref.authors.slice(0, 3).join(', '))
                : '—';
            const year = ref.year ? ' (' + ref.year + ')' : '';
            const title = ref.url
                ? '<a href="' + escapeHTML(ref.url) + '" target="_blank" rel="noopener">' + escapeHTML(ref.title) + '</a>'
                : escapeHTML(ref.title);
            reading += '<li>' + authors + '. ' + title + year + '</li>';
        }
        reading += '</ul></div>';
    } else if (r.reading && r.reading.verified > 0) {
        reading = '<div class="card-reading"><h4>' +
            r.reading.verified + ' refs</h4></div>';
    }

    let links = '<div class="card-links">';
    if (r.has_report) links += '<a href="/report/' + encodeURIComponent(r.run_id) + '">Report</a>';
    if (r.has_audio) links += '<a href="/player?run=' + encodeURIComponent(r.run_id) + '">Listen</a>';
    links += '</div>';

    return '<div class="card">' +
        '<div class="card-header">' +
            '<span class="card-panel">' + escapeHTML(r.panel) + '</span>' +
            '<span class="card-condition">' + escapeHTML(r.version) + ' &middot; ' +
                escapeHTML(r.condition + (r.hostprep ? ' +hp' : '')) + '</span>' +
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
