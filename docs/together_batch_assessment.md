# Together AI Batch Inference: assessment for BleakHouse

**Status:** documented-evidence-only assessment, no empirical probes. Companion to `docs/structured_output_review.html` (synchronous inference) and `docs/self_hosted_provider_assessment.md` (Modal/Runpod). This doc covers the third category: *managed serverless inference in async/batch mode*.

## TL;DR

Together's batch API is a real product with a real discount, but the 50%-off list is **six specific models**, and **none of them match BleakHouse's current candidate set**. gpt-oss-120B (our most portable open-weight candidate) is not on the discount list — it would run through batch at full synchronous price with a 24h SLA. Whether `response_format: json_schema` even works per-line in Together's batch body is **not documented either way**.

The fit is poor today. Worth revisiting if (a) we add a discount-eligible model to the candidate set, (b) bulk re-enrichment becomes a real workload, or (c) we want to test the json_schema-in-batch question empirically.

## What Together Batch is

A managed batch endpoint that takes a JSONL file with up to 50,000 requests, queues them on Together's regular serverless infrastructure, and returns a results file. The product page promises **up to 50% savings vs synchronous rates** on a documented list of models, with a **best-effort 24-hour SLA** (testimonials and docs say "often within hours").

Operationally: you don't manage GPUs (unlike Modal/Runpod) and you don't pay per second (unlike Modal/Runpod). You pay the same per-token rates as synchronous, minus the discount where applicable. The trade is **per-call latency for throughput**: you don't see results until the batch completes, but you don't tie up your synchronous concurrency budget while it runs.

## What the docs actually commit to

Sourced from [docs.together.ai/docs/inference/batch](https://docs.together.ai/docs/inference/batch) and [batch/tutorial](https://docs.together.ai/docs/inference/batch/tutorial), verified 2026-05-14.

### Discount-eligible models (verbatim)

These six get the documented 50% discount:

- `meta-llama/Llama-3.3-70B-Instruct-Turbo`
- `meta-llama/Llama-3-70b-chat-hf`
- `Qwen/Qwen2.5-7B-Instruct-Turbo`
- `mistralai/Mixtral-8x7B-Instruct-v0.1`
- `zai-org/GLM-4.5-Air-FP8`
- `openai/whisper-large-v3`

### Models explicitly *unsupported* in batch (verbatim)

The docs enumerate this exclusion list: DeepSeek variants, MiniMax, Kimi, Qwen3.5, GLM-5 variants.

### Other models

The marketing page says "any serverless model" can run via batch. The docs themselves don't expand on this. Practically: it appears the model has to be Together-hosted, and pricing for non-listed models defaults to full synchronous rate (no discount). **gpt-oss-120B falls here**: not in the discount list, not in the exclusion list — likely supported via batch at sync price, but not committed to in writing.

### Endpoints supported

- `/v1/chat/completions` (text)
- `/v1/audio/transcriptions`
- `/v1/audio/translations`

No documented batch support for `/v1/embeddings` or other endpoints.

### Per-line JSONL shape

```json
{"custom_id": "request-1", "body": {"model": "...", "messages": [...], "max_tokens": 200}}
```

- `custom_id`: required, max 64 chars, reconciles inputs to outputs (results return in arbitrary order)
- `body`: required, object matching the endpoint schema (chat-completions body)
- `method`: required only for audio batches (set to `"FILE"`)

### What's NOT in the docs

- Whether `response_format: json_schema` (or any structured-output config) is supported inside `body`. No example, no statement either way.
- Whether `extra_body` / `reasoning_effort` parameters propagate.
- Whether function-calling / tool-use works per-line in batch.
- Whether `cache_control` semantics carry over.

### Limits

- 50,000 requests per batch
- 100 MB per input file
- 30 billion tokens enqueued per model at any time per user
- Best-effort 24h completion; advised to wait 72h `IN_PROGRESS` before contacting support

### Lifecycle

States: `VALIDATING`, `IN_PROGRESS`, `COMPLETED`, `FAILED`, `EXPIRED`, `CANCELLED`. Polling cadence: every 30-60s (tighter loops hit rate limits).

### SDK

`pip install together>=2.0.0`. The relevant calls are:

```python
client = Together()
file_resp = client.files.upload(file=jsonl_path, purpose="batch-api", check=False)
batch = client.batches.create_batch(file_id=file_resp.id, endpoint="/v1/chat/completions").job
batch = client.batches.retrieve(batch.id)  # poll
with client.files.with_streaming_response.content(id=batch.output_file_id) as resp:
    # stream output JSONL
```

## Fit for BleakHouse's current candidate set

| Our candidate | Discount in Together batch? | Notes |
|---|---|---|
| Anthropic Haiku 4.5 | n/a — not on Together | Anthropic has its own `messages.batches` API with 50% off, already used in the existing pipeline |
| OpenAI gpt-4o-mini | n/a — not on Together | OpenAI has its own Batches API |
| DeepSeek-V4-Flash | **No** — Together docs explicitly exclude DeepSeek variants from batch | — |
| Gemma 4 26B-A4B-it | Not on the discount list. Listed on Together's catalogue front page as Gemma 4 31B (different variant); 26B-A4B coverage on Together is uncertain | — |
| Qwen3-Next 80B-A3B-Instruct | Not on the discount list; not in the exclusion list | Likely supported at sync price |
| **gpt-oss-120B** | Not on the discount list; not in the exclusion list | Likely supported at sync price |
| gpt-oss-20B | The 6-discount list includes related family member Qwen2.5-7B-Turbo but not gpt-oss-20B specifically | — |

**None of our currently-shortlisted candidates is in the 50%-off bucket.**

The 6 discount-eligible models break down as:
- 4 Llama / Mixtral / Qwen-2.5 / GLM-4.5 generation — all older or smaller than our current bar
- 1 Whisper (audio, not relevant to enrichment)
- Llama 3.3 70B Turbo was already ruled out empirically in this session — markdown-wrapped pseudo-JSON regardless of strict flag (per the early `debug_structured_output.py` probe)

## Workload economics

Assuming gpt-oss-120B runs via Together's batch endpoint *at full synchronous Together pricing* (no discount), and assuming `response_format: json_schema` works per-line (undocumented):

- Together synchronous gpt-oss-120B pricing is not in their catalogue card directly. Per artificialanalysis.ai it's in the ~$0.15/$0.75 per 1M area on Together (~3× DeepInfra's $0.04/$0.19).
- One BleakHouse onboarding cycle ≈ 5M input × 0.15/M + 14.75M output × 0.75/M ≈ $0.75 + $11 = **~$12 per cycle**.
- DeepInfra synchronous gpt-oss-120B: **~$5 per cycle**.
- Anthropic Haiku 4.5 batch (50% off via `messages.batches` API, what we already use): ~$36 per cycle. *See breakdown below.*

So even if Together's batch API serves gpt-oss-120B with json_schema cleanly, **the price is ~2.4× DeepInfra's synchronous rate**. The 24h SLA buys nothing we don't already get from DeepInfra synchronous + concurrency (which we already use).

### Haiku cost breakdown (what's in the $36 and what isn't)

The $36 above reflects the 50% Anthropic batch discount **but not prompt caching**. It's worth stating clearly *why* caching doesn't help here, because the reason isn't the one usually quoted.

Anthropic's prompt cache is whole-prefix up to a `cache_control` breakpoint — a breakpoint can sit on the system block, a user content block, or anywhere else, and everything before it is cached. The 1024-token minimum applies to **the cached prefix size**, not the system block specifically.

So the real test is: **on the current per-chapter shape, is there any static prefix ≥1024 tokens that recurs across calls?**

- System (~500 tokens, novel-specific instructions): same across chapters of a novel, but below the 1024-token minimum on its own.
- User message (~3.2k tokens of chapter text): above the threshold, but unique per call.
- One call per chapter, no inner loop.

No matter where you place the marker, nothing meaningful repeats. Cache writes have nothing to amortise against. The per-chapter shape simply isn't a workload that prompt caching can help.

### What it would take to make caching fire on Haiku enrichment

| Design | Cacheable prefix | Fires? | Net savings vs $36 baseline |
|---|---|---|---|
| Enlarge system block to ~1100 tokens (add per-novel 3-arc / character / theme context) | 1100 tokens × ~50 chapters/novel | yes | ~$0.45/cycle (rounding error: input is only $1.48 of $36; cache writes ate most of the saving) |
| Per-paragraph + full chapter as cached prefix | ~5k tokens × ~64 paragraphs/chapter | yes | **negative**: ~$65/cycle (per-paragraph adds ~30% JSON-envelope output, and output at $5/M dominates) |

The reason caching can't materially improve Haiku enrichment is structural, not configurational: **at Haiku's $5/M output rate and our output volume (~14M tokens/cycle), input is ~$1.48 of the $36 total**. Even cutting input to zero saves less than ten percent; caching only cuts the *reused* fraction of input, which is bounded above by that $1.48.

### Reframed table

| Haiku call shape | Caching fires? | Sync or batch | Cost / onboarding cycle |
|---|---|---|---|
| per-chapter | no — no recurring ≥1024-token prefix | sync | ~$72 |
| **per-chapter** | **no — same reason** | **batch (production)** | **~$36** |
| per-chapter + enlarged system (~1100t) | yes, modestly | batch | ~$35.55 |
| per-paragraph + chapter cached | yes, but output overhead wins | sync | ~$129 |
| per-paragraph + chapter cached | yes | batch | ~$65 |

For the Together comparison, **$36 is the right comparator** — not because caching can't fire on the current shape, but because at this output volume there is no Haiku configuration where caching meaningfully improves on it. The current per-chapter shape is genuinely cost-optimal for Haiku.

## Where Together batch could become relevant

1. **If a Together-discounted model becomes a candidate.** GLM-4.5-Air-FP8 is in the discount list and we haven't probed it. If it turns out to be schema-compliant on Together's batch endpoint, the 50% discount on $0.x/$1.x rates could undercut DeepInfra synchronous. We previously found that GLM-4.7-Flash has a reasoning-content quirk; the 4.5 generation may or may not share it. Not probed.

2. **Bulk re-enrichment.** If we ever decide to re-enrich all 18 novels in parallel (after a schema change), the 50k-requests-per-batch limit and 24h SLA become an attractive shape vs orchestrating ~1M synchronous calls through DeepInfra ourselves. But again, the model has to be on Together's batch-discount list for the economics to flip — at full sync price the savings disappear.

3. **The json_schema-in-batch question itself.** Whether Together's batch decoder honours `response_format: json_schema` per-line is genuinely undocumented. Anyone planning to depend on Together for structured-output batch work would want this answered before committing. A ~2-request probe JSONL would resolve it; cost negligible, time is up to 24h wall-clock.

## Recommendation

**Don't wire Together batch into the BleakHouse pipeline today.** The discount list doesn't include any of our current candidates, gpt-oss-120B and Qwen3-Next would run at full sync price (worse economics than DeepInfra), and the `response_format: json_schema` support is undocumented.

Revisit if one of these is true:

- We add **GLM-4.5-Air-FP8** to the candidate set after probing it (the only discount-eligible model that could plausibly handle our task).
- We commit to **bulk re-enrichment** as a recurring workload (multi-novel parallel runs benefit from batch shape regardless of discount).
- We decide to **empirically resolve the json_schema-in-batch question** with a small probe JSONL — this would close one of the documented unknowns without committing to use.

The Anthropic native_batch API is already our existing batch shape; it has 50% off Haiku (`$0.50/$2.50` per 1M) and the structured-output config we already depend on. That remains the right batch option for Haiku-served work; Together adds nothing for non-Together models.

## Sources

- [Together AI Batch Inference (product page)](https://www.together.ai/batch-inference) — verified 2026-05-14
- [docs.together.ai/docs/inference/batch](https://docs.together.ai/docs/inference/batch)
- [docs.together.ai/docs/inference/batch/tutorial](https://docs.together.ai/docs/inference/batch/tutorial)
- [docs.together.ai/docs/inference/batch/manage](https://docs.together.ai/docs/inference/batch/manage)
- artificialanalysis.ai per-provider pricing pages for cross-reference on non-discount sync rates
