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
from webapp_v2.audio import router as audio_router
from webapp_v2.selection import canonical_run_for, list_canonical_episodes

WEBAPP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEBAPP_DIR / "templates"
STATIC_DIR = WEBAPP_DIR / "static"

app = FastAPI(title="Not In Our Time (v2)")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(audio_router)


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


@app.get("/reveal/{run_id}/{passage_ref}", response_class=HTMLResponse)
def reveal(request: Request, run_id: str, passage_ref: str):
    """Render the passage-reveal fragment for an htmx swap.

    Reads passages_contextual when available (it carries the
    LLM-generated context strings); falls back to passages_enriched
    (BH and Room With a View only have that — context is null).
    """
    run = content_db.get_run_index(run_id)
    if run is None:
        raise HTTPException(404, f"Unknown run {run_id!r}")
    passages = content_db.read_novel_artifact(run.novel, "passages_contextual")
    if passages is None:
        passages = content_db.read_novel_artifact(run.novel, "passages_enriched")
    if not isinstance(passages, list):
        raise HTTPException(404, f"No passages for novel {run.novel!r}")
    passage = next(
        (p for p in passages
         if isinstance(p, dict) and p.get("passage_id") == passage_ref),
        None,
    )
    if passage is None:
        raise HTTPException(
            404, f"Passage {passage_ref!r} not found in {run.novel}",
        )
    enrichment = passage.get("enrichment") or {}
    if not isinstance(enrichment, dict):
        enrichment = {}
    return templates.TemplateResponse(request, "partials/reveal.html", {
        "passage": passage,
        "enrichment": enrichment,
    })
