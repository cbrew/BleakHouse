# Three-Way Comparison: What We've Shown, What We Haven't, What's Needed

**Date:** 2026-03-10

## The Question

What are the relative contributions of three factors to the quality of generated podcast scripts?

1. **Passages** — the specific textual material fed to the script generator
2. **Prompts** — the expert persona descriptions and segment structure that shape generation
3. **Prior knowledge** — what the LLM already knows about Bleak House from training

## The Three Pipelines

| Pipeline | Passage selection uses | What it tests |
|----------|----------------------|---------------|
| **Transport** | Enriched metadata + min-cost flow | Full system: structured optimization over editorial metadata |
| **Embedding** | Enriched metadata + LLM curation | Same enrichment, different selection mechanism (LLM reasoning vs optimization) |
| **Plain RAG** | Raw text embeddings + cosine similarity | No enrichment in selection; passages chosen by surface textual similarity to expert descriptions |

## What We Have Shown

### 1. Passage selection method matters (strong evidence)

- Passage overlap between transport and embedding is near-zero (Jaccard 0.047 across 8 matched pairs). These are genuinely different selections, not sampling noise.
- The differences propagate to scripts: transport produces 26% more character mentions per 1k words (all 8 pairs), embedding recovers 18pp more quotes.
- Vocabulary signatures differ: Kilgarriff G2 keywords show transport scripts use more character names, embedding scripts use more analytical/structural language.

**Evidence:** `specificity_findings.md`, `pipeline_comparison/comparison_report.txt`

### 2. Expert identity is the strongest shaping force (strong evidence)

- Vocabulary signatures (B2) are stable across both pipelines: Hartley always gets "narration, structurally, omniscient"; Blackstone always gets "victorian, legal, chancery"; Trevelyan always gets "aloud, performer, read".
- Script vocabulary cosine between transport and embedding for the same expert averages 0.549 — despite completely different input passages.
- Character mention Jaccard in scripts averages 0.430 for same expert across pipelines.

**Interpretation:** The expert persona prompt dominates passage selection in determining *what the expert talks about*. Different passages shift the specifics, but the expert's voice and focus persist. This is a prompt effect.

**Evidence:** `expert_comparison/full_report.txt` (B2, Tier 3)

### 3. Enrichment metadata captures information embeddings miss (strong evidence)

- Vector search achieves 66.7% precision@10 against enrichment-defined criteria; metadata filtering achieves 100%.
- Character arc coverage: embeddings cover 19-37% of relevant chapters; metadata achieves 100%.
- 76% of transport-redundant passage swaps involve passages that are embedding-far but enrichment-close (same editorial function, different topic).

**Evidence:** `experiments_discussion.md` (Experiments 1, 2, 4)

### 4. The two pipelines produce different *kinds* of specificity (moderate evidence)

- Transport: character-dense (more characters mentioned, more character diversity from arc constraints)
- Embedding: text-faithful (higher quote recovery, more chapter references)
- Sentence specificity and close-reading depth are indistinguishable (~87% and ~2.7/1k respectively)

**Evidence:** `specificity_findings.md`

### 5. Panel composition changes what experts get, but not who they are (moderate evidence)

- Panel-mate effects (A6): same expert gets very different passages with different colleagues (mean pairwise Jaccard 0.11-0.34)
- But vocabulary signatures (B2) remain stable across panels
- Demand satisfaction varies (transport 53-91%, embedding 42-80%) but the expert's analytical lens persists

**Evidence:** `expert_comparison/full_report.txt` (A6, B2, C1)

## What We Have NOT Shown

### 1. The role of LLM prior knowledge (not measured)

This is the critical gap. The script generator (Sonnet) has read Bleak House in its training data. It can discuss Esther, Jarndyce, Lady Dedlock, and Jo without any passage input at all. We have no measurement of how much script quality comes from the LLM's prior knowledge vs the passages we provide.

**What's missing:** A condition where Phase 3 receives **no passages** — just the expert personas, segment structure, and the instruction "discuss Bleak House." This would establish a prior-knowledge baseline. If the scripts are still 80% as good, passages matter less than we assume. If they're empty or generic, passages are essential grounding.

### 2. Whether passage *identity* matters, or just passage *presence* (not measured)

We know transport and embedding select different passages and produce different scripts. But we don't know whether *random* passages would produce scripts of similar quality. The LLM might use any Dickens passage as a springboard for its existing knowledge.

**What's missing:** A condition with **random passage selection** — same number of passages, same Phase 3, but randomly drawn from the corpus. If random passages produce comparable scripts, then selection sophistication (transport, embedding, or RAG) adds little.

### 3. Whether enrichment helps the *script generator* or just the *selector* (not measured)

Phase 3 receives the enrichment metadata (provisions, themes, best_quote) alongside the passage text. We don't know whether the script generator uses this metadata. It might ignore it and work from the raw text, or it might rely on it heavily.

**What's missing:** A condition where Phase 3 receives **passages without enrichment metadata** — just raw text, expert name, and segment structure. Compare to the full-metadata condition.

### 4. Absolute quality (not measured)

All our metrics are relative (transport vs embedding). We have no external quality benchmark — no literary scholar ratings, no listener preferences, no grading against a rubric.

**What's missing:** Human evaluation, even informal.

### 5. Whether plain RAG's disadvantage (if any) comes from worse passages or fewer constraints (not yet measured)

The plain RAG pipeline removes both enrichment metadata from selection AND structural constraints (arcs, demands). If it performs worse, we can't separate these two effects without an intermediate condition.

**What's missing:** An intermediate condition that uses enrichment metadata in simple filtering (e.g., "select passages with strong humor for Woodcourt") but no optimization or LLM curation. This would isolate the enrichment contribution from the constraint-satisfaction contribution.

## What the Three-Way Comparison CAN Show

| Comparison | What it isolates |
|-----------|-----------------|
| Transport vs Embedding | Selection mechanism (optimization vs LLM reasoning), holding enrichment constant |
| Transport vs Plain RAG | Value of enrichment + structured constraints |
| Embedding vs Plain RAG | Value of enrichment + LLM curation |
| All three vs random baseline | Whether selection matters at all |
| All three vs no-passages baseline | Role of LLM prior knowledge |

The current three conditions (transport, embedding, plain RAG) can answer: **does enrichment-informed selection produce measurably different scripts from text-similarity-only selection?** If plain RAG scripts are indistinguishable from the other two, enrichment adds no downstream value. If they differ, we can characterize how.

But without the no-passages and random baselines, we cannot answer the deeper question: **how much of the script comes from the passages vs the LLM's own knowledge of Bleak House?**

## Recommended Additional Conditions

| Priority | Condition | Cost | What it answers |
|----------|-----------|------|----------------|
| **1** | **No passages** — expert personas + segment structure only, instruction to discuss Bleak House | 20 runs × ~5 min | Isolates LLM prior knowledge. The single most informative baseline. |
| **2** | **Random passages** — 32 random Bleak House passages per run, same Phase 3 | 20 runs × ~7 min | Tests whether passage identity matters or just presence |
| 3 | **Passages without enrichment metadata** — strip provisions, themes, best_quote from Phase 3 input | 20 runs × ~7 min | Tests whether Phase 3 uses enrichment metadata |
| 4 | **Metadata filtering only** — select passages by enrichment fields, no optimization | 20 runs × ~7 min | Isolates constraint-satisfaction from enrichment |

Priority 1 is essential — without it, the three-way comparison cannot distinguish "passages matter" from "the LLM already knows everything." Priority 2 establishes whether selection *quality* matters or just having *some* grounding text.

## Evidence Inventory

| Claim | Evidence source | Strength |
|-------|----------------|----------|
| Passage sets are disjoint across pipelines | Jaccard measurements, 8+ matched pairs | Strong |
| Character density advantage for transport | 8 pairs, consistent direction | Strong |
| Quote recovery advantage for embedding | 8 pairs, consistent direction | Strong |
| Expert vocabulary signatures are stable | G2 keywords across 20+ runs | Strong |
| Enrichment captures non-embedding information | Precision@10, arc coverage, redundancy analysis | Strong |
| Script generator partially converges despite different inputs | Vocabulary cosine 0.549, character Jaccard 0.430 | Moderate |
| Demand satisfaction higher for transport | 30 runs, per-expert averages | Moderate |
| Character density enables comedy | Impressionistic, no listener study | Weak |
| Plain RAG produces worse scripts | Not yet measured (runs in progress) | Pending |
| Passages matter more than LLM prior knowledge | Not measured | **Gap** |
| Passage identity matters (vs random) | Not measured | **Gap** |
