# Context paths audit — C vs D (2026-05-04)

**Phase 1 of BleakHouse-1kg7.** Read of `enrichment/generate_contexts.py`
(C, 232 lines), `enrichment/submit_context_batch.py` (D-submit, 148 lines),
`enrichment/collect_context_batch.py` (D-collect, 116 lines), and the shared
`enrichment/context_prompt.py` (38 lines). Both C and D import
`build_context_messages` from `context_prompt`, so prompt-text drift is
impossible by construction. Most drift is in operational details.

## Summary

- **Substantive differences: 1** (NOVEL_KEYS list — C is 10 entries behind D).
- **Operational differences: 6** (resume flag, chunking, custom-id format, output sidecars, instrumentation, logging).
- **Stylistic differences: 0** (both use the same logger/format/style).

## Category 1: System prompt

- **C**: calls `build_context_messages(chapter_text, passage["text"])` from `context_prompt.py`. Returns a system block list `[TextBlockParam(type="text", text=f"<document>\n{chapter_text}\n</document>", cache_control={"type": "ephemeral"})]`.
- **D**: calls the identical `build_context_messages(chapter_text, passage["text"])`.
- **Match**: yes (by construction — same shared function).
- **Note**: cache_control is set on both paths. Whether the cache actually hits is a runtime question (sync sequential = hits guaranteed; batch = best-effort).

## Category 2: User prompt

- **C**: `build_context_messages` returns the same user message: `f"Here is the chunk we want to situate within this chapter of {cfg.title} by {cfg.author}: <chunk>{chunk_text}</chunk> Please give a short succinct context to situate this chunk..."`.
- **D**: identical (same shared function).
- **Match**: yes (by construction).

## Category 3: Model id

- **C** (line 46): `MODEL = "claude-haiku-4-5-20251001"`.
- **D-submit** (line 30): `MODEL = "claude-haiku-4-5-20251001"`.
- **Match**: yes.

## Category 4: max_tokens, temperature, params

- **C** (lines 167-172): `max_tokens=MAX_TOKENS` (300), no `temperature` set (Anthropic default = 1.0).
- **D-submit** (lines 75-80): `max_tokens=MAX_TOKENS` (300), no `temperature` set.
- **Match**: yes.

## Category 5: Output schema / parsing

- **C** (lines 175-177): `block = response.content[0]; assert block.type == "text"; contexts[pid] = block.text`.
- **D-collect** (lines 81-87): `result.result.type == "succeeded"`, then `msg = result.result.message; if msg.content and msg.content[0].type == "text": contexts[pid] = msg.content[0].text`.
- **Match**: equivalent extraction logic; D-collect adds an explicit success check (batch results can have `errored`/`expired`/`canceled` types, sync responses cannot fail silently the same way). D's check is appropriate for the batch context.
- **Note**: D-collect checks `if msg.content` (handles the edge case of an empty content list); C uses `assert`. C's assert is OK because sync calls don't return empty-content successes in practice.

## Category 6: Retry / error handling

- **C**: no explicit retry. Relies on the Anthropic SDK's default retries. Failure on a single passage would abort the chapter loop (uncaught exception). `--resume` lets you re-run after a crash and pick up from the last saved chapter.
- **D-submit**: no retry; one batch creation call. Failure aborts.
- **D-collect**: no retry on `batches.retrieve` or `batches.results`. Failure aborts.
- **Match**: roughly equivalent — both rely on SDK defaults. C's `--resume` provides recovery via state-on-disk; D's recovery is "the batch_id in the manifest still works, re-run collect."

## Category 7: Chunking

- **C** (line 138): iterates `for chapter_id in sorted(by_chapter, key=_chapter_sort_key):`, then `for i, passage in enumerate(passages):`. **Sequential within a chapter so the cache stays hot.**
- **D-submit** (lines 61-82): iterates `for chapter_id in sorted(by_chapter):`, builds a single flat `requests` list spanning all chapters, submits via `batches.create(requests=requests)`. Concurrent processing inside Anthropic — cache is best-effort.
- **Match**: no — this is the fundamental architectural difference between the paths. Not drift, by design.
- **Note**: C uses `_chapter_sort_key` (handles `cP`, `c1..c67`, `F2`, `F3`); D uses plain `sorted()` (would order `c1, c10, c11, ..., c2` lexicographically, but order doesn't matter for batch submission so this is harmless).

## Category 8: Output format

- **C** writes:
  - `passages_contextual.json` (canonical: list of passages with `context` field added)
  - `contexts.json` (intermediate: dict of `passage_id → context_text` for resume)
  - `passage_enrichment_timings.json` (sidecar from `Recorder`)
- **D-submit** writes:
  - `context_batch_manifest.json` (batch_id, id_map, status, etc.)
- **D-collect** writes:
  - `passages_contextual.json` (canonical: same shape as C's)
  - `contexts.json` (intermediate, same shape as C's)
  - updates `context_batch_manifest.json` with `status=collected` and `succeeded` count
- **Match**: canonical output (`passages_contextual.json`) shape is **identical** — both produce a list of passage dicts with a `context: str` field appended.
- **Drift**: C produces a timings sidecar (cost/time data). D produces a batch-manifest sidecar (batch_id, id_map). Neither is needed by downstream consumers; both are operational metadata.

## Category 9: Metrics / logging

- **C**:
  - Imports `from enrichment.timing import Recorder, time_model`.
  - Wraps every API call: `time_model(recorder, f"context {pid}", lambda: client.messages.create(...))` — records token counts, cost, wall-clock per call.
  - Writes `passage_enrichment_timings.json` after each chapter.
  - Logs cache_create / cache_read for the first 2 passages of each chapter (sanity-checks the cache is hot).
- **D-submit**: no timing instrumentation. Logs only `"Built %d context requests"` and `"Batch %s submitted (%d requests)"`.
- **D-collect**: no timing instrumentation. Logs the batch's `succeeded`/`errored` counts and the merge progress.
- **Match**: no. **C is instrumented (BleakHouse-ybbn); D is not.**
- **Implication for measurement**: extracting D's cost requires reading `result.result.message.usage` from each batch result during collection (the data is available; D-collect just doesn't aggregate it).

## Category 10: Novel-key handling

- **C** (lines 39-44): `NOVEL_KEYS = ["our_mutual_friend", "mill_on_the_floss", "north_and_south", "passage_to_india"]` — 4 entries.
- **D-submit** (lines 33-48): `NOVEL_KEYS = [...same 4..., "hard_times", "middlemarch", "daniel_deronda", "david_copperfield", "cranford", "no_name", "new_grub_street", "odd_women", "miss_marjoribanks", "hester"]` — 14 entries.
- **D-collect** (lines 20-35): same 14-entry list as D-submit.
- **Match**: no. **C is 10 novels behind.** Every novel onboarded since the original 4 has been done via D (since C would reject `--novel hester` etc. via `argparse`'s `choices` validation).
- **Note**: C also has an optional fallback path (no `--novel` → top-level `data/passages_enriched.json` etc.) that D does not. That fallback is legacy from when this was a single-novel BleakHouse repo; safe to drop in reconciliation.

## Path A audit

(reserved for Task 6 — see Phase 5 of the spec)

## Reconciled (Task 2)

| # | Item | Decision | Commit |
|---|------|----------|--------|
| 1 | `NOVEL_KEYS` list (C had 4, D had 14) | Drop hardcoded lists from both; import the canonical `NOVEL_IDS` frozenset from `enrichment/axes.py` (16 entries today, derived from the `NOVELS` tuple — single source of truth for new novel keys). | `c87f74c5` |
| 2 | `--resume` flag (C only) | Drop `--resume` from C entirely. Both paths now use the same idempotency model: skip if the terminal output already exists. Drop the `contexts.json` intermediate file from C (was only used to support resume) and from D-collect's partial-merge logic (overkill for the one-batch-per-novel use case). Crash recovery: delete the output file. | `31fd5e21` |
| 3 | Chunking (sequential-by-chapter vs flat batch) | Architectural axis being measured in Phase 3. Not reconcilable by design. | — |
| 4 | Custom-id format (passage_ids vs `ctx-s{seq}` + id_map) | Deferred to post-Phase-4. If D wins, simplify by using `custom_id=f"ctx-{passage_id}"` directly so Anthropic batch errors and the manifest are self-describing (no id_map indirection). If C wins, the question is moot. | — (deferred) |
| 5 | Output sidecars (C: timings; D: batch manifest) | No reconcile needed; both survive on the winner. | — |
| 6 | Instrumentation (C wired to `Recorder`; D none) | Will be addressed in Task 3/4 when building `scripts/compare_context_paths.py` — the harness needs equal cost-tracking on both paths (read D's per-request `usage` from the batch results during collection). | — (Task 3) |
| 7 | Logging detail | Cosmetic, no reconcile. | — |

**Outcome**: substantive drift fully reconciled; operational drift either reconciled (1, 2) or deliberately preserved (3, 5, 7) or deferred (4) until the winner is known. Phase 3 measurement can proceed with confidence that the comparison reflects the architectural axis (cache vs batch), not stale prompts or list mismatches.

## Phase 3 measurement

(reserved for Task 4)

## Phase 6 verification

(reserved for Task 9)
