# Deploy via `dvc pull`: simplifying the Fly demo

**Status**: design approved 2026-05-03 (this session). Ready for implementation plan.
**Author**: brainstormed with Claude Opus 4.7 in BleakHouse session 2026-05-03.
**Supersedes parts of**: BleakHouse-1dnv (Phase 4 scope), BleakHouse-au0l, BleakHouse-g760, BleakHouse-x5a3 original scope.

## Problem

The current Fly demo deploy is bespoke and brittle:

- `scripts/stage_demo.sh` (130+ lines) computes a "demo subset" of runs from a tangle of sources (`build_matrix()`, `'interdisciplinary' in name`, `'_cerebras_' in name`, regex on `_v1_\d+$`, every label in `experiments.db`, a hand-maintained `panel_scripts` set), then copies a hand-listed set of files per run into a `demo_data/` tree, with special cases for `audio/manifest.json`, `audio/shards.json`, and `experiments.db` bundling.
- The webapp (`webapp/app.py`) has its own bespoke logic for resolving audio URLs: reads `run_manifest.json`, pulls `audio_variants[*].hash`, constructs R2 URLs as `<R2>/files/md5/<h[:2]>/<h[2:]>`, branches per variant (`classic`, `qwen`, `trevelyan_v2`).
- A latent staleness bug exists: `run_manifest.json` is a derived cache of dvc.lock hashes, but the `run_manifest` dvc stage's deps don't list `dvc.lock`, so the cache silently desynchronises after any audio re-render — and the BleakHouse-1dnv DVC migration just made dvc.lock churn vastly more often.

Net: the deploy path is a maintenance burden that grows in fragility every time the pipeline grows.

## Goal

Reduce the surface of bespoke code we maintain in the deploy path by leaning on standard tools (DVC, podman, fly) with as little improvisation as possible.

This is the user's stated principle, prioritised over alternative goals like "smallest image" or "fastest cold start."

## Architecture

```
DEV MACHINE                       FLY MACHINE
-----------                       -----------
generate run                      
   ↓                              fly machine restart
dvc commit                            ↓
   ↓                              container start
dvc push -r r2  ──────────────►  dvc pull (R2 → cache on Fly volume)
   ↓                                  ↓
git push                          symlinks under data/runs/ resolve
   ↓                                  ↓
fly deploy                        webapp serves files as static content
```

**Container** = code + `dvc.lock` + `runs.yaml` + `dvc.yaml` + `.dvc/config` (no secrets) + git-tracked `config.json` and `run_manifest.json` files. **No data**.

**Container start** = a small entrypoint script generates `.dvc/config.local` from Fly secrets, runs `dvc pull` to materialise `~600MB` into `.dvc/cache` on a mounted Fly volume (cache survives restarts), then execs the webapp.

**Webapp** = serves `data/runs/<run>/<file>` as ordinary static files. Knows nothing about R2 or content hashes. The single new moving part is the entrypoint script (3-5 lines); everything else is removal.

## Component changes

### Deleted

- `scripts/stage_demo.sh` — the demo-subset selection + per-file copy logic. ~130 lines.
- The proposed `scripts/build_audio_index.py` from BleakHouse-au0l — never written; cancel that ticket.
- Webapp R2 URL construction: `_r2_url_for_hash`, the audio_variants iteration in `_load_run_manifest`, the multi-variant routing in `/audio` handlers.
- `experiments.db` bundling step in `stage_demo.sh` — DB itself stays useful for the tracker. It rides the same `dvc pull` mechanism: declare it as a DVC out (new dvc.yaml stage with cmd `python -m enrichment.expdb scan`, deps on `data/runs/**/run_manifest.json` + the scan script). Avoids a second deploy-time mechanism.

### Simplified

- `scripts/deploy_demo.sh` — collapses to: `dvc push -r r2` (unconditional, idempotent), `podman build`, podman smoke-test (existing), `fly deploy --local-only`, `fly machine restart`, post-deploy curl check.
- `scripts/generate_run_manifest.py` + the `run_manifest` dvc stage — investigate whether it's vestigial after audio routing dies. Webapp's other uses of `run_manifest.json` may already be served by `config.json` (axes) or `dvc.lock` (stages). Outcomes:
  - **If vestigial**: delete the script, drop the dvc stage, remove the 217 git-tracked files, remove from `.gitignore`'s explicit non-ignore comment.
  - **If still needed**: strip only the `audio_variants[*].hash` block from the script's output; the staleness bug dissolves because nothing reads the audio block any more.
- `webapp/app.py` audio handlers — collapse multi-variant routing to "serve the file at this path". The webapp stops being aware of variants as a concept; the URL space (e.g., `/audio/<run_id>/podcast.mp3` vs `/audio/<run_id>/podcast_qwen.mp3`) maps directly to filenames.

### New

- **`scripts/container-entrypoint.sh`** (or named more specifically): 3-5 lines. Generates `.dvc/config.local` from `DVC_REMOTE_R2_ACCESS_KEY` / `DVC_REMOTE_R2_SECRET_ACCESS_KEY` env vars, sets `cache.dir` to the Fly volume mount path, sets `cache.type` to `symlink,hardlink,copy`, runs `uv run dvc pull -r r2`, execs the webapp.
- **`Containerfile`** changes: COPY `dvc.lock`, `dvc.yaml`, `runs.yaml`, `.dvc/config`, the git-tracked subset of `data/runs/<run>/{config,run_manifest}.json`. Set entrypoint. Omit any `data/runs/<run>/<other-files>`.
- **Fly secrets**: `DVC_REMOTE_R2_ACCESS_KEY` and `DVC_REMOTE_R2_SECRET_ACCESS_KEY` (set once via `fly secrets set ...`).
- **Fly volume mount**: cache lives on a mounted volume so it survives restarts. Likely repurpose or extend the existing audio volume; need to verify size is adequate (~1GB headroom).

### Unchanged

- DVC + R2 + Fly themselves (the standard tools doing the lifting).
- All migration work done in BleakHouse-1dnv Phases 0-3 (the JSON outs are in DVC + R2 already; this design relies on that).
- `git rm --cached` decisions: `config.json` + `run_manifest.json` stay in git (so a fresh clone can read them without `dvc pull`); everything else is DVC-managed.
- The pipeline regenerator scripts (`dvc_regenerate.py`, `generate_runs_yaml.py`, etc.) — they produce runs; they're not deploy infrastructure.

## Data flow

### Deploy (after `bash scripts/deploy_demo.sh`)

1. `dvc push -r r2` — sync any pending DVC state to R2. Idempotent.
2. `podman build -t bleakhouse-demo -f Containerfile .` — packages code + DVC metadata. Fast, no data transfer.
3. Podman smoke test — same as today: start container, curl health, scan logs for ModuleNotFoundError-style failures.
4. `fly deploy --local-only` — pushes image.
5. `fly machine restart` — Fly machines start the new image, run entrypoint, `dvc pull` populates cache, webapp starts.
6. `curl https://<app>.fly.dev/health` — verify.

### Runtime (per request)

1. Webapp receives `GET /audio/<run_id>/<file>` (or `GET /tracker`, etc.).
2. Reads `data/runs/<run_id>/<file>` from disk. The file is a symlink into `.dvc/cache` (mounted on the Fly volume).
3. Returns content. No R2 awareness, no hash construction, no per-variant routing.

### Dev workflow

- After `git pull`: `uv sync && dvc pull -r r2`. Two commands. Documented in CLAUDE.md.
- After producing a new run: `dvc commit <stage>@<run> && dvc push -r r2 && git add config.json runs.yaml dvc.lock && git commit && git push`. Run goes live on next deploy + restart.
- Local webapp: `uv run uvicorn webapp.app:app --reload` — uses local `.dvc/cache` (currently `/Volumes/Crucial X9/...`); no Fly involvement.

### Cold-start cost on Fly

- First boot ever (empty volume): `dvc pull` of ~600MB. At ~50MB/s from R2 = ~12 seconds.
- Subsequent boots (volume populated): `dvc pull` is a no-op except for changes since last pull.
- Worst case (volume disk pressure → cache eviction): re-pull. Bounded.

## Migration impact

### Cancel (work no longer needed)

- **BleakHouse-au0l** (audio_index.json from dvc.lock) — entire premise dissolved. Webapp doesn't construct R2 URLs in the new world. Close as superseded.
- **BleakHouse-g760** (retrofit lock via frozen stages) — threat was "someone runs `dvc repro` and clobbers a retrofit." In the new world, deploy is read-only `dvc pull`; `dvc repro` is a dev concern only. Plus, the ad-hoc filter machinery to lock retrofits doesn't pay for itself. Close as superseded; the docs/dvc.md "Run categories" section already documents retrofits as snapshots, which suffices.

### Reshape

- **BleakHouse-x5a3** (Phase 4: workflow updates) — old scope was "make stage_demo.sh do dvc pull; document new-run convention." New scope is "delete stage_demo.sh; rewrite Containerfile + add entrypoint + Fly secrets/volume; document new dev workflow." Bigger but more focused.
- **BleakHouse-zbj6** (Phase 6: tests + docs) — `tests/test_data_hygiene.py` still useful; the docs section grows because deploy is now central.

### Stays as planned

- **BleakHouse-6noz** (Phase 5: history rewrite via git-filter-repo) — independent of deploy; still cleans clone size.
- **BleakHouse-7nno** (niche artefacts, P3) — independent.

### New tickets (born from this redesign)

To be filed during the implementation plan stage. The umbrella replaces the original BleakHouse-x5a3 scope. Likely sub-tickets:

- Containerfile + entrypoint + Fly secrets/volume.
- Strip webapp audio-variant routing.
- Decide and act on `run_manifest.json` (delete vs simplify).
- Update CLAUDE.md with new dev + deploy workflow.
- End-to-end deploy verification.

## Risks

**R1. Container-side `.dvc/config.local` for cache + credentials.** Today, dev's `.dvc/config.local` points cache at `/Volumes/Crucial X9/...` and holds R2 credentials. Container needs a *different* config.local pointing at the Fly volume mount, with credentials sourced from Fly secrets at startup. Mitigation: entrypoint script generates it from env vars before `dvc pull`. ~5-line shell snippet.

**R2. DVC `cache.type` on Linux.** Mac uses `symlink,hardlink,copy`. Linux container should match. Set explicitly in the runtime-generated config.local; don't rely on defaults.

**R3. First-boot `dvc pull` failure modes.** R2 unreachable → container fails to start (visible in Fly logs, good). Volume full → `dvc pull` fails. Both are loud failures; worth a `fly volumes show` health check in the deploy script before redeploy.

**R4. Discipline gap: `dvc push` before `fly deploy`.** If you `git push` + `fly deploy` without first `dvc push`, the container's `dvc pull` finds dvc.lock entries that R2 doesn't have. Container fails to start. Mitigation: `deploy_demo.sh` runs `dvc push` unconditionally before `fly deploy`. Cheap; idempotent.

**R5. `run_manifest.json` decision is deferred to implementation.** This needs a real audit during implementation: grep webapp for every `run_manifest` access, decide field-by-field. Could surprise us with a non-trivial dependency.

**R6. Existing `audio_variants[*].hash` consumers outside webapp.** Need a quick grep before deletion: tracker frontend JS, external scripts, the experiments DB ingestor.

**R7. Cold-start latency on full pull (~12s).** Fly machines have a startup grace window; need to confirm pull finishes before Fly's healthcheck times out. If not, set a longer grace period via fly.toml, OR start the webapp first and return 503 while pull is running.

**R8. Cache eviction / volume pressure on Fly.** DVC doesn't evict; cache grows. Periodic `dvc gc` could keep it bounded but adds complexity. Defer; revisit if volume fills.

Acknowledged but not mitigated to closure:
- Loss of Fly volume → full re-pull. Tolerable given infrequent occurrence.
- DVC version drift between dev and container. Pin in pyproject.toml; already standard practice.

## Acceptance criteria

The redesign is "done" when:

1. `scripts/stage_demo.sh` is deleted from git; `scripts/deploy_demo.sh` no longer references it.
2. The container's entrypoint runs `dvc pull` and starts the webapp; the entrypoint script is ≤ 10 lines of shell, with no bespoke per-file logic.
3. `webapp/app.py` no longer contains `_r2_url_for_hash` or any direct R2 URL construction; audio is served as ordinary static files via the existing static-file mechanism.
4. The `run_manifest.json` audio_variants[*].hash field is either removed (preferred) or no longer read by the webapp.
5. A fresh deploy from a clean checkout reproduces the live site: `git clone`, `uv sync`, `bash scripts/deploy_demo.sh` end-to-end works without manual intervention.
6. CLAUDE.md documents the new dev workflow (`uv sync && dvc pull` after `git pull`; `dvc commit + dvc push + git push` after producing a run).
7. BleakHouse-au0l and BleakHouse-g760 are closed as superseded with cross-references to this design.
