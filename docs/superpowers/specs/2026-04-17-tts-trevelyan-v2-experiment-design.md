# Experimental TTS profile: `trevelyan_v2`

**Date:** 2026-04-17
**Author:** CB + Claude
**Status:** Design — awaiting implementation

## Goal

Produce one alternative audio rendering of the canonical Trevelyan-panel Bleak House episode, using `gemini-3.1-flash-tts-preview` and the full six-part prompting scheme documented at <https://ai.google.dev/gemini-api/docs/speech-generation#prompting-strategies>. The existing rendering path must remain the default and be untouched in behaviour. This is an experiment, not a migration.

## Source episode

`data/runs/ext_v19_all_swapped_hostprep/phase3_episode.json` — the "Literary Panel B" (Trevelyan, Leigh, Rosen) run linked from `webapp/pages/examples.html:141`. Transport + host preparation. Use the whole episode; no segment filtering.

## Architecture

Introduce a `TTSProfile` abstraction. Selection via a new `--profile {classic,trevelyan_v2}` CLI flag on `enrichment/render_audio.py`. Default = `classic`, which preserves current behaviour byte-for-byte.

```
enrichment/
  render_audio.py            # gains --profile flag; all fixed prompt/voice logic moves
                             # behind the profile. Pause insertion scales by profile.pause_scale.
  tts_profiles/
    __init__.py              # PROFILES registry {"classic", "trevelyan_v2"}
    base.py                  # TTSProfile Protocol
    classic.py               # wraps existing SPEAKER_VOICES/ACCENTS/POLICIES + current prompt
    trevelyan_v2.py          # new profile (3.1 model, six-strategy prompting, reduced pauses)
```

`TTSProfile` protocol:

```python
class TTSProfile(Protocol):
    name: str
    model_id: str
    cache_namespace: str          # isolates cache dir per profile
    pause_scale: float            # multiplier for leading/trailing/segment silence
    def voice_name(speaker: str) -> str: ...
    def build_turn_prompt(turn: Turn, ctx: EpisodeContext) -> str: ...
```

`EpisodeContext` (new, internal):

```python
@dataclass
class EpisodeContext:
    episode_title: str
    segment_title: str
    segment_index: int
    turn_index: int
    previous_turn: Turn | None    # for Sample Context
```

Cache path moves from `data/tts_cache/<hash>.wav` to `data/tts_cache/<profile.cache_namespace>/<hash>.wav`. Classic's namespace = `classic`; existing cache files are re-homed on first run or (simpler) left orphaned — acceptable as the cache is regenerable.

Output naming: when `args.profile != "classic"`, suffix the filename → `podcast_trevelyan_v2.mp3` in the `PODCAST_AUDIO_DIR/<run>/` directory.

## `trevelyan_v2` content

### Model

`gemini-3.1-flash-tts-preview`. PCM 24 kHz mono, same as current.

### Scene (shared — prepended to every turn prompt)

```
## THE SCENE
A BBC Radio 4 studio, early evening. Four participants seated at a round oak
table, each with a boom-mounted microphone. Soft foam acoustic panels; the
faint hum of studio gear. The tone is In Our Time — measured, literary,
unhurried, but the conversation flows: participants pick up each other's
threads with minimal dead air and the host treats silence as a tool, not a
default. The red RECORD light is on; the host has just wrapped the
introduction.
```

### Audio Profiles (per speaker)

```
# AUDIO PROFILE: Host / "The chair"
A veteran BBC Radio 4 presenter, around 80 years old. Educated RP with
northern English colouring — grammar-school in the West Riding, then
Cambridge. Low, generous timbre; the voice of someone who has interviewed
everyone and is still curious. Treats questions as invitations. Never hurries
a guest, but never leaves dead air either.

# AUDIO PROFILE: Oliver Trevelyan / "The reader-performer"
An English actor and audiobook artist, male, born in the late 1950s.
Educated at Uppingham School and Cambridge. Received Pronunciation of that
generation: resonant lower register, theatrical timing, a touch of avuncular
warmth. A man who has read Dickens aloud for a living and relishes a good
anecdote. Never hurried; always moving forward.

# AUDIO PROFILE: Edmund Leigh / "The don"
Emeritus Oxford don, late 60s, Victorianist. Patrician RP with faint
pre-war inflections. Dry, aphoristic, allergic to cliché. His pauses do as
much work as his sentences — but those pauses are chosen, not habitual.

# AUDIO PROFILE: Daniel Rosen / "The critic"
London-based critic, early 40s, trained between New York and UCL. Clear
London cadence with American emphasis patterns. Direct, argumentative,
intellectually quick; tends to press a point hard, then soften it with a
joke. Forward momentum is his default.
```

These Audio Profile strings live in `trevelyan_v2.py` as a dict keyed by speaker name, with a sensible fallback for any unexpected speaker.

### Director's Notes (per turn)

Generated from existing `VoicePolicy` (via `enrichment/podcast_types.py`) plus per-utterance `Utterance` fields, but reformatted under the 3.1 heading structure and **tuned for flow**:

```
### DIRECTOR'S NOTES
Style: {policy.style} — {elaboration from a style→phrase table in trevelyan_v2.py; covers all style ids used by the eleven speakers defined in render_audio.py}
Pacing: {derived from rate × policy.rate}. Prefer forward momentum; let
  sentences connect without settling. Pauses only where a thought genuinely
  demands one.
Articulation: {derived from energy + emphasis_words}
Accent: {speaker accent string — Trevelyan's is exactly the spec above}
Breathing: {add only if any utterance has pause_before_ms > 600}
```

Flow-tuning rules (encoded in `trevelyan_v2.py`):

- Raise `_rate_direction` thresholds so a rate of 0.96–1.04 emits no special pace instruction (flow is the default).
- Drop `[hesitantly]` entirely — its use in classic contributed to the cautious feel the user flagged.
- `emphasis_words` → single Director's Note line ("Give light emphasis to: …"), not an inline tag.

### Sample Context (per turn)

One synthesised line drawn from the preceding turn:

```
### SAMPLE CONTEXT
You are responding to {previous_turn.speaker}. They have just said:
"{previous_turn.utterances[-1].text}"
The segment is "{segment_title}".
```

Verbatim quoting avoids an extra LLM call to summarise. If `previous_turn is None` (first turn of episode), omit the section entirely and rely on Scene + Audio Profile to set the opener.

### Transcript with Audio Tags

```
#### TRANSCRIPT
{text, with inline audio tags derived from quote_mode:}
  quote_mode == "setup"     → leading [curious]
  quote_mode == "reading"   → leading [serious]
                              + Director's Note: "Read as a direct literary
                                quotation; slower, savoured."
  quote_mode == "commentary" → no tag
  quote_mode == "none"      → no tag
```

No other automatic tag insertions. Emphasis handled through Director's Notes.

### Pause scaling

`classic.pause_scale = 1.0`; `trevelyan_v2.pause_scale = 0.5`.

Applied in `_apply_turn_pauses` to:

- leading silence (`first.pause_before_ms`)
- trailing silence beyond the 300 ms default (`last.pause_after_ms - 300`)

And in `render_episode` to the 2000 ms inter-segment gap. Profile plumbed through via a new parameter or a small `RenderState` dataclass — whichever reads cleanest.

### Voice selection

Keep the existing `SPEAKER_VOICES` prebuilt voices for v2 (Sulafat for Host, Algenib for Leigh, Alnilam for Rosen, Achird for Trevelyan). The Audio Profile text does the heavy lifting. If a voice clearly conflicts with the persona text in listening, iterate in a later pass; not in scope here.

## CLI surface

```
uv run python -m enrichment.render_audio \
    --run ext_v19_all_swapped_hostprep \
    --profile trevelyan_v2
```

- `--profile` defaults to `classic`.
- Existing `--model flash|pro` flag applies only when `--profile=classic`; under `trevelyan_v2` the model is fixed (the profile owns its model id).
- Output: `/Volumes/Crucial X9/bleakhouse_audio/ext_v19_all_swapped_hostprep/podcast_trevelyan_v2.mp3`.

## Testing

- Unit test: `build_turn_prompt` for `trevelyan_v2` emits all six required headers for a turn with a preceding turn; omits `### SAMPLE CONTEXT` when previous is `None`; inserts `[serious]` for a `quote_reading` utterance and `[curious]` for `quote_setup`.
- Unit test: pause scaling — for a `Turn` with `pause_before_ms=800` and `pause_after_ms=1500`, the rendered segment under `pause_scale=0.5` has half the leading silence and half the extra trailing silence compared to `pause_scale=1.0`. No real TTS call required — drive with a stub `render_turn` that returns a known audio chunk.
- Unit test: cache keys for the same `(turn, voice)` under `classic` and `trevelyan_v2` land in distinct directories and do not collide.
- Integration smoke test: render a single segment with `--segment 0 --profile trevelyan_v2` and confirm an MP3 of plausible length is written. This is a manual step the first time the API is hit, not part of the automated suite.

## Acceptance criteria

- `uv run python -m enrichment.render_audio --run ext_v19_all_swapped_hostprep` (no `--profile`) produces byte-identical audio to the classic output it would have produced before this change (confirmed by re-running with primed cache).
- `uv run python -m enrichment.render_audio --run ext_v19_all_swapped_hostprep --profile trevelyan_v2` writes a new MP3 at the documented path.
- All unit tests above pass.
- `uv run ruff check .`, `uv run pyright`, `uv run mypy .` all clean on the changed files.
- Zero pre-existing ruff errors left behind (per project policy).

## Deferred / out of scope

- Two-speaker multi-speaker calls for Host↔panellist exchanges (the 3.1 API caps multi-speaker at 2, so a 4-person roundtable still renders turn-by-turn; pairing is a separate experiment).
- Richer / sentiment-aware audio-tag selection.
- Revising voice selection (prebuilt voice names).
- Any change to upstream episode generation (Phase 0–3).
- Auto-migrating the classic cache into the new per-profile directory.

## Open questions

None outstanding for implementation. If the v2 audio reveals that `pause_scale=0.5` over-compresses, tune by ear in a follow-up — not by redesigning.
