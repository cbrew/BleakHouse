# Migrate off DVC to a small content-addressed store (CAS)

**Status**: design approved 2026-05-07. Ready for implementation plan.
**Author**: brainstormed with Claude Opus 4.7 in BleakHouse session 2026-05-07.
**Resolves**: BleakHouse-e9go.
**Supersedes**: BleakHouse-5f3x (config-driven audio root — fully absorbed).
**Related**: BleakHouse-gc2g (deferred dedupe; depends on this), BleakHouse-6bid (DVC-stale tracker signal — moot once 8.8 lands).

## Problem

DVC was a defensible early choice (git-for-data with pipelines, multi-developer sync) but doesn't fit this project's current shape:

- One developer day-to-day; cross-machine sync is rarely exercised.
- The pipeline doesn't run through DVC's executor — we have shell scripts and a Burr state machine, and `dvc.yaml` stages are mostly artifacts.
- Deployment talks to R2 directly (302 redirects from the webapp); DVC plays no runtime role.
- Most run-dir files are JSON small enough to live in git directly; only audio mp3s are genuinely large.

Concrete recurring friction:

- Symlink-as-source-of-truth complicates code. We patched `_resolve_path` in `webapp/db_views.py` because absolute Mac-local DVC paths leaked through into `hostprep_version` DB rows and broke `/api/runs/X/prep` on Fly.
- `dvc unprotect` required before any write to a DVC-tracked file (`data/experiments.db` hits this regularly).
- `dvc.lock` churns from unrelated stages; `git checkout -- dvc.lock` is documented as a workaround in CLAUDE.md.
- `dvc pull -r r2` deletes tracked files for removed stages — `deploy_demo.sh` carries a comment saying "deliberately do NOT run dvc pull here".
- DVC cache symlinks point at `/Volumes/Crucial X9`; an unplugged external drive disappears half the working tree.

Plus a recently-discovered silent-fallback bug class: `enrichment/segment_transport.py:build_passage_assignments` silently substituted empty strings for every passage's `text`/`summary`/`best_quote` when `passages_enriched.json` was missing at the legacy path. The 32 long-form runs masked it for months. CLAUDE.md's "don't do fallback options" rule isn't enforced anywhere.

## Goal

Replace the DVC + R2 storage layer with a single small CAS module addressing bytes by md5. End state: zero `.dvc` files, zero references to the `dvc` CLI in scripts, every novel-aware path resolved through one helper module. A new run on a fresh checkout reconstructs from R2 with `cas pull`; missing data fails loudly instead of producing empty popovers.

## Architecture

| Today | After |
|---|---|
| `.dvc/cache/files/md5/<prefix>/<rest>` (DVC-managed local cache) | `<BLEAKHOUSE_CAS_ROOT>/files/md5/<prefix>/<rest>` — same shape, env-var configurable |
| 33 `.dvc` sidecar files | gone |
| `dvc.yaml` + 51k-line `dvc.lock` | gone |
| Symlinks at `data/runs/*/audio/shards/<profile>/*.mp3` (absolute, into `/Volumes/Crucial X9/`) | gone — no working-tree audio entries |
| Webapp parses `dvc.lock` at startup → `_AUDIO_R2_URLS` map | Webapp scans per-run `audio/shards.json` + `audio/assets.json` → same map shape |
| `dvc add` / `dvc push` / `dvc pull` CLI | `cas.put` / `cas.push` / `cas.pull` Python calls |
| `dvc_stale_report.py`, `dvc_regenerate.py`, `dvc.yaml`-driven repro | dropped entirely; regeneration is manual via `run_pipeline.py` |

**Unchanged**: R2 bucket `not-in-our-time` and its `/files/md5/<prefix>/<rest>` layout; webapp audio routes (URL shape stays; only md5-source changes); `shards.json` schema; `BLEAKHOUSE_NOVEL` conventions.

## Components

### `cas/` package

```python
# cas/store.py
def put(path: Path) -> str          # hash, copy into CAS, return md5; idempotent
def url(md5: str) -> str            # R2 public URL
def local_path(md5: str) -> Path | None   # None if blob not in local CAS
def push(md5: str) -> None          # upload to R2 (HEAD-then-PUT); raise if blob missing locally
def pull(md5: str) -> Path          # download from R2; raise if missing remotely
def has_local(md5: str) -> bool
def has_remote(md5: str) -> bool

# cas/paths.py — centralised, novel-aware path resolution
def passages_enriched(novel: str) -> Path
def clusters_literary(novel: str) -> Path
def clusters_characters(novel: str) -> Path
def assignments(run_id: str) -> Path
def reading_list(run_id: str) -> Path
def episode(run_id: str) -> Path
def shards_manifest(run_id: str) -> Path
def audio_assets(run_id: str) -> Path
# (Final list grows during the audit pass.)
```

**Backend**: `boto3` directly (already transitively via `dvc-s3`; promoted to direct dep). Webapp does not need credentials — it serves redirects only.

**Configuration**:
- `BLEAKHOUSE_CAS_ROOT` — local cache root, default `<repo>/data/cas`
- `R2_PUBLIC_URL` — already in webapp, reused
- `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_ENDPOINT_URL` — required by writers (push/pull); not by webapp

**Error policy**:
- `cas.local_path(md5)` returns `None` (the one place "missing" is a normal state)
- Everything else raises on miss/error. No silent fallbacks.
- `cas.put` reads-and-copies (does not move/link). Caller cleans up its own temp files.

### `scripts/cas_dedupe.py` (also `python -m cas.dedupe`)

Three modes, dry-run by default; `--delete` to commit:

- `orphan-blobs` — blobs in `<CAS_ROOT>` referenced by NO manifest (re-render leftovers; ongoing)
- `legacy-dvc-cache` — entries in `.dvc/cache/files/md5/...` already present in `<CAS_ROOT>` (one-time, post-soak)
- `working-tree-dupes` — files under `data/runs/.../audio/...` whose bytes match a CAS blob (sanity check; should be zero post-migration)

Output: `<path> | md5=<hash> | size=<bytes> | reason=<mode>` plus `would free X.X GB across N files`.

### Manifests

**`shards.json`** — no schema change. Producer (`enrichment/render_audio.py`) calls `cas.put(temp_mp3) → md5` per shard and writes the md5 into the existing schema.

**`audio/assets.json`** — NEW per-run, replaces `dvc.lock` as md5 source for the 41 legacy non-shard mp3s:

```json
{
  "schema_version": 1,
  "assets": {
    "podcast.mp3": "abc123...",
    "podcast_qwen.mp3": "def456..."
  }
}
```

Frozen content (no new legacy audio is produced); written at migration time by walking `.dvc` files.

**`run_manifest.json`** — field rename `dvc_hash → md5` everywhere. No structural change.

### Webapp changes

`webapp/app.py:_build_audio_r2_map()` rewritten to walk per-run `shards.json` + `assets.json` instead of parsing `dvc.lock`. `serve_shard_audio` and `serve_audio` use `cas.local_path(md5)` + `cas.url(md5)` directly.

**Audio player visibility is a hard binary signal.** A run with no `shards.json` AND no `assets.json` contributes zero entries to `_AUDIO_R2_URLS` → no player rendered. A run whose manifest references an unresolvable md5 (not in local CAS, 404 on R2) is a bug condition, not a silent skip — drop the affected entries, log an error, write a `data_health.json` flag the tracker UI surfaces. The user never sees a broken player.

The two existing `.is_file()` guards on `shards.json` and `assets.json` discovery in the startup walk are legitimate (in-progress runs may not yet have either) and stay; they are NOT the silent-fallback pattern Section 6 targets.

### Silent-fallback audit + path helpers

Scope: **`enrichment/` + `scripts/` only**. Webapp's `.exists()` guards are mostly legitimate (404 short-circuits, optional manifests) — out of scope.

Methodology:

1. Grep for `if .*\.exists\(\):` followed by skip / `None` / `[]` / `{}` / empty default.
2. Grep for direct path construction (`Path(...) / 'foo.json'`) where the same path appears in 2+ places.
3. Triage each hit:
   - **Required** — convert to direct `open()`, let `FileNotFoundError` propagate; route through `cas.paths` if applicable.
   - **Optional-by-design** — keep guard, add one-line comment explaining why.
   - **Path duplication** — replace with `cas.paths.<helper>` call.

Acceptance: zero silent-default patterns in scope for required data; every novel-aware path resolution under scope goes through `cas.paths`; no `if novel == "bleak_house":` survives.

### Preflight smoke test

`run_pipeline.py` calls `_preflight_check(novel)` before any phase:

```python
def _preflight_check(novel: str) -> None:
    enriched = json.loads(cas.paths.passages_enriched(novel).read_text())
    if not enriched:
        raise RuntimeError(f"passages_enriched.json for {novel} is empty")
    fields = ("text", "summary", "best_quote")
    bad = [p["id"] for p in enriched if any(not p.get(f) for f in fields)]
    if len(bad) / len(enriched) > 0.05:
        raise RuntimeError(
            f"{len(bad)}/{len(enriched)} passages in {novel} have empty "
            f"text/summary/best_quote (>5% threshold). First 5: {bad[:5]}"
        )
```

Threshold ≥95% complete. Test with two fixtures (passes + raises).

## Migration plan

One-shot script `scripts/cas_migrate.py`. Dry-run default; `--commit` applies.

**Phase A — Inventory (read-only)**: walk every `.dvc` file (33: 32 `classic.dvc` + 1 `trevelyan_v2.dvc`); expand `<hash>.dir` shard dirs into per-file md5s; walk `dvc.lock` `phase4_audio*` stages for legacy mp3s; output `migration_inventory.json`.

**Phase B — Verify R2 coverage (read-only, network)**: HEAD every unique md5 against R2. Any miss aborts (cannot delete `.dvc` until R2 has every blob). `--allow-r2-misses` for knowingly-abandoned runs.

**Phase C — Populate local CAS (mutating, idempotent)**: copy bytes into `<CAS_ROOT>/files/md5/<prefix>/<rest>`. Verify md5 matches during copy. Skip if blob already present.

**Phase D — Write replacement manifests (mutating)**: ensure each run's `shards.json` is current (verify, don't overwrite — generator already writes them); write `audio/assets.json` for runs with legacy audio; rename `dvc_hash → md5` in every `run_manifest.json`.

**Phase D.5 — Backup tarball (mutating, additive)**:
```bash
tar --exclude='.dvc/cache' --exclude='.dvc/tmp' \
    -cf ../bleakhouse-pre-cas-migration-$(date +%Y%m%d).tar \
    data/runs .dvc dvc.lock dvc.yaml
```
Excludes `.dvc/cache/` (huge, redundant — bytes already in CAS); keeps the metadata. Cheap insurance.

**Phase E — Delete DVC artifacts (destructive)**:
- 33 `.dvc` sidecars under `data/runs/`
- Symlink directories at `data/runs/<run>/audio/shards/<profile>/`
- `dvc.yaml`, `dvc.lock`, `.dvc/config*`, `.dvc/.gitignore`, `.dvc/tmp/`
- `scripts/dvc_stale_report.py`, `scripts/dvc_regenerate.py`, `tests/scripts/test_dvc_regenerate.py`
- `dvc>=3.67.1` and `dvc-s3>=3.0` from `pyproject.toml`; add `boto3` direct
- Strip `dvc commit` from `add_novel.sh`; strip dvc-pull comment from `deploy_demo.sh`
- **`.dvc/cache/` left in place** (BleakHouse-gc2g handles after soak)

**Phase F — Smoke verification (read-only)**: rebuild `_AUDIO_R2_URLS` from manifests; diff against the dvc.lock-derived map; non-empty diff aborts. Boot webapp; sample one run from each cohort (shards-only and legacy-only); play through. `data_health.json` empty.

## Sub-issue split (linear chain)

Each issue depends only on its immediate predecessor. Linearity is deliberate: choices made early bind every downstream issue.

| # | Title | Acceptance |
|---|---|---|
| 8.1 | `cas: build store + paths package + tests` | `pytest cas/` green; `put → local_path` round-trip; `push → pull` round-trip against R2 (skip-marked unless `R2_INTEGRATION=1`); every `cas.paths.*` helper raises with contextual message on miss. |
| 8.2 | `cas: migration script (Phase A-D, no destruction)` | dry-run on current repo produces inventory of 33 .dvc + 41 legacy mp3s; R2 HEAD-check confirms 100% coverage; `--commit` populates `<CAS_ROOT>` idempotently; `audio/assets.json` written for every run with legacy audio; `migration_inventory.json` committed. |
| 8.3 | `webapp: swap _AUDIO_R2_URLS source from dvc.lock to manifests` | webapp test suite green; live demo plays audio for every run that previously had it; 0 broken-player UI states; data_health.json clean. Verified with Playwright before any deploy. |
| 8.4 | `enrichment: integrate cas.put into audio generator` | a fresh small-novel render produces `shards.json` with valid md5s; bytes land in `<CAS_ROOT>`; `cas.push` succeeds; webapp serves the new run via the new path. |
| 8.5 | `enrichment+scripts: silent-fallback audit + path-helper migration` | zero `if .*\.exists\(\):` + empty-default patterns under scope for required data; every novel-aware path goes through `cas.paths`; no `if novel == "bleak_house":` survives; pipeline runs end-to-end on bleak_house. **Hard time-box: 4h. If not done, abort and file a follow-up.** |
| 8.6 | `pipeline: preflight enrichment-completeness smoke test` | passes for every novel currently registered in `enrichment/axes.py`; raises on a synthetic 10%-empty fixture. Test in `tests/test_preflight.py`. |
| 8.7 | `migration: execute Phase E (delete DVC) + Phase F (verify)` | `git grep -E "\bdvc\b"` returns zero hits in code (matches in old commits / docs OK); `pyproject.toml` has no dvc/dvc-s3; live demo plays audio for sampled bh+motf+ngs runs; `data_health.json` clean; backup tar exists outside the repo. |
| 8.8 | `webapp+tracker: remove DVC-stale signal from run_status + tracker UI` | tracker page renders without stale-flag column; `run_status` returns same shape minus stale field. Closes BleakHouse-6bid as moot. |

**Already filed**: BleakHouse-gc2g (deferred to 2026-05-08, depends on e9go) — `cas dedupe: delete legacy .dvc/cache after CAS migration soaks`. Reclaims ~3.3G after soak gate.

**Implicit follow-ups not in this epic**:
- Retire legacy audio format entirely (the 41 non-shard mp3s) — file separately when ready. Removes `audio/assets.json` codepath.
- Move CLAUDE.md gotchas (`dvc unprotect`, `git checkout -- dvc.lock`) — handled in 8.7's commit message.

## Non-goals

- Changing the R2 layout (kept as-is; existing bytes reused).
- Changing webapp audio route URL shape.
- Auditing webapp `.exists()` guards.
- Auditing `tools/forced_align/` beyond the `cas.put` integration in backup mode.
- Replacing the dropped DVC stale-tracking with a new manifest-based stale tracker (BleakHouse-6bid is moot, not migrated).

## Wall-clock estimate

1.5-2 days end-to-end. 8.1 (~½d), 8.2 (~½d), 8.5 (4h hard cap), 8.7 (afternoon).
