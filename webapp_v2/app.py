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


@app.get(
    "/reveal/{run_id}/{segment_idx}/{turn_idx}",
    response_class=HTMLResponse,
)
def reveal(request: Request, run_id: str, segment_idx: int, turn_idx: int):
    """Render a turn's passage-reveal fragment for an htmx swap.

    A turn may reference multiple passages (deduped, in occurrence
    order); one panel renders all of them stacked. Single-handle-per-
    turn matches v1's UX — keeps the conversation flow intact.

    Reads passages_contextual when present (LLM context-prefix
    strings); falls back to passages_enriched (BH and Room With a
    View only have that — context is null on those passages).
    """
    run = content_db.get_run_index(run_id)
    if run is None:
        raise HTTPException(404, f"Unknown run {run_id!r}")
    episode = content_db.read_run_artifact(run_id, "phase3_episode")
    if not isinstance(episode, dict):
        raise HTTPException(404, f"No episode for run {run_id!r}")

    segments = episode.get("segments") or []
    if segment_idx < 0 or segment_idx >= len(segments):
        raise HTTPException(404, f"Segment {segment_idx} out of range")
    turns = segments[segment_idx].get("turns") or []
    if turn_idx < 0 or turn_idx >= len(turns):
        raise HTTPException(404, f"Turn {turn_idx} out of range")

    # Deduped, occurrence-ordered passage refs in this turn.
    seen: set[str] = set()
    refs: list[str] = []
    for utt in turns[turn_idx].get("utterances", []):
        ref = utt.get("passage_ref") if isinstance(utt, dict) else None
        if ref and ref not in seen:
            seen.add(ref)
            refs.append(ref)
    if not refs:
        raise HTTPException(404, "Turn has no passage references")

    # Index passages by id once per request.
    passage_list = content_db.read_novel_artifact(run.novel, "passages_contextual")
    if passage_list is None:
        passage_list = content_db.read_novel_artifact(run.novel, "passages_enriched")
    if not isinstance(passage_list, list):
        raise HTTPException(404, f"No passages for novel {run.novel!r}")
    by_id: dict[str, dict] = {
        p["passage_id"]: p
        for p in passage_list
        if isinstance(p, dict) and isinstance(p.get("passage_id"), str)
    }
    panel: list[dict] = []
    for ref in refs:
        p = by_id.get(ref)
        if p is None:
            continue
        panel.append({
            "passage": p,
            "enrichment": p.get("enrichment") if isinstance(p.get("enrichment"), dict) else {},
        })
    if not panel:
        raise HTTPException(404, "No passages found for refs in this turn")

    return templates.TemplateResponse(request, "partials/reveal.html", {
        "panel": panel,
    })
