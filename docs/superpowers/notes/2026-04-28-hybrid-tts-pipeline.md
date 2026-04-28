# Hybrid TTS pipeline — accent-permissive vs accent-distinctive personas

**Date:** 2026-04-28
**Issue:** [BleakHouse-9lk](../../../) (designed refs) + follow-ups filed below.
**Companion:** [2026-04-27-designed-voice-refs-host.md](2026-04-27-designed-voice-refs-host.md)

## Summary

The accent-drift problem we set out to solve has **two distinct sources**, each requiring a different fix:

| Source of accent drift | Affected personas | Fix |
|---|---|---|
| Single-clip ref shape (always opener), per-run extraction, content-keyed | Host, possibly all panelists | Designed reference clips (BleakHouse-9lk — shipped for Host) |
| Qwen3-TTS's tokenizer architecture systematically discards accent at quantisation | Blackstone (Edinburgh), Woodcourt (Bristol), and probably any persona spec'd with a non-RP / non-General-American accent | **Hybrid pipeline:** route accent-distinctive personas to Gemini, accent-permissive ones to Qwen + designed ref |

The first finding (Host) is documented in the [companion note](2026-04-27-designed-voice-refs-host.md). This note covers the second.

## The Blackstone observation

After designing a Blackstone reference clip (73 s, 6 prosodic slots, all clips F0-validated as male in the 95–170 Hz range), all three ref strategies (production / greedy concat / designed) produced English RP-ish output. None was Scottish. Gemini's source rendering of the same Blackstone is "really really really Scottish — exactly the intended educated persona" (user's listening verdict). So the source has the accent we want; the Qwen pipeline is destroying it.

## The diagnosis

Two independent lines of evidence point at the same architectural cause.

### Direct inspection of Qwen3-TTS-12Hz-0.6B-Base

```bash
$ grep "import.*Mimi" qwen_tts/core/tokenizer_12hz/modeling_qwen3_tts_tokenizer_v2.py
from transformers import MimiConfig, MimiModel
```

Qwen's 12 Hz tokenizer is **Mimi**, Kyutai's audio codec from the Moshi project. Mimi has two branches:

- An acoustic codec (RVQ over the waveform).
- A **semantic distillation** target trained against WavLM (a self-supervised speech model). The semantic branch is what makes Mimi suitable for LLM-style speech generation: it produces tokens that LLMs can predict autoregressively because they correlate with phonetic content.

The semantic distillation pulls from later WavLM layers — exactly the layers shown to compress out accent in favour of phonetic content.

### The Edinburgh paper

Zhong, Wang, Richmond, Bell, *Rethinking Discrete Speech Representation Tokens for Accent Generation*, arXiv:2601.19786 (v2, March 2026). University of Edinburgh CSTR.

Findings, quoted directly:

> "(1) choice of layers has the most significant impact on retaining accent information"
>
> "(2) accent information is substantially reduced by ASR supervision"
>
> "(3) naive codebook size reduction cannot effectively disentangle accent from phonetic and speaker information"
>
> "Predominant design of DSRTs for speech generation (quantising a later layer in a speech representation model, or using ASR supervision) discards most accent information."

The paper specifically calls out:

- **CosyVoice** uses "supervised semantic tokens, obtained by injecting FSQ in an internal ASR model encoder" — the destructive pattern.
- **Vevo** quantises layer 18 of HuBERT-large — a late layer, also destructive.
- The accent-preserving choice they validate is **HuBERT (non-finetuned), mid-early layers (layer 6 specifically)** — not what any current production TTS uses.

Qwen3-TTS-12Hz's WavLM-distilled Mimi tokens are the same family as the patterns the paper rules out. So the Blackstone failure isn't a Qwen-specific quirk; it's the predicted consequence of the entire current generation of LLM-friendly TTS tokenizers.

## What we cannot do (and why)

- **Better refs won't help.** The encoder gets a token sequence as input; if the tokens don't carry accent, no amount of ref material will reconstruct it. We empirically confirmed this with three ref strategies for Blackstone (production / greedy / designed) — all produced RP.
- **Codebook-size tweaks won't help.** Per Vevo's claim, falsified by Wells et al. (cited in the paper) and again by this paper's findings.
- **Fine-tuning Qwen on Scottish data probably won't help.** The tokenizer is upstream of fine-tuning; if accent is gone before the LLM sees it, the LLM has nothing to fine-tune toward.

## Decision: hybrid pipeline

Route TTS by persona's accent profile:

| Persona | Spec'd accent | Engine | Why |
|---|---|---|---|
| Host | RP / Home Counties | Qwen + designed ref (`v1/Host/`) | Well-trained Qwen mode; designed ref locks it in |
| Hartley | Cambridge | Qwen + designed ref (TBD) | RP-adjacent; expect to work |
| Trevelyan | Mild English | Qwen + designed ref (TBD) | RP-adjacent |
| Chen / Martinez / Volkov | American (CA / SW / East Coast) | Qwen + designed ref (TBD) | Well-trained Qwen mode |
| **Blackstone** | **Edinburgh / Scottish** | **Gemini direct** | Qwen flattens accent; Gemini renders correctly |
| **Woodcourt** | **Bristol West Country** | **Gemini direct** | Likely flattens; verify with Accent ABX (future work) |
| Edmund Leigh / Daniel Rosen | Distinct American regional | Qwen — verify | Probably works (American mode), but verify |

The render system already supports per-speaker voice configs (`enrichment/tts_profiles/classic.py`), so "speaker X uses engine Y" is a configuration change. Implementation tracked in **BleakHouse-8mv** (filed below).

The trade-off is honest: Gemini renders are slower and cost real money per minute. We accept that for the personas where the accent is the persona's identity — losing Scottish from Blackstone collapses him into "another English academic" and undoes the panel's design intent.

## Why this is a stronger position than "Qwen has a bug"

The Edinburgh paper turns the negative finding from "we couldn't make Qwen do Scottish" into "Qwen's tokenizer architecturally discards accent for the same reasons CosyVoice's and Vevo's do, per published Edinburgh CSTR research." That's a defensible architectural position. The hybrid pipeline isn't a workaround; it's the result of routing each persona to the engine whose representation can actually carry that persona's identifying features.

## Future work captured separately

- **BleakHouse-a2y** — Accent ABX screening harness. Before any future TTS swap (ElevenLabs, XTTS-v2, GPT-SoVITS, next-generation models), measure whether the candidate's tokens preserve accent on a held-out multi-accent set. Saves us from rediscovering this class of failure the hard way.
- **BleakHouse-9dh** — HuBERT-layer-6 + RepCodec accent-preserving render path. Research spike to replicate the paper's positive result, only worth doing if the hybrid pipeline ever proves insufficient.

## References

- Zhong, J., Wang, Y., Richmond, K., Bell, P. (2026). *Rethinking Discrete Speech Representation Tokens for Accent Generation.* arXiv:2601.19786. Code: https://github.com/jzmzhong/GenAID. Demo: https://jzmzhong.github.io/Accent-DSRT/
- Défossez, A. et al. (2024). *Moshi: a speech-text foundation model for real-time dialogue.* (Mimi tokenizer.)
- Companion note: [2026-04-27-designed-voice-refs-host.md](2026-04-27-designed-voice-refs-host.md)
