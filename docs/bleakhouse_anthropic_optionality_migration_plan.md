# BleakHouse: Make Anthropic Optional Without Breaking the Pipeline

## Purpose

Implement provider optionality for BleakHouse so that:

1. Anthropic Claude remains supported and may remain the default.
2. The codebase no longer requires Anthropic for all LLM-backed work.
3. Open-weight models served through an OpenAI-compatible endpoint can be evaluated and used selectively.
4. Provider-specific behavior is not hidden behind leaky abstractions, especially Anthropic's Batch API.

This document is written for an LLM coding assistant working inside the repository. Follow it as an implementation plan, not as a speculative architecture exercise.

---

## Verified current-state facts

These are facts already visible in the repository and should be treated as constraints.

### Environment and provider inventory

`.env.example` currently documents:

- `ANTHROPIC_API_KEY` for “Phase 1/2.5/3 generation, quote verification”
- `PERSONAL_ANTHROPIC`
- `GEMINI_API_KEY` for TTS
- `OPENAI_API_KEY` for embeddings and the RAG tutorial
- `CEREBRAS_API_KEY` and `CEREBRAS_FREE_TIER_API_KEY` for alternative-generator experiments

### Known direct Anthropic coupling

At least the following files directly couple to Anthropic:

- `enrichment/test_single.py`
  - imports `anthropic`
  - constructs `anthropic.Anthropic(...)`
  - calls `client.messages.create(...)`
  - uses Anthropic-native structured output:
    `output_config={"format": {"type": "json_schema", "schema": schema}}`

- `enrichment/submit_passages_enriched.py`
  - imports `anthropic`
  - imports Anthropic batch request types
  - hard-codes `MODEL = "claude-haiku-4-5-20251001"`
  - constructs Anthropic-native batch requests
  - submits via `client.messages.batches.create(...)`

### Existing structured-output contract

The enrichment pipeline already has a real schema boundary:

- `ChapterEnrichmentResult.model_json_schema()`
- `ChapterEnrichmentResult.model_validate_json(...)`

Preserve that boundary. The migration should change providers, not weaken the contract.

### Important implication

There are at least two distinct problems:

1. **Single request portability**: replace a direct Anthropic call with a provider-neutral request path.
2. **Batch execution portability**: replace Anthropic Batch API dependence with a pipeline-level batch abstraction or a separate execution path.

Do not pretend these are the same problem.

---

## Goals

### Primary goals

1. Make Anthropic optional for all newly touched LLM call sites.
2. Keep current behavior reproducible when `anthropic` is selected.
3. Support at least one OpenAI-compatible provider suitable for:
   - hosted open-weight models on Runpod/vLLM or equivalent
   - Cerebras/OpenAI-compatible experimentation where practical
4. Preserve schema-constrained outputs and validation.
5. Record provider/model provenance in outputs and manifests.
6. Make it easy to benchmark providers per task rather than globally switching the whole project.

### Non-goals for the first migration

1. Do not remove Anthropic support.
2. Do not promise that open-weight models equal Sonnet quality.
3. Do not rewrite unrelated pipeline code.
4. Do not introduce a heavyweight agent framework.
5. Do not force all providers into Anthropic Batch semantics.
6. Do not change Gemini TTS work in this migration.
7. Do not generalize prematurely across every possible LLM feature.

---

## Design principles

### 1. Separate **task** from **provider/model**

Call sites should request a task-level capability, not a raw model string.

Examples of tasks:

- `passage_enrichment`
- `quote_verification`
- `reading_list_generation`
- `script_generation`
- `listener_pick`
- any other actual current tasks found during inventory

Each task resolves to a provider/model configuration.

Bad:

```python
MODEL = "claude-haiku-4-5-20251001"
```

Better:

```python
task = "passage_enrichment"
model_spec = settings.for_task(task)
```

### 2. Preserve provider-specific execution where it genuinely differs

A single portable interface for one-shot generation is desirable.

A fake universal batch interface is not, unless it captures genuinely shared semantics.

For now, treat these separately:

- **single request**: portable
- **provider-native batch submission**: Anthropic-specific
- **portable batch runner**: project-owned orchestration over many single requests

### 3. Keep the Pydantic schema as the contract

The provider layer should return text/JSON; the caller should continue to validate with the current Pydantic models.

Where the provider supports constrained decoding, use it. Still validate after generation.

### 4. Configuration should be explicit and auditable

A run should record:

- logical task
- provider
- model
- endpoint/base URL where relevant
- decoding configuration
- whether provider-native structured output was requested
- whether provider-native batch mode or portable batch mode was used

### 5. Prefer a small, boring seam

Do not start with LiteLLM unless there is a demonstrated need. BleakHouse has a small enough number of call patterns that an internal seam is likely easier to reason about and easier to test.

---

## Proposed target structure

Create a small package under `enrichment/llm/`:

```text
enrichment/llm/
  __init__.py
  types.py
  settings.py
  client.py
  providers/
    __init__.py
    anthropic_provider.py
    openai_compatible_provider.py
  batch.py
```

### `types.py`

Define narrow types. Do not over-model future features.

Suggested concepts:

```python
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str
    base_url: str | None = None

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
    raw: Any | None = None
```

Do not put Pydantic model classes into the provider layer. Pass JSON Schema only.

### `settings.py`

Provide task-to-model resolution from environment-driven config.

First acceptable implementation:

- environment variables with explicit names
- sensible defaults preserving current Anthropic behavior

Example shape:

```python
TASK_DEFAULTS = {
    "passage_enrichment": ModelSpec(
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
    ),
}
```

Add environment overrides later, for example:

```text
BLEAKHOUSE_LLM_PASSAGE_ENRICHMENT_PROVIDER=anthropic
BLEAKHOUSE_LLM_PASSAGE_ENRICHMENT_MODEL=claude-haiku-4-5-20251001

BLEAKHOUSE_OPENAI_COMPATIBLE_BASE_URL=
BLEAKHOUSE_OPENAI_COMPATIBLE_API_KEY=
```

Do not make the first PR depend on a new config file format unless the repo already has a clear place for one.

### `client.py`

Provide the task-facing API.

Suggested first surface:

```python
def generate(request: GenerationRequest) -> GenerationResult:
    ...
```

Possible later surface:

```python
async def agenerate(request: GenerationRequest) -> GenerationResult:
    ...
```

Do not force async into the first PR unless the touched call sites already need it.

### `providers/anthropic_provider.py`

Implement current behavior exactly enough to preserve existing outputs:

- create Anthropic client from `ANTHROPIC_API_KEY`
- call `messages.create`
- when `json_schema` is present, translate to Anthropic `output_config`
- return the first text block
- do not parse into Pydantic models here

### `providers/openai_compatible_provider.py`

Implement the minimal path needed for hosted open-weight models:

- use the OpenAI Python client with configurable `base_url`
- use `chat.completions.create`
- when `json_schema` is present, pass `response_format={"type": "json_schema", ...}` if the endpoint supports it
- return `choices[0].message.content`
- do not assume every OpenAI-compatible endpoint supports every feature; surface provider errors clearly

### `batch.py`

Implement **portable batch execution**, not a fake provider abstraction over Anthropic Batch API.

First acceptable version:

```python
def run_many(
    requests: list[GenerationRequest],
    *,
    concurrency: int = 1,
) -> list[GenerationResult]:
    ...
```

This can initially be sequential. Concurrency can be added later.

Keep Anthropic-native batch submission as a separate adapter/path until there is a reason to remove it.

---

## Required inventory before coding

The assistant must do this first inside the repo:

```bash
rg -n "import anthropic|from anthropic|messages\.create|messages\.batches|claude-|ANTHROPIC_API_KEY|PERSONAL_ANTHROPIC" .
rg -n "CEREBRAS|cerebras|OPENAI_API_KEY|llm\.get_model|llm\.get_async_model|from openai|import openai" .
```

Then produce a short table in the working notes:

| file | function/entry point | current provider | current model | call type | schema? | batch? | proposed task name |
|---|---|---:|---|---|---:|---:|---|

Do not proceed on the assumption that the files named in this document are exhaustive.

---

## Migration phases

## Phase 0 — Inventory and characterization

### Work

1. Run the inventory commands above.
2. Identify every LLM-backed call site.
3. Classify each call site by:
   - task
   - provider
   - model
   - single vs batch
   - structured vs free text
   - sync vs async
   - required context length if obvious
4. Identify which outputs already record `model`, and which do not.
5. Identify tests already covering each call path.

### Deliverable

Create a temporary planning note or issue comment with the call-site table.

### Acceptance criteria

- No direct Anthropic call site remains undiscovered within the files searched.
- The assistant can explain which paths are easy one-shot migrations and which paths are batch-specific.

---

## Phase 1 — Introduce the provider-neutral one-shot seam

### Work

1. Add `enrichment/llm/` package.
2. Implement:
   - `ModelSpec`
   - `GenerationRequest`
   - `GenerationResult`
   - task-to-model settings
   - `generate(...)`
   - `AnthropicProvider`
3. Refactor **only** `enrichment/test_single.py` first:
   - remove direct Anthropic construction from the script
   - replace it with `generate(...)`
   - preserve:
     - prompt
     - max_tokens
     - schema
     - validation
     - logging
4. Keep the default task resolution pointing to the current Claude model.

### Tests to add

1. Unit test provider translation:
   - request with JSON schema becomes Anthropic `output_config`
2. Unit test task settings:
   - default task resolves to existing provider/model
3. Script-level or function-level test:
   - `test_single` still validates `ChapterEnrichmentResult`

Use fakes; do not make tests depend on live APIs.

### Acceptance criteria

- `test_single.py` no longer imports `anthropic`.
- Running with default settings still uses the same Anthropic model and schema mode as before.
- Existing output validation remains unchanged.
- No pipeline behavior changes beyond the new seam.

---

## Phase 2 — Add an OpenAI-compatible provider

### Work

1. Implement `OpenAICompatibleProvider`.
2. Add configuration for:
   - provider name
   - model
   - base URL
   - API key
3. Support JSON-schema output where available.
4. Add one small smoke-test script or CLI mode that can run:
   - current Anthropic provider
   - OpenAI-compatible provider
   on the same fixed passage/chapter input.

### Tests to add

1. Unit test:
   - structured request becomes expected OpenAI-compatible request shape
2. Unit test:
   - provider error is surfaced with enough context to debug endpoint/model mismatch
3. Optional contract test:
   - both providers return text accepted by the same downstream Pydantic validation path

### Acceptance criteria

- No code change is needed at a call site to swap `passage_enrichment` from Anthropic to an OpenAI-compatible model; only task configuration changes.
- A real endpoint can be exercised without editing code.
- Pydantic validation stays outside the provider.

---

## Phase 3 — Deal with batch execution explicitly

### Background

`submit_passages_enriched.py` currently depends on Anthropic Batch API. Open-weight endpoints will commonly not provide that API.

### Work

1. Split the current concerns:
   - request construction
   - execution mode
   - result persistence
2. Preserve Anthropic-native batch path for now.
3. Add a portable execution path over the same logical requests:
   - many one-shot requests
   - sequential at first or bounded-concurrency if straightforward
   - resumable from manifest state if practical
4. Record execution mode in manifests:
   - `provider_native_batch`
   - `portable_batch`
5. Keep model/provider recorded per request set.

### Suggested refactor

Extract from `submit_passages_enriched.py`:

```text
build_enrichment_requests(...)        # provider-neutral logical requests
submit_anthropic_native_batch(...)    # existing behavior
run_portable_batch(...)               # provider-neutral
write_batch_manifest(...)
```

Do not require the portable path to mimic Anthropic batch IDs.

### Acceptance criteria

- Anthropic native batch still works.
- The same logical enrichment requests can be run without Anthropic Batch API.
- Manifests reveal which provider, model, and execution mode produced the outputs.
- No silent fallback from native batch to portable batch.

---

## Phase 4 — Migrate remaining call sites task by task

### Work

Using the Phase 0 inventory, migrate the remaining call sites in order of lowest risk:

1. strict structured tasks
2. deterministic validation/filtering tasks
3. intermediate generation tasks
4. final prose/script generation last

For each task:

1. name the task
2. route through the shared seam
3. add or update tests
4. preserve current Anthropic default
5. record provider/model provenance
6. create a small evaluation fixture if none exists

### Suggested order

Probable first candidates, subject to inventory:

1. quote verification
2. any simple classification/filtering paths
3. passage enrichment
4. reading-list/listener-pick tasks
5. script generation last

### Acceptance criteria

- No directly migrated call site imports Anthropic.
- Task defaults preserve current behavior.
- OpenAI-compatible providers can be selected per task.
- Regression tests pass.

---

## Phase 5 — Evaluation harness for provider substitution

### Purpose

Provider optionality is not useful unless task quality can be measured on BleakHouse's own workloads.

### Work

Create a small evaluation harness, probably under `enrichment/eval/` or existing experiment machinery if one already exists.

For each migrated task, define:

- fixed input fixtures
- expected schema validity
- retry rate / parse failure rate
- latency
- token usage where available
- task-specific semantic checks
- blinded human-comparison support where the task is creative

For final script generation, do not use schema validity as the primary metric. Use human preference / publishability judgments.

### Initial evaluation matrix

At minimum compare:

- current Anthropic default
- one small/cheap open model for structured tasks
- one stronger open model for literary generation

### Acceptance criteria

- A provider can be substituted and evaluated without editing pipeline code.
- Results record task/provider/model.
- There is an explicit “good enough for this task” decision mechanism, not a global model ranking.

---

## Phase 6 — Documentation and cleanup

### Work

1. Update `.env.example`:
   - do not describe Anthropic as mandatory if it no longer is
   - document OpenAI-compatible endpoint variables
   - document per-task overrides
2. Update `README.md` and `CLAUDE.md` only after the code is true.
3. Remove dead dependencies only after verifying they are dead.
4. Add a short operator note:
   - how to use Anthropic
   - how to use a hosted open-weight endpoint
   - how to run the task/provider smoke test
   - how to run the evaluation harness

### Acceptance criteria

- Docs describe the actual implementation, not the intended future.
- Fresh setup instructions make provider requirements clear.
- Anthropic remains usable, but is no longer conceptually mandatory.

---

## Specific coding instructions for the assistant

### Do

- Work in small PR-sized increments.
- Keep current Anthropic behavior as the regression baseline.
- Write tests before broad migration.
- Use dependency injection or provider fakes in unit tests.
- Keep raw provider responses available enough for debugging.
- Preserve existing output schemas.
- Record provenance everywhere a generated artifact or manifest is written.
- Make failures loud when a selected provider does not support requested structured output.

### Do not

- Do not rewrite the pipeline around a framework.
- Do not introduce a single universal abstraction that hides batch semantic differences.
- Do not remove Anthropic until a later explicit decision.
- Do not move final prose-generation tasks first.
- Do not silently drop schema-constrained output when changing providers.
- Do not assume `README.md` or `CLAUDE.md` accurately describe current code.
- Do not claim provider equivalence without repo-specific evaluation.

---

## Minimal first PR

### Scope

Make exactly one call path provider-neutral while preserving current behavior.

### Files likely touched

```text
enrichment/llm/__init__.py
enrichment/llm/types.py
enrichment/llm/settings.py
enrichment/llm/client.py
enrichment/llm/providers/anthropic_provider.py
enrichment/test_single.py
tests/... new LLM seam tests ...
```

### Done when

1. `enrichment/test_single.py` has no direct `anthropic` import.
2. Running it with default configuration still uses the same Claude model and structured-output contract.
3. Unit tests prove request translation and default settings.
4. No other call sites are migrated yet.
5. There is no behavioral claim beyond “the seam exists and default behavior is preserved.”

---

## Minimal second PR

### Scope

Add OpenAI-compatible single-request support.

### Files likely touched

```text
enrichment/llm/providers/openai_compatible_provider.py
enrichment/llm/settings.py
.env.example
tests/... provider tests ...
```

### Done when

1. A task can point at an OpenAI-compatible endpoint through configuration.
2. The same `GenerationRequest` can target Anthropic or OpenAI-compatible backends.
3. Structured-output request shaping is tested.
4. A local or hosted endpoint can be smoke-tested without code changes.

---

## Minimal third PR

### Scope

Make passage enrichment executable without Anthropic Batch API.

### Files likely touched

```text
enrichment/submit_passages_enriched.py
enrichment/llm/batch.py
tests/... batch orchestration tests ...
```

### Done when

1. Existing Anthropic-native batch submission remains available.
2. Portable batch mode exists.
3. The manifest records provider/model/execution mode.
4. Logical request construction is no longer entangled with Anthropic request classes.

---

## Suggested acceptance test suite

### Unit tests

- model/task settings resolution
- Anthropic structured-request translation
- OpenAI-compatible structured-request translation
- unsupported provider/mode errors
- provenance fields included in manifests
- portable batch runner preserves input/output ordering or explicit IDs

### Integration-ish tests with fakes

- `test_single` happy path under Anthropic fake
- `test_single` happy path under OpenAI-compatible fake
- portable passage-enrichment batch over 2–3 fake requests
- manifest emission for both native and portable modes

### Manual smoke tests

- one real `test_single` run with Anthropic
- one real `test_single` run with a hosted OpenAI-compatible model
- one tiny portable enrichment batch on a few passages
- compare output validity and obvious semantic adequacy before moving further

---

## Risk register

| Risk | Why it matters | Mitigation |
|---|---|---|
| Open-weight model produces valid JSON but worse semantics | Schema validity is not task quality | Task-specific evaluation fixtures and human review |
| Anthropic Batch API semantics get hidden under a false universal API | Leads to confused code and weak portability | Keep native batch and portable batch explicit |
| Provider config becomes sprawling | Hard to reason about experiments | Resolve by task; keep defaults explicit |
| Final script quality drops invisibly | User-facing product degradation | Migrate prose generation last; use blinded comparisons |
| Docs drift again | Future assistants infer false architecture | Update docs only after code lands; remove stale claims |
| OpenAI-compatible endpoints differ in structured-output support | “Compatible” is not identical | Test capabilities; fail loudly when unsupported |

---

## Open questions to settle only after inventory

1. What are the exact current LLM call sites beyond the already verified files?
2. Which tasks truly need long context?
3. Which tasks currently use Sonnet versus Haiku?
4. Does any current experiment machinery already provide the right place to record provider/model provenance?
5. Which outputs are stable enough to serve as evaluation fixtures?
6. Should provider configuration eventually live in code, environment variables, or experiment manifests?
7. Is a later `llm`-package integration useful, or is a small internal seam better long-term?

---

## Recommended first instruction to give the coding assistant

> Read this plan. Do not begin by changing code. First run the inventory commands, inspect the actual current LLM call sites, and produce the call-site table requested in Phase 0. Treat repository docs as hypotheses unless confirmed by code. Then implement only the minimal first PR: introduce the one-shot provider seam and migrate `enrichment/test_single.py` while preserving current Anthropic behavior exactly.
