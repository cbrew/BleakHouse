# Qwen3-TTS ICL mode is unusable — A/B 2026-04-27

**Question:** Can we fix the Host's drifting British accent by switching off
`x_vector_only_mode=True` and letting the full ICL path (ref_audio + ref_text)
do its job?

**Answer: no, twice over.**

## Method

`experiments/qwen_tts/icl_ab.py` rendered 5 diagnostic sentences for the Host
voice (Sulafat / Gemini ref clip from `bh_trn_literary`) in two modes:

- `x_vector_only_mode=True`  — the current production path
- `x_vector_only_mode=False` — full ICL with `ref_text` from the sidecar

Run on pop-os with `Qwen/Qwen3-TTS-12Hz-0.6B-Base` via the pinned `qwen-tts`
package. Server stopped to free GPU.

## Findings

### 1. Frequent EOS-stall in ICL mode (2/5 sentences)

| sentence | xvec=True audio | xvec=False audio | xvec=False outcome |
|---|---|---|---|
| 01 chancery | ~5 s | ~10 s | ok-ish |
| 02 remarkable | ~5 s | **164 s** | **stall — hit max_new_tokens=2048** |
| 03 welcome | ~5 s | **164 s** | **stall** |
| 04 chapter | ~5 s | ~15 s | ok-ish |
| 05 fog | ~5 s | ~5 s | ok-ish |

40% of one-line sentences stall completely. The model's EOS path doesn't fire,
generation runs to the token cap, and we get ~3 minutes of garbage instead of
a 5-second sentence. This is exactly the bug the production code was already
working around.

### 2. The 3 *non-stall* ICL outputs are nonsense

Listening test: the three sentences that didn't stall in ICL mode produced
audio that user judged "total nonsense" — i.e., the path is broken even when
it terminates. So the bug isn't only EOS — the ref-text conditioning itself
isn't working in this model+library combo for our reference distribution.

## Implication

There is no cheap path to fix Host's accent drift on the existing model. The
production `x_vector_only_mode=True` is the best Qwen3-TTS can do with these
ref clips, and accent drift is intrinsic to that path (speaker-embedding-only
conditioning captures timbre, not accent).

The right fix is fine-tuning a per-speaker model — see plan
`2026-04-27-host-f5tts-finetune-spike.md`.

## Artefacts

- Wavs: `/tmp/qwen_icl_ab/` on the Mac (not committed; subjective listening
  artifact)
- Script: `experiments/qwen_tts/icl_ab.py`
