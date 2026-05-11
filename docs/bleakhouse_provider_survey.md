# BleakHouse Provider Survey

**Status**: Stage 1 (desk survey) complete 2026-05-11. Stage 2 (live
benchmark on shortlist) blocked on user decision about API key
provisioning + budget. See "Stage 2 shortlist" + "Open work" below.

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
| Gemma 4 | Together (31B); DeepInfra serves Gemma 3 27B but not yet 4. Likely to broaden but newer. |
| Phi-4 | Limited hosted footprint; mostly self-hosted right now. |
| Mistral / Mixtral | Together, DeepInfra, Fireworks. Broad. |

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

**Candidates (4 hosted + 1 fallback-rehearsal)**:

1. **Llama 3.1 8B on DeepInfra** (Tier S). Cheap; broad portability;
   high-frequency small-structured tasks.
2. **Qwen 2.5-72B-Instruct on DeepInfra** (Tier M). Apache 2.0;
   broad portability; passage_enrichment + mid-structured tasks.
   Stage 2 compares schema validity + content fidelity to current
   Anthropic Haiku baseline.
3. **Gemma 4 31B on Together** (Tier L hosted). Apache 2.0; same
   family as user-preferred Gemma 4 26B MoE but dense + currently
   available hosted. Stage 2 measures blinded preference vs
   Sonnet-on-short.
4. **DeepSeek-V3.2 on DeepInfra** (Tier L alternate). DeepSeek
   License; 160k context. Head-to-head with Gemma 4 31B on the
   same short-prose fixture. Pick winner of (3) vs (4) as default.

**Fallback rehearsal** (not a Stage 2 quality data-point; an
operational dry-run):

5. **Qwen 2.5-72B-Instruct deployed on Modal H100**, exercising the
   vLLM-on-Modal recipe end-to-end once during Stage 2. Goal: prove
   the fallback path is operational and document any deployment
   gotchas. Do NOT use this as a quality-comparison point; do NOT
   make it a default. It's there so when a hosted provider does
   eventually do something we don't like, we have a known-working
   migration path.

If Stage 2 turns up a surprise — e.g. Llama 3.3 70B Turbo on
DeepInfra clears the prose floor at $0.28/M blended — fold it into
the candidate list at decision time rather than expanding Stage 2
itself.

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

Provisional routing direction (Stage 1 inference):

- **Small tasks (listener_pick, reading_list_winnow, reference_tools,
  quote_verification)**: **Llama 3.1 8B** on DeepInfra as primary,
  alternate at Groq, Together, Fireworks. Apache-2.0-equivalent
  Meta Community License → portable.

- **Mid batch tasks (passage_enrichment, passage_contexts)**:
  **Qwen 2.5-72B-Instruct** on DeepInfra ($0.36/$0.40) as primary,
  alternate at Together, Fireworks. Apache 2.0 → portable. Stage 2
  benchmark validates quality vs Haiku-batch baseline. The
  Anthropic-Batch-Haiku path stays available as opt-in (50%
  discount may justify it on cost discipline for very large novel
  onboardings).

- **Prose generation (short format)**: between **Gemma 4 31B** (on
  Together; same family as the user's Gemma 4 26B preference;
  dense vs MoE; Apache 2.0) and **DeepSeek-V3.2** (on DeepInfra;
  DeepSeek License; 160k context). Stage 2 quality head-to-head
  decides. Both have decent multi-host availability now; both will
  broaden. Llama 3.3 70B Turbo on DeepInfra is a wildcard at very
  low price ($0.28/M blended) but uses quantization that may hurt
  schema-strict output.

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
