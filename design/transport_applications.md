# Design: Optimal Transport Applications for Enriched Passages

**Status:** Draft
**Depends on:** Contextual retrieval pipeline (`bh-wui`) — 6,916 passages with
20-field `FieldReportEnrichment` + situating context + LanceDB embeddings

This document describes two applications of the enriched passage data, both
using min-cost flow (optimal transport) to select and organize content.

---

## Shared Foundation: Passage Clustering

Both applications benefit from pre-clustering passages along three independent
axes. Clustering controls redundancy at the source, before any optimization runs.

### Axis 1: Semantic Content

Cluster by embedding similarity (from LanceDB `text-embedding-3-small` vectors).
Passages describing the fog in chapters 1 and 16 land in the same cluster.
This prevents selecting near-duplicates.

### Axis 2: Literary Provisions

Cluster by enrichment profile: `plot_function`, `emotional_register`, and the
seven `prov_*` fields. This groups passages by *what they do narratively* —
a cluster of satirical exposition passages, a cluster of gothic climaxes, etc.
Selecting from diverse literary clusters ensures variety of mode.

### Axis 3: Dramatis Personae

Cluster by `characters_present` and `characters_speaking` overlap (Jaccard
similarity). This produces character-centric groups: the Dedlock passages, the
Jarndyce-and-Jarndyce passages, the Jo passages. These clusters are the basis
for tracking character arcs through the novel.

### Cluster Representation in the Flow Network

Each cluster becomes a single supply node. Its capacity equals the number of
member passages (or a configured maximum). When the solver assigns flow through
a cluster node, a post-processing step selects the best representative
passage(s) — by interest_score, quotability, or narrative position.

---

## Application A: Podcast Expert Assignment

### Problem

Select and assign passages to podcast experts for a multi-voice literary
discussion. Each expert has a profile defining their interests. The producer
has budget constraints. The result should be a balanced, non-redundant
conversation that tracks chosen character arcs.

### Participants

| Role | Function in the network |
|------|------------------------|
| **Expert** | Demand node — pulls passages matching their profile |
| **Producer** | Capacity constraints — bounds total length, per-expert allocation, segment structure |
| **Character arc** | Demand node — pulls passages tracing a character's journey |

### Expert Profiles as Demand Vectors

Each expert declares interest levels (0/1/2) across the enrichment dimensions:

```
literary_critic:
  prov_narrative_technique: 2    # strong demand
  prov_character_development: 2
  prov_thematic_depth: 1
  quotability: 2

social_historian:
  prov_social_critique: 2
  prov_atmosphere_setting: 2
  themes (poverty, class, law): 2

close_reader:
  quotability: 2
  prov_humor_entertainment: 2
  prov_character_development: 1
  emotional_register variety: 1
```

Interest levels map to demand units. A `prov_social_critique: 2` demand means
the social historian needs at least 2 units of social critique passages.

Passage supply comes from enrichment: `prov_social_critique: "strong"` = 2
units, `"weak"` = 1, `"none"` = 0.

### Character Arcs as Demand

The producer identifies arcs to track:

```
arcs:
  - name: "Richard's deterioration"
    character: "Richard Carstone"
    demand: 6          # want ~6 passages tracing this arc
    require: prov_character_development != "none"
    prefer: interest_score >= 3

  - name: "Lady Dedlock's secret"
    character: "Lady Dedlock"
    demand: 5
    require: prov_plot_advancement != "none"

  - name: "Jo's suffering"
    character: "Jo"
    demand: 4
    require: prov_social_critique != "none"
```

Each arc becomes a demand node. Passages in the character's dramatis personae
cluster that meet the `require` filter are eligible sources. The solver selects
passages in chapter order, giving narrative coherence.

### The Flow Network

```
                    ┌──────────────┐
                    │ SUPER_SOURCE │
                    └──────┬───────┘
                           │
            ┌──────────────┼──────────────┐
            │              │              │
            ▼              ▼              ▼
     ┌─────────────┐ ┌──────────┐ ┌──────────┐
     │ Semantic     │ │ Literary │ │ Character│
     │ Cluster A    │ │ Cluster B│ │ Cluster C│
     │ supply=5     │ │ supply=3 │ │ supply=8 │
     └──────┬──────┘ └────┬─────┘ └────┬─────┘
            │              │              │
            ├──────┬───────┼──────┬───────┤
            │      │       │      │       │
            ▼      ▼       ▼      ▼       ▼
     ┌──────────┐ ┌──────────┐ ┌──────────┐
     │ Literary │ │ Social   │ │ Richard  │
     │ Critic   │ │ Historian│ │ Arc      │
     │ demand=8 │ │ demand=8 │ │ demand=6 │
     └────┬─────┘ └────┬─────┘ └────┬─────┘
          │             │             │
          └─────────────┼─────────────┘
                        ▼
               ┌─────────────────┐
               │   SUPER_SINK    │
               │ capacity=budget │
               └─────────────────┘
```

Plus a NULL source node for gap detection (as in blog post 2).

### Redundancy Penalties: Convex Costs via Arc Duplication

To prevent over-drawing from popular clusters or themes, use increasing
marginal costs:

For a cluster with supply=3, replace one arc (capacity=3, cost=c) with:

```
arc1: capacity=1, cost=c       # first passage is cheap
arc2: capacity=1, cost=2c      # second costs double
arc3: capacity=1, cost=4c      # third costs quadruple
```

`SimpleMinCostFlow` handles this natively — each piece is just a separate arc.
The solver spreads across clusters rather than draining one.

The same trick applies per-theme: if an expert already has 2 "law" passages,
the 3rd "law" passage costs more, pushing toward "poverty" or "identity."

### Arc Coherence Bonus

Passages that continue a character thread already in the selection get a cost
reduction. If c12:p45 (Richard argues with Jarndyce) is selected, then c14:p22
(Richard doubles down) becomes cheaper.

**Option A — Two-pass:** First pass selects passages. Second pass adjusts costs
based on character continuity and re-solves. Simple, may not converge.

**Option B — Sequential arc pricing:** Process chapters in order. After each
chapter's passages are allocated, update costs for the next chapter based on
which threads are active. Each chapter is a small flow problem. Greedy across
chapters but optimal within.

**Option C — Expanded network with continuity arcs:** Add explicit "thread
continuation" arcs between chapter-adjacent passages of the same character,
with negative cost (bonus). The solver sees continuity as cheaper than starting
a new thread. Most elegant but largest network.

**Recommendation:** Option B. Sequential is natural for a narrative that
unfolds in chapter order, and keeps each sub-problem small.

### Producer Constraints

| Constraint | Implementation |
|-----------|---------------|
| Total length budget | Capacity on super_sink |
| Per-expert max | Capacity on expert→super_sink arcs |
| Per-expert min | Minimum flow constraint (or high penalty for under-allocation) |
| Segment structure | Multiple sink nodes (opening, deep_dive, closing) with separate capacities |
| ±20% balance | Capacity bounds on super_source→expert arcs |

### Consensus vs. Debate

Tunable via cost structure on cluster→expert arcs:

| Mode | Cost structure | Effect |
|------|---------------|--------|
| **Consensus** | Increasing marginal cost for multi-expert assignment | Each expert brings unique material |
| **Debate** | Flat or reduced cost for shared passages | Experts deliberately overlap to argue different readings |
| **Mixed** | Per-passage flag: `discussion_point=true` gets debate costs, others get consensus costs | Producer marks specific passages for group discussion |

### Output

For each expert, a ranked list of passages with:
- Which dimension(s) motivated the assignment
- Which character arc (if any) it serves
- Suggested talking points derived from enrichment fields

For the producer:
- Gap report (NULL flows): which demands went unmet
- Coverage map: which chapters/characters/themes are represented
- Budget utilization: how close to capacity limits

---

## Application B: Study Guide Generation (SparkNotes Simulation)

### Problem

Generate a structured chapter-by-chapter study guide from the enriched
passages, analogous to SparkNotes. Where the podcast application *selects*
passages for discussion, the study guide application *summarizes and organizes*
them for reference.

### Why Transport?

A study guide has sections with specific informational needs. Each section is
a demand node requiring particular types of content. Transport ensures every
section draws from the most relevant passages without over-citing popular ones.

### Study Guide Sections per Chapter

| Section | Demand dimensions | Source filter |
|---------|------------------|--------------|
| **Summary** | `prov_plot_advancement`: strong | All passages, weighted by plot_function ∈ {action, climax, revelation} |
| **Character Analysis** | `prov_character_development`: strong | Passages with characters_present, grouped by character |
| **Themes & Motifs** | `prov_thematic_depth`: strong | Passages with themes tags, clustered by theme |
| **Key Quotes** | `quotability`: strong | Passages where quotability = "strong", with best_quote extracted |
| **Historical Context** | `accessibility`: difficult | Passages rated "difficult" — these are what needs annotation |
| **Literary Devices** | `prov_narrative_technique`: strong | Passages with notable technique, emotional_register variety |
| **Social Commentary** | `prov_social_critique`: strong | Satirical/polemical passages about institutions |

### The Flow Network for Study Guide Generation

```
passages (supply, from enrichment scores)
        │
        ▼
 ┌──────────────────────────────────┐
 │  Per-chapter transport problem   │
 │                                  │
 │  source: passage clusters        │
 │  demand: study guide sections    │
 │  null: uncovered sections = gaps │
 └──────────────────────────────────┘
        │
        ▼
selected passages per section
        │
        ▼
 ┌──────────────────────────────────┐
 │  LLM generation (per section)    │
 │  Input: selected passages +      │
 │         enrichment metadata      │
 │  Output: study guide prose       │
 └──────────────────────────────────┘
```

Transport selects *which* passages feed each section. An LLM then synthesizes
the selected passages into study guide prose, using the enrichment metadata
(summary, themes, characters, best_quote) as structured input.

### Section Budget and Cross-Chapter Arcs

Each section has a passage budget:

```
summary:            5-8 passages (the backbone)
character_analysis: 3-5 per major character present
themes:             2-4 per theme
key_quotes:         2-3 (only the best)
historical_context: 1-3 (only where needed)
literary_devices:   2-3
social_commentary:  1-3 (only where present)
```

**Cross-chapter arcs** work differently than in the podcast. Here the goal is
not to track a character across episodes but to provide cross-references:
"Richard's declining judgment here echoes c24:p15 — see Chapter 24 analysis."

These cross-references emerge naturally from the character clusters: when a
character appears in multiple chapters, the study guide's character analysis
section can reference the cluster to find prior and subsequent appearances.

### Narrator-Aware Organization

Bleak House alternates between Esther's first-person narration and an
omniscient third-person narrator. The study guide should flag this:

- Chapters narrated by Esther (odd-numbered, roughly) get a "Narrator's
  Perspective" subsection noting her biases and limited knowledge
- Omniscient chapters get a "Narrative Irony" subsection where the
  omniscient narrator's satirical distance from characters is analyzed
- The `narrator` enrichment field directly supports this split

### Difficulty-Adaptive Annotation

The `accessibility` field (easy/moderate/difficult) drives annotation depth:

| Accessibility | Study guide treatment |
|--------------|---------------------|
| easy | Summary only, minimal annotation |
| moderate | Summary + brief context note |
| difficult | Full annotation: historical context, vocabulary, cultural reference explanation |

This means the study guide automatically focuses its explanatory effort where
a modern reader actually needs help — Chancery procedure, Victorian social
hierarchy, legal terminology — rather than annotating passages that are
self-explanatory.

### Generation Pipeline

```
Option G1: Pure extraction (no LLM)
  - Assemble sections from enrichment fields directly
  - summary field → Summary section
  - best_quote → Key Quotes section
  - themes → Themes section headers
  - Fast, cheap, deterministic
  - Quality limited by enrichment quality

Option G2: LLM synthesis from selected passages
  - Transport selects passages per section
  - LLM receives: passage text + enrichment metadata + section template
  - LLM writes study guide prose
  - Higher quality, can cross-reference and synthesize
  - Costs ~$2-5 for full novel (Haiku on structured input)

Option G3: Hybrid
  - Use G1 for straightforward sections (Key Quotes, Summary)
  - Use G2 for sections requiring synthesis (Character Analysis, Themes)
  - Best cost/quality tradeoff

Recommendation: Option G3. The enrichment data is already high quality for
extraction. Only use LLM where synthesis adds genuine value.
```

### Output Format Options

| Format | Use case |
|--------|---------|
| **Markdown** | Web rendering, GitHub pages |
| **JSON** | Structured data for downstream apps |
| **EPUB** | E-reader companion to the novel |
| **Interactive (Textual TUI)** | Navigate by chapter, character, theme — linked to vector search |

---

## Comparison of Applications

| Dimension | Podcast Assignment | Study Guide |
|-----------|-------------------|-------------|
| **Selection strategy** | Curated highlights for discussion | Comprehensive coverage for reference |
| **Passage budget** | Tight (episode length) | Generous (thoroughness valued) |
| **Redundancy** | Strongly penalized | Tolerated (cross-references are useful) |
| **Character arcs** | Tracked as narrative threads | Tracked as cross-chapter references |
| **Narrator voice** | Shapes which expert discusses it | Shapes annotation depth |
| **NULL flows mean** | "Gap in discussion — find more material" | "Thin chapter — note it for the reader" |
| **LLM role** | Downstream: experts discuss selected passages | Downstream: synthesize into prose |
| **Transport role** | Core: who gets what | Preprocessing: what feeds each section |

---

## Implementation Order

1. **Clustering pipeline** (shared) — cluster passages on 3 axes, store cluster
   assignments. Prerequisite for both applications.
2. **Study guide generator** — simpler flow network, mostly extraction,
   fast to validate. Good proof of concept for the transport approach.
3. **Expert assignment** — richer network with consensus/debate modes, producer
   constraints, arc coherence. Builds on lessons from study guide.

---

## Dependencies

- `bh-wui`: Contextual retrieval pipeline (passages + embeddings)
- OR-Tools (`ortools`) for `SimpleMinCostFlow`
- Existing enrichment data: `data/passages_enriched.json` (6,916 passages × 20 fields)
