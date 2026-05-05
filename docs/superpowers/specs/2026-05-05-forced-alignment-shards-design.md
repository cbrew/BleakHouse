# Forced-alignment migration: legacy podcast.mp3 → per-turn shards

## Problem

Thirty-two audio runs use the legacy single-`podcast.mp3` rendering. The
served per-turn manifest is built with `build_manifest --no-audio` (15
chars/sec character-count estimate), so click-to-jump in the player lands
on the wrong turn. Drift accumulates across the episode and reaches ~10
minutes by the end of a 100-minute mp3.

The shards rendering used by `room_with_a_view` does not have this
problem: each turn is its own mp3 file, so the player advances on
`<audio>` `ended` events and there are no ms offsets to drift from.

The fix: cut the legacy `podcast.mp3` files into per-turn shards using
forced alignment, write the matching `shards.json` and audio-measured
`manifest.json`, and let the existing player code switch to shards mode
the next time the run is loaded.

## Non-goals

- Re-rendering audio for runs whose TTS cache is incomplete locally.
- Removing the legacy `podcast.mp3` files. They remain as a fallback
  until shards prove out across all 32 runs (separate decision).
- Failure-recovery elaborations: deviation-fallback transcribe mode,
  word-confidence interpolation, manual-review queues, etc. v1 logs
  alignment errors and skips the affected run.
- Touching the existing `webapp/build_manifest.py`. It stays on its
  current code path; it becomes irrelevant for runs that gain shards.

## Sources of truth

- **Audio**: `data/runs/<run>/audio/podcast.mp3` is the only source for
  what listeners hear. Forced-align against this file directly.
- **Transcript**: `data/runs/<run>/phase3_episode.json` is the only
  source for the intended utterance text and the speaker/turn labels.
- **The TTS cache is not consulted.** No `_cache_key`, no
  `_load_cached`, no `len(cached)`. The cache hash assumes prompt +
  voice + model uniquely identifies what was rendered, which doesn't
  hold once anyone touches the script or the cache after concatenation.

## Architecture

A self-contained tool `tools/forced_align/` with its own
`pyproject.toml` and `uv.lock`. Heavy WhisperX/torch dependencies stay
out of the main project. Never deployed to Fly. Lives on the
`feature/forced-alignment-shards` branch until the migration is
verified end-to-end.

### Pipeline (per run)

```
podcast.mp3                                  ┐
phase3_episode.json                          ┘
       │
       ▼
1. Build expected transcript (concat utterances in script order;
   remember each turn's [first_word_idx, last_word_idx])
       │
       ▼
2. WhisperX force-align mode: provided transcript + audio →
   per-word (start, end) timestamps
       │
       ▼
3. Project word timestamps → per-turn (T_first_speech, T_last_speech)
       │
       ▼
4. Compute shard boundaries:
   shard_N covers [midpoint(prev_speech_end, this_speech_start),
                   midpoint(this_speech_end, next_speech_start)]
   First shard starts at 0; last shard ends at mp3_duration.
       │
       ▼
5. Slice mp3 with ffmpeg `-c copy -ss X -to Y -avoid_negative_ts make_zero`
   (exact byte slicing, no re-encode) →
   data/runs/<run>/audio/shards/classic/0000.mp3, 0001.mp3, ...
       │
       ▼
6. Write data/runs/<run>/audio/shards.json   (matches rwv schema)
         data/runs/<run>/audio/manifest.json (audio-measured timing)
       │
       ▼
7. dvc add data/runs/<run>/audio/shards
   dvc push -r r2
```

### Modules under `tools/forced_align/`

Each is small and individually testable.

- `transcript.py` — parse `phase3_episode.json`; emit a flat word list
  for the whole episode plus a `[first, last]` index range for each
  turn.
- `align.py` — thin WhisperX wrapper. Input: `(audio_path,
  transcript_words)`. Output: `[(word, t_start, t_end), ...]`. Loads
  the model once per process; not part of the pure-logic core.
- `boundaries.py` — pure function: given alignment + per-turn word
  ranges + mp3 duration, returns shard boundaries. Unit-tested
  exhaustively against synthetic data. Knows nothing about audio.
- `slicer.py` — ffmpeg subprocess wrapper. Slices and writes mp3 files.
- `manifest.py` — emits `shards.json` and audio-measured
  `manifest.json` from the boundaries + the script's turn metadata.
- `__main__.py` — CLI entry point: `--run <id>`, `--all`, `--force`.

### Output schema

`shards.json` exactly mirrors the rwv schema:

```json
{
  "schema_version": 1,
  "profile": "classic",
  "episode_title": "...",
  "experts": [...],
  "shards": [
    {"file": "0000.mp3", "md5": "...", "kind": "turn",
     "segment_index": 0, "turn_index": 0,
     "speaker": "Host", "role": "host",
     "utterances": [{"text": "...", ...}]},
    ...
  ]
}
```

All shards are `kind="turn"`. Unlike rwv (which has 6 `kind="break"`
shards for inter-segment silence inserted by the shards renderer), the
legacy mp3 already contains whatever inter-segment silence was rendered
into it; midpoint slicing distributes that silence to the adjacent
turn shards. The player handles either layout — `seekToTurn` and the
shard advancer key off `kind === "turn"` only.

`audio/manifest.json` mirrors the existing audio-measured manifest
shape (the same one `webapp/build_manifest.py` writes in audio=True
mode), with `start_ms`/`end_ms` per turn taken from the forced-aligned
boundaries. Webapp's `/api/runs/<id>/manifest` already prefers this
file when present, so no webapp change is required.

### Slicing rule (recap)

Midpoint split. Each shard is contiguous; sequential playback of all
shards is byte-identical to playing the original mp3 at every point.
Click-to-jump lands a half-pause before the speaker.

## Edge cases

- **First turn**: shard 0 starts at `0.0` (no preceding silence to split).
- **Last turn**: last shard ends at mp3 duration.
- **Zero-silence boundary** (TTS rendered with no inter-turn pause):
  midpoint of an empty interval is the boundary itself.
- **Min shard length** (< 0.5s): log a warning, write the shard anyway.
  Likely indicates a one-word turn ("Right.") or an alignment glitch.

## Errors

Minimal in v1:

- WhisperX raises → write `<run>/audio/align_error.txt` with the
  trace, exit non-zero for that run, continue with the next run.
- ffmpeg slice fails → same handling.
- Output validation (e.g. duration mismatch > 1s between sum-of-shards
  and the mp3): log warning, do not block.

No fallback to transcribe mode. No alignment-quality flagging. If a
run fails it stays on the legacy mp3; the player's existing fallback
serves it as today. We collect failures and address them in a separate
follow-up.

## Idempotency

Without `--force`, refuse if `shards.json` already exists for a run.
With `--force`, overwrite shards + shards.json + manifest.json + the
DVC-tracked shards directory.

## Testing

- **Unit**: `boundaries.py` is a pure function — full coverage with
  synthetic alignment dicts. Covers: 1-turn run, all-zero-silence
  run, missing-words gaps, edges (first/last turn).
- **Integration**: tiny synthetic fixture (3 turns × ~3s of pre-built
  speech-like wav) — verifies end-to-end slicing math + `shards.json`
  schema. Does not run WhisperX in CI.
- **Manual listen-test on the pilot run**: validation gate for actual
  alignment quality.

## Pilot

1. Create branch `feature/forced-alignment-shards` off main.
2. Build `tools/forced_align/`. Unit + integration tests pass.
3. Run on `bh_trn_literary_hostprep`. Generate shards into the run's
   audio dir. **Do not deploy.**
4. Click through ~10 turns on the local consumer player at
   `http://127.0.0.1:8765/listen/bleak_house/literary`. Verify each
   click lands on the speaker the player highlights.
5. If clean: run on the other 31 runs (overnight if needed).
6. `dvc add` + `dvc push -r r2` for all new shards directories. Commit
   `shards.json` + `audio/manifest.json` + `.dvc` files.
7. Merge `feature/forced-alignment-shards` to main. Deploy.

## Performance

Estimate: WhisperX `large-v2` on Apple-silicon MPS, ~10–15 minutes per
~100-minute mp3. 32 runs ≈ 4–8 hours wall clock. One-time migration;
unattended-run-friendly.

R2 storage: ~32 runs × ~100 shards × ~600 KB ≈ ~2 GB additional.
Existing DVC/R2 flow handles it; no infra changes.

## Out-of-scope follow-ups (not part of v1)

- Removing legacy `podcast.mp3` files after shards prove out.
- Improving alignment quality for flagged-poor runs.
- Re-rendering deviated turns from cache.
- Aligning the non-classic profiles (`qwen`, `trevelyan_v2`,
  `3.1-flash`) — only the classic mp3 is in scope for v1.
