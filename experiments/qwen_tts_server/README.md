# qwen-tts-server

FastAPI service on `pop-os.local` that owns the GPU and runs Qwen3-TTS renders.
Replaces the long-lived ssh+python wrapper (`scripts/render_qwen_remote.sh`)
that broke whenever the ssh connection flapped.

## Endpoints

- `POST /render` — multipart upload of (`manifest.json`, `phase3_episode.json`,
  `ref_source.mp3`) plus a `run_id` form field. Idempotent by sha256 over the
  three input files plus the renderer code rev. Returns `{"job": ..., "existing": false}` (201) for a new job, or `{"existing": true}` (200) when the same inputs hit a previous job.
- `GET /jobs` — list jobs, newest first.
- `GET /jobs/{id}` — job status, progress blob, error.
- `GET /jobs/{id}/result/{name}` — `episode.wav` / `episode.json` / `segment_NN.wav`. 409 until the job has succeeded.
- `GET /jobs/{id}/log` — captured render log (text/plain).
- `DELETE /jobs/{id}` — cancel queued/running, or remove a finished record.

All endpoints require `Authorization: Bearer $TOKEN`.

## Deploy from a workstation

```bash
# 1. Sync the repo:
rsync -a --delete \
      --exclude=.venv --exclude=.git --exclude='data/runs' \
      --exclude='reports' --exclude='.dvc' \
      ./ cbrew@pop-os.local:/home/cbrew/bleakhouse-qwen-tts/

# 2. Sync deps on pop-os:
ssh cbrew@pop-os.local 'cd /home/cbrew/bleakhouse-qwen-tts && uv sync'

# 3. Install the service (idempotent):
ssh -t cbrew@pop-os.local 'sudo bash /home/cbrew/bleakhouse-qwen-tts/experiments/qwen_tts_server/install.sh'

# 4. Pull the token to the Mac:
mkdir -p ~/.config/qwen-tts
ssh cbrew@pop-os.local 'sudo cat /etc/qwen-tts-server/token' > ~/.config/qwen-tts/token
chmod 600 ~/.config/qwen-tts/token
```

## Operate

```bash
ssh cbrew@pop-os.local 'sudo journalctl -u qwen-tts-server -f'
ssh cbrew@pop-os.local 'sudo systemctl restart qwen-tts-server'
ssh cbrew@pop-os.local 'sudo cat /etc/qwen-tts-server/token'
```

## Use from the workstation

```bash
# canonical entrypoint — same usage as before:
bash scripts/render_qwen_remote.sh <run_id> [--ref-source <path>]
```

The bash shim now delegates to `scripts/render_qwen_via_http.py`, which uses
discrete polled HTTP requests. wifi flaps and laptop sleep no longer kill an
in-flight render.
