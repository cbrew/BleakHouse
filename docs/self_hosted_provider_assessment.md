# Self-hosted-style providers (Modal, Runpod): assessment for BleakHouse

**Status:** evidence-based assessment, 2026-05-13. Companion to `docs/structured_output_review.html` which covered fully-managed serverless inference (DeepInfra, OpenAI, Anthropic, Together). This document covers the *next tier of management responsibility*: providers where the operator deploys their own vLLM container.

## TL;DR

For the BleakHouse workload as it stands today, **Modal and Runpod are 10-50× more expensive than serverless per-token pricing** for the small set of established open-weight models we care about (gpt-oss, DeepSeek-V4-Flash, Qwen3-Next, Gemma-4 26B-A4B-it). The crossover only flips when the GPU runs at sustained high utilisation — roughly equivalent to **~50 novel-onboarding cycles per month**, vs the project's actual ~1-2 cycles per month.

Self-hosted is worth keeping in the toolbox for four specific cases (private weights, custom fine-tunes, custom vLLM flags, no-serverless-host models) — not as the default.

## What these providers are

Both **Modal** and **Runpod Serverless** are *serverless GPU* platforms: you deploy a container, they handle queuing and autoscaling, you pay per second of compute. The model identity is yours to choose. There's no per-token meter; there's a per-second GPU meter.

This is operationally heavier than DeepInfra/Together (where you just hit `client.chat.completions.create(model="openai/gpt-oss-120b")`). You're responsible for:

- Writing the Dockerfile / Modal `@app.function` / Runpod template
- Picking + pinning the vLLM version
- Configuring vLLM flags (`--gpu-memory-utilization`, `--max-model-len`, `--max-num-seqs`, tensor-parallel size)
- Storing model weights somewhere that loads on container start (Modal Volume, Runpod Network Volume, or pulled from HuggingFace at boot)
- Cold-start tuning (FAST_BOOT, GPU memory snapshots)
- Monitoring (no built-in token-cost dashboard like DeepInfra's)

The upside is that the resulting endpoint is **OpenAI-compatible** in both cases — vLLM exposes `/v1/chat/completions` natively, so the rest of the BleakHouse seam (the `openai_compat` provider path) talks to it without changes. The seam already has slots for `"modal"` and `"runpod"` in `enrichment/llm/capabilities.py` and `enrichment/llm/providers/openai_compatible_provider.py`.

## Documented pricing (2026-05-13)

### Modal

Per-second GPU billing, scale-to-zero, no idle charges. From [modal.com/pricing](https://modal.com/pricing):

| GPU | $/second | $/hour |
|---|---|---|
| H200 | $0.001261 | ~$4.54 |
| H100 | $0.001097 | ~$3.95 |
| A100 80GB | $0.000694 | ~$2.50 |
| A100 40GB | $0.000583 | ~$2.10 |
| L4 | $0.000222 | ~$0.80 |
| T4 | $0.000164 | ~$0.59 |

Starter plan includes $30/month free credits, 10 GPU concurrency, 100 container max.

Cold start typically **2–4 seconds** per the comparison docs (faster with FAST_BOOT mode or GPU memory snapshots).

vLLM-in-OpenAI-compat-mode is the documented serving pattern. There's [a Modal example for Gemma + vLLM](https://modal.com/docs/examples/vllm_inference) that runs in ~60 seconds end-to-end. The deployed endpoint sits at `https://<workspace>--<app>.modal.run/v1/chat/completions` and takes no auth header by default (Modal's `token_id`/`token_secret` are for `modal deploy`, not for runtime calls — already noted in `enrichment/llm/providers/openai_compatible_provider.py`).

### Runpod Serverless

Per-second GPU billing, with a **two-tier rate**: "flex workers" scale to zero between requests; "active workers" run 24/7 at a discount. From [docs.runpod.io/serverless/pricing](https://docs.runpod.io/serverless/pricing):

| GPU | Memory | Flex $/s | Active $/s | Flex $/hr |
|---|---|---|---|---|
| B200 | 180GB | $0.00240 | $0.00190 | $8.64 |
| H200 PRO | 141GB | $0.00155 | $0.00124 | $5.58 |
| H100 PRO | 80GB | $0.00116 | $0.00093 | $4.18 |
| A100 | 80GB | $0.00076 | $0.00060 | $2.74 |
| L40, L40S, 6000 Ada PRO | 48GB | $0.00053 | $0.00037 | $1.91 |
| A6000, A40 | 48GB | $0.00034 | $0.00024 | $1.22 |
| L4, A5000, 3090 | 24GB | $0.00019 | $0.00013 | $0.68 |
| 4090 PRO | 24GB | $0.00031 | $0.00021 | $1.12 |

Cold start: **48% under 200ms**, idle timeout default 5 seconds before scale-down. Runpod claims faster cold starts than Modal on average; both are dramatically faster than full container boots.

vLLM templates are first-class; the [Runpod serverless overview](https://www.runpod.io/articles/guides/top-serverless-gpu-clouds) describes vLLM as the default inference stack.

## Cost crossover for BleakHouse

The decision turns on **GPU-hours required per workload** vs **per-token serverless rate**.

### Workload: one novel-onboarding cycle on gpt-oss-120B

- 59,000 per-paragraph calls (median chapter = 64 paragraphs × ~922 chapters ÷ 18 novels ≈ 3,300 paragraphs per novel; many novels, batch sized for sustained throughput)
- Each call: ~5k input tokens (cached chapter prefix amortises this on serverless) + ~250 output tokens
- Total: ~14.75M output tokens emitted per onboarding cycle

### gpt-oss-120B throughput on a single H100 with vLLM

From [vLLM's GPT-OSS recipe](https://docs.vllm.ai/projects/recipes/en/latest/OpenAI/GPT-OSS.html): MoE activation lets the 120B fit on a single H100 80GB but only with care (`--gpu-memory-utilization 0.95 --max-model-len 32768 --max-num-seqs 16 --max-num-batched-tokens 4096`). Real-world throughput for batched generation on 1×H100: empirically **~100–200 output tokens/sec sustained** at batch size 16.

At 150 tok/s sustained: 14.75M ÷ 150 ÷ 3600 = **~27 GPU-hours per cycle**.

### Modal / Runpod cost per cycle

| Path | GPU | $/hr | Hours | Cost/cycle |
|---|---|---|---|---|
| Modal H100 | $3.95 | 27 | **~$107** |
| Runpod H100 PRO (flex) | $4.18 | 27 | **~$113** |
| Modal A100 80GB | $2.50 | ~50 (slower) | ~$125 |
| Runpod A100 80GB (flex) | $2.74 | ~50 | ~$137 |

### DeepInfra serverless cost per cycle (gpt-oss-120B at $0.04 / $0.19 per 1M)

- Input: caching makes most input free after first call; assume effective ~20% × 5k × 59k = 59M billable input tokens → $2.36
- Output: 14.75M × $0.19/M = $2.80
- **Total: ~$5.16 per cycle**

### So: **Modal / Runpod is ~20× more expensive per cycle for this workload**.

That's despite generous cold-start handling and despite Modal being one of the cheaper $/hr H100 providers. The fundamental driver is **utilisation**: BleakHouse runs maybe 1-2 onboarding cycles a month. Each cycle takes ~27 hours of GPU time. The GPU sits idle ~700 hours a month under serverless self-host accounting (scale-to-zero recovers most of that), but the per-hour rate dominates because each cycle is short relative to the per-hour bandwidth.

### When does the crossover flip?

A continuously-running H100 on Modal costs $3.95 × 720 = ~$2,843/month. To break even against DeepInfra at $5.16/cycle, you'd need **~550 cycles per month** — about **18 onboarding cycles per day**. That requires the workload to be either continuous batch processing or many concurrent novels in flight.

The realistic BleakHouse cadence (1-2 cycles/month) is **~250× below the crossover**.

## When Modal / Runpod *do* make sense

The economics don't favour self-hosted for our day-to-day. But these providers are the right answer for specific cases:

### 1. Privacy / compliance with model weights or data

If the input is something you can't send to a third-party gateway (proprietary prompts, regulated content, PII), running on Modal/Runpod in your own AWS/GCP-adjacent space puts the inference behind your own controls. For BleakHouse — public-domain literature — this doesn't apply.

### 2. Custom fine-tunes

If you fine-tune a base model and want to serve it, no serverless provider will host your weights. Modal/Runpod let you mount the weights and serve them through vLLM. We currently have no fine-tuned models; not relevant.

### 3. Specific vLLM flags the gateway doesn't expose

DeepInfra/Together pick the vLLM config for you. If you need exotic sampling parameters (custom logit processors, speculative decoding, draft-model setups, KV-cache externalisation, particular quantisation), self-hosted is the only way. **Possibly relevant for us**: our investigation surfaced that `uniqueItems` is hard-rejected on DeepInfra's grammar engine. A self-hosted vLLM with `outlines` or `lm-format-enforcer` could honour `uniqueItems` natively — at the cost of running the GPU.

### 4. Models no serverless provider hosts

If a model exists on HuggingFace but no gateway has picked it up, self-hosted is the only way. For our candidate set, **none** of the open-weight models we care about is in this category — all are on at least 2 serverless providers.

### 5. Predictable high-throughput batch jobs

If you ever decide to **re-enrich all 18 novels in parallel** (say, after a schema change), the workload becomes ~18 × 27 = 486 GPU-hours of work concentrated in a short window. Spinning up 4-8 H100s for ~24 hours costs ~$400-800 on Modal/Runpod — comparable to DeepInfra serverless, with potentially lower wall time because you control the batch parallelism rather than depending on the gateway's queue. **This is the one scenario where self-hosted is genuinely competitive for us.**

## Modal vs Runpod, head-to-head

| Dimension | Modal | Runpod Serverless |
|---|---|---|
| H100 $/hour | $3.95 | $4.18 (flex) / $3.35 (active) |
| H200 $/hour | $4.54 | $5.58 (flex) / $4.46 (active) |
| A100 80GB $/hour | $2.50 | $2.74 (flex) / $2.16 (active) |
| Cold start (typical) | 2-4 s | "48% under 200ms" |
| OpenAI-compat endpoint | yes (vLLM example in docs) | yes (vLLM template first-class) |
| Auth on the runtime endpoint | none by default (Modal token used at deploy) | API key per endpoint |
| Free tier | $30/month credits (Starter) | none documented |
| Geographic distribution | "hundreds of GPUs" (not detailed) | 9 regions |
| Python SDK / deployment DX | Decorator-based (`@app.function`) | Container template + REST API |
| Active-worker discount | none | yes (~80% of flex) |

**Where Modal is the better default**: developer experience is meaningfully cleaner. The `@app.function(gpu="H100")` decorator + 60-second vLLM example is friendlier than Runpod's template-and-spec workflow. The $30/month free credit covers the kind of experimentation this codebase has done in the past sessions.

**Where Runpod is the better default**: sustained workloads. Active-worker pricing knocks ~20% off the H100 rate, and the active-worker SLA fits "run this batch for 24 hours" better than Modal's per-second scale-to-zero. Cold starts are also faster on average, which matters more for low-latency interactive use than for batch enrichment.

## Recommendation for BleakHouse

**Stay on serverless (DeepInfra / OpenAI / Anthropic / Together) as the default.** The economics are 20-50× in favour, and the management overhead of self-hosted is real (Dockerfile, vLLM pin, weights mounting, monitoring).

**Keep one self-hosted spike on the shelf for two cases:**

1. **Bulk re-enrichment** (rare, ~once a year if schema changes). At that scale, ~24 hours on 4× H100 on Runpod is plausibly cheaper than serverless because we control batching and don't pay the gateway markup. The seam's `runpod` capability slot is ready for this; the actual deployment recipe would be vLLM's `recipes/OpenAI/GPT-OSS.md`.
2. **Schema-feature experiments where the hosted gateway rejects what we need.** E.g. if we ever wanted decoder-level `uniqueItems` enforcement on a Qwen or DeepSeek model, a self-hosted vLLM with `outlines` would do it. Cheaper than negotiating with the gateway; one-off experimental.

**Don't yet wire either provider into the production seam.** Both have slots in `capabilities.py` but no provider-specific code path. Wiring is a few hours of work when the case actually arises; doing it speculatively before either case is real would be premature.

## Sources

- Modal pricing: [modal.com/pricing](https://modal.com/pricing) (verified 2026-05-13)
- Runpod Serverless pricing: [docs.runpod.io/serverless/pricing](https://docs.runpod.io/serverless/pricing) (verified 2026-05-13)
- Modal vLLM example: [modal.com/docs/examples/vllm_inference](https://modal.com/docs/examples/vllm_inference)
- vLLM GPT-OSS recipe: [docs.vllm.ai/projects/recipes/en/latest/OpenAI/GPT-OSS.html](https://docs.vllm.ai/projects/recipes/en/latest/OpenAI/GPT-OSS.html)
- Modal/Runpod comparison: [runpod.io/articles/guides/top-serverless-gpu-clouds](https://www.runpod.io/articles/guides/top-serverless-gpu-clouds)
