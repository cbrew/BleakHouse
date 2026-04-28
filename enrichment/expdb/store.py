"""Experiment ledger Store — SQLite, stdlib only."""
from __future__ import annotations

import json
import sqlite3
import time
from importlib.resources import files
from pathlib import Path

from .models import (
    AudioArtifact,
    Episode,
    Evaluation,
    GenerationRun,
    HostprepVersion,
    RegenerationRequest,
    ScriptVersion,
    TTSConfig,
)

# TTSConfig is imported for re-export — callers may want the row dataclass.
_ = TTSConfig

EXPECTED_USER_VERSION = 4


def _schema_sql() -> str:
    return (files("enrichment.expdb") / "schema.sql").read_text()


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        return c

    def init_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            current = c.execute("PRAGMA user_version").fetchone()[0]
            if current == EXPECTED_USER_VERSION:
                return
            if current == 0:
                c.executescript(_schema_sql())
                c.execute(f"PRAGMA user_version = {EXPECTED_USER_VERSION}")
                return
            raise RuntimeError(
                f"DB at {self.path} is at user_version={current}, "
                f"expected {EXPECTED_USER_VERSION}. The DB is regenerable from "
                f"data/runs — delete it and re-run `python -m enrichment.expdb scan`."
            )

    # ---- Episode ----

    def upsert_episode(self, *, novel: str, panel: str, pipeline: str,
                       hostprep: bool, generator: str, ref_tools: bool,
                       label: str) -> int:
        with self._conn() as c:
            row = c.execute(
                "SELECT id FROM episode WHERE novel=? AND panel=? AND pipeline=? "
                "AND hostprep=? AND generator=? AND ref_tools=?",
                (novel, panel, pipeline, int(hostprep), generator, int(ref_tools)),
            ).fetchone()
            if row is not None:
                return int(row["id"])
            cur = c.execute(
                "INSERT INTO episode(novel, panel, pipeline, hostprep, generator, "
                "ref_tools, label, created_at) VALUES(?,?,?,?,?,?,?,?)",
                (novel, panel, pipeline, int(hostprep), generator,
                 int(ref_tools), label, time.time()),
            )
            assert cur.lastrowid is not None
            return int(cur.lastrowid)

    def get_episode(self, episode_id: int) -> Episode | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM episode WHERE id=?", (episode_id,)).fetchone()
        return _row_to_episode(row) if row else None

    def list_episodes(self, *, novel: str | None = None) -> list[Episode]:
        sql = "SELECT * FROM episode"
        params: tuple = ()
        if novel is not None:
            sql += " WHERE novel=?"
            params = (novel,)
        sql += " ORDER BY id"
        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [_row_to_episode(r) for r in rows]

    # ---- HostprepVersion ----

    def create_hostprep_version(self, *, episode_id: int,
                                  interviews_path: str,
                                  interviews_dvc_hash: str | None,
                                  briefs_path: str,
                                  briefs_dvc_hash: str | None,
                                  n_segments: int, n_interviews: int,
                                  n_questions: int) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO hostprep_version"
                "(episode_id, interviews_path, interviews_dvc_hash, briefs_path, "
                " briefs_dvc_hash, n_segments, n_interviews, n_questions, created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (episode_id, interviews_path, interviews_dvc_hash,
                 briefs_path, briefs_dvc_hash,
                 n_segments, n_interviews, n_questions, time.time()),
            )
            assert cur.lastrowid is not None
            return int(cur.lastrowid)

    def get_hostprep_version(self, hpv_id: int) -> HostprepVersion | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM hostprep_version WHERE id=?",
                            (hpv_id,)).fetchone()
        return _row_to_hostprep(row) if row else None

    def list_hostprep_for_episode(self, episode_id: int) -> list[HostprepVersion]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM hostprep_version WHERE episode_id=? ORDER BY id",
                (episode_id,),
            ).fetchall()
        return [_row_to_hostprep(r) for r in rows]

    # ---- ScriptVersion ----

    def create_script_version(self, *, episode_id: int, path: str,
                              dvc_hash: str | None, n_segments: int,
                              n_turns: int, n_utterances: int,
                              hostprep_version_id: int | None = None) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO script_version"
                "(episode_id, hostprep_version_id, path, dvc_hash, "
                " n_segments, n_turns, n_utterances, created_at)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (episode_id, hostprep_version_id, path, dvc_hash,
                 n_segments, n_turns, n_utterances, time.time()),
            )
            assert cur.lastrowid is not None
            return int(cur.lastrowid)

    def get_script_version(self, sid: int) -> ScriptVersion | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM script_version WHERE id=?", (sid,)).fetchone()
        return _row_to_script(row) if row else None

    def list_scripts_for_episode(self, episode_id: int) -> list[ScriptVersion]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM script_version WHERE episode_id=? ORDER BY id",
                (episode_id,),
            ).fetchall()
        return [_row_to_script(r) for r in rows]

    # ---- GenerationRun ----

    def create_generation_run(self, *, script_version_id: int, generator: str,
                              git_commit: str | None, dvc_rev: str | None,
                              config: dict, finished_at: float,
                              started_at: float | None = None) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO generation_run"
                "(script_version_id, generator, git_commit, dvc_rev, config_json,"
                " started_at, finished_at) VALUES(?,?,?,?,?,?,?)",
                (script_version_id, generator, git_commit, dvc_rev,
                 json.dumps(config), started_at, finished_at),
            )
            assert cur.lastrowid is not None
            return int(cur.lastrowid)

    def get_generation_run(self, rid: int) -> GenerationRun | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM generation_run WHERE id=?", (rid,)).fetchone()
        return _row_to_run(row) if row else None

    def list_runs_for_script(self, script_version_id: int) -> list[GenerationRun]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM generation_run WHERE script_version_id=? ORDER BY id",
                (script_version_id,),
            ).fetchall()
        return [_row_to_run(r) for r in rows]

    # ---- TTSConfig ----

    def upsert_tts_config(self, *, engine: str, profile: str | None,
                           voice_ref_ver: str | None, config: dict) -> int:
        cfg_json = json.dumps(config, sort_keys=True)
        with self._conn() as c:
            row = c.execute(
                "SELECT id FROM tts_config WHERE engine=? AND "
                "COALESCE(profile,'')=COALESCE(?,'') AND "
                "COALESCE(voice_ref_ver,'')=COALESCE(?,'') AND "
                "config_json=?",
                (engine, profile, voice_ref_ver, cfg_json),
            ).fetchone()
            if row is not None:
                return int(row["id"])
            cur = c.execute(
                "INSERT INTO tts_config(engine, profile, voice_ref_ver, config_json, created_at) "
                "VALUES(?,?,?,?,?)",
                (engine, profile, voice_ref_ver, cfg_json, time.time()),
            )
            assert cur.lastrowid is not None
            return int(cur.lastrowid)

    # ---- AudioArtifact ----

    def create_audio_artifact(self, *, script_version_id: int, tts_config_id: int,
                               name: str, path: str, dvc_hash: str | None,
                               duration_s: float | None = None,
                               audio_manifest_path: str | None = None) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO audio_artifact"
                "(script_version_id, tts_config_id, name, path, dvc_hash, "
                " duration_s, audio_manifest_path, created_at)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (script_version_id, tts_config_id, name, path, dvc_hash,
                 duration_s, audio_manifest_path, time.time()),
            )
            assert cur.lastrowid is not None
            return int(cur.lastrowid)

    def get_audio_artifact(self, aid: int) -> AudioArtifact | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM audio_artifact WHERE id=?", (aid,)).fetchone()
        return _row_to_audio(row) if row else None

    def list_audio_for_script(self, script_version_id: int) -> list[AudioArtifact]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM audio_artifact WHERE script_version_id=? ORDER BY id",
                (script_version_id,),
            ).fetchall()
        return [_row_to_audio(r) for r in rows]

    # ---- Evaluation ----

    def record_evaluation(self, *, script_version_id: int | None = None,
                           audio_artifact_id: int | None = None,
                           hostprep_version_id: int | None = None,
                           metric_kind: str, metric: dict) -> int:
        if (script_version_id is None and audio_artifact_id is None
                and hostprep_version_id is None):
            raise ValueError(
                "evaluation must reference a script, an audio artefact, or a hostprep version"
            )
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO evaluation"
                "(script_version_id, audio_artifact_id, hostprep_version_id, "
                " metric_kind, metric_json, created_at)"
                " VALUES(?,?,?,?,?,?)",
                (script_version_id, audio_artifact_id, hostprep_version_id,
                 metric_kind, json.dumps(metric), time.time()),
            )
            assert cur.lastrowid is not None
            return int(cur.lastrowid)

    def list_evaluations_for_script(self, sid: int) -> list[Evaluation]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM evaluation WHERE script_version_id=? ORDER BY id",
                (sid,),
            ).fetchall()
        return [_row_to_eval(r) for r in rows]

    def list_evaluations_for_audio(self, aid: int) -> list[Evaluation]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM evaluation WHERE audio_artifact_id=? ORDER BY id",
                (aid,),
            ).fetchall()
        return [_row_to_eval(r) for r in rows]

    def list_evaluations_for_hostprep(self, hpv_id: int) -> list[Evaluation]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM evaluation WHERE hostprep_version_id=? ORDER BY id",
                (hpv_id,),
            ).fetchall()
        return [_row_to_eval(r) for r in rows]

    # ---- RegenerationRequest ----

    def create_regeneration_request(self, *, audio_artifact_id: int,
                                      new_tts_config_id: int, scope: str) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO regeneration_request"
                "(audio_artifact_id, new_tts_config_id, scope, requested_at)"
                " VALUES(?,?,?,?)",
                (audio_artifact_id, new_tts_config_id, scope, time.time()),
            )
            assert cur.lastrowid is not None
            return int(cur.lastrowid)

    def get_regeneration_request(self, rid: int) -> RegenerationRequest | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM regeneration_request WHERE id=?",
                            (rid,)).fetchone()
        return _row_to_regen(row) if row else None


def _row_to_episode(row: sqlite3.Row) -> Episode:
    return Episode(
        id=int(row["id"]),
        novel=row["novel"],
        panel=row["panel"],
        pipeline=row["pipeline"],
        hostprep=bool(row["hostprep"]),
        generator=row["generator"],
        ref_tools=bool(row["ref_tools"]),
        label=row["label"],
        created_at=float(row["created_at"]),
    )


def _row_to_script(row: sqlite3.Row) -> ScriptVersion:
    return ScriptVersion(
        id=int(row["id"]),
        episode_id=int(row["episode_id"]),
        hostprep_version_id=int(row["hostprep_version_id"])
            if row["hostprep_version_id"] is not None else None,
        path=row["path"],
        dvc_hash=row["dvc_hash"],
        n_segments=int(row["n_segments"]),
        n_turns=int(row["n_turns"]),
        n_utterances=int(row["n_utterances"]),
        created_at=float(row["created_at"]),
    )


def _row_to_hostprep(row: sqlite3.Row) -> HostprepVersion:
    return HostprepVersion(
        id=int(row["id"]),
        episode_id=int(row["episode_id"]),
        interviews_path=row["interviews_path"],
        interviews_dvc_hash=row["interviews_dvc_hash"],
        briefs_path=row["briefs_path"],
        briefs_dvc_hash=row["briefs_dvc_hash"],
        n_segments=int(row["n_segments"]),
        n_interviews=int(row["n_interviews"]),
        n_questions=int(row["n_questions"]),
        created_at=float(row["created_at"]),
    )


def _row_to_run(row: sqlite3.Row) -> GenerationRun:
    return GenerationRun(
        id=int(row["id"]),
        script_version_id=int(row["script_version_id"]),
        generator=row["generator"],
        git_commit=row["git_commit"],
        dvc_rev=row["dvc_rev"],
        config=json.loads(row["config_json"] or "{}"),
        started_at=float(row["started_at"]) if row["started_at"] is not None else None,
        finished_at=float(row["finished_at"]),
    )


def _row_to_audio(row: sqlite3.Row) -> AudioArtifact:
    return AudioArtifact(
        id=int(row["id"]),
        script_version_id=int(row["script_version_id"]),
        tts_config_id=int(row["tts_config_id"]),
        name=row["name"],
        path=row["path"],
        dvc_hash=row["dvc_hash"],
        duration_s=float(row["duration_s"]) if row["duration_s"] is not None else None,
        audio_manifest_path=row["audio_manifest_path"],
        created_at=float(row["created_at"]),
    )


def _row_to_eval(row: sqlite3.Row) -> Evaluation:
    return Evaluation(
        id=int(row["id"]),
        script_version_id=int(row["script_version_id"]) if row["script_version_id"] is not None else None,
        audio_artifact_id=int(row["audio_artifact_id"]) if row["audio_artifact_id"] is not None else None,
        hostprep_version_id=int(row["hostprep_version_id"]) if row["hostprep_version_id"] is not None else None,
        metric_kind=row["metric_kind"],
        metric=json.loads(row["metric_json"]),
        created_at=float(row["created_at"]),
    )


def _row_to_regen(row: sqlite3.Row) -> RegenerationRequest:
    return RegenerationRequest(
        id=int(row["id"]),
        audio_artifact_id=int(row["audio_artifact_id"]),
        new_tts_config_id=int(row["new_tts_config_id"]),
        scope=row["scope"],
        requested_at=float(row["requested_at"]),
        fulfilled_audio_artifact=int(row["fulfilled_audio_artifact"]) if row["fulfilled_audio_artifact"] is not None else None,
        fulfilled_at=float(row["fulfilled_at"]) if row["fulfilled_at"] is not None else None,
    )
