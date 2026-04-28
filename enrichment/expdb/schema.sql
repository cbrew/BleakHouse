-- The logical episode: a fully-specified experimental condition. Generator
-- (which LLM produced the script) is a treatment axis — running the same
-- (novel, panel, pipeline, hostprep) tuple through Anthropic Sonnet vs
-- Cerebras Qwen vs Z.AI GLM is three separate experiments, not three
-- realisations of one experiment.
CREATE TABLE episode (
    id           INTEGER PRIMARY KEY,
    novel        TEXT NOT NULL,
    panel        TEXT NOT NULL,
    pipeline     TEXT NOT NULL,
    hostprep     INTEGER NOT NULL,
    generator    TEXT NOT NULL,
    label        TEXT NOT NULL,
    created_at   REAL NOT NULL,
    UNIQUE(novel, panel, pipeline, hostprep, generator)
);

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
