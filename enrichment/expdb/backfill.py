"""Walk data/runs/<run_id>/ dirs and populate the experiment ledger."""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .store import Store


def _count_script(phase3: dict) -> tuple[int, int, int]:
    segments = phase3.get("segments", [])
    n_seg = len(segments)
    n_turns = sum(len(s.get("turns", [])) for s in segments)
    n_utt = sum(
        len(t.get("utterances", []))
        for s in segments for t in s.get("turns", [])
    )
    return n_seg, n_turns, n_utt


def _parse_ts(iso: str | None) -> float:
    if not iso:
        return time.time()
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return time.time()


def _read_audio_duration(run_dir: Path, manifest_rel: str | None) -> float | None:
    if not manifest_rel:
        return None
    candidate = run_dir / Path(manifest_rel).name  # try relative-to-run first
    if not candidate.exists():
        candidate = Path(manifest_rel)  # absolute / repo-relative
    if not candidate.exists():
        return None
    try:
        m = json.loads(candidate.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return m.get("episode_audio_seconds") or m.get("total_duration_s")


def scan_run_dir(store: Store, run_dir: Path) -> dict[str, Any]:
    """Idempotently insert rows for one run dir. Returns the resulting row IDs."""
    run_manifest_path = run_dir / "run_manifest.json"
    phase3_path = run_dir / "phase3_episode.json"
    if not run_manifest_path.exists():
        raise FileNotFoundError(run_manifest_path)
    if not phase3_path.exists():
        raise FileNotFoundError(phase3_path)

    rm = json.loads(run_manifest_path.read_text())
    phase3 = json.loads(phase3_path.read_text())

    axes = rm["axes"]
    label = rm.get("run_id", run_dir.name)

    episode_id = store.upsert_episode(
        novel=axes["novel"], panel=axes["panel"], pipeline=axes["pipeline"],
        hostprep=bool(axes.get("hostprep", False)), label=label,
    )

    # Idempotent script_version: keyed by (episode_id, path).
    n_seg, n_turns, n_utt = _count_script(phase3)
    script_path = str(phase3_path)  # absolute path; repo-rel can be derived later
    existing = [s for s in store.list_scripts_for_episode(episode_id) if s.path == script_path]
    if existing:
        sid = existing[0].id
    else:
        sid = store.create_script_version(
            episode_id=episode_id, path=script_path,
            dvc_hash=rm.get("stages", {}).get("phase3", {}).get("hash"),
            n_segments=n_seg, n_turns=n_turns, n_utterances=n_utt,
        )

    # Idempotent generation_run: keyed by (script_version_id, generator, dvc_rev).
    generator = axes.get("generator", "unknown")
    dvc_rev = rm.get("dvc_lock_sha")
    existing_runs = store.list_runs_for_script(sid)
    matching = [r for r in existing_runs if r.generator == generator and r.dvc_rev == dvc_rev]
    if matching:
        run_id = matching[0].id
    else:
        run_id = store.create_generation_run(
            script_version_id=sid, generator=generator,
            git_commit=None, dvc_rev=dvc_rev, config={},
            finished_at=_parse_ts(rm.get("generated_at")),
        )

    # Audio variants → tts_config + audio_artifact rows.
    audio_ids: list[int] = []
    existing_audio = {a.name: a for a in store.list_audio_for_script(sid)}
    for variant in rm.get("audio_variants", []):
        engine = variant.get("engine", "unknown")
        profile = variant.get("name")  # "classic", "trevelyan_v2", ...
        cfg_id = store.upsert_tts_config(
            engine=engine, profile=profile, voice_ref_ver=None, config={},
        )
        manifest_rel = variant.get("audio_manifest")
        duration_s = _read_audio_duration(run_dir, manifest_rel) if manifest_rel else None
        audio_file = variant.get("audio_file") or ""
        name = Path(audio_file).name or f"podcast_{profile or 'default'}.mp3"
        if name in existing_audio:
            audio_ids.append(existing_audio[name].id)
            continue
        aid = store.create_audio_artifact(
            script_version_id=sid, tts_config_id=cfg_id, name=name,
            path=audio_file, dvc_hash=variant.get("hash"),
            duration_s=duration_s, audio_manifest_path=manifest_rel,
        )
        audio_ids.append(aid)

    # Evaluations: quote_verification, if present.
    eval_ids: list[int] = []
    qv = rm.get("stages", {}).get("quote_verification")
    if qv and "verified" in qv:
        existing_evals = store.list_evaluations_for_script(sid)
        if not any(e.metric_kind == "quote_verification" for e in existing_evals):
            eval_ids.append(store.record_evaluation(
                script_version_id=sid, audio_artifact_id=None,
                metric_kind="quote_verification",
                metric={"verified": qv["verified"], "total": qv["total"],
                        "rate": qv.get("rate")},
            ))

    return {
        "episode_id": episode_id,
        "script_version_id": sid,
        "generation_run_id": run_id,
        "audio_artifact_ids": audio_ids,
        "evaluation_ids": eval_ids,
    }


def scan_runs_dir(store: Store, runs_dir: Path) -> dict[str, Any]:
    """Walk runs_dir/* and scan each subdir that has the required files."""
    scanned = 0
    skipped = 0
    errors: list[dict[str, str]] = []
    eps_before = len(store.list_episodes())
    scripts_before = sum(
        len(store.list_scripts_for_episode(e.id)) for e in store.list_episodes()
    )

    for entry in sorted(runs_dir.iterdir()):
        if not entry.is_dir():
            continue
        if not (entry / "run_manifest.json").exists() or not (entry / "phase3_episode.json").exists():
            skipped += 1
            continue
        try:
            scan_run_dir(store, entry)
            scanned += 1
        except Exception as exc:
            errors.append({"run_dir": str(entry), "error": str(exc)})

    eps_after = len(store.list_episodes())
    scripts_after = sum(
        len(store.list_scripts_for_episode(e.id)) for e in store.list_episodes()
    )
    return {
        "scanned": scanned,
        "skipped": skipped,
        "episodes_inserted": eps_after - eps_before,
        "scripts_inserted": scripts_after - scripts_before,
        "errors": errors,
    }
