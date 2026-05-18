# Instructor probe findings

> **Decision 2026-05-18: not adopting Instructor.** The probes both
> passed mechanically, but the upstream-policy finding (issue #1320,
> closed as out-of-scope: multi-turn tool use will not land) makes
> the hybrid two-codepath architecture permanent. With our only
> multi-turn site being `host_prep.py`'s pre-interview loop, the
> dependency cost outweighs the marginal benefit. The seam in
> `enrichment/llm/` stays as the LLM abstraction. This doc is kept
> as the record of why we considered and why we declined; see the
> "Upstream policy" section at the bottom for the load-bearing
> citation. Tickets `BleakHouse-fupq` / `305o` / `26sq` are all
> closed.

Findings from the two Instructor probes filed against the open
questions in `docs/instructor_evaluation.md`. Companion to
`scripts/probe_instructor_deepinfra.py` (BleakHouse-fupq) and
`scripts/probe_instructor_tool_use.py` (BleakHouse-305o).

## Probe 1 — Instructor against DeepInfra (BleakHouse-fupq)

**Date:** 2026-05-18.
**Library version:** `instructor==1.15.1`.
**Model:** `Qwen/Qwen3-235B-A22B-Instruct-2507` via
`https://api.deepinfra.com/v1/openai`.

### What was tested

| probe | schema | mode | result |
|---|---|---|---|
| A | trivial Person (name, age) | `Mode.JSON_SCHEMA` | **PASS** — 21 in / 14 out tokens |
| B | trivial Person | `Mode.TOOLS` | **PASS** — 208 in / 26 out tokens |
| C | production `HostQuestion` (min_length=1, max_length=4, extra='forbid', nested list) | `Mode.JSON_SCHEMA` | **PASS** — 59 in / 146 out; returned a valid instance with `follow_up_for` length 2 (in-band) |
| D | trivial via OpenRouter | `Mode.JSON_SCHEMA` | SKIP — `OPENROUTER_API_KEY` not configured |

### What we learned

1. **DeepInfra works via `instructor.from_openai(openai.OpenAI(base_url=DEEPINFRA_BASE, api_key=...))`** — the generic openai-compatible wrapping is exactly the pattern. No code changes to Instructor needed.

2. **`Mode.JSON_SCHEMA` is the right default for DeepInfra.** It uses `response_format={"type":"json_schema","json_schema":...}` (the same surface our seam's `_generate_one_shot` path uses) and produces clean output at low token overhead.

3. **`Mode.TOOLS` works too but pays a ~10× overhead on input tokens** — the schema gets wrapped as a tool definition with all its description prose. For single-shot extraction, JSON_SCHEMA is unambiguously cheaper.

4. **Our production Pydantic constraints are honoured.** `HostQuestion` has `extra='forbid'`, `min_length=1`, `max_length=4` on `follow_up_for`. Instructor sent the full schema (Qwen on DeepInfra honours `minItems`/`maxItems` at decode time — verified in our earlier seam work). The response satisfied the constraints natively.

5. **Token counts and the raw completion are accessible** via `client.chat.completions.create_with_completion(...)` which returns `(parsed_model, raw_completion)`. The standard `create(...)` returns just the parsed model. We'd use `create_with_completion` everywhere we currently extract usage stats.

6. **No reasoning_effort issue.** Instructor doesn't set `reasoning_effort` automatically; the seam's `_adapt_openai_reasoning_effort` is only relevant for paths that explicitly request it. If we migrate single-shot calls to Instructor and stop passing `reasoning_effort` for tasks that don't need it, that whole adapter becomes irrelevant for the migrated paths.

### Implications for the Qwen production route

The clean recommendation: **direct DeepInfra wrapping**, no need for OpenRouter as the Instructor route to Qwen.

```python
import instructor
import openai

di_client = openai.OpenAI(
    api_key=os.environ["DEEPINFRA_API_KEY"],
    base_url="https://api.deepinfra.com/v1/openai",
)
client = instructor.from_openai(di_client, mode=instructor.Mode.JSON_SCHEMA)
result = client.chat.completions.create(
    model="Qwen/Qwen3-235B-A22B-Instruct-2507",
    response_model=MyPydanticModel,
    messages=[...],
)
```

OpenRouter remains a viable fallback for any DeepInfra outage but is not the primary route.

### Open follow-up (out of scope for this ticket)

- The probe did not exercise Instructor's auto-retry-on-ValidationError. Probe D would do that by sending a deliberately-confused prompt and observing the retry behaviour + cost ceiling.
- Streaming, partial parsing, `Maybe[T]` for optional outputs — all available but not relevant to BleakHouse's current call sites.

### Status

**BleakHouse-fupq: ready to close.** Recommendation: direct DeepInfra wrapping with `Mode.JSON_SCHEMA` is the production target for our Qwen route under Instructor. No code change needed in Instructor or our seam to support this; it's just a different way of calling the same wire format.

---

## Probe 2 — Instructor for multi-turn tool-use loops (BleakHouse-305o)

**Date:** 2026-05-18.
**Library version:** `instructor==1.15.1`.
**Models:** `claude-haiku-4-5-20251001` (probe A); `Qwen/Qwen3-235B-A22B-Instruct-2507` on DeepInfra (probe B).
**Probe script:** `scripts/probe_instructor_tool_use.py`.

### Surface inspection — what Instructor does and doesn't drive

Inspected `instructor.Instructor` class methods. The public surface is single-shot: `create`, `create_with_completion`, `create_iterable`, `create_partial`. There is **no built-in `tool_use_loop`** or similar multi-turn driver.

The `Mode` values that include `_tools` (e.g. `tool_call`, `anthropic_tools`, `parallel_tool_call`) refer to using tool-calling as the **mechanism** for structured output — i.e. the model "calls" a tool whose schema is the response_model. They do *not* drive multi-turn loops with multiple tools and user-defined executors.

So the architectural question becomes: can Instructor **coexist with manually-driven loops**? Specifically — can we drive the loop with the raw provider client (`anthropic.Anthropic()` / `openai.OpenAI()`), then call the Instructor-wrapped client for the final structured-output parse?

### What was tested

| probe | route | loop driver | final parse | result |
|---|---|---|---|---|
| A | Anthropic native (claude-haiku-4-5-20251001) | raw `anthropic.Anthropic()` with `tools=[…]`, manual tool_use/tool_result handling | `instructor.from_anthropic(client, mode=Mode.ANTHROPIC_TOOLS)` → `client.messages.create(response_model=ResearchSummary, …)` | **PASS** — 3 iterations, 3 tool calls, 1203-char final text, parsed into ResearchSummary |
| B | Qwen3-235B on DeepInfra (`base_url=https://api.deepinfra.com/v1/openai`) | raw `openai.OpenAI(base_url=…)` with `tools=[…]`, manual openai-style tool_calls + role:tool handling | `instructor.from_openai(client, mode=Mode.JSON_SCHEMA)` → `client.chat.completions.create(response_model=ResearchSummary, …)` | **PASS** — 3 iterations, 2 tool calls, 332-char final text, parsed into ResearchSummary |

Both probes produced valid Pydantic instances with all `min_length`/`max_length`/`extra='forbid'` constraints satisfied.

### What we learned

1. **The hybrid pattern works.** The same `openai.OpenAI()` / `anthropic.Anthropic()` client can be (a) used directly for raw tool-use turns, (b) wrapped via `instructor.from_*` for the final structured parse. No conflict; no special handling needed.

2. **Loop-driving code is provider-shaped (Anthropic vs openai-compat), but Instructor doesn't change that.** Anthropic uses `tool_use` / `tool_result` content blocks; openai-compat uses `tool_calls` + `role:tool` messages. Our seam's `_generate_with_tools` already abstracts this; Instructor doesn't.

3. **Migration story for the multi-turn tool-use call site (host_prep pre-interview):**
   - **Loop driver**: stays where it is, but could be slimmed if we wanted (it's already provider-agnostic-ish via the seam's `ToolSpec`/`tool_executors`).
   - **Final parse step** at `host_prep.py:323-334` (the `host_prep_pre_interview_structured` task call): cleanly replaceable by an Instructor call with `response_model=PreInterviewResponse`. This is the step we already determined was the bottleneck for Qwen — moving it to Instructor doesn't change that, but does drop our seam's strictify/denature code on this path.

4. **Mode picks**: probe A used `Mode.ANTHROPIC_TOOLS`; probe B used `Mode.JSON_SCHEMA`. These match what the seam already does on each provider (Anthropic tools-as-schema vs DeepInfra `response_format=json_schema`). No surprises.

5. **Cost / token telemetry is per-call.** Each call (loop turn or final parse) has its own `completion.usage`. Aggregation across the multi-turn sequence is on us — same posture as the seam.

### Implications for the architectural options in `docs/instructor_evaluation.md`

- **Option B (hybrid: Instructor for single-shot, seam-style for tool-loop)** is empirically viable. The "seam-style" piece doesn't need the seam — manual loop driving with the raw provider client is fine.
- **Option A (full replacement of the seam)** is also viable, but loop-driving code has to live somewhere; we'd just move it from the seam to a call-site helper. Architecturally similar surface.
- **Option C (per-task migration)** is the safest landing. First migration target: `passage_enrichment` (single-shot, large schema). After that lands, consider migrating `host_prep_pre_interview_structured` (the parse step) and so on.

### Caveats and follow-ups

- The probe used trivial response models (`ResearchSummary`, a 3-field test class). Production models (`PreInterviewResponse`, `HostBrief`, `EpisodeSegment`) are larger and have richer constraints. The DeepInfra probe (Probe 1) showed `HostQuestion` round-tripping cleanly — there's no reason to expect the larger models to break, but they remain unverified.
- Anthropic's `_denature_schema_for_anthropic` allowlist work is **not exercised by Instructor's path**. Instructor's `from_anthropic` does its own schema translation. Whether Instructor strips the same keys we do (`minItems`, `maxItems`, etc.) is empirically unverified for now — Probe A only showed it works, not that it handles arbitrary Pydantic models with non-trivial constraints. A second probe with `HostBrief` (with min_length=3 / max_length=4 on `questions`) against Anthropic via Instructor would tell us this.
- Cost-table integration (our `estimated_cost_usd`) is not surfaced through Instructor's API. We'd extract it from `completion.usage` and look up the price ourselves — same as we do today.

### Status

**BleakHouse-305o: ready to close.** The probe established the hybrid pattern works mechanically. See the next section for an upstream-policy finding that revises the framing.

A separate follow-up probe should exercise our largest production models (`PreInterviewResponse`, `HostBrief`, `EpisodeSegment`, `FieldReportEnrichment`) against Instructor's Anthropic path before the migration ticket (`BleakHouse-26sq`) is unblocked — to confirm Instructor's Anthropic schema translation handles the kind of constraints our schemas carry.

---

## Upstream policy — multi-turn tool use is out of scope (2026-05-18 finding)

While the probe was running, the user pointed at upstream issue
[567-labs/instructor#1320](https://github.com/567-labs/instructor/issues/1320),
titled "Support for multi-turn conversations that use function calling".
The issue is **closed as out-of-scope** with explicit maintainer
statements:

- **jxnl (original author), 2025-03-03**: *"not right now, the goal is
  to just make instructor a single tool. supporting conversations
  feels like slowly doing more than it needs to"*
- **ivanleomk (maintainer), 2025-03-17**: *"Going to close this for
  now since it's out of scope"*

This is a deliberate policy, not a missing feature waiting to land.
The hybrid pattern we just probed isn't a transitional workaround —
it's the permanent shape of any Instructor-based integration. If we
adopt Instructor, the tool-loop code in `host_prep.py` (or its
equivalent) is **infrastructure we maintain ourselves forever**.

A sharp comment from the issue's discussion captures the cost-benefit
question well:

> *"Even a simple requirement like giving LLM a calculator requires
> user to build a different codepath (which has validation, retries,
> etc) and bypass instructor. And once they do it, they can run
> everything through that codepath → no need for instructor anymore."*
> — sgondala, 2025-03-03

The argument: once you've written the tool-loop codepath with its own
validation and retries, you've reproduced most of what Instructor
offers, just for the non-tool case. The marginal value of Instructor
narrows.

### How this updates the BleakHouse recommendation

**Before this finding:** Option B (hybrid) with the implicit assumption
that tool-use might eventually land upstream. Migration looked like a
clean staged adoption.

**After this finding:** Option B is still mechanically viable. But the
"two-codepaths-forever" cost is structural. We need to weigh it
honestly.

What Instructor still buys us, given the policy:

- Mode auto-detection (picks JSON_SCHEMA vs TOOLS vs STRICT per provider).
- Auto-retry-on-ValidationError with the error fed back to the model
  as feedback.
- Uniform `response_model=` surface across providers.
- Library-maintained handling of provider-specific schema subsets
  (e.g. it likely already does the equivalent of our
  `_denature_schema_for_anthropic`).
- Active maintenance of new providers and new SDK versions — we don't
  have to chase API changes.

What it explicitly **won't** absorb (the maintainers have said so):

- Multi-turn tool use — we maintain `host_prep.py`'s loop driver
  permanently.
- Implicitly: anything that looks like "manage conversation state".

What it doesn't claim to absorb (silent on, must verify):

- DeepInfra-specific request quirks (the `reasoning_effort='minimal'`
  → HTTP 422 we fixed in the seam).
- Cost-table integration (we extract from `completion.usage`
  ourselves).
- Per-task routing (the `settings.py` task → ModelSpec dispatch).

### Three honest options now

**Option B-revised** — Hybrid adoption, eyes open. Use Instructor for
all single-shot calls; keep manual loop driving for the one tool-use
site in `host_prep.py`. Accept that the hybrid is permanent. **Net
gain**: roughly the schema-mutation code (`_denature_schema_for_anthropic`,
`_strictify_for_openai`) and the retry/validation logic we haven't
written yet. **Cost**: a real external dependency + two codepaths to
maintain for the foreseeable future.

**Option D-revised** — Cherry-pick patterns, no dependency. Take the
ideas (Pydantic-first, auto-retry-on-ValidationError, mode-aware
schema handling) and add them to our existing seam. **Net gain**: no
external dependency; full control; one codepath. **Cost**: we
maintain provider quirk handling as upstream APIs change.

**Option E (new)** — Adopt Instructor only for the simplest tasks
(passage_enrichment, embedding_podcast_curate, design_segments) where
the bulk of LLM cost lives and the schemas are static and small. Keep
the seam for host_prep entirely (both the tool loop and the brief).
**Net gain**: bounded scope of adoption; the seam doesn't need to
serve two purposes. **Cost**: heterogeneous architecture for the rest
of the project; new contributors have to learn both paths.

### Recommendation update

The upstream-policy finding is genuinely significant. I'd downgrade
my prior "hybrid adoption" recommendation from "yes, file the
migration" to **"reconsider with the policy in mind"**.

Specifically: before unblocking `BleakHouse-26sq` (migrate one task
to Instructor), we should answer two questions that the probe didn't
address:

1. **Does Instructor's Anthropic provider strip the same JSON-Schema
   keys our `_denature_schema_for_anthropic` does?** If yes, that's
   the largest concrete win and worth adopting for. If no, we'd
   still need our denature code, which shrinks the value.
2. **What's our retry budget tolerance?** Auto-retry-on-ValidationError
   can fire 1-3 times per call by default. On a batch enrichment run
   over thousands of paragraphs, that's a real cost variance we don't
   have today.

Both are short follow-up probes. If both answer favourably, Option
B-revised is still the recommendation. If Anthropic schema handling
is no better than ours, Option D-revised (cherry-pick) becomes more
attractive. If retry cost is unbounded, Option E (scoped adoption)
hedges.

The migration ticket `BleakHouse-26sq` should stay open and blocked
until those two questions resolve.
