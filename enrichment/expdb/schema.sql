-- The logical episode: a fully-specified experimental condition. Treatment
-- axes that materially change the output, beyond (novel, panel, pipeline,
-- hostprep), are:
--   generator   — which LLM produced the script (Sonnet vs Cerebras Qwen vs ...)
--   ref_tools   — whether hostprep had OpenAlex/Wikipedia reference search
--                 enabled, which injects scholarly citations into the host's
--                 questions and produces phase2_5_reading_list.json
--   length      — 'long' (~90-min episodes, the original scope) or 'short'
--                 (~30-min episodes, regenerated with a tighter Phase 3 prompt
--                 target). Short variants live in <run>_short/ sibling dirs.
CREATE TABLE episode (
    id           INTEGER PRIMARY KEY,
    opaque_id    TEXT UNIQUE,
    novel        TEXT NOT NULL,
    panel        TEXT NOT NULL,
    pipeline     TEXT NOT NULL,
    hostprep     INTEGER NOT NULL,
    generator    TEXT NOT NULL,
    ref_tools    INTEGER NOT NULL,
    length       TEXT NOT NULL DEFAULT 'long',
    label        TEXT NOT NULL,
    created_at   REAL NOT NULL,
    UNIQUE(novel, panel, pipeline, hostprep, generator, ref_tools, length)
);

-- Axis registry. Names mirror enrichment.axes.AXES. Adding a new axis is a
-- one-place edit in axes.py + a backfill that calls AxisStore.set_axes()
-- for existing episodes; no schema migration needed.
CREATE TABLE axis (
    name TEXT PRIMARY KEY
);

-- Inverted-index source: (episode_id, axis_name) → canonical value.
-- One row per (episode, axis). Reverse lookup (axis,value → episodes) is
-- powered by idx_episode_axis_value.
CREATE TABLE episode_axis (
    episode_id INTEGER NOT NULL REFERENCES episode(id) ON DELETE CASCADE,
    axis_name  TEXT NOT NULL REFERENCES axis(name),
    value      TEXT NOT NULL,
    PRIMARY KEY (episode_id, axis_name)
);

CREATE INDEX idx_episode_axis_value ON episode_axis(axis_name, value);

-- Host preparation: per-(segment, expert) Haiku interviews +
-- per-segment Sonnet briefs. Inputs to script generation when
-- episode.hostprep is true. One hostprep run produces both
-- phase2_5_interviews.json and phase2_5_host_briefs.json.
CREATE TABLE hostprep_version (
    id                   INTEGER PRIMARY KEY,
    episode_id           INTEGER NOT NULL REFERENCES episode(id),
    interviews_path      TEXT NOT NULL,
    interviews_dvc_hash  TEXT,
    briefs_path          TEXT NOT NULL,
    briefs_dvc_hash      TEXT,
    n_segments           INTEGER NOT NULL,
    n_interviews         INTEGER NOT NULL,
    n_questions          INTEGER NOT NULL,
    created_at           REAL NOT NULL
);

-- One generated script. Produced by exactly one generation_run.
-- Optionally references a hostprep_version (null when episode.hostprep=false).
CREATE TABLE script_version (
    id                   INTEGER PRIMARY KEY,
    episode_id           INTEGER NOT NULL REFERENCES episode(id),
    hostprep_version_id  INTEGER REFERENCES hostprep_version(id),
    path                 TEXT NOT NULL,
    dvc_hash             TEXT,
    n_segments           INTEGER NOT NULL,
    n_turns              INTEGER NOT NULL,
    n_utterances         INTEGER NOT NULL,
    created_at           REAL NOT NULL
);

-- A single execution of a generation pipeline. Produces one script_version.
-- Captures git_commit + dvc_rev so we can reproduce.
CREATE TABLE generation_run (
    id                  INTEGER PRIMARY KEY,
    script_version_id   INTEGER NOT NULL REFERENCES script_version(id),
    generator           TEXT NOT NULL,
    git_commit          TEXT,
    dvc_rev             TEXT,
    config_json         TEXT,
    started_at          REAL,
    finished_at         REAL NOT NULL,
    UNIQUE(script_version_id, generator, git_commit)
);

-- A TTS configuration. References a designed voice ref version.
-- Many audio_artifacts can share a tts_config (same engine + voice = same config).
CREATE TABLE tts_config (
    id              INTEGER PRIMARY KEY,
    engine          TEXT NOT NULL,
    profile         TEXT,
    voice_ref_ver   TEXT,
    config_json     TEXT NOT NULL,
    created_at      REAL NOT NULL,
    UNIQUE(engine, profile, voice_ref_ver, config_json)
);

-- A rendered audio file. Path on disk + DVC hash + which (script, config) made it.
CREATE TABLE audio_artifact (
    id                  INTEGER PRIMARY KEY,
    script_version_id   INTEGER NOT NULL REFERENCES script_version(id),
    tts_config_id       INTEGER NOT NULL REFERENCES tts_config(id),
    name                TEXT NOT NULL,
    path                TEXT NOT NULL,
    dvc_hash            TEXT,
    duration_s          REAL,
    audio_manifest_path TEXT,
    created_at          REAL NOT NULL,
    UNIQUE(script_version_id, tts_config_id, name)
);

-- Quality / verification measurements attached to a script, audio artefact,
-- or hostprep version (e.g. reading-list verification rate).
CREATE TABLE evaluation (
    id                   INTEGER PRIMARY KEY,
    script_version_id    INTEGER REFERENCES script_version(id),
    audio_artifact_id    INTEGER REFERENCES audio_artifact(id),
    hostprep_version_id  INTEGER REFERENCES hostprep_version(id),
    metric_kind          TEXT NOT NULL,
    metric_json          TEXT NOT NULL,
    created_at           REAL NOT NULL,
    CHECK (script_version_id IS NOT NULL OR audio_artifact_id IS NOT NULL
           OR hostprep_version_id IS NOT NULL)
);

-- A request to redo a turn / segment / whole episode under a different
-- tts_config. Empty initially; populated by the future interactive UI.
CREATE TABLE regeneration_request (
    id                       INTEGER PRIMARY KEY,
    audio_artifact_id        INTEGER NOT NULL REFERENCES audio_artifact(id),
    new_tts_config_id        INTEGER NOT NULL REFERENCES tts_config(id),
    scope                    TEXT NOT NULL,
    requested_at             REAL NOT NULL,
    fulfilled_audio_artifact INTEGER REFERENCES audio_artifact(id),
    fulfilled_at             REAL
);

CREATE INDEX idx_script_episode ON script_version(episode_id);
CREATE INDEX idx_script_hostprep ON script_version(hostprep_version_id);
CREATE INDEX idx_hostprep_episode ON hostprep_version(episode_id);
CREATE INDEX idx_run_script ON generation_run(script_version_id);
CREATE INDEX idx_audio_script ON audio_artifact(script_version_id);
CREATE INDEX idx_audio_config ON audio_artifact(tts_config_id);
CREATE INDEX idx_eval_script ON evaluation(script_version_id);
CREATE INDEX idx_eval_audio ON evaluation(audio_artifact_id);
CREATE INDEX idx_eval_hostprep ON evaluation(hostprep_version_id);

-- Per-run, per-stage cost / token / timing rollup. One row per
-- (run_label, stage). Populated by scripts/timings_summary.py from the
-- per-phase phase<N>_timings.json sidecars in the run dir, so the DB
-- can answer queries like "average phase3 cost per generator" in SQL
-- without reading 200+ JSON files.
--
-- run_label is denormalised so analyses don't have to join through
-- episode → script_version → generation_run for the common case of
-- "find this run's costs by name". novel is denormalised similarly.
-- generation_run_id is nullable because timings can be summarised
-- before a generation_run row exists (e.g. just-rendered audio that
-- the experiments scanner hasn't picked up yet).
CREATE TABLE run_cost (
    id                 INTEGER PRIMARY KEY,
    generation_run_id  INTEGER REFERENCES generation_run(id),
    novel              TEXT,
    run_label          TEXT NOT NULL,
    stage              TEXT NOT NULL,
    n_calls            INTEGER NOT NULL,
    cpu_s              REAL NOT NULL,
    wall_s             REAL NOT NULL,
    in_tok             INTEGER NOT NULL,
    cache_w_tok        INTEGER NOT NULL,
    cache_r_tok        INTEGER NOT NULL,
    out_tok            INTEGER NOT NULL,
    in_chars           INTEGER NOT NULL,
    audio_ms           INTEGER NOT NULL,
    cost_usd           REAL NOT NULL,
    created_at         REAL NOT NULL,
    UNIQUE(run_label, stage)
);

CREATE INDEX idx_run_cost_label ON run_cost(run_label);
CREATE INDEX idx_run_cost_stage ON run_cost(stage);
CREATE INDEX idx_run_cost_genrun ON run_cost(generation_run_id);
