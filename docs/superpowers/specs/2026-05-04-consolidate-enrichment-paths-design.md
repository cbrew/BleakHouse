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

After reconciliation, run the equivalence heuristic (Phase 3 sub-step) on a single chapter as a sanity check. **Do not** treat the heuristic as a pass/fail gate; report results to the user and resolve outliers together.

### Phase 3 — Measure (controlled experiment)

**Test corpus**: an existing novel that already has a known-good `passages_contextual.json` (e.g., `bleak_house`). Pick 5-10 chapters as the slice; run both paths on the same input.

**Measurements** (per path, per run, twice):

- Total cost (USD): input tokens × input rate + output tokens × output rate, with cache-hit accounting for C and batch discount for D.
- Wall-clock seconds.
- Cache hit rate (C only).
- Batch processing time end-to-end (D only — submit to result-available).
- Output equivalence vs the known-good baseline, via the three-check heuristic (below).

**Equivalence heuristic** — three checks. **Reported as data, not a verdict**; the user reads the numbers and decides whether to call it equivalent or dig into outliers:

1. **Schema match** — same JSON shape, same fields populated, same types.
2. **Length within ±20% per passage** — both responses for the same input passage have similar text length.
3. **Cosine similarity ≥ 0.9** on a small embedding model between C's response and D's response per passage, averaged across N=10 sample passages. Sanity-check the threshold by running C against itself in two independent runs and confirming most pairs land ≥ 0.95; if self-similarity is lower, raise the cross-path threshold accordingly.

**Output**: a markdown table summarising both paths side-by-side (cost, wall-clock, cache hit rate, equivalence-check medians/min/max).

### Phase 4 — Decide + delete

**Decision rule** (in priority order):

1. **Quality first**: if the equivalence heuristic shows one path's output is demonstrably better against the baseline, that wins.
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

Done when all four pass:

1. Pick a fresh novel not yet in `data/novels/` — small one if available (~50k-word novella) to keep wall-clock manageable.
2. Run `bash scripts/add_novel.sh <key>` from clean state.
3. Confirm:
   - `data/novels/<key>/passages_enriched.json` exists and has expected shape
   - `data/novels/<key>/passages_contextual.json` exists and has expected shape
   - `dvc commit` + `dvc push` succeeds (the produced files enter DVC cleanly)
4. One downstream consumer works: pick a `bh_*` run config, point at the new novel, run `enrichment/run_pipeline.py` for Phase 0-2; confirm `phase2_plan.json` is generated.

If any fail: drop into debugging mode; the failure is a real signal that the new canonical path has a gap.

## Risks

**R1. Audit misses a difference between C and D.** The measurement comparison would be invalid (we'd attribute drift to fundamentals when it's actually a missed prompt diff). Mitigation: the post-reconcile equivalence sanity check (Phase 2 end) catches gross misses; outliers in the cosine-similarity numbers flag specific passages to investigate.

**R2. The known-good baseline (existing `passages_contextual.json`) was itself produced by one of the paths**, so comparing both paths against it isn't fully neutral — we'd implicitly bias toward the producing path. Mitigation: record which path produced the baseline; if it's C, the cosine numbers will likely look better for C; we factor this into the read of the data, not the heuristic itself.

**R3. Model snapshot drift.** Anthropic occasionally updates models behind a stable id. A measurement done today may not generalise to a measurement done in a month. Mitigation: capture the exact model id and timestamp in the measurement output; document that the decision is calibrated to a specific snapshot.

**R4. Collapse of `submit/collect` modules deferred.** If we later collapse into one module with subcommands, we'd have to rename again. Mitigation: explicitly note the deferral and the naming-only nature of the rename in this phase; the decision can be revisited freely without invalidating the consolidation.

**R5. The "small novella" required for Phase 6 verification might not exist** in the repo's domain (Victorian novels tend toward door-stoppers). Mitigation: if no small novel is available, run on chapter-bounded slices of an existing one and document that.

## Out of scope

- Cost optimisation of paths beyond C-vs-D (e.g., switching to a different model). Stay focused on consolidation.
- Schema changes to `passages_enriched.json` or `passages_contextual.json`. Whatever the surviving path produces today is what the canonical path produces.
- Refactoring downstream consumers (anything that reads these JSONs). They keep their current contract.
- Per-novel data migrations. Existing novels' `passages_contextual.json` files stay as-is; the canonical path applies to new novels onboarded after consolidation lands.

## Acceptance criteria

(a) One contexts path lives in the repo, the other deleted; (b) `CLAUDE.md` documents the canonical "add a novel" command as `bash scripts/add_novel.sh <key>`; (c) `dvc.yaml` references only the surviving stage (note: at audit time, none of the four paths are referenced in `dvc.yaml` — this criterion is automatically satisfied if it remains so post-consolidation); (d) `test_single.py` is either deleted or comment-tagged as debug-only; (e) end-to-end verification on a fresh novel passes.
