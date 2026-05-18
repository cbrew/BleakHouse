# Schema change log — `enrichment/llm/schemas.py`

This file is the version log for every Pydantic class used as a
`response_model` for a structured-output LLM call in BleakHouse.

**Treat schema changes as breaking API changes.** A schema is part of
the contract between BleakHouse and the LLM, and between BleakHouse
and the saved-run artefacts on disk. Every edit to `enrichment/llm/schemas.py`
should be reflected here, and the `schema_version` ClassVar on the
affected class(es) should be bumped per the rules below.

## Bump rules (semver-ish)

The bump category determines whether a migration script is needed for
existing saved data and whether downstream `pyright`/Pydantic
validation will continue to accept old artefacts.

### Patch (`schema_version` unchanged or date-only refresh)

No saved-data migration. No code-level change required of consumers.

- Adding an optional field with a default value.
- Adding a Literal/Enum value (additive — old data has only the
  pre-existing values, which remain valid).
- Loosening a constraint that previously rejected valid output
  (e.g. `min_length=3 → min_length=1`; `max_length=4 → max_length=5`).
- Description-text changes, docstring changes, comment changes.
- Field re-ordering (Pydantic doesn't care; downstream callers might
  if they rely on ordered output, but that's a separate concern).

### Minor (`schema_version` bumped; date string updated)

No saved-data migration required *if* the change has been empirically
verified to accept existing saved data.

- Tightening a constraint that all existing saved data already
  satisfies. The verification step (a `model_validate` pass over
  representative saved runs) is the gate — record the saved-run
  paths you verified against in the changelog entry.
- Adding a new required field whose value can be filled by a
  defaulting shim (e.g. an `@field_validator(mode='before')` that
  populates the field if missing from the input dict).
- Renaming a Literal/Enum value where the change is reversible by a
  defaulting shim that maps the old name to the new.

### Major (`schema_version` bumped; date string updated; migration script required)

Saved-data migration script REQUIRED. Document the script's name and
the runs it was applied to in the changelog entry.

- Renaming a field (existing artefacts have the old key; new schema
  rejects them via `extra='forbid'`).
- Removing a field that downstream code reads.
- Removing a Literal/Enum value that appears in saved data.
- Changing a field's type incompatibly (e.g. `str → list[str]`).
- Tightening a constraint that rejects existing saved data
  (e.g. `min_length=1 → min_length=3` when some saved runs have
  shorter lists).
- Restructuring (e.g. flattening nested fields, nesting flat fields).

### When in doubt

Run `model_validate` over the artefacts in `data/runs/` against the
proposed new schema. If it raises ValidationError on ≥1 file, you're
in major-bump territory. If it passes, minor at most. Empirical
beats theoretical here.

## Changelog format

Each entry has the structure:

    ## YYYY-MM-DD — short summary line

    - Bump category: patch / minor / major
    - Affected class(es): MyClass, MyOtherClass
    - schema_version: '2026-05-18' → '2026-06-15'   (omit if patch)
    - Migration: script path, or 'none required'
    - Verified against: list of saved-run paths spot-checked
    - Why: one sentence

## History

### 2026-05-18 — initial consolidation (BleakHouse-gfn2)

- **Bump category**: structural reorganisation; no schema semantics
  changed. All `schema_version` values are baseline `'2026-05-18'`.
- **Affected classes**: all 13 LLM-bound classes — `FieldReportEnrichment`,
  `ParagraphEnrichment`, `ChapterEnrichmentResult`, `SegmentTemplate`,
  `SegmentDesignResult`, `SentenceType` (enum), `Utterance`, `Turn`,
  `EpisodeSegment`, `PreInterviewResponse`, `HostQuestion`, `HostBrief`,
  `CuratedAssignment`, `CurationResult`.
- **Migration**: none required. The classes moved files but their
  field shape is identical to what was in
  `enrichment/schemas.py` / `enrichment/podcast_types.py` /
  `enrichment/design_segments.py` / `enrichment/embedding_podcast.py`
  before the move.
- **Verified against**:
  `data/runs/mmar_trn_alternatives_hostprep/phase3_episode.json`
  (7 segments / 112 turns / 545 utterances) — clean `PodcastEpisode.model_validate`.
- **Why**: schema layout was previously scattered across four files
  with inconsistent strictness postures (three different patterns
  for `additionalProperties: false` alone). BleakHouse-vyo4 (closed
  same day) unified the strictness; this work moved everything to
  one well-named file as the prerequisite for treating future schema
  changes as breaking API changes per
  `docs/structured_recommendations.md`.

### Earlier history (pre-consolidation)

Pre-2026-05-18 schema changes lived in the file commit history of
`enrichment/podcast_types.py` and `enrichment/schemas.py` — see
`git log` on those paths for the audit trail before the move.

Notable pre-consolidation changes (for context):

- **2026-05-18** — BleakHouse-vyo4: every LLM-bound class given
  `model_config = ConfigDict(extra='forbid')`; `_StrictBase` deleted;
  seam-side `_strictify_for_openai` walker deleted.
- **2026-05-18** — BleakHouse host_prep two-tier-schema work:
  `PreInterviewResponse` / `HostQuestion` / `HostBrief` got
  `min_length=1, max_length=4` on every list field, plus
  `HostBrief.questions` special-cased to `min_length=3, max_length=4`;
  `@field_validator(mode='before')` coercers added to pad/truncate
  Anthropic responses that violate the schema.
- **Earlier** — see `docs/structured_output_review.html` for the
  empirical findings that drove provider-specific decisions
  (Anthropic schema subset, Qwen empty-list bias, etc.).
