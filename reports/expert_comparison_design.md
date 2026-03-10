# Expert-Level Comparison Design

**Date:** 2026-03-10
**Status:** In progress (first 3 analyses running on available data)

## Dataset

With all C(6,3) = 20 expert panels, each of the 6 experts appears in exactly
C(5,2) = 10 panels. Each panel is run through both transport and embedding
pipelines, giving **20 runs per expert** (10 transport + 10 embedding).

Experts:
- **Eleanor Hartley** — literary craft, narrative technique focus
- **James Blackstone** — legal/institutional, social critique focus
- **Caroline Woodcourt** — character development, emotional/relational focus
- **Edmund Leigh** (alt) — conservative, traditional literary values
- **Daniel Rosen** (alt) — Marxist/materialist, social critique focus
- **Oliver Trevelyan** (alt) — performance/theatrical, humor focus

## Comparison Layers

### Layer 1: Passage-level (what the expert *gets*)

| ID | Analysis | Data source | Key question |
|----|----------|-------------|-------------|
| A1 | Provision profile heatmap | assignments.provisions | Does each expert get passages matching their demands? |
| A2 | Chapter/narrator diversity | assignments.chapter_id, .narrator | Do some experts range widely while others concentrate? |
| A3 | Character exposure | assignments.characters_present | Which novel characters does each expert encounter? |
| A4 | Interest score distribution | assignments.interest_score | Do some experts get "better" passages? |
| A5 | Pipeline divergence per expert | passage_id sets, same panel both pipelines | Which experts are most affected by selection method? |
| A6 | Panel-mate effects | same expert, different panels | How much does panel composition change assignments? |

### Layer 2: Script-level (what the expert *says*)

| ID | Analysis | Data source | Key question |
|----|----------|-------------|-------------|
| B1 | Airtime (word/turn count) | episode.segments.turns | Are some experts consistently dominant? |
| B2 | Vocabulary signature | episode turns, Kilgarriff G2 | Does each expert have a distinctive, stable voice? |
| B3 | Quote usage per expert | turns vs assigned best_quote | Who integrates primary text vs paraphrases? |
| B4 | Character mention density | turns, character name regex | Who talks about specific characters vs generalizes? |
| B5 | Cross-expert agreement | overlapping passages across runs | Does expert identity shape interpretation? |

### Layer 3: Structural

| ID | Analysis | Data source | Key question |
|----|----------|-------------|-------------|
| C1 | Demand satisfaction rate | expert.demands vs actual assignments | Does embedding meet demands as reliably as transport? |
| C2 | Assignment type breakdown | assignment_type field | Are some experts mostly backfilled? |

## Implementation Plan

**Phase 1** (immediate, passage-level only): A1, A2, C1
- Script: `scripts/expert_comparison.py`
- Works on incomplete dataset (currently available runs)
- Output: `reports/expert_comparison/`

**Phase 2** (after Phase 1, still passage-level): A5, A6
- Requires matched transport/embedding pairs
- Builds on Phase 1 infrastructure

**Phase 3** (after Phase 2, needs scripts): B1, B2
- Requires phase3_episode.json
- Most interesting question: do experts have stable identities across panels?

## Expert Appearance Matrix

Each expert appears in these 10 panels (default = Hartley, Blackstone, Woodcourt):

| Expert | Panels where present |
|--------|---------------------|
| Hartley | v01-v09, v10, v14, v16, v17, v20-v25 |
| Blackstone | v01-v09, v11, v13-v15, v21-v22, v26-v29 |
| Woodcourt | v01-v09, v10-v12, v15-v16, v18, v23, v26, v30 |
| Edmund | v10, v12, v17, v21, v24, v26-v28, v30 |
| Rosen | v11, v13, v18-v19, v22-v25, v27, v29 |
| Trevelyan | v14-v20, v25, v28-v30 |

## Key Design Decisions

1. **Aggregate across panels, not within.** The interesting signal is whether an expert
   has a stable "signature" regardless of who else is on the panel.

2. **Control for panel composition.** When comparing two experts, only compare runs where
   they appear in the *same* panel (direct competition) vs runs where one is absent
   (counterfactual).

3. **Separate transport and embedding.** Don't pool pipelines — the selection mechanism
   is itself a variable. Report per-pipeline and delta.

4. **Normalize by run size.** Runs have 28-34 passages; use proportions not raw counts
   for cross-run comparisons.
