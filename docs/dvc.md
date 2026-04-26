# DVC for BleakHouse pipeline provenance

## Why this exists

Before DVC we had repeated provenance bugs:

- `podcast.mp3` was rendered against an older `SPEAKER_VOICES` mapping,
  but nothing on disk said so, and `git log` couldn't tell us either.
- `manifest.json` timings drifted ~6 minutes from the actual MP3
  (Gemini voice-drift bug, `BleakHouse-z4v`) — invisible until we tried
  to extract per-speaker reference clips for voice cloning.
- When the axis migration renamed run directories, every stored
  `manifest.json` had a stale `run_id` field; we had to hand-patch.

DVC fixes this by declaring the input-output graph explicitly. Change
an input (params value, code file, earlier-phase artefact) and DVC
immediately flags every downstream artefact as stale. No guessing.

## What's tracked today

**`params.yaml`** — pipeline-parameter source of truth:

```
speakers:
  voices:           Host → Sulafat, James Blackstone → Sadaltager, ...
  accents:          per-speaker Gemini voice-direction phrases
  voice_policies:   rate/energy/pause_bias_ms/style per speaker
generators:         [{id, api_model, provider, display}, ...]
default_generator:  anthropic_sonnet_4_6
```

Python modules (`enrichment/tts_profiles/classic.py`,
`enrichment/axes.py`) load from here on import.

**`dvc.yaml`** — three matrix stages per canonical run:

| stage | deps | outs |
|---|---|---|
| `phase3_episode` | config.json, phase2_plan.json, generate_podcast.py, podcast_types.py, params:generators/default_generator | phase3_episode.json |
| `phase4_post` | phase3_episode.json, post_phase3.py, build_manifest.py, build_report.py | manifest.json, report.html, report.txt |
| `phase4_audio` | phase3_episode.json, render_audio.py, tts_profiles/classic.py, params:speakers | audio/podcast.mp3 |

Each stage expands via `foreach: ${run_ids_*}` over `runs.yaml`, giving
194 × 3 ≈ 582 concrete stage instances.

**`runs.yaml`** — machine-generated inventory from `data/runs/*/config.json`.
Regenerate with:

```bash
uv run python -m scripts.generate_runs_yaml
```

**`dvc.lock`** — committed. Holds the baseline content hash for every out.
`dvc status` compares current deps/outs against this.

**Not yet tracked** — earlier pipeline phases (phase0_segments,
phase1_assignments, phase2_plan, phase2_5_*). Deliberate scope choice:
they rarely go stale in practice for the existing corpus. Add them if
you want by adding more stages to `dvc.yaml` and running `dvc commit`.

## Common commands

```bash
uv run dvc status          # "up to date" = green
uv run dvc stage list      # every expanded stage instance
uv run dvc dag --mermaid   # dependency graph (big — pipe to a file)

# After editing params.yaml or a declared code file:
uv run dvc status          # shows which runs are affected

# If you regenerate a run via the normal pipeline CLI, re-baseline it:
uv run dvc commit
```

`dvc repro` is only partially automated — see "regeneration" below.

## Adding something new

### New parameter

1. Add the key to `params.yaml`.
2. Have the consuming Python module read it via
   `enrichment.params.get(...)`.
3. Add the param name to the relevant stage's `params:` list in
   `dvc.yaml`.
4. Run `uv run dvc commit` to baseline once everything is consistent.

### New stage (e.g. phase1_assignments)

1. Declare a new block in `dvc.yaml`:
   ```yaml
   phase1_assignments:
     foreach: ${run_ids_phase3}
     do:
       cmd: uv run python scripts/dvc_regenerate.py phase1 --run ${item}
       deps:
         - data/runs/${item}/config.json
         - data/runs/${item}/phase0_segments.json
         - enrichment/segment_transport.py
         - enrichment/embedding_run.py
         - enrichment/no_passages_run.py
       outs:
         - data/runs/${item}/phase1_assignments.json:
             cache: false
   ```
2. Extend `scripts/dvc_regenerate.py` with a `regenerate_phase1` handler
   (or leave it as a "not yet" stub if you don't need automation).
3. `uv run dvc commit` to register existing artefacts.

### New run directory

1. Produce the run's artefacts via the existing pipeline CLIs.
2. Regenerate `runs.yaml`:
   `uv run python -m scripts.generate_runs_yaml`.
3. `uv run dvc commit` picks up the new run.

## Regeneration

`dvc repro <stage>` runs the `cmd:` of a stale stage. For this project:

- **`phase4_post`** is fully automated — `scripts/dvc_regenerate.py`
  calls `enrichment.post_phase3.run_post_phase3` and the manifest/report
  triad is rebuilt in place.
- **`phase3_episode`** and **`phase4_audio`** are stubbed. Running their
  `cmd:` prints a message telling you to use the existing pipeline CLI
  (e.g. `uv run python -m enrichment.run_pipeline --name <run>
  --resume-from 3`) and then `dvc commit`. Extending the dispatcher is
  welcome; see `scripts/dvc_regenerate.py`.

## CI / pre-commit

`.pre-commit-config.yaml` declares two local hooks:

- **`dvc-status`** — aborts a commit if `dvc status` reports any stale
  runs. Escape hatch: `git commit --no-verify` when you intentionally
  land a stale state (e.g. in a migration branch).
- **`runs-yaml-current`** — aborts a commit if `runs.yaml` is out of
  sync with `data/runs/*/config.json`. Run
  `uv run python -m scripts.generate_runs_yaml` and stage the diff.

Install once per clone:

```bash
pre-commit install
```

## Known limitations

- Only 3 pipeline phases are declared; 0/1/2/2.5 aren't yet.
- No DVC remote configured. Outs stay in git (small JSON files are
  fine; `audio/podcast.mp3` is `.gitignore`-excluded and lives on
  `PODCAST_AUDIO_DIR`). If we add phase2_5 or anything else large,
  configure a DVC remote (Fly volume / Crucial X9 / S3).
- `dvc.lock` is 500 KB / 15 k lines because of the 594-instance matrix.
  That's a one-time commit; incremental updates to it are small.
