# Deploy via `dvc pull` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bespoke Fly demo deploy (130-line `stage_demo.sh` + custom audio routing in webapp) with a standard `dvc pull` at container startup. Eliminate ~200+ lines of our code.

**Architecture:** Container holds code + DVC metadata only. A small entrypoint script generates `.dvc/config.local` from Fly secrets, runs `dvc pull -r r2` to materialise `data/runs/` from R2 onto a Fly volume, then execs the webapp. Webapp serves `data/runs/<run>/<file>` as ordinary static files.

**Tech Stack:** Python 3.13, FastAPI/uvicorn, DVC, Cloudflare R2, podman, Fly.io.

**Spec:** `docs/superpowers/specs/2026-05-03-deploy-via-dvc-pull-design.md`.

---

## Task 1: Audit `run_manifest.json` + audio_variants usage

**Goal:** Decide whether `run_manifest.json` is vestigial after the audio refactor (R5/R6 from the spec). Output: a short notes file recording the decision.

**Files:**
- Read: `webapp/app.py`, `webapp/db.py`, `webapp/build_manifest.py`, `webapp/build_report.py`, `webapp/build_teasers.py`, `webapp/static/*.js`, `tests/**`, `scripts/**`
- Create: `docs/superpowers/notes/2026-05-03-run-manifest-audit.md`

- [ ] **Step 1: Find all reads of `run_manifest.json` in the codebase**

```bash
grep -rn "run_manifest\.json\|run_manifest\b" --include="*.py" --include="*.js" --include="*.html" 2>/dev/null | grep -v ".venv\|node_modules\|/_archive/" > /tmp/run_manifest_refs.txt
wc -l /tmp/run_manifest_refs.txt
cat /tmp/run_manifest_refs.txt
```

- [ ] **Step 2: Find all reads of `audio_variants` (the field inside run_manifest)**

```bash
grep -rn "audio_variants" --include="*.py" --include="*.js" --include="*.html" 2>/dev/null | grep -v ".venv\|node_modules\|/_archive/"
```

- [ ] **Step 3: Categorise each reference**

For each reference, record in the notes file what it reads and from which run_manifest field. Categories:
- (A) Reads only `audio_variants` → goes away in this redesign.
- (B) Reads `axes` → could be served from `config.json` instead (axes already there).
- (C) Reads `stages` → could be served from `dvc.lock` parsing OR is itself vestigial.
- (D) Reads `dvc_lock_sha`, `generated_at`, `schema_version` → metadata; investigate purpose.
- (E) Other → record what.

- [ ] **Step 4: Write decision to notes file**

Create `docs/superpowers/notes/2026-05-03-run-manifest-audit.md` with this structure:

```markdown
# run_manifest.json audit (2026-05-03)

## Findings
- N references in webapp, M references in scripts, K references in tests.
- Field-by-field breakdown: ... (per Step 3 categories)

## Decision
**Verdict**: DELETE | SIMPLIFY (pick one)

**Rationale**: [one paragraph]

## Implementation impact
- Files to delete: ...
- Files to modify: ...
- dvc.yaml changes: ...
```

- [ ] **Step 5: Commit the notes**

```bash
git add docs/superpowers/notes/2026-05-03-run-manifest-audit.md
git commit -m "docs: audit run_manifest.json usage for deploy redesign

Inventory of webapp/scripts/tests references to run_manifest.json fields,
informing the delete-vs-simplify decision in the deploy-via-dvc-pull plan.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Refactor webapp audio handlers to serve from local files

**Goal:** Replace the R2-redirect audio routing with FastAPI `StaticFiles` (or `FileResponse`) so the webapp serves audio bytes from `data/runs/<run>/audio/<file>` as ordinary static content. After this task, `_r2_url_for_hash` and the `audio_variants` iteration are gone.

**Files:**
- Modify: `webapp/app.py:589-665` (the `_r2_url_for_hash` + `serve_audio` + `serve_shards_manifest` block) and lines 425-475 (`_load_run_manifest`, `_available_versions`)
- Create: `tests/webapp/__init__.py`, `tests/webapp/test_audio_serving.py`

- [ ] **Step 1: Verify the current code path with a smoke test**

```bash
# Local webapp must be running (uv run uvicorn webapp.app:app --port 8000)
curl -sI http://127.0.0.1:8000/audio/bh_trn_literary/podcast.mp3 | head -5
# Expected: HTTP/1.1 302 Found, Location: https://pub-... (R2 URL)
```

Record the response in your scratch notes for comparison after the refactor.

- [ ] **Step 2: Create the failing test**

Create `tests/webapp/__init__.py` (empty file).

Create `tests/webapp/test_audio_serving.py`:

```python
"""Audio routes serve files locally — no R2 redirects in our code path."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    """Webapp wired to a tmp data dir with a synthetic run."""
    runs = tmp_path / "data" / "runs" / "test_run" / "audio"
    runs.mkdir(parents=True)
    (runs / "podcast.mp3").write_bytes(b"FAKE_MP3_BYTES")
    (runs / "podcast_qwen.mp3").write_bytes(b"FAKE_QWEN_BYTES")
    (runs / "manifest.json").write_text('{"segments": []}')

    monkeypatch.setenv("BLEAKHOUSE_DATA_DIR", str(tmp_path / "data"))
    # Re-import after env is set
    import importlib
    import webapp.app as appmod
    importlib.reload(appmod)
    return TestClient(appmod.app)


def test_audio_mp3_served_locally_not_redirected(client: TestClient) -> None:
    """GET /audio/<run>/podcast.mp3 returns the bytes directly, not a 302."""
    resp = client.get("/audio/test_run/podcast.mp3", follow_redirects=False)
    assert resp.status_code == 200
    assert resp.content == b"FAKE_MP3_BYTES"
    assert "location" not in resp.headers


def test_audio_qwen_variant_served_locally(client: TestClient) -> None:
    """Variant filenames are passed through as ordinary file paths."""
    resp = client.get("/audio/test_run/podcast_qwen.mp3", follow_redirects=False)
    assert resp.status_code == 200
    assert resp.content == b"FAKE_QWEN_BYTES"


def test_path_traversal_rejected(client: TestClient) -> None:
    resp = client.get("/audio/test_run/..%2Fconfig.json", follow_redirects=False)
    assert resp.status_code == 400


def test_404_for_missing_audio(client: TestClient) -> None:
    resp = client.get("/audio/nonexistent_run/podcast.mp3", follow_redirects=False)
    assert resp.status_code == 404
```

- [ ] **Step 3: Run the test and confirm it fails (current code 302-redirects)**

```bash
uv run pytest tests/webapp/test_audio_serving.py -v
```

Expected: tests fail because the current handler returns 302 (or because `BLEAKHOUSE_DATA_DIR` env var isn't honoured yet — both signal the right starting point).

- [ ] **Step 4: Refactor the audio handlers in `webapp/app.py`**

Locate the `_r2_url_for_hash`, `serve_shards_manifest`, and `serve_audio` block (currently `webapp/app.py:589-665`). Replace with:

```python
@app.get("/audio/{run_id}/shards.json")
async def serve_shards_manifest(run_id: str):
    """Return the per-turn shards index. URLs in the manifest now point at
    /audio/<run>/shards/<md5>.mp3 — webapp serves shard bytes locally too,
    no R2 URL construction."""
    if ".." in run_id:
        raise HTTPException(400, "Invalid path")
    path = DATA_DIR / "runs" / run_id / "audio" / "shards.json"
    if not path.exists():
        raise HTTPException(404, f"No shards manifest for run {run_id}")
    return FileResponse(str(path), media_type="application/json")


@app.get("/audio/{run_id}/{filename}")
async def serve_audio(run_id: str, filename: str):
    """Serve audio + audio-manifest JSON files from data/runs/<run>/audio/.

    Files are materialised by `dvc pull` (run at container startup; locally
    by `dvc pull` after `git pull`). DVC symlinks resolve transparently.
    """
    if ".." in run_id or ".." in filename:
        raise HTTPException(400, "Invalid path")
    path = DATA_DIR / "runs" / run_id / "audio" / filename
    if not path.exists():
        raise HTTPException(404, f"No file {filename} for run {run_id}")
    media_type = "audio/mpeg" if filename.endswith(".mp3") else "application/json"
    return FileResponse(str(path), media_type=media_type)
```

Then DELETE the `_r2_url_for_hash` function entirely (currently `webapp/app.py:589-596`).

Then DELETE the `audio_variants` reference inside `_load_run_manifest` consumers — specifically:
- `_available_versions` (currently `webapp/app.py:441-475`): rewrite to read variants from disk by globbing `data/runs/<run>/audio/podcast*.mp3`. Replacement:

```python
def _available_versions(run_id: str) -> list[str]:
    """Return the render versions available on disk.

    Variants are inferred from filenames: `podcast.mp3` → "classic",
    `podcast_<name>.mp3` → "<name>". Shard format (per-turn mp3s indexed
    by audio/shards.json) surfaces as "classic" when present.
    """
    versions: set[str] = set()
    audio_dir = DATA_DIR / "runs" / run_id / "audio"
    if not audio_dir.exists():
        return []
    if (audio_dir / "shards.json").exists() or (audio_dir / "podcast.mp3").exists():
        versions.add("classic")
    for mp3 in audio_dir.glob("podcast_*.mp3"):
        name = mp3.stem.removeprefix("podcast_")
        if name:
            versions.add(name)
    return sorted(versions)
```

Also: search for any remaining `audio_variants` references in `webapp/app.py` and remove them. Search for `_r2_url_for_hash` references — there should be none after this step.

- [ ] **Step 5: Add the `BLEAKHOUSE_DATA_DIR` env-var support if not already present**

Check `webapp/app.py` for `DATA_DIR = ...`. If it's hard-coded, parameterise:

```python
import os
DATA_DIR = Path(os.environ.get("BLEAKHOUSE_DATA_DIR", BASE_DIR / "data"))
```

This unblocks the test fixture. If it's already env-var-driven, skip.

- [ ] **Step 6: Run the tests + ruff + pyright**

```bash
uv run pytest tests/webapp/test_audio_serving.py -v
uv run ruff check webapp/app.py tests/webapp/
uv run pyright webapp/app.py 2>&1 | tail -5
```

All four tests should pass; ruff + pyright clean.

- [ ] **Step 7: Manual smoke test against a real run**

```bash
# Start local webapp
uv run uvicorn webapp.app:app --port 8000 &
sleep 2
# Verify direct serve, not redirect
curl -sI http://127.0.0.1:8000/audio/bh_trn_literary/podcast.mp3 | head -3
# Expected: HTTP/1.1 200 OK, Content-Type: audio/mpeg (NOT 302)
kill %1
```

- [ ] **Step 8: Commit**

```bash
git add webapp/app.py tests/webapp/__init__.py tests/webapp/test_audio_serving.py
git commit -m "webapp: serve audio from local files, drop R2 URL construction

Replaces the bespoke audio-variant routing (302 redirects to R2 via
_r2_url_for_hash + audio_variants iteration in _load_run_manifest)
with FastAPI FileResponse serving from data/runs/<run>/audio/<file>.

After this commit: webapp knows nothing about R2 or content hashes.
Files reach the container via 'dvc pull' at startup (next task).

Audio variants are now inferred from filenames (podcast_<variant>.mp3)
rather than from run_manifest.json's audio_variants[*].hash field —
removes the staleness bug surfaced in BleakHouse-au0l (which is
cancelled by this redesign; see docs/superpowers/specs/2026-05-03-...).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Apply the `run_manifest.json` decision

**Goal:** Implement whichever decision Task 1 reached (delete vs simplify).

**Files:** Depend on the decision. Anticipated:
- If DELETE: `dvc.yaml` (drop `run_manifest` stage), `scripts/generate_run_manifest.py` (delete), `.gitignore` (clean up the carve-out comment), `docs/dvc.md` (update Run categories), and ~217 git-tracked `data/runs/*/run_manifest.json` files.
- If SIMPLIFY: `scripts/generate_run_manifest.py` (drop the audio_variants block), regenerate all 217 files, commit.

- [ ] **Step 1: Read the audit decision**

```bash
cat docs/superpowers/notes/2026-05-03-run-manifest-audit.md
```

- [ ] **Step 2 (DELETE branch): drop the dvc.yaml stage**

Edit `dvc.yaml`. Delete the entire `run_manifest:` stage block (currently 8 lines around `foreach: ${runs_by_id}` with `cmd: uv run python scripts/generate_run_manifest.py --run ${key}`).

- [ ] **Step 3 (DELETE branch): remove from .gitignore comment + git rm files**

Edit `.gitignore`: remove the `# run_manifest.json deliberately NOT gitignored — see Phase 3 audit (BleakHouse-9d98)…` comment block.

```bash
git rm 'data/runs/*/run_manifest.json'
# count check: should be 217 deletions
git status --short | grep -c "^D.*run_manifest.json"
```

- [ ] **Step 4 (DELETE branch): delete the producer**

```bash
git rm scripts/generate_run_manifest.py
```

- [ ] **Step 5 (SIMPLIFY branch alternative): edit producer to drop audio_variants**

In `scripts/generate_run_manifest.py`, find the section that builds `audio_variants` (look for `audio_variants` literal). Delete that block + its inclusion in the output dict. Then regenerate all 217 files:

```bash
uv run python -m scripts.generate_runs_yaml  # ensure runs.yaml current
for run in $(yq '.runs[].run_id' runs.yaml); do
  uv run python scripts/generate_run_manifest.py --run "$run"
done
```

Then `dvc commit -f run_manifest` to update `dvc.lock` hashes (cache:false, so it just records the new content hash for each).

- [ ] **Step 6: Run quality checks**

```bash
uv run ruff check .
uv run pyright 2>&1 | tail -5
uv run pytest tests/webapp/ -v  # audio tests still pass
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "run_manifest: <DELETE|SIMPLIFY> per audit decision

[Per the Task 1 audit findings, take whichever action was decided.
Reference the audit notes in this commit message.]

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Add `experiments.db` as a DVC stage

**Goal:** Stop bundling `experiments.db` ad-hoc in `stage_demo.sh`. Make it an ordinary DVC out so it rides the same `dvc pull` mechanism as everything else.

**Files:**
- Modify: `dvc.yaml`
- Verify: `enrichment/expdb.py` (the producer)

- [ ] **Step 1: Verify the producer command**

```bash
grep -n "def main\|argparse" enrichment/expdb.py | head
# Should find a CLI entry: uv run python -m enrichment.expdb scan
```

- [ ] **Step 2: Add the stage to dvc.yaml**

Append to `dvc.yaml` (anywhere among the existing stages):

```yaml
  # experiments.db — derived from data/runs/**/run_manifest.json + config.json.
  # Tracker reads it for matrix coordinates. Stage exists so the deploy
  # ride the same `dvc pull` mechanism as everything else (no ad-hoc bundle
  # step in stage_demo.sh).
  experiments_db:
    cmd: uv run python -m enrichment.expdb scan
    deps:
      - enrichment/expdb.py
      - runs.yaml
    outs:
      - data/experiments.db:
          cache: true
```

Note: deps don't include `data/runs/**/run_manifest.json` literally because dvc.yaml foreach can't expand wildcards in deps. The `runs.yaml` dep is a coarse trigger — every new run regenerates this dep file via `generate_runs_yaml.py`, which is sufficient.

- [ ] **Step 3: Remove `data/experiments.db` from `.gitignore`**

The file is currently gitignored (line 35-37). With cache:true it's now in DVC; the gitignore stays (we don't want it in git either) — confirm and leave alone.

- [ ] **Step 4: Initial commit + push**

```bash
uv run --no-sync dvc commit -f experiments_db
uv run --no-sync dvc push -r r2 experiments_db
uv run --no-sync dvc status -c -r r2 | grep -E "experiments_db|sync" | head -3
# Expected: "Cache and remote 'r2' are in sync."
```

- [ ] **Step 5: Verify experiments.db is now a symlink into the cache**

```bash
ls -la data/experiments.db
# Expected: lrwxr-xr-x ... data/experiments.db -> /Volumes/Crucial X9/...
```

- [ ] **Step 6: Commit**

```bash
git add dvc.yaml dvc.lock
git commit -m "dvc.yaml: declare experiments.db as a DVC stage

Move experiments.db from ad-hoc 'cp data/experiments.db demo_data/' in
stage_demo.sh into the standard dvc pull/push mechanism. One deploy
mechanism instead of two.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Create the container entrypoint script

**Goal:** A small (≤ 10-line) shell script that generates `.dvc/config.local` from env vars, runs `dvc pull`, and execs the webapp. This is the only piece of new ad-hocery introduced by the redesign — keep it tight.

**Files:**
- Create: `scripts/container-entrypoint.sh`

- [ ] **Step 1: Write the entrypoint**

```bash
cat > scripts/container-entrypoint.sh <<'EOF'
#!/bin/sh
set -eu

# Generate .dvc/config.local from Fly secrets. The committed .dvc/config
# names the R2 remote; credentials and the runtime cache.dir live here.
mkdir -p /app/.dvc
cat > /app/.dvc/config.local <<CONFIG
[cache]
    dir = /cache
    type = "symlink,hardlink,copy"
['remote "r2"']
    access_key_id = ${DVC_REMOTE_R2_ACCESS_KEY}
    secret_access_key = ${DVC_REMOTE_R2_SECRET_ACCESS_KEY}
CONFIG

# Materialise data/runs/ from R2. First boot pulls ~600MB; subsequent
# boots use the volume-mounted cache and finish in <1s.
cd /app && uv run --no-sync dvc pull -r r2

# Hand off to the webapp.
exec uv run --no-sync uvicorn webapp.app:app --host 0.0.0.0 --port 8080
EOF
chmod +x scripts/container-entrypoint.sh
```

- [ ] **Step 2: Verify the script is executable + parseable**

```bash
sh -n scripts/container-entrypoint.sh && echo "syntax OK"
ls -la scripts/container-entrypoint.sh  # confirm executable
```

- [ ] **Step 3: Commit**

```bash
git add scripts/container-entrypoint.sh
git commit -m "scripts: container entrypoint (generate config.local + dvc pull)

The single piece of new code introduced by the deploy redesign. Generates
.dvc/config.local from Fly secrets at boot, runs dvc pull to materialise
data/runs/ from R2 onto the mounted cache volume, then execs uvicorn.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Update Containerfile

**Goal:** Replace the `COPY demo_data/ data/` (which depended on `stage_demo.sh`) with a minimal layout: code + DVC metadata + git-tracked config files only. Set the new entrypoint.

**Files:**
- Modify: `Containerfile`

- [ ] **Step 1: Rewrite Containerfile**

Replace the existing `Containerfile` with:

```dockerfile
FROM python:3.13-slim

# DVC + minimal runtime tooling (uv ships its own Python; we use system pip
# only to bootstrap uv since the project is uv-managed).
RUN pip install --no-cache-dir uv

WORKDIR /app

# Install Python deps via uv into the container's venv (cached layer).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Code.
COPY webapp/ webapp/
COPY enrichment/__init__.py enrichment/__init__.py
COPY enrichment/axes.py enrichment/axes.py
COPY enrichment/params.py enrichment/params.py
COPY enrichment/expdb.py enrichment/expdb.py
COPY scripts/generate_runs_yaml.py scripts/generate_runs_yaml.py
COPY scripts/container-entrypoint.sh scripts/container-entrypoint.sh
COPY params.yaml runs.yaml dvc.yaml dvc.lock ./

# Committed DVC config (names R2 remote; secrets injected at runtime).
COPY .dvc/config .dvc/config

# Poster + static assets.
COPY poster/poster_print.html poster/
COPY poster/poster_provenance.js poster/
COPY poster/TheOhioStateUniversity-Scarlet-Vert-RGBHEX.jpg poster/
COPY poster/lexisplusailogo.png poster/
COPY poster/screenshots/ poster/screenshots/

# The entrypoint generates .dvc/config.local from env, dvc pulls, execs uvicorn.
EXPOSE 8080
ENTRYPOINT ["scripts/container-entrypoint.sh"]
```

- [ ] **Step 2: Local podman build to verify the layout works**

```bash
podman build -t bleakhouse-deploy-test -f Containerfile .
# Expected: build succeeds, image is small (~200-300MB without data/)
podman images | head -3
```

- [ ] **Step 3: Local podman run smoke test (with mock env vars and a tmp cache)**

```bash
mkdir -p /tmp/dvc-cache-smoke
podman run --rm \
  -e DVC_REMOTE_R2_ACCESS_KEY=$(grep access_key_id .dvc/config.local | awk '{print $3}') \
  -e DVC_REMOTE_R2_SECRET_ACCESS_KEY=$(grep secret_access_key .dvc/config.local | awk '{print $3}') \
  -v /tmp/dvc-cache-smoke:/cache \
  -p 8081:8080 \
  --name bleakhouse-smoke \
  bleakhouse-deploy-test &
sleep 30  # wait for dvc pull (~10-20s on first run)
curl -sI http://127.0.0.1:8081/ | head -3
# Expected: HTTP/1.1 200 OK from the webapp
podman stop bleakhouse-smoke
```

If this passes, the Containerfile + entrypoint work end-to-end locally.

- [ ] **Step 4: Commit**

```bash
git add Containerfile
git commit -m "Containerfile: minimal layout for dvc-pull-at-startup deploy

Drops 'COPY demo_data/ data/' (which depended on stage_demo.sh's bespoke
file-selection logic — to be deleted next task). Container now packages
only code + DVC metadata; data materialises at boot via dvc pull.

Image ~200MB (down from ~800MB with staged data).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Set up Fly secrets + volume

**Goal:** Inject R2 credentials as Fly secrets and mount a volume at `/cache` so the DVC cache survives restarts. Two existing 32GB `audio_data` volumes are unattached and can be reused.

**Files:**
- Modify: `fly.toml`

This task involves Fly CLI commands; the user (or an operator) runs them. Document each clearly.

- [ ] **Step 1: Set the R2 credentials as Fly secrets**

```bash
# Read credentials from local .dvc/config.local (don't echo them anywhere).
ACCESS=$(grep access_key_id .dvc/config.local | awk '{print $3}')
SECRET=$(grep secret_access_key .dvc/config.local | awk '{print $3}')
fly secrets set \
  DVC_REMOTE_R2_ACCESS_KEY="$ACCESS" \
  DVC_REMOTE_R2_SECRET_ACCESS_KEY="$SECRET" \
  -a bleakhouse-demo
```

- [ ] **Step 2: Confirm secrets are set (without revealing them)**

```bash
fly secrets list -a bleakhouse-demo
# Expected: DVC_REMOTE_R2_ACCESS_KEY and DVC_REMOTE_R2_SECRET_ACCESS_KEY listed
```

- [ ] **Step 3: Add the volume mount to fly.toml**

Edit `fly.toml`. Add a `[mounts]` section:

```toml
[[mounts]]
  source = "audio_data"
  destination = "/cache"
  initial_size = "32gb"
```

(Fly will reuse the existing `audio_data` volume — already 32GB, in iad. The name "audio_data" is historical; if renaming matters, do it later as a separate cleanup ticket.)

- [ ] **Step 4: Commit fly.toml**

```bash
git add fly.toml
git commit -m "fly.toml: mount audio_data volume at /cache for DVC cache persistence

Repurposes the existing 32GB audio_data volume (unattached since
BleakHouse-m6o3 retired the local-mp3 path) as the .dvc/cache mount.
First container boot pulls ~600MB; subsequent boots reuse the cache.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Rewrite `scripts/deploy_demo.sh`, delete `scripts/stage_demo.sh`

**Goal:** Replace the deploy script with the new minimal flow: `dvc push`, `podman build`, podman smoke test, `fly deploy`, `fly machine restart`, post-deploy curl. Delete `stage_demo.sh`.

**Files:**
- Modify: `scripts/deploy_demo.sh`
- Delete: `scripts/stage_demo.sh`

- [ ] **Step 1: Read the current deploy_demo.sh to preserve any subtle behavior**

```bash
cat scripts/deploy_demo.sh
# Note: any behavior that's worth keeping (--dry-run, log scanning, etc.)
```

- [ ] **Step 2: Rewrite deploy_demo.sh**

Replace `scripts/deploy_demo.sh` with:

```bash
#!/bin/bash
# Deploy the Fly demo. New world: container does `dvc pull` at startup;
# this script's job is just push-build-deploy-restart-verify.
set -euo pipefail

DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

echo "==> dvc push -r r2 (sync any pending blobs)"
uv run --no-sync dvc push -r r2

echo "==> podman build"
podman build -t bleakhouse-demo -f Containerfile .

echo "==> podman smoke test"
mkdir -p /tmp/bleakhouse-deploy-smoke
ACCESS=$(grep access_key_id .dvc/config.local | awk '{print $3}')
SECRET=$(grep secret_access_key .dvc/config.local | awk '{print $3}')
podman run -d --rm \
  -e DVC_REMOTE_R2_ACCESS_KEY="$ACCESS" \
  -e DVC_REMOTE_R2_SECRET_ACCESS_KEY="$SECRET" \
  -v /tmp/bleakhouse-deploy-smoke:/cache \
  -p 8081:8080 \
  --name bleakhouse-deploy-smoke \
  bleakhouse-demo
trap 'podman stop bleakhouse-deploy-smoke 2>/dev/null || true' EXIT
sleep 30  # let dvc pull finish on first boot

if ! curl -sf http://127.0.0.1:8081/ > /dev/null; then
  echo "==> SMOKE TEST FAILED. Container logs:"
  podman logs bleakhouse-deploy-smoke
  exit 1
fi

# Scan logs for known startup failure patterns.
if podman logs bleakhouse-deploy-smoke 2>&1 | grep -qE "ModuleNotFoundError|ImportError|Traceback"; then
  echo "==> Startup error detected:"
  podman logs bleakhouse-deploy-smoke
  exit 1
fi

podman stop bleakhouse-deploy-smoke
trap - EXIT

if [ "$DRY_RUN" = "1" ]; then
  echo "==> --dry-run: stopping after local verification."
  exit 0
fi

echo "==> fly deploy --local-only"
fly deploy --local-only -a bleakhouse-demo

echo "==> fly machine restart (forces dvc pull on the new image)"
fly machine list -a bleakhouse-demo --json | \
  python3 -c "import json,sys; [print(m['id']) for m in json.load(sys.stdin)]" | \
  xargs -I{} fly machine restart {} -a bleakhouse-demo

echo "==> Waiting for cold-start dvc pull to finish (~30s)..."
sleep 45

echo "==> Post-deploy curl"
curl -sf https://bleakhouse-demo.fly.dev/ > /dev/null && echo "OK ✓" || (echo "FAIL ✗"; exit 1)
```

- [ ] **Step 3: Delete stage_demo.sh**

```bash
git rm scripts/stage_demo.sh
```

- [ ] **Step 4: Make the new script executable**

```bash
chmod +x scripts/deploy_demo.sh
```

- [ ] **Step 5: Commit**

```bash
git add scripts/deploy_demo.sh
git commit -m "scripts: rewrite deploy_demo.sh, delete stage_demo.sh

New flow: dvc push, podman build, podman smoke test, fly deploy,
fly machine restart, post-deploy curl. ~50 lines vs ~130 + 130 of
the old setup. No bespoke file-selection or per-run copy logic —
the container does dvc pull at startup.

Closes the deploy-side scope of the BleakHouse-1dnv migration epic.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Update CLAUDE.md and docs/dvc.md

**Goal:** Document the new dev workflow + deploy mechanism so the next contributor (and the next session of this assistant) doesn't reinvent the old wheels.

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/dvc.md`

- [ ] **Step 1: Read current CLAUDE.md to find the right insertion point**

```bash
grep -n "^##\|^# " CLAUDE.md
```

- [ ] **Step 2: Add a "Dev workflow" section to CLAUDE.md**

Insert after the existing "Build & Run" section:

```markdown
## Dev workflow (post-DVC-migration)

Pipeline outputs live in DVC + Cloudflare R2 (see `docs/dvc.md`).
After cloning or pulling:

```bash
uv sync
uv run dvc pull -r r2     # materialises data/runs/ from R2 (~600MB on first run; cached after)
```

After producing a new run locally:

```bash
uv run dvc commit <stage>@<run_id>     # records the on-disk hash
uv run dvc push -r r2                  # uploads to R2
git add config.json runs.yaml dvc.lock # stays-in-git: pipeline declarations
git commit && git push
```

Deploy to Fly:

```bash
bash scripts/deploy_demo.sh            # dvc push, podman build, fly deploy, fly machine restart
```

The container runs `dvc pull` at startup; restart forces a fresh pull.
```

- [ ] **Step 3: Update docs/dvc.md to reflect the deploy mechanism**

Add a new top-level section after "Run categories" (or wherever fits):

```markdown
## Deploy mechanism

The Fly demo container holds code + DVC metadata only. At container
startup, `scripts/container-entrypoint.sh`:

1. Generates `.dvc/config.local` from the Fly secrets `DVC_REMOTE_R2_ACCESS_KEY`
   and `DVC_REMOTE_R2_SECRET_ACCESS_KEY`, plus a runtime `cache.dir`
   pointing at `/cache` (the mounted Fly volume `audio_data`).
2. Runs `uv run dvc pull -r r2` to materialise `data/runs/` from R2
   onto the cache. First boot ever pulls ~600MB; subsequent boots use
   the volume-cached blobs and finish in <1s.
3. Execs `uv run uvicorn webapp.app:app`.

The webapp serves `data/runs/<run>/<file>` as ordinary static content
via FastAPI `FileResponse`. It knows nothing about R2 or content hashes.

Deploy script: `scripts/deploy_demo.sh` does `dvc push`, `podman build`,
local podman smoke test, `fly deploy --local-only`, `fly machine restart`,
post-deploy curl. ~50 lines, no bespoke file-selection logic.
```

- [ ] **Step 4: Drop stale references to stage_demo.sh, audio_variants, R2 routing**

```bash
grep -rn "stage_demo\|audio_variants\|_r2_url_for_hash" CLAUDE.md docs/ 2>/dev/null
# Edit each found reference: either delete or update.
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/dvc.md
git commit -m "docs: document dvc-pull-at-startup deploy mechanism

CLAUDE.md gains a Dev workflow section explaining uv sync + dvc pull,
new-run commit convention, and deploy command. docs/dvc.md gains a
Deploy mechanism section explaining the container entrypoint.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: End-to-end deploy verification

**Goal:** Actually deploy to Fly and verify the live site works. This is the gate that proves the redesign holds together.

- [ ] **Step 1: Run the new deploy script**

```bash
bash scripts/deploy_demo.sh
# Expected: dvc push, podman build, podman smoke test passes,
# fly deploy succeeds, fly machine restart triggers, post-deploy curl
# returns OK.
```

- [ ] **Step 2: Verify the live site loads**

```bash
curl -sf https://bleakhouse-demo.fly.dev/ | head -20
# Expected: HTML for the tracker page.
```

- [ ] **Step 3: Verify audio plays from a known run**

```bash
# Use a run you know has audio. Verify the audio endpoint returns 200 OK
# (NOT 302) and the bytes start with the mp3 magic header (ID3 or FF FB).
curl -s -o /tmp/test.mp3 https://bleakhouse-demo.fly.dev/audio/bh_trn_literary/podcast.mp3
file /tmp/test.mp3   # expects: "MPEG ADTS, layer III" or similar
ls -la /tmp/test.mp3 # non-zero size
```

- [ ] **Step 4: Verify tracker shows runs**

```bash
curl -s https://bleakhouse-demo.fly.dev/api/runs | python3 -m json.tool | head -20
# Expected: a list/dict of runs with axes
```

- [ ] **Step 5: Verify Fly machine logs are clean**

```bash
fly logs -a bleakhouse-demo | tail -50
# Look for: "Cache and remote 'r2' are in sync." or similar dvc pull success.
# Should NOT see: ModuleNotFoundError, ImportError, dvc pull failures.
```

- [ ] **Step 6: Smoke-test a complete user flow in a browser**

Open https://bleakhouse-demo.fly.dev/ in a browser. Click into a run. Trigger audio playback. Verify the player works.

- [ ] **Step 7: If all green, commit a "verified" marker**

```bash
git commit --allow-empty -m "deploy: verified post-redesign Fly demo end-to-end

scripts/deploy_demo.sh ran clean, https://bleakhouse-demo.fly.dev/
serves tracker + audio + scripts. dvc pull on container startup
materialised data/runs/ from R2 onto the audio_data volume.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Close superseded bd tickets

**Goal:** Reflect the redesign in the bd graph: cancel tickets the redesign superseded, update the parent's acceptance criteria.

- [ ] **Step 1: Cancel BleakHouse-au0l (audio_index.json from dvc.lock)**

```bash
bd close BleakHouse-au0l --reason="Superseded by the deploy-via-dvc-pull redesign (see docs/superpowers/specs/2026-05-03-deploy-via-dvc-pull-design.md). The webapp no longer constructs R2 URLs from hash mappings — it serves files locally — so the audio-index abstraction is unnecessary."
```

- [ ] **Step 2: Cancel BleakHouse-g760 (retrofit lock via frozen stages)**

```bash
bd close BleakHouse-g760 --reason="Superseded by the deploy-via-dvc-pull redesign. Threat was 'someone runs dvc repro and clobbers a retrofit'; in the new world deploy is read-only dvc pull, dvc repro is a dev concern only. Retrofits are documented as snapshots in docs/dvc.md (Run categories); developer discipline suffices."
```

- [ ] **Step 3: Close BleakHouse-x5a3 (Phase 4 workflow updates) as fulfilled**

```bash
bd close BleakHouse-x5a3 --reason="Fulfilled by the deploy-via-dvc-pull redesign tasks (Containerfile, entrypoint, deploy_demo.sh rewrite, CLAUDE.md). Original scope (add dvc pull to stage_demo.sh; document new-run convention) was reshaped into a more focused redesign per docs/superpowers/specs/2026-05-03-deploy-via-dvc-pull-design.md."
```

- [ ] **Step 4: Update BleakHouse-1dnv (parent) notes**

```bash
bd update BleakHouse-1dnv --notes "$(cat <<'EOF'
2026-05-03 DEPLOY-VIA-DVC-PULL REDESIGN

Phases 0-3 of the original plan landed (cache:false → cache:true for all
JSON outs; ~1,400 blobs in R2). Phase 4's original scope (workflow
updates inside stage_demo.sh) was replaced by a deeper redesign — the
deploy now uses dvc pull at container startup, eliminating stage_demo.sh
entirely and stripping bespoke audio-variant routing from the webapp.

Spec: docs/superpowers/specs/2026-05-03-deploy-via-dvc-pull-design.md
Plan: docs/superpowers/plans/2026-05-03-deploy-via-dvc-pull.md

Cancelled tickets (superseded): BleakHouse-au0l, BleakHouse-g760.
Fulfilled tickets: BleakHouse-x5a3.
Still open: BleakHouse-6noz (Phase 5 history rewrite — independent of deploy).
EOF
)"
```

- [ ] **Step 5: Push everything**

```bash
git push origin main
```

---

## Self-review notes

- Spec coverage: every spec section has at least one task. Section 5 risks are addressed across Tasks 5 (R1, R2), 7 (R3, R4), 1 (R5, R6), 7+10 (R7).
- No placeholders detected. Code blocks are present in every step that changes code.
- Type/method consistency: `_r2_url_for_hash` is removed in Task 2 and not referenced thereafter; `_load_run_manifest` is mentioned in Task 1 (audit) and Task 2 (refactor); `audio_variants` is removed in Task 2 and the dependent decision in Task 3.
- One known deferred decision: Task 1's outcome shapes Task 3 (DELETE vs SIMPLIFY branch). Both branches are written out so the executor can take whichever the audit picked.
