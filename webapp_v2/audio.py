"""GET /audio/<run_id>/shards.json — synthesises the shard manifest.

Reads shards_index from content.db (no filesystem touch) and embeds the
R2 public URL for each shard's md5. The client fetches mp3 bytes
directly from R2 — the server is never in the audio data path.

No proxy endpoint: there's nothing the server adds between the client
and R2 for shard playback. The CAS local_path optimisation that v1
uses for dev machines isn't worth carrying over for v2 — production
always reads from R2 anyway, and dev cold cache is fine.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cas import store as cas_store  # type: ignore[import]
from webapp_v2 import content as content_db

router = APIRouter()


@router.get("/audio/{run_id}/shards.json")
def shards_manifest(run_id: str) -> dict:
    payload = content_db.read_run_artifact(run_id, "shards_index")
    if not isinstance(payload, dict):
        raise HTTPException(404, f"No shards for run {run_id!r}")
    raw_shards = payload.get("shards") or []
    out: list[dict] = []
    for s in raw_shards:
        if not isinstance(s, dict):
            continue
        md5 = s.get("md5")
        if not md5:
            continue
        out.append({
            "file":          s.get("file"),
            "md5":           md5,
            "kind":          s.get("kind"),
            "segment_index": s.get("segment_index"),
            "turn_index":    s.get("turn_index"),
            "speaker":       s.get("speaker"),
            "role":          s.get("role"),
            "url":           cas_store.url(md5),
        })
    return {
        "schema_version": 1,
        "run_id":         run_id,
        "profile":        payload.get("profile"),
        "shards":         out,
    }
