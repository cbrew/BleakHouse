"""Consumer webapp v2 — FastAPI app.

Phase B: landing + listen pages, server-rendered, no audio JS yet.
The listen page emits the full transcript inline with data attributes
on each turn so Phase C can wire click-to-seek without re-rendering.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from enrichment.axes import NOVEL_BY_ID, PANEL_BY_ID  # type: ignore[import]
from webapp_v2 import content as content_db
from webapp_v2.selection import canonical_run_for, list_canonical_episodes

WEBAPP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEBAPP_DIR / "templates"
STATIC_DIR = WEBAPP_DIR / "static"

app = FastAPI(title="Not In Our Time (v2)")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    episodes = []
    for ep in list_canonical_episodes():
        novel = NOVEL_BY_ID.get(ep.novel)
        panel = PANEL_BY_ID.get(ep.panel)
        if novel is None or panel is None:
            # canonical episode references a novel/panel we don't have
            # metadata for — skip rather than 500. Logged-and-flagged
            # would be better long-term.
            continue
        episodes.append({
            "novel_id": novel.id,
            "novel_title": novel.title,
            "author": novel.author,
            "year": novel.year,
            "panel": ep.panel,
            "panel_display": panel.display,
        })
    episodes.sort(key=lambda e: (e["novel_title"].lower(), e["panel"]))
    return templates.TemplateResponse(
        request, "landing.html", {"episodes": episodes},
    )


@app.get("/listen/{novel_id}/{panel}", response_class=HTMLResponse)
def listen(request: Request, novel_id: str, panel: str):
    ep = canonical_run_for(novel_id, panel)
    if ep is None:
        raise HTTPException(
            404, f"No audio episode for {novel_id} / {panel}",
        )
    novel = NOVEL_BY_ID.get(ep.novel)
    panel_meta = PANEL_BY_ID.get(ep.panel)
    if novel is None or panel_meta is None:
        raise HTTPException(404, "Unknown novel or panel")
    episode = content_db.read_run_artifact(ep.run_id, "phase3_episode")
    if not isinstance(episode, dict):
        raise HTTPException(
            500, f"Missing or malformed phase3_episode for {ep.run_id}",
        )
    return templates.TemplateResponse(request, "listen.html", {
        "novel": novel,
        "panel": panel_meta,
        "run_id": ep.run_id,
        "episode": episode,
    })
