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

from pathlib import Path
from typing import Any

from webapp.db import db_conn  # pyright: ignore[reportMissingImports]

# Repo root: webapp/db_views.py → webapp → REPO
_REPO_ROOT = Path(__file__).resolve().parent.parent

# Path columns that store repo-relative file paths. The DB is portable
# across machines (Mac dev box, Linux server, Fly container) only because
# stored paths are relative to _REPO_ROOT and resolved on read.
_PATH_COLUMNS = (
    "script_path", "briefs_path", "interviews_path",
    "audio_path", "audio_manifest_path",
)


def _resolve_path(value: str | None) -> str | None:
    """Resolve a stored path to absolute against the current repo root.

    Stored paths are repo-relative ('data/runs/<run>/...'). On read, they
    expand to wherever the repo lives now, so the DB works on a Mac at
    /Users/brewc/... and on Fly at /app/... without rewriting rows.

    Already-absolute values are passed through (legacy rows pre-migration;
    a one-shot migration should rewrite them).
    """
    if value is None or value == "":
        return value
    p = Path(value)
    if p.is_absolute():
        return value
    return str(_REPO_ROOT / p)


def _resolve_row_paths(row: dict[str, Any]) -> dict[str, Any]:
    """In-place expand every known path column on a row dict."""
    for col in _PATH_COLUMNS:
        if col in row:
            row[col] = _resolve_path(row[col])
    return row


# Window-function CTEs pick the freshest row in each partition. SQLite
# >= 3.25 supports window functions; verified in CPython 3.13.
#
# Episode ordering note: a retrofit creates a new episode at the same
# (novel, panel, pipeline, hostprep, generator) coordinate with a new
# script_version, but typically does NOT re-render audio. Strictly
# picking the newest episode per coordinate would silently drop audio
# the user can still play. So we rank audio-bearing episodes first
# within each coordinate, falling back to creation time. Matrix cells
# at coordinates with any audio always surface the audio-bearing run.
_MATRIX_ROWS_SQL = """
WITH episode_with_audio_flag AS (
    SELECT e.*,
        CASE WHEN EXISTS (
            SELECT 1
            FROM audio_artifact a
            JOIN script_version s ON a.script_version_id = s.id
            WHERE s.episode_id = e.id
        ) THEN 1 ELSE 0 END AS coord_has_audio
    FROM episode e
),
ranked_episode AS (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY novel, panel, pipeline, hostprep, generator
            ORDER BY coord_has_audio DESC, created_at DESC, id DESC
        ) AS rn
    FROM episode_with_audio_flag
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
        _resolve_row_paths(r)
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


# Same join shape as _MATRIX_ROWS_SQL but without the per-coordinate dedup
# filter on episode. Returns one row per *distinct* episode, joined to its
# freshest script/hostprep/audio. Powers /tracker/versions and the run-list
# endpoints (one row per run, regardless of whether a fresher run shares the
# same axes).
_ALL_EPISODES_SQL = """
WITH ranked_script AS (
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
FROM episode e
LEFT JOIN ranked_script   sc ON sc.episode_id = e.id AND sc.rn = 1
LEFT JOIN ranked_hostprep hp ON hp.episode_id = e.id AND hp.rn = 1
LEFT JOIN ranked_audio    au ON au.episode_id = e.id AND au.rn = 1
ORDER BY e.created_at DESC, e.id DESC
"""


def all_episode_rows() -> list[dict[str, Any]]:
    """One row per distinct episode (no per-coordinate dedup), joined to its
    freshest script/hostprep/audio. Use for run-list and version-grouping
    surfaces; use matrix_rows() for the per-coord matrix view."""
    with db_conn() as conn:
        rows = [dict(r) for r in conn.execute(_ALL_EPISODES_SQL).fetchall()]
    for r in rows:
        _resolve_row_paths(r)
        r["status"] = _row_status(r)
    return rows


def hostprep_for_run(run_id: str) -> dict[str, Any] | None:
    """Return the latest hostprep_version paths for an episode, looked up by
    label. Used by /api/runs/<id>/prep so retrofit episodes serve their
    refreshed interviews/briefs (which may live in a different dir than the
    original episode label).

    Returns None if the episode has no hostprep_version. Returned dict has
    keys: interviews_path, briefs_path, n_segments, n_interviews, n_questions.
    """
    sql = """
        SELECT hp.interviews_path, hp.briefs_path, hp.n_segments,
               hp.n_interviews, hp.n_questions
        FROM episode e
        JOIN hostprep_version hp ON hp.episode_id = e.id
        WHERE e.label = ?
        ORDER BY hp.created_at DESC, hp.id DESC
        LIMIT 1
    """
    with db_conn() as conn:
        row = conn.execute(sql, (run_id,)).fetchone()
    if row is None:
        return None
    return _resolve_row_paths(dict(row))
