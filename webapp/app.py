"""Podcast player web application.

Serves audio files and timing manifests for synchronized transcript playback.

Usage:
    uv run uvicorn webapp.app:app --reload --port 8080
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Bleak House Podcast Player")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _discover_runs() -> list[dict]:
    """Find runs that have both audio and a manifest."""
    runs = []
    runs_dir = DATA_DIR / "runs"
    if not runs_dir.exists():
        return runs
    for run_dir in sorted(runs_dir.iterdir()):
        manifest_path = run_dir / "audio" / "manifest.json"
        podcast_path = run_dir / "audio" / "podcast.mp3"
        if manifest_path.exists() and podcast_path.exists():
            with open(manifest_path) as f:
                manifest = json.load(f)
            runs.append({
                "run_id": run_dir.name,
                "title": manifest.get("title", run_dir.name),
                "experts": manifest.get("experts", []),
                "total_duration_ms": manifest.get("total_duration_ms", 0),
            })
    return runs


@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/runs")
async def list_runs():
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
    # Sanitize path components
    if ".." in run_id or ".." in filename:
        raise HTTPException(400, "Invalid path")
    audio_path = DATA_DIR / "runs" / run_id / "audio" / filename
    if not audio_path.exists():
        raise HTTPException(404, f"Audio file not found: {filename}")
    return FileResponse(str(audio_path), media_type="audio/mpeg")
