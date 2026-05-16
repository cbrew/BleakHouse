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
    # One card per (novel, panel, generator) bucket with audio. When a
    # bucket has only the default Sonnet run, the card renders without
    # an explicit generator label; alternative generators get a chip so
    # listeners know which provider produced the prose.
    DEFAULT_GENERATOR = "anthropic_sonnet_4_6"
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
            "generator": ep.generator,
            "is_default_generator": ep.generator == DEFAULT_GENERATOR,
        })
    # Sort: novel title, then panel, then non-default generators last so
    # the canonical Sonnet card sits next to its alternatives.
    episodes.sort(key=lambda e: (
        e["novel_title"].lower(), e["panel"],
        0 if e["is_default_generator"] else 1,
        e["generator"],
    ))
    return templates.TemplateResponse(
        request, "landing.html", {"episodes": episodes},
    )


def _normalize_references(reading: object) -> tuple[list[dict], dict[str, dict]]:
    """Reconcile the three reading-list schemas (CLAUDE.md):

    - New: top-level `entries` list, each item has tag/title/authors/...
    - Legacy: top-level `verified`/`unverified` lists with raw_text +
      openalex_* fields; no tags.
    - Hybrid: both shapes coexist.

    Returns (references, refs_by_tag). Legacy verified entries are
    flattened into the new shape and deduped by (title, year). Tags
    only exist for new-schema rows; the legacy fall-through is by
    string-match on the raw citation in the template.
    """
    if not isinstance(reading, dict):
        return [], {}
    entries = reading.get("entries")
    if isinstance(entries, list) and entries:
        out = [r for r in entries if isinstance(r, dict)]
    else:
        # Legacy: synthesize entries from verified.
        verified = reading.get("verified") or []
        seen: set[tuple[str, object]] = set()
        out = []
        for r in verified:
            if not isinstance(r, dict):
                continue
            title = r.get("openalex_title") or r.get("raw_text", "")
            year = r.get("openalex_year")
            key = (title, year)
            if not title or key in seen:
                continue
            seen.add(key)
            out.append({
                "tag": "",
                "title": title,
                "authors": r.get("openalex_authors") or [],
                "year": year,
                "publisher": "",
                "description": (
                    r.get("raw_text", "")
                    if r.get("openalex_title") else ""
                ),
                "doi": r.get("openalex_doi") or "",
                # Carry verified URL + resolution fields through from
                # the legacy row (after 7cgk backfill, legacy 'verified'
                # entries also have these). When absent, defaults make
                # the item unresolved which the renderer handles.
                "url": r.get("url") or "",
                "resolution_status": r.get("resolution_status"),
                "resolution_source": r.get("resolution_source"),
                "attempted": r.get("attempted") or [],
                "resolution_reason": r.get("resolution_reason"),
                "raw_url": r.get("raw_url") or r.get("url") or "",
            })
    refs_by_tag = {
        r["tag"]: r for r in out
        if isinstance(r.get("tag"), str) and r["tag"]
    }
    return out, refs_by_tag


def _resolve_episode(
    novel_id: str, panel: str, generator: str | None = None,
):
    """Resolve (novel_id, panel[, generator]) → (Episode, Novel, Panel)
    or raise 404. `generator` is optional; absent → cross-generator
    best ranked. Present → that generator's best ranked run for the
    (novel, panel)."""
    ep = canonical_run_for(novel_id, panel, generator)
    if ep is None:
        msg = f"No audio episode for {novel_id} / {panel}"
        if generator:
            msg += f" / generator={generator}"
        raise HTTPException(404, msg)
    novel = NOVEL_BY_ID.get(ep.novel)
    panel_meta = PANEL_BY_ID.get(ep.panel)
    if novel is None or panel_meta is None:
        raise HTTPException(404, "Unknown novel or panel")
    return ep, novel, panel_meta


def _is_resolved_url(item: dict) -> bool:
    """Does this reading-list/reference entry carry a usable link?

    Post-7cgk backfill, entries set resolution_status='resolved' or
    'unresolved' explicitly. Fallback for older / non-backfilled
    data: URL must be present, http(s), no synthetic 'wiki-fr:'
    prefix.
    """
    status = item.get("resolution_status")
    if status == "resolved":
        return True
    if status in ("unresolved", "no_title"):
        return False
    # status is None — defensive heuristic
    url = (item.get("url") or "").strip()
    if not url or "wiki-fr:" in url:
        return False
    return url.startswith("http://") or url.startswith("https://")


def _split_resolved(items: list) -> tuple[list[dict], list[dict]]:
    """Partition a list of reading-list / reference entries into
    (visible-resolved, unresolved-for-HTML-comment)."""
    resolved: list[dict] = []
    unresolved: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if _is_resolved_url(it):
            resolved.append(it)
        else:
            unresolved.append(it)
    return resolved, unresolved


@app.get("/listen/{novel_id}/{panel}", response_class=HTMLResponse)
def listen(
    request: Request, novel_id: str, panel: str,
    generator: str | None = None,
):
    ep, novel, panel_meta = _resolve_episode(novel_id, panel, generator)
    episode = content_db.read_run_artifact(ep.run_id, "phase3_episode")
    if not isinstance(episode, dict):
        raise HTTPException(
            500, f"Missing or malformed phase3_episode for {ep.run_id}",
        )
    return templates.TemplateResponse(request, "listen.html", {
        "novel": novel,
        "panel": panel_meta,
        "novel_id": novel_id,
        "panel_id": panel,
        "run_id": ep.run_id,
        "generator": ep.generator,
        "episode": episode,
    })


@app.get(
    "/listen/{novel_id}/{panel}/interviews", response_class=HTMLResponse,
)
def tab_interviews(request: Request, novel_id: str, panel: str,
    generator: str | None = None,
):
    ep, novel, panel_meta = _resolve_episode(novel_id, panel, generator)
    interviews = content_db.read_run_artifact(ep.run_id, "phase2_5_interviews")
    briefs = content_db.read_run_artifact(ep.run_id, "phase2_5_host_briefs")
    reading = content_db.read_run_artifact(ep.run_id, "phase2_5_reading_list")
    references, refs_by_tag = _normalize_references(reading)
    # Pull segment titles from phase3_episode so the interviews/briefs
    # arrays (positional) get human-readable headers. Falls back to
    # the segment_name on the brief if the episode is missing.
    episode = content_db.read_run_artifact(ep.run_id, "phase3_episode") or {}
    segment_titles: list[str] = [
        s.get("title", "") for s in episode.get("segments", [])
    ] if isinstance(episode, dict) else []

    interviews_segs = interviews if isinstance(interviews, list) else []
    briefs_segs = briefs if isinstance(briefs, list) else []
    n_segs = max(
        len(interviews_segs),
        len(briefs_segs),
        len(segment_titles),
    )
    rows = []
    for i in range(n_segs):
        title = (
            segment_titles[i] if i < len(segment_titles)
            else (briefs_segs[i].get("segment_name")
                  if i < len(briefs_segs)
                  and isinstance(briefs_segs[i], dict) else f"Segment {i + 1}")
        )
        experts = (
            interviews_segs[i] if i < len(interviews_segs)
            and isinstance(interviews_segs[i], list) else []
        )
        questions = (
            briefs_segs[i].get("questions", [])
            if i < len(briefs_segs) and isinstance(briefs_segs[i], dict)
            else []
        )
        rows.append({
            "title": title,
            "experts": experts,
            "questions": questions,
        })
    references_resolved, references_unresolved = _split_resolved(references)
    return templates.TemplateResponse(request, "interviews.html", {
        "novel": novel,
        "panel": panel_meta,
        "novel_id": novel_id,
        "panel_id": panel,
        "run_id": ep.run_id,
        "rows": rows,
        "references": references,
        "references_resolved": references_resolved,
        "references_unresolved": references_unresolved,
        "refs_by_tag": refs_by_tag,
        "has_interviews": bool(interviews_segs),
        "has_briefs": bool(briefs_segs),
    })


@app.get(
    "/listen/{novel_id}/{panel}/profiles", response_class=HTMLResponse,
)
def tab_profiles(request: Request, novel_id: str, panel: str,
    generator: str | None = None,
):
    _ep, novel, panel_meta = _resolve_episode(novel_id, panel, generator)
    panel_payload = content_db.read_panel_artifact(panel)
    experts = (
        panel_payload.get("experts", [])
        if isinstance(panel_payload, dict) else []
    )
    return templates.TemplateResponse(request, "profiles.html", {
        "novel": novel,
        "panel": panel_meta,
        "novel_id": novel_id,
        "panel_id": panel,
        "experts": experts,
    })


@app.get("/listen/{novel_id}/{panel}/arcs", response_class=HTMLResponse)
def tab_arcs(request: Request, novel_id: str, panel: str,
    generator: str | None = None,
):
    _ep, novel, panel_meta = _resolve_episode(novel_id, panel, generator)
    arcs = content_db.read_novel_artifact(novel.id, "arcs")
    return templates.TemplateResponse(request, "arcs.html", {
        "novel": novel,
        "panel": panel_meta,
        "novel_id": novel_id,
        "panel_id": panel,
        "arcs": arcs if isinstance(arcs, list) else [],
    })


# ── Static pages (Phase F) ───────────────────────────────────────────

_STATIC_PAGES = ("about", "help", "references", "research", "prompts")


@app.get("/scripts", response_class=HTMLResponse)
def scripts_index(request: Request):
    """All-scripts browser. Every run in run_index, audio or not,
    canonical or superseded. Read by anyone clicking through from
    /about ("How It Works"). The front-page audio gate doesn't apply
    here — that's the whole point."""
    conn = content_db._connection()
    rows = list(conn.execute("""
        SELECT run_id, novel, panel, pipeline, length, hostprep, ref_tools,
               generator, has_audio
        FROM run_index
        ORDER BY novel, panel, generator,
                 CASE length WHEN 'short' THEN 0 ELSE 1 END,
                 has_audio DESC, run_id
    """))
    runs = []
    for r in rows:
        nv = NOVEL_BY_ID.get(r["novel"])
        runs.append({
            "run_id": r["run_id"],
            "novel": r["novel"],
            "novel_title": nv.title if nv else r["novel"],
            "novel_author": nv.author if nv else "",
            "panel": r["panel"],
            "pipeline": r["pipeline"],
            "length": r["length"],
            "hostprep": bool(r["hostprep"]),
            "ref_tools": bool(r["ref_tools"]),
            "generator": r["generator"],
            "has_audio": bool(r["has_audio"]),
        })
    return templates.TemplateResponse(request, "scripts.html", {
        "runs": runs,
    })


@app.get("/script/{run_id}", response_class=HTMLResponse)
def script_viewer(request: Request, run_id: str):
    """Transcript-only viewer for a single run. Works for every run in
    run_index regardless of audio status; the audio player is only
    rendered if has_audio=1 (via a 'Listen with audio →' link to the
    /listen page)."""
    if "/" in run_id or ".." in run_id:
        raise HTTPException(400, "Invalid run_id")
    conn = content_db._connection()
    row = conn.execute(
        "SELECT * FROM run_index WHERE run_id = ?", (run_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"Unknown run_id: {run_id!r}")
    episode = content_db.read_run_artifact(run_id, "phase3_episode")
    if not isinstance(episode, dict):
        raise HTTPException(
            500, f"phase3_episode missing for run {run_id!r}",
        )
    novel = NOVEL_BY_ID.get(row["novel"])
    panel_meta = PANEL_BY_ID.get(row["panel"])
    return templates.TemplateResponse(request, "script.html", {
        "run_id": run_id,
        "episode": episode,
        "novel": novel,
        "novel_id": row["novel"],
        "novel_title": novel.title if novel else row["novel"],
        "novel_author": novel.author if novel else "",
        "panel_id": row["panel"],
        "panel_display": panel_meta.display if panel_meta else row["panel"],
        "pipeline": row["pipeline"],
        "length": row["length"],
        "hostprep": bool(row["hostprep"]),
        "ref_tools": bool(row["ref_tools"]),
        "generator": row["generator"],
        "has_audio": bool(row["has_audio"]),
    })


@app.get("/about", response_class=HTMLResponse)
def static_about(request: Request):
    return templates.TemplateResponse(request, "about.html")


@app.get("/help", response_class=HTMLResponse)
def static_help(request: Request):
    return templates.TemplateResponse(request, "help.html")


@app.get("/references", response_class=HTMLResponse)
def static_references(request: Request):
    return templates.TemplateResponse(request, "references.html")


@app.get("/research", response_class=HTMLResponse)
def static_research(request: Request):
    return templates.TemplateResponse(request, "research.html")


@app.get("/prompts", response_class=HTMLResponse)
def static_prompts(request: Request):
    return templates.TemplateResponse(request, "prompts.html")


@app.get("/blog", response_class=HTMLResponse)
def blog_index(request: Request):
    return templates.TemplateResponse(request, "blog_index.html")


@app.get("/blog/{post_id}", response_class=HTMLResponse)
def blog_post(request: Request, post_id: str):
    if ".." in post_id or "/" in post_id:
        raise HTTPException(400, "Invalid path")
    template_name = f"blog_{post_id}.html"
    if not (TEMPLATES_DIR / template_name).exists():
        raise HTTPException(404, f"Blog post not found: {post_id!r}")
    return templates.TemplateResponse(request, template_name)


@app.get(
    "/listen/{novel_id}/{panel}/reading-list", response_class=HTMLResponse,
)
def tab_reading_list(request: Request, novel_id: str, panel: str,
    generator: str | None = None,
):
    ep, novel, panel_meta = _resolve_episode(novel_id, panel, generator)
    reading = content_db.read_run_artifact(ep.run_id, "phase2_5_reading_list")
    recommended = (
        reading.get("recommended", [])
        if isinstance(reading, dict) else []
    )
    recommended_resolved, recommended_unresolved = _split_resolved(recommended)
    return templates.TemplateResponse(request, "reading_list.html", {
        "novel": novel,
        "panel": panel_meta,
        "novel_id": novel_id,
        "panel_id": panel,
        "run_id": ep.run_id,
        "recommended": recommended,
        "recommended_resolved": recommended_resolved,
        "recommended_unresolved": recommended_unresolved,
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
