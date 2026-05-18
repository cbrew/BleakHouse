# Prompt change log — `enrichment/llm/*_prompts.py`

This file is the version log for every prompt template used in
a structured-output LLM call in BleakHouse.

**Treat prompt changes as breaking API changes.** A prompt is part
of the contract between BleakHouse and the LLM and shapes the
outputs that go into saved-run artefacts. Every edit to a
`*_prompts.py` file should be reflected here, and the corresponding
`*_VERSION` constant should be bumped per the rules below.

Sibling discipline: `docs/schemas_changelog.md` governs Pydantic
schemas. Same spirit, different bump-test specifics.

## Bump rules

The bump category determines whether a per-run version bump is
required and whether saved-run outputs would still be reproducible
from the new prompt.

### Patch (`*_VERSION` unchanged or date-only refresh)

No per-run version bump required. Empirically: re-running the same
inputs through the new prompt should produce indistinguishably-similar
outputs.

- Whitespace, line-break, or punctuation tidying inside a sentence.
- Typo fixes.
- Comment-only edits (the prose surrounding the prompt constant in
  the .py file).
- Renumbering a list whose items didn't change.

### Minor (`*_VERSION` bumped; date string updated)

Output drift expected to be small but real. Worth recording but no
migration script.

- Reordering bullet points within a section.
- Wording clarification ("draw out their take" → "draw out their
  strongest take") where the operational meaning is unchanged.
- Format-slot rename (e.g. `{novel_title}` → `{title}`) — note that
  this also requires updating every caller in the same commit; treat
  as minor for the prompt itself if the substitution is identical.

### Major (`*_VERSION` bumped; date string updated; record-on-replay implications)

The outputs of new runs against the new prompt are not directly
comparable with outputs from old runs against the old prompt. Saved
runs should record the prompt version used; conformance suites
should be re-baselined.

- Adding or removing a numbered constraint.
- Changing a count (e.g. "3-5 questions" → "5-8 questions").
- Adding or removing a section of the prompt.
- Re-writing the framing (the "You are a podcast host..." sentence
  and what follows).
- Changing the output-format instructions (the JSON shape, the
  per-utterance schema description block in `generation_prompts.SYSTEM_PROMPT`).
- Adding a new format-slot that the caller must populate.
- Changing the tone or persona instructions in a way that would
  shift the model's response register.

### When in doubt

The empirical test: pick a small fixture (3-5 representative
inputs), run them through the old and new prompt with the same
model + seed where applicable, and diff the outputs. If a
non-trivial fraction (more than ~10% of diff lines) shifted, it's
a major bump. If the diffs are localised typos / whitespace,
patch is fine.

## Changelog format

Each entry has the structure:

    ## YYYY-MM-DD — short summary line

    - Bump category: patch / minor / major
    - Affected prompt(s): host_prep_prompts.INTERVIEW_SYSTEM, ...
    - *_VERSION: '2026-05-18' → '2026-06-15'   (omit if patch)
    - Fixture diffed: short note on what was re-run
    - Why: one sentence

## History

### 2026-05-18 — initial consolidation (BleakHouse-mz2g)

- **Bump category**: structural reorganisation; no prompt content
  changed. All `*_VERSION` values are baseline `'2026-05-18'`.
- **Affected prompts**: every LLM-bound prompt in the codebase:
  - **host_prep_prompts**: `INTERVIEW_SYSTEM`, `INTERVIEW_USER`,
    `INTERVIEW_TOOLS_ADDENDUM`, `INTERVIEW_STRUCTURED_PARSE_SYSTEM`,
    `QUESTION_PLANNING_SYSTEM`, `QUESTION_PLANNING_USER`,
    `LISTENER_PICK_SYSTEM`. Plus `QUESTION_COUNT_LONG/SHORT` count
    constants.
  - **design_segments_prompts**: `SYSTEM_PROMPT_V1`,
    `SYSTEM_PROMPT_V2`, `SYSTEM_PROMPT_V3`. Plus `SEGMENT_COUNT_*`
    and `TOTAL_PASSAGES_*` substitution constants.
  - **generation_prompts**: `SYSTEM_PROMPT`, `SEGMENT_LENGTH_LONG`,
    `SEGMENT_LENGTH_SHORT`, `QUOTE_SOURCING_V2`.
  - **curation_prompts**: `CURATION_SYSTEM_PROMPT`.
- **Fixture diffed**: not applicable — the move was a literal
  copy/paste from the source files (host_prep.py, design_segments.py,
  generate_podcast.py, embedding_podcast.py) into the new files. No
  whitespace or content changes. The original files now import the
  same string objects under the same `_INTERVIEW_SYSTEM` etc. names.
- **Why**: prompts were inline in their call sites with no version
  tracking. Per `docs/structured_recommendations.md` and the
  BleakHouse-pd1u epic (version-pinning propagation), prompts need
  to be version-pinned alongside schemas. Consolidating into
  per-cluster `enrichment/llm/*_prompts.py` files makes each prompt
  grep-able and gives it a sibling `*_VERSION` constant.

### Earlier history (pre-consolidation)

Pre-2026-05-18 prompt changes lived in the file commit history of
the four source files (host_prep.py, design_segments.py,
generate_podcast.py, embedding_podcast.py). See `git log` on those
paths for the audit trail before the move.

One pre-consolidation change worth noting:

- **2026-05-18** — `_QUESTION_COUNT_LONG` changed from `"3–5"` to
  `"3–4"` to match the `HostBrief.questions` `max_length=4` schema
  cap (BleakHouse-vyo4, the host_prep two-tier strategy). Major
  bump under the new rules, but predates the per-prompt
  `*_VERSION` constants.
