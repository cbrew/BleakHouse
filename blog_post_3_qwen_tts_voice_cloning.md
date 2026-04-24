# Cloning Podcast Voices with Qwen3-TTS

*What happens when you try to reproduce an existing AI-rendered podcast in a different voice engine — and everything the plumbing has been hiding comes out of the walls at once*

---

## The Starting Question

We have a literary-podcast pipeline that generates ~45-minute episodes: an LLM writes a multi-voice script (host + three expert personas discussing Dickens), and Gemini TTS turns it into audio. Rendering a single episode through Gemini is fine at one-off scale, but across 192 canonical runs the API bill adds up, and we wanted to experiment with cheaper, self-hostable alternatives.

The deeper goal, not just cost: **eventually, let listeners join the conversation as a fifth participant.** The listener contributes their own turn — by voice or by chat — and the four AI panelists (host + three experts) react to them in character. We're not synthesising the listener's voice; we're synthesising *the panel's responses to them*, on demand, quickly enough that it feels like joining a room rather than submitting a forum post. That requires two things the current pipeline doesn't have yet — tolerable latency from a listener's turn to the first audible response, and voices stable enough that the panel still sounds like itself when it speaks extemporaneously. Batch rendering is the staging ground; interactive is the destination.

The obvious candidate: Qwen. Alibaba's Qwen3 family has a dedicated text-to-speech model, Apache-licensed, with zero-shot voice cloning. Documentation claims 97 ms streaming latency on big hardware. If it worked, we could render variants locally on a single NVIDIA card, compare them against the Gemini baseline, and start poking at what the interactive path would cost.

This post is the story of *actually doing that* — which turned into a tour of every provenance assumption the pipeline had been quietly leaning on.

---

## Wrong Tool, Right Family

First mistake: I reached for **Qwen2.5-Omni-3B**, the one that shows up first in a HuggingFace search for "Qwen TTS". It is a 3B-parameter *any-to-any* multimodal model — text + vision + audio in, text + audio out. Only two voices ("Chelsie", "Ethan"), no cloning, `qwen-research` license (non-commercial), and it drags in `torch + torchvision + transformers + accelerate` to the tune of ~2.4 GB of Python packages before you download the 6 GB of weights.

Omni rendered a hello-world sentence fine. But the user quickly pushed back: *"is there a good reason to use Omni rather than a TTS-specific one? don't much want bloat in the .venv."*

There isn't. The right tool is **Qwen3-TTS** — a dedicated `qwen-tts` pip package the Qwen team ships separately:

- `Qwen3-TTS-12Hz-0.6B-Base` — 0.6 B parameters, Apache 2.0, supports zero-shot voice cloning from a ~6–10 s reference clip
- Proper Python API: `Qwen3TTSModel.from_pretrained(...).generate_voice_clone(text=..., ref_audio=..., ref_text=...)`
- Eleven input languages; 97 ms streaming latency on beefy hardware

Lesson: *"Qwen" isn't a single thing.* Search for the task, not the brand.

## The Cloning Setup

Voice cloning needs two things per target speaker: a reference audio clip and (for best fidelity) its transcript. We already have both — the existing Gemini episodes are sitting on disk as MP3s alongside manifest files that carry per-turn timestamps:

```json
{
  "turns": [
    {"speaker": "Host",            "start_ms": 0,       "end_ms": 76000,  ...},
    {"speaker": "James Blackstone", "start_ms": 76200,  "end_ms": 128600, ...},
    {"speaker": "Eleanor Hartley",  "start_ms": 128800, "end_ms": 177700, ...}
  ]
}
```

Plan: for each of the four speakers, find their longest single turn, slice the matching time range out of `podcast.mp3`, save as a WAV, and use that as the voice-cloning reference.

First implementation: extract the **longest** turn per speaker, skip 200 ms of lead-in, keep 15 s. Ran `render_episode.py`, kicked off 363 utterances, came back 15 minutes later.

Result: segment 0 came out with **all-female voices**, regardless of speaker.

## Bug 1: The Reference Clips Are Wrong

First instinct was to blame the voice-cloning model. Instead I measured F0 (median pitch) on every reference clip itself:

| speaker | F0 of extracted clip | expected |
|---|---|---|
| Host | 253 Hz (female) | female ✓ (Sulafat voice in Gemini config) |
| James Blackstone | **215 Hz (female)** | male ✗ |
| Eleanor Hartley | 212 Hz (female) | female ✓ |
| Caroline Woodcourt | 197 Hz (female) | female ✓ |

Blackstone was the surprise. The Gemini voice configured for him is `Sadaltager` — a male voice. But the clip we extracted from `podcast.mp3` at his "longest turn" time range sounded female.

Why? **Two independent drifts**, neatly hidden by the file layout:

1. **Manifest timing drift.** `manifest.total_duration_ms = 2804 s` but the actual `podcast.mp3` was **3184 s** — a ~6-minute gap. Something in the Gemini render path had inserted silences or transitions that the manifest never learned about. When we sliced the MP3 at "James's longest turn: 1624 s", we were reading ~6 minutes downstream of where James actually was.
2. **Gemini voice-assignment drift.** Even correcting for timing and picking each speaker's *first* turn (low drift near the start) revealed a second bug: probing F0 at successive JB turns gave **139 Hz (male, correct), then 194, 203, 289, 197 (all wrong)**. Gemini was rendering the first turn of each speaker with the configured voice, then drifting onto different voices for later turns. This had been there for months and nobody had noticed because nobody had measured.

Fixes: pick each speaker's first turn, skip `max(2000 ms, 25 %)` of the turn's duration (drift absorbs the first couple of seconds), and **verify by F0** before trusting the clip — if the detected gender doesn't match the speaker's expected gender from `params.yaml`, warn loudly.

After this, references were gender-correct:
```
Host              229 Hz  female  ✓
James Blackstone  123 Hz  male    ✓
Eleanor Hartley   241 Hz  female  ✓
Caroline Woodcourt 214 Hz  female  ✓
```

The Gemini bug is real and was logged as its own issue to chase separately. The reference-extraction fix works around it.

## Bug 2: fp16 Softmax Nans on Both Edge Platforms

Qwen3-TTS contains an autoregressive code-predictor that emits VQ codes, which a separate neural vocoder turns into waveform samples. Samples from the code-predictor's softmax are drawn with `torch.multinomial`.

On both **MPS (Apple Silicon)** and **CUDA Turing (RTX 2070 Super, compute 7.5)**, running the model in fp16 produced:

```
RuntimeError: probability tensor contains either `inf`, `nan` or element < 0
```

The code-predictor's pre-softmax logits overflow in fp16; the softmax output then contains NaN or negative values, and `multinomial` refuses to sample. On Ampere+ GPUs (sm_80+) you'd switch to bf16 and the problem goes away, but Turing doesn't have bf16 and Apple Silicon's bf16 support is spotty. fp32 works; it's slower but correct.

We picked dtype at runtime:

```python
if torch.cuda.is_available():
    major, _ = torch.cuda.get_device_capability()
    dtype = torch.bfloat16 if major >= 8 else torch.float32
elif torch.backends.mps.is_available():
    dtype = torch.float32
```

## Bug 3: ICL Mode Stalls for Certain Clips

The cloning API has two modes:

- **ICL mode** (`x_vector_only_mode=False` + `ref_text=`): full in-context learning. Best voice fidelity.
- **x-vector mode** (`x_vector_only_mode=True`, no `ref_text`): uses only the reference speaker embedding. Faster, slightly less faithful.

Rendering the episode in ICL mode, utterance 9 hung. GPU was 41 % utilized, memory steady — the generation loop was doing something, but no output. After 15 minutes of no progress, I killed it.

Reproduced the stall in isolation: the same `(text, ref_audio, ref_text)` tuple for JB hangs in ICL but completes in 3.6 s in x-vector mode. The code-predictor enters a state where it never emits its end-of-sequence token. With `x_vector_only_mode=True` and `max_new_tokens=1024`, it's been reliable across hundreds of utterances.

Fidelity cost was acceptable: gender is preserved, speaker identity is *roughly* right but less crisp than Gemini's native voices. For our purposes — where reliability matters more than pitch-perfect cloning — it's the right trade.

## Performance

Same first utterance ("*The fog is everywhere, and yet I feel at home in it.*" — 11 words, ~4 s of audio), measured on three configurations:

| hardware | dtype | wall | realtime |
|---|---|---|---|
| M1 Pro / MPS | fp32 | 22.3 s | 0.18× |
| 2070 Super / CUDA (Turing) | fp32 | 6.1 s | 0.65× |
| 2070 Super, warm start | fp32 | 7.0 s | 0.67× |

**3.6× speedup** going from MPS to CUDA. Still sub-realtime because fp16 is out (bug 2) and Turing has no bf16. On Ampere+ with bf16 and flash-attention the same model would comfortably exceed 1× RT.

The full-episode render (363 utterances → 47.5 min audio) completed in **56.5 min wall** (0.84× RT on the 2070 Super). That's workable: a full episode every ~hour, versus the minutes-to-get-rate-limited experience on the Gemini API.

## The Deeper Lesson

Four bugs surfaced in the space of one afternoon:

1. Gemini voice assignment drifts within an episode.
2. Manifests and rendered audio disagree on total duration.
3. fp16 softmax NaNs on two different platforms.
4. ICL-mode voice cloning stalls for some reference-text pairings.

Only (3) and (4) are Qwen's fault. (1) and (2) were sitting in our Gemini renders the whole time, and we'd never hit them because nothing in the pipeline ever *asked* "is this audio consistent with what the manifest claims, and with the current voice config?". The files are in the run directory, git tracks them, case closed — except the content of the audio depended on a `SPEAKER_VOICES` mapping that had since changed, on a rendering pass that had been re-run with different pauses, on a set of utterance pause timings that were never re-synced with the actual MP3.

This motivated adopting **DVC** (Data Version Control) for the whole pipeline. Declare every phase's inputs and outputs; hash both sides; let the tool tell you when an artifact is stale. After DVC was wired up, editing `SPEAKER_VOICES.Host` lit up every audio-bearing run as stale within a second. The deploy script now refuses to ship stale runs.

That, more than Qwen itself, is the lasting win from this experiment.

## Current State

For the apples-to-apples Gemini-vs-Qwen comparison, the right script to render through both engines is a *hostprep* script — one built from a Phase 2.5 host brief, where the host asks explicit questions and steers between experts. A separate investigation showed that non-hostprep scripts generate host-light dialogue (on average **1.8** interior host turns per episode vs **20.9** with hostprep; 30% of non-hostprep runs have zero interior host turns). That's being re-rendered now: `bh_trn_literary_hostprep`'s 726-utterance script running through Qwen3-TTS, same reference clips, ~1h50m wall.

When that finishes, we'll have a matched pair: the same script, the same four cloned voices, rendered by two different TTS engines. Whatever that comparison says, the plumbing around it now actually tells us what it's comparing.

## Where It Doesn't Reach (Yet)

The batch-render numbers (0.84× real-time end-to-end) are workable for offline episodes, but they're at least an order of magnitude off the "fifth person in the room" use case. For that we need:

- **Time-to-first-sound well under a second** after the listener finishes their turn, so the panel's reply feels like a response rather than a queued job. For voice-input listeners this compounds with STT latency; for chat-input listeners the TTS is the whole critical path.
- **Sustained throughput above 1× real-time** with headroom, so the panel can keep replying while the next utterance is still decoding and listeners can interrupt each other naturally.
- **Quality parity with the named voice** while the reference is a few seconds of recorded audio, because listeners will notice the host sounding subtly different mid-conversation far more than they notice it in a pre-rendered episode.

The speed gap is probably solvable without a model change — Qwen3-TTS has a streaming mode (text-in streaming, audio-out streaming) that we haven't exercised, the 2070 Super is ancient by 2026 standards, and Turing's lack of bf16 is the specific reason we're stuck on fp32 here. On an Ampere or better card with flash-attention enabled and bf16 weights, published numbers for this family comfortably clear 2× RT. The quality gap is less obvious: `x_vector_only_mode` is giving up fidelity we might actually need when a listener's ear is on it and the panel is improvising rather than following a pre-written script. ICL mode was too flaky in batch; in an interactive setting with one carefully-curated reference per voice, it may behave better.

Neither is here today. But the same experiment now has a defined baseline ("at 0.84× RT on a 2070 Super with x-vector cloning, this is what 363 utterances of Bleak House sound like"), and it has provenance machinery that will tell us whether a later-today version is actually better or just different.
