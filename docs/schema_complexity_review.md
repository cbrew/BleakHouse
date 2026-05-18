# Schema complexity review — BleakHouse LLM-bound schemas

> **Update 2026-05-18 (BleakHouse-gfn2 epic closed):** the file-level
> inventory in this doc is **superseded** by the single consolidated
> file `enrichment/llm/schemas.py`. Cross-cutting concerns C1 (three
> postures on `additionalProperties`) and C5 (wrapper-list idiom) are
> partially resolved by BleakHouse-vyo4 and the consolidation. The
> per-schema observations and the open questions in §"Recommendations"
> still apply — they're about the shape and content of individual
> schemas, not their location. Read the inventory section as historical
> context; read the deep dives and the recommendations as current.

Status: review + (still-pending) recommendations. Companion to
`docs/structured_recommendations.md` (the external recommendations
doc), `docs/structured_output_review.html` (the empirical evidence
log + the two-tier-schema-strategy addendum), and
`docs/schemas_changelog.md` (the version-bump policy and history).

The review is scoped to **schemas that flow through the LLM seam via
`json_schema=...`** — i.e. shapes the model is asked to produce. It
does not cover internal Pydantic models that never become a JSON
Schema (e.g. config-side `ExpertPersona`, vector-DB `ContextualPassage`).

## TL;DR

> **Post-consolidation (2026-05-18):** all 13 LLM-bound schemas now
> live in a single file, `enrichment/llm/schemas.py`. The "scattered
> across four files" framing below describes the pre-consolidation
> state and the issues that motivated the move. The complexity
> observations below — schema content, list cardinality, enum
> overlaps — were NOT resolved by the move; they're about individual
> schemas and remain open.

Twelve LLM-bound schemas used to live across four files. They were not
designed together; the postures across them diverged significantly:

- **FieldReportEnrichment** (passage enrichment) is by far the largest
  — 21 fields, 11 of them Literal enums plus 4 lists. It declares
  itself "deliberately liberal" — no length caps, count guidance in
  descriptions only.
- **HostBrief / PreInterviewResponse / HostQuestion** (host prep) are
  the most constrained — `extra='forbid'`, `min_length`/`max_length`
  on every list, before-validator coercers.
- **EpisodeSegment / Turn / Utterance** (phase 3 generation) is the
  deepest — depth-3 nesting, large output, and emits numerical
  defaults (`rate`, `pause_before_ms`, `pause_after_ms`) the renderer
  largely ignores.
- **SegmentDesignResult / CurationResult / ChapterEnrichmentResult**
  are thin "wrap a list in an object" idioms.
- **JUDGE_SCHEMA** is a raw dict schema, not Pydantic — the only
  outlier.

There is no single architectural posture on:
- numerical constraints (some have `min_length`/`max_length`; most don't)
- `additionalProperties: false` (some use `ConfigDict(extra='forbid')`,
  some use `ConfigDict(json_schema_extra=...)`, most use neither)
- count guidance ("3-5" in description vs `min_length=3`)
- enum re-use (two overlapping vocabularies for "quote-y-ness")

## Inventory

LLM-bound shapes, sorted roughly by "production weight" (how often the
schema is emitted per pipeline run):

| name | file | task | depth | fields | list fields | constraints |
|---|---|---|---:|---:|---:|---|
| `FieldReportEnrichment` | `schemas.py` | passage_enrichment | 1 | **21** | 4 | none (description-only) |
| `ParagraphEnrichment` | `schemas.py` | (wraps FieldReportEnrichment) | 2 | 2 | 0 | none |
| `ChapterEnrichmentResult` | `schemas.py` | passage_enrichment | 3 | 2 | 1 | none |
| `Utterance` | `podcast_types.py` | (in EpisodeSegment) | 1 | **10** | 1 | description-only |
| `Turn` | `podcast_types.py` | (in EpisodeSegment) | 2 | 3 | 1 | none |
| `EpisodeSegment` | `podcast_types.py` | generate_podcast | **3** | 3 | 1 | none |
| `PreInterviewResponse` | `podcast_types.py` | host_prep_pre_interview_structured | 1 | 6 | 4 | `extra='forbid'`, min/max=1,4 |
| `HostQuestion` | `podcast_types.py` | (in HostBrief) | 1 | 4 | 1 | `extra='forbid'`, min/max=1,4 |
| `HostBrief` | `podcast_types.py` | host_prep_brief | 2 | 5 | 3 | `extra='forbid'`, min/max=3,4 & 1,4 |
| `SegmentTemplate` | `podcast_types.py` | (in SegmentDesignResult) | 1 | 7 | 3 | description-only |
| `SegmentDesignResult` | `design_segments.py` | design_segments | 2 | 1 | 1 | none |
| `CuratedAssignment` | `embedding_podcast.py` | (in CurationResult) | 1 | 7 | 0 | description-only |
| `CurationResult` | `embedding_podcast.py` | embedding_podcast_curate | 2 | 2 | 1 | none |
| `JUDGE_SCHEMA` (dict) | `scripts/judge_eval_pairings_llm.py` | (script) | 1 | 2 | 0 | enum + `additionalProperties: false` |

Schemas with `_StrictBase` (uses `json_schema_extra={"additionalProperties": False}`):
- FieldReportEnrichment, ParagraphEnrichment, ChapterEnrichmentResult.

Schemas with `ConfigDict(extra='forbid')`:
- PreInterviewResponse, HostQuestion, HostBrief.

Schemas with **neither**:
- Utterance, Turn, EpisodeSegment, EpisodeMetadata, PodcastEpisode,
  SegmentTemplate, SegmentDesignResult, CuratedAssignment, CurationResult.

That third bucket is the issue: it includes the deepest (`EpisodeSegment`)
and the most-emitted (`Utterance` × many per run) schemas. Pydantic
will silently accept hallucinated extra fields on each of them; the
generated JSON Schema doesn't have `additionalProperties: false` so
Anthropic strict-mode would 400 on the schemas as-is (this is masked
today because Anthropic only sees these via `output_config.format`,
which has its own behaviour, and we haven't probed every path).

## Per-schema deep dive — the four complexity hotspots

### 1. `FieldReportEnrichment` (schemas.py) — the over-loaded enrichment payload

**Shape:** 21 fields on one flat object. Composition:

- 2 free-text fields (`interest_rationale`, `summary`)
- 1 free-text optional (`best_quote`)
- 4 list-of-string fields (`characters_present`, `characters_speaking`,
  `themes`, plus the emotional_register Literal-list)
- 1 integer field with prose-only range (`interest_score: 0-5`)
- **11 Literal enums** — `narrator`, `plot_function`, 1 list-of-Literal
  (`emotional_register` × 9 values), `quotability`, `accessibility`,
  and 6 `prov_*` provision dimensions each with `none|weak|strong`.

**Smells:**

a. **Count guidance is description-only and inconsistent.** The
   `characters_present` description says "Most paragraphs have 1-3";
   `themes` says "typically 2-4 ... rich paragraphs may reach 8";
   `emotional_register` says "Typically 1-2; up to 4". The model has
   to read English text per field to figure out the rough cardinality.
   The schema doesn't help.

b. **A comment in the file declares this deliberate** (lines 21-27):
   "Numerical caps deliberately NOT enforced ... per 2026-05-13 user
   direction: 'make the schema liberal but add recommendations in the
   prompt'". So the design is intentional. The question for this
   review: does it still earn its keep? See "Cross-cutting concerns"
   for the inconsistency with the host_prep cluster's tighter posture.

c. **Six `prov_*` provision dimensions** each ask a `none|weak|strong`
   judgment. They cluster on related axes (character development,
   plot, theme, social critique, humor, atmosphere, technique). Are
   they all read downstream, or are some legacy? Worth checking
   `enrichment/transport_podcast.py` and `enrichment/embedding_podcast.py`
   for which `prov_*` fields actually feed selection. Anything unread
   is paid-for surface.

d. **Pydantic-side strictness is `json_schema_extra` not `extra='forbid'`.**
   The `_StrictBase` injects `additionalProperties: false` into the
   *emitted* JSON Schema, but Pydantic itself will silently accept
   extras at validation time. Asymmetric — the schema is stricter
   than the validator. If the model hallucinates a field, Anthropic
   rejects the response but Pydantic would accept it.

### 2. `Utterance` (podcast_types.py) — the over-loaded TTS unit

**Shape:** 10 fields, one of them a Literal enum (`quote_mode`), one
of them an Enum class field (`sentence_type` of type `SentenceType`).

**Smells:**

a. **Two enum vocabularies for an overlapping concept.**
   `sentence_type` has values `intro | question | quote_setup |
   quote_reading | analysis | punchline | transition | closing`.
   `quote_mode` has values `none | setup | reading | commentary`.
   The `setup` / `reading` values appear in both. The model has to
   set both consistently per utterance; the schema doesn't tell it
   they're related. Strong candidate for consolidation.

b. **Three numerical fields with detailed prose ranges in
   descriptions:** `rate` ("0.90-1.05; use 0.92-0.95 for quotes,
   1.02-1.05 for excited analysis"), `pause_before_ms` ("0 normal;
   120-220 before quotes; 180-260 after speaker switch"),
   `pause_after_ms` ("300 normal sentence; 500 emphasis; 800
   paragraph break; 1500 section break"). The model emits these
   per utterance. Do downstream renderers actually use them, or do
   they fall back to the speaker's `VoicePolicy`? If `VoicePolicy`
   wins, we're paying token output cost on every utterance for
   numbers the renderer ignores.

c. **`emphasis_words: list[str]` with description-only "max 2-3 per
   utterance"** — same description-only-cap pattern. Light weight,
   but consistent with the rest of the codebase.

d. **No `extra='forbid'`** — bucket 3 above. Anthropic side does
   not 400 here only because the seam denatures `additionalProperties`
   into the schema before sending (via the `_StrictBase` pattern —
   but `Utterance` doesn't extend `_StrictBase`, so even that
   protection is absent).

### 3. `EpisodeSegment` → `Turn` → `Utterance` (podcast_types.py) — the deepest schema

**Shape:** depth-3 nesting (`EpisodeSegment.turns` is `list[Turn]`;
`Turn.utterances` is `list[Utterance]`). Each segment can have
multiple turns; each turn many utterances. Multiplicatively this is
the largest schema we send.

**Smells:**

a. **Provider-side schema compile cost.** Anthropic compiles the
   grammar at first request and caches by schema hash; deeply nested
   schemas inflate compile time and inflate the per-call output
   tokens (the model has to traverse the structure). We don't have
   empirical compile-time numbers, but this is the schema most likely
   to suffer.

b. **No `additionalProperties: false` on any of the three.** Same
   bucket-3 issue, multiplied across the deepest schema.

c. **`EpisodeSegment` is minimal (just `title`, `segment_type`,
   `turns`).** The complexity is all under it. The structure is
   "container → speaker turns → atomic TTS units" which is genuinely
   3 levels of nesting; we can't easily flatten without changing the
   TTS contract.

### 4. `HostBrief` cluster — the recently-tightened set

**Shape:** the three host_prep models we touched today.
PreInterviewResponse (6 fields, 4 lists, all min/max=1,4),
HostQuestion (4 fields, 1 list min/max=1,4), HostBrief (5 fields, 3
lists with min/max=3,4 or 1,4).

**Strengths** (compared to the rest of the codebase):

- `extra='forbid'` on all three, consistent.
- Numerical constraints declared and (per the two-tier strategy)
  enforced at decode time on Qwen + post-validation on Anthropic.
- Per-field `min_length`/`max_length` is explicit, not buried in prose.

**Smells** (vs. the recommendations doc):

- We're using `minItems`/`maxItems` on the JSON Schema, which the
  recommendations doc lists as "intricate numeric constraints —
  avoid". Our two-tier strategy works around the portability issue,
  but the workaround is non-trivial code surface (the denature walker
  + the before-validator coercers + the placeholder shapes).
- The earlier conversation about replacing `HostBrief.questions` with
  slots (`question_1` … `question_4`) is precisely the "design to the
  portable subset" move the recommendations doc proposes — it would
  remove the need for the schema-constraint dance on the field that
  most needed it.

## Cross-cutting concerns

### C1. Three different postures on `additionalProperties: false` — RESOLVED 2026-05-18

Was three different patterns; now one. BleakHouse-vyo4 (closed
2026-05-18) migrated every LLM-bound class to
`model_config = ConfigDict(extra='forbid')` and deleted `_StrictBase`.
The seam-side `_strictify_for_openai` walker is gone too. The
single source of truth for object strictness is now the per-class
Pydantic config. See `docs/schemas_changelog.md` for the version-bump
discipline; see `CLAUDE.md`'s "Schema changes are breaking API
changes" section for the contributor policy.

### C2. Three different postures on list cardinality

| approach | example | enforcement |
|---|---|---|
| Description-only count guidance | FieldReportEnrichment.themes ("typically 2-4") | none — model may emit 0 or 100 |
| Pydantic `min_length` / `max_length` | HostBrief.questions (3-4) | decode-time on Qwen + post-validation coercion on Anthropic |
| `default_factory=list` (no description guidance) | EpisodeMetadata.chapters_covered | none, but signals "absence is OK" |

The doc-recommended pattern is **portable subset = required vs.
optional fields, no `minItems`/`maxItems` reliance**. We've adopted
the second approach where it matters most (host_prep) and held off
elsewhere (passage_enrichment by explicit design). The inconsistency
isn't structurally harmful, but it makes "what does this codebase
do about counts?" un-answerable in one sentence.

### C3. Numerical defaults emitted by the model and arguably ignored

`Utterance.rate / pause_before_ms / pause_after_ms` are emitted on
every utterance. The renderer also has `VoicePolicy.rate /
pause_bias_ms / style`. Do the per-utterance numbers ever override
the per-speaker policy? If the answer is "rarely or never", we're
paying:

- token output cost on every utterance (~30 tokens of JSON for the
  three numeric fields and their context),
- schema surface that the model has to learn to set sensibly,
- a category of hallucination risk (model emits `rate: 7.0`).

**Action item to check** before deciding: read `enrichment/render_audio.py`
and any TTS-rendering call sites to confirm whether per-utterance
`rate` / pauses are actually applied.

### C4. Overlapping enum vocabularies

`Utterance.sentence_type` (8 values, Enum class) and
`Utterance.quote_mode` (4 values, inline Literal) overlap on
"quote_setup / setup" and "quote_reading / reading". Consolidation
options:

- Drop `quote_mode` entirely; let `sentence_type == quote_setup`
  encode the same information.
- Or drop the quote-related values from `sentence_type` and rely
  entirely on `quote_mode` + a separate `intent`-style field.

The current state is the worst-of-both — two enums, each partial,
both worded slightly differently.

### C5. Wrapper-list idiom

`SegmentDesignResult`, `ChapterEnrichmentResult`, `CurationResult`
all have one job: be a Pydantic object whose only field is
`list[InnerType]`. This is a Pydantic convention for top-level JSON
output (you can't have a list as the top-level shape in JSON Schema
mode for most providers). It's not strictly excess complexity, just
a wart of the JSON-schema-must-be-an-object constraint. Worth
documenting as deliberate, not removing.

### C6. The non-Pydantic outlier

`JUDGE_SCHEMA` in `scripts/judge_eval_pairings_llm.py` is a raw dict
with 2 properties, an enum, `additionalProperties: false`, and
`required` on both. It's the smallest schema in the codebase and the
only one not derived from Pydantic. It's also the cleanest example of
"design to the portable subset". Not a complaint — a benchmark.

## Recommendations

### Apply uniformly

1. **`ConfigDict(extra='forbid')` on every LLM-bound model.** ✅ Done
   2026-05-18 under BleakHouse-vyo4. `_StrictBase` deleted; the nine
   previously-undefended schemas now each declare the config.

2. **Standardize on the recommendations-doc portable subset.** That
   means: `type`, `properties`, `required`, `items`, `$ref`, `$defs`,
   `additionalProperties: false`, `enum`, `anyOf` (for nullable),
   `description`, `format`. Treat `minItems`/`maxItems`/`min_length`/
   `max_length`/`pattern` as non-portable; reserve them for cases
   where decode-time enforcement is genuinely needed and worth the
   two-tier coercion machinery. (Still open beyond the host_prep
   cluster.)

### Decide per-schema (each needs a small judgment)

3. **`FieldReportEnrichment`: audit the `prov_*` dimensions.** For
   each of the 6 `none|weak|strong` provision fields, check
   downstream readers. Drop any that aren't read. This is the
   biggest payload in the system; trimming dead fields cuts cost on
   every passage_enrichment call.

4. **`Utterance`: investigate whether per-utterance `rate` / pauses
   are honoured by the renderer.** If `VoicePolicy` wins, drop the
   three numerical fields from the schema. (Adds back at the renderer
   side as a Python default; the model stops being asked.)

5. **`Utterance`: consolidate `sentence_type` and `quote_mode`.** Pick
   one; either drop the other or refactor `sentence_type` to lose
   the quote-related values.

6. **`HostBrief.questions`: revisit the slots-vs-list decision.** The
   slots refactor we discussed today would remove all the
   coercion machinery for the most-bothering field. Net-positive
   code change; the only cost is downstream iteration call sites
   (3 small edits).

7. **The other `min_length`/`max_length` constraints in the host_prep
   cluster (`PreInterviewResponse.*`, `HostQuestion.follow_up_for`,
   `HostBrief.cross_engagement_targets`, `HostBrief.recommended_reading`):**
   the variable-cardinality cases. Either keep them as-is (we now
   document the strategy), or drop the constraints and accept the
   description-only count guidance + prompt-level enforcement. The
   user's framing was "we are in trouble with our numerical
   constraints"; this is where most of the trouble accumulates.

### Add new (gap from the recommendations doc)

8. **Adversarial conformance suite.** For each provider/model we
   care about, an automated fixture set that probes the actual
   portable subset against the schemas above. Today we have
   `docs/structured_output_review.html` (an evidence log) and
   `scripts/probe_host_prep_qwen_vs_anthropic.py` (one fixture). The
   recommendations doc calls this out as the missing reliability
   layer; we should file it as a ticket.

## Open questions for the user

1. **Which `prov_*` dimensions are still load-bearing?** I can grep
   the readers and surface a list, but the call on which to keep is
   judgement, not mechanical.
2. **Per-utterance `rate` / `pause_*`: model output or renderer
   default?** Answer determines whether `Utterance` shrinks.
3. **`HostBrief.questions` slots: yes/no?** We have the open
   recommendation from the earlier turn; this review hasn't changed
   the trade-off.
4. **Cardinality constraints on the other host_prep list fields:
   keep, drop, or slot?** Slotting them isn't natural; keeping them
   keeps the two-tier coercion logic; dropping them returns to
   description-only.
5. **Scope of this cleanup:** apply uniformly across the LLM-bound
   surface in one pass, or stage (host_prep first, then
   passage_enrichment, then phase 3)?

## Where this fits in the bd tickets

- Adjacent to `BleakHouse-vyo4` (migrate all production Pydantic
  models to `extra='forbid'`, remove seam-side schema mutation) —
  this review extends the rationale and adds the per-schema
  recommendations.
- Adjacent to `BleakHouse-rosr` (Leviathan trial) — any cleanup we
  do here lands before that test case to keep its baseline clean.
- Would benefit from a new ticket for the **adversarial conformance
  suite** (per recommendation 8 above), and a per-schema cleanup
  ticket once we agree the scope.
