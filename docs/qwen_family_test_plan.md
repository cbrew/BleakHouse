# Qwen-family candidate test plan

**Status:** test plan, 2026-05-14. Companion to
`docs/open_weights_pipeline_plan.md` (the strategic plan for adding
open-weight alternatives); this doc covers the empirical work needed
to evaluate the specific Qwen-family candidates suggested 2026-05-14.

Audio candidates (Qwen3-TTS, Qwen3-ASR, Qwen3-ForcedAligner) are
**deferred** per direction. This plan covers prose/script, structured
tasks, and embeddings only.

## Candidate matrix (provider survey, 2026-05-14)

### Prose/script (Phase 2.5c host brief + Phase 3 script generation)

**Standing hypothesis (suggestion-grade, untested for BleakHouse):
DeepSeek may be the strongest prose-writing candidate.** This came in
as a recommendation from another assistant 2026-05-14, without
attribution to specific benchmarks for our use case. The plan
treats it as a hypothesis to test (Stage 3 elevates DeepSeek to a
primary candidate, not a comparator) rather than as established
fact.

| Model | License | Confirmed providers | Pricing (in/out per 1M) | Notes from this session |
|---|---|---|---|---|
| **DeepSeek-V4-Pro** | MIT | DeepInfra, Fireworks, Novita, SiliconFlow, DeepSeek (1st-party), Together, OpenRouter — **7+ providers** | DeepInfra $1.74/$3.48 (list); DeepSeek 1st-party $0.435/$0.87 (75% promo through 2026-05-31); OpenRouter $0.435/$0.87 | **DeepSeek flagship.** 1.6T total / 49B active MoE, 1M-token context. Promo pricing makes it currently cheaper than its list price suggests. **Primary prose-quality candidate to test against Qwen3-235B baseline.** |
| Qwen3-235B-A22B-Instruct-2507 | Apache 2.0 | Cerebras (preview), DeepInfra, Novita | $0.071 / $0.10 (DI) | Already `cerebras_qwen` generator. User-validated for Phase 3 ("not awful"). Failed at chapter-scale enrichment on DeepInfra (different task). Current best-known Apache 2.0 option. |
| Qwen3.6-35B-A3B | Apache 2.0 | DeepInfra | $0.15 / $0.95 | Smaller MoE (35B / 3B active). "Is small enough good enough" Qwen test. Untested at script-generation scale; structured-output probe passed with `enable_thinking=False`. |
| Kimi K2.6 | Modified MIT | **11 providers**: Fireworks, Parasail, CoreWeave, Clarifai, Cloudflare, Together (FP4), Moonshot/Kimi, Azure, DeepInfra (FP4), SiliconFlow (FP8), Novita | $0.75 / $3.50 (DI) | 1T params total / 32B active MoE. Non-Apache MoE comparator. |
| DeepSeek-V4-Flash | MIT | 5 providers (DeepInfra FP4, SiliconFlow FP8, DeepSeek 1st-party, Novita, Parasail FP8) | $0.14 / $0.28 (DI) | Cheap DeepSeek tier. Already passed our enrichment probe. Worth running for cost-tier comparison against V4-Pro. |
| DeepSeek-V3.2 | MIT | DeepInfra; V4 family is on 5 providers, V3.2 likely similar | $0.26 / $0.38 (DI) | Older DeepSeek; useful only if V4 path has issues |
| Kimi K2.5 | Modified MIT | 15 providers | $0.90 blended (DI) | Older Kimi sibling. Skip unless K2.6 has unexpected issues. |

### Structured tasks (passage_enrichment + Phase 0 + winnow + quote verify)

| Model | License | Confirmed providers | DeepInfra price (in/out) | Notes |
|---|---|---|---|---|
| Qwen3-32B | Apache 2.0 | DeepInfra, Together, Fireworks, Novita, OpenRouter, Groq | $0.08 / $0.28 | Dense 32B. Untested. |
| Qwen3-30B-A3B | Apache 2.0 | DeepInfra | unknown | 30B/3B MoE. Earlier probe in this session: emitted `<think>` tags in content, JSON parse failed. Re-probe needed with explicit thinking-disable. |
| Qwen3-14B | Apache 2.0 | DeepInfra ($0.12/M); also documented as drop-in OpenAI-compat on Together, Fireworks, Novita, OpenRouter, Groq though pricing wasn't quoted directly | $0.12 / unknown | Smallest of the trio — "is 14B enough?" question |
| Qwen3.6-35B-A3B | (same as prose row above) | DeepInfra | $0.15 / $0.95 | Cross-listed; useful baseline since it passed our enrichment probe |

### Embeddings (LanceDB vector store for the `embedding` pipeline variant)

| Model | License | Confirmed providers | Notes |
|---|---|---|---|
| Qwen3-Embedding-0.6B | Apache 2.0 | DeepInfra (also has `Qwen3-Embedding-0.6B-batch`) | smallest variant |
| Qwen3-Embedding-4B | Apache 2.0 | DeepInfra (also batch variant) | mid |
| Qwen3-Embedding-8B | Apache 2.0 | DeepInfra (also batch variant) | largest/strongest in family |
| QZhou-Embedding (Kingsoft-LLM) | TBD — base model is Qwen2.5-7B-Instruct (Apache 2.0) | Hugging Face model card; **provider hosting unverified**. Likely self-host via vLLM/HF Inference if not on a managed provider | SOTA on MTEB and CMTEB benchmarks (Aug 2025). Built on Qwen2.5-7B. |

### Open provider questions to resolve in Stage 0

- DeepSeek-V3.2 multi-provider list (only DeepInfra confirmed; SiliconFlow / Together / Novita likely)
- Qwen3-30B-A3B and Qwen3-14B pricing on providers other than DeepInfra
- QZhou-Embedding hosting status — is it on any managed provider, or self-host only?
- Whether Cerebras's preview catalogue includes any of the smaller Qwens (3.6-35B / 32B / 30B / 14B) — none currently registered in `params.yaml`

## Test stages

### Stage 0 — Provider verification (1-2 hours, no API spend)

Resolve the four open provider questions above via vendor catalogue
pages and the `client.models.list()` endpoint where we have an API key.
Add confirmed entries to `enrichment/llm/cost_table.py`. Output: a
single revision to this doc with the matrix complete and the lock-in
story (multi-provider vs single-provider) fully documented per
candidate.

### Stage 1 — Structured-output schema-feature probes (~1 hour, ~$0.05 API spend)

For each new structured-task candidate (Qwen3-32B, Qwen3-30B-A3B,
Qwen3-14B), run `scripts/structured_output_review.py` and merge the
results into the existing 8-candidate matrix.

**Steps**:

1. Add three `Candidate` entries to `scripts/structured_output_review.py`:
   - `qwen3_32b` (DeepInfra)
   - `qwen3_30b_a3b` (DeepInfra) — pass `extra_body={"chat_template_kwargs": {"enable_thinking": False}}` per the Qwen 3.5+ pattern documented in the structured-output review
   - `qwen3_14b` (DeepInfra)
2. Run the 16-test matrix. Existing cells are cached; only the 48 new cells fire (~$0.05 total).
3. Re-render `docs/structured_output_review.html`. The matrix grows from 8 columns to 11.

**What we expect to learn**:
- Whether Qwen3-30B-A3B's thinking leak is fixable with the disable flag (we have evidence Qwen3.6-35B-A3B's was).
- Whether dense Qwen3-32B and Qwen3-14B have different schema-feature acceptance than the MoE Qwen3-Next-80B that hallucinated in our enrichment probe.
- Whether a 14B model can hold a structured-output contract at all.

**Output**: updated structured-output review HTML; entries in cost_table.py for the three new candidates.

### Stage 2 — Per-paragraph enrichment fit (~1 day, ~$0.20 API spend)

For each Stage-1 survivor (whichever Qwens passed schema-validity on
the bulk of tests) **plus** DeepSeek-V3.2, run the per-paragraph
enrichment fixture against the `north_and_south/c6` chapter we've used
throughout this session. Compare outputs side-by-side against the
Haiku baseline using the existing `scripts/eyeball_compare.py`
machinery.

**Steps**:

1. Add the surviving candidates to `scripts/eyeball_compare.py`'s `CANDIDATES` dict.
2. Run on 3 paragraphs (quartile sample), the same protocol used for the gpt-oss / DeepSeek-V4-Flash eyeball compare in this session.
3. For survivors, run `scripts/run_eval_passage_enrichment.py --n 1 --candidates <candidate>` to get full-chapter behaviour (cost, latency, schema validity, cache hit rate).
4. Update the candidate scoring per task in `docs/open_weights_pipeline_plan.md`.

**What we expect to learn**:
- Whether any 14B–35B model handles per-paragraph enrichment competently. If yes, we've found a *much cheaper* alternative than gpt-oss-120B for the enrichment phase.
- Whether DeepSeek-V3.2 is meaningfully better/worse than V4-Flash for our enrichment task.
- A specific recommended candidate for the enrichment phase, with cost numbers.

**Output**: empirical recommendation for the open-weight enrichment alternative, added to the open-weights plan as Stage C.2's concrete `ModelSpec` choice.

### Stage 3 — Prose/script comparator (~3 days, ~$5-10 API spend)

Run Phase 3 on one canonical novel × panel through each candidate,
using the same Phase 0/1/2/2.5 inputs. **Test order reflects the
DeepSeek-for-prose hypothesis: DeepSeek candidates first, then
Qwen, then Kimi.**

| Order | Candidate | Path | Cost angle |
|---|---|---|---|
| **3.1** | **DeepSeek-V4-Pro** | DeepInfra ($1.74/$3.48 list) or DeepSeek 1st-party ($0.435/$0.87 promo) | The headline test of the "DeepSeek is better for prose" hypothesis. Run via DeepSeek 1st-party during the promo for best economics. |
| **3.2** | **DeepSeek-V4-Flash** | DeepInfra ($0.14/$0.28) | Same family, cheap tier. Tells us if the prose quality is family-wide or only at flagship scale. |
| **3.3** | **Qwen3-235B-A22B-Instruct-2507** | Cerebras (existing `cerebras_qwen` runs already exist for this fixture — no new spend if we reuse) | User-validated baseline. Reference point for DeepSeek comparison. |
| **3.4** | **Qwen3.6-35B-A3B** | DeepInfra ($0.15/$0.95) | "Is small enough" test. Cheapest Qwen candidate; useful if quality holds. |
| **3.5** | **Kimi K2.6** | DeepInfra ($0.75/$3.50) | Non-Apache MoE comparator. Skip if 3.1-3.4 give us a clear winner. |

Skipped from the original plan:
- **DeepSeek-V3.2** — V4-Pro is the better DeepSeek prose candidate; only test V3.2 if V4-Pro has unexpected issues.
- **Kimi K2.5** — K2.6 is newer; skip K2.5 unless K2.6 misbehaves.

**Steps**:

1. Pick a canonical run for comparison — recommend `bh_trn_literary_hostprep` (the existing Anthropic Sonnet baseline). Reuse its Phase 0/1/2.5 outputs for fair comparison.
2. **Generalise the cerebras driver** (`enrichment/phase3_runner.py`) to support arbitrary openai-compat hostings. The current driver hard-codes the Cerebras SDK; the generalised version takes `(base_url, api_key, model)` and runs via the `openai` package. ~2 hours of work; **must be done before 3.1-3.5 because DeepSeek-V4-Pro is not on Cerebras**.
3. Run candidates in order 3.1 → 3.5. After each, listen + judge before committing to the next. **Stop early if a clear winner emerges** — there's no obligation to run all five.
4. Record per-candidate: total cost, wall-time, output token counts, qualitative judgment.
5. Once a winner (or two-way tie) is identified, run a **second-novel confirmation** — same candidate(s) on a different novel × panel — to guard against single-fixture artifacts.

**What we expect to learn**:
- Whether DeepSeek-V4-Pro is meaningfully better at literary dialogue than Qwen3-235B (the hypothesis under test).
- Whether the gap between V4-Pro and V4-Flash justifies V4-Pro's ~12× higher price (or whether V4-Flash is "good enough").
- Whether Qwen3.6-35B-A3B at $0.15/$0.95 can hold quality — would be a huge cost-tier win.
- A specific candidate (with provider, pricing, evidence) to register as the open-weight Phase 3 alternative.

**Output**: an empirical prose-tier recommendation with per-candidate evidence and audio samples; updates to `params.yaml` for any new generators; updates to Stage E of the open-weights plan. The Anthropic Sonnet default stays unchanged regardless of outcome.

**Cost note**: with the DeepSeek 1st-party promo through 2026-05-31, running V4-Pro is currently cheaper than it will be after the promo ends. If we want a real cost number to compare against Qwen3-235B's $0.071/$0.10 long-term, multiply by 4× to model post-promo DeepSeek pricing.

### Stage 4 — Embedding comparator (~1 day, ~$1 API spend)

Replace `text-embedding-3-small` in the LanceDB pipeline with
Qwen3-Embedding-{0.6B, 4B, 8B} and measure retrieval quality on a
fixed query set.

**Steps**:

1. Add Qwen3-Embedding-8B (the strongest in the family) to LanceDB's embedding registry. LanceDB supports custom embedding providers; this is a config change, not a code rewrite.
2. Re-embed one novel's `passages_contextual.json` with the Qwen embedding (small per-novel data — a few minutes, ~$0.50 at 8B rates).
3. Run a fixed set of retrieval queries against both indexes (text-embedding-3-small vs Qwen3-Embedding-8B). Use the test queries that already exist for the embedding-variant pipeline (or define ~10 if none).
4. Compare retrieval@5 and @10 against ground-truth "good" passages identified per query. (Ground truth comes from passages that the transport-variant solver selected for the same demand profile, as a rough proxy.)
5. If results are close, also try 4B and 0.6B variants for cost-efficiency.

**QZhou-Embedding handling**: Stage 0 should resolve whether it's hostable on any managed provider. If not, defer (we don't want to spin up a self-hosted GPU just for this; see `docs/self_hosted_provider_assessment.md`). If yes, slot it in as a fourth candidate alongside the three Qwen3-Embedding sizes.

**What we expect to learn**:
- Whether the Qwen embedding family is good enough to replace OpenAI's embedding model (the *only* live OpenAI usage in the system).
- Cost picture — Qwen embedding pricing on DeepInfra vs OpenAI's $0.020/M for text-embedding-3-small.
- Whether the smallest (0.6B) is acceptable or if we need 4B/8B for quality.

**Output**: a recommended Qwen-family embedding model, plus a clean swap into LanceDB's embedding registry as an alternative to text-embedding-3-small. Like Stages 2-3, the OpenAI default stays available.

### Stage 5 — Documentation rollup (~0.5 days)

Roll Stage 1-4 findings into:

- `docs/structured_output_review.html` — expanded matrix
- `docs/open_weights_pipeline_plan.md` — concrete `ModelSpec` choices per stage
- `enrichment/llm/cost_table.py` — pricing for all newly-tested models
- A new "candidate registry" section in the open-weights plan listing the recommended open-weight alternative per task with provider, cost, and evidence file pointer.

## Total estimated effort

| Stage | Effort | API spend |
|---|---|---|
| 0 — Provider verification | 1-2 hours | $0 |
| 1 — Structured-output probes (3 new candidates) | 1 hour | ~$0.05 |
| 2 — Per-paragraph enrichment fit | 1 day | ~$0.20 |
| 3 — Prose/script comparator (5 candidates × 1 novel) | 3 days | ~$5 |
| 4 — Embedding comparator | 1 day | ~$1 |
| 5 — Documentation rollup | 0.5 days | $0 |
| **Total** | **~6 days** | **~$7** |

## Sequencing notes

- **Stages 1 and 4 can run in parallel** — different tasks, different infrastructure.
- **Stage 2 depends on Stage 1** (only test enrichment on candidates that passed schema-validity).
- **Stage 3 is independent** of the others — uses the existing cerebras driver pattern, doesn't share infrastructure with the enrichment probes.
- **Stage 0 can run in parallel with all others** — provider verification is mostly documentation.
- **Defer Stage 4 if priorities require** — the embedding swap only matters for the `--pipeline embedding` variant, not the default transport pipeline.

## Open recommendations to discuss before executing

1. **Do we run Stage 1 immediately or wait for Stage 0 to finish?** Stage 1 only needs DeepInfra (which we have); Stage 0's value is mostly documenting non-DeepInfra options.
2. **Stage 3 ordering and stopping rule.** The plan tests DeepSeek-V4-Pro first to evaluate the "DeepSeek for prose" hypothesis directly against the Qwen baseline. If V4-Pro is clearly better than Qwen3-235B, we may not need to run Kimi or Qwen3.6 — stop early. If V4-Pro is *not* clearly better, run the full slate to find the actual ceiling.
3. **DeepSeek 1st-party promo (75% off through 2026-05-31)** changes the cost picture for V4-Pro. Worth running the Stage 3 head-to-head before May 31 to capture the discount? Or use post-promo pricing for the long-term decision? Recommendation: run during promo for empirical convenience, but make the routing decision based on post-promo rates.
4. **Stage 3 driver generalisation**: extending `enrichment/phase3_runner.py` to non-Cerebras providers is **required** for Stage 3 because DeepSeek-V4-Pro is not on Cerebras. ~2 hours of work, must precede 3.1.
5. **Qwen3-30B-A3B's earlier thinking leak**: should we re-probe it before adding to Stage 1, or include it speculatively and let Stage 1 confirm?

## Sources

- DeepSeek V4 Pro pricing + providers: [deepinfra.com/blog/deepseek-v4-pro-pricing-guide-2026-providers-cost-analysis](https://deepinfra.com/blog/deepseek-v4-pro-pricing-guide-2026-providers-cost-analysis), [api-docs.deepseek.com/quick_start/pricing](https://api-docs.deepseek.com/quick_start/pricing/) (75% promo through 2026-05-31), [openrouter.ai/deepseek/deepseek-v4-pro](https://openrouter.ai/deepseek/deepseek-v4-pro)
- Kimi K2.6 providers + pricing: [artificialanalysis.ai/models/kimi-k2-6/providers](https://artificialanalysis.ai/models/kimi-k2-6/providers)
- Kimi K2.5 providers: [artificialanalysis.ai/models/kimi-k2-5/providers](https://artificialanalysis.ai/models/kimi-k2-5/providers)
- Qwen3-14B on DeepInfra: [deepinfra.com/Qwen/Qwen3-14B](https://deepinfra.com/Qwen/Qwen3-14B/api)
- Qwen3-Embedding family on DeepInfra: [deepinfra.com/qwen](https://deepinfra.com/qwen)
- QZhou-Embedding model card: [huggingface.co/Kingsoft-LLM/QZhou-Embedding](https://huggingface.co/Kingsoft-LLM/QZhou-Embedding)
- QZhou-Embedding technical report: [arxiv.org/html/2508.21632v1](https://arxiv.org/html/2508.21632v1)
- DeepInfra catalogue including all Qwen3 variants: confirmed via `client.models.list()` earlier in session
