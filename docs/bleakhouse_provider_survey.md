# BleakHouse Provider Survey

**Status**: Stage 1 (desk survey) complete 2026-05-11. Stage 2 (live
benchmark on shortlist) blocked on user decision about API key
provisioning + budget. See "Stage 2 shortlist" + "Open work" below.

**Ticket**: BleakHouse-o3ir.

**Method**: Web research against canonical provider docs. Items
marked `[VERIFY]` were not surfaced in fetched docs and need
confirmation before they affect routing decisions. Pricing changes
fast; treat numbers as "as of 2026-05-11" not contract.

---

## Stage 1 — Hosted-API providers

| Provider | Endpoint | Open-weight catalogue (notable) | Batch API | Fine-tune hosting | Structured output | Ops complexity |
|---|---|---|---|---|---|---|
| **Cerebras** | `api.cerebras.ai/v1` (OpenAI-compat) | gpt-oss-120b (Apache 2.0); zai-glm-4.7 355B preview. **llama3.1-8b and qwen-3-235b withdrawn 2026-05-27**. | No | Dedicated Endpoints only (enterprise) | response_format json_schema; strict-flag semantics differ [VERIFY] | 1 (hosted) |
| **Together** | `api.together.xyz/v1` (OpenAI-compat) | Llama 3.3 70B, Llama 3 8B Lite, Qwen 3 235B A22B FP8, Qwen 3.5 9B, Qwen 2.5 7B Turbo, Gemma 4 31B, Gemma 3n E4B, DeepSeek-V3.1, DeepSeek V4 Pro, Mistral [VERIFY] | **Yes, 50% off** | Dedicated Inference; custom model support | response_format json_schema [VERIFY] | 1 (hosted) |
| **Fireworks** | `api.fireworks.ai/v1` (OpenAI-compat) | Llama, Qwen, Mistral, DeepSeek, Gemma — exact catalogue not enumerated [VERIFY] | **Yes, 50% off** | Yes; LoRA and full-parameter at same price as base | json_schema [VERIFY] | 1 (hosted) |
| **Groq** | `api.groq.com/openai/v1` (OpenAI-compat) | Llama 3.1 8B Instant, Llama 3.3 70B Versatile, Llama 4 Scout (17Bx16E MoE), Qwen3 32B, GPT-OSS 20B, GPT-OSS 120B | **Yes, 50% off; 24h-7d window** | Enterprise-only fine-tuned hosting | json_schema response_format (Groq is known for this) [VERIFY strict] | 1 (hosted) |
| **DeepInfra** | OpenAI-compat (endpoint not surfaced) [VERIFY] | Llama 3.3 70B Turbo, Llama 3.1 8B, Qwen 2.5 72B, Qwen 3 32B, Qwen3-Max, Mistral Small 3.2 24B, Mistral Nemo, DeepSeek-V3.2, DeepSeek-V3.1, **Gemma 3 27B**, Gemma 3 4B | [VERIFY] | Yes, dedicated GPU hosting (A100/H100/H200/B200/B300, per-minute billing) | [VERIFY] | 1 (hosted) |
| **Anyscale Endpoints** | DISCONTINUED | — | — | — | — | — |

### Hosted-API pricing per million tokens (input / output)

| Model | Cerebras | Together | Fireworks | Groq | DeepInfra |
|---|---:|---:|---:|---:|---:|
| Llama 3.1 8B | (withdrawn 5/27) | $0.10 / $0.10 (Lite) | [VERIFY] | $0.05 / $0.08 | $0.02 / $0.05 |
| Llama 3.3 70B | — | $0.88 / $0.88 | [VERIFY] | $0.59 / $0.79 | **$0.10 / $0.32** (Turbo) |
| Llama 4 Scout 17Bx16E | — | — | [VERIFY] | $0.11 / $0.34 | [VERIFY] |
| Qwen 2.5 72B | — | — | [VERIFY] | — | $0.36 / $0.40 |
| Qwen 3 32B | — | — | [VERIFY] | $0.29 / $0.59 | $0.08 / $0.28 |
| Qwen 3 235B A22B | (withdrawn 5/27) | $0.20 / $0.60 (FP8) | [VERIFY] | — | — |
| Gemma 3 27B / Gemma 4 31B | — | $0.20 / $0.50 (G4 31B) | [VERIFY] | — | $0.08 / $0.16 (G3 27B) |
| DeepSeek-V3.x | — | $0.60 / $1.70 (V3.1) | [VERIFY] | — | $0.26 / $0.38 (V3.2) |
| gpt-oss-120b | available | — | [VERIFY] | $0.15 / $0.60 | [VERIFY] |
| gpt-oss-20b | — | — | [VERIFY] | $0.075 / $0.30 | [VERIFY] |

DeepInfra is consistently the cheapest hosted option in this table.
Groq is the cheapest on Llama 3.1 8B.

### Anthropic (baseline reference, opt-in target)

| Model | Input $/M | Output $/M | Batch discount | Cache write | Cache read |
|---|---:|---:|---:|---:|---:|
| Claude Haiku 4.5 | $1.00 | $5.00 | 50% | ~$0.30/M [VERIFY] | ~$0.10/M [VERIFY] |
| Claude Sonnet 4.6 | $3.00 | $15.00 | 50% | ~$3.75/M [VERIFY] | ~$0.30/M [VERIFY] |

For passage_enrichment (the canonical batch task), Anthropic with
Batch API = $0.50 / $2.50 effective per M tokens on Haiku.

---

## Stage 1 — Self-hosting (Runpod / Modal / GKE)

Per-hour GPU pricing. Multiply by GPU-hours-per-million-tokens to
estimate per-task cost; vLLM throughput on 70B-class models on H100
is roughly 1500-3000 tokens/sec per GPU depending on batch size and
context, so ~1M tokens ≈ 5-10 GPU-min ≈ $0.30-$0.70 per million on
H100. Cheaper than most hosted Llama-3.3-70B options; pays for
itself once you have steady volume; pays a premium for sporadic
calls due to cold-start + idle time.

| GPU | Modal $/hr | Runpod $/hr | GKE on-demand $/hr [VERIFY] | GKE spot $/hr [VERIFY] |
|---|---:|---:|---:|---:|
| B200 180GB | $6.25 | $8.64 | — | — |
| H200 141GB | $4.54 | $5.58 | ~$10 | ~$3 |
| H100 80GB | $3.95 | $4.18 | ~$11 | ~$3.30 |
| A100 80GB | $2.50 | $2.72 | ~$3.67 | ~$1.10 |
| A100 40GB | $2.10 | — | ~$2.93 | ~$0.88 |
| L40S 48GB | $1.95 | $1.90 | ~$1.90 | ~$0.57 |
| A10 24GB | $1.10 | — | ~$1.10 | ~$0.33 |
| RTX 4090 24GB | — | $1.10 | — | — |

**Ops complexity ranking** (revised after closer look at Modal/Runpod auth + deployment model; 1 = hand over a key and call, 5 = full self-host):

- **Hosted-API providers (Cerebras, Together, Fireworks, Groq, DeepInfra serverless)**: **1**. Single `API_KEY` env var; call their endpoint; done.
- **DeepInfra dedicated GPU**: **2**. Same auth model as serverless but you manage a dedicated GPU instance (per-minute billing, autoscale config) via their console.
- **Modal**: **3**. Not just hand-over-a-key. You write a Python file (`@modal.web_server(port=8000)` wrapping vLLM's OpenAI-compatible server), `modal deploy`, get back a `*.modal.run` URL. You own the inference container image + model-weight caching via Modal Volumes + cold-start tuning. Auth is two-part token (`token_id` + `token_secret`) set up via `modal token new` (interactive browser flow → stored in `~/.modal.toml`) OR `MODAL_TOKEN_ID` + `MODAL_TOKEN_SECRET` env vars for CI. The runtime call to BleakHouse only needs the `*.modal.run` URL — no per-call auth unless you add Modal Secrets gating.
- **Runpod**: **3**. Similar shape to Modal: deploy a serverless endpoint (vLLM template available), get a URL, configure that as `base_url`. Less idiomatic Python-first DX than Modal; web console for setup. Auth via Runpod API key.
- **GKE**: **5**. GPU operator, vLLM/SGLang containerization, autoscaling, GPU node pools, IAM, networking, log aggregation, Workload Identity, billing alerts. Highest control but real ops investment.

**Deployment workflow for Modal-hosted Gemma 4 26B (concrete sketch)**:

```python
# infra/modal/vllm_gemma4_26b.py
import modal

app = modal.App("vllm-gemma4-26b")
image = (
    modal.Image.debian_slim()
    .pip_install("vllm==<pinned>", "huggingface_hub")
)
volume = modal.Volume.from_name("hf-cache", create_if_missing=True)

@app.cls(
    image=image,
    gpu="H100",                       # single H100 80GB
    volumes={"/cache": volume},
    container_idle_timeout=300,       # 5-min keep-warm after last request
    timeout=3600,
)
class GemmaServer:
    @modal.enter()
    def load(self):
        # vLLM loads weights from /cache (or downloads on first run)
        import vllm
        self.engine = vllm.LLM(
            model="google/gemma-4-26b-it",  # HF model id; exact name TBD
            download_dir="/cache",
            max_model_len=8192,
        )

    @modal.web_server(port=8000, startup_timeout=120)
    def serve(self):
        # vLLM speaks OpenAI's API natively
        import subprocess
        subprocess.Popen([
            "python", "-m", "vllm.entrypoints.openai.api_server",
            "--model", "google/gemma-4-26b-it",
            "--download-dir", "/cache",
            "--host", "0.0.0.0",
            "--port", "8000",
        ])
```

Deploy with `modal deploy infra/modal/vllm_gemma4_26b.py`; the URL
that comes back goes into `enrichment/llm/settings.py` as the
`base_url` for the `generate_podcast` task.

**Custom-weights / fine-tune feasibility (the long-term lever)**:
- Modal / Runpod / GKE: yes by construction — you deploy your own weights.
- DeepInfra: yes, dedicated GPU hosting.
- Together / Fireworks: yes, dedicated inference / custom-model hosting.
- Groq / Cerebras: only via enterprise contracts.

---

## Model license summary

| Model family | License | Fine-tune redistribution |
|---|---|---|
| Llama 3.x | Meta Llama 3 Community License | Permitted; restrictions only on >700M MAU services |
| Qwen 2.5 / Qwen 3 | Apache 2.0 (most variants) | Fully permissive |
| Qwen3-Max | [VERIFY — may be proprietary not open-weight] | — |
| Mistral / Mixtral | Apache 2.0 (open variants) | Fully permissive |
| Gemma 3.x | Gemma Terms of Use | Fine-tunable but Prohibited-Use Policy applies |
| **Gemma 4** | **Apache 2.0** | Fully permissive |
| DeepSeek-V3 / V3.x | DeepSeek License | Fine-tunable; some redistribution constraints |
| gpt-oss-120b / 20b | Apache 2.0 | Fully permissive (OpenAI open release) |
| Phi-4 (Microsoft) | MIT | Fully permissive |
| Yi-1.5 (01.AI) | Apache 2.0 | Fully permissive |
| Aya 23 (Cohere) | CC-BY-NC | **Non-commercial only** — flag |

---

## Stage 2 shortlist

Tier-first lexicographic per the o3ir rubric. Aim: one candidate per
tier, plus one non-API self-hosted option (per Principle 6 of the
plan).

### Tier S — small structured (listener_pick, reading_list_winnow, reference_tools, quote_verification)

**Recommended: Llama 3.1 8B on DeepInfra** — $0.02 / $0.05 per M
tokens is the cheapest credible option; 8B is enough for tag-picking
and JSON-output tasks. Apache-2.0-equivalent fine-tunability via
Llama Community License.

Runner-up: **Gemma 4 9B** [VERIFY availability across hosts] —
Apache 2.0 (Gemma 4 specifically), small enough for consumer-GPU
LoRA, would tee up self-hosting later.

### Tier M — structured intermediate (design_segments, host_prep brief, passage_enrichment, passage_contexts)

**Recommended: Qwen 2.5-72B-Instruct on DeepInfra** — $0.36 / $0.40
is competitive vs Anthropic Haiku-batch ($0.50 / $2.50 effective).
Apache 2.0. Long context (32k). Strong reputation on structured-output
tasks.

Runner-up: **Llama 3.3 70B Turbo on DeepInfra** — $0.10 / $0.32 is
remarkable; "Turbo" suffix suggests quantization, which may affect
schema-strict output reliability. VERIFY at Stage 2.

### Tier L — prose generation (short format) (generate_podcast)

**Recommended: Gemma 4 26B (MoE per user; VERIFY architecture)** —
user's preferred candidate; Apache 2.0 (Gemma 4 family); if MoE,
the active-parameter count per token is much smaller than 26B
total, giving 70B-class quality at smaller inference cost. Availability
across hosted providers VERIFY — Together hosts Gemma 4 31B (dense)
at $0.20/$0.50, not the 26B MoE; the 26B MoE variant likely requires
self-hosting on Modal/Runpod with weights from HF.

**Cost reassessment for Gemma 4 26B on Modal (revised from the
optimistic $0.55/M earlier — that assumed sustained utilization,
which BleakHouse does not have)**:

The true $/M-tokens for self-hosted depends heavily on usage
pattern. Three scenarios:

| Scenario | GPU-time per M tokens | Cost per M tokens (H100 $3.95/h) | Notes |
|---|---|---|---|
| Sustained utilization (continuous request stream, batch>8) | ~500s active GPU time | **~$0.55** | Best case; assumes ~2000 tok/s sustained throughput; ignores cold-start |
| Daily batch render (10 episodes × ~10k output tokens back-to-back) | ~125s including cold-start + warmdown | **~$1.40** | Realistic for BleakHouse's pattern if renders are grouped |
| Sporadic (a few requests/day spaced apart) | ~650s per million actually generated (cold-start dominates) | **~$10-15** | Worst case; pays for cold-start each time the container spins back up |

BleakHouse's actual prose-generation pattern is closer to Scenario B
(daily-batch renders triggered when episodes are produced). Realistic
working estimate: **$1.50-3/M tokens** for self-hosted Gemma 4 26B
on Modal H100.

Cheaper-GPU options for the same model (Stage 2 should verify
quality holds):
- **A100 80GB ($2.50/h on Modal)** — fits 26B fp16 weights (~52GB)
  with tight headroom for KV cache. ~$0.95-1.90/M in Scenario B.
- **L40S 48GB ($1.95/h on Modal)** — fp16 doesn't fit; would need
  4-bit / 8-bit quantization. ~$0.75-1.50/M if quality holds at
  quant.

**Cost comparison across the prose-tier shortlist** (using
Scenario B for self-hosted, blended I/O assuming prose-heavy
~80% output):

| Candidate | Hosted/self | $/M blended | Notes |
|---|---|---:|---|
| Gemma 4 26B MoE on Modal H100 (scenario B) | self | ~$1.50-3 | Non-API constraint cleared; fine-tune path open |
| Gemma 4 26B MoE on Modal A100 80GB | self | ~$1-2 | If A100 throughput holds for MoE |
| Gemma 4 26B 4-bit on Modal L40S | self | ~$0.75-1.50 | Quality at 4-bit VERIFY |
| Gemma 4 31B (dense) on Together | hosted | ~$0.44 | Same family, hosted is cheaper for our pattern |
| DeepSeek-V3.2 on DeepInfra | hosted | ~$0.36 | 160k context; cheapest credible prose option |
| Llama 3.3 70B Turbo on DeepInfra | hosted | ~$0.28 | Quantized — schema-strict reliability VERIFY |
| Qwen 3 235B A22B FP8 on Together | hosted | ~$0.52 | Largest model; cheap output rate |
| Anthropic Sonnet 4.6 (no batch) | hosted | ~$12 | Current baseline |
| Anthropic Sonnet 4.6 (batch) | hosted | ~$6 | If we used Batch on prose |

**Implication**: for BleakHouse's usage pattern, hosted Gemma 4 31B
on Together ($0.44/M) or DeepSeek-V3.2 on DeepInfra ($0.36/M) is
materially cheaper than self-hosted Gemma 4 26B. The non-API
benefit of self-hosting only justifies the ~3-5x cost premium if:

- Quality of Gemma 4 26B MoE is meaningfully better than Gemma 4
  31B dense on the prose fixture (Stage 2 question), OR
- Fine-tune-enablement is load-bearing for the project's roadmap
  (currently low-priority per the user note), OR
- Sustained utilization can be achieved by batching all prose work
  into a single keep-warm window per day.

The non-API constraint (Principle 6 of the plan) says we need at
least ONE non-API option in the shortlist. It does NOT require
prose specifically to be self-hosted. If hosted Gemma 4 31B wins
on prose, the non-API constraint can be satisfied by routing
`passage_enrichment` (the batch task) to self-hosted instead —
volume + cost-predictability are stronger drivers there than for
prose.

Alternates to benchmark (all hosted):
- **Gemma 4 31B on Together** ($0.20 / $0.50). Same family as
  Gemma 4 26B; dense vs MoE; should be the head-to-head reference.
- DeepSeek-V3.2 on DeepInfra ($0.26 / $0.38) — 160k context, top
  open-weight prose model class.
- Qwen 3 235B A22B FP8 on Together ($0.20 / $0.60) — large model,
  cheap output rate.

Anthropic Sonnet 4.6 ($3 / $15 no-batch; $1.50 / $7.50 with Batch)
stays as the baseline to beat by ≥45% blinded preference on the
short-podcast fixture, NOT to match.

### Tier W — wildcard fine-tune-ready

**Recommended: Phi-4 14B on Modal** — MIT license, consumer-GPU
LoRA-tunable, well-regarded for instruction following at small size.
This is the candidate that gives BleakHouse a clean fine-tune path
without renting H100s.

### Non-API self-hosted option (Principle 6)

The non-API constraint says the shortlist must include at least one
self-hosted candidate. It does NOT require any specific task to be
self-hosted by default. The economics of self-hosted vs hosted is
sensitive to usage pattern:

- **Self-hosted wins** when GPU utilization is sustained (continuous
  request stream, batch>8). Realistic break-even vs hosted Llama 3.3
  70B Turbo on DeepInfra is roughly 40-60% sustained utilization.
- **Hosted wins** for sporadic or daily-batch patterns (cold-start
  cost amortizes poorly over small workloads).

For BleakHouse specifically, the most plausible self-hosted-default
candidate is **passage_enrichment** rather than `generate_podcast`,
because:

- Volume: passage_enrichment processes thousands of passages per
  novel; per-novel-onboarding it runs in big batches.
- Cost discipline: at hosted prices, even cheap providers cost
  meaningful real dollars for the full pipeline. Self-hosted gives
  fixed cost regardless of token volume.
- Quality tolerance: passage_enrichment is a structured task
  (schema validation gates it); modest quality differences across
  candidates are tolerable.

For `generate_podcast` (prose, short format), the cost reassessment
above suggests hosted is materially cheaper for BleakHouse's daily-
batch render pattern. Self-hosted Gemma 4 26B may still win on
quality (Stage 2 question), but it's no longer the obvious choice.

Concrete proposal for the non-API option:

**Modal-hosted Qwen 2.5-72B-Instruct (or similar mid-class model)
for passage_enrichment**, sized for a single daily batch run per
novel. Run cost: ~$2-4 per novel-onboarding batch (~10M tokens
generated over ~30-60 min wall time). Compared to DeepInfra hosted
Qwen 2.5-72B at $0.36/$0.40 ($0.36 per M = $3.60 for 10M), self-
hosted is roughly the same cost but with API-independence + a
clean fine-tune path.

---

## Stage 2 plan (not yet run)

Per the o3ir spec, Stage 2 = live benchmark on 3-4 candidates from
the shortlist. Concrete proposal:

**Candidates (4)**:
1. Llama 3.1 8B on DeepInfra (Tier S).
2. Qwen 2.5-72B-Instruct on DeepInfra (Tier M).
3a. Gemma 4 26B on Modal (Tier L self-hosted; head-to-head vs 3b).
3b. Gemma 4 31B (dense) on Together (Tier L hosted; head-to-head vs 3a).
4. Qwen 2.5-72B on Modal (non-API option for passage_enrichment;
   reuses the Modal infra from candidate 3a). Also serves Phi-4 14B
   wildcard if there's appetite — fold the fine-tune-wildcard
   benchmark into the same Modal account if the budget allows.

Tier L now benchmarks self-hosted vs hosted of the same model family
explicitly (3a vs 3b). If hosted Gemma 4 31B dense matches or beats
the self-hosted 26B MoE on quality at substantially lower cost, the
prose default is hosted; the non-API constraint is satisfied by the
passage_enrichment routing (candidate 4).

**Fixtures**:
- Small structured: 10 listener_pick-shape inputs sampled from existing reading lists. Compare to Haiku-baseline picks.
- Mid structured: 5 passage_enrichment-shape inputs. Compare ChapterEnrichmentResult JSON outputs.
- Prose: 3 generate_podcast short-format inputs. Compare to Sonnet-on-short output via blinded preference (manual or with a rubric LLM-judge as second pass).

**Recorded per candidate × task**:
- Schema validity %
- Latency p50 / p95
- Cost per invocation
- Quality verdict 1-5 vs baseline

**Cost estimate for Stage 2 itself**:
- Hosted candidates: ~$1-3 in total API calls.
- Modal candidates: ~$5-10 in GPU-minutes including model load.
- Anthropic baseline calls: ~$2-5 on Haiku + Sonnet for comparisons.
- Total: under $20.

**Blockers**:
- API keys for DeepInfra and Modal (Together/Fireworks/Groq optional).
- Modal account + deployed vLLM endpoints for Gemma 4 26B and Phi-4.
- Decision on whether to use existing `experiments/cerebras/` infra as a starting point for the survey scaffolding or build fresh.

---

## Open work for Stage 2

The `[VERIFY]` items in the Stage 1 tables, especially:
- Structured-output `strict` semantics on each OpenAI-compatible
  provider (Cerebras, Together, Fireworks, Groq, DeepInfra).
- Whether Gemma 4 26B MoE specifically is available on a hosted
  provider, vs self-hosting being the only path.
- Fireworks open-weight catalogue (current "Serverless Pricing" page
  pointed to docs; need to walk the model library).
- Confirmation of Llama 3.3 70B Turbo (DeepInfra)'s quantization
  level — may affect schema strictness.

These don't block Stage 2 (live calls will surface most of them
empirically) but should be noted in the Stage 2 report.

---

## Decision context — what this survey commits us to

Provisionally, the survey points toward:

- **Default routing for small tasks**: Llama 3.1 8B on DeepInfra (cheap, fast, capable enough).
- **Default routing for mid batch tasks**: Qwen 2.5-72B on DeepInfra; Anthropic-Batch-Haiku as opt-in when volume + cost-discipline wins.
- **Default routing for prose (short)**: head-to-head between Gemma 4 26B on Modal (self-hosted) and Gemma 4 31B on Together (hosted, same family, ~3-5x cheaper for our usage pattern). Decision made by Stage 2 quality data, not by Stage 1's cost inference alone.
- **Default routing for legacy prose (long, opt-in only)**: Anthropic Sonnet 4.6.
- **Non-API constraint** (Principle 6) most naturally satisfied by routing `passage_enrichment` (the high-volume batch task) to self-hosted on Modal; prose may stay hosted if quality data supports it.

This is a Stage 1 inference, not a decision. Stage 2 results revise.
