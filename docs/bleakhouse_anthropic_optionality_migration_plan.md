# BleakHouse: Open-Weight Default, Anthropic Opt-In

## Status

Revised 2026-05-11 after a round of plan-revision tickets
(BleakHouse-l4v9, -wh0d, -ipr3, -ft71, -79tv, -5b7m, -9k9n, -o3ir,
-0rtg, -c2yr, -r7g8). This document encodes the framework. The
research work (provider survey, per-task routing decisions) tracks
under the still-open tickets `o3ir` and `9k9n`.

## Purpose

Build provider optionality into BleakHouse so that:

1. **Open-weight models are the default** for LLM-backed work.
2. **Anthropic Claude stays supported as an opt-in**, selectable per
   task. Not removed.
3. A non-API (self-hosted) path is kept viable for at least one task,
   even if hosted-API alternatives score higher on the rubric.
4. The structured-output schema contract is preserved across provider
   substitution.

This is not a "fully migrate off Anthropic" plan. Anthropic remains
the right tool for some tasks (likely including the legacy long-form
prose path); open-weight becomes the default for the rest.

---

## Out of scope

These are explicit non-goals; do not generalize the migration to
absorb them.

1. **TTS migration** (BleakHouse-c2yr). Gemini-TTS is the audio
   rendering path. No alternative is good enough as of 2026-05.
   `enrichment/render_audio.py` and `enrichment/tts_voices/*` stay
   Gemini-specific. If a competitive alternative emerges, file a
   separate ticket.
2. **Removing Anthropic support.** Anthropic stays as an opt-in
   provider. The Anthropic-native Batch API path stays available
   because its 50%-off volume discount may make it the right choice
   for some tasks.
3. **Rewriting unrelated pipeline code.** Touch only what's needed
   to support the seam + per-task routing.
4. **Heavyweight agent framework.** No LangChain, no LangGraph, no
   DSPy. A small project-owned seam is the substrate.

---

## Verified facts (current state)

### Provider inventory

Per `docs/llm_call_sites.md` (BleakHouse-l4v9 — that's the
authoritative inventory; verify with a single grep pass before
coding, don't redo from scratch):

**Anthropic** — ~12 call sites across ~10 files:
- `enrichment/submit_passages_enriched.py` (batch submit, Haiku)
- `enrichment/collect_passages_enriched.py` (batch collect)
- `enrichment/retry_failed.py` (batch retry, Haiku)
- `enrichment/design_segments.py:283` (Phase 1, Haiku)
- `enrichment/generate_podcast.py:558,725` (Phase 3 prose, Sonnet 4.6)
- `enrichment/embedding_podcast.py:554` (Phase 3 embed variant, Sonnet 4.6)
- `enrichment/host_prep.py:203` (pre-interview agentic loop, Haiku)
- `enrichment/host_prep.py:245` (structured pre-interview, Haiku)
- `enrichment/host_prep.py:398` (host brief, Sonnet 4.6)
- `enrichment/reference_tools.py:444` (reading-list winnow, Haiku)
- `enrichment/submit_passage_contexts.py` (batch submit)
- `enrichment/collect_passage_contexts.py` (batch collect)
- `enrichment/test_single.py:60` (single-passage sanity script, Haiku)

**Gemini** — 3 TTS-only files; out of scope.

**OpenAI** — 1 site (`enrichment/retrieval_schema.py:6` via LanceDB
embedding adapter); not in scope for this migration.

### Existing deps that affect plan (BleakHouse-79tv)

`pyproject.toml` already carries:
- `llm>=0.30` — Simon Willison's LLM library; plugin-based provider abstraction.
- `llm-cerebras>=0.1.8` — LLM plugin for Cerebras.
- `cerebras-cloud-sdk>=1.67.0` — direct Cerebras SDK.

There's also `experiments/cerebras/` with pricing.py. These deps must
have been added for a reason. Before introducing a new
`enrichment/llm/` package, the survey/implementation must answer:
either (a) the new seam uses `llm` as its provider abstraction, or
(b) the deps come out in a cleanup ticket. Don't parallel-track a
new abstraction without acknowledging the one already in the tree.

### Structured-output contract (preserve)

The pipeline uses Pydantic schemas as the data contract:
- `ChapterEnrichmentResult.model_json_schema()` produces the JSON Schema.
- `ChapterEnrichmentResult.model_validate_json(...)` validates the response.

The provider layer returns text/JSON; the caller validates. This boundary
stays where it is.

### Short-podcast direction

The pipeline already supports `--length short` (~30 min audio,
~600 words/segment) via `enrichment/run_pipeline.py:503-507`. Two
short runs currently exist (`bh_trn_literary_hostprep_short`,
`wh_trn_literary_short`). The migration's prose-generation work
targets the short format as the primary product direction, not the
legacy long format. User clarification: "a whole hour of this stuff
is sometimes a bit much."

---

## Design principles

### 1. Per-task configuration, not global swap

Call sites request a task-level capability. Each task resolves to a
provider/model. Default per-task table (the actual values land via
`BleakHouse-9k9n` once `o3ir` survey concludes):

| task | suggested default tier | overridable |
|---|---|---|
| listener_pick | hosted small-class | yes |
| reading_list_winnow | hosted small-class | yes |
| reference_tools winnow | hosted small-class | yes |
| quote_verification | hosted small-class | yes |
| passage_enrichment (batch) | self-hosted mid-class | yes (Anthropic Batch may still win on cost) |
| passage_contexts (batch) | self-hosted mid-class | yes |
| design_segments | TBD by survey | yes |
| host_prep agentic | TBD by survey (capability-dependent) | yes |
| host_prep brief | TBD by survey | yes |
| generate_podcast (prose, short) | self-hosted large-class | yes (legacy long stays on Anthropic Sonnet) |
| embedding_podcast curation | TBD by survey | yes |
| test_single | follows passage_enrichment default | yes |

Constraint (BleakHouse-9k9n): the final table must include **at least
one task whose default is non-API self-hosted**. Natural candidates:
`generate_podcast` (prose, fine-tune story) and `passage_enrichment`
(volume, cost-sensitive).

### 2. Quality primary, price secondary (tier-first lexicographic)

For per-task model selection (BleakHouse-o3ir):
- **Tier 1: Quality.** Candidates with a meaningful quality gap drop
  out regardless of price. "Meaningful" is task-specific:
  - Prose: >10pt blinded-preference gap vs Sonnet-on-short baseline.
  - Structured filtering: >5pt set-overlap reduction.
  - Structured intermediate: >5pt schema-validity drop or field-presence drop.
- **Tier 2 (within quality-comparable candidates): Cost.** Pick the cheapest.
- **Tie-breakers:** structured-output reliability, rate-limit headroom,
  fine-tune feasibility, operational complexity.

The earlier weighted rubric (30% quality / 30% cost / 20% capability /
10% rate-limit / 10% ops) is retired as the primary instrument; stays
as a sanity-check second pass.

### 3. Schema as contract

Provider layer returns text/JSON; caller validates with the same
Pydantic models. Don't push Pydantic into the provider layer.

### 4. Batch is desirable but not essential (BleakHouse-r7g8)

- Anthropic-native Batch API stays available as an opt-in path for
  the 50%-off volume discount.
- Portable execution path = sequential or bounded-concurrency
  one-shots over the same logical request set. No promise of matching
  Anthropic Batch economics.
- Passage_enrichment and passage_contexts default-flips do NOT wait
  on a portable-batch story being mature. They flip on
  quality+cost-per-request alone.
- Concurrency speedups (e.g. ThreadPoolExecutor) are desirable but
  not gating. The SDK's max_retries=N + exponential backoff handles
  rate-limit bursts in the simplest path.
- This can flip back if a survey-shortlisted provider's batch
  economics materially change the cost picture.

### 5. Configuration is explicit and auditable

Each LLM-backed artifact records:
- logical task name
- provider
- model
- endpoint / base URL (if applicable)
- hosting (cerebras | runpod | modal | gke | together | fireworks | anthropic | ...)
- input_tokens, output_tokens
- estimated_cost_usd (from a per-model price table)
- execution_mode (one_shot | native_batch | portable_batch)
- whether provider-native structured output was requested

The cost field is first-class (BleakHouse-ft71), not a Phase 5
afterthought. Per-model prices live in a small Python dict next
to the seam; print a warning when an unknown model is encountered.

### 6. Non-API option preserved

The recommendation must include at least one self-hostable (Runpod /
Modal / GKE + open weights) candidate in the shortlist, even if a
hosted-API candidate scores higher. Motivations:
- API independence (Cerebras's catalogue narrowing on 2026-05-27 —
  llama3.1-8b and qwen-3-235b withdrawn, leaving only gpt-oss-120b —
  illustrates the risk).
- Fine-tuning enablement (hosted-only providers usually don't accept
  custom-weight uploads).
- Cost predictability at sustained volume.
- Data sovereignty.

### 7. Prefer a small, boring seam

`enrichment/llm/` package. Not LiteLLM, unless the `llm` reconciliation
ticket (BleakHouse-79tv) concludes that's the right path.

---

## Target structure

```
enrichment/llm/
  __init__.py
  types.py              # ModelSpec, GenerationRequest, GenerationResult, ProviderCapabilities
  settings.py           # task-to-model resolution
  client.py             # generate(...) facade
  cost_table.py         # per-model price dict (Anthropic, Cerebras, Together, etc.)
  providers/
    __init__.py
    anthropic_provider.py
    openai_compatible_provider.py
  batch.py              # portable batch runner; bounded concurrency
  eval/
    __init__.py
    fixtures/           # task-specific regression fixtures
    runner.py           # run a fixture against a configured provider
```

### Key types (sketch)

```python
@dataclass(frozen=True)
class ModelSpec:
    provider: str            # "anthropic" | "openai_compatible"
    model: str
    base_url: str | None = None
    hosting: str | None = None  # "cerebras" | "runpod" | "modal" | "gke" | ...

@dataclass(frozen=True)
class GenerationRequest:
    task: str
    system: str | None
    user: str
    max_tokens: int
    json_schema: dict[str, Any] | None = None
    temperature: float | None = None

@dataclass(frozen=True)
class GenerationResult:
    text: str
    provider: str
    model: str
    hosting: str | None
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost_usd: float | None
    execution_mode: str           # "one_shot" | "native_batch" | "portable_batch"
    raw: Any | None = None        # provider-native response for debugging

@dataclass(frozen=True)
class ProviderCapabilities:
    # BleakHouse-5b7m: per-provider capability flags
    json_schema_constrained: bool
    json_schema_strict: bool      # OpenAI 'strict' semantics
    tool_use: bool
    native_batch: bool
    context_window: int
    embedding_models: tuple[str, ...]
```

### Structured-output capability matrix (BleakHouse-5b7m)

The seam must not pretend "json_schema" is a universal feature.
Concrete mismatches per provider:

| provider | constrained-decoding mechanism | strict semantics |
|---|---|---|
| Anthropic | `messages.create` + `output_config={'format': {'type': 'json_schema', 'schema': ...}}` OR `messages.parse` + Pydantic model | Schema-strict by default; some validators happen client-side |
| OpenAI (and most OpenAI-compatible) | `response_format={'type': 'json_schema', 'json_schema': {'name': str, 'schema': dict, 'strict': bool}}` | 'strict': true rejects extra properties; not all compatible endpoints honor this |
| vLLM (OpenAI-compatible + extensions) | `extra_body={'guided_json': schema}` or `response_format` on recent versions | guided_json is regex-strict; response_format depends on vLLM version |
| SGLang | constrained_decoding=True with grammar | varies by deployment |
| Cerebras | `response_format` for json_schema | the 'strict' flag behavior differs from OpenAI's |
| TGI / Ollama | partial OpenAI compatibility | hit-and-miss |

When a task requests structured output and the configured provider
lacks the capability, **fail loudly at configuration time** (not at
first request). The seam exposes `ProviderCapabilities` per
configured provider; settings resolution checks the task's
requirements against the capability table.

The seam also normalizes the Anthropic `messages.create` vs
`messages.parse` return shapes so call sites don't have to know
which API the provider used internally.

---

## Phases

### Phase 1 — Seam introduction

1. Create `enrichment/llm/` with types, settings, anthropic_provider,
   client.
2. Refactor `enrichment/test_single.py` to use `generate(...)`.
3. Default settings preserve current Anthropic + Haiku behaviour for
   `passage_enrichment` (the task that `test_single` exercises).
4. Tests: provider translation, task settings resolution, end-to-end
   on `test_single`.

**Acceptance**: `test_single.py` has no direct `anthropic` import;
defaults reproduce current output.

### Phase 2 — Evaluation harness (moved up from old Phase 5; BleakHouse-ipr3)

Phase 2, not Phase 5, because under the open-weight-default policy
the eval harness is load-bearing. Without it, every default-flip
ships on faith.

1. `enrichment/llm/eval/` package: fixtures + runner.
2. For each task class, a small fixture (5-20 inputs).
3. Per-task quality floors (BleakHouse-0rtg):

   | task class | floor protocol | starting values |
   |---|---|---|
   | small structured (listener_pick, reading_list_winnow, reference_tools) | schema validity + set-overlap with Anthropic-Haiku baseline on 20-input fixture | 100% validity; ≥85% Jaccard |
   | structured intermediate (design_segments, host_prep brief, passage_enrichment) | schema validity + field-presence match + rubric-based content fidelity | 100% validity; ≥95% field-presence; rubric per fixture |
   | quote_verification | exact-match recall + false-positive rate | ≥98% recall, ≤2% FP |
   | agentic tool-use (host_prep pre-interview) | tool-call validity + convergence rate | 100% validity; ≥98% convergence |
   | prose (generate_podcast, short format) | schema validity + blinded preference vs Sonnet-on-short baseline | 100% validity; ≥45% preference |

   Floor VALUES are starting positions, revisable once Stage 2 of the
   o3ir survey produces real data. Floor PROTOCOL is the spec —
   what we measure, what against.

4. Runner reports per-task pass/fail and stores results in a small
   sqlite or JSON-on-disk record under `data/eval/`.

**Acceptance**: A task can be evaluated against any configured
provider; results are reproducible; floors are enforceable.

### Phase 3 — OpenAI-compatible provider + capability matrix

1. `enrichment/llm/providers/openai_compatible_provider.py` using the
   OpenAI Python client with configurable `base_url`.
2. Populate `ProviderCapabilities` for each candidate the survey
   shortlists.
3. Configuration surface for provider name + model + base_url + API key.
4. Fail loudly when a configured provider can't honour a task's
   structured-output requirement.

**Acceptance**: Same `GenerationRequest` can target Anthropic or
OpenAI-compatible backends; structured-output requests fail loudly
when the provider lacks the capability.

### Phase 4 — Open-weight survey + per-task routing decisions

This phase IS the work tracked by `o3ir` (survey) + `9k9n` (routing).
Two-stage:

**Stage 1: Desk survey (BleakHouse-o3ir Stage 1).**

For every candidate (Cerebras, Runpod, Modal, GKE, Together,
Fireworks, Groq, Anyscale, DeepInfra), record a single
markdown table in `docs/bleakhouse_provider_survey.md`:

| provider | hosting kind | models (license per model) | API surface | structured-output mechanism | rate limits | pricing | batch API | embedding support | fine-tune feasibility tier | ops complexity 1-5 |

Target effort: 2-4h focused web research.

Cerebras-specific note (2026-05-11): catalogue narrows to
gpt-oss-120b only after 2026-05-27 (llama3.1-8b and
qwen-3-235b-a22b-instruct-2507 withdrawn).

**Stage 2: Live benchmark on top 3-4 shortlisted candidates.**

Shortlist mix:
- One small-tier (Gemma 4 9B / Phi-4 / Yi-1.5 on Modal / Runpod) for
  structured filtering.
- One mid-tier (Qwen 2.5-72B / Llama-3.3-70B on Together / Fireworks)
  for structured intermediate.
- One large-tier for prose evaluation — Gemma 4 26B (MoE), Llama-3.3-70B,
  Qwen-2.5-72B, DeepSeek-V3 — targeted at the **short-podcast format**.
- One wildcard with a strong fine-tune story.

Run against fixed fixtures (3 small-structured / 5 mid-structured /
3 prose-short). Record per candidate × task:
- schema validity rate
- latency p50/p95
- cost per invocation
- quality verdict vs baseline

Target effort: 1-2 days of live calls + analysis.

**Decision**: apply the tier-first lexicographic rubric (Principle
2) to produce the per-task routing table (`9k9n`'s deliverable).

**Acceptance**: `docs/bleakhouse_provider_survey.md` exists with
Stage 1 + Stage 2 data; per-task routing table is populated; at
least one task's default is non-API self-hosted.

### Phase 5 — Per-task default flips

For each task, in order of lowest risk:

1. Listener-pick (BleakHouse-sz5m work already validated structurally — small, fast, low-stakes).
2. Reading-list winnow / reference_tools winnow.
3. Quote verification.
4. Host_prep brief.
5. Passage_contexts (batch).
6. Passage_enrichment (batch).
7. Host_prep agentic (capability-dependent).
8. Design_segments.
9. Embedding_podcast curation.
10. Generate_podcast (short format, prose; last because it's most subjective).

Each flip is gated on:
- the task's regression fixture exists
- the candidate model passes the task's quality floor
- the routing decision exists in `enrichment/llm/settings.py`
- the manifest records `provider`, `model`, `hosting`, etc.

Anthropic remains available as opt-in via per-task override.

`generate_podcast` long format may keep Anthropic Sonnet 4.6 as
its default by policy. That's a routing-table decision (Phase 4
output).

### Phase 6 — Native vs portable batch split (lower urgency)

Per BleakHouse-r7g8, this phase is not gating. The split exists
so manifests can record which mode produced an artifact, and so
operators can choose Anthropic Batch when its discount makes
economic sense.

1. Extract from `submit_passages_enriched.py`:
   - `build_enrichment_requests(...)` — provider-neutral logical requests
   - `submit_anthropic_native_batch(...)` — existing behaviour
   - `run_portable_batch(...)` — sequential or bounded-concurrency
   - `write_batch_manifest(...)` — records execution_mode
2. No silent fallback from native to portable batch.

### Phase 7 — Documentation and cleanup

1. Update `.env.example` to document the new task-routing variables
   and to soften the "ANTHROPIC required" wording.
2. Update `CLAUDE.md` Architecture section after the code is true.
3. Resolve BleakHouse-79tv: either commit to using the `llm` package
   underneath the seam, or remove `llm`/`llm-cerebras`/`cerebras-cloud-sdk`
   from pyproject.toml.
4. Operator notes: how to swap a task's provider; how to add a new
   provider; how to run the eval harness.

---

## Risk register

| Risk | Why it matters | Mitigation |
|---|---|---|
| Open-weight model produces valid JSON but worse semantics | Schema validity ≠ task quality | Per-task fixtures + content-fidelity rubric (Phase 2) |
| Anthropic Batch API semantics get hidden behind a false universal API | Confused code; weak portability | Keep native batch and portable batch explicit; r7g8 |
| Provider config sprawls | Hard to reason about experiments | Resolve by task; keep defaults explicit |
| Prose quality drops invisibly on short-format flip | User-facing degradation | Prose is last; blinded comparison against Sonnet-on-short; floor ≥45% preference |
| Docs drift again | Future assistants infer false architecture | Update docs only after code lands |
| OpenAI-compatible endpoints differ in structured-output support | "Compatible" ≠ identical | ProviderCapabilities table; fail loudly when unsupported (5b7m) |
| Cerebras catalogue narrows further | Hosted-API lock-in risk | Non-API option required in shortlist (Principle 6) |
| Survey grows stale | Open-source moves fast | Treat survey + floors as revisable; re-run when a candidate becomes available |

---

## Open work-items (not closed by this plan revision)

These tickets stay OPEN because they describe research/implementation
work that hasn't happened yet:

- `BleakHouse-o3ir` (P2) — run the provider survey (Stage 1 + Stage 2).
  Output: `docs/bleakhouse_provider_survey.md`.
- `BleakHouse-9k9n` (P3) — fill in the per-task routing decision table
  from the survey's results.
- `BleakHouse-wh0d` (P3) — finalize Phase 5 ordering once routing decisions
  are made.

Closed by this plan revision (the framework is now in this document):

- `BleakHouse-l4v9` — inventory reference (now points at docs/llm_call_sites.md).
- `BleakHouse-ipr3` — eval harness moved to Phase 2.
- `BleakHouse-ft71` — cost telemetry as manifest field; cost_table.py module.
- `BleakHouse-79tv` — `llm`/cerebras reconciliation deferred to Phase 7.
- `BleakHouse-5b7m` — capability matrix encoded in Principles + Phase 3.
- `BleakHouse-0rtg` — quality floor protocol + starting values encoded in Phase 2.
- `BleakHouse-c2yr` — Gemini-TTS scope-out in "Out of scope" section.
- `BleakHouse-r7g8` — batch as desirable-not-essential in Principle 4 + Phase 6.

---

## Minimal first PR

Make one call path provider-neutral while preserving current behavior.

**Scope**: `enrichment/llm/{__init__,types,settings,client,cost_table}.py`,
`enrichment/llm/providers/anthropic_provider.py`, `enrichment/test_single.py`,
and new tests under `tests/llm/`.

**Done when**:
1. `enrichment/test_single.py` has no direct `anthropic` import.
2. Running it with default settings still uses the same Claude model
   and structured-output contract.
3. Unit tests prove request translation and default settings.
4. No other call sites are migrated yet.
5. Manifest fields (`provider`, `model`, `hosting`, `input_tokens`,
   `output_tokens`, `estimated_cost_usd`, `execution_mode`) are
   populated.

This PR introduces the seam but doesn't claim any default flip; the
test_single migration is seam-introduction, not user-visible
behavior change.

---

## Coding instructions

### Do

- Work in small PR-sized increments.
- Keep current Anthropic behavior reproducible (set its task default
  to existing Claude model + parameters).
- Write tests before broad migration; use provider fakes in unit tests.
- Record provenance everywhere a generated artifact is written.
- Fail loudly when a configured provider can't honor a structured-output request.
- Treat the quality floors as a learning loop; revise values when Stage 2 results land.

### Do not

- Do not remove Anthropic.
- Do not rewrite the pipeline around a framework.
- Do not introduce a single universal abstraction that hides batch semantics.
- Do not move prose generation (especially long-form) first.
- Do not silently drop schema-constrained output when changing providers.
- Do not claim provider equivalence without repo-specific evaluation.
- Do not assume README.md / CLAUDE.md describe current code accurately.
