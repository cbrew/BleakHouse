# Hostprep Retrofit Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate the missing `phase2_5_interviews.json` + `phase2_5_host_briefs.json` artefacts (and a fresh phase 3 script paired with them) for the 88 legacy `hostprep=true` runs that completed the pipeline before phase 2.5 outputs were being persisted to disk. Each retrofit becomes a new experimental run sharing the original's episode key; the original run is untouched.

**Architecture:**
- Each retrofit is a *new* run, sibling-dir naming `<original_run_id>_retrofit_v1/`. Same axes-tuple as the source → same `episode` row in the DB. Different script paths → distinct `script_version` rows. Two scripts per affected episode (original without hostprep_version_id, retrofit with).
- Driver script invokes `enrichment.run_pipeline` with `--host-prep` and `--start-from phase2_5` (verify flag exists in Task 1) to skip phase 0/1/2 and reuse the source run's existing artefacts.
- No audio rendering in this plan. Retrofit scripts are generated but not rendered. Audio is a separate, larger investment.
- DB scanner needs no changes — the existing `scan_runs_dir` walks `data/runs/*/` and naturally picks up the new sibling dirs.

**Tech Stack:** Python 3.13, existing `enrichment.run_pipeline`, `enrichment.expdb`, sqlite3.

**Beads:** [BleakHouse-us0](../../../).

**Cost ceiling:** $500. Each retrofit estimated at $3–5 (prep + script, no audio). 88 runs × $5 worst-case = $440.

---

## What's not in scope

- **Rendering audio for retrofit scripts.** ~$300 extra. If we want listenable retrofit episodes, that's a separate batch.
- **Schema changes.** v3 supports this entirely. If we later want a typed `parent_script_version_id` link, that's a v4 bump in a follow-up plan.
- **Editing the original run dirs.** Their `axes.hostprep=true` is honestly correct — the original *did* use hostprep, just didn't persist the artefacts. Retrofits are siblings.
- **Filling in the original's `hostprep_version_id`.** Stays NULL. The original prep is unrecoverable; pretending we recovered it would be dishonest.

---

## File structure

```
scripts/retrofit_hostprep.py            -- single-run driver
scripts/retrofit_hostprep_batch.py      -- bulk driver across the 88
tests/expdb/test_retrofit_scan.py       -- backfill picks up retrofit sibling dirs

data/runs/<original>_retrofit_v1/       -- sibling per retrofit
  phase2_5_interviews.json
  phase2_5_host_briefs.json
  phase2_5_reading_list.json     (if reference search is enabled)
  phase3_episode.json
  retrofit_manifest.json         -- {source_run, retrofit_date, models, ...}
  run_manifest.json              -- axes copied from source; dvc_lock_sha = current
```

---

## Pre-flight verification

Before any work touches real money, prove the pipeline supports what we need.

- [ ] **Step 1: Read `enrichment/run_pipeline.py` to confirm flag support**

Required flags: `--host-prep`, `--only-host-prep`, `--name <out_dir>`, and a way to **skip phase 0/1/2 and reuse existing artefacts**. The pipeline already supports `--phase` and `--only-host-prep`; verify it can take an existing `phase1_assignments.json` + `phase2_plan.json` from a source run.

If unsupported: this plan needs a wrapper that copies phase 0–2 artefacts into the retrofit dir before invoking the pipeline. Add Task 1.5 to write that wrapper.

- [ ] **Step 2: Run a dry-run trial against one source run**

Pick the smallest BH hostprep run (probably `bh_trn_literary_hostprep` if it lacks the JSONs, otherwise any). Manually:

```bash
mkdir -p data/runs/_retrofit_trial/
cp data/runs/<source>/phase{0,1}*.json data/runs/_retrofit_trial/
cp data/runs/<source>/phase2_plan.json data/runs/_retrofit_trial/
cp data/runs/<source>/manifest.json data/runs/_retrofit_trial/
# then invoke pipeline with --start-from phase2_5 --only-host-prep against _retrofit_trial/
```

Expected: `phase2_5_interviews.json` + `phase2_5_host_briefs.json` produced in ~2–4 minutes. Cost: ~$2.

If this works, the retrofit driver in Task 2 is a thin shell over this manual procedure. If not, debug before continuing.

---

## Task 1: Identify the 88 retrofit candidates

**Files:**
- Create: `scripts/list_retrofit_candidates.py`

- [ ] **Step 1: Write the script**

Write `scripts/list_retrofit_candidates.py`:

```python
"""List runs needing hostprep retrofit (BleakHouse-us0).

A run needs retrofit when:
  - run_manifest.json axes.hostprep is true
  - phase2_5_interviews.json or phase2_5_host_briefs.json is missing on disk
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def find_candidates(repo: Path) -> list[Path]:
    out = []
    for rm in sorted((repo / "data" / "runs").glob("*/run_manifest.json")):
        try:
            m = json.loads(rm.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not m.get("axes", {}).get("hostprep"):
            continue
        d = rm.parent
        if (d / "phase2_5_interviews.json").exists() and (d / "phase2_5_host_briefs.json").exists():
            continue
        # Skip directories that already look like retrofits.
        if d.name.endswith("_retrofit_v1"):
            continue
        out.append(d)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=Path("data/retrofit_candidates.txt"))
    args = p.parse_args()

    repo = Path(__file__).resolve().parent.parent
    candidates = find_candidates(repo)
    args.out.write_text("\n".join(c.name for c in candidates) + "\n")
    print(f"{len(candidates)} candidates → {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it and verify count**

```bash
uv run python scripts/list_retrofit_candidates.py
wc -l data/retrofit_candidates.txt
```

Expected: 88 candidates (or whatever the current state shows; the doc-time count was 88).

- [ ] **Step 3: Commit**

```bash
git add scripts/list_retrofit_candidates.py
git commit -m "retrofit: list_retrofit_candidates.py for BleakHouse-us0"
```

---

## Task 2: Single-run retrofit driver

**Files:**
- Create: `scripts/retrofit_hostprep.py`

- [ ] **Step 1: Write the driver**

Write `scripts/retrofit_hostprep.py`:

```python
"""Retrofit hostprep for one source run.

Creates a sibling dir `<source_run>_retrofit_v1/`, copies phase 0–2
artefacts from the source, then invokes the pipeline to generate
phase 2.5 (interviews + briefs) and phase 3 (script). Original
source run is untouched.

Usage:
    uv run python scripts/retrofit_hostprep.py <source_run_id> [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_PHASE_INPUTS = [
    "manifest.json",
    "phase0_segments.json",
    "phase1_assignments.json",
    "phase2_plan.json",
    "config.json",
]


def stage_inputs(source_dir: Path, retrofit_dir: Path) -> None:
    retrofit_dir.mkdir(parents=True, exist_ok=True)
    for name in REQUIRED_PHASE_INPUTS:
        src = source_dir / name
        if not src.exists():
            raise SystemExit(f"FAIL: {src} not present in source run")
        shutil.copy2(src, retrofit_dir / name)


def write_retrofit_manifest(source_dir: Path, retrofit_dir: Path) -> None:
    src_run_manifest = json.loads((source_dir / "run_manifest.json").read_text())
    rm = {
        "schema_version": 1,
        "retrofit_of": source_dir.name,
        "retrofit_date": datetime.now(timezone.utc).isoformat(),
        "axes": src_run_manifest.get("axes", {}),
        "source_dvc_lock_sha": src_run_manifest.get("dvc_lock_sha"),
    }
    (retrofit_dir / "retrofit_manifest.json").write_text(json.dumps(rm, indent=2))


def run_pipeline(retrofit_dir: Path, source_axes: dict, dry_run: bool = False) -> int:
    """Invoke enrichment.run_pipeline against retrofit_dir.

    The pipeline reads existing phase 0–2 outputs from the run dir and
    generates phase 2.5 + phase 3 fresh. Output goes into the same dir.
    """
    novel = source_axes.get("novel", "bh")
    pipeline = source_axes.get("pipeline", "trn")
    panel = source_axes.get("panel", "literary")
    hostprep = source_axes.get("hostprep", True)
    if not hostprep:
        raise SystemExit("source run is not hostprep — nothing to retrofit")

    cmd = [
        "uv", "run", "python", "-m", "enrichment.run_pipeline",
        "--novel", _novel_to_full_name(novel),
        "--name", retrofit_dir.name,
        "--pipeline", _pipeline_to_full_name(pipeline),
        "--panel", panel,
        "--host-prep",
        "--phase", "2_5",   # start from phase 2.5; phase 0–2 outputs already in place
    ]
    if dry_run:
        print("DRY-RUN:", " ".join(cmd))
        return 0
    return subprocess.run(cmd, check=False).returncode


def _novel_to_full_name(short: str) -> str:
    # Match the pipeline's --novel arg conventions; extend as needed.
    return {
        "bh": "bleak_house", "motf": "mill_on_the_floss", "omf": "our_mutual_friend",
        "nas": "north_and_south", "pti": "passage_to_india", "mid": "middlemarch",
        "dd": "daniel_deronda", "dc": "david_copperfield", "ht": "hard_times",
        "cran": "cranford", "ngs": "new_grub_street", "oddw": "odd_women",
        "noname": "no_name", "mmar": "miss_marjoribanks", "hest": "hester",
    }.get(short, short)


def _pipeline_to_full_name(short: str) -> str:
    return {"trn": "transport", "emb": "embedding", "nop": "no-passages",
            "rag": "rag"}.get(short, short)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source_run_id")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    repo = Path(__file__).resolve().parent.parent
    source_dir = repo / "data" / "runs" / args.source_run_id
    if not source_dir.is_dir():
        sys.exit(f"FAIL: {source_dir} not found")

    retrofit_dir = source_dir.parent / f"{args.source_run_id}_retrofit_v1"
    if retrofit_dir.exists():
        sys.exit(f"FAIL: {retrofit_dir} already exists; remove or version up")

    src_run_manifest = json.loads((source_dir / "run_manifest.json").read_text())
    if not src_run_manifest.get("axes", {}).get("hostprep"):
        sys.exit("source run is not hostprep — nothing to retrofit")

    print(f"==> staging phase 0–2 inputs from {source_dir.name}")
    if not args.dry_run:
        stage_inputs(source_dir, retrofit_dir)
        write_retrofit_manifest(source_dir, retrofit_dir)

    t0 = time.perf_counter()
    rc = run_pipeline(retrofit_dir, src_run_manifest["axes"], dry_run=args.dry_run)
    elapsed = time.perf_counter() - t0
    if rc != 0:
        sys.exit(f"FAIL: pipeline returned {rc}")
    print(f"OK: retrofit produced at {retrofit_dir} ({elapsed:.0f}s wall)")


if __name__ == "__main__":
    main()
```

**Caveat:** the `--phase 2_5` flag and `--name` semantics need confirming against `enrichment/run_pipeline.py` in pre-flight Step 1. If `--name <retrofit_dir.name>` causes the pipeline to write to a *different* dir than the one we staged, this script needs adjusting. Verify before bulk-running.

- [ ] **Step 2: Dry-run against one candidate**

```bash
uv run python scripts/retrofit_hostprep.py bh_trn_literary_hostprep --dry-run
```

Expected: prints the staging steps + the pipeline command without invoking it.

- [ ] **Step 3: Real run on one candidate (the trial)**

Pick the cheapest candidate — probably `cran_trn_literary_hostprep` (Cranford has fewer passages than BH).

```bash
uv run python scripts/retrofit_hostprep.py cran_trn_literary_hostprep
```

Expected: ~2–4 min, ~$2–3 in API spend. Produces:
- `data/runs/cran_trn_literary_hostprep_retrofit_v1/phase2_5_interviews.json`
- `data/runs/cran_trn_literary_hostprep_retrofit_v1/phase2_5_host_briefs.json`
- `data/runs/cran_trn_literary_hostprep_retrofit_v1/phase3_episode.json`
- `data/runs/cran_trn_literary_hostprep_retrofit_v1/retrofit_manifest.json`

- [ ] **Step 4: Read the trial output and confirm quality**

Manually read the new `phase2_5_host_briefs.json` and `phase3_episode.json`. They should:
- Use the same expert personae as the original
- Reference passages from the source's `phase1_assignments.json`
- Have the same overall shape as a normal hostprep run

If quality is off, stop and debug. Don't proceed to bulk.

- [ ] **Step 5: Re-scan DB and verify retrofit ingests cleanly**

```bash
uv run python -m enrichment.expdb scan
uv run python -m enrichment.expdb show cran_trn_literary_hostprep
```

Expected: `show` displays *two* scripts under the episode — the original (no hostprep_version) and the retrofit (with hostprep_version).

- [ ] **Step 6: Commit**

```bash
git add scripts/retrofit_hostprep.py
git commit -m "retrofit: single-run driver + trial run on cran_trn_literary_hostprep"
```

---

## Task 3: Bulk driver with cost gate

**Files:**
- Create: `scripts/retrofit_hostprep_batch.py`

- [ ] **Step 1: Write the batch driver**

```python
"""Bulk hostprep retrofit across N candidates.

Reads candidates from data/retrofit_candidates.txt (one run_id per line),
runs scripts/retrofit_hostprep.py on each, tracks elapsed time and
estimated cost, stops at --limit or --cost-cap whichever comes first.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

EST_COST_PER_RUN = 5.0  # conservative upper bound; tighten after Task 2 trial


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--candidates", type=Path,
                    default=Path("data/retrofit_candidates.txt"))
    p.add_argument("--limit", type=int, default=10,
                    help="max runs to retrofit in this invocation")
    p.add_argument("--cost-cap", type=float, default=50.0,
                    help="stop when estimated total cost exceeds this (USD)")
    p.add_argument("--skip-existing", action="store_true", default=True)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    repo = Path(__file__).resolve().parent.parent
    if not args.candidates.exists():
        sys.exit(f"FAIL: {args.candidates} not found; run list_retrofit_candidates.py first")
    candidates = [line.strip() for line in args.candidates.read_text().splitlines() if line.strip()]
    print(f"loaded {len(candidates)} candidates")

    done = []
    skipped = []
    failed: list[tuple[str, str]] = []
    spent = 0.0
    for i, run_id in enumerate(candidates):
        if len(done) >= args.limit:
            print(f"reached --limit {args.limit}")
            break
        if spent + EST_COST_PER_RUN > args.cost_cap:
            print(f"reached --cost-cap ${args.cost_cap}")
            break
        retrofit_dir = repo / "data" / "runs" / f"{run_id}_retrofit_v1"
        if retrofit_dir.exists() and args.skip_existing:
            skipped.append(run_id)
            continue

        print(f"[{i + 1}/{len(candidates)}] {run_id}")
        cmd = ["uv", "run", "python", "scripts/retrofit_hostprep.py", run_id]
        if args.dry_run:
            cmd.append("--dry-run")
        t0 = time.perf_counter()
        rc = subprocess.run(cmd, cwd=repo, check=False).returncode
        elapsed = time.perf_counter() - t0
        if rc != 0:
            failed.append((run_id, f"exit={rc}"))
            continue
        done.append(run_id)
        spent += EST_COST_PER_RUN
        print(f"    ok ({elapsed:.0f}s, est ${EST_COST_PER_RUN:.2f}, cumulative ${spent:.2f})")

    print()
    print(f"done: {len(done)}, skipped: {len(skipped)}, failed: {len(failed)}")
    if failed:
        for r, msg in failed[:5]:
            print(f"  {r}: {msg}")
    print(f"estimated total spend: ${spent:.2f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Dry-run the batch**

```bash
uv run python scripts/retrofit_hostprep_batch.py --limit 5 --dry-run
```

Expected: prints 5 retrofit-staging commands without spending.

- [ ] **Step 3: Commit**

```bash
git add scripts/retrofit_hostprep_batch.py
git commit -m "retrofit: bulk driver with cost cap"
```

---

## Task 4: First wave of 5 (real money)

**Files:** none (operational task).

- [ ] **Step 1: Run the first wave**

```bash
uv run python scripts/retrofit_hostprep_batch.py --limit 5 --cost-cap 30
```

Expected: ~5 retrofits in ~15–20 minutes. Cost <$30.

- [ ] **Step 2: Re-scan DB**

```bash
uv run python -m enrichment.expdb scan
```

Expected: 5 new `script_version` rows, 5 new `hostprep_version` rows, episodes_inserted=0 (same axes as existing episodes).

- [ ] **Step 3: Spot-check three retrofits**

For three of the five, manually inspect the retrofit's `phase3_episode.json` and `phase2_5_host_briefs.json`. Pass criteria:
- Personae match the source run's panel (literary vs alternatives)
- Brief questions reference the source's actual passages, not made-up ones
- No obvious errors (truncated JSON, model refusing the prompt, etc.)

If any retrofit looks broken, debug before scaling.

- [ ] **Step 4: Decision gate**

If 5/5 passed: continue to Task 5 (rest of the batch).
If 4/5: continue but flag the failure pattern.
If 3/5 or worse: stop, debug, retry the failing ones.

---

## Task 5: Remaining 83 in waves of 30

**Files:** none.

- [ ] **Step 1: Wave 2 (30 retrofits, ~$150)**

```bash
uv run python scripts/retrofit_hostprep_batch.py --limit 30 --cost-cap 200
```

- [ ] **Step 2: Re-scan + spot-check**

```bash
uv run python -m enrichment.expdb scan
uv run python -m enrichment.expdb list-episodes | grep retrofit | wc -l
```

Expected: 35 retrofit-named scripts (5 from Task 4 + 30 from this wave).

- [ ] **Step 3: Wave 3 (30 retrofits)**

```bash
uv run python scripts/retrofit_hostprep_batch.py --limit 30 --cost-cap 200
```

- [ ] **Step 4: Wave 4 (final ~23 retrofits)**

```bash
uv run python scripts/retrofit_hostprep_batch.py --limit 30 --cost-cap 200
```

- [ ] **Step 5: Final scan**

```bash
uv run python -m enrichment.expdb scan
uv run --no-sync python -c "
import sqlite3
c = sqlite3.connect('data/experiments.db')
n_hp = c.execute('SELECT COUNT(*) FROM hostprep_version').fetchone()[0]
print(f'hostprep_version rows: {n_hp}')
"
```

Expected: ~103 hostprep_version rows (15 original + 88 retrofits).

---

## Task 6: Documentation + close issue

**Files:**
- Create: `docs/superpowers/notes/2026-XX-XX-hostprep-retrofit-results.md`
- Modify: bd issue BleakHouse-us0

- [ ] **Step 1: Write the results note**

Capture: total spend, wall-time per wave, any retrofits that needed manual fix, the final hostprep_version count, the per-panel reading-list verification rates after retrofit.

- [ ] **Step 2: Close the bd issue**

```bash
bd close BleakHouse-us0 --reason="Retrofitted 88 legacy hostprep runs with new prep + script artefacts. See docs/superpowers/notes/<date>-hostprep-retrofit-results.md. hostprep_version row count went from 15 to 103."
```

- [ ] **Step 3: Commit + push**

```bash
git add docs/superpowers/notes/<file>
git commit -m "retrofit: results note + closure of BleakHouse-us0"
git push
```

---

## Recovery / undo

If a retrofit goes wrong (bad model output, partial generation, etc.):

```bash
# Delete the retrofit dir on disk
rm -rf data/runs/<source_run_id>_retrofit_v1/

# Drop the DB and rescan; the deleted retrofit's rows go away.
rm data/experiments.db
uv run python -m enrichment.expdb scan
```

The original source run is untouched. The DB is regenerable.

---

## Self-review

**Spec coverage:**
- "retrofit the legacy hostprep runs" → Tasks 1–5 cover identification, single-run driver, bulk driver, three waves
- "doesn't lose any existing material" → sibling-dir convention; original run dir untouched; no DB rows mutated, only added; recovery path documented

**Type consistency:**
- `_novel_to_full_name` and `_pipeline_to_full_name` cover the 15 novels + 4 pipelines we've seen in the data
- The retrofit_manifest.json schema is documented in Task 2's `write_retrofit_manifest`

**Placeholder scan:** all commands shown verbatim; the `<file>` in Task 6 Step 3 is a deliberate fill-at-completion-time.

**Open question** (will be answered by pre-flight Step 1): does `enrichment/run_pipeline.py --phase 2_5 --name <dir>` write into the existing `<dir>` or create a new dir at `data/runs/<dir>/`? If the latter, Task 2 needs a tweak — possibly invoke pipeline with the existing dir as `--name`, or post-process by moving outputs.
