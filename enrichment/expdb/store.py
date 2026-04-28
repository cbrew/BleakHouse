"""Experiment ledger Store — SQLite, stdlib only."""
from __future__ import annotations

import json
import sqlite3
import time
from importlib.resources import files
from pathlib import Path

from .models import AudioArtifact, Episode, GenerationRun, ScriptVersion, TTSConfig

EXPECTED_USER_VERSION = 1


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
            if current >= EXPECTED_USER_VERSION:
                return
            c.executescript(_schema_sql())
            c.execute(f"PRAGMA user_version = {EXPECTED_USER_VERSION}")

    # ---- Episode ----

    def upsert_episode(self, *, novel: str, panel: str, pipeline: str,
                       hostprep: bool, label: str) -> int:
        with self._conn() as c:
            row = c.execute(
                "SELECT id FROM episode WHERE novel=? AND panel=? AND pipeline=? AND hostprep=?",
                (novel, panel, pipeline, int(hostprep)),
            ).fetchone()
            if row is not None:
                return int(row["id"])
            cur = c.execute(
                "INSERT INTO episode(novel, panel, pipeline, hostprep, label, created_at) "
                "VALUES(?,?,?,?,?,?)",
                (novel, panel, pipeline, int(hostprep), label, time.time()),
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

    # ---- ScriptVersion ----

    def create_script_version(self, *, episode_id: int, path: str,
                              dvc_hash: str | None, n_segments: int,
                              n_turns: int, n_utterances: int) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO script_version"
                "(episode_id, path, dvc_hash, n_segments, n_turns, n_utterances, created_at)"
                " VALUES(?,?,?,?,?,?,?)",
                (episode_id, path, dvc_hash, n_segments, n_turns, n_utterances, time.time()),
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


def _row_to_episode(row: sqlite3.Row) -> Episode:
    return Episode(
        id=int(row["id"]),
        novel=row["novel"],
        panel=row["panel"],
        pipeline=row["pipeline"],
        hostprep=bool(row["hostprep"]),
        label=row["label"],
        created_at=float(row["created_at"]),
    )


def _row_to_script(row: sqlite3.Row) -> ScriptVersion:
    return ScriptVersion(
        id=int(row["id"]),
        episode_id=int(row["episode_id"]),
        path=row["path"],
        dvc_hash=row["dvc_hash"],
        n_segments=int(row["n_segments"]),
        n_turns=int(row["n_turns"]),
        n_utterances=int(row["n_utterances"]),
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
