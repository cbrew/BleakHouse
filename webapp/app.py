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
