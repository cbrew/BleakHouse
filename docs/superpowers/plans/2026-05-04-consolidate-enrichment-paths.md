# Consolidate Enrichment Paths Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the duplicate C/D paths producing `passages_contextual.json` with one canonical path, decided empirically against an aligned (apples-to-apples) comparison on Oliver Twist; verify the consolidated pipeline on Mrs. Dalloway as a fresh-novel onboarding test.

**Architecture:** Phase-based execution mirroring the spec. Heavy interactive checkpoints — Phase 2 (per-difference reconciliation), Phase 3 (read measurements together), Phase 4 (winner decision). Both novels become real onboarded corpora as a side effect.

**Tech Stack:** Python 3.13, Anthropic SDK (Messages API + Batch API), uv, pydantic, sqlite3 (existing experiments DB), bash (deploy_demo / add_novel scripts).

**Spec:** `docs/superpowers/specs/2026-05-04-consolidate-enrichment-paths-design.md`. **Resolves:** BleakHouse-1kg7.

---

## Files

### Created
- `docs/superpowers/notes/2026-05-04-context-paths-audit.md` — drift inventory + Path A audit + measurement results table
- `scripts/compare_context_paths.py` — runs both paths on a novel, captures metrics, runs equivalence heuristic, emits markdown table
- `scripts/add_novel.sh` — end-to-end novel onboarding (idempotent)
- `enrichment/run_passage_contexts.py` — survivor of C/D, renamed
- `enrichment/submit_passages_enriched.py` — renamed from submit_batch.py
- `enrichment/collect_passages_enriched.py` — renamed from collect_results.py

### Deleted
- Either `enrichment/generate_contexts.py` (if D wins) **or** `enrichment/submit_context_batch.py` + `enrichment/collect_context_batch.py` (if C wins). Decided in Task 5.
- `enrichment/test_single.py` — if Task 6 finds it has no unique debug role.

### Modified
- `CLAUDE.md` — replace ad-hoc novel-onboarding instructions with `bash scripts/add_novel.sh <key>`
- `docs/pipeline.md` — refresh phase-0 enrichment section with the canonical path
- `docs/llm_call_sites.md` — drop deleted entries, update path names

---

## Task 1: Phase 1 — Alignment audit of C and D

**Goal:** Produce a structured drift inventory between paths C and D so Phase 2 has concrete items to reconcile.

**Files:**
- Create: `docs/superpowers/notes/2026-05-04-context-paths-audit.md`
- Read (do not modify): `enrichment/generate_contexts.py`, `enrichment/submit_context_batch.py`, `enrichment/collect_context_batch.py`, `enrichment/context_prompt.py` (the shared prompt-building module both paths use), `enrichment/submit_batch.py` (path C imports `format_chapter_text` from here).

- [ ] **Step 1: Read both paths end-to-end**

```bash
wc -l enrichment/generate_contexts.py enrichment/submit_context_batch.py enrichment/collect_context_batch.py enrichment/context_prompt.py
cat enrichment/context_prompt.py  # the shared prompt builder
```

Note: both paths import `build_context_messages` from `enrichment/context_prompt`, so prompt-text drift is bounded — most drift will be in operational details (novel-key lists, retry, chunking, output format, instrumentation).

- [ ] **Step 2: Walk the audit categories and record findings**

Create `docs/superpowers/notes/2026-05-04-context-paths-audit.md` with this structure:

```markdown
# Context paths audit — C vs D (2026-05-04)

## Summary
- N substantive differences, M operational, K stylistic.

## Category 1: System prompt
- C: <what generate_contexts.py constructs via build_context_messages>
- D: <what submit_context_batch.py constructs via build_context_messages>
- Match: yes/no
- Note: if both call the same function, drift is impossible by construction; record that.

## Category 2: User prompt
(same shape)

## Category 3: Model id
(same shape)

## Category 4: max_tokens, temperature, params
(same shape)

## Category 5: Output schema / parsing
(same shape — note: C parses `response.content[0].text`; D parses each batch result's text per the Anthropic batch-message-result schema)

## Category 6: Retry / error handling
(same shape — list any try/except, retry helpers, partial-failure handling)

## Category 7: Chunking
(same shape — C iterates chapters then passages; D builds one big request list)

## Category 8: Output format
(same shape — what file does each write? what JSON structure? `passages_contextual.json` or different?)

## Category 9: Metrics / logging
(same shape — `enrichment.timing.Recorder`? sidecar files written? log lines?)

## Category 10: Novel-key handling
(same shape — both modules have `NOVEL_KEYS` lists; record which is currently more current)

## Path A audit (placeholder)
(reserved for Task 6 — leave empty for now)
```

Fill each section with specifics, not summaries. If two values match by construction (shared function), say so explicitly — the comparison is the value.

- [ ] **Step 3: Commit the audit**

```bash
git add docs/superpowers/notes/2026-05-04-context-paths-audit.md
git commit -m "$(cat <<'EOF'
docs: alignment audit of C vs D contexts paths (Task 1)

Per-category drift inventory between enrichment/generate_contexts.py
and enrichment/submit_context_batch.py + collect_context_batch.py.
Informs Phase 2 reconciliation. Both paths share
enrichment/context_prompt.build_context_messages, so prompt-text
drift is bounded by construction; most drift is in operational
details (novel-key lists, retry, instrumentation, output format).

Phase 1 of BleakHouse-1kg7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Phase 2 — Reconcile (interactive with user)

**Goal:** For each substantive difference recorded in Task 1, apply the user's per-item decision; produce semantically-equivalent C and D.

**Files:** Likely `enrichment/generate_contexts.py`, `enrichment/submit_context_batch.py`, `enrichment/collect_context_batch.py`, possibly `enrichment/context_prompt.py`. Specific files depend on the audit findings.

- [ ] **Step 1: Walk the audit findings with the user**

For each substantive difference (Categories 1-10 in the audit), present:

```
Difference: <category, e.g., "novel-key list">
  C says: <C's value, copied exactly from the audit>
  D says: <D's value>
  
  Reconcile to which? (a) C's version, (b) D's version, (c) something new, (d) skip — operational drift, no reconcile needed
```

Wait for the user's decision. If unclear, dig deeper (e.g., "what does the missing novel key in C's list cause when called?"). **Do not guess** — the user owns each decision.

- [ ] **Step 2: Apply each decision as a small commit**

For each reconciled item, edit the relevant file(s) and commit immediately. Example:

```bash
git add enrichment/submit_context_batch.py enrichment/generate_contexts.py
git commit -m "$(cat <<'EOF'
contexts: align NOVEL_KEYS list between C and D

D had 14 novels, C had 4 (the 4 are the original supported set; D
grew to 14 as new novels were onboarded via the batch path). Aligned
both to the 14-novel list per Phase 2 reconciliation; C had been the
silent loser of every novel onboarded since 2026-04-XX.

Phase 2 of BleakHouse-1kg7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

(One commit per logical reconciliation item; not one giant commit at the end.)

- [ ] **Step 3: Quality checks after each commit**

```bash
uv run ruff check enrichment/generate_contexts.py enrichment/submit_context_batch.py enrichment/collect_context_batch.py
uv run pyright enrichment/generate_contexts.py enrichment/submit_context_batch.py enrichment/collect_context_batch.py 2>&1 | tail -3
```

Both should pass clean (or at least introduce no new errors).

- [ ] **Step 4: Update the audit doc**

After the last reconciliation, append a "## Reconciled" section to the audit doc listing each decision and the commit SHA that landed it.

```bash
git add docs/superpowers/notes/2026-05-04-context-paths-audit.md
git commit -m "docs: record reconciliation decisions in audit doc

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Phase 2 sanity check — single-chapter equivalence test

**Goal:** Confirm reconciliation succeeded by running both paths on a single chapter and reading the equivalence-heuristic output together with the user.

**Files:**
- Create: `scripts/compare_context_paths.py` (the comparison harness, also used in Task 4)

- [ ] **Step 1: Pick a sanity-check chapter**

Use `bleak_house` chapter 1 (already in the repo, contexts already exist as a known reference point). The chapter has enough passages to give the heuristic meaningful data without being expensive.

```bash
uv run python -c "
import json
p = json.load(open('data/novels/bleak_house/passages_enriched.json'))
ch1 = [x for x in p if x['chapter_id'] == 'c1']
print(f'chapter 1 has {len(ch1)} passages')"
```

- [ ] **Step 2: Write the comparison harness**

Create `scripts/compare_context_paths.py`:

```python
"""Run both contexts paths on the same chapter slice; emit metrics + heuristic.

Usage:
    uv run python scripts/compare_context_paths.py --novel bleak_house --chapters c1
    uv run python scripts/compare_context_paths.py --novel oliver_twist     # full novel
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path("data")


def _run_C(novel: str, chapters: str | None) -> tuple[float, dict]:
    """Run path C (sync + cache) and return (wall_clock_s, metrics_dict)."""
    novel_dir = DATA_DIR / "novels" / novel
    out_path = novel_dir / "passages_contextual.json"
    out_path_C = novel_dir / "passages_contextual.C.json"
    if out_path_C.exists():
        out_path_C.unlink()
    cmd = ["uv", "run", "python", "-m", "enrichment.generate_contexts", "--novel", novel]
    if chapters:
        cmd.extend(["--chapters", chapters])
    t0 = time.time()
    subprocess.run(cmd, check=True)
    elapsed = time.time() - t0
    # generate_contexts writes to passages_contextual.json; move it aside
    if out_path.exists():
        shutil.move(out_path, out_path_C)
    return elapsed, {}


def _run_D(novel: str, chapters: str | None) -> tuple[float, dict]:
    """Run path D (batch) and return (wall_clock_s, metrics_dict)."""
    novel_dir = DATA_DIR / "novels" / novel
    out_path = novel_dir / "passages_contextual.json"
    out_path_D = novel_dir / "passages_contextual.D.json"
    if out_path_D.exists():
        out_path_D.unlink()
    submit_cmd = ["uv", "run", "python", "-m", "enrichment.submit_context_batch", "--novel", novel]
    if chapters:
        submit_cmd.extend(["--chapters", chapters])
    collect_cmd = ["uv", "run", "python", "-m", "enrichment.collect_context_batch", "--novel", novel]
    t0 = time.time()
    subprocess.run(submit_cmd, check=True)
    subprocess.run(collect_cmd, check=True)
    elapsed = time.time() - t0
    if out_path.exists():
        shutil.move(out_path, out_path_D)
    return elapsed, {}


def _equivalence_heuristic(novel: str, sample_n: int = 10) -> dict:
    """Three-check heuristic: schema match, length within ±20%, cosine ≥ 0.9."""
    novel_dir = DATA_DIR / "novels" / novel
    c_path = novel_dir / "passages_contextual.C.json"
    d_path = novel_dir / "passages_contextual.D.json"
    c = json.loads(c_path.read_text())
    d = json.loads(d_path.read_text())

    # Schema check: both lists, same length, same passage_ids in same order
    if not isinstance(c, list) or not isinstance(d, list):
        return {"schema_match": False, "reason": "expected JSON arrays"}
    if len(c) != len(d):
        return {"schema_match": False, "reason": f"length mismatch: C={len(c)} D={len(d)}"}

    schema_ok = sum(
        1 for ci, di in zip(c, d, strict=True)
        if ci.get("passage_id") == di.get("passage_id") and "context" in ci and "context" in di
    )

    # Length within ±20% per passage
    length_ratios = []
    for ci, di in zip(c, d, strict=True):
        cl = len(ci.get("context", ""))
        dl = len(di.get("context", ""))
        if cl == 0 and dl == 0:
            continue
        ratio = min(cl, dl) / max(cl, dl) if max(cl, dl) > 0 else 0
        length_ratios.append(ratio)
    median_length_ratio = float(np.median(length_ratios)) if length_ratios else 0.0
    within_20pct = sum(1 for r in length_ratios if r >= 0.8)

    # Cosine similarity on a sample
    # Lazy import — only needed for cosine check.
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("all-MiniLM-L6-v2")
    sample_n_actual = min(sample_n, len(c))
    indices = np.linspace(0, len(c) - 1, sample_n_actual, dtype=int)
    cos_sims = []
    for i in indices:
        c_text = c[int(i)].get("context", "")
        d_text = d[int(i)].get("context", "")
        if not c_text or not d_text:
            continue
        ec = model.encode(c_text, convert_to_numpy=True, normalize_embeddings=True)
        ed = model.encode(d_text, convert_to_numpy=True, normalize_embeddings=True)
        cos_sims.append(float(np.dot(ec, ed)))
    median_cos = float(np.median(cos_sims)) if cos_sims else 0.0
    min_cos = float(np.min(cos_sims)) if cos_sims else 0.0

    return {
        "schema_match": schema_ok == len(c),
        "schema_pairs_matched": f"{schema_ok}/{len(c)}",
        "length_within_20pct": f"{within_20pct}/{len(length_ratios)}",
        "length_median_ratio": median_length_ratio,
        "cosine_median": median_cos,
        "cosine_min": min_cos,
        "cosine_sample_n": len(cos_sims),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--novel", required=True)
    p.add_argument("--chapters", default=None, help="comma-separated chapter ids; default = whole novel")
    p.add_argument("--skip-runs", action="store_true", help="skip running paths; only run heuristic on existing .C.json/.D.json")
    args = p.parse_args()

    if not args.skip_runs:
        logger.info("=== Running path C (sync + cache) ===")
        c_time, _ = _run_C(args.novel, args.chapters)
        logger.info("path C wall-clock: %.1fs", c_time)
        logger.info("=== Running path D (batch) ===")
        d_time, _ = _run_D(args.novel, args.chapters)
        logger.info("path D wall-clock: %.1fs", d_time)
    else:
        c_time = d_time = 0.0

    logger.info("=== Equivalence heuristic ===")
    h = _equivalence_heuristic(args.novel)
    logger.info("Heuristic: %s", json.dumps(h, indent=2))

    print()
    print("# Comparison results")
    print(f"Novel: {args.novel}, chapters: {args.chapters or 'ALL'}")
    print()
    print("|             | C (sync+cache) | D (batch) |")
    print("|-------------|----------------|-----------|")
    print(f"| wall-clock  | {c_time:.1f}s          | {d_time:.1f}s     |")
    print()
    print("## Equivalence heuristic (C vs D)")
    for k, v in h.items():
        print(f"- {k}: {v}")


if __name__ == "__main__":
    main()
```

Note: this writes outputs to `passages_contextual.C.json` / `passages_contextual.D.json` so neither overwrites the other. Cost-tracking is not yet wired in this pass — Task 4 will extend the harness to capture token usage from each path's API responses (the existing `enrichment.timing.Recorder` is the right hook for path C; path D's batch result has its own usage info).

- [ ] **Step 2.5: Sanity-check the cosine threshold (run C against itself)**

Before the C-vs-D run, run C twice and compare its outputs to itself to see what self-similarity looks like:

```bash
# Run C once
uv run python -m enrichment.generate_contexts --novel bleak_house --chapters c1
mv data/novels/bleak_house/passages_contextual.json data/novels/bleak_house/passages_contextual.C1.json

# Run C again
uv run python -m enrichment.generate_contexts --novel bleak_house --chapters c1
mv data/novels/bleak_house/passages_contextual.json data/novels/bleak_house/passages_contextual.C2.json

# Compare the two C runs (treating them as if they were C and D)
cp data/novels/bleak_house/passages_contextual.C1.json data/novels/bleak_house/passages_contextual.C.json
cp data/novels/bleak_house/passages_contextual.C2.json data/novels/bleak_house/passages_contextual.D.json
uv run python scripts/compare_context_paths.py --novel bleak_house --chapters c1 --skip-runs
```

The cosine median and min from this self-comparison sets the floor. If self-similarity is, say, 0.92 median, then a 0.90 threshold for C-vs-D is too lax and we should adjust. Report the floor to the user before proceeding.

- [ ] **Step 3: Run the C-vs-D comparison on chapter 1**

```bash
# Clean up self-comparison files
rm data/novels/bleak_house/passages_contextual.C1.json data/novels/bleak_house/passages_contextual.C2.json data/novels/bleak_house/passages_contextual.C.json data/novels/bleak_house/passages_contextual.D.json

# Real comparison: run both paths on chapter 1
uv run python scripts/compare_context_paths.py --novel bleak_house --chapters c1
```

- [ ] **Step 4: Report results to user; user decides go/no-go**

Show the markdown table output to the user. Reference the self-similarity floor from Step 2.5. The user calls one of:
- "looks equivalent — proceed to Phase 3 (Task 4) on Oliver Twist"
- "outliers worth investigating — show me passages where cos_min < <value>"
- "the heuristic itself isn't telling us enough — adjust thresholds and re-run"

Do not move on without an explicit go-ahead. Iterate Step 3 if the user wants threshold adjustments or outlier investigation.

- [ ] **Step 5: Commit the harness**

```bash
git add scripts/compare_context_paths.py
git commit -m "$(cat <<'EOF'
scripts: compare_context_paths.py — runs both C/D, emits heuristic

Harness for Phase 2 sanity check (single chapter) and Phase 3
measurement (full novel). Runs each path, moves outputs to
.C.json / .D.json suffixes, then computes the three-check
equivalence heuristic (schema match, length ratio per passage,
cosine similarity on a sample of N=10).

Reports as data, not a verdict — user reads the table and decides.

Phase 2/3 of BleakHouse-1kg7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Phase 3 — Onboard Oliver Twist + measurement

**Goal:** Calibrate C vs D on a real novel (~155k words). Produce a side-by-side metrics table for the decision.

**Files:**
- Modify: `scripts/compare_context_paths.py` (add cost tracking, multi-run support)
- Created (as a side effect): `data/novels/oliver_twist/passages_enriched.json`, `data/novels/oliver_twist/passages_contextual.C.json`, `data/novels/oliver_twist/passages_contextual.D.json`

- [ ] **Step 1: Onboard Oliver Twist text + passages_enriched.json**

Run the existing pre-context steps for `oliver_twist`. The exact commands depend on the project's current ingestion flow — investigate via:

```bash
grep -rn "novel_key\|NOVEL_KEYS\|oliver_twist" enrichment/ scripts/ docs/pipeline.md 2>/dev/null | head -20
ls data/novels/middlemarch/  # exemplar of a fully-onboarded novel; mirror its files
```

Likely sequence (verify against the project's actual scripts):

```bash
# 1. Add 'oliver_twist' to NOVEL_KEYS in enrichment/axes.py (or wherever it lives) and any other registries
# 2. Download Project Gutenberg text:
uv run python -m enrichment.download --novel oliver_twist
# 3. Chapter the text + extract passages (existing path):
uv run python -m enrichment.passages --novel oliver_twist
# 4. Submit the literary-features batch (path A):
uv run python -m enrichment.submit_batch --novel oliver_twist
# Wait for completion (~30 min – 2 hr); poll status if needed.
# 5. Collect:
uv run python -m enrichment.collect_results --novel oliver_twist
```

The output should be `data/novels/oliver_twist/passages_enriched.json`. If it doesn't appear: read the actual code paths and adjust.

- [ ] **Step 2: Extend `scripts/compare_context_paths.py` with cost tracking**

Add cost capture to `_run_C` and `_run_D`. For path C, hook into `enrichment.timing.Recorder` (look for the existing pattern in `enrichment/generate_contexts.py`); for path D, parse the batch result file's per-request usage.

```python
# Replace the dict-returning bits of _run_C and _run_D with concrete metrics.
# Path C: recorder fields are total_input_tokens, total_cached_tokens, total_output_tokens,
#         and the recorder writes a sidecar JSON. Read that sidecar after the run.
# Path D: collect_context_batch.py loads the batch result file; each result has
#         a `result.message.usage` block with input_tokens / output_tokens.
#         If batch caching happened, look for cache-hit indicators per Anthropic's batch schema.

# Pricing (claude-haiku-4-5-20251001 as of 2026-05): input $1/M, cached input $0.10/M, output $5/M.
# Batch discount applies 50% off both input and output for path D.
INPUT_USD_PER_M = 1.00
CACHED_INPUT_USD_PER_M = 0.10  # 90% off
OUTPUT_USD_PER_M = 5.00
BATCH_DISCOUNT = 0.5
```

Capture per run:
- `wall_clock_s`
- `input_tokens` (total)
- `cached_input_tokens` (path C only)
- `output_tokens` (total)
- `total_cost_usd` (computed)
- `cache_hit_rate` (path C only) = cached / input

- [ ] **Step 3: Run the harness twice for each path (full novel)**

```bash
# Path C, run 1 + run 2 (manual repeat for now; the harness can be made to repeat in a future task)
uv run python scripts/compare_context_paths.py --novel oliver_twist | tee /tmp/oliver-twist-run1.txt
# Manually re-run by deleting outputs and invoking again; capture run 2 metrics
```

Wall-clock estimate: path C ~2 hr, path D ~30 min – 2 hr depending on Anthropic queue depth. Plan for an afternoon.

- [ ] **Step 4: Build the side-by-side measurement table**

Append a "## Phase 3 measurement" section to `docs/superpowers/notes/2026-05-04-context-paths-audit.md`:

```markdown
## Phase 3 measurement (Oliver Twist, full novel, 2 runs each path)

|                            | C run 1   | C run 2   | D run 1   | D run 2   |
|----------------------------|-----------|-----------|-----------|-----------|
| wall-clock                 | XX min    | XX min    | XX min    | XX min    |
| input tokens               | X.XXm     | X.XXm     | X.XXm     | X.XXm     |
| cached input tokens        | X.XXm     | X.XXm     | n/a       | n/a       |
| output tokens              | X.XXk     | X.XXk     | X.XXk     | X.XXk     |
| cache hit rate             | XX%       | XX%       | best-effort | best-effort |
| total cost (USD)           | $X.XX     | $X.XX     | $X.XX     | $X.XX     |

### Equivalence heuristic (C run 1 vs D run 1)
- schema_match: ...
- length_within_20pct: ...
- length_median_ratio: ...
- cosine_median: ...
- cosine_min: ...
- cosine_sample_n: ...
```

- [ ] **Step 5: Show the table to the user; await decision**

Same protocol as Task 3 Step 4 — user reads numbers, decides winner per the spec's decision rule (Quality > Wall-clock > Cost-amortised). Do not move to Task 5 without an explicit "winner is X."

- [ ] **Step 6: Commit measurement results**

```bash
git add docs/superpowers/notes/2026-05-04-context-paths-audit.md scripts/compare_context_paths.py
git commit -m "$(cat <<'EOF'
docs: Phase 3 measurement results (Oliver Twist, C vs D)

C/D measured on Oliver Twist (~155k words, 2 runs each). Cost,
wall-clock, cache hit rate, and equivalence heuristic captured in
the audit doc. User-facing decision happens in Task 5.

Phase 3 of BleakHouse-1kg7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Phase 4 — Decide + delete + rename

**Goal:** Apply the user's winner decision: keep one path, delete the other, rename the survivor to a content-named module.

**Files:**
- Delete: `enrichment/generate_contexts.py` **OR** `enrichment/submit_context_batch.py` + `enrichment/collect_context_batch.py`
- Rename winner to: `enrichment/run_passage_contexts.py`
- Modify: any callers of the deleted module's name (find via grep), `enrichment/run_novel.py:141` (if it references a deleted path), `dvc.yaml` (no current refs to these per spec, but verify)

- [ ] **Step 1: Promote the winner's output to canonical name**

```bash
cd data/novels/oliver_twist/
# If C wins:
mv passages_contextual.C.json passages_contextual.json && rm passages_contextual.D.json
# Else if D wins:
mv passages_contextual.D.json passages_contextual.json && rm passages_contextual.C.json
cd -
```

- [ ] **Step 2: Identify callers of the loser's module name**

```bash
LOSER=generate_contexts        # or submit_context_batch / collect_context_batch
grep -rn "enrichment\.${LOSER}\|enrichment/${LOSER}\.py\|from enrichment import.*${LOSER}" \
    --include="*.py" --include="*.md" --include="*.yaml" --include="*.sh" \
    2>/dev/null | grep -v ".venv" | tee /tmp/loser-refs.txt
wc -l /tmp/loser-refs.txt
```

- [ ] **Step 3: Delete the loser**

```bash
git rm enrichment/${LOSER}.py
# If D is the loser, also:  git rm enrichment/collect_context_batch.py
```

- [ ] **Step 4: Rename the winner**

```bash
WINNER_FILE=enrichment/generate_contexts.py    # or enrichment/submit_context_batch.py (and collect_context_batch.py)
git mv "$WINNER_FILE" enrichment/run_passage_contexts.py
# If D wins (two files): collapse-or-keep is deferred per the spec; for now,
# git mv enrichment/submit_context_batch.py enrichment/run_passage_contexts.py
# and decide in Task 6 whether to also keep collect_context_batch.py separately
# or merge it under run_passage_contexts.py with a --collect subcommand.
```

- [ ] **Step 5: Update the survivor's docstring**

The survivor's top-of-file docstring should reflect the new role:

```python
"""Generate situating context for each passage (canonical path).

Produces data/novels/<novel>/passages_contextual.json. This is the
single canonical implementation; the alternative path was deleted in
BleakHouse-1kg7 Phase 4 (2026-05-XX) after measurement on Oliver Twist
showed <one-sentence-rationale>.

Usage:
    uv run python -m enrichment.run_passage_contexts --novel <key>
"""
```

Replace `<one-sentence-rationale>` with the actual rationale from the user's decision.

- [ ] **Step 6: Update all callers**

For each line in `/tmp/loser-refs.txt`, replace the import or invocation. For renamed-survivor references, update to `enrichment.run_passage_contexts`. Loser references: delete or replace with the survivor.

- [ ] **Step 7: Quality checks + smoke test**

```bash
uv run ruff check .
uv run pyright 2>&1 | tail -5
# Smoke test: run the canonical path on a single chapter to confirm it still works.
uv run python -m enrichment.run_passage_contexts --novel bleak_house --chapters c1 --resume
ls -la data/novels/bleak_house/passages_contextual.json
```

- [ ] **Step 8: Commit the consolidation**

```bash
git add -A
git commit -m "$(cat <<'EOF'
contexts: consolidate to enrichment/run_passage_contexts.py

Per Phase 3 measurement on Oliver Twist (results in
docs/superpowers/notes/2026-05-04-context-paths-audit.md), the
winner is <C|D> on <quality|wall-clock|cost>: <one-line
rationale>.

- Renamed <winner module(s)> → enrichment/run_passage_contexts.py.
- Deleted <loser module(s)>.
- Updated <N> callers across the repo.
- Smoke-tested on bleak_house ch1.

Phase 4 of BleakHouse-1kg7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Phase 5 — Sweep paths A & B

**Goal:** Audit path A (`submit_batch.py` + `collect_results.py`); rename it for naming consistency. Decide path B (`test_single.py`) fate.

**Files:**
- Modify: `docs/superpowers/notes/2026-05-04-context-paths-audit.md` (append Path A audit section)
- Rename: `enrichment/submit_batch.py` → `enrichment/submit_passages_enriched.py`
- Rename: `enrichment/collect_results.py` → `enrichment/collect_passages_enriched.py`
- Possibly delete or rename: `enrichment/test_single.py`

- [ ] **Step 1: Path A audit (quick)**

Read `enrichment/submit_batch.py` + `enrichment/collect_results.py`. Append to the audit doc:

```markdown
## Path A audit (passages_enriched.json producer)

- Model id: <claude-haiku-4-5-20251001 / other>
- max_tokens: <value>
- temperature: <value>
- Retry handling: <yes/no/details>
- Output schema: <Pydantic model name or "raw JSON">
- Last-touched commit: <git log -1 --format=%h enrichment/submit_batch.py>
- Drift from Path D's batch handling: <list any differences worth noting>

**Action**: <"no fixes needed" / list of fixes applied with commit SHAs>
```

If you find anything broken (e.g., outdated model id, missing retry that's now standard), fix it in this task with small commits.

- [ ] **Step 2: Rename A's modules**

```bash
git mv enrichment/submit_batch.py enrichment/submit_passages_enriched.py
git mv enrichment/collect_results.py enrichment/collect_passages_enriched.py
```

- [ ] **Step 3: Update imports**

```bash
grep -rn "submit_batch\|collect_results" --include="*.py" --include="*.md" --include="*.yaml" --include="*.sh" 2>/dev/null | grep -v ".venv"
# Edit each match. Pay special attention to:
#   - enrichment/run_passage_contexts.py (it imports format_chapter_text from submit_batch)
#   - enrichment/retry_failed.py (line 15: from enrichment.submit_batch import build_requests)
#   - docs/llm_call_sites.md (entries for submit_batch.py:144 and collect_results.py:75)
```

- [ ] **Step 4: Decide test_single.py fate**

Read it; decide:

- **Delete** if its function is well-covered by `enrichment/run_passage_contexts.py --resume` or by the renamed passages-enriched path. Default leaning per the spec.
- **Rename + tag** to `enrichment/debug_passage_enrichment.py` and add a docstring banner: `"""DEBUG ONLY — single-passage smoke test for the passages-enriched API path. Not a production path."""`

If the user has a strong opinion, follow it. Otherwise default to delete.

```bash
# Delete branch:
git rm enrichment/test_single.py

# OR rename branch:
git mv enrichment/test_single.py enrichment/debug_passage_enrichment.py
# (Then edit the docstring per above.)
```

- [ ] **Step 5: Quality checks + commit**

```bash
uv run ruff check .
uv run pyright 2>&1 | tail -5
git add -A
git commit -m "$(cat <<'EOF'
enrichment: rename path A modules; <delete|tag> test_single.py

- enrichment/submit_batch.py → enrichment/submit_passages_enriched.py
- enrichment/collect_results.py → enrichment/collect_passages_enriched.py
- enrichment/test_single.py → <deleted / renamed to debug_passage_enrichment.py>
- Updated <N> caller references across the repo
- Path A audit findings recorded in
  docs/superpowers/notes/2026-05-04-context-paths-audit.md;
  <no fixes needed | applied <small fix> in commit XXX>

Phase 5 of BleakHouse-1kg7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Phase 6a — Write `scripts/add_novel.sh`

**Goal:** A single shell script that takes a novel key and runs every onboarding step end-to-end, idempotent (re-runs skip already-completed steps).

**Files:**
- Create: `scripts/add_novel.sh`

- [ ] **Step 1: Identify the canonical step sequence**

From the existing onboarding flow (post-Task 6 renames), the sequence is:

1. Download Project Gutenberg text (`enrichment/download.py` or equivalent).
2. Chapter / passage extraction.
3. Submit literary-features batch: `enrichment.submit_passages_enriched`.
4. Wait for batch to complete.
5. Collect literary-features: `enrichment.collect_passages_enriched`.
6. Run passage contexts: `enrichment.run_passage_contexts`.
7. Cluster (existing scripts; verify exact module name).
8. Build run-manifest entries (or whatever the existing post-enrichment step is).

Confirm by reading `enrichment/run_novel.py`, which appears to be the closest existing dispatcher:

```bash
sed -n '1,50p' enrichment/run_novel.py
```

- [ ] **Step 2: Write the script**

Create `scripts/add_novel.sh`:

```bash
#!/bin/bash
# Onboard a new novel end-to-end. Idempotent: each step skips if its
# output already exists. Stop on first failure (set -e).
#
# Usage: bash scripts/add_novel.sh <novel_key>
#   e.g.  bash scripts/add_novel.sh mrs_dalloway
#
# Wall-clock expectation: 1-3 hours, mostly waiting on the
# passages-enriched batch and the contexts run.
set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: $0 <novel_key>" >&2
    exit 2
fi
NOVEL="$1"
NOVEL_DIR="data/novels/${NOVEL}"
mkdir -p "$NOVEL_DIR"

echo "==> Onboarding novel: $NOVEL"
echo "    target dir: $NOVEL_DIR"

# Step 1: Download text. Skip if pg<id>.txt already there.
# (Replace the actual filename with what enrichment/download.py produces.)
if ls "$NOVEL_DIR"/pg*.txt >/dev/null 2>&1; then
    echo "==> [1/6] text already downloaded; skipping"
else
    echo "==> [1/6] download text"
    uv run python -m enrichment.download --novel "$NOVEL"
fi

# Step 2: Extract passages. Skip if passages_raw.json exists.
if [ -f "$NOVEL_DIR/passages_raw.json" ]; then
    echo "==> [2/6] passages already extracted; skipping"
else
    echo "==> [2/6] extract passages"
    uv run python -m enrichment.passages --novel "$NOVEL"
fi

# Step 3: Submit literary-features batch. Skip if passages_enriched.json exists.
if [ -f "$NOVEL_DIR/passages_enriched.json" ]; then
    echo "==> [3/6] passages_enriched.json present; skipping submit + collect"
else
    echo "==> [3/6] submit + collect literary-features batch (this can take 30 min – 2 hr)"
    uv run python -m enrichment.submit_passages_enriched --novel "$NOVEL"
    # Poll/wait happens inside submit module; collect blocks until ready or fails.
    uv run python -m enrichment.collect_passages_enriched --novel "$NOVEL"
fi

# Step 4: Run passage contexts. Skip if passages_contextual.json exists.
if [ -f "$NOVEL_DIR/passages_contextual.json" ]; then
    echo "==> [4/6] passages_contextual.json present; skipping"
else
    echo "==> [4/6] generate passage contexts"
    uv run python -m enrichment.run_passage_contexts --novel "$NOVEL"
fi

# Step 5: Cluster. Skip if clusters_literary.json + clusters_characters.json exist.
if [ -f "$NOVEL_DIR/clusters_literary.json" ] && [ -f "$NOVEL_DIR/clusters_characters.json" ]; then
    echo "==> [5/6] clusters already present; skipping"
else
    echo "==> [5/6] cluster passages"
    # Replace with the actual clustering invocation (verify against scripts/expert_clustering.py
    # or whatever the canonical module is).
    uv run python -m enrichment.cluster_passages --novel "$NOVEL"
fi

# Step 6: dvc commit + push so the produced files enter the deploy artefact set.
echo "==> [6/6] dvc commit + push (so the new novel's data ships in the next deploy)"
uv run --no-sync dvc commit -f
uv run --no-sync dvc push -r r2

echo ""
echo "SUCCESS. Novel $NOVEL onboarded. Files at $NOVEL_DIR/"
```

Note: the exact module names for steps 1, 2, and 5 depend on what the project actually uses. Verify each against the current code; replace placeholders with the real invocations.

- [ ] **Step 3: chmod + syntax check**

```bash
chmod +x scripts/add_novel.sh
bash -n scripts/add_novel.sh && echo "syntax OK"
```

- [ ] **Step 4: Smoke test on an existing novel (idempotent path)**

Test idempotency: run on `bleak_house`, which is fully onboarded. Every step should skip:

```bash
bash scripts/add_novel.sh bleak_house
```

Expected output: every step says "skipping" except step 6 (dvc commit, which is idempotent itself).

- [ ] **Step 5: Commit**

```bash
git add scripts/add_novel.sh
git commit -m "$(cat <<'EOF'
scripts: add_novel.sh — single-command novel onboarding

Six-step idempotent shell wrapper around the canonical onboarding
sequence: download → extract passages → submit/collect literary
features (path A, batch) → run passage contexts (canonical) →
cluster → dvc commit/push. Each step skips if its output already
exists. Wall-clock 1-3 hrs end-to-end on a new novel; near-instant
when re-run on a fully-onboarded novel (smoke-tested on bleak_house).

Phase 6a of BleakHouse-1kg7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Phase 6b — Update docs

**Goal:** Reflect the consolidation in CLAUDE.md, docs/pipeline.md, docs/llm_call_sites.md.

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/pipeline.md`
- Modify: `docs/llm_call_sites.md`

- [ ] **Step 1: Update CLAUDE.md**

Find any prose that documents how to add a novel:

```bash
grep -n "add a novel\|new novel\|onboard\|passages_enriched\|passages_contextual" CLAUDE.md
```

Replace with:

```markdown
## Adding a novel

Single command:

```bash
bash scripts/add_novel.sh <novel_key>
```

Six steps end-to-end (download → passages → literary features → contexts → cluster → dvc commit + push). Idempotent: re-runs skip already-completed steps. Wall-clock 1-3 hrs on a new novel; the literary-features batch and the contexts run dominate.
```

(Adjust to fit CLAUDE.md's structure — find the right section heading.)

- [ ] **Step 2: Update docs/pipeline.md**

Find the phase-0 enrichment section:

```bash
grep -n "phase.0\|enrichment\|passages_enriched\|passages_contextual" docs/pipeline.md
```

Update the relevant prose to point at `scripts/add_novel.sh` and `enrichment/run_passage_contexts.py`. Drop references to the deleted module(s).

- [ ] **Step 3: Update docs/llm_call_sites.md**

```bash
grep -n "submit_batch\|submit_context_batch\|collect_results\|collect_context_batch\|generate_contexts\|test_single" docs/llm_call_sites.md
```

For each entry:
- Renamed: update the path (e.g., `enrichment/submit_batch.py` → `enrichment/submit_passages_enriched.py`).
- Deleted: remove the row from the table.
- `test_single`: drop if deleted; otherwise update to `enrichment/debug_passage_enrichment.py`.

- [ ] **Step 4: Quality + commit**

```bash
git add CLAUDE.md docs/pipeline.md docs/llm_call_sites.md
git commit -m "$(cat <<'EOF'
docs: reflect consolidated enrichment pipeline

- CLAUDE.md: replace ad-hoc novel-onboarding prose with bash
  scripts/add_novel.sh <key>.
- docs/pipeline.md: phase-0 enrichment section points at the
  canonical run_passage_contexts and the renamed
  submit/collect_passages_enriched modules.
- docs/llm_call_sites.md: drop deleted entries, update renamed
  paths, drop test_single.py if deleted.

Phase 6b of BleakHouse-1kg7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Phase 6 verification — Mrs. Dalloway end-to-end

**Goal:** Run `scripts/add_novel.sh mrs_dalloway` from a clean state and confirm all four acceptance gates pass.

- [ ] **Step 1: Confirm clean starting state**

```bash
ls data/novels/mrs_dalloway/ 2>&1
# Expected: "No such file or directory" — Mrs. Dalloway is not yet onboarded.
```

If the directory exists from a previous attempt, decide with the user whether to delete and re-run or skip Step 1's "from clean state" requirement.

- [ ] **Step 2: Run the script**

```bash
bash scripts/add_novel.sh mrs_dalloway 2>&1 | tee /tmp/mdal-onboard.log
echo "exit code: $?"
```

Wall-clock expectation: 1-2 hr. Watch the log; the literary-features batch and the contexts run will dominate.

- [ ] **Step 3: Verify acceptance gates**

```bash
echo "Gate 1: script exit 0 — already verified by 'set -e' in Step 2"

echo "Gate 2: canonical artefacts exist with sane shape"
ls -la data/novels/mrs_dalloway/passages_enriched.json data/novels/mrs_dalloway/passages_contextual.json
uv run python -c "
import json
e = json.load(open('data/novels/mrs_dalloway/passages_enriched.json'))
c = json.load(open('data/novels/mrs_dalloway/passages_contextual.json'))
print(f'passages_enriched: {len(e)} entries')
print(f'passages_contextual: {len(c)} entries')
assert len(e) == len(c), 'enriched and contextual must have same count'
assert 'context' in c[0], 'contextual entries must have a context field'
print('shape OK')
"

echo "Gate 3: dvc commit + push handled by step 6 of add_novel.sh — verify R2 in sync"
uv run --no-sync dvc status -c -r r2 | tail

echo "Gate 4: downstream consumer works"
# Pick or invent a run id; e.g. mdal_trn_literary
# Add config.json + axes for the new run
# Then:
uv run python -m enrichment.run_pipeline --name mdal_trn_literary --resume-from 0 --phase 2
ls -la data/runs/mdal_trn_literary/phase2_plan.json
```

- [ ] **Step 4: Document the verification result**

Append to the audit doc:

```markdown
## Phase 6 verification (Mrs. Dalloway)

- script exit: 0
- passages_enriched.json: <N> entries
- passages_contextual.json: <N> entries (matches enriched count)
- dvc status -c -r r2: in sync
- downstream consumer (mdal_trn_literary, phase 0-2): phase2_plan.json produced

**Outcome**: <verification passed / failed at gate X with details>
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/notes/2026-05-04-context-paths-audit.md
git commit -m "$(cat <<'EOF'
docs: Phase 6 verification on Mrs. Dalloway — <passed|failed>

Ran scripts/add_novel.sh mrs_dalloway from clean state. <Summarise
outcome: which gates passed, any issues, downstream consumer
result.>

Phase 6 of BleakHouse-1kg7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Close the bd ticket

- [ ] **Step 1: Close BleakHouse-1kg7**

```bash
bd close BleakHouse-1kg7 --reason="Consolidated to enrichment/run_passage_contexts.py per Phase 3 measurement on Oliver Twist (winner: <C|D>; rationale in docs/superpowers/notes/2026-05-04-context-paths-audit.md). Path A renamed to submit_passages_enriched.py + collect_passages_enriched.py; test_single.py <deleted|tagged as debug>. Single-command onboarding via bash scripts/add_novel.sh <key>; verified end-to-end on Mrs. Dalloway. Spec: docs/superpowers/specs/2026-05-04-consolidate-enrichment-paths-design.md. Plan: docs/superpowers/plans/2026-05-04-consolidate-enrichment-paths.md."
```

- [ ] **Step 2: Final push**

```bash
git push origin main
```

---

## Self-review notes

- **Spec coverage**: every spec phase maps to a task. Phase 1 → Task 1; Phase 2 → Task 2 + Task 3 (sanity check separated); Phase 3 → Task 4; Phase 4 → Task 5; Phase 5 → Task 6; Phase 6a (script) → Task 7; Phase 6b (docs) → Task 8; Verification → Task 9; ticket close → Task 10.
- **Spec acceptance criteria**: (a) one path lives; (b) CLAUDE.md updated; (c) dvc.yaml unchanged (already none referenced); (d) test_single deleted-or-tagged; (e) verification on fresh novel — all addressed in Tasks 5/8/8/6/9 respectively.
- **Placeholder scan**: a few `<placeholder>` strings appear inside commit-message templates (e.g. `<C|D>`, `<one-sentence-rationale>`, `<deleted|tagged>`) — these are intentional fill-ins after the user's per-step decisions, not unfilled plan items. The plan itself contains no TBDs; every step has concrete commands, code, or a clear "ask user, await answer" prompt.
- **Type/method consistency**: `_run_C` and `_run_D` in `compare_context_paths.py` share the same return signature (`tuple[float, dict]`); `_equivalence_heuristic` returns a single dict. `enrichment/run_passage_contexts.py` is the single name used post-rename throughout Tasks 5-9.
- **Interactive checkpoints (where the human gates progress)**: Task 2 Step 1 (per-difference reconciliation), Task 3 Step 4 (sanity-check go/no-go), Task 4 Step 5 (winner decision), Task 6 Step 4 (test_single fate). The agentic worker should NOT proceed past these without an explicit user reply.
