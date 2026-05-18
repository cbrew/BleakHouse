# Instructor as a cross-provider structured-output layer — exploration

Status: research-only, no code calls run. Investigates whether
[Instructor](https://python.useinstructor.com/) is a plausible
replacement for (or supplement to) BleakHouse's hand-rolled LLM seam
in `enrichment/llm/`.

Companion to:
- `docs/structured_recommendations.md` — the external review that
  named Instructor as "probably the most practical cross-provider
  reference implementation for Pydantic-first structured extraction".
- `docs/schema_complexity_review.md` — our own schema audit and
  recommendations.
- `docs/structured_output_review.html` — empirical provider behaviour.

## TL;DR

- **Instructor's value proposition matches our pain**: Pydantic models
  as the canonical schema, automatic validation-error retry, per-provider
  quirks absorbed inside the library. This is exactly the layer we
  hand-rolled in `enrichment/llm/providers/`.
- **Native providers we use**: OpenAI, Anthropic, Cerebras — all three
  have their own subdirectory under `instructor/providers/` (confirmed
  from the upstream repo, verified 2026-05-18).
- **OpenRouter**: not a native provider directory, but has a documented
  integration page (`/integrations/openrouter/`) — implemented by
  wrapping an `openai.OpenAI` client pointed at OpenRouter's base URL.
  This is the only route to Qwen3-235B-A22B-Instruct-2507 that uses an
  Instructor-named integration.
- **DeepInfra: no native support.** No provider directory, no
  integration page (the `/integrations/deepinfra/` URL is HTTP 404).
  Using DeepInfra requires the same trick as OpenRouter — build an
  openai client with a custom `base_url` and wrap it. Empirically
  unverified but architecturally straightforward.
- **Tool-use loops are the uncertainty.** Instructor's primary focus
  is single-shot structured output. The host_prep pre-interview loop
  is a multi-turn tool-use loop. We need to verify before relying.

## What Instructor is

A Python library that sits between application code and provider SDKs.
The canonical usage:

```python
import instructor
from pydantic import BaseModel

class Person(BaseModel):
    name: str
    age: int

client = instructor.from_provider("openai/gpt-4o-mini")
person = client.create(
    response_model=Person,
    messages=[{"role": "user", "content": "..."}],
)
```

Key features (from the docs):
- **Pydantic-first**: response_model is a Pydantic class; Instructor
  emits the JSON Schema, sends the call, validates the response, and
  returns a validated instance.
- **Modes**: TOOLS, JSON, MD_JSON, etc. — the underlying mechanism by
  which structured output is enforced. Per-provider defaults are
  picked automatically; can be overridden per call.
- **Retries**: documented to handle Pydantic ValidationError by
  re-prompting with the error as feedback. Number of retries is
  configurable.
- **Streaming, partial parsing, multi-tool**: also supported (we'd
  mostly ignore for now).

## Provider matrix for our use case

Verified against `https://github.com/instructor-ai/instructor/tree/main/instructor/providers`
on 2026-05-18:

| our use case | provider directory exists? | `from_provider` string | notes |
|---|---|---|---|
| Anthropic Sonnet 4.6 (production prose, host_prep_brief) | ✓ `anthropic/` | `anthropic/claude-sonnet-4-6` | native, mode=TOOLS recommended |
| Anthropic Haiku 4.5 (Phase 0/2.5 small calls) | ✓ `anthropic/` | `anthropic/claude-haiku-4-5-20251001` | same surface |
| OpenAI gpt-5-mini (parallel pipeline) | ✓ `openai/` | `openai/gpt-5-mini` | native |
| OpenAI gpt-5.4 | ✓ `openai/` | `openai/gpt-5.4` | native; the per-model `reasoning_effort` quirk (rejects "minimal") is *our* problem to handle until/unless Instructor catches it |
| Cerebras Qwen-3-235B / GLM / gpt-oss | ✓ `cerebras/` | `cerebras/qwen-3-235b-a22b-instruct-2507` | native |
| Qwen3-235B-A22B-Instruct-2507 on DeepInfra (Tier L winner, host_prep_qwen target) | **✗ no directory** | (use openai-compat with custom base_url) | the open question — see below |
| Qwen3-235B via OpenRouter (routes to DeepInfra) | ✗ no directory, ✓ integration page | `openrouter/qwen/qwen3-235b-a22b-2507` w/ `base_url="https://openrouter.ai/api/v1"` | viable, but adds OpenRouter margin |
| Together AI gpt-oss-120B | ✗ no directory, ✓ integration page | same openai-compat pattern | same shape |

## The DeepInfra question

You asked specifically about DeepInfra. **Instructor does not list
DeepInfra as a named integration**. The provider directory doesn't
exist; the integration page is HTTP 404.

What this means in practice:

1. **We can probably make it work** via Instructor's generic
   OpenAI-compatible wrapping: build an `openai.OpenAI` client with
   `base_url="https://api.deepinfra.com/v1/openai"` and an environment
   API key, then wrap with `instructor.from_openai(client, mode=...)`.
   This is the same pattern that almost certainly powers the OpenRouter,
   Together, and DeepSeek integration pages (they're not directories
   either — they're documentation entries for "use these arguments
   with the openai integration"). Empirically unverified for DeepInfra
   specifically but architecturally normal.

2. **Provider-specific quirks won't be absorbed.** When we used the
   seam directly today, we discovered DeepInfra's global request
   validator rejects `reasoning_effort='minimal'` even for models that
   don't list the parameter (the 422 we fixed via `_adapt_openai_reasoning_effort`).
   Instructor's generic openai wrapping won't know this; we'd hit the
   same 422 unless we pre-massaged the request. Same applies to any
   future DeepInfra-isms.

3. **The OpenRouter→DeepInfra path is an alternative.** OpenRouter
   routes `qwen/qwen3-235b-a22b-2507` to DeepInfra (verified 2026-05-17
   via `https://openrouter.ai/api/v1/models/.../endpoints`, see
   `docs/qwen_pricing_deepinfra_alibaba.html`). Using Instructor's
   OpenRouter integration avoids the "Instructor doesn't know about
   DeepInfra" problem at the cost of OR's margin (single-digit percent
   on this model; verified small).

## What we'd gain by adopting Instructor

Each item below maps to specific code we currently maintain:

| concern | our current code | what Instructor would absorb |
|---|---|---|
| Anthropic schema subset (drop minItems/maxItems) | `_denature_schema_for_anthropic()` + `_KNOWN_REJECTED_KEYS` allowlist | Instructor's Anthropic provider handles it (mode-dependent; verify) |
| OpenAI strict-mode `additionalProperties: false` injection | `_strictify_for_openai()` | Instructor's OpenAI provider handles it |
| Per-provider reasoning_effort vocabulary | `_adapt_openai_reasoning_effort()` | partial — Instructor's docs don't claim model-level adaptation |
| Pydantic ValidationError → retry with error context | not implemented; we let the error propagate | core Instructor feature |
| Schema strictness inconsistency (the C1 issue in `docs/schema_complexity_review.md`) | three different patterns across the codebase | Instructor enforces one pattern through `response_model` |
| Tool-call message-protocol differences (Anthropic block pairs vs OpenAI tool_calls) | `_generate_with_tools()` in both providers | uncertain — see below |

The line items above are real, measurable code surface — easily 500+
lines of provider-specific quirk-handling that Instructor's library
already maintains.

## What we'd lose / what isn't covered

| concern | our current code | Instructor coverage |
|---|---|---|
| **Per-task provider routing** (`task="host_prep_brief"` → resolve to a ModelSpec via params.yaml profile) | `enrichment/llm/settings.py` | **none** — Instructor takes the model id at call time. We'd keep this layer. |
| **Cost telemetry** (per-call estimated_cost_usd) | `enrichment/llm/cost_table.py` | **none** documented. We'd keep this. |
| **Multi-turn tool-use loop** (host_prep pre-interview emits 3-6 tool calls per persona×segment) | `_generate_with_tools()` in both providers | **uncertain** — Instructor focuses on structured output; tool-use loops are a documented capability but the surface looks different. Needs probe. |
| **DeepInfra-specific request adaptation** | `_adapt_openai_reasoning_effort` for the `'minimal'` → `'low'` translation | not absorbed (no DeepInfra integration) |
| **Auto-batch / progress flush** (per-interview checkpointing the `BleakHouse-3vev` ticket would add) | not implemented yet | not Instructor's domain |
| **Behaviour parity with the seam's observed quirks** (we've empirically validated specific things; Instructor may handle them differently) | seam code + comments + the structured-output review HTML | unverified |

The two big unknowns: **tool-use loops** and **DeepInfra adaptations**.
Until those are resolved by probing, the seam can't be fully retired.

## Architectural options

### Option A: Full replacement of `enrichment/llm/providers/`

Drop the two provider files. `enrichment/llm/__init__.py:generate()`
becomes a thin shim that:
1. Resolves task → ModelSpec via `settings.py` (unchanged).
2. Translates ModelSpec to an Instructor `from_provider` string.
3. Builds/caches the Instructor client.
4. Calls `client.create(response_model=..., messages=...)`.
5. Maps the result back to `GenerationResult` (token counts, cost, etc.).

**Pros**: ~600 lines deleted, schema mutation gone, retries free.

**Cons**: only viable for the single-shot structured-output call sites.
The tool-use loop in `host_prep.py:run_pre_interview_with_tools` would
need a different mechanism. Probably more lines than retained.

### Option B: Hybrid — Instructor for single-shot, seam for tool-loops

Keep the seam's `_generate_with_tools` path (it works, it's specific to
the one tool-loop call site in the codebase). Replace the single-shot
`_generate_one_shot` path with Instructor in both providers.

**Pros**: cleanest split by concern. The tool-loop is a small dedicated
piece; the single-shot path is the bulk of the surface and the bulk of
the pain.

**Cons**: two systems for callers to learn (though `GenerationRequest`
remains the entry point, so internal split is invisible to callers).

### Option C: Per-task migration (most conservative)

Pick the highest-pain task, replace ONLY that call site with Instructor.
Compare empirically. Iterate.

Candidate first migration: `passage_enrichment` (the largest, most-run
LLM call; single-shot; uses the gigantic `FieldReportEnrichment`
schema). If Instructor handles that cleanly, expand.

**Pros**: revert-able if it goes badly. Reveals integration friction
one site at a time.

**Cons**: slower. Two systems alive during the transition.

### Option D: Don't adopt; cherry-pick patterns

Take the ideas (uniform Pydantic + automatic retries on ValidationError
+ provider-specific mode picking) and add them to the existing seam.

**Pros**: no new dependency. Keeps the per-task routing and cost
telemetry intact without integration work.

**Cons**: we end up maintaining what Instructor already maintains.
Defeats the purpose.

## Open questions to resolve before deciding

1. **Tool-use loops**: can Instructor drive a multi-turn tool-use loop
   the way `host_prep.py:run_pre_interview_with_tools` does? Probe
   target: a 3-tool fixture against Anthropic native (the path we
   already know works in the seam).
2. **DeepInfra via custom base_url**: does
   `instructor.from_openai(openai.OpenAI(base_url=..., api_key=...))`
   work against Qwen3-235B-A22B-Instruct-2507? Probe target: a one-call
   fixture using our existing `Probe A / Probe B` shape from
   `scripts/probe_qwen3_235b_tool_use.py`.
3. **OpenRouter Qwen path**: does
   `instructor.from_provider("openrouter/qwen/qwen3-235b-a22b-2507",
   base_url="https://openrouter.ai/api/v1")` work end-to-end? Cost
   delta vs direct DeepInfra is small (verified earlier) but real.
4. **Anthropic schema handling**: does Instructor's Anthropic provider
   strip `minItems` / `maxItems` the way we currently do, or does it
   leak them through to a 400? If the latter, we keep
   `_denature_schema_for_anthropic`.
5. **Retry budget under high load**: passage enrichment runs over many
   thousands of paragraphs in batch. Instructor's retry-on-ValidationError
   can fire many times per call; the cost ceiling matters. Probe target:
   intentional validation failures.
6. **Cost extraction**: how do we surface input/output token counts
   and our `estimated_cost_usd` after an Instructor call? The
   `.create()` return value is a Pydantic instance; raw response is
   accessible but not the primary API.

## Recommended path forward

**Stage 1 — probe** (one session of work, no production change):

1. Write `scripts/probe_instructor_pilot.py`, modelled on
   `scripts/probe_qwen3_235b_tool_use.py`. It exercises Instructor
   against:
   - Anthropic native (claude-haiku-4-5) on a small schema → verifies
     our basic assumption.
   - DeepInfra via custom base_url on Qwen3-235B-A22B-Instruct-2507 →
     answers open question 2.
   - OpenRouter on the same model → answers open question 3.
2. For each path, run one structured-output call and one (synthesised)
   tool-use call. Record: what Instructor mode it picked, what the
   response shape was, how it handled validation, what raw token
   counts are visible.
3. Write findings into a new file `docs/instructor_probe_findings.md`,
   addendum-style. If any of the open questions block adoption, this
   is where they get documented.

**Stage 2 — decide** (after Stage 1):

Based on probe results, pick one of: A (full replacement), B (hybrid),
C (per-task migration), or D (cherry-pick). The honest expectation
based on what we know: B or C is most likely.

**Stage 3 — implement** (only if Stage 2 says "adopt"):

Migrate one task (likely `passage_enrichment`), compare empirically
with a side-by-side probe on a fixture, then expand.

## Bd ticket(s) to file

I'd file two tickets — one for the probe (Stage 1), one as a placeholder
for the migration (Stage 2-3 contingent). Stage 2 is a decision, not a
ticket.

- **(new) Probe Instructor as a structured-output layer**: scope = the
  probe script + findings doc. Blocks adoption decision.
- **(placeholder) Migrate one production task to Instructor** —
  blocked-by the probe ticket. Resolves only after probe results
  inform Stage 2.

Not filed yet — awaiting your sign-off on this plan.

## My honest reading

Instructor genuinely matches the layer we built. The retry-on-validation
feature alone would have saved us several rounds today. The provider
adaptation work we did empirically (Anthropic schema subset, OpenAI
strict-mode `additionalProperties`, reasoning_effort vocabulary) is
exactly the kind of thing Instructor maintains in one place across
versions.

The blockers are real but bounded:
- DeepInfra integration is "make our own client and wrap it" rather
  than first-class. Workable but won't absorb DeepInfra's quirks.
- Tool-use loops are an unknown until probed.

If Stage 1 probe says the openai-compat wrapping works on DeepInfra
and the tool-loop shape is tractable, I'd lean toward Option B
(hybrid: Instructor for single-shot, seam-style for the one tool-loop
site). That keeps `enrichment/llm/settings.py` and the cost table
intact while shedding the schema-mutation code.

If the probe surfaces friction, Option C (per-task migration) gives
us a graceful path.

If the probe says "DeepInfra doesn't work cleanly under Instructor"
then we'd either route Qwen via OpenRouter (small margin tax) or
keep the seam for the DeepInfra path and use Instructor for the
others (de facto hybrid).
