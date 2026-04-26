# Webapp ↔ DVC: tightening the connection

User push: *"the connection between the webapp and dvc should be tight and maintainable.
manifests may (I am not sure) be part of that, or an orthogonal thing. transparency and
maintainability and reproducibility are crucial."*

The synthesis-version bug (`docs/synthesis_redesign.md`) is one visible symptom of this
deeper structural issue. This doc describes the architecture problem, where manifests fit,
and a migration path that prioritises the three properties the user named:

- **Transparency** — a viewer should be able to ask "what produced this and from what?" of
  any artefact and get a concrete answer.
- **Maintainability** — one place where "what runs have what" is computed; everything else
  reads it.
- **Reproducibility** — DVC's `dvc repro` is the trusted path from inputs to outputs; the
  UI surfaces that path, doesn't bypass it.

## Current state

DVC is the authoritative graph: `dvc.lock` records every input dep's md5 + every output's
md5 for every stage. `dvc status` is the canonical answer to "is run X fresh?".

The webapp does NOT read DVC. It reads the filesystem. Specifically:

| Code path | Reads | Authoritative? |
|---|---|---|
| `_discover_runs` | `<run>/audio/manifest.json` existence | filesystem convention |
| `_summarize_run_dir` | several JSONs by name + audio file existence | filesystem convention |
| `_available_versions` | `<run>/audio/podcast*.mp3` + `manifest_*.json` pairs | filesystem convention |
| `has_audio` | bool wrapper around `_available_versions` | filesystem convention |
| `_dvc_stale_runs` | `dvc status --json` | DVC ✓ |
| `runs.yaml` | filesystem; consumed by both DVC's foreach and `generate_runs_yaml.py` | mixed |

Only the staleness badge actually consults DVC. Everything else infers from file paths.

## Where this leaks

The two views can drift in either direction:

1. **A render produces a file that's not yet `dvc commit`'d** — webapp shows the audio,
   DVC says the stage is dirty. Visitor sees inconsistent state.
2. **A file is deleted but `dvc.lock` retains its hash** — webapp loses sight of it; DVC
   still believes it exists.
3. **Filename conventions become quasi-API** — the qwen visibility bug was exactly this:
   `manifest_qwen.json` existed (so qwen registered as a version) but `manifest.json` did
   not (so classic was missed even though `podcast.mp3` was right there as a symlink).
4. **Three answers to "what audio variants does this run have"**: `runs.yaml` flags,
   filesystem inspection, and `dvc.lock` outputs. They mostly agree. When they don't, no
   single tie-breaker.

## Where do manifests fit?

Today's `audio/manifest.json` files describe the *renderer's output* — segments, turns,
utterances, durations, speakers. They're consumed by `webapp/static/player.js` to render
the synced-script-and-audio UI.

That's a legitimate role: a manifest captures what the renderer produced, frozen, so the
player doesn't have to recompute timings or re-decode audio. They're orthogonal to
provenance — a manifest tells you *what's inside* an audio file, not *how it was made*.

**The audio/manifest.json files are necessary content metadata. They are not the right
place to encode webapp ↔ DVC reconciliation.** A different file should do that job.

## Proposal: a run_manifest

Introduce one JSON per run, `data/runs/<id>/run_manifest.json`, that is the single
authoritative answer to "what does this run consist of, and what's the hash of each
piece?". Produced by a DVC stage that depends on every upstream phase, so it's regenerated
automatically when anything changes.

Shape (sketch):

```json
{
  "schema_version": 1,
  "run_id": "bh_trn_literary_hostprep",
  "axes": {
    "novel": "bh", "novel_id": "bleak_house",
    "pipeline": "trn", "panel": "literary",
    "hostprep": true, "generator": "anthropic_sonnet_4_6"
  },
  "stages": {
    "phase3_episode": { "hash": "8e7c…", "fresh": true },
    "phase2_5":       { "hash": "1b22…", "fresh": true },
    "quote_verification": { "hash": "44ab…", "fresh": true,
                             "verified": 142, "total": 156, "rate": 91.0 },
    "phase4_post":    { "hash": "9d10…", "fresh": true },
    "phase4_audio":   { "hash": "44de…", "fresh": true,
                         "audio_file": "audio/podcast.mp3",
                         "audio_manifest": "audio/manifest.json",
                         "engine": "gemini-2.5-flash-preview-tts" },
    "phase4_audio_qwen": { "hash": "5f3c…", "fresh": true,
                            "audio_file": "audio/podcast_qwen.mp3",
                            "audio_manifest": "audio/manifest_qwen.json",
                            "engine": "qwen3-tts-0.6b-base" }
  },
  "audio_variants": [
    {"name": "classic",  "engine": "gemini-2.5-flash-preview-tts",
     "stage": "phase4_audio",      "hash": "44de…"},
    {"name": "qwen",     "engine": "qwen3-tts-0.6b-base",
     "stage": "phase4_audio_qwen", "hash": "5f3c…"}
  ],
  "generated_at": "2026-04-26T01:42:00Z",
  "dvc_lock_sha": "<sha of dvc.lock at generation time>"
}
```

Properties:

- **Per-stage `fresh` boolean** comes from comparing `dvc.lock` hash to the file on disk —
  cheap.
- **`audio_variants`** is an explicit, ordered list. Webapp's `_available_versions` becomes
  `[v["name"] for v in run_manifest["audio_variants"]]`. No filename pattern matching.
- **`engine`** captures the actual TTS used; today this is implicit (classic = Gemini,
  qwen = Qwen). Making it explicit lets the UI label and filter.
- **`dvc_lock_sha`** lets the webapp detect when run_manifest itself is stale relative to
  the global graph state.

## Migration plan (incremental, no big-bang)

Each step leaves the app in a working state.

1. **`scripts/generate_run_manifest.py`** — for one run, produces `run_manifest.json` from
   `dvc.lock` + filesystem. Idempotent. Manual invocation works first.
2. **DVC stage `run_manifest@<id>`** — `foreach: ${runs_by_id}`. Deps: every other phase's
   output for that run. Out: `data/runs/<id>/run_manifest.json` (cache:false, git-tracked).
3. **Webapp adds `_load_run_manifest(run_id)`**. New code paths read from it. Old paths
   continue to work via filesystem inspection — both code paths exist for one PR.
4. **Migrate one consumer at a time**: `_available_versions` → run_manifest. Re-test.
   Then `_summarize_run_dir`. Then `_discover_runs`.
5. **When all consumers are migrated**, remove the filesystem-convention paths. Single
   source of truth lands.

After step 5, the webapp's view IS DVC's view. A change DVC sees, the webapp sees on next
request. A change DVC doesn't see, the webapp doesn't see.

## Surfacing reproducibility in the UI

Once the run_manifest is in place, the UI can directly expose what DVC knows:

- **Per-cell badge** in the matrix:
  - ✓ green: all stages fresh, all hashes in dvc.lock, file on disk matches.
  - ⚠ amber: at least one stage stale (file or dep changed since last commit).
  - ✕ red: file referenced by dvc.lock missing on disk.
- **Per-run drill-down**: a `/run/<id>` page that prints the run_manifest's stage table —
  hash, fresh/stale, and a copy-paste line to regenerate (`uv run dvc repro phase4_audio_qwen@<id>`).
- **Audio variant labels** show the engine name explicitly (the chip says "Gemini Flash"
  or "Qwen3-TTS", not just "classic" or "qwen").

This is what the user means by transparency: anyone can ask "where did this come from?"
and get a concrete answer pointing at DVC.

## Trade-offs

| Trade-off | Direction |
|---|---|
| One more DVC stage per run × 194 runs = 194 more stages | Acceptable; each is a fast Python read. `dvc commit -f` won't notice. |
| Webapp depends on dvc.lock structure | DVC's lockfile schema is stable; pinning to a major version is fine. |
| The `run_manifest@<id>` stage's deps must be every phase output for that run | Mechanical to declare. Makes the dependency graph explicit, which is the point. |
| Tier 1 fix in flight already touches `_available_versions` | Tier 1 stays — it's the immediate UX fix. The run_manifest is the long-term replacement that subsumes Tier 1's special-case logic. |

## Where this leaves the synthesis redesign

Tier 1 (the in-flight fix) ships now. Tier 2 (synthesis as a first-class axis) becomes
trivial *after* run_manifest lands — the matrix already has the audio_variants list per
run, the filter is `[v.name for v in audio_variants]`. Tier 3 (compare page) doesn't depend
on run_manifest but benefits from it.

In other words: the webapp ↔ DVC re-architecture isn't an alternative to the synthesis
work, it's the foundation that makes the synthesis work cheap.

## Recommended sequencing

1. Land Tier 1 synthesis fix (one PR, today).
2. Build `run_manifest@<id>` and the dual-read webapp (one PR).
3. Migrate webapp consumers (one PR per consumer or batched, low-risk).
4. Drop filesystem-convention code paths (one cleanup PR).
5. Tier 2 synthesis filter + cell badges, now reading run_manifest natively (one PR).
6. Tier 3 /compare page (only if a user asks).

Step 2 is the architecturally important one. Steps 3–4 are mechanical. Step 5 becomes a
small UI-only change once the data layer is solid.
