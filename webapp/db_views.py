"""SQL views over the experiments DB, returned as lists of dicts.

Building blocks for endpoint code, not called from any endpoint yet.
The shape of `matrix_rows()` is the contract: one row per
(novel, panel, pipeline, hostprep, generator) coordinate, with the
freshest episode at that coordinate joined to its latest script,
hostprep, and audio artefacts.

Why "freshest episode": the episode UNIQUE(...) constraint includes
ref_tools, so a retrofit (typically ref_tools=1, run later) is a
distinct row from the older ref_tools=0 episode at the same
(novel, panel, pipeline, hostprep, generator). Matrix display picks
the most recent — retrofits surface naturally without per-feature
code.
"""

from __future__ import annotations

from typing import Any

from webapp.db import db_conn


# Window-function CTEs pick the freshest row in each partition. SQLite
# >= 3.25 supports window functions; verified in CPython 3.13.
_MATRIX_ROWS_SQL = """
WITH ranked_episode AS (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY novel, panel, pipeline, hostprep, generator
            ORDER BY created_at DESC, id DESC
        ) AS rn
    FROM episode
),
ranked_script AS (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY episode_id
            ORDER BY created_at DESC, id DESC
        ) AS rn
    FROM script_version
),
ranked_hostprep AS (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY episode_id
            ORDER BY created_at DESC, id DESC
        ) AS rn
    FROM hostprep_version
),
ranked_audio AS (
    SELECT a.id, a.script_version_id, a.tts_config_id, a.name,
           a.path, a.dvc_hash, a.duration_s, a.audio_manifest_path,
           a.created_at, s.episode_id,
        ROW_NUMBER() OVER (
            PARTITION BY s.episode_id
            ORDER BY a.created_at DESC, a.id DESC
        ) AS rn
    FROM audio_artifact a
    JOIN script_version s ON a.script_version_id = s.id
)
SELECT
    e.id            AS episode_id,
    e.novel         AS novel,
    e.panel         AS panel,
    e.pipeline      AS pipeline,
    e.hostprep      AS hostprep,
    e.generator     AS generator,
    e.ref_tools     AS ref_tools,
    e.label         AS run_id,
    e.created_at    AS episode_created_at,

    sc.id           AS script_version_id,
    sc.path         AS script_path,
    sc.n_segments   AS script_n_segments,
    sc.n_turns      AS script_n_turns,
    sc.n_utterances AS script_n_utterances,
    sc.created_at   AS script_created_at,

    hp.id           AS hostprep_version_id,
    hp.briefs_path  AS briefs_path,
    hp.interviews_path AS interviews_path,
    hp.n_segments   AS hostprep_n_segments,
    hp.n_interviews AS hostprep_n_interviews,
    hp.n_questions  AS hostprep_n_questions,
    hp.created_at   AS hostprep_created_at,

    au.id           AS audio_artifact_id,
    au.name         AS audio_name,
    au.path         AS audio_path,
    au.duration_s   AS audio_duration_s,
    au.audio_manifest_path AS audio_manifest_path,
    au.created_at   AS audio_created_at,

    CASE WHEN sc.id IS NOT NULL THEN 1 ELSE 0 END AS has_episode,
    CASE WHEN hp.id IS NOT NULL THEN 1 ELSE 0 END AS has_host_prep,
    CASE WHEN au.id IS NOT NULL THEN 1 ELSE 0 END AS has_audio
FROM ranked_episode e
LEFT JOIN ranked_script   sc ON sc.episode_id = e.id AND sc.rn = 1
LEFT JOIN ranked_hostprep hp ON hp.episode_id = e.id AND hp.rn = 1
LEFT JOIN ranked_audio    au ON au.episode_id = e.id AND au.rn = 1
WHERE e.rn = 1
ORDER BY e.novel, e.pipeline, e.panel, e.hostprep, e.generator
"""


def _row_status(row: dict[str, Any]) -> str:
    """Coarse status string for the matrix card. Mirrors the JS contract:
    'done' = episode rendered, 'host_prep' = hostprep but no script yet,
    'missing' = nothing on disk."""
    if row.get("has_episode"):
        return "done"
    if row.get("has_host_prep"):
        return "host_prep"
    return "missing"


def matrix_rows() -> list[dict[str, Any]]:
    """One row per (novel, panel, pipeline, hostprep, generator) cell.

    Retrofits surface as the freshest row at their coordinate.
    Each row includes:
      - axes: novel, panel, pipeline, hostprep, generator, ref_tools
      - run_id: episode.label (the run_dir name on disk)
      - latest script_version, hostprep_version, audio_artifact metadata
      - has_episode / has_host_prep / has_audio flags
      - status: 'done' | 'host_prep' | 'missing'
    """
    with db_conn() as conn:
        rows = [dict(r) for r in conn.execute(_MATRIX_ROWS_SQL).fetchall()]
    for r in rows:
        r["status"] = _row_status(r)
    return rows


def episode_by_run_id(run_id: str) -> dict[str, Any] | None:
    """Return the matrix-row dict for a single run_id (episode.label)."""
    rows = matrix_rows()
    for r in rows:
        if r["run_id"] == run_id:
            return r
    return None


def all_episode_run_ids() -> list[str]:
    """Every episode.label currently in the DB (one per row, ordered by
    most recent created_at first). Useful for endpoints that list runs."""
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT label FROM episode ORDER BY created_at DESC, id DESC"
        ).fetchall()
    return [r["label"] for r in rows]
