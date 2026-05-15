# Provider Control Spec

Status: draft, 2026-05-15.
Owner: see BleakHouse-otae.
Supersedes the per-call-site framing in the original BleakHouse-otae description.

## Goal

The user has full, transparent control over which LLM provider/model serves
each LLM call in the pipeline. Choices are visible (config + CLI), recorded
with the run (run config.json is self-describing), and uniform (no caller
bypasses the chosen mechanism).

Two reference profiles must work end-to-end on the same fixture and produce
distinguishable, audio-renderable runs:

- **all-anthropic** — Haiku 4.5 + Sonnet 4.6 (current production default).
- **all-openai** — gpt-5-mini for cheap tasks, gpt-5.4 for prose-tier.

Plus hybrid combinations the user can express ergonomically.

## Inventory: every LLM call in the active pipeline

Audited 2026-05-15 via grep + read. Excludes experiment_h\* modules, eval
harness, retired scripts. TTS is Gemini and is out of scope for this spec
(separate provider category, no analogue swap).

| # | Stage | Module : function | Today's model | SDK call | Tool use? | Structured output? | Batch? |
|---|---|---|---|---|---|---|---|
| 1 | Enrichment (per-chapter) | `submit_passages_enriched.py` | claude-haiku-4-5 | `messages.batches.create` | No | Yes (`ChapterEnrichmentResult`) | **Yes** (Anthropic Batch) |
| 1 | Enrichment (per-chapter) | `submit_passages_enriched_openai.py` | gpt-5-mini | `client.batches.create` endpoint=/v1/responses | No | Yes | **Yes** (OpenAI Batch) |
| 2 | Passage contexts | `submit_passage_contexts.py` | claude-haiku-4-5 | `messages.batches.create` | No | Yes | **Yes** |
| 3 | Phase 2 segment design | `design_segments.py` | claude-haiku-4-5 | `messages.parse` | No | Yes (`SegmentDesigns`) | No |
| 4 | Phase 2 transport plan | `transport_podcast.py` | (none — OR-tools) | — | — | — | — |
| 4 | Phase 2 embedding plan | `embedding_podcast.py` | claude-sonnet-4-6 | `messages.parse` | No | Yes | No |
| 5 | Phase 2.5 pre-interview (no refs) | `host_prep.py:pre_interview` | claude-haiku-4-5 | `messages.parse` | No | Yes (`PreInterviewResponse`) | No |
| 6 | Phase 2.5 pre-interview (with refs) | `host_prep.py:pre_interview_with_refs` | claude-haiku-4-5 | `messages.create` (tool loop) then `messages.parse` (extract) | **Yes** (3 tools — OpenAlex, Wikipedia search, Wikipedia read) | Yes (two-phase) | No |
| 7 | Phase 2.5 brief planner | `host_prep.py:plan_questions` | claude-sonnet-4-6 | `messages.parse` | No | Yes (`HostBrief`) | No |
| 8 | Phase 2.5 winnower (listener-pick) | `host_prep.py:_select_listener_recommendations` | claude-haiku-4-5 | `messages.create` | No | No (free-text JSON parsed via regex) | No |
| 9 | Phase 3 prose (per segment) | `generate_podcast.py` | claude-sonnet-4-6 | `messages.parse` | No | Yes (`EpisodeSegment`) | No |
| 9 | Phase 3 prose (alt driver) | `phase3_runner.py` | cerebras\_\* OR gpt-5.4 | provider-specific | No | Yes | No |

Counts: **12 distinct LLM call sites** across the pipeline. Phase 0
(segmentation), Phase 1 (passage→arc assignment), cluster steps, post-Phase-3
manifest/report build, and reference verification are deterministic — no LLM
calls.

## User-control surface

Profile + override model, written to `params.yaml` and selected by a single
CLI flag, with per-task overrides for experimentation.

### params.yaml extensions

```yaml
# Existing — kept verbatim
generators:
  - id: anthropic_sonnet_4_6
    api_model: claude-sonnet-4-6
    provider: anthropic
  - id: openai_5_mini
    api_model: gpt-5-mini
    provider: openai
  # ... etc

# New: per-task default models, addressable by stable task name
task_models:
  passage_enrichment:      { model_id: anthropic_haiku_4_5,    batch: true }
  passage_contexts:        { model_id: anthropic_haiku_4_5,    batch: true }
  segment_design:          { model_id: anthropic_haiku_4_5 }
  embedding_planner:       { model_id: anthropic_sonnet_4_6 }
  host_prep_pre_interview: { model_id: anthropic_haiku_4_5 }
  host_prep_interview_with_refs: { model_id: anthropic_haiku_4_5 }
  host_prep_brief_planner: { model_id: anthropic_sonnet_4_6 }
  host_prep_winnower:      { model_id: anthropic_haiku_4_5 }
  phase3_prose:            { model_id: anthropic_sonnet_4_6 }

# New: named profiles. Each is a (task → model_id) map; missing tasks
# fall back to `task_models` defaults above. A profile that lists every
# task is a complete override.
provider_profiles:
  production:
    # Empty body → uses task_models defaults. This is the documented
    # production default.

  all_openai:
    passage_enrichment:      openai_5_mini
    passage_contexts:        openai_5_mini
    segment_design:          openai_5_mini
    embedding_planner:       openai_5_4
    host_prep_pre_interview: openai_5_mini
    host_prep_interview_with_refs: openai_5_mini
    host_prep_brief_planner: openai_5_4
    host_prep_winnower:      openai_5_mini
    phase3_prose:            openai_5_4

  all_anthropic:
    # Alias for production — explicit name for clarity in run dirs.

  hybrid_openai_enrichment_anthropic_rest:
    passage_enrichment: openai_5_mini
    # Everything else falls back to production defaults.

default_provider_profile: production
```

### CLI surface

A single new flag plus repeating overrides:

```
--provider-profile NAME                    # default: from params.yaml default_provider_profile
--provider-override TASK=MODEL_ID          # repeat as needed
```

Example: an apples-to-apples OpenAI run for OT alternatives short:

```
uv run python -m enrichment.run_pipeline --name ot_trn_alternatives_hostprep \
    --novel oliver_twist --pipeline transport --length short \
    --host-prep --reference-tools \
    --provider-profile all_openai \
    --replace-expert "Eleanor Hartley=sir_edmund" \
    --replace-expert "James Blackstone=dr_rosen" \
    --replace-expert "Caroline Woodcourt=trevelyan"
```

Example: experimenting with gpt-5.4 just for the brief planner:

```
--provider-profile production --provider-override host_prep_brief_planner=openai_5_4
```

The `--model`, `--interview-model`, `--planning-model`, `--curation-model`,
`--enrichment-variant` flags become **deprecated aliases**: they translate
into `--provider-override` calls for one cycle, then the next pass removes
them. The translation table is documented; no behaviour change for callers
that still use the old flags.

### Why profile + overrides (not per-task flags or YAML-only)

- **Profile**: 95% of runs are "all X" or "production default". One flag is
  ergonomic and the profile name appears in `run_dir/config.json` for
  one-glance audit.
- **Overrides**: needed for experiments ("try gpt-5.4 for just the brief
  planner without touching the rest"). Repeating CLI flags beats editing
  params.yaml between every run.
- **Not YAML-only**: forcing a YAML edit per experimental run loses
  reproducibility (you'd have to commit the experimental config or pass it
  via a one-off file). The profile-as-name + named overrides keeps the
  decisions in argv where they can be logged with the run.

## Provenance: what gets recorded

Each run's `config.json` gains a `providers` block:

```json
{
  "axes": { ... },
  "providers": {
    "profile": "all_openai",
    "resolved_per_task": {
      "passage_enrichment":      "openai_5_mini",
      "passage_contexts":        "openai_5_mini",
      "segment_design":          "openai_5_mini",
      "host_prep_pre_interview": "openai_5_mini",
      "host_prep_interview_with_refs": "openai_5_mini",
      "host_prep_brief_planner": "openai_5_4",
      "host_prep_winnower":      "openai_5_mini",
      "phase3_prose":            "openai_5_4"
    },
    "overrides_at_runtime": []
  }
}
```

The `resolved_per_task` map is the source of truth — it's the fully-applied
result of profile + overrides, evaluated once at run start. Downstream
readers (`expdb scan`, webapp, comparison scripts) read this block and
never re-resolve.

`enrichment_variant` (the existing field added 2026-05-15) becomes a
**read-only derived view** of `providers.resolved_per_task.passage_enrichment`
for backwards compatibility with the webapp. It can be removed once the
webapp reads `providers` directly.

## Implementation surface

Three layers; the seam at the bottom does the heavy lifting.

### 1. Settings layer (`enrichment/llm/settings.py`)

Add:
```python
def resolved_providers(
    profile_name: str,
    overrides: dict[str, str],
) -> dict[str, ModelSpec]:
    """Build the full task→ModelSpec map from profile + overrides.
    Validates: every task in the inventory is resolved; every model_id is
    a registered generator. Failure modes raise at config-time, not at
    first call."""
```

### 2. Seam capability parity (`enrichment/llm/`)

The seam must support every LLM call the inventory makes. Today it covers
structured output for both providers; missing pieces:

- **Tool use**: `GenerationRequest` gains `tools: list[ToolSpec] | None` and
  `tool_executors: dict[str, Callable]`. Providers run the
  tool-use loop (request → tool_use blocks → execute → tool_result → repeat
  until end_turn). Caller passes tool specs + executors; provider returns
  the final assistant message + the tool transcript for auditing.
  - `AnthropicProvider`: implement the loop using `messages.create(tools=...)`
    matching the shape currently inlined in `host_prep.py:pre_interview_with_refs`.
  - `OpenAICompatibleProvider`: for OpenAI native, Responses API's `tools` +
    `tool_calls` output items.

- **Native batch**: today the Batch API calls in `submit_passages_enriched*.py`
  bypass the seam entirely. The seam needs a batch-submit and batch-collect
  surface that returns provider-neutral handles. Out of scope for the
  initial migration if `BLEAKHOUSE-otae` is sized to "interactive calls
  only" — see the migration plan below.

### 3. Call-site migration

Every call in the inventory routes through `seam.generate(task=..., request=...)`.
Migration order matches the inventory order (smallest blast radius first):

1. Winnower (#8)
2. Pre-interview no-refs (#5)
3. Brief planner (#7)
4. Segment design (#3)
5. Embedding planner (#4 — pipeline-conditional)
6. Phase 3 prose (#9)
7. Pre-interview with refs (#6) — last because it needs tool-use support
8. Batch submits (#1, #2) — last because they need batch-handle support, or
   keep their own pathway and document the carve-out

After each migration step: re-run on the OT alternatives short fixture
with `--provider-profile all_anthropic` (must match current output
byte-for-byte modulo timestamps) and `--provider-profile all_openai` (must
produce a valid, distinct run dir).

## Migration plan as bd subtasks

Replaces the four host_prep-scoped subtasks in the original BleakHouse-otae
description.

**A. Spec landed** — this document. Done when this file is committed and
BleakHouse-otae description references it.

**B. Provider-control surface implemented** — params.yaml extensions,
settings.resolved_providers, CLI flags, deprecated-alias translation. No
call-site changes yet. Acceptance: `uv run python -m enrichment.run_pipeline
--provider-profile all_openai --help` prints the resolved per-task map for
the active profile; running the pipeline still works because old --model
flags still resolve via the alias path.

**C. Seam capability parity** — add tool-use to GenerationRequest + both
providers. Acceptance: a self-contained probe runs an OpenAlex+Wikipedia
tool loop through the seam against both providers and gets matching
transcripts.

**D. Migration of interactive call sites** — sites #3, #4, #5, #6, #7, #8,
#9 route through the seam. Validation gate: after each, run both reference
profiles on OT alternatives short. Acceptance: `grep -rn
'anthropic\.Anthropic\|client\.messages\|client\.chat\.completions'
enrichment/` returns only `enrichment/llm/providers/` and the batch
submit/collect scripts.

**E. Batch path consolidation** (deferable) — `submit_passages_enriched*.py`
and `submit_passage_contexts.py` either gain a seam-mediated path or stay
carved out with a documented exception. Decision when D lands.

**F. Provenance landed** — `config.json` includes `providers` block; webapp
+ expdb scan read it without falling back to env or filename inference.

## Test fixtures

- **Smoke**: OT alternatives short (5 segments, ~$0.50-1 per profile).
  Used for every migration step.
- **End-to-end reference**: BH literary hostprep short, both profiles.
  Used after step D and again after step F.

## Decisions explicitly deferred

- Per-call **fallback** behaviour (e.g. retry winnower with Anthropic if
  the OpenAI call returns invalid JSON twice). Useful but adds policy
  surface; not in scope until the simple case ships.
- **Cost ceilings** per profile (e.g. abort if estimated cost >$X).
  Orthogonal to provider control; separate issue if needed.
- **Per-novel** provider profiles (e.g. "use gpt-5.4 only for Modernist
  novels"). Profiles are global today; novel-conditional profiles are a
  later refinement.

## Empirical findings that inform this spec

Recorded 2026-05-15 from the OpenAI variant pipeline implementation work;
the full per-call probe matrix lives in `docs/structured_output_review.html`.

- gpt-5.4 rejects `reasoning.effort="minimal"` (gpt-5-mini-only); supported
  values are `none / low / medium / high / xhigh`. Settings layer must
  validate per-model-id.
- OpenAI Responses API with `strict=false` accepts Pydantic schemas with
  `$defs`/`$refs` unchanged; `strict=true` rejects `allOf`/`anyOf`/`$defs`
  and requires every property in `required`. The seam should default to
  `strict=true` for OpenAI when feasible (sentinel: schema has no $refs) and
  fall back to `strict=false` otherwise. Document the fallback in run
  metadata.
- Under `strict=false`, gpt-5.4 occasionally hallucinates enum values
  (`sentence_type='commentary'` observed; `commentary` is valid in the
  separate `quote_mode` enum). Recommend a retry-on-validation-error helper
  in the seam — tracked separately as BleakHouse-atub.
- OpenAI Batch via `/v1/responses` works. JSONL shape: `{"custom_id",
  "method": "POST", "url": "/v1/responses", "body": {...}}`. 50% cost
  discount applies. Chunk size matters: at 200 paragraphs/request,
  reasoning.effort=minimal produced contiguous-prefix truncation; at 20
  paragraphs the failure pattern reduced to single-paragraph tail truncation
  (5 of 6916 OT paragraphs).
