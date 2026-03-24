# Experiment Skill

**Description:** Plan, design, run, and analyse experiments testing hypotheses about the BleakHouse literary podcast system. Experiments serve two potential papers with different audiences and framings.

**When to use:** When the user says "experiment", "test hypothesis", "run experiment", "design experiment", or references specific hypothesis IDs (H1-H20) from paper/hypotheses.md.

## Two Paper Framings

Every experiment contributes to one or both of these papers. When designing an experiment, note which framing(s) it serves.

**Paper 1 (ACL framing): How LLMs behave under grounding and distribution shift.**
- Core claim: Providing explicit textual grounding largely eliminates hallucination, while lack of grounding reveals structured, distribution-dependent failure modes tied to the model's training exposure.
- Key findings for this paper: grounding vs no-grounding dominance, hallucination as systematic borrowing (not random noise), measurable novel-dependent LLM knowledge, architecture-induced interaction vs prompt-induced interaction, clean ablations.
- Audience cares about: hallucination mechanisms, distribution shift, RAG vs architectural design, generalizable insights beyond the literary domain.

**Paper 2 (Digital Humanities framing): How interpretation can be modeled, controlled, and studied computationally.**
- Core claim: Literary interpretation can be operationalized as an allocation problem over textual affordances, where different critical lenses produce distinct, inspectable readings of the same text.
- Key findings for this paper: parameterized interpretive lenses (Marxist, formalist, etc.), textual affordances that vary across works, passage selection as interpretive act, misquotation as intertextual contamination, scholarly discourse scaffolded without prior expertise.
- Audience cares about: making interpretation explicit and manipulable, bridging close reading and computational methods, theories of interpretation, what happens when you point established critical lenses at unfamiliar texts.

## Obscure Novel Candidates

Five lesser-known Victorian novels on Project Gutenberg, ordered by likely LLM training exposure (most to least familiar):

| Novel | Author | Year | ~Words | Key test |
|---|---|---|---|---|
| No Name | Wilkie Collins | 1862 | 250K | Sensation/thriller structure vs Dickensian experts |
| New Grub Street | George Gissing | 1891 | 200K | Meta-literary (fictional authors) — risk of LLM confusion |
| The Odd Women | George Gissing | 1893 | 150K | Gender politics — tests whether Rosen's Marxist frame and Edmund's conservative frame stretch |
| Miss Marjoribanks | Mrs Oliphant | 1866 | 200K | Domestic comedy, deeply obscure. LLM training exposure likely very low |
| Hester | Mrs Oliphant | 1883 | 180K | Banking, women in finance. Oliphant is genuinely forgotten |

**Why Oliphant matters most:** She wrote over 90 novels, was enormously popular in her time, but is barely read today. If the system produces coherent, grounded discussion of Miss Marjoribanks, that's a strong generalization result. If ungrounded generation confabulates by borrowing from Eliot or Gaskell (the most similar well-known authors), that reveals the structure of LLM literary hallucination — systematic borrowing, not random noise.

**Gutenberg availability (confirmed):**
- No Name: gutenberg.org/ebooks/1438
- New Grub Street: gutenberg.org/ebooks/1709
- The Odd Women: gutenberg.org/ebooks/4313
- Miss Marjoribanks: gutenberg.org/ebooks/41286
- Hester: gutenberg.org/ebooks/48197

**Novel key conventions:**
- `miss_marjoribanks` → prefix `mmar`
- `hester` → prefix `hest`
- `no_name` → prefix `noname`
- `new_grub_street` → prefix `ngs`
- `odd_women` → prefix `oddw`
- `hard_times` → prefix `ht`
- `middlemarch` → prefix `mid`
- `daniel_deronda` → prefix `dd`
- `david_copperfield` → prefix `dc`
- `cranford` → prefix `cran`

**Onboarding a new novel requires:** downloading from Gutenberg, parsing into passages, running Phase 0 enrichment (~5M Haiku tokens, one-time), and adding novel-specific configuration to enrichment/novel_prompts.py (title, author, year, narration notes, character arcs). The seven provision dimensions are applied unchanged — whether they transfer is itself hypothesis H18.

**Currently onboarded (segmented, awaiting enrichment):** hard_times, middlemarch, daniel_deronda, david_copperfield, cranford, no_name, new_grub_street, odd_women, miss_marjoribanks, hester.

**Fully enriched (ready for pipeline runs):** bleak_house, our_mutual_friend, mill_on_the_floss, north_and_south, passage_to_india.

## Instructions

### 1. Load Context

Read the hypotheses document and current system state:

```
Read paper/hypotheses.md           # All hypotheses with test plans
Read paper/two_papers.txt          # ACL and DH paper framings
Read data/runs/*/config.json       # What runs exist
bd list                            # Open beads issues
```

Identify which hypotheses the user wants to test. If unclear, ask.

### 2. Discuss Design with User

Before running anything, present a concrete experimental design and ask for approval. The design should include:

**Paper relevance.** Which paper framing(s) this experiment serves (ACL, DH, or both) and why.

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
- Cross-novel confabulation: match quotes against wrong novel's corpus

**Cost estimate.** Approximate token cost:
- Phase 0 (segment design): ~2K Haiku tokens
- Phase 2.5a (pre-interviews): ~1K Haiku tokens × experts × segments
- Phase 2.5b (question planning): ~3K Sonnet tokens × segments
- Phase 3 (script generation): ~15K Sonnet tokens × segments (~100K total)
- Enrichment (new novel): ~5M Haiku tokens (one-time)

**Expected outcome.** What result would confirm or disconfirm the hypothesis. State this concretely: "We expect Jaccard < 0.05" or "We expect verification to drop below 10%."

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
If not, enrichment must be run first. This requires:
1. Download from Gutenberg and parse into passages
2. Add novel config to enrichment/novel_prompts.py
3. Run Phase 0 enrichment (~5M Haiku tokens)
4. Optionally generate contextual embeddings for embedding pipeline

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

For cross-novel confabulation (H19 — does a confabulated Oliphant quote match real Dickens?):
```python
# Match quotes from novel A's no-passages run against novel B's enriched passages
passages_b = load_enriched_passages("Bleak House")
results = match_episode_quotes(episode_from_novel_a, passages_b)
# High match ratios = systematic cross-novel borrowing
```

### 6. Report Results

Save a structured report to `data/runs/[run_name]/experiment_report.txt` containing:
- Hypothesis ID and statement
- Paper relevance (ACL / DH / both)
- Experimental design (runs, conditions, metrics)
- Results table (baseline vs treatment, with deltas)
- Assessment: confirmed / disconfirmed / inconclusive
- Surprises or unexpected findings
- Implications for each paper framing
- Suggested follow-up experiments

Present a summary to the user and discuss interpretation. Specifically discuss:
- Does this change what we'd write in the ACL paper?
- Does this change what we'd write in the DH paper?
- What should we test next?

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

## Hypothesis quick reference

### Ready to test now (no new infrastructure needed)

| ID | Hypothesis | Paper | Status |
|---|---|---|---|
| H2 | Host prep transforms monologue into dialogue | Both | Preliminary: confirmed |
| H3 | Convergence paradox (persona dominates content) | ACL | Data exists, needs TF-IDF |
| H5 | Grounding prevents confabulation | ACL | Data exists across 5 novels |
| H6 | Expert prominence adapts to text | DH | Data exists across 5 novels |
| H8 | Demand manipulation produces predictable shifts | Both | Data exists for peaked/high-arc |
| H9 | Confabulation is novel-dependent | ACL | Data exists across 5 novels |
| H10 | Host prep preserves expert identity | Both | One pair exists |
| H11 | Length constraints preserve conversational gains | UX | Preliminary: confirmed |
| H14 | Transport enables zero-cost exploration | Both | Timing data available |

### Need ablation runs (prompt modifications)

| ID | Hypothesis | Paper | Ablation |
|---|---|---|---|
| H1 | Cross-engagement is architecture-driven | ACL | Remove "not parallel monologues" |
| H4 | Quote pattern is prompt-driven | ACL | Remove 3-part quote spec |
| H7 | Prosodic annotations are prompt-driven | ACL | Remove rate/pause guidance |
| H12 | Sentence-type classification is redundant | ACL | Remove type requirement |
| H15 | Timing guidance is low-impact | ACL | Remove timing table |

### Need new novel infrastructure (Gutenberg onboarding)

| ID | Hypothesis | Paper | Key novel |
|---|---|---|---|
| H16 | Grounding gap widens for obscure novels | ACL | Oliphant |
| H17 | Expert personas degrade gracefully | Both | Oliphant |
| H18 | Enrichment schema is Dickens-biased | DH | All candidates |
| H19 | Confabulation borrows from known novels | ACL | Oliphant vs Dickens |
| H20 | Host prep compensates for LLM ignorance | Both | Oliphant |
