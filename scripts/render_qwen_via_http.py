"""Thin HTTP client for the qwen-tts-server on pop-os.local.

Replaces the body of scripts/render_qwen_remote.sh. ssh is no longer held
open — each poll is a fresh HTTP request, so a wifi blip / Mac sleep can't
kill an in-flight 2 h render. Job state is owned by the server.

Usage:
    uv run python scripts/render_qwen_via_http.py <run_id> [--ref-source PATH]
                                                            [--base-url URL]
Env (optional):
    QWEN_TTS_BASE_URL          default http://pop-os.local:8765
    QWEN_TTS_TOKEN             direct token (else read from token file)
    QWEN_TTS_TOKEN_FILE        default ~/.config/qwen-tts/token
    QWEN_TTS_POLL              poll interval seconds, default 15
    QWEN_TTS_RETRY             retry sleep seconds on transient errors, default 10
    QWEN_TTS_RETRY_ATTEMPTS    max attempts on a single request, default 30
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

DEFAULT_BASE_URL = os.environ.get("QWEN_TTS_BASE_URL", "http://pop-os.local:8765")
TOKEN_PATH = Path(os.environ.get("QWEN_TTS_TOKEN_FILE", str(Path.home() / ".config/qwen-tts/token")))
POLL_SECONDS = int(os.environ.get("QWEN_TTS_POLL", "15"))
RETRY_SECONDS = int(os.environ.get("QWEN_TTS_RETRY", "10"))
RETRY_ATTEMPTS = int(os.environ.get("QWEN_TTS_RETRY_ATTEMPTS", "30"))


def _load_token() -> str:
    env_token = os.environ.get("QWEN_TTS_TOKEN")
    if env_token:
        return env_token.strip()
    if not TOKEN_PATH.exists():
        sys.exit(f"FAIL: no token at {TOKEN_PATH} (or set QWEN_TTS_TOKEN env var)")
    return TOKEN_PATH.read_text().strip()


def _retrying_request(client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    """Retry transient HTTP/transport errors. 4xx is treated as terminal; 5xx retries."""
    last_err: Exception | None = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            r = client.request(method, url, **kwargs)
            if r.status_code >= 500:
                raise httpx.HTTPStatusError(f"{r.status_code}", request=r.request, response=r)
            return r
        except (httpx.HTTPError, httpx.TransportError) as exc:
            last_err = exc
            if attempt == RETRY_ATTEMPTS:
                break
            print(
                f"    {method} {url}: {exc} — retry in {RETRY_SECONDS}s ({attempt}/{RETRY_ATTEMPTS})",
                flush=True,
            )
            time.sleep(RETRY_SECONDS)
    raise SystemExit(f"FAIL: {method} {url} unrecoverable after {RETRY_ATTEMPTS} attempts: {last_err}")


def _resolve_ref_source(run_dir: Path, override: Path | None) -> Path:
    p = override or (run_dir / "audio" / "podcast.mp3")
    if not p.exists() and not p.is_symlink():
        sys.exit(f"FAIL: ref source {p} not found")
    return p.resolve()


def render(run_id: str, ref_source: Path | None, base_url: str) -> int:
    repo = Path(__file__).resolve().parent.parent
    run_dir = repo / "data" / "runs" / run_id
    if not run_dir.exists():
        sys.exit(f"FAIL: {run_dir} not found")
    manifest = run_dir / "manifest.json"
    phase3 = run_dir / "phase3_episode.json"
    if not manifest.exists():
        sys.exit(f"FAIL: {manifest} missing")
    if not phase3.exists():
        sys.exit(f"FAIL: {phase3} missing")
    ref_path = _resolve_ref_source(run_dir, ref_source)

    token = _load_token()
    headers = {"Authorization": f"Bearer {token}"}

    print(f"==> POST {base_url}/render  (run_id={run_id})", flush=True)
    with httpx.Client(timeout=httpx.Timeout(60.0), headers=headers) as client:
        with manifest.open("rb") as mf, phase3.open("rb") as p3, ref_path.open("rb") as rf:
            files = [
                ("manifest", ("manifest.json", mf, "application/json")),
                ("phase3", ("phase3_episode.json", p3, "application/json")),
                ("ref_source", (ref_path.name, rf, "audio/mpeg")),
            ]
            r = _retrying_request(
                client, "POST", f"{base_url}/render",
                data={"run_id": run_id}, files=files,
            )
        if r.status_code not in (200, 201):
            sys.exit(f"FAIL: render returned {r.status_code}: {r.text}")
        body = r.json()
        job_id = body["job"]["id"]
        existing = body["existing"]
        print(f"    job_id={job_id} existing={existing}", flush=True)

        prev_status: str | None = None
        j: dict = body["job"]
        while j["status"] not in ("succeeded", "failed", "cancelled"):
            time.sleep(POLL_SECONDS)
            r = _retrying_request(client, "GET", f"{base_url}/jobs/{job_id}")
            if r.status_code == 404:
                sys.exit(f"FAIL: job {job_id} disappeared")
            r.raise_for_status()
            j = r.json()
            if j["status"] != prev_status:
                print(f"    [{time.strftime('%H:%M:%S')}] status={j['status']}", flush=True)
                prev_status = j["status"]

        if j["status"] != "succeeded":
            log = _retrying_request(client, "GET", f"{base_url}/jobs/{job_id}/log").text
            print("--- server log ---", file=sys.stderr)
            print(log, file=sys.stderr)
            sys.exit(f"FAIL: job ended in status={j['status']}: {j.get('error') or '(no error)'}")

        audio_dir = run_dir / "audio"
        audio_dir.mkdir(exist_ok=True)
        wav_path = audio_dir / "podcast_qwen.wav"
        manifest_path = audio_dir / "manifest_qwen.json"

        print(f"==> GET episode.wav -> {wav_path}", flush=True)
        r = _retrying_request(client, "GET", f"{base_url}/jobs/{job_id}/result/episode.wav")
        r.raise_for_status()
        wav_path.write_bytes(r.content)

        print(f"==> GET episode.json -> {manifest_path}", flush=True)
        r = _retrying_request(client, "GET", f"{base_url}/jobs/{job_id}/result/episode.json")
        r.raise_for_status()
        manifest_path.write_bytes(r.content)

    mp3_path = audio_dir / "podcast_qwen.mp3"
    print(f"==> ffmpeg wav -> mp3 ({mp3_path})", flush=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path),
         "-b:a", "192k", str(mp3_path)],
        check=True,
    )
    wav_path.unlink()
    print(f"SUCCESS: {run_id} -> {mp3_path}", flush=True)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--ref-source", type=Path, default=None)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    args = parser.parse_args()
    sys.exit(render(args.run_id, args.ref_source, args.base_url))


if __name__ == "__main__":
    main()
