# Voice as Continuity: Cloning a Podcast Panel for Interactive Conversation

*How a literary podcast's cast of AI voices becomes an identity the listener can address directly*

---

## The Panel as a Named Cast

Our literary podcast pipeline, *Bleak House Unpacked*, produces ~45-minute episodes of structured conversation. A host convenes three named experts — Dr. Eleanor Hartley, the novelist-as-craft-teacher; Professor James Blackstone, the legal and social historian; Caroline Woodcourt, the lifelong close reader — and together they work through a passage of Dickens. Each expert has a written persona: intellectual lineage, analytical habits, rhetorical signature. The host steers; the experts respond in their own idiom. Across 194 canonical runs (fifteen novels, three expert panels, several retrieval pipelines), those four voices have become something approaching characters.

That identity is not just textual. It lives in how they sound. A listener who has heard Eleanor Hartley show why a single em-dash carries a sentence's weight has a particular voice in her ear when she sees Eleanor's name again. That voice is part of what makes the panel feel like *a room she has been in*, not simply a transcript she is reading.

The question this post is about: if the panel is this real as an artifact, can we let the listener join it?

---

## From Closed Episode to Shared Room

A batch-rendered podcast episode is a closed object. Audio exists or it doesn't; you press play or you don't. But the scripts our pipeline produces are explicit about who speaks when. Nothing about the data prevents an additional turn being inserted — from a listener asking the panel a question about a passage, and Eleanor or James or Caroline replying in character.

What prevents this, for now, is the rendering side. Gemini TTS produces excellent episode audio, but it doesn't let us put the listener in the conversation. The listener types a question and waits for a pre-packaged response; by the time the reply arrives, the sense of being *in the room* is gone.

The requirement is surprisingly specific:

- **Voice identity has to hold.** If the listener has to accept the host sounding subtly different when she replies, the conversational illusion fails. The same speaker has to arrive in the same voice whether the listener is meeting her at minute 37 of a pre-rendered episode or in a new exchange initiated this morning.
- **Latency has to be short enough that reply feels like response**, not queue-processing. The target is time-to-first-audible-sound well under a second after a listener turn ends.
- **It has to be self-hostable** so we can shape the turn-taking behaviour ourselves, including the subtle things a listener notices — who chooses to reply, how long the silence is before someone does, whether two voices overlap in agreement.

No single hosted TTS API meets all three at once today. Cloning an open-weight model does, at least in principle.

---

## Why Cloning, Not Casting

A cheaper move would be to cast new voices from a stock set — pick a British female timbre for Eleanor, a measured Edinburgh bass for James — and accept that these are not *exactly* the voices from the archive. Listeners know what new narrators sound like when audiobooks get re-recorded; they adjust.

We rejected this path. The panel is a 200-episode archive. The listener who has been with us has heard Eleanor for hours. A new voice at the point of interaction, however well cast, announces "this is a different project now." The whole point of the interactive experiment is that it should not feel that way.

Zero-shot voice cloning — synthesising new speech conditioned on a brief audio sample of a speaker — gives us a way to keep continuity. The existing archive is the training data for itself. For each voice, we extract a short clean clip from any previous episode and use it as the voice prompt for new utterances. The synthetic version isn't identical to the original, but it is within the range of natural variation: the same speaker, on a different day, saying something new.

---

## What Qwen3-TTS Contributes

Alibaba's Qwen team publishes a dedicated text-to-speech model, Qwen3-TTS-12Hz-0.6B-Base, under Apache 2.0. It is a fraction the size of the all-in-one multimodal models it sits next to in the Qwen family, and it is built specifically for the zero-shot cloning case: you provide a reference clip plus, optionally, its transcript, and the model generates new speech in that voice.

For our purposes this has three useful properties.

**It is small enough to self-host.** The weights fit on a consumer NVIDIA card. We don't need to lease an A100 to play with it. Our existing development machine renders a full Bleak House episode through the cloning pipeline in about an hour — slower than real-time by a small multiple, but well within "leave it running while you do something else."

**It is licensed for the use we care about.** Apache 2.0 means the interactive product, if this research path leads there, is not compromised by terms that assumed batch research use only.

**It takes references we already have.** Every episode in the archive ends up on disk as a rendered MP3 alongside a manifest that tells us which speaker holds the floor at which moment. For each panel voice, the first turn of the first segment of any episode gives us a clean ~10-second clip of that speaker alone. The archive functions as its own reference library.

---

## What a Cloned Episode Sounds Like

Rendered end-to-end on a single consumer GPU, the full literary-panel episode is 47.5 minutes of audio generated in 56.5 minutes of wall time — a 0.84× real-time ratio for a 726-utterance conversation spanning four distinct voices. Speaker transitions are preserved (the host actually hands to Eleanor, Eleanor to James, and so on); pause durations are taken from the script's own TTS annotations, so the rhythm matches what the original episode had.

The voices are recognisable as the panel. They are not indistinguishable from Gemini's original renders — zero-shot cloning at this model size gives up some fidelity, particularly in the distinctive prosodic habits of a specific voice — but the identity holds across the episode. A listener hearing a sample of cloned Eleanor and a sample of cloned James will correctly separate them, correctly label them by gender and general register, and often correctly identify them by name if they have heard the real episodes.

This is far short of production-grade podcast audio. It is clearly above the bar for *conversational continuity* — that is, for a listener to sustain the sense of being addressed by the same people they have been listening to.

---

## What It Unlocks

The point of this work is not the batch render. A batch-rendered episode in a second voice engine is a curiosity; the project already has one that sounds better.

The point is that the same machinery, exercised one turn at a time instead of in an 8-segment sweep, gives us a live panel. The listener asks a question. A turn generator decides which expert replies and drafts a response in their persona. The cloned voice renders that response and plays it — in the same voice the listener has been listening to for hours. Another expert chimes in. A back-and-forth unfolds.

That configuration — four AI panelists responding in their own voices to a fifth, human, participant — is the destination. The batch work here is what makes it *possible*. The remaining work is what will make it *fast enough* and *reliable enough* to be part of a listener's afternoon rather than a research demo. That work has its own plan, separately scoped, and is the subject of the next post in this series.

---

*Part 3 of the Bleak House Unpacked series. Part 1 covers the document-enrichment pipeline; Part 2 covers the optimal-transport matching that turns enrichment into aligned source-target pairs. The interactive-panel experiment will be Part 4.*
