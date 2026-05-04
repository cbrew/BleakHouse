# Consolidate enrichment paths into one canonical pipeline

**Status**: design approved 2026-05-04. Ready for implementation plan.
**Author**: brainstormed with Claude Opus 4.7 in BleakHouse session 2026-05-04.
**Resolves**: BleakHouse-1kg7.

## Problem

Two paths produce `passages_contextual.json` per novel:

- **C** = `enrichment/generate_contexts.py` — sync, prompt-cached on the chapter prefix; ~90% input-token savings on cache hits but 1-2 hours wall-clock per novel.
- **D** = `enrichment/submit_context_batch.py` + `enrichment/collect_context_batch.py` — Anthropic Batch API; 50% input-token discount but caching is best-effort. Faster wall-clock.

When a new novel needs onboarding, there's no rule for which to pick. Both produce the same artefact. A reader of the repo can't tell which is canonical. This duplication invites drift: each maintenance touch on one path doesn't necessarily land on the other.

Two adjacent paths that aren't duplicates but share the confusion:

- **A** = `enrichment/submit_batch.py` + `enrichment/collect_results.py` — produces `passages_enriched.json`. Not duplicated, but the file names ("submit_batch", "collect_results") don't say what they batch or collect — they could plausibly belong to either A or D.
- **B** = `enrichment/test_single.py` — sync, single-call, documented as debug-only. Should it be deleted or clearly tagged?

## Goal

One canonical path per artefact, named for what it produces (not its API style). One shell script (`scripts/add_novel.sh <key>`) that runs the full sequence end-to-end. Decision between C and D made empirically on aligned inputs (apples-to-apples comparison; reconcile any drift before measuring).

## Phases

### Phase 1 — Alignment audit

Walk C and D code paths in parallel. Produce a structured drift inventory at `docs/superpowers/notes/2026-05-04-context-paths-audit.md`. Categories:

- System prompt (the cached chapter-context prefix in C; the equivalent in D's batch request)
- User prompt (the per-passage instruction)
- Model id (both should be `claude-haiku-4-5-20251001`; flag if drifted)
- max_tokens, temperature, other inference params
- Output schema (Pydantic model or JSON schema; if no schema, look at how the response is parsed)
- Retry / error handling
- Chunking (chapter-by-chapter vs one batch)
- Output format (both write the same `passages_contextual.json` shape; spot-check a real example)
- Metrics / logging (C is instrumented per BleakHouse-ybbn; D may not be)

For each category: what C does, what D does, whether they match, one-line note.

### Phase 2 — Reconcile (interactive)

For each substantive difference from Phase 1, surface to the user: "C says X, D says Y. Reconcile to which?" The user decides per-item — sometimes from knowledge, sometimes after digging deeper into a specific passage's behaviour. Once decided, port the chosen version into the other path so both are semantically equivalent.

After reconciliation, run the equivalence heuristic (Phase 3 sub-step) on a single chapter as a sanity check — N (the sample size) scales to the number of passages in that chapter (likely 5-20 in practice; smaller than Phase 3's N=10 across the full novel only if the chapter is unusually short). **Do not** treat the heuristic as a pass/fail gate; report results to the user and resolve outliers together.

### Phase 3 — Measure (controlled experiment)

**Test novel**: Dickens' *Oliver Twist* (key: `oliver_twist`). ~155k words, mid-Victorian three-volume novel — same general shape as the existing Dickens corpus this repo is built on, so the measurement is calibrated against the kind of text the pipeline will see most. Not yet onboarded; the measurement work onboards it as a side effect.

**Outputs kept distinct.** Both paths run on the same input but write to separate filenames so neither overwrites the other and the comparison can be done after the fact:

- C writes `data/novels/oliver_twist/passages_contextual.C.json`
- D writes `data/novels/oliver_twist/passages_contextual.D.json`

After measurement and decision, the winning path's file is renamed to the canonical `data/novels/oliver_twist/passages_contextual.json` (and the loser's deleted). Phase 6 then onboards a *different* novel (*Mrs. Dalloway*) through the consolidated pipeline, so verification isn't biased toward the calibration corpus.

**Measurements** (each path runs twice on the full novel; "per run, twice" lets us separate noise from real differences — e.g., batch wall-clock varies a lot with Anthropic queue depth):

- Total cost (USD): input tokens × input rate + output tokens × output rate, with cache-hit accounting for C and batch discount for D.
- Wall-clock seconds.
- Cache hit rate (C only).
- Batch processing time end-to-end (D only — submit to result-available).
- Output equivalence — the three-check heuristic (below) compares C's output directly against D's output (no separate baseline). Both should match the schema; their per-passage outputs should be similar in length and meaning.

**Equivalence heuristic** — three checks comparing C's `passages_contextual.C.json` against D's `passages_contextual.D.json`. **Reported as data, not a verdict**; the user reads the numbers and decides whether to call it equivalent or dig into outliers:

1. **Schema match** — same JSON shape, same fields populated, same types.
2. **Length within ±20% per passage** — both responses for the same input passage have similar text length.
3. **Cosine similarity ≥ 0.9** on a small embedding model between C's response and D's response per passage, averaged across N=10 sample passages. Sanity-check the threshold by running C against itself in two independent runs and confirming most pairs land ≥ 0.95; if self-similarity is lower, raise the cross-path threshold accordingly.

**Output**: a markdown table summarising both paths side-by-side (cost, wall-clock, cache hit rate, equivalence-check medians/min/max).

### Phase 4 — Decide + delete

**Decision rule** (in priority order):

1. **Quality first**: if the equivalence heuristic surfaces real differences (e.g., one path's outputs are systematically shorter, or schema-violating, or low-cosine-similarity for a non-trivial subset of passages), the user reads the data and may declare one path the quality winner. With no baseline, "quality" here is a judgement on the comparison output, not a numeric pass/fail.
2. **Wall-clock second**: faster onboarding for new novels matters because it gates throughput.
3. **Cost as tiebreaker only**, weighted by amortisation-per-script, not raw per-novel. Enrichment runs once per novel and feeds N panels × M personas × K script versions of downstream output (typically dozens of episodes). A 2× cost difference at the enrichment layer becomes fractions of a cent per downstream episode. Quality and wall-clock matter more.

Once decided: delete the loser path. Rename the survivor to `enrichment/run_passage_contexts.py` (matching the project's `run_pipeline.py` / `run_novel.py` naming).

### Phase 5 — Sweep paths A & B

**Path A audit**: quick code read of `submit_batch.py` + `collect_results.py`. Flag any drift from current best practice (outdated model id, missing retry, etc.). One-paragraph note in the audit doc. Probably no action; if there is, fix in this phase.

**Path A renames** (regardless of audit findings):

- `enrichment/submit_batch.py` → `enrichment/submit_passages_enriched.py`
- `enrichment/collect_results.py` → `enrichment/collect_passages_enriched.py`

(Whether to collapse these into a single `run_passages_enriched.py` with `--submit` / `--collect` subcommands is **deferred** — decide during implementation based on which feels right after the audit.)

**Path B fate**: decide during this phase whether `test_single.py` is well-covered by the retained passage-enriched path (delete it) or still useful as a debug tool (rename to `enrichment/debug_passage_enrichment.py` and add a clear "debug only — not a production path" docstring). Default leaning: delete; only keep if there's a real debug workflow it uniquely serves.

### Phase 6 — Workflow consolidation

`scripts/add_novel.sh <novel_key>`:

```
download → chapter → submit_passages_enriched → wait → collect_passages_enriched
       → run_passage_contexts → cluster → build_manifest
```

- Each step fail-loud (`set -e`).
- Documents wall-clock expectations (batch steps each 30 min – a few hours).
- Idempotent where possible (re-running a finished step skips it).

Doc updates:

- `CLAUDE.md`: replace any "to add a novel, run X then Y then Z" prose with `bash scripts/add_novel.sh <key>`.
- `docs/pipeline.md`: refresh the phase-0 enrichment section.
- `docs/llm_call_sites.md`: drop the deleted path's entry, rename the survivor's entry, drop `test_single`'s entry if deleted.

## Verification (acceptance gates)

The verification corpus is Virginia Woolf's *Mrs. Dalloway* (key: `mrs_dalloway`) — a different novel from the calibration corpus (Phase 3 used *Oliver Twist*). Mrs. Dalloway is ~64k words, modernist, single-day narrative — different era and structure from *Oliver Twist*, so the verification genuinely exercises whether the consolidated pipeline generalises beyond the calibration novel.

Done when all four pass:

1. `bash scripts/add_novel.sh mrs_dalloway` runs from a clean state (no `data/novels/mrs_dalloway/` directory at start) and exits 0.
2. Confirm the canonical artefacts now exist:
   - `data/novels/mrs_dalloway/passages_enriched.json` with expected shape
   - `data/novels/mrs_dalloway/passages_contextual.json` with expected shape
3. `dvc commit` + `dvc push` succeeds (the produced files enter DVC cleanly).
4. One downstream consumer works: pick a `bh_*` run config, point at *Mrs. Dalloway* (`mdal_trn_literary` or similar new run id), run `enrichment/run_pipeline.py` for Phase 0-2; confirm `phase2_plan.json` is generated.

If any fail: drop into debugging mode; the failure is a real signal that either the consolidation has a gap or the calibration assumed something *Oliver Twist*-specific.

## Risks

**R1. Audit misses a difference between C and D.** The measurement comparison would be invalid (we'd attribute drift to fundamentals when it's actually a missed prompt diff). Mitigation: the post-reconcile equivalence sanity check (Phase 2 end) catches gross misses; outliers in the cosine-similarity numbers flag specific passages to investigate.

**R2. Oliver Twist is one novel; calibration may not generalise.** Even though it's a typical Victorian three-volume novel that matches the existing corpus shape, a single calibration run might miss edge cases (e.g., very short chapters, unusually-long passages). Mitigation: Phase 6 verifies independently on *Mrs. Dalloway* — a different era, different chapter structure, different prose density. If the consolidated path works for both, the calibration probably generalised. If Phase 6 fails on *Mrs. Dalloway*, that's a real signal to re-examine the calibration assumptions.

**R3. Model snapshot drift.** Anthropic occasionally updates models behind a stable id. A measurement done today may not generalise to a measurement done in a month. Mitigation: capture the exact model id and timestamp in the measurement output; document that the decision is calibrated to a specific snapshot.

**R4. Collapse of `submit/collect` modules deferred.** If we later collapse into one module with subcommands, we'd have to rename again. Mitigation: explicitly note the deferral and the naming-only nature of the rename in this phase; the decision can be revisited freely without invalidating the consolidation.

**R5. Two-novel cost.** Both *Oliver Twist* and *Mrs. Dalloway* will be onboarded as part of this work, doubling the API spend over a single-corpus design. Mitigation: each novel is small enough that the absolute cost is bounded (under $20 expected); we treat the spend as the cost of an honest verification, not waste. The two novels also become real onboarded corpora the project can use afterward.

## Out of scope

- Cost optimisation of paths beyond C-vs-D (e.g., switching to a different model). Stay focused on consolidation.
- Schema changes to `passages_enriched.json` or `passages_contextual.json`. Whatever the surviving path produces today is what the canonical path produces.
- Refactoring downstream consumers (anything that reads these JSONs). They keep their current contract.
- Per-novel data migrations. Existing novels' `passages_contextual.json` files stay as-is; the canonical path applies to new novels onboarded after consolidation lands.

## Acceptance criteria

(a) One contexts path lives in the repo, the other deleted; (b) `CLAUDE.md` documents the canonical "add a novel" command as `bash scripts/add_novel.sh <key>`; (c) `dvc.yaml` references only the surviving stage (note: at audit time, none of the four paths are referenced in `dvc.yaml` — this criterion is automatically satisfied if it remains so post-consolidation); (d) `test_single.py` is either deleted or comment-tagged as debug-only; (e) end-to-end verification on a fresh novel passes.
