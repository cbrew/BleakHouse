# OpenAI pipeline execution plan (focused)

**Status:** focused execution plan, 2026-05-14. Scope locked per
direction: gpt-5-mini (cheap tier) + gpt-5.4 (prose tier), one test
novel, no alternatives explored.

For broader context (why this pair, alternatives considered, etc.)
see `docs/openai_pipeline_plan.md`. This document is the execution
plan we actually run.

## Scope

- **Cheap tier**: `gpt-5-mini` ($0.25 in / $2.00 out per 1M tokens) for enrichment + structured tasks.
- **Prose tier**: `gpt-5.4` ($2.50 in / $0.25 cached / $15.00 out per 1M tokens) for Phase 3 + Phase 2.5c host brief.
- **Test novel**: **Bleak House** (`bleak_house`). Chosen because (a) it's the canonical project novel, (b) it has an existing `bh_trn_literary_hostprep` Anthropic-baseline Phase 3 run for clean A/B comparison, (c) it has 6,916 passages so cost behaviour at realistic scale is observable (not toy data).
- **Out of scope**: gpt-5-nano, gpt-5, gpt-5.5, gpt-4o, gpt-4o-mini for new work. Anthropic Sonnet remains the production default throughout.

## Bootstrap (~$0.05, 1 hour)

1. **Cost-table entries** in `enrichment/llm/cost_table.py`:

   ```python
   ("openai_compatible", "gpt-5-mini"): ModelPricing(
       input_per_m=0.25, output_per_m=2.00,
   ),
   ("openai_compatible", "gpt-5.4"): ModelPricing(
       input_per_m=2.50, output_per_m=15.00,
       cache_read_per_m=0.25,
   ),
   ```

   gpt-5-mini's cache_read rate not documented separately — defer until we have a measured number.

2. **Register generators** in `params.yaml`:

   ```yaml
   generators:
     # ... existing entries unchanged ...
     - id: openai_5_mini
       api_model: gpt-5-mini
       provider: openai
       display: OpenAI GPT-5-mini
     - id: openai_5_4
       api_model: gpt-5.4
       provider: openai
       display: OpenAI GPT-5.4
   ```

3. **Schema probe for gpt-5-mini** — small subset (~5 tests) of the structured-output review matrix. We have gpt-4o-mini's full results as a prior; only run the full 16-test matrix if gpt-5-mini behaves measurably differently. Quick tests to fire:
   - `01_enum` (sanity)
   - `04_maxItems` (constraint enforcement)
   - `06_uniqueItems` (OpenAI strict-mode rejection check)
   - `12_list_loop` (pathology — does strict mode prevent it?)
   - `14_strict_modes` (does strict=true matter for this model?)

   Add `gpt5_mini` candidate to `scripts/structured_output_review.py`, run those 5 cells (~$0.05 total).

**Expected outcome**: confirmation gpt-5-mini behaves at least as well as gpt-4o-mini on schema features. If it doesn't, document the gap before proceeding.

## Stage 1: Per-chapter enrichment probe on gpt-5-mini (~$0.50, 1 hour)

**Question to answer**: can gpt-5-mini handle the existing per-chapter call shape (16k+ token structured-JSON output per chapter)?

This matters because if **yes**, we can use the existing `submit_passages_enriched.py` machinery for OpenAI without restructuring. If **no**, we have to build the per-paragraph + cached-chapter-prefix code path first (Stage C in `docs/open_weights_pipeline_plan.md`) before any enrichment-tier OpenAI work proceeds.

**Steps**:

1. Pick one Bleak House chapter (recommend `c6` — moderately-sized, has the full literary range).
2. Send it through the existing per-chapter prompt + schema, but to gpt-5-mini instead of Haiku, via a one-shot script using the seam.
3. Measure: schema validity, output_tokens, elapsed, cost.

**Expected outcome**: gpt-5-mini is a newer-generation model than gpt-4o-mini and has higher default `max_completion_tokens` ceilings; it may handle the per-chapter shape where gpt-4o-mini's behaviour was uncertain. Either answer is informative for the path through Stage 2.

## Stage 2: Bleak House enrichment via gpt-5-mini (~$8-15, ~3 hours wall time)

**Two paths depending on Stage 1**:

### Path A — gpt-5-mini passes per-chapter shape (~$8)

Use the existing batch infrastructure. One call per Bleak House chapter (~108 chapters total per the project layout).

- Submit via OpenAI API (or OpenAI Batch API for the 50% discount).
- Cost estimate: ~108 chapters × ~3.2k input × $0.25/M + ~108 × ~19k output × $2/M = ~$0.09 input + ~$4.10 output = **~$4** (synchronous) or **~$2** (batch).
- Add input-token + cache savings; realistic total: $3-5 enrichment cost on gpt-5-mini for all of Bleak House.

### Path B — gpt-5-mini cannot do per-chapter; build per-paragraph code path first (~1 week + $5-12)

This is the Stage C work from `docs/open_weights_pipeline_plan.md`. Build the per-paragraph + cached-chapter-prefix code path in `submit_passages_enriched.py`, then run Bleak House through it on gpt-5-mini.

- Cost estimate: 6,916 paragraphs × ~5k cached input + ~100 unique input + ~250 output ≈ $0.25 input (after cache) + $3.46 output = **~$5** without batch discount.
- This is the same enrichment-shape change required for any non-Haiku enrichment work; doing it once unblocks the open-weights plan too.

**Output**: Bleak House with `passages_enriched.json` derived by gpt-5-mini. Preserved in `data/novels/bleak_house/passages_enriched.openai_5_mini.json` (or similar suffix) so the Anthropic-derived version stays available as the production default. Spot-check via the eyeball-compare machinery on 3 sample paragraphs.

## Stage 3: Bleak House Phase 3 via gpt-5.4 (~$10, ~3 hours total)

Use the existing `bh_trn_literary_hostprep` Phase 0/1/2/2.5 outputs (Anthropic-derived). Replace only Phase 3 with gpt-5.4. This isolates the prose-tier swap from the enrichment-tier swap.

### Generalise the Phase 3 driver (~2 hours of code work, $0)

`enrichment/phase3_runner.py` hard-codes the Cerebras SDK.
Extend it (or write a sibling) that takes `(provider, base_url, api_key, model)` from the `Generator` entry in axes and routes via the seam. The same generalisation is required by the Qwen-family Stage 3, so this work is shared.

### Run gpt-5.4 on Bleak House Phase 3 (~$10)

- Episode ≈ 5 segments × ~15-25k output tokens × $15/M ≈ $1.50-2.00 per segment × 5 = **~$8-10 per episode**.
- Generates `data/runs/bh_trn_literary_hostprep_openai_5_4/phase3_episode.json` (and the post-phase3 artifacts).
- Compare against the existing Sonnet baseline at `data/runs/bh_trn_literary_hostprep/`.

### Listen and judge

- Use the existing webapp player to A/B the Sonnet and gpt-5.4 episodes.
- Document: prose quality, dialogue naturalness, persona distinctiveness, host-question coverage, quote handling.
- Note any specific failure modes (e.g. invented characters, missing prosody annotations, etc.).

## Stage 4: End-to-end OpenAI Bleak House run (optional, ~$15)

If Stages 2 and 3 both pass, run the full pipeline end-to-end on Bleak House using OpenAI throughout:

- Enrichment from Stage 2 (gpt-5-mini-derived).
- Phase 0 segment design via gpt-5-mini (one call, trivial cost).
- Phase 1/2 transport / embedding (no LLM in transport variant; if embedding variant, OpenAI embeddings already used by default).
- Phase 2.5 host prep — pre-interview via gpt-5-mini, brief planning via gpt-5.4.
- Phase 3 script generation via gpt-5.4.

Generates `data/runs/bh_trn_literary_hostprep_openai_5_4_e2e/` (or similar — naming convention TBD). Compare to the Sonnet baseline.

**Skip this stage if Stages 2 or 3 reveal issues** that need fixing first. End-to-end is the final test, not an early test.

## Stage 5: Decision + documentation (~0.5 days)

After Stages 1-4, the empirical question is: **does the OpenAI pair (gpt-5-mini + gpt-5.4) produce a usable Bleak House episode at a competitive cost?**

If yes:

- Register `openai_5_mini` and `openai_5_4` as production-selectable alternatives in the canonical generator registry.
- Document the routing pattern: `--generator openai_5_4` for Phase 3, `--enrichment-generator openai_5_mini` (or whichever CLI hook lands).
- Update `docs/open_weights_pipeline_plan.md` to note the OpenAI parallel pipeline is now wired alongside the open-weight options.

If no (which failure mode?):

- Phase 3 quality issue with gpt-5.4 → consider gpt-5.5 (premium tier) as fallback before declaring failure.
- Enrichment quality issue with gpt-5-mini → consider gpt-5.4-mini ($0.75/$4.50, current generation, more capable) before declaring failure.
- Both fail → document the gap and the OpenAI pair stays unregistered for now.

## Cost summary

| Stage | Cost | Notes |
|---|---|---|
| Bootstrap | ~$0.05 | 5 schema probes on gpt-5-mini |
| Stage 1 — per-chapter probe | ~$0.50 | One Bleak House chapter |
| Stage 2 — full Bleak House enrichment | ~$3-12 | Path A vs Path B |
| Stage 3 — Bleak House Phase 3 on gpt-5.4 | ~$10 | One episode |
| Stage 4 — end-to-end OpenAI Bleak House (optional) | ~$15 | One full pipeline |
| **Total** | **~$30-40** | Plus ~1 week elapsed if Path B is needed |

## Decision points

1. **After Bootstrap**: gpt-5-mini schema features OK to proceed?
2. **After Stage 1**: per-chapter shape works (Path A) or not (Path B)?
3. **After Stage 2**: enrichment quality acceptable on eyeball compare?
4. **After Stage 3**: Phase 3 audio acceptable on listen-test?
5. **After Stage 4**: end-to-end pipeline produces a usable episode?

Stop at the first "no" — don't burn the remaining cost on a known-broken path.

## What this plan does *not* do

- No exploration of gpt-5-nano, gpt-5, gpt-5.5, or gpt-4o-mini for production work.
- No batch-API setup for OpenAI (could come later for cost-tier optimisation; not needed for one-novel measurement).
- No migration of production default away from Anthropic Sonnet. The OpenAI pair joins as a selectable alternative if it passes; production keeps running on Anthropic regardless.
- No multi-novel validation. Bleak House is the single test. If results are convincing, a second-novel confirmation run can be added as a follow-on.

## Chat Completions vs Responses API: verified per-provider state (2026-05-14)

We currently call `client.chat.completions.create(...)` throughout
the seam (`enrichment/llm/providers/openai_compatible_provider.py`).
Stage 1's "16k tokens consumed entirely by reasoning, 0 chars of
content" failure mode is the documented Chat-Completions trap on
gpt-5 family: `max_completion_tokens` is one combined budget for
reasoning + visible output.

OpenAI explicitly recommends the **Responses API** (`/v1/responses`)
for gpt-5 family work: separate `max_output_tokens` cap for visible
output, reasoning tokens budgeted independently, 40-80% better
prompt-cache utilisation per OpenAI's internal eval, and a 3% quality
uplift on SWE-bench. Different request shape (`input=` instead of
`messages=`, `text.format` instead of `response_format`) and different
response shape (iterate `response.output` items rather than reading
`choice.message.content`).

The question for the seam is: **do the third-party openai-compat
providers expose `/v1/responses` too, or only Chat Completions?** I
verified each provider's documentation directly rather than
extrapolating:

| Provider | Has `/v1/responses`? | Chat Completions reasoning surface | Source |
|---|---|---|---|
| **OpenAI native** | yes (recommended for gpt-5 family) | also supported, with the budget-conflation caveat above | [Migrate to the Responses API](https://platform.openai.com/docs/guides/migrate-to-responses) |
| **DeepInfra** | **no** — only `/v1/openai/chat/completions` documented; `/v1/responses` does not appear in their llms.txt index | `reasoning_effort` either as top-level parameter or in `extra_body`; reasoning surfaced via `message.reasoning_content` | [docs.deepinfra.com/chat/reasoning.md](https://docs.deepinfra.com/chat/reasoning.md), [docs.deepinfra.com/llms.txt](https://docs.deepinfra.com/llms.txt) |
| **Together** | **no** — only `/v1/chat/completions` documented; reasoning models guide describes only chat-completions calls | model-family-dependent: `reasoning={"enabled": True}` top-level for hybrid models, `chat_template_kwargs={"thinking": True}` for Qwen-shape models, `reasoning_effort` for gpt-oss only; reasoning surfaced via a dedicated `message.reasoning` field separate from content (most models) or `<think>` tags inline (DeepSeek-R1) | [docs.together.ai/docs/reasoning-models-guide](https://docs.together.ai/docs/reasoning-models-guide) |
| **Cerebras** | **no** — only `/v1/chat/completions` documented in the introduction | `reasoning_effort` supported for gpt-oss; documented as "mostly OpenAI-compatible" | [inference-docs.cerebras.ai/introduction](https://inference-docs.cerebras.ai/introduction) |

**Implication for the seam**: the dispatch logic is genuinely
asymmetric — OpenAI native is the only hosting where the Responses
API is even an option. The clean design is:

- `spec.hosting == "openai"` → `client.responses.create(...)` with `input=`, `text.format` for json_schema, `reasoning={"effort":...}`, `max_output_tokens`. Extract via `response.output` iteration.
- All other hostings → keep current Chat Completions path. Each provider has its own reasoning-surface convention (DeepInfra's `reasoning_content`, Together's `reasoning` field, Cerebras's per-model story); the seam's `_extract_text` already handles `content` and can be extended per-hosting to also pull `reasoning_content` / `reasoning` when present.

This is more code than the current "one client method for all
openai-compat" pattern, but it's the documented best practice and it
directly addresses Stage 1's reasoning-budget conflation. Plumbing
once unblocks Stage 1 (re-probe gpt-5-mini cleanly), Stage 3 (gpt-5.4
prose), and any future OpenAI-native work.

**What this plan does *not* do**: it does not upgrade non-OpenAI
hostings to Responses, because they don't expose it. Reasoning-model
support on those hostings stays on Chat Completions with the
per-provider conventions documented above (and already partially
plumbed via `reasoning_effort` in the seam from earlier in the session).

## Sequencing with other work-in-flight

- **Stage A seam migration** (from `docs/open_weights_pipeline_plan.md`) is the foundation for the cleanest gpt-5-mini routing. Without it, this plan can still execute via direct OpenAI SDK calls, but registering as a long-term alternative is messier.
- **Phase 3 driver generalisation** (Stage 3 of `docs/qwen_family_test_plan.md`) is shared with this plan's Stage 3. Do once, reuse.
- This plan is **independent of the Qwen family tests** — runs on different infrastructure (OpenAI vs DeepInfra), different candidates, different test fixtures. Can run in parallel with Qwen Stage 1-2 without contention.

## Sources

- OpenAI pricing 2026-05-14: [devtk.ai/en/blog/openai-api-pricing-guide-2026](https://devtk.ai/en/blog/openai-api-pricing-guide-2026/)
- Bleak House passage count: validation output earlier in this session (6,916 passages).
- Existing Phase 3 baseline fixture: `data/runs/bh_trn_literary_hostprep/`.
- Broader OpenAI candidate context: `docs/openai_pipeline_plan.md`.
