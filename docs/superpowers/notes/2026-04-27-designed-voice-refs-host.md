# Designed reference clips beat per-run extracted refs — Host A/B/C

**Date:** 2026-04-27
**Issue:** [BleakHouse-9lk](../../../) — Designed reference clips per persona

## Problem

The current pipeline calls `extract_refs.py` per render to slice a 15 s
reference clip from the start of the first Host turn of *that episode's*
podcast.mp3. This has three structural defects:

- **Always opener-shaped.** The first 15 s of any Host turn is a "Welcome
  to Bleak House Unpacked…" cadence — statement register, no vocatives,
  no questions, no em-dash beats. The speaker encoder sees only one slice
  of Host's prosodic palette.
- **Per-episode, unversioned.** Each run's ref is whatever Gemini happened
  to produce on the day of that render. Voice-drift in any single episode
  contaminates that episode's ref.
- **Content-keyed.** The ref's transcript overlaps heavily with the test
  audio's transcript when those passages discuss the same novel — so any
  apparent quality is partly memorisation of nearby phrases, not
  generalisation.

## Hypothesis

Qwen3-TTS's speaker encoder produces a single fixed-size embedding by
integrating over the entire ref clip. A *designed* ref, stitched from
clips that cover Host's prosodic slot taxonomy (opener · vocative
address · double-em-dash aside · multi-clause sentence · synthesis-
starter · pivot), will produce a more accent-stable speaker embedding
than the production single-clip approach.

## Method

**Three reference strategies** applied to the same 10 test sentences via
the same `generate_voice_clone(..., x_vector_only_mode=True)` call:

| Ref | Source | Length | Shape |
|---|---|---|---|
| Production | `extract_refs.py` first 15 s of one episode's first Host turn | 15 s | always opener |
| Greedy concat | 5 longest clips from F0-filtered Host pool | 60 s | mostly opener-ish |
| Designed | 6 slot-matched clips, one per prosodic role | 73 s | opener + 5 different prosodic shapes |

All three refs draw from the same 76-clip F0-filtered Host pool produced
by `scripts/build_voice_pool.py` (Sulafat-range F0 195–295 Hz). All other
parameters held constant.

**Test sentences:** 10 held-out sentences, content-disjoint from the
designed ref's transcript (verified zero content-word overlap by
`scripts/check_test_overlap.py`). Three categories:

- **In-register, disjoint content** (3): Host-shaped panel-discussion
  sentences about non-Bleak-House topics (Brontë, Hardy/Eliot, Yorkshire).
- **Out-of-register** (4): everyday non-literary content with British
  markers (Edinburgh-Doncaster train, kettle/biscuits, Lord's cricket,
  Cumbria/Adirondacks).
- **Phonetic contrast** (3): engineered for specific diagnostics — BATH/
  TRAP split, British-coded vocabulary (lorry/queue/roundabout/bypass),
  L-vocalisation + rhotic R.

**Why phonetic coverage is heuristic.** Maximising phonetic coverage of
a corpus is set-cover, NP-complete (Karp 1972). The unit-selection
tradition (Black & Lenzo's FestVox work at CMU) settled on greedy +
register-shaped heuristics for the same reason. We pick clips matching
*prosodic structure* (em-dash, vocative, comma-density) on the assumption
that prosodic coverage correlates with the phonetic coverage that
actually matters for Qwen's speaker encoder.

## Result

**Verdict (subjective listening, single listener, n=10 sentences):**
designed > greedy concat ≈ production. All three are usable; the
designed ref is the one to ship.

The designed ref's audible differences:
- Accent stability across all 10 sentences, including the out-of-register
  category that the encoder has nothing in the ref to anchor on.
- The phonetic-contrast sentences (`08_bath`, `09_lorry`, `10_dancer`)
  retained British features — the BATH vowel, the rhotic R drop, the
  L-vocalisation — that they didn't always retain in production.
- Prosody more in keeping with Host's actual rhythm than the production
  ref produces, presumably because the encoder saw vocative addresses
  and em-dash beats during the integration.

## What this implies

**Ship the designed-ref approach.** The result was strong enough on
Host to invest in per-persona slot design for the rest of the panel.
The pipeline change is small: replace the per-run `extract_refs.py`
call with a lookup of `data/voice_refs/v1/<persona>/ref.wav`.

**Idempotency hash needs a ref-version field.** The `qwen-tts-server`
job hash currently digests inputs (manifest, phase3_episode, ref source
mp3) + renderer code rev. With designed refs, the ref is no longer a
function of the input mp3 — it's a versioned artefact. Adding the ref
version to the hash means `v1 → v2` correctly invalidates cached jobs.

## Limitations

This is a sniff test, not a full evaluation:

- **Single listener, single session.** No blinding, no inter-rater
  reliability, no statistical test.
- **10 sentences ≠ 600+ utterances.** A full episode renders 600–730
  utterances; cumulative drift over that scale isn't captured.
- **One persona.** Host has a recognisable prosodic palette (welcomes,
  vocatives, pivots). Whether the slot taxonomy generalises is what the
  Blackstone test is for next.
- **Slot taxonomy is one of many.** No quote-setup, no sign-off, no
  list-with-parallel-structure. These may matter; we don't know.
- **The greedy-concat baseline already sounds good.** The marginal win
  of designed-over-greedy is real but smaller than the win of
  long-over-15-s. Most of the gain may come from "more material" rather
  than from "designed material."

## Next

- **Blackstone (in progress).** Same recipe, persona-specific slot
  taxonomy. Decides whether the design generalises or whether each
  persona will need bespoke slot work.
- **Pipeline integration.** Once two personas validate, replace the
  per-run `extract_refs.py` call with a frozen-ref lookup + ref-version
  in the job hash.
- **Eight more personas.** Hartley, Woodcourt, Edmund Leigh, Daniel Rosen,
  Trevelyan, Chen, Martinez, Volkov.

## Artefacts

- `data/voice_refs/v1/Host/ref.wav` (73.2 s) + `ref.json` (slot provenance)
- `data/voice_refs/v1/test_sentences.json` (10 held-out)
- `scripts/build_voice_pool.py` — per-speaker clean clip pool builder
- `scripts/build_voice_ref.py` — slot-matched ref stitcher
- `scripts/check_test_overlap.py` — vocab-disjointness verifier
- `scripts/render_qwen_diagnostic.py` — ref-comparison renderer
- Listening wavs at `/tmp/heldout_{designed,greedy,production}/` (not
  committed; regenerable)
