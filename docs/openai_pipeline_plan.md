# OpenAI parallel pipeline plan

**Status:** plan, 2026-05-14. Sibling to
`docs/open_weights_pipeline_plan.md` and
`docs/qwen_family_test_plan.md`. Where those documents cover
open-weight alternatives, this one covers a fully closed-source
OpenAI alternative that mirrors the existing Anthropic structure
(cheap model for non-prose tasks, expensive model for prose).

## Framing

This is a **second closed-source pipeline alongside Anthropic**, not
an open-weight alternative. The motivation is the same one that drives
the open-weight work — hedge against single-vendor risk on the
production-default Anthropic stack — but the mechanism is different:
OpenAI is reliably good, OpenAI-locked (with Azure as a secondary
source of the same models), and known to behave well on structured
output.

Three pipelines coexisting after the plans land:

| Pipeline | Status | Lock-in | Default? |
|---|---|---|---|
| Anthropic (Haiku + Sonnet) | production today | single-vendor | yes |
| Open-weight (Qwen / DeepSeek / gpt-oss family, multi-provider) | per `docs/open_weights_pipeline_plan.md` | multi-provider | no — selectable alternative |
| **OpenAI (gpt-5-mini + gpt-5.4)** | **this plan** | single-vendor (OpenAI + Azure mirror) | no — selectable alternative |

The user's framing: cheaper OpenAI model for non-prose (enrichment,
contexts, segment design, winnow, quote verify); more expensive OpenAI
model for prose (Phase 2.5c host brief, Phase 3 script generation).
This mirrors the Haiku-vs-Sonnet split on Anthropic.

## OpenAI lineup as of 2026-05-14

From [devtk.ai's pricing tracker](https://devtk.ai/en/blog/openai-api-pricing-guide-2026/) and OpenAI's pricing page:

### Cheap tier (Haiku-equivalent candidates)

| Model | Input $/M | Cached $/M | Output $/M | OpenAI's stated "best for" |
|---|---|---|---|---|
| gpt-5-nano | $0.05 | — | $0.40 | very high-volume routing and extraction |
| gpt-4o-mini | $0.15 | — | $0.60 | legacy multimodal integrations |
| gpt-5.4-nano | $0.20 | $0.02 | $1.25 | high-volume simple work |
| gpt-5-mini | $0.25 | — | $2.00 | cost-sensitive GPT-5-family workloads |
| gpt-5.4-mini | $0.75 | $0.075 | $4.50 | lower-latency, lower-cost production |

**Comparison to Haiku 4.5** ($1.00 in / $0.10 cache-write / $5.00 out):

- **gpt-5-mini at $0.25/$2.00 is 4× cheaper than Haiku on input, 2.5× cheaper on output**, and is current-generation (GPT-5 family). Recommended cheap-tier pick.
- gpt-5-nano at $0.05/$0.40 is **20× cheaper on input, 12.5× cheaper on output** but is positioned by OpenAI as "high-volume routing and extraction" — its prose capability for our enrichment summaries is unknown.
- gpt-5.4-mini at $0.75/$4.50 is nearly Haiku-equivalent on pricing; the "current generation, higher quality" pick if cost-parity with Haiku is acceptable.
- gpt-4o-mini we've already probed in the structured-output review — schema feature support is solid. Older generation.

### Prose tier (Sonnet-equivalent candidates)

| Model | Input $/M | Cached $/M | Output $/M | OpenAI's stated "best for" |
|---|---|---|---|---|
| gpt-5 | $1.25 | — | $10.00 | older GPT-5 baseline already deployed |
| gpt-5.4 | $2.50 | $0.25 | $15.00 | frontier quality at lower cost |
| gpt-5.5 | $5.00 | $0.50 | $30.00 | hard coding, agents, long-context professional work |
| gpt-4o | $2.50 | — | $10.00 | legacy multimodal |

**Comparison to Sonnet 4.6** ($3.00 in / $0.30 cache-write / $15.00 out):

- **gpt-5.4 at $2.50/$15 is roughly Sonnet-equivalent pricing** and OpenAI positions it as "frontier quality at lower cost". Recommended prose-tier pick if matching Sonnet on cost is acceptable.
- gpt-5 at $1.25/$10 is **2× cheaper than Sonnet on input, 1.5× cheaper on output** — the budget prose pick within OpenAI. Generation gap (older GPT-5 vs current GPT-5.4) is worth measuring.
- gpt-5.5 at $5/$30 is the premium "agents and long-context professional" tier — probably overkill for podcast script generation and meaningfully more expensive than Sonnet.

## Recommended OpenAI pipeline pairing

Primary:

- **Cheap tier: gpt-5-mini** ($0.25/$2.00) — 4× cheaper than Haiku, current generation, OpenAI-positioned for cost-sensitive structured workloads.
- **Prose tier: gpt-5.4** ($2.50/$15) — Sonnet-equivalent pricing, OpenAI's current top quality model below the premium 5.5 tier.

Backup picks worth quick-testing:

- **gpt-5-nano** for the cheap tier if quality holds — 5× cheaper than even gpt-5-mini, would make the OpenAI pipeline materially cheaper than Anthropic on the enrichment phases.
- **gpt-5** for the prose tier — cheaper than Sonnet by ~30-50%, but a generation behind gpt-5.4. Worth testing if cost matters more than the quality delta.

Skip:

- **gpt-5.5** for prose unless gpt-5.4 has unexpected issues. Pricier than Sonnet without obvious benefit for our task.
- **gpt-4o-mini** for new work — same family as gpt-4o but older than gpt-5-mini. We have probe data; no need to deploy.
- **gpt-4o** for prose — superseded by gpt-5.4 at the same price.

## Cost picture per BleakHouse cycle

Worked out per pipeline using the per-call volumes from
`docs/together_batch_assessment.md` (the verified Haiku cost basis).
Numbers are rough — based on per-token cost ratios applied to existing
phase volumes. Not measured.

### Cheap-tier-equivalent work (passage_enrichment ~ representative)

| Stack | Tier model | Per-cycle output cost | Per-cycle input cost (no caching) | Total |
|---|---|---|---|---|
| Anthropic batch | Haiku 4.5 ($1/$5, 50% batch) | ~$44 | ~$1.50 | **~$45** |
| **OpenAI parallel (sync; no batch yet)** | **gpt-5-mini ($0.25/$2)** | ~$35 | ~$0.75 | **~$36** |
| OpenAI parallel | gpt-5-nano ($0.05/$0.40) | ~$7 | ~$0.15 | **~$7** (if quality holds) |
| OpenAI parallel | gpt-5.4-mini ($0.75/$4.50) | ~$32 | ~$2.25 | **~$34** |

OpenAI doesn't currently have an Anthropic-style 50% batch discount on
all models, but OpenAI does have a Batch API with up to 50% off for
overnight jobs on most models — would bring cheap-tier OpenAI parity
or below Anthropic batch.

### Prose-tier work (Phase 3 script generation, ~3-7 segments per run)

Rough per-run cost (one episode):

| Stack | Tier model | Per-run cost (est) |
|---|---|---|
| Anthropic | Sonnet 4.6 ($3/$15) | ~$8-15 |
| **OpenAI parallel** | **gpt-5.4 ($2.50/$15)** | **~$7-13** |
| OpenAI parallel | gpt-5 ($1.25/$10) | ~$4-8 |
| OpenAI parallel | gpt-5.5 ($5/$30) | ~$16-30 |

### Bottom-line cost comparison

For a single onboarding cycle + one episode generation:

| Stack | Cheap-tier (~$X) | Prose-tier (~$Y) | Total per "novel + 1 episode" |
|---|---|---|---|
| Anthropic | $45 | $10 | **~$55** |
| OpenAI (recommended: gpt-5-mini + gpt-5.4) | $36 | $10 | **~$46** |
| OpenAI (aggressive: gpt-5-nano + gpt-5) | $7 | $6 | **~$13** (quality unverified) |

The recommended OpenAI pipeline is ~15-20% cheaper than Anthropic at
similar quality positioning. The aggressive variant is ~75% cheaper if
gpt-5-nano holds up on enrichment — which is exactly the question to
test before adopting it.

## What's already in place

- **Seam infrastructure for OpenAI**: `enrichment/llm/providers/openai_compatible_provider.py` handles OpenAI native (base_url=None, OPENAI_API_KEY).
- **Capability table entry**: `enrichment/llm/capabilities.py:"openai"` declares strict mode + native_batch support.
- **gpt-4o-mini already probed**: in `docs/structured_output_review.html`, the cell matrix has 16 schema-feature results. Newer GPT-5 family models inherit the same response_format machinery; behaviour should be similar (worth confirming with a probe).
- **Generator-axis support**: `params.yaml:generators` already supports multiple Phase 3 dispatch options. Adding `openai_5_mini` and `openai_5_4` is a config addition, no code change.

## What's needed

1. **Add OpenAI generators to `params.yaml`** with `provider: openai`. Two entries minimum:
   - `openai_5_mini` (api_model: `gpt-5-mini`) — cheap-tier for enrichment phases and any task wired through the seam.
   - `openai_5_4` (api_model: `gpt-5.4`) — prose-tier for Phase 3 + Phase 2.5c.
2. **Cost-table entries** in `enrichment/llm/cost_table.py` for the gpt-5 family at OpenAI hosting.
3. **Stage A seam migration** (from `docs/open_weights_pipeline_plan.md`) — same code refactor enables OpenAI dispatch, no separate work. Once a call site is seam-routed, swapping to OpenAI is a `ModelSpec` registration.
4. **Phase 3 driver generalisation** — the same ~2 hours of work needed to dispatch Phase 3 to non-Cerebras providers (per `docs/qwen_family_test_plan.md` Stage 3) makes OpenAI Phase 3 work.

## Test plan (OpenAI-specific stages)

These compose with the existing test plans rather than duplicating
work.

### Stage OA-1 — gpt-5-mini schema-feature probe (~$0.05, 1 hour)

Add `gpt5_mini` candidate to `scripts/structured_output_review.py`,
re-run. Compare to `gpt4o_mini` results in the existing matrix. Confirm
the cheap-tier OpenAI pick behaves at least as well as gpt-4o-mini on
schema features.

Worth adding `gpt5_nano` in the same pass — same setup cost, gives us
the aggressive-tier data.

### Stage OA-2 — per-paragraph enrichment fit on gpt-5-mini (~$0.05, 1 hour)

Run `scripts/eyeball_compare.py` and one-chapter
`scripts/run_eval_passage_enrichment.py` with gpt-5-mini on the
canonical `north_and_south/c6` fixture. Compare to the existing
gpt-4o-mini results (which we have for this fixture from earlier in
the session).

If gpt-5-mini wins on quality at lower cost, it's the cheap-tier
recommendation. If gpt-5-nano also passes, even better.

### Stage OA-3 — gpt-5.4 Phase 3 quality compare (~$10, 1 day)

After the Stage 3 driver generalisation lands (per
`docs/qwen_family_test_plan.md`), run gpt-5.4 against the same
canonical Phase 3 fixture (`bh_trn_literary_hostprep` baseline).
Compare audio output to the Sonnet baseline and to DeepSeek-V4-Pro
(if that's been tested by then). Listen, judge.

Optionally also run gpt-5 for the cost-tier comparison.

### Stage OA-4 — wire as production-selectable alternatives (~0.5 days)

Once Stages OA-1, OA-2, OA-3 give us confident generator IDs:

- Register `openai_5_mini` and `openai_5_4` in `params.yaml`.
- Add cost-table entries.
- Document the routing pattern in `docs/open_weights_pipeline_plan.md` (which becomes the canonical pipeline-options doc).

## Sequencing relative to other plans

The OpenAI plan and the open-weight test plan share infrastructure:

- **Stage A of the open-weights plan** (seam migration) benefits both. Do it once.
- **Stage 3 driver generalisation** in the Qwen-family plan unblocks Stage OA-3 here. Do it once.
- **Stage 1 of the Qwen plan** (structured-output probes) and **Stage OA-1 here** can run in the same probe matrix execution — both add candidates to the same `scripts/structured_output_review.py`.

This means **adding the OpenAI pipeline to the work in flight is ~1
extra day** beyond what the open-weight test plan already costs,
because the most expensive shared pieces (seam migration, driver
generalisation, probe infrastructure) are already in the work.

## What this plan does *not* commit to

- Migrating production default from Anthropic to OpenAI. The Anthropic stack stays as the default; OpenAI joins as a selectable alternative, same as the open-weight options.
- Wiring the OpenAI Batch API. OpenAI does have one (50% off for overnight jobs), and once `submit_passages_enriched.py` and `submit_passage_contexts.py` are seam-routed via the open-weights Stage A work, plumbing OpenAI Batch becomes a per-provider concern. Defer this.
- Picking between the recommended and aggressive variants until measured. gpt-5-nano's quality on enrichment is the open empirical question; until Stage OA-2 measures it we don't know whether the ~$13/cycle aggressive number is real or aspirational.

## Open questions to confirm before executing

1. **Do we want gpt-5 in the prose-tier test set, or commit to gpt-5.4?** gpt-5 is meaningfully cheaper and the "old reliable" option; gpt-5.4 is current generation. Adding gpt-5 to Stage OA-3 is a marginal cost (~$5).
2. **Do we care about gpt-5.5 enough to test it?** Probably not — it's positioned for coding/agents, our task is literary dialogue, and it's the most expensive OpenAI model.
3. **Stage OA-1 probe scope**: 16-test matrix per candidate is overkill given gpt-4o-mini's results — should we run a 5-test fast subset for gpt-5-mini and gpt-5-nano, full matrix only if the subset shows differences from gpt-4o-mini?

## Sources

- OpenAI API pricing tracker (May 2026): [devtk.ai/en/blog/openai-api-pricing-guide-2026](https://devtk.ai/en/blog/openai-api-pricing-guide-2026/)
- OpenAI official pricing: [openai.com/api/pricing](https://openai.com/api/pricing/)
- Per-call cost basis for Anthropic comparison: `docs/together_batch_assessment.md` (verified Haiku per-cycle figure)
- Generator axis pattern: `enrichment/axes.py`, `params.yaml`
- Schema-feature evidence (gpt-4o-mini): `docs/structured_output_review.html`
