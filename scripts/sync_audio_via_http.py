"""Push DVC audio cache blobs to fly via the webapp's HTTP admin endpoint.

Replaces sync_audio_to_fly.sh (fly ssh + tar pipe). The HTTPS edge has
none of the per-session lifetime issues that kill SSH transfers; we
just POST each blob and verify by md5.

Per-machine targeting via Fly's `fly-force-instance-id` header so each
machine's volume is populated independently.

Usage:
    ADMIN_UPLOAD_TOKEN=$(fly secrets list ...) \
    uv run python -m scripts.sync_audio_via_http
    uv run python -m scripts.sync_audio_via_http --machine <id>
    uv run python -m scripts.sync_audio_via_http --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import requests
import yaml

APP = os.environ.get("FLY_APP", "bleakhouse-demo")
APP_URL = os.environ.get("PUBLIC_URL", f"https://{APP}.fly.dev")


def _phase4_audio_hashes() -> list[str]:
    """Hashes for every cached audio output across phase4_audio variants.

    Matches any stage whose name starts with `phase4_audio` (covers
    `phase4_audio@<run>`, `phase4_audio_qwen@<run>`, `phase4_audio_
    trevelyan_v2@<run>`, and any future variant we add). The .mp3
    path filter ensures we only return blobs DVC actually caches —
    manifest JSONs (cache:false) have no md5 in the lock and would
    skip on the `o.get('md5')` check anyway.
    """
    lock = yaml.safe_load(Path("dvc.lock").read_text())
    out: list[str] = []
    for stage_name, stage in (lock.get("stages") or {}).items():
        if "@" not in stage_name or not stage_name.startswith("phase4_audio"):
            continue
        for o in stage.get("outs") or []:
            if not o.get("md5"):
                continue
            path = o.get("path") or ""
            if path.endswith(".mp3"):
                out.append(o["md5"])
    return out


def _machines() -> list[str]:
    raw = subprocess.check_output(["fly", "machines", "list", "-a", APP, "--json"], text=True)
    out: list[str] = []
    for m in json.loads(raw):
        if any(mt.get("name") == "audio_data" for mt in (m.get("config", {}).get("mounts") or [])):
            out.append(m["id"])
    return out


def _local_cache_dir() -> Path:
    raw = subprocess.check_output(
        ["uv", "run", "--no-sync", "dvc", "config", "cache.dir"], text=True
    ).strip()
    p = Path(raw) / "files" / "md5"
    if not p.is_dir():
        sys.exit(f"FAIL: local cache dir missing: {p}")
    return p


def _ensure_started(mach: str) -> None:
    raw = subprocess.check_output(["fly", "machines", "list", "-a", APP, "--json"], text=True)
    state = next((m["state"] for m in json.loads(raw) if m["id"] == mach), None)
    if state == "started":
        return
    print(f"  starting machine {mach} (was: {state})")
    subprocess.run(["fly", "machines", "start", mach, "-a", APP], check=True)


def _list_remote(mach: str, token: str) -> set[str]:
    """List blobs already on a machine's volume, with transient retry."""
    import time
    headers = {"X-Admin-Token": token, "Fly-Force-Instance-Id": mach}
    last_exc: Exception | None = None
    delay = 5
    for attempt in range(1, 6):
        try:
            r = requests.get(
                f"{APP_URL}/api/_admin/list-blobs", headers=headers, timeout=60
            )
            if r.status_code == 503 and "ADMIN_UPLOAD_TOKEN" in (r.text or ""):
                # Specific to "admin endpoint disabled" — not a transient.
                sys.exit("FAIL: admin endpoint disabled — set ADMIN_UPLOAD_TOKEN secret on fly")
            if r.status_code in _TRANSIENT_HTTP:
                last_exc = requests.HTTPError(f"transient {r.status_code}")
                print(f"      list-blobs attempt {attempt} got {r.status_code}; sleeping {delay}s",
                      file=sys.stderr)
                time.sleep(delay)
                delay *= 2
                continue
            r.raise_for_status()
            body = r.json()
            if body.get("machine_id") and body["machine_id"] != mach:
                sys.exit(
                    f"FAIL: requested machine {mach}, got response from {body['machine_id']}. "
                    f"Try `fly machines start {mach}` so it's the only running one, then re-run."
                )
            return set(body["hashes"])
        except (requests.ConnectionError, requests.Timeout) as e:
            last_exc = e
            print(f"      list-blobs attempt {attempt} connection error: {e}; sleeping {delay}s",
                  file=sys.stderr)
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"list-blobs failed after retries: {last_exc}")


_TRANSIENT_HTTP = {502, 503, 504, 408, 429}


def _push_blob(mach: str, h: str, blob_path: Path, token: str) -> None:
    """POST one blob with retry on transient fly-edge errors.

    fly's edge sporadically returns 502/503 when a target machine is
    cold-starting or its ingress is briefly unhealthy. Per-call retry
    keeps the deploy orchestrator (deploy_demo.sh) able to run end-to-
    end without manual resumption.
    """
    import time
    headers = {
        "X-Admin-Token": token,
        "Fly-Force-Instance-Id": mach,
        "Content-Type": "application/octet-stream",
    }
    last_exc: Exception | None = None
    delay = 5
    for attempt in range(1, 6):
        try:
            with blob_path.open("rb") as f:
                r = requests.post(
                    f"{APP_URL}/api/_admin/upload-blob",
                    params={"hash": h},
                    headers=headers,
                    data=f,  # streamed
                    timeout=600,
                )
            if r.status_code in _TRANSIENT_HTTP:
                print(
                    f"      attempt {attempt} got {r.status_code} from fly edge; "
                    f"sleeping {delay}s",
                    file=sys.stderr,
                )
                last_exc = requests.HTTPError(f"transient {r.status_code}")
                time.sleep(delay)
                delay *= 2
                continue
            r.raise_for_status()
            body = r.json()
            if body.get("machine_id") and body["machine_id"] != mach:
                sys.exit(f"FAIL: requested {mach}, response from {body['machine_id']}")
            return
        except (requests.ConnectionError, requests.Timeout) as e:
            print(f"      attempt {attempt} connection error: {e}; sleeping {delay}s",
                  file=sys.stderr)
            last_exc = e
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"upload-blob failed after retries: {last_exc}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--machine", help="single machine id; default = all with audio_data")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    token = os.environ.get("ADMIN_UPLOAD_TOKEN")
    if not token:
        sys.exit("FAIL: set ADMIN_UPLOAD_TOKEN env var (matches fly secret)")

    hashes = _phase4_audio_hashes()
    if not hashes:
        print("nothing to sync")
        return
    print(f"==> {len(hashes)} phase4_audio blob hashes from dvc.lock")

    machines = [args.machine] if args.machine else _machines()
    if not machines:
        sys.exit("FAIL: no fly machines with audio_data volume")
    print(f"==> targeting machine(s): {' '.join(machines)}")

    cache_root = _local_cache_dir()

    if args.dry_run:
        print(f"--dry-run: would consider {len(hashes)} blob(s) × {len(machines)} machine(s)")
        return

    for mach in machines:
        print(f"==> machine {mach}")
        _ensure_started(mach)
        existing = _list_remote(mach, token)
        missing = [h for h in hashes if h not in existing]
        print(f"    already on remote: {len(existing)} | missing: {len(missing)}")
        for i, h in enumerate(missing, 1):
            blob_path = cache_root / h[:2] / h[2:]
            if not blob_path.exists():
                print(f"    WARN: local blob missing: {h}", file=sys.stderr)
                continue
            sz = blob_path.stat().st_size
            print(f"    [{i}/{len(missing)}] {h} ({sz / 1e6:.1f} MB)", flush=True)
            _push_blob(mach, h, blob_path, token)
        # Re-probe to confirm.
        final = _list_remote(mach, token)
        landed = sum(1 for h in hashes if h in final)
        print(f"    machine {mach}: {landed}/{len(hashes)} blob(s) on remote")
        if landed < len(hashes):
            sys.exit(f"FAIL: machine {mach} only has {landed}/{len(hashes)}")

    print("SUCCESS: all machines fully synced")


if __name__ == "__main__":
    main()
