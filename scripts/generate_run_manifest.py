"""Generate data/runs/<id>/run_manifest.json — the single source of truth for a run.

Reconciles the webapp's view of a run with DVC's state by reading
dvc.lock and inspecting the filesystem.

Usage:
    uv run python scripts/generate_run_manifest.py [--run <id>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = BASE_DIR / "data" / "runs"
DVC_LOCK_PATH = BASE_DIR / "dvc.lock"


def get_git_sha(path: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=path, stderr=subprocess.DEVNULL
        ).decode("ascii").strip()
    except Exception:
        return "unknown"


def get_file_md5(path: Path) -> str | None:
    if not path.exists():
        return None
    hash_md5 = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def load_dvc_lock():
    if not DVC_LOCK_PATH.exists():
        return {}
    with open(DVC_LOCK_PATH) as f:
        return yaml.safe_load(f)


def generate_manifest(run_id: str, lock_data: dict, lock_sha: str):
    run_dir = RUNS_DIR / run_id
    cfg_path = run_dir / "config.json"
    if not cfg_path.exists():
        logger.warning(f"No config.json for {run_id}")
        return

    with open(cfg_path) as f:
        cfg = json.load(f)
    axes = cfg.get("axes", {})

    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "axes": axes,
        "stages": {},
        "audio_variants": [],
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dvc_lock_sha": lock_sha,
    }

    stages_in_lock = lock_data.get("stages", {})

    # Define the stages we care about for the manifest
    target_stages = {
        "phase3": f"phase3_episode@{run_id}",
        "phase2_5": f"phase2_5@{run_id}",
        "quote_verification": f"quote_verification@{run_id}",
        "phase4_audio": f"phase4_audio@{run_id}",
        "phase4_audio_qwen": f"phase4_audio_qwen@{run_id}",
        "phase4_audio_trevelyan_v2": f"phase4_audio_trevelyan_v2@{run_id}",
    }

    for key, stage_name in target_stages.items():
        lock_entry = stages_in_lock.get(stage_name)
        if not lock_entry:
            continue

        stage_info = {"fresh": False}
        
        # Check outputs
        outs = lock_entry.get("outs", [])
        if not outs:
            continue
            
        # We'll use the first output as the primary representative for the stage's hash/freshness
        primary_out = outs[0]
        out_path = BASE_DIR / primary_out["path"]
        lock_hash = primary_out.get("md5")
        
        stage_info["hash"] = lock_hash
        
        if out_path.exists():
            actual_hash = get_file_md5(out_path)
            stage_info["fresh"] = (actual_hash == lock_hash)
            
        # Special handling for quote_verification
        if key == "quote_verification" and out_path.exists():
            try:
                with open(out_path) as f:
                    qv_data = json.load(f)
                    stage_info.update({
                        "verified": qv_data.get("verified"),
                        "total": qv_data.get("total"),
                        "rate": qv_data.get("rate"),
                    })
            except Exception:
                pass
                
        # Special handling for audio stages
        if key.startswith("phase4_audio"):
            # audio_variants entry
            variant_name = "classic"
            if "qwen" in key: variant_name = "qwen"
            elif "trevelyan_v2" in key: variant_name = "trevelyan_v2"
            
            # Find manifest and mp3 in outs
            audio_file = None
            audio_manifest = None
            for out in outs:
                p = out["path"]
                if p.endswith(".mp3"): audio_file = p
                if p.endswith("manifest.json") or p.endswith("manifest_qwen.json") or p.endswith("manifest_trevelyan_v2.json"):
                    audio_manifest = p
            
            # Fallback for classic if manifest not in DVC outs
            if variant_name == "classic" and not audio_manifest:
                fallback_manifest = f"data/runs/{run_id}/audio/manifest.json"
                if (BASE_DIR / fallback_manifest).exists():
                    audio_manifest = fallback_manifest

            engine_map = {
                "classic": "gemini-2.0-flash-preview-tts",
                "qwen": "qwen3-tts-0.6b-base",
                "trevelyan_v2": "gemini-3.1-flash-tts-preview"
            }
            
            variant_info = {
                "name": variant_name,
                "engine": engine_map.get(variant_name, "unknown"),
                "stage": key,
                "hash": lock_hash,
                "audio_file": audio_file,
                "audio_manifest": audio_manifest
            }
            manifest["audio_variants"].append(variant_info)
            
            stage_info.update({
                "audio_file": audio_file,
                "audio_manifest": audio_manifest,
                "engine": variant_info["engine"]
            })

        manifest["stages"][key] = stage_info

    out_path = run_dir / "run_manifest.json"
    with open(out_path, "w") as f:
        json.dump(manifest, f, indent=2)
    logger.info(f"Wrote {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", help="Run ID to generate manifest for (default: all)")
    args = parser.parse_args()

    lock_data = load_dvc_lock()
    lock_sha = get_git_sha(BASE_DIR)

    if args.run:
        generate_manifest(args.run, lock_data, lock_sha)
    else:
        for run_dir in sorted(RUNS_DIR.iterdir()):
            if not run_dir.is_dir() or run_dir.name.startswith("_"):
                continue
            if (run_dir / "config.json").exists():
                generate_manifest(run_dir.name, lock_data, lock_sha)


if __name__ == "__main__":
    main()
