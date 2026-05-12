# BleakHouse Provider Survey

**Status**: Stage 1 (desk survey) complete 2026-05-11. Stage 2 Tier S
benchmark complete 2026-05-12 (BleakHouse-1aav + 7usk follow-up).
Tier M and Tier L benchmarks pending. See "Stage 2 Tier S results"
section below for findings.

**Usage pattern** (corrected 2026-05-11 after user feedback):

BleakHouse is NOT a continuously-rendering service. The actual
workload:

- **New-novel onboarding** (the dominant token-volume event). Per
  the run-data audit, a typical novel produces ~13 run dirs across
  panel × pipeline × variant combinations (e.g. Bleak House has 26;
  most others 13; new novels in flight have 1-2). Two panels are
  the norm — `literary` (19 novels) and `alternatives` (15 novels)
  — with `interdisciplinary` for 3 novels.
- **Occasional corrections** — re-running part of a pipeline for an
  existing novel when a bug fix lands or a quality issue surfaces.
- **Frequency**: ~5-10 new-novel onboardings per year, plus
  scattered corrections.

Token-volume estimate per novel-onboarding:
- `passage_enrichment` + `passage_contexts` (batch tasks, upstream
  of panels): ~5-10M tokens (~1-2h wall time per CLAUDE.md).
- Per-panel pipeline × ~13 runs: ~100k prose output + ~100k
  reading-list / host-prep + ~50k structured-filtering tokens.
- Total per novel: ~10M tokens roughly.

Annual envelope: ~50-100M tokens across the whole pipeline. At
hosted prices the total annual LLM bill is on the order of **$20-40
per year**. At self-hosted Modal H100 prices it's **$40-80 per
year** (a single novel-onboarding burst is ~1-2h of GPU at $3.95/h,
plus the same fraction of overhead for corrections).

**Implication**: at this volume, cost is not a meaningful decision
driver. A 3-5x cost ratio between hosted and self-hosted resolves
to ~$50/year in absolute terms. The decision drivers, in order:

1. Quality (still primary per the rubric).
2. **Lock-in resistance** (corrected interpretation of Principle 6
   after user feedback 2026-05-11; see "What 'non-API' really
   means" below).
3. Fine-tune enablement (low priority but real).
4. Operational simplicity (zero maintenance for hosted; deploy +
   monitor for Modal).

### What "non-API" really means

The plan's Principle 6 was phrased "non-API option required" and I
initially read this as "use self-hosted infrastructure." User
correction: **the constraint is non-lock-in, not literally
non-API**. The mechanism for non-lock-in is portability across
providers, not necessarily self-hosting.

Open-weight models with broad hosted availability give us portability
without paying the ops cost of self-hosting:

- If the model is open-weight (Apache 2.0 Gemma 4, Apache 2.0 Qwen,
  Meta Community Llama, Apache 2.0 gpt-oss), any vLLM-compatible
  host can serve it. The model itself is portable.
- If the API surface is OpenAI-compatible (standard `response_format`,
  `tools`, etc.), switching providers is a config change, not a
  code change.
- Multi-host availability means we can multi-source the same model.
  If DeepInfra changes prices, we move to Together. If Together
  withdraws Gemma 4 31B, we use Fireworks or self-host on Modal.
- Self-hosting on Modal stays as a documented fallback path we
  *could* pivot to, but we don't pay the ongoing cost of running
  it.

**Reasonable assumption** (per user): Gemma 4 will be available
serverless at several sizes and from multiple providers; similarly
Qwen and Llama. The open-weight catalogue is broadening fast.

What still constitutes lock-in:
- **Closed-weight providers** (Anthropic, OpenAI GPT, Cohere
  Command): can't multi-source, can't self-host, fully dependent
  on the vendor.
- **Single-provider proprietary catalogue**: Cerebras's
  withdrawal of llama3.1-8b and qwen-3-235b on 2026-05-27 is a
  textbook case — narrow catalogue + single vendor = forced
  migration.

What does NOT constitute lock-in:
- Using a hosted provider as the runtime default, as long as the
  same model (or a comparable open-weight peer) is available
  elsewhere via OpenAI-compatible API.

### Model-portability ranking (within the open-weight families)

Higher rank = more hosts currently serve it = lower lock-in risk:

| Model family | Host availability |
|---|---|
| Llama 3.x | Together, DeepInfra, Fireworks, Groq, many more. **Highest portability.** |
| Qwen 2.5 / 3.x | Together, DeepInfra, Fireworks, Groq. Broad. |
| DeepSeek-V3.x | Together, DeepInfra, others. Broad. |
| gpt-oss-120b / 20b | Cerebras, Groq, Fireworks. Decent. |
| Mistral / Mixtral | Together, DeepInfra, Fireworks. Broad. |
| Gemma 4 26B-A4B-it (MoE) / 31B-it (dense) | DeepInfra, Novita, Featherless-AI, Fireworks (26B); Together adds 31B. Good. |
| Gemma 4 small (E2B / E4B) | Azure Foundry only. Weak (will likely broaden). |
| Phi-4 | Limited hosted footprint; mostly self-hosted right now. |
| Nemotron-Nano-9B-v2 | **DeepInfra ($0.04/$0.16, 128k context)** + NVIDIA NIM. Decent portability. |
| Nemotron-3-Nano (4B / 30B-A3B-MoE) | NVIDIA NIM is the primary hosted home; Azure Foundry secondary. DeepInfra etc. not yet confirmed for the -3- generation. Verify at survey time; portability for the older Nano-9B-v2 has expanded to DeepInfra, so the newer -3- variants may follow. |

For routing decisions, prefer the higher-portability rows when
quality is comparable.

The earlier cost-reassessment (Scenario A/B/C breakdown) is
preserved below for reference but is no longer the centre of the
decision.

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
| **DeepInfra** | OpenAI-compat (endpoint not surfaced) [VERIFY] | Llama 3.3 70B Turbo, Llama 3.1 8B, Qwen 2.5 72B, Qwen 3 32B, Qwen3-Max, Mistral Small 3.2 24B, Mistral Nemo, DeepSeek-V3.2, DeepSeek-V3.1, **Gemma 4 26B-A4B-it (MoE)**, **Gemma 4 31B-it**, Gemma 3 27B, Gemma 3 4B | [VERIFY] | Yes, dedicated GPU hosting (A100/H100/H200/B200/B300, per-minute billing) | [VERIFY] | 1 (hosted) |
| **Novita** | OpenAI-compat (HF Inference Providers partner) | **Gemma 4 26B-A4B-it (MoE)** + broader open-weight catalogue [VERIFY] | [VERIFY] | [VERIFY] | OpenAI-compat → response_format json_schema [VERIFY] | 1 (hosted) |
| **Featherless-AI** | OpenAI-compat (HF Inference Providers partner) | **Gemma 4 26B-A4B-it (MoE)** + broad open-weight catalogue (many fine-tunes hosted) [VERIFY] | [VERIFY] | [VERIFY] | OpenAI-compat [VERIFY] | 1 (hosted) |
| **NVIDIA NIM** (`integrate.api.nvidia.com/v1/chat/completions`) | OpenAI-compatible | NVIDIA Nemotron family (Nano-9B-v2, Nano-3-4B, Nano-3-30B-A3B MoE) + curated Meta/Mistral/Google/IBM catalogue | [VERIFY] | Self-host NIMs locally; managed hosted = NVIDIA-only | OpenAI-compat (response_format json_schema) [VERIFY strict] | 1 (hosted) |
| (DeepInfra also hosts **NVIDIA-Nemotron-Nano-9B-v2** at $0.04/$0.16, 128k context — listed under DeepInfra row above) | — | — | — | — | — | — |
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
| Gemma 4 26B-A4B-it (MoE; 4B active) | — | — | available [VERIFY price] | — | **$0.07 / $0.34** |
| Gemma 4 31B-it (dense) | — | $0.20 / $0.50 | available [VERIFY price] | — | $0.13 / $0.38 |
| Gemma 3 27B (dense) | — | — | [VERIFY] | — | $0.08 / $0.16 |
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
| Nemotron family (NVIDIA) | NVIDIA Open Model License (NOML) | Commercial use + fine-tuning + redistribution allowed, but with caveats — see below |

### NVIDIA Open Model License caveats (vs Apache 2.0)

Materially more restrictive than Apache 2.0 in several non-obvious ways:

- **Unilateral amendment.** NVIDIA may update the license at any time; you either comply with the new terms or cease use. No grandfather clause. For long-running production projects this is a real stability risk.
- **No patent grant.** Apache 2.0 includes an explicit patent grant; NOML does not. If NVIDIA ever asserted a patent claim against a Nemotron user, the license offers no defense.
- **Guardrail-circumvention trap.** Disabling any safety mechanism without "substantially similar Guardrail" auto-terminates the license. Only relevant if we fine-tune.
- **Trustworthy AI compliance.** Separately-maintained NVIDIA document; external dependency that can change without notice.
- **Litigation termination.** Filing any patent or copyright suit against NVIDIA terminates the license, even on unrelated matters.
- **Indemnity asymmetry.** Licensee indemnifies NVIDIA for third-party claims; no reciprocal obligation.
- **Attribution required.** "Licensed by NVIDIA Corporation under the NVIDIA Open Model License" in a Notice file when redistributing.
- **Output ownership.** We own outputs; this is fine and matches Apache 2.0.

Net: acceptable for **hosted-API inference use** (no redistribution, no fine-tuning, content within any reasonable Trustworthy AI interpretation — BleakHouse's literary podcasts qualify). Strictly worse than Apache 2.0 for fine-tuning or long-horizon production commitments. If a Nemotron candidate ties an Apache 2.0 alternative on quality, prefer the Apache 2.0 option for cleaner long-term posture.

---

## Stage 2 shortlist

Tier-first lexicographic per the o3ir rubric. Aim: one candidate per
tier, plus one non-API self-hosted option (per Principle 6 of the
plan).

### Tier S — small structured (listener_pick, reading_list_winnow, reference_tools, quote_verification)

Three credible hosted candidates as of 2026-05-11:

**Recommended head-to-head in Stage 2**:

1. **NVIDIA-Nemotron-Nano-9B-v2 on DeepInfra** — $0.04/$0.16/M; 128k
   context; multilingual (en/es/fr/de/it/ja); trained on NVIDIA's
   instruction-following + structured-outputs RL datasets (the
   training mix explicitly targets our task shape). Also hosted on
   NVIDIA NIM → 2-host portability. Licensed under the **NVIDIA
   Open Model License (NOML)** — commercial use OK, but strictly
   worse than Apache 2.0 for long-horizon use (unilateral
   amendment, no patent grant, guardrail-circumvention trap if we
   ever fine-tune; see the License Caveats section above). Strong
   fit on training-data alignment with our use case; license is
   acceptable for hosted-API inference today but adds a stability
   risk if NVIDIA tightens terms later.

2. **Llama 3.1 8B on DeepInfra** — $0.02/$0.05/M; 8B params;
   broadest multi-host portability (Together, DeepInfra,
   Fireworks, Groq, many more). Meta Community License. Safe
   baseline.

3. **Gemma 3 4B on DeepInfra** — $0.04/$0.08/M; smallest model;
   Gemma 3 family (older Gemma Terms of Use, fine-tunable but
   Prohibited-Use Policy applies). Family-consistent with the
   prose-tier Gemma 4 candidate.

At our token volume (~1-2M small-tier tokens/year) the price spread
is pennies/year and not a decision driver. The decision drivers
are:
- **Quality on structured-output tasks**: Nemotron-Nano-9B-v2's
  training data has a meaningful advantage. Llama 3.1 8B is well-
  benchmarked but trained on more general data.
- **Multi-host portability**: Llama 3.1 8B wins by a wide margin.
- **Provider consolidation**: all three are on DeepInfra; single
  API-key story works regardless of pick.
- **License posture**: Llama (Meta Community) and Gemma 3 (Gemma
  Terms of Use) are both well-understood; Nemotron's NOML is
  strictly worse than Apache 2.0 (see License Caveats above). If
  Stage 2 quality is close, the license preference tilts away from
  Nemotron.

Stage 2 directly compares all three on a 20-input fixture
sampled from existing reading lists. Lowest-stakes Tier in the
survey; could ship on Stage 1 confidence alone if Stage 2 is
deferred.

Future revisit trigger: when Gemma 4 E2B or E4B lands on
serverless hosting (Azure Foundry only currently).

### Tier M — structured intermediate (design_segments, host_prep brief, passage_enrichment, passage_contexts)

**Recommended: Qwen 2.5-72B-Instruct on DeepInfra** — $0.36 / $0.40
is competitive vs Anthropic Haiku-batch ($0.50 / $2.50 effective).
Apache 2.0. Long context (32k). Strong reputation on structured-output
tasks.

Runner-up: **Llama 3.3 70B Turbo on DeepInfra** — $0.10 / $0.32 is
remarkable; "Turbo" suffix suggests quantization, which may affect
schema-strict output reliability. VERIFY at Stage 2.

### Tier L — prose generation (short format) (generate_podcast)

**Recommended: `gemma-4-26B-A4B-it` (MoE; 26B total / 4B active per
token) hosted on DeepInfra** — Apache 2.0; user's preferred MoE
variant; **DeepInfra prices it at $0.07 in / $0.34 out per 1M
tokens** (~$0.27/M blended), which is *cheaper* than Gemma 4 31B
dense ($0.13/$0.38 on DeepInfra, $0.20/$0.50 on Together) — the MoE
architecture's small active-param count flows directly into the
price. Multi-host availability confirmed: hosted by **Novita,
Featherless-AI, DeepInfra, and Fireworks**. Lock-in resistance is
strong.

Earlier drafts assumed Gemma 4 26B was self-host-only; that was
wrong. The model is widely hosted via the HF Inference Providers
network and direct provider partnerships.

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

**Cost comparison across the prose-tier shortlist** (hosted-first
now that Gemma 4 26B MoE availability is confirmed; blended I/O
assuming prose-heavy ~80% output):

| Candidate | Hosted/self | $/M blended | Notes |
|---|---|---:|---|
| **Gemma 4 26B-A4B-it on DeepInfra** | hosted | **~$0.27** | MoE, 4B active; cheapest credible Gemma 4 prose option; multi-host (Novita / Featherless / DeepInfra / Fireworks) |
| Gemma 4 31B-it on DeepInfra | hosted | ~$0.33 | Dense; same family head-to-head vs MoE 26B |
| Gemma 4 31B-it on Together | hosted | ~$0.44 | Same model, different host (portability check) |
| DeepSeek-V3.2 on DeepInfra | hosted | ~$0.36 | 160k context; alternate prose option |
| Llama 3.3 70B Turbo on DeepInfra | hosted | ~$0.28 | Quantized — schema-strict reliability VERIFY |
| Qwen 3 235B A22B FP8 on Together | hosted | ~$0.52 | Largest model; cheap output rate |
| Gemma 4 26B MoE on Modal H100 (scenario A sustained) | self | ~$0.55 | Self-host fallback only; not a default |
| Gemma 4 26B MoE on Modal A100 80GB | self | ~$0.40 | A100 fits with quant headroom; fallback only |
| Anthropic Sonnet 4.6 (no batch) | hosted | ~$12 | Current baseline |
| Anthropic Sonnet 4.6 (batch) | hosted | ~$6 | If we used Batch on prose |

**Implication of the corrected availability picture**: the
user-preferred Gemma 4 26B-A4B-it MoE is the leading prose-tier
candidate on every axis simultaneously — it's the cheapest, the
quality-favored, the multi-host (Novita / Featherless / DeepInfra
/ Fireworks), and Apache 2.0. Stage 2 still needs to validate
blinded preference vs Sonnet-on-short, but unless there's a
quality surprise this is the prose default.

Head-to-heads still worth running in Stage 2:
- Gemma 4 26B-A4B-it (MoE) vs Gemma 4 31B (dense) on the same
  short-podcast fixture — does MoE actually match dense at
  smaller cost?
- Gemma 4 26B-A4B-it on DeepInfra vs the same model on Novita /
  Featherless — sanity-check that hosted-provider implementations
  don't differ on structured-output reliability.
- DeepSeek-V3.2 on DeepInfra (~$0.36/M) as a non-Gemma alternate —
  particularly if Stage 2 surfaces a quality concern on Gemma 4.

Anthropic Sonnet 4.6 ($3 / $15 no-batch; $1.50 / $7.50 with Batch)
stays as the baseline to beat by ≥45% blinded preference on the
short-podcast fixture, NOT to match.

**Gemma 4 small variants (E2B, E4B) status**: HF Hub confirms they
exist (~5B and ~8B total params; multimodal incl audio; Apache 2.0;
`deploy:azure` tag). But as of 2026-05-11, no OpenAI-compatible
hosted-serverless provider in our survey has picked them up yet
(Azure Foundry is the canonical hosted home; not OpenAI-compatible
in the same way). Likely to broaden — Novita / Featherless / DeepInfra
already host the 26B-A4B variant and will probably extend. Until
then, the Tier S default stays on a hosted Llama 3.1 8B or Gemma 3
4B. Worth re-running the survey when small Gemma 4 hits a serverless
host.

### Tier W — wildcard fine-tune-ready

**Recommended: Phi-4 14B on Modal** — MIT license, consumer-GPU
LoRA-tunable, well-regarded for instruction following at small size.
This is the candidate that gives BleakHouse a clean fine-tune path
without renting H100s.

### Lock-in mitigation (corrected interpretation of Principle 6)

Earlier drafts of this section read Principle 6 as "at least one
default must be self-hosted." Per user correction: the constraint
is **non-lock-in via portability**, not literally self-hosted.

Lock-in mitigation strategy adopted by this survey:

1. **Choose open-weight models** for all defaults. The model itself
   is portable across any vLLM-compatible host.
2. **Choose models with broad multi-host availability** when quality
   is comparable. Llama 3.x > Qwen 2.5 > DeepSeek-V3 > Gemma 4
   (Gemma 4 is newer; portability will broaden).
3. **Use OpenAI-compatible APIs** uniformly. Switching providers is
   a config change (`base_url`, `api_key`), not a code change.
4. **Document an alternate provider per task** in
   `enrichment/llm/settings.py`. Operators flip with one env var
   when DeepInfra changes prices or Together drops a model.
5. **Keep Modal self-hosting as a documented fallback path**, not a
   primary default. The vLLM-on-Modal recipe earlier in this doc
   stays as an operational dry-run we could execute when needed.

What this strategy doesn't pay for:
- Ongoing Modal app maintenance (the ~$50/year of hosted-API spend
  it would replace isn't enough to justify the ops cost).
- Pre-emptive fine-tuning before there's a project-driven reason to
  do it.

What this strategy pays for:
- Same provider-config seam BleakHouse needs anyway for
  experimentation across hosted candidates.
- A Modal recipe in the tree, exercised once during Stage 2 (see
  Stage 2 plan below), so the fallback path is known-working when
  needed.

---

## Stage 2 plan (not yet run)

Per the o3ir spec, Stage 2 = live benchmark on 3-4 candidates from
the shortlist. Concrete proposal:

**Candidates (5 hosted + 1 fallback-rehearsal)**:

1. **Tier S head-to-head (3 candidates on DeepInfra)**: Llama 3.1
   8B, NVIDIA-Nemotron-Nano-9B-v2, Gemma 3 4B. Compare set-overlap
   with Haiku baseline on 20 sampled listener_pick inputs. The
   Nemotron candidate is interesting because its training mix
   explicitly targets structured-output tasks. Single DeepInfra
   API key serves all three. Gemma 4 E2B/E4B not yet serverless-
   hosted; revisit when they land.
2. **Qwen 2.5-72B-Instruct on DeepInfra** (Tier M). Apache 2.0;
   broad portability; passage_enrichment + mid-structured tasks.
   Stage 2 compares schema validity + content fidelity to current
   Anthropic Haiku baseline.
3. **Gemma 4 26B-A4B-it (MoE) on DeepInfra** (Tier L primary).
   $0.07/$0.34/M; Apache 2.0; the user-preferred MoE variant;
   multi-host (Novita/Featherless/DeepInfra/Fireworks). Stage 2
   measures blinded preference vs Sonnet-on-short.
4. **Gemma 4 31B-it (dense) on DeepInfra** (Tier L sibling).
   $0.13/$0.38/M; head-to-head with (3) — does MoE 26B match
   dense 31B at smaller cost?
5. **DeepSeek-V3.2 on DeepInfra** (Tier L alternate). $0.26/$0.38;
   160k context; non-Gemma fallback if Stage 2 surfaces a quality
   issue with Gemma 4.

**Provider-portability spot-check** (low cost, high value):
- Re-run a small subset of Stage 2's prose fixture against
  `gemma-4-26B-A4B-it` on **Novita** and/or **Featherless-AI**.
  Goal: confirm that switching providers yields equivalent output
  (no provider-specific quirks in structured-output handling).
  This validates the "lock-in mitigation by multi-source" strategy
  empirically.

**Fallback rehearsal** (not a Stage 2 quality data-point; an
operational dry-run):

6. Optionally deploy `gemma-4-26B-A4B-it` (or Qwen 2.5-72B) on
   Modal H100, exercise the vLLM-on-Modal recipe end-to-end once.
   Goal: prove the fallback path is operational. Do NOT use as a
   quality-comparison point; do NOT make it a default. Lower
   priority now that hosted Gemma 4 26B MoE is widely available —
   the fallback rehearsal may be deferred to "we'll do it when we
   actually need it."

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
- Hosted candidates (4 candidates × 3 task classes × small fixtures): ~$2-5 in total API calls (DeepInfra + Together + Anthropic baselines).
- Modal fallback rehearsal: ~$3-8 in GPU-minutes including model load + cold-start.
- Total: under $15.

**Blockers**:
- API keys for DeepInfra, Together, and (existing) Anthropic.
- Modal account + token credentials for the fallback rehearsal only.
- Decision on whether to reuse `experiments/cerebras/` infra as a starting point for the seam scaffolding or build fresh.

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

## Stage 2 Tier S results (2026-05-12)

8 inputs sampled (seed=42) from real reading lists; baseline = the
post-sz5m `recommended[]` produced by Haiku. Two metrics:
**set_overlap_with_Haiku-baseline** (the 0rtg-spec'd floor) and
**LLM-judge rating** on a 1-5 rubric (judge = Haiku 4.5).

| Candidate | overlap_mean | judge mean | judge median | judge dist (1/2/3/4/5) | cost / 8 inputs | wall |
|---|---:|---:|---:|---|---:|---:|
| Anthropic Haiku 4.5 (baseline) | 0.871 | **3.50** | 4.0 | [0, 1, 2, 5, 0] | $0.0382 | 20.9s |
| NVIDIA-Nemotron-Nano-9B-v2 on DeepInfra | 0.331 | 2.38 | 2.0 | [0, 6, 1, 1, 0] | $0.0040 | 134.3s |
| meta-llama/Meta-Llama-3.1-8B-Instruct on DeepInfra | 0.120 | 2.00 | 2.0 | [0, 8, 0, 0, 0] | $0.0007 | 13.0s |
| google/gemma-3-4b-it on DeepInfra | 0.142 | 2.00 | 2.0 | [0, 8, 0, 0, 0] | $0.0014 | 9.2s |

### What the data actually says

1. **The set-overlap floor measures conformity to Haiku, not pick
   quality.** Haiku-against-itself only hits 0.871 — that's the noise
   ceiling of LLM stochasticity. The 0rtg-spec'd 0.85 threshold is
   essentially "match Haiku exactly", which only Haiku can do. The
   floor protocol needs revision; values were starting positions per
   the 0rtg ticket.

2. **The judge rubric tells a clearer story.** All three open-weight
   candidates concentrate at rubric value 2 ("Mostly poor picks. Too
   many journal articles, dissertations, or items a listener can't
   access"). Haiku concentrates at 4 ("Mostly good picks").

3. **Nemotron's training-data alignment shows in the long tail.**
   Nemotron-Nano-9B-v2 got one judgement at 4 and one at 3, more than
   Llama (uniformly 2) or Gemma 3 4B (uniformly 2). The NSCLv1
   license tradeoff (see License Caveats above) isn't worth a
   ~0.4-rubric-point lift over Llama at the small-tier.

4. **Cost ranking confirms Stage 1 inference.** Open-weight candidates
   are 17-60× cheaper per call. At project volume (~1-2M small-tier
   tokens/year) the cost gap is pennies/year.

5. **Nemotron's latency is poor** (134s for 8 inputs vs 9-20s for
   others). Reasoning models emit `reasoning_content` separately from
   `content`; first run hit max_tokens=512 → reasoning ate the budget
   → empty content (BleakHouse-7usk). Fixed at max_tokens=4096; cost
   rose marginally but latency stays bad even at higher budget.

### Judge methodology + bias caveat

Judge = Haiku 4.5 with an absolute 1-5 rubric (see
`enrichment/llm/eval/judge.py:_JUDGE_SYSTEM`). The candidate output's
tags are extracted, paired with the full candidate list (so the
judge can verify tag→entry mapping), and presented to Haiku.

**Bias**: Haiku judging Haiku-picks favours Haiku-style picks.
Mitigation: the rubric is absolute (not "compare to baseline"); the
judge sees the picks alongside the full candidate list and rates
against accessibility/listener-fit criteria, not against the
baseline's specific choices. The 1.5-rubric-point gap between Haiku
(3.5) and the open-weight candidates (2.0-2.38) is plausibly real
even after discounting for bias — neither Llama nor Gemma 3 4B got
ANY judge rating above 2.

### Routing decision for listener_pick (input to BleakHouse-9k9n)

**Keep Anthropic Haiku 4.5 as the default for listener_pick.**

Rationale:
- Quality (user's primary criterion): meaningful gap (3.50 vs
  2.0-2.38 on a 1-5 scale; median 4 vs 2).
- Cost (secondary): $0.04 per 8 inputs vs $0.0007-0.0040. At project
  volume of ~1-2M small-tier tokens/year, total Haiku cost stays
  under $5/year — not worth a quality compromise.
- Lock-in resistance: Anthropic is closed-weight, but the seam makes
  a future flip a one-line `settings.register_task` change. The
  non-API constraint (Principle 6) is satisfied by routing OTHER
  tasks (passage_enrichment) to open-weight, not by routing this
  small high-volume task.

---

## Stage 2 Tier M-Haiku results — passage_enrichment (2026-05-12)

3 chapters sampled (seed=42, paragraph range 15-50): our_mutual_friend/c9 (32p), daniel_deronda/c9 (37p), daniel_deronda/c18 (42p). Baseline = Haiku's own existing enrichment in `passages_enriched.json`. Schema = `ChapterEnrichmentResult` with 17 Literal/required-string fields per paragraph.

| Candidate | schema valid | coverage | literal-field agreement | total cost | wall |
|---|---:|---:|---:|---:|---:|
| Anthropic Haiku 4.5 (baseline) | **1.00** | 1.00 | **0.802** | $0.1724 | 210s |
| Qwen 2.5-72B-Instruct on DeepInfra | 0.67 | 0.67 | 0.521 | $0.0106 | 2711s (45 min) |
| Llama 3.3-70B-Instruct-Turbo on DeepInfra | **0.00** | 0.00 | n/a | $0.0082 | 960s (16 min) |

### What the data shows

1. **Haiku-vs-itself literal agreement is 0.80** — the noise floor for this task. Disagreement isn't error; it's stochasticity in Literal-field assignment (a paragraph that's borderline "description" vs "transition" will swing across runs).

2. **Qwen 2.5-72B on DeepInfra has serious problems with this schema**:
   - 1 of 3 chapters timed out at 30 min and returned malformed (`Request timed out` after 2 retries).
   - On the 2 chapters that succeeded, literal-field agreement is 0.52 — **well below the 0.80 noise floor**. So the disagreements are real classification differences, not noise.
   - Latency per chapter: 413-495s on success, 1802s on timeout. Compared to Haiku's 56-77s.

3. **Llama 3.3-70B-Instruct-Turbo on DeepInfra fails schema entirely** (0/3 chapters):
   - Returned markdown-wrapped JSON code blocks instead of a flat `ChapterEnrichmentResult`.
   - Used wrong field names: `interest` not `interest_score`, `characters` not `characters_present`+`characters_speaking`, `provision_dimensions` as nested object instead of flat `prov_*` fields.
   - `emotional_register` as string `"neutral"` instead of a list.
   - `plot_function` value `"Introduction"` not in the Literal enum.
   - This is despite the seam sending `response_format={"type":"json_schema","json_schema":{...}}`. DeepInfra's strict-flag is `False` in our capabilities table (conservative default); Llama-Turbo's quantization may also degrade schema-following.

### Routing decision for passage_enrichment (input to BleakHouse-9k9n)

**Keep Anthropic Haiku 4.5 for passage_enrichment.** Open-weight candidates on DeepInfra are not viable for this task at our current configuration:

- Llama 3.3-70B Turbo: complete schema failure.
- Qwen 2.5-72B: 33% failure rate, 30-min timeouts, agreement below noise floor on successful runs.

Annual cost stays on Anthropic Batch (50% off Haiku = $0.50/M input + $2.50/M output). At our project volume of ~50-100M tokens/year for passage_enrichment, that's ~$50-150/year.

### Follow-ups worth trying before declaring open-weight unviable for this task

The result above is a verdict on *this configuration* (DeepInfra hosting + our seam's strict=False default + the dense BleakHouse schema). Worth testing whether different choices change the picture:

- **Together with `strict=True`**: capabilities table flags Together as `strict=True`. Hosted Qwen 2.5-72B-Instruct on Together with the strict flag honored might fix Llama-style schema misses. File as follow-up ticket.
- **Smaller per-call inputs**: split chapters in half (15-25 paragraphs per request); reduces output size and schema complexity per call. The production pipeline already does this for chapters >200 paragraphs; we could lower the threshold.
- **A model with stronger structured-output capability**: DeepSeek-V3.2 or Qwen-3 (newer than 2.5).
- **Self-hosted vLLM with `guided_json`** (Modal): vLLM's strict grammar-based decoding is more reliable than provider-level `response_format` for complex schemas. But back to the self-hosting cost question.

These are improvements at the margin, not changes in conclusion. The conclusion is: passage_enrichment is harder than listener_pick on open-weight, and Haiku-on-batch is a legitimate default.

### Open questions for Tier M and Tier L

The Tier S protocol generalises:
- Build a fixture from real pipeline data (passage_enrichment from
  chapter inputs; prose from short-format episode prompts).
- Run candidates via the seam (already capable).
- Score via LLM-as-judge with task-specific rubrics — but for prose
  the judge rubric matters much more, and Haiku-as-judge bias is
  more serious since Haiku also generates the prose baseline.
  Probably needs a blinded human-preference protocol per 0rtg rather
  than LLM-as-judge.

These are separate tickets when ready.

---

## Decision context — what this survey commits us to

Given the corrected usage pattern (novel-onboarding bursts; annual
LLM bill ~$20-80 regardless of hosting) AND the corrected
interpretation of non-lock-in (open-weight + multi-host
availability, not literally self-hosted), the recommendation
simplifies considerably:

**All defaults can be hosted.** The lock-in constraint is satisfied
by choosing open-weight models that are available from multiple
hosted providers via OpenAI-compatible APIs. Self-hosting on Modal
stays as a documented fallback for the day a provider changes terms
or withdraws a model.

Provisional routing direction (Stage 1 inference, updated after
confirming hosted Gemma 4 26B availability):

- **Small tasks (listener_pick, reading_list_winnow, reference_tools,
  quote_verification)**: Stage 2 picks between three on DeepInfra —
  Llama 3.1 8B ($0.02/$0.05, broad portability),
  NVIDIA-Nemotron-Nano-9B-v2 ($0.04/$0.16, training data targets
  structured outputs), and Gemma 3 4B ($0.04/$0.08, smaller).
  Decided by quality on the 20-input fixture; price is noise at
  our volume. Revisit when Gemma 4 E2B/E4B reach serverless
  hosting (Azure-only currently); they'd be a family-consistent
  alternative.

- **Mid batch tasks (passage_enrichment, passage_contexts)**:
  **Qwen 2.5-72B-Instruct** on DeepInfra ($0.36/$0.40) as primary,
  alternate at Together, Fireworks. Apache 2.0 → portable. Stage 2
  benchmark validates quality vs Haiku-batch baseline. The
  Anthropic-Batch-Haiku path stays available as opt-in (50%
  discount may justify it on cost discipline for very large novel
  onboardings).

- **Prose generation (short format)**: **`gemma-4-26B-A4B-it` (MoE)
  on DeepInfra** as primary candidate. $0.07/$0.34/M is cheaper
  than the dense 31B variant; Apache 2.0; hosted by
  Novita/Featherless/DeepInfra/Fireworks (strong multi-host
  portability). Stage 2 validates blinded preference vs Sonnet-on-
  short and runs the head-to-head against dense Gemma 4 31B
  ($0.13/$0.38 on DeepInfra). DeepSeek-V3.2 on DeepInfra is the
  non-Gemma alternate if Stage 2 surfaces a quality concern.

- **Legacy prose (long format, opt-in)**: Anthropic Sonnet 4.6.

- **Lock-in mitigation**: the seam reads `(provider, model, base_url)`
  from settings; switching providers is a config change. Document
  per-task an alternate provider in `enrichment/llm/settings.py`
  so operators can flip with one env var when needed.

Modal self-hosting stays in the toolbox for:
- The day a hosted provider withdraws a model we depend on.
- A future fine-tune path (low priority but real).
- A specific task where benchmark data shows self-hosting wins on
  quality at a margin that justifies the ops cost.

But Modal is NOT a Stage 1 default. The annual ops cost of
maintaining a Modal vLLM endpoint (image rebuilds, model-weight
caching, occasional cold-start debugging) exceeds the $50/year of
hosted-API spend it would replace.

What the survey does NOT recommend:
- Self-hosting on Modal as a primary default for any task.
- Cerebras as a primary default for any task (narrow catalogue +
  imminent withdrawal date = exactly the lock-in risk the
  constraint exists to avoid). Cerebras can still be the opt-in
  fast-inference path for `gpt-oss-120b` if that model wins on a
  task; document but don't default.

Stage 2 questions that matter under this view:
1. **Qwen 2.5-72B-Instruct vs Anthropic Haiku-batch on passage_enrichment**:
   schema validity, content fidelity, cost-per-novel-onboarding.
2. **Gemma 4 31B vs DeepSeek-V3.2 vs Llama 3.3 70B Turbo on short-prose**:
   blinded preference vs Sonnet-on-short, JSON-strict reliability,
   short-format word-count discipline.
3. **Llama 3.1 8B on listener_pick + reading_list_winnow**: set-
   overlap with Haiku baseline. Lowest stakes; if it's even close,
   the cost differential ($0.04/M vs $1-3/M) makes the call easy.

This is a Stage 1 inference, not a decision. Stage 2 results revise.
