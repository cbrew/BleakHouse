"""Selection logic for the consumer-facing site.

`best_episodes_for_consumer()` walks the experiments DB and returns one row
per (novel, panel) pair that has rendered audio. Within each (novel, panel)
bucket the rules pick the most listener-friendly run:

  pipeline:  trn/transport > emb > nop  (transport-based selection first)
  hostprep:  yes > no                   (host-prep adds question density)
  ref_tools: yes > no                   (verified scholarly references)
  recency:   newest script_version wins ties

Pairs with zero rendered audio are dropped entirely.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from enrichment import axes  # pyright: ignore[reportMissingImports]
from webapp.db import db_conn  # pyright: ignore[reportMissingImports]

logger = logging.getLogger(__name__)

# Pipeline preference ordering. trn and transport are aliases for the same
# min-cost-flow pipeline; both rank top. rag is a secondary embedding-based
# variant; lump with emb. Lower number = more preferred.
_PIPELINE_RANK: dict[str, int] = {
    "trn": 0,
    "transport": 0,
    "emb": 1,
    "rag": 1,
    "nop": 2,
}

# Visual ordering for cards within a novel. Used by the API/template, not
# selection (selection is per (novel, panel), so every panel that survives
# becomes its own card).
_PANEL_ORDER: dict[str, int] = {
    "literary": 0,
    "alternatives": 1,
    "interdisciplinary": 2,
}

# `episode.novel` is mostly the short key ("bh", "dd") but sometimes the
# id form ("oliver_twist", "mrs_dalloway"). Build a lookup that accepts either.
_NOVEL_BY_ANY: dict[str, axes.Novel] = {
    **{n.key: n for n in axes.NOVELS},
    **{n.id: n for n in axes.NOVELS},
}


def _rank_key(row: dict[str, Any]) -> tuple[int, int, int, float]:
    """Sort key: smaller is better. Pipeline > hostprep > ref_tools > newer."""
    return (
        _PIPELINE_RANK.get(row["pipeline"], 9),
        0 if row["hostprep"] else 1,
        0 if row["ref_tools"] else 1,
        -float(row["script_created"] or 0.0),
    )


def _load_teaser(runs_root: Path, run_id: str) -> str | None:
    """Read phase3_teaser.json's `teaser` field, or fall back to the first
    segment name from phase0_segments.json. Returns None if neither exists."""
    teaser_path = runs_root / run_id / "phase3_teaser.json"
    if teaser_path.exists():
        try:
            with open(teaser_path) as f:
                data = json.load(f)
            text = data.get("teaser")
            if text:
                return str(text).strip()
        except (OSError, json.JSONDecodeError) as e:
            logger.debug("teaser load failed for %s: %s", run_id, e)
    segs_path = runs_root / run_id / "phase0_segments.json"
    if segs_path.exists():
        try:
            with open(segs_path) as f:
                data = json.load(f)
            if isinstance(data, list) and data and isinstance(data[0], dict):
                name = data[0].get("name")
                if name:
                    return str(name).strip()
        except (OSError, json.JSONDecodeError) as e:
            logger.debug("segments load failed for %s: %s", run_id, e)
    return None


_QUERY = """
SELECT
    e.id              AS episode_id,
    e.novel           AS novel,
    e.panel           AS panel,
    e.pipeline        AS pipeline,
    e.hostprep        AS hostprep,
    e.ref_tools       AS ref_tools,
    e.label           AS run_id,
    s.id              AS script_id,
    s.n_segments      AS n_segments,
    s.n_turns         AS n_turns,
    s.created_at      AS script_created,
    a.duration_s      AS duration_s
FROM episode e
JOIN script_version s   ON s.episode_id = e.id
JOIN audio_artifact a   ON a.script_version_id = s.id
WHERE e.panel IN ('literary', 'alternatives', 'interdisciplinary')
"""


def best_episodes_for_consumer(data_dir: Path | None = None) -> list[dict[str, Any]]:
    """Return one row per (novel, panel) pair that has rendered audio.

    Each row carries the metadata the consumer landing card needs:
    novel (key), novel_title, author, year, panel, run_id, pipeline,
    hostprep, ref_tools, segments, duration_seconds, teaser. Results are
    sorted by (novel_title, panel-visual-order).
    """
    if data_dir is None:
        from webapp.app import DATA_DIR  # pyright: ignore[reportMissingImports]
        data_dir = DATA_DIR
    runs_root = data_dir / "runs"

    with db_conn() as conn:
        rows = [dict(r) for r in conn.execute(_QUERY)]

    # Bucket by (novel, panel) and keep the best run in each bucket.
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        # An episode can have multiple audio_artifacts; rank picks the best
        # script too, so a duplicate row from a second audio render of the
        # same script_version doesn't harm the result — but it does cost a
        # teaser load. Dedupe by (episode_id, script_id) keeping the newest
        # audio first via SQL ORDER not yet applied; do it in-place here.
        key = (row["novel"], row["panel"])
        prev = buckets.get(key)
        if prev is None or _rank_key(row) < _rank_key(prev):
            buckets[key] = row

    out: list[dict[str, Any]] = []
    for (novel_key, panel), row in buckets.items():
        meta = _NOVEL_BY_ANY.get(novel_key)
        novel_title = meta.title if meta else novel_key
        author = meta.author if meta else ""
        year = meta.year if meta else 0
        out.append({
            "novel": novel_key,
            "novel_id": meta.id if meta else novel_key,
            "novel_title": novel_title,
            "author": author,
            "year": year,
            "panel": panel,
            "run_id": row["run_id"],
            "pipeline": row["pipeline"],
            "hostprep": bool(row["hostprep"]),
            "ref_tools": bool(row["ref_tools"]),
            "segments": row["n_segments"],
            "duration_seconds": row["duration_s"],
            "teaser": _load_teaser(runs_root, row["run_id"]),
        })

    out.sort(key=lambda r: (r["novel_title"].lower(), _PANEL_ORDER.get(r["panel"], 9)))
    return out
