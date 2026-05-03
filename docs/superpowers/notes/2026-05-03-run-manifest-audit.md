# run_manifest.json audit (2026-05-03)

## Findings

**40 total grep hits; 19 substantive references** (the rest are comments, the
generator script itself, or the notes directory).  Broken down by location:

- webapp (`webapp/app.py`): 8 substantive references (2 functions + their callers)
- scripts: 6 references across 3 scripts (`generate_run_manifest.py`,
  `retrofit_hostprep.py`, `list_retrofit_candidates.py`, `generate_runs_yaml.py`)
- enrichment DB (`enrichment/expdb/backfill.py`, `enrichment/expdb/refresh.py`): 3 references
- tests (`tests/expdb/`): 4 fixture writes (test_backfill.py ×2, test_backfill_bulk.py, test_cli.py)

### Field-by-field breakdown

#### Category A — reads `audio_variants` (goes away after Task 2 audio refactor)

| File | Line(s) | What it does |
|------|---------|--------------|
| `webapp/app.py` | 461–463 | `_available_versions()` iterates `audio_variants[*].hash` to enumerate playable variants |
| `webapp/app.py` | 639–664 | `/audio/{run_id}/{filename}` handler: iterates `audio_variants` to match filename → hash → R2 redirect |
| `enrichment/expdb/backfill.py` | 161–178 | Inserts `audio_variants` into the experiment DB (`tts_config` + `audio_artifact` rows) |
| `tests/expdb/test_backfill.py` | 28–35 | Fixture providing one `audio_variants` entry for the scan tests |

The webapp uses (`hash` → R2 URL) are the staleness bug root cause.  The DB
backfill use is **not** going away in Task 2 — it reads `audio_variants` to
populate `audio_artifact` rows including `dvc_hash` for provenance. This is the
one non-trivial Category A consumer that survives Task 2.

#### Category B — reads `axes`

| File | Line(s) | What it does |
|------|---------|--------------|
| `enrichment/expdb/backfill.py` | 57–72 | Reads `rm["axes"]` to populate episode/script rows |
| `scripts/retrofit_hostprep.py` | 48–80 | Reads `axes` from source run_manifest to stamp the retrofit's manifest |
| `scripts/list_retrofit_candidates.py` | 29 | Filters on `axes.hostprep` to list retrofit-needed runs |
| `scripts/generate_runs_yaml.py` | 43–48 | Fallback: reads `axes` from run_manifest for retrofit runs that lack `config.json` axes |

Note: `generate_runs_yaml.py` uses `run_manifest.json` only as a **fallback**
for retrofit dirs that have no canonical `config.json`.  Canonical runs always
get axes from `config.json`; this path is only exercised for the hand-built
retrofit manifests that `retrofit_hostprep.py` produces.

Axes are already in `config.json` for all canonical runs.  The spec notes
that `config.json` is git-tracked and will be COPYed into the container.
For retrofit dirs, `run_manifest.json` is the only source of axes (by design —
retrofit dirs have no config.json axes block).

#### Category C — reads `stages`

| File | Line(s) | What it does |
|------|---------|--------------|
| `enrichment/expdb/backfill.py` | 182–187 | Reads `stages.quote_verification` to record an evaluation row |

`stages` is generated from dvc.lock by `generate_run_manifest.py`.  The
`quote_verification` sub-field contains `{verified, total, rate}` lifted from
the output file of the `quote_verification@{run_id}` DVC stage.  This is the
only consumer of `stages` outside the generator script itself.

#### Category D — reads `dvc_lock_sha`, `generated_at`, `schema_version`

| File | Line(s) | What it does |
|------|---------|--------------|
| `enrichment/expdb/backfill.py` | 155 | Reads `generated_at` as `finished_at` on the generation_run DB row |
| `scripts/retrofit_hostprep.py` | 54 | Copies `dvc_lock_sha` into the retrofit manifest as `source_dvc_lock_sha` |

`dvc_lock_sha` in the retrofit case provides provenance ("which dvc.lock was
current when this retrofit was generated").  `generated_at` drives the DB
timestamp.  `schema_version` is read nowhere outside the generator — it is
purely forward-compatibility scaffolding that has never been branched on.

#### Category E — other

| File | Line(s) | What it does |
|------|---------|--------------|
| `enrichment/expdb/refresh.py` | 41 | Mtime check: `run_manifest.json` is one of four files whose mtime determines whether to re-scan the DB. Not a field read — purely filesystem presence/mtime. |
| `enrichment/expdb/backfill.py` | 215 | Presence check: skips a run dir if `run_manifest.json` does not exist. Acts as a **sentinel** — a run is "ready to index" iff this file exists. |

The sentinel role is the most load-bearing non-field use.  The DB scanner uses
`run_manifest.json` as the existence gate for a run being backfill-eligible.

---

## Decision

**Verdict: SIMPLIFY**

**Rationale:** `run_manifest.json` is not vestigial — it carries three distinct
roles that survive the audio routing refactor:

1. **axes for retrofit dirs** (`generate_runs_yaml.py`, `retrofit_hostprep.py`,
   `list_retrofit_candidates.py`): retrofit dirs have no axes in `config.json`;
   `run_manifest.json` is the only axes source.

2. **DB backfill inputs** (`enrichment/expdb/backfill.py`): the experiment DB
   scanner reads `axes`, `audio_variants` (for audio artifact rows with
   `dvc_hash`), `stages.quote_verification` (for evaluation rows), and
   `generated_at`.  After Task 2, the webapp will stop reading `audio_variants`,
   but the DB backfill will still need it for provenance.

3. **Sentinel for DB scanning**: `run_manifest.json` existence is the
   precondition for `scan_runs_dir` processing a run dir.  Deleting the file
   would silently exclude runs from the experiment DB.

What CAN be removed is the `audio_variants[*].hash` → R2 path in the webapp
(the staleness-bug source), and the `generate_run_manifest.py` DVC stage whose
deps don't include `dvc.lock`.  The file stays; the webapp's reading of it for
audio URL construction goes away.

The `dvc_lock_sha` field and the DVC stage itself warrant attention: after the
audio routing moves to `dvc pull`-materialised files, the DVC stage for
`run_manifest` is no longer needed as a build step (the file is already
git-tracked).  The generator script becomes a developer utility, not a DVC
stage.

---

## Implementation impact

### Files to delete
- Nothing (SIMPLIFY verdict: the file stays)
- The `run_manifest` DVC stage definition in `dvc.yaml` (to be done in a later
  task — the DVC stage is not needed if the file is git-tracked and the
  generator is run manually)

### Files to modify

- `webapp/app.py`: Remove `_load_run_manifest()`, `_available_versions()` loop
  over `audio_variants`, and all R2 URL construction from the `/audio` handler.
  This is Task 2 of the plan.  The `manifest.json`-serving fallback (`manifest.json`
  at line 668) is unrelated to `run_manifest.json` — it refers to the per-run
  `manifest.json` (podcast script JSON), not the run manifest.

- `scripts/generate_run_manifest.py`: No immediate change needed.  After Task 2,
  can strip the `audio_variants[*].hash` block (the staleness-bug field) if
  desired, leaving `axes`, `stages`, `generated_at`, `dvc_lock_sha`.

- `enrichment/expdb/refresh.py`: No change needed — mtime-watches the file,
  which continues to exist.

- `tests/expdb/test_backfill.py`, `test_backfill_bulk.py`, `test_cli.py`:
  Fixtures stay valid as-is.  After Task 2 strips `audio_variants` from the
  webapp, the DB backfill still reads this field so the fixtures remain correct.

### dvc.yaml changes

- Candidate for removal: the `run_manifest@{run_id}` stage (if it exists per
  run).  Dropping it removes the broken dep-list (doesn't include `dvc.lock`),
  which was the root cause of the staleness bug.  The generator script becomes
  a manual developer tool, not a DVC pipeline stage.  Verify in a later task
  whether the stage exists in dvc.yaml before deleting it.
