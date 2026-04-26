# BleakHouse Pipeline: Novel + Expert Profiles → Gemini TTS Audio

End-to-end description of the literary-podcast pipeline, with the LLM /
engine used at each step and the file produced. Claude is used for
every generative text step; Gemini is used only for TTS. Every
artefact is DVC-tracked (see `docs/dvc.md`).

**Driver:** `enrichment/run_pipeline.py::main`.

## Prerequisites (fixtures, per novel)

Not in the per-run DVC graph — computed once per novel by separate
scripts:

- `data/novels/{novel}/passages_enriched.json` — passages with LLM-
  computed "provision" scores on literary dimensions (comedic, legal,
  social, romance, …).
- `data/novels/{novel}/clusters_literary.json` +
  `clusters_characters.json` — required for transport pipelines.
- `params.yaml` — speaker voices, accents, voice policies, generator
  registry.
- Expert profiles (`enrichment/experts.py` — `ExpertProfile`) + arc
  demands (`enrichment/arcs.py` — `ArcDemand`). Still in code rather
  than per-run JSON.

## Inputs to a single run

- Novel name (e.g. `bleak_house`)
- Expert panel (list of `ExpertProfile` — name, background, per-
  dimension demands)
- Arc demands (list of `ArcDemand` — segment-type preferences)
- Run name (e.g. `bh_trn_literary_hostprep`)
- Pipeline type: `transport` | `no-passages` | `embedding`
- Optional `--host-prep`
- Optional generator (defaults to `anthropic_sonnet_4_6`)

## Phase 0 — Segment design

`enrichment/design_segments.py::design_segments` calls **Claude Haiku
4.5** (`claude-haiku-4-5-20251001`) to propose segment templates from
the expert panel + arc demands. Each template has a name,
segment_type, min/max passage count.

**Output:** `phase0_segments.json` (list of `SegmentTemplate`).

## Phase 1+2 — Passage matching and ordering

Dispatch on pipeline type (`run_pipeline.py:149–303`):

- **transport** (`run_phases_1_2_transport`): Sinkhorn optimal-
  transport match of passages to segments, weighted by passage
  provisions against expert demands. **No LLM calls** — pure numerics.
- **no-passages** (`run_phases_1_2_no_passages`): skips passage
  grounding entirely; keeps segment structure and expert roles. Same
  output filenames, empty passage lists.
- **embedding** (`run_phases_1_2_embedding`): embedding cosine-
  similarity match instead of OT.

**Outputs:** `phase1_assignments.json` (passage → segment) +
`phase2_plan.json` (ordering + speaker assignments).

## Phase 2.5 — Host preparation (only if `--host-prep`)

`enrichment/host_prep.py::run_host_prep` calls Claude in two roles:

- **Interviewer** — default **Claude Haiku 4.5**. Simulates pre-
  interview Q&A with each expert about their assigned passages.
- **Planner** — default **Claude Sonnet 4.6**. Produces the host's
  segment briefs (anticipated questions, narrative transitions).

When `--use-reference-tools` is set, the interview model is promoted
to Sonnet 4.6 because the tool-use flow needs the stronger model.

**Outputs:** `phase2_5_host_briefs.json`, `phase2_5_interviews.json`,
`phase2_5_reading_list.json`.

## Phase 3 — Script generation

`enrichment/generate_podcast.py::generate_episode` calls the
configured generator (default **Claude Sonnet 4.6**) once per turn to
produce each speaker's utterances, given `phase2_plan.json` + (if
hostprep) the `phase2_5_*` briefs. Every utterance carries
`pause_before_ms`, `rate`, `quote_mode`, `emphasis_words` annotations
used by the TTS step.

**Output:** `phase3_episode.json` (a `PodcastEpisode` with segments →
turns → utterances).

## Phase 4 post-processing (non-audio)

All read from `phase3_episode.json`; only `precompute_quote_verification`
issues LLM calls:

- `enrichment/post_phase3.py::run_post_phase3` → `report.txt`
- `webapp/build_manifest.py` → `manifest.json` (powers tracker/webapp)
- `webapp/build_report.py` → `report.html`
- `enrichment/precompute_quote_verification.py` → `quote_verification.json`
  (one LLM call per cited passage to verify the quote against source
  text)

## Phase 4 audio — Gemini TTS

`enrichment/render_audio.py` + `enrichment/tts_profiles/classic.py::ClassicProfile`:

1. For each turn, `build_turn_prompt(turn)` builds:
   ```
   [Voice direction: {speaker} {accent}. Energy: {e}. Style: {s}.]

   ({rate+quote+emphasis directions})
   {utterance text}

   ({more directions})
   {next utterance text}
   ...
   ```
2. Calls the configured TTS model with
   `speech_config.voice_config.prebuilt_voice_config.voice_name = SPEAKER_VOICES[speaker]`.
   The voice map comes from `params.yaml:speakers.voices`.
3. Concatenates per-turn audio, inserts per-utterance
   `pause_before/after_ms` silences, glues segments with 2s silence.
4. Exports MP3 at 192 kbps to `data/runs/{run_id}/audio/podcast.mp3`
   — a symlink into the DVC cache on the external volume.

### Current default: Gemini 2.5 Flash TTS

`CLASSIC_MODEL_IDS` in `enrichment/render_audio.py`:

```python
CLASSIC_MODEL_IDS = {
    "flash": "gemini-2.5-flash-preview-tts",
    "pro": "gemini-2.5-pro-preview-tts",
}
```

Invoked via `uv run python -m enrichment.render_audio --run <id> --model flash`.

### Upgrading to Gemini 3.1 Flash TTS

Released 2026-04-15 as a preview. Google reports > 70 languages,
200+ audio tags for expressive control, native multi-speaker dialogue,
and an Artificial Analysis Elo of 1211 on the TTS leaderboard (higher
than 2.5 Flash TTS on Google's own comparison).

**Model ID (verified against Google AI Developers docs):**
`gemini-3.1-flash-tts-preview`.

**Access:** Google AI Studio or Vertex AI, under the existing Gemini
API. No change to authentication (the existing `GEMINI_API_KEY` +
`google.genai.Client()` pattern works).

**Code change needed.** Extend `CLASSIC_MODEL_IDS` and the CLI's
`--model` choices in `enrichment/render_audio.py`:

```python
CLASSIC_MODEL_IDS = {
    "flash": "gemini-2.5-flash-preview-tts",
    "pro":   "gemini-2.5-pro-preview-tts",
    "flash3": "gemini-3.1-flash-tts-preview",
}

# ... in main():
parser.add_argument("--model", choices=["flash", "pro", "flash3"], ...)
```

Then: `uv run python -m enrichment.render_audio --run <id> --model flash3`.

**Provenance impact.** The model ID is part of the DVC dep chain for
the audio stage indirectly — it's encoded in the cache key via
`_cache_key(text, voice, model_id)` in `render_audio.py`. Switching
models invalidates every prior cache entry, which is the correct
provenance behaviour. The `phase4_audio` DVC stage doesn't currently
hash the model ID as an explicit param, but `enrichment/render_audio.py`
is a dep and changing its default there would flag every stage stale;
if the model is passed as a CLI arg rather than edited into code, the
DVC dep chain does *not* see it. Adding `--model` as a tracked param
(or, better, promoting it to `params.yaml`) is the right
accompanying change.

**Audio-tag control (Gemini 3.1 only).** The new model accepts
inline tags like `[warm]`, `[whispered]`, `[slow]`, `[laughter]` in
the prompt text. The current `build_turn_prompt` already emits
bracketed directives (`(Speak slowly and deliberately.)`) that Gemini
2.5 interprets via LLM reading of the prompt; 3.1 exposes a
structured tag vocabulary that is more reliable. If switching to 3.1,
the `tts_profiles/classic.py` prompt builder can be simplified to
emit the canonical tags instead of natural-language instructions.

**Voice-drift note.** We have an observed voice-drift issue on Gemini
2.5 Flash TTS on some runs (bead BleakHouse-z4v). Whether 3.1 Flash
has the same behaviour is **unverified in this codebase**; it must be
measured before claiming either way.

## Where Claude is not used

- Passage enrichment (pre-pipeline fixture step).
- Phase 1+2 matching (optimal transport / embeddings — numeric).
- Phase 4 audio (Gemini TTS).

## Summary

| Phase | Script | LLM / engine | Output |
|---|---|---|---|
| 0 | `design_segments.py` | Claude Haiku 4.5 | `phase0_segments.json` |
| 1+2 | `run_pipeline.py` (three dispatchers) | none (numeric) | `phase1_assignments.json`, `phase2_plan.json` |
| 2.5 | `host_prep.py` | Claude Haiku 4.5 + Sonnet 4.6 | `phase2_5_{host_briefs,interviews,reading_list}.json` |
| 3 | `generate_podcast.py` | Claude Sonnet 4.6 (configurable) | `phase3_episode.json` |
| 4 post | `post_phase3.py`, `build_manifest.py`, `build_report.py`, `precompute_quote_verification.py` | Claude (quote verify only) | `report.txt`, `manifest.json`, `report.html`, `quote_verification.json` |
| 4 audio | `render_audio.py` + `tts_profiles/classic.py` | Gemini 2.5 Flash TTS (default); Gemini 3.1 Flash TTS once the CLI change above is in | `audio/podcast.mp3` (symlink into DVC cache) |

## Sources (Gemini 3.1 Flash TTS verification, 2026-04-24)

- [Gemini 3.1 Flash TTS preview (Google AI Developers docs)](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-tts-preview)
- [Gemini 3.1 Flash TTS: New text-to-speech AI model (Google blog)](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-1-flash-tts/)
- [Gemini 3.1 Flash Audio model card (Google DeepMind)](https://deepmind.google/models/model-cards/gemini-3-1-flash-audio/)
