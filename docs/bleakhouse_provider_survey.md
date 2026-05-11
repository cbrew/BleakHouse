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

**Ops complexity ranking** (1 = managed, 5 = full self-host):
- Modal: 2. Python-decorator deployment; vLLM-on-Modal recipes exist; OpenAI-compatible endpoint via FastAPI wrapper. Cold start dominated by model load (~30-60s for 70B-class from disk).
- Runpod: 2-3. Serverless workers with vLLM template; faster per-request cold start than from-scratch Modal; less idiomatic Python deployment.
- GKE: 5. GPU operator, vLLM/SGLang containerization, autoscaling, GPU node pools, IAM, networking. Highest control but real ops investment.

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

**Recommended: Gemma 4 26B MoE [VERIFY availability]** — user's
preferred candidate; Apache 2.0; MoE architecture gives 70B-class
quality at smaller inference cost. If not available hosted, deploy
on Modal or Runpod (24GB + VRAM per active expert).

Alternates to benchmark:
- DeepSeek-V3.2 on DeepInfra ($0.26 / $0.38) — 160k context, top
  open-weight prose model class.
- Qwen 3 235B A22B FP8 on Together ($0.20 / $0.60) — large model,
  cheap output rate.

Anthropic Sonnet 4.6 ($3 / $15) stays as the baseline to beat by
≥45% blinded preference, NOT to match.

### Tier W — wildcard fine-tune-ready

**Recommended: Phi-4 14B on Modal** — MIT license, consumer-GPU
LoRA-tunable, well-regarded for instruction following at small size.
This is the candidate that gives BleakHouse a clean fine-tune path
without renting H100s.

### Non-API self-hosted option (Principle 6)

**Candidate: Modal-hosted Qwen 2.5-72B-Instruct or Gemma 4 26B**.
Modal pricing on H100 (~$4/hr) at ~2000 tok/s sustained gives
~$0.55 per million tokens — competitive with hosted prices, and
clears the API-independence + fine-tune-enablement goals.

For sustained-volume tasks (passage_enrichment / passage_contexts):
self-hosted wins if average GPU utilization stays >40%. Otherwise
hosted is cheaper.

---

## Stage 2 plan (not yet run)

Per the o3ir spec, Stage 2 = live benchmark on 3-4 candidates from
the shortlist. Concrete proposal:

**Candidates (4)**:
1. Llama 3.1 8B on DeepInfra (Tier S).
2. Qwen 2.5-72B-Instruct on DeepInfra (Tier M).
3. Gemma 4 26B on Modal (Tier L + non-API self-hosted, two birds).
4. Phi-4 14B on Modal (Tier W).

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
- **Default routing for prose (short)**: Gemma 4 26B on Modal (self-hosted) — clears Principle 6's non-API constraint AND the short-podcast prose direction.
- **Default routing for legacy prose (long, opt-in only)**: Anthropic Sonnet 4.6.

This is a Stage 1 inference, not a decision. Stage 2 results revise.
