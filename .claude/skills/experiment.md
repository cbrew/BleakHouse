# Experiment Skill

**Description:** Plan, design, run, and analyse experiments testing hypotheses about the BleakHouse literary podcast system.

**When to use:** When the user says "experiment", "test hypothesis", "run experiment", "design experiment", or references specific hypothesis IDs (H1-H20) from paper/hypotheses.md.

## Instructions

### 1. Load Context

Read the hypotheses document and current system state:

```
Read paper/hypotheses.md           # All hypotheses with test plans
Read data/runs/*/config.json       # What runs exist
bd list                            # Open beads issues
```

Identify which hypotheses the user wants to test. If unclear, ask.

### 2. Discuss Design with User

Before running anything, present a concrete experimental design and ask for approval. The design should include:

**Runs needed.** List the exact `run_pipeline` commands, specifying:
- `--novel` (which novel)
- `--pipeline` (transport / no-passages / embedding)
- `--name` (descriptive name encoding the experiment)
- `--host-prep` (if testing host preparation)
- `--replace-expert` (if testing specific panels)
- Any other flags

**Baseline.** What existing run serves as the comparison. Check whether it already exists in data/runs/.

**Metrics.** Which measurements will test the hypothesis. Available metrics:
- Word count, turn count, utterance count (per segment and total)
- Question frequency (regex `\?` count, per segment)
- Reactive markers (regex for agreement/disagreement phrases, per segment)
- Host word fraction
- Expert airtime proportions (per-expert word count as % of expert words)
- Quote count, quote pattern compliance (setup/reading/commentary)
- Quote verification rate (fuzzy 5-word match against source text)
- Per-expert TF-IDF vocabulary signatures and cross-condition cosine
- Passage-level and chapter-level Jaccard between conditions
- Provision dimension distributions (from enrichment data)
- Confabulation detection (match_passages.py for ungrounded runs)

**Cost estimate.** Approximate token cost:
- Phase 0 (segment design): ~2K Haiku tokens
- Phase 2.5a (pre-interviews): ~1K Haiku tokens × experts × segments
- Phase 2.5b (question planning): ~3K Sonnet tokens × segments
- Phase 3 (script generation): ~15K Sonnet tokens × segments (~100K total)
- Enrichment (new novel): ~5M Haiku tokens (one-time)

**Expected outcome.** What result would confirm or disconfirm the hypothesis.

Present this to the user and wait for their go-ahead before running anything.

### 3. Create Beads Issue

Before running, create a beads issue:

```bash
bd create --title="Experiment: [hypothesis ID] — [brief description]" \
    --description="[full design from step 2]" \
    --type=task --priority=1
bd update [issue-id] --claim
```

### 4. Run the Experiment

**For runs that reuse existing Phase 0/1/2 data:**
```bash
mkdir -p data/runs/[new_run_name]
cp data/runs/[baseline]/phase0_segments.json data/runs/[new_run_name]/
cp data/runs/[baseline]/phase1_assignments.json data/runs/[new_run_name]/
cp data/runs/[baseline]/phase2_plan.json data/runs/[new_run_name]/

uv run python -m enrichment.run_pipeline \
    --novel [novel] --name [new_run_name] --pipeline [type] \
    --resume-from 3 [other flags]
```

**For runs that need new passage selection:**
```bash
uv run python -m enrichment.run_pipeline \
    --novel [novel] --name [new_run_name] --pipeline [type] [flags]
```

**For ablation experiments (prompt modifications):**
Make a targeted edit to generate_podcast.py SYSTEM_PROMPT, run the experiment, then revert the edit. Document exactly what was changed.

**For new novels:**
First check if enrichment exists:
```bash
ls data/novels/[novel_key]/passages_enriched.json
```
If not, enrichment must be run first (Phase 0, ~5M Haiku tokens).

### 5. Measure Results

Use this measurement script pattern (adapt metrics to the hypothesis):

```python
import json, re
from collections import Counter

REACTIVE = re.compile(
    r'\b(exactly|absolutely|that\'s|I agree|but I|yes but|I think|'
    r'you\'re right|that reminds|building on|to add to|I\'d push back|'
    r'that\'s a great|fair point|interesting)\b', re.I)

def measure(path):
    with open(path) as f:
        ep = json.load(f)
    # ... compute metrics ...
    return metrics_dict

baseline = measure('data/runs/[baseline]/phase3_episode.json')
treatment = measure('data/runs/[treatment]/phase3_episode.json')
```

For quote verification, use the existing compute_metrics infrastructure:
```python
from enrichment.compute_metrics import fuzzy_quote_match, load_source_text, verify_quotes
```

For confabulation analysis on ungrounded runs:
```python
from webapp.match_passages import load_enriched_passages, match_episode_quotes
```

### 6. Report Results

Save a structured report to `data/runs/[run_name]/experiment_report.txt` containing:
- Hypothesis ID and statement
- Experimental design (runs, conditions, metrics)
- Results table (baseline vs treatment, with deltas)
- Assessment: confirmed / disconfirmed / inconclusive
- Surprises or unexpected findings
- Suggested follow-up experiments

Present a summary to the user and discuss interpretation.

### 7. Close Out

```bash
bd close [issue-id] --reason="[summary of findings]"
git add data/runs/[run_name]/ enrichment/generate_podcast.py  # if ablation
git commit -m "[descriptive message]"
git push
```

## Experiment naming conventions

Run names should encode the experiment:
- `ext_v01_hostprep` — transport baseline with host prep
- `ext_v01_ablation_a1` — transport baseline with ablation A1
- `nop_v19_hostprep` — no-passages all-swapped with host prep
- `mmar_ext_v01_baseline` — Miss Marjoribanks transport baseline
- `mmar_nop_v01_baseline` — Miss Marjoribanks no-passages baseline

Novel key conventions for new novels:
- `miss_marjoribanks` → prefix `mmar`
- `hester` → prefix `hest`
- `no_name` → prefix `noname`
- `new_grub_street` → prefix `ngs`
- `odd_women` → prefix `oddw`

## Hypothesis quick reference

### Ready to test now (no new infrastructure needed)
- H2, H11: Host prep effects (preliminary results exist)
- H3: Convergence paradox (data exists, needs TF-IDF analysis)
- H5, H9: Grounding and confabulation (data exists across 5 novels)
- H6: Expert prominence adaptation (data exists across 5 novels)
- H8: Demand manipulation (data exists for peaked/high-arc)
- H10: Host prep + identity preservation (one pair exists, need more)
- H14: Transport cost advantage (timing data available)

### Need ablation runs (prompt modifications)
- H1: Cross-engagement ablation (A1)
- H4: Quote pattern ablation (A2)
- H7: Prosodic annotation ablation (A3)
- H12: Sentence-type ablation (A4)
- H15: Timing guidance ablation (A6)

### Need new novel infrastructure
- H16: Grounding gap on obscure novels
- H17: Expert degradation on unfamiliar material
- H18: Enrichment schema bias
- H19: Cross-novel confabulation patterns
- H20: Host prep compensates for ignorance
