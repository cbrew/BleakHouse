# Prompt Review and Anti-Redundancy Analysis

**Date:** 2026-03-11
**Git:** 4325ec4

A critical review of the pipeline's prompt architecture and redundancy
controls, informed by the manipulability, expert variation, and
conversational responsiveness findings.

---

## Part 1: Prompt Architecture Review

### 1.1 The Three Prompt Layers

The pipeline uses three distinct prompts at three phases:

1. **Enrichment prompt** (prompt.py) — Haiku annotates raw passages with
   20-field `FieldReportEnrichment` (interest, characters, provision
   dimensions, themes, emotional register, quotability, etc.)

2. **Segment design prompt** (design_segments.py) — Haiku designs 5–8
   episode segments given the expert panel and arc demands

3. **Script generation prompt** (generate_podcast.py) — Sonnet produces
   the actual podcast dialogue, structured as TTS-ready utterances

### 1.2 What the Prompts Do Well

**The enrichment prompt** is appropriately calibrated. The instruction
"Most paragraphs in Dickens are routine connective prose (score 0–1).
Reserve 4–5 for genuinely remarkable passages" creates useful
discrimination. The canonical name requirement ("Lady Dedlock" not "my
Lady") supports downstream character matching. The provision dimension
scoring ("most paragraphs provide 'none' or 'weak' on most dimensions")
prevents score inflation that would make the transport layer's cost
structure meaningless.

**The script generation prompt** is the strongest of the three. It
establishes a specific register ("BBC Radio 4 or a fine public-radio
roundtable"), gives precise TTS annotations (pause_before_ms ranges,
rate multipliers, quote_mode sequences), and explicitly mandates
inter-expert responsiveness: "Experts react to each other: agree, push
back gently, riff on each other's ideas. This is a conversation, not
parallel monologues." The conversational responsiveness data (§2.1–2.2
of the manipulability report) confirms this instruction is effective:
54% cross-referencing, 70% responsive directionality.

**The persona descriptions** create genuinely distinct voices. Each
expert has a differentiated analytical frame:
- Hartley: craft and structure ("architecture of sentences")
- Blackstone: institutional context ("what Chancery actually was")
- Woodcourt: reading experience ("what's funny, what's moving")
- Edmund: moral imagination ("Esther's goodness, Richard's weakness")
- Rosen: class power ("every institution is a mechanism for extracting value")
- Trevelyan: performance and sound ("hears the rhythms of the prose")

The G2 vocabulary analysis confirms these frames produce measurably
distinct language: Blackstone's "legal", "chancery", "victorian";
Rosen's "system", "class", "power"; Trevelyan's "read", "aloud",
"voice", "feel". The persona descriptions are doing real work.

### 1.3 What the Prompts Could Do Better

**The segment design prompt has a structural gap.** It asks Haiku to
design segments but doesn't tell it what material is actually available.
The prompt specifies which dimensions and arcs exist, but not the
distribution of supply — which dimensions have many strong-provision
passages and which are scarce. The segment designer might create a
deep_dive on atmosphere_setting when there are only 12 strong passages
for that dimension, or ignore humor_entertainment when there are 80.

This is partly by design (Phase 0 runs before Phase 1, so supply isn't
known yet), but it means segment designs can't optimise for the material.
A pre-pass summarising provision supply per dimension would let the
segment designer make better editorial choices.

**The script generation prompt doesn't surface transport assignments
explicitly.** The passage block shows `— assigned to {expert}` and
`(dimension: {dim})`, which is good. But it doesn't tell the LLM *why*
the solver chose this passage — what demand it satisfied, what cluster
it belongs to, what arc it serves. Adding a brief editorial rationale
per passage ("chosen for social_critique to satisfy Blackstone's primary
demand; from the Chancery cluster") would give the script generator
more to work with.

**The persona descriptions are divorced from the demand profiles.**
Hartley's description says she's "obsessed with how Dickens constructs
his effects" (narrative technique), but her transport demands are
`narrative_technique=2, character_development=2, thematic_depth=1` —
character_development is co-equal with her defining interest. In the
peaked condition, boosting narrative_technique to 6 and dropping
character_development to 1 actually *aligns* the demand profile with
the persona description better than the baseline does.

This raises a design question: should demand profiles be derived from
persona descriptions rather than set independently? Currently they're
separate artefacts — the persona says who the expert *is*, the demand
profile says what passages they *get*. The extreme condition showed that
aligning these more tightly (Rosen gets 100% social_critique, matching
his description as a class-power analyst) produces a more coherent
output.

**Quote handling could be more directive.** The prompt says "Include at
least one direct Dickens quote per expert turn" and provides the
setup/reading/commentary pattern. But it doesn't tell the expert to
prefer quoting from their *assigned* passages over inventing quotations.
The quote verification data shows 87% verification for transport — the
13% unverified could partly be addressed by a stronger instruction:
"Quote from the passages provided. If you need additional quotations,
signal clearly which passage you're drawing from."

**No anti-repetition instruction at the script level.** The prompt
relies entirely on Phase 1–2 deduplication to deliver non-redundant
passages. This is mostly correct — by the time the LLM sees passages,
they're already deduplicated. But across *segments*, the LLM doesn't
know what was discussed in previous segments (each segment is a separate
API call). An expert might introduce the same Dickens quote in segment 2
that another expert read in segment 1, because the LLM has no memory
across calls. A brief "Previously discussed" note per segment would
prevent this.


## Part 2: Anti-Redundancy Mechanisms

### 2.1 Overview

The pipeline has six distinct anti-redundancy mechanisms, operating at
four levels:

| Level | Mechanism | Default | Effect |
|-------|-----------|---------|--------|
| **Passage supply** | Provision strength (strong=2, weak=1, none=0) | — | Limits how much each passage can contribute |
| **Cluster penalty** | `cluster_lambda` convex cost | 5 | Penalises selecting multiple passages from same literary cluster |
| **Demand satisfaction** | `null_cost` | 100 | Forces real passages over unmet demand |
| **Cost preference** | `strong_cost=1, weak_cost=3` | — | Solver prefers strong provisions |
| **Post-flow dedup** | Keep lowest-cost per (passage, expert) | — | Removes multi-dimension duplicates |
| **Segment dedup** | One passage per segment maximum | — | Prevents within-segment repetition |

### 2.2 The Cluster Lambda: How It Works

The primary anti-redundancy mechanism. Passages are grouped into
literary clusters via HDBSCAN on a 24-dimensional feature vector
(8 plot_function + 9 emotional_register + 7 provision dimensions).

When the solver assigns passages from a cluster to an expert, costs
increase linearly:
- 1st passage from cluster C to expert E: cost 0
- 2nd passage: cost λ (=5)
- 3rd passage: cost 2λ (=10)
- kth passage: cost (k-1)×λ

This is a **convex penalty** — each additional passage from the same
cluster is progressively more expensive. The solver will naturally
diversify across clusters when cheaper alternatives exist, but won't
refuse a strong passage just because a similar one was already selected.

The experiment_redundancy.py script validated three settings:
- `lambda=0`: no penalty — solver freely reuses clusters
- `lambda=5`: default — moderate diversity pressure
- `lambda=20`: strict — strong diversity enforcement

### 2.3 What the Cluster Lambda Doesn't Do

The cluster lambda penalises *within-expert* cluster repetition. It
does **not** penalise cross-expert repetition: if Hartley and Blackstone
both get passages from the same cluster, there's no penalty. This is
intentional — different experts should be able to discuss the same
literary territory from different angles.

However, the post-flow deduplication (§2.1) removes exact duplicates:
the same passage_id cannot be assigned to the same expert twice. But
two *different* passages from the same cluster can go to the same
expert (at increasing cost), and the *same* passage can go to two
different experts (no cost interaction).

### 2.4 The Embedding Pipeline's Approach

The embedding pipeline (embedding_podcast.py) uses a fundamentally
different anti-redundancy strategy:

1. **Multi-query retrieval**: ~20 queries (expert × segment, per-arc,
   per-expert, per-segment) each retrieve top-15 candidates
2. **Query-hit aggregation**: Passages matching multiple queries rise
   in the candidate pool (`-query_hits, best_distance, -interest_score`)
3. **Interest filtering**: Drop passages with interest_score < 2

This is **popularity-based** rather than **cost-based**. A passage that
matches many queries is considered valuable; there's no mechanism
penalising thematic repetition. If the top 10 passages are all about
Chancery, they'll all be selected.

The embedding pipeline has no equivalent of cluster_lambda. Its diversity
comes implicitly from query diversity — different expert × segment
combinations produce different queries, which retrieve different
passages. But this is weaker than explicit redundancy control.

### 2.5 RAG, Random, and No-Passages

**RAG** (plain retrieval-augmented generation): Retrieves passages based
on segment descriptions. No explicit anti-redundancy. Whatever the
vector search returns is what the experts get.

**Random**: Passages selected uniformly at random. Anti-redundancy is
probabilistic — with 6,916 passages, the chance of selecting the same
passage twice is low, but thematic diversity is uncontrolled.

**No-passages**: No passages at all. "Anti-redundancy" is trivially
satisfied but the experts confabulate freely (38% quote verification).

### 2.6 Critique of the Anti-Redundancy Design

**Strengths:**

The convex penalty is elegant. It doesn't require hard constraints or
arbitrary diversity quotas. The solver naturally balances diversity
against quality: it will accept a second passage from the same cluster
if the alternative is a weak passage from a different cluster, but
won't take a fifth passage from the same cluster when four other
clusters have untouched strong passages. The graduated cost means the
system degrades gracefully when supply is thin.

The separation of clustering (HDBSCAN on enrichment features) from
cost structure (transport layer) means the redundancy notion is
task-specific. Two passages are "redundant" not because they have
similar embeddings, but because they serve the same literary function
(same provision profile, similar plot function, similar emotional
register). This is exactly the right abstraction.

**Weaknesses:**

**No cross-segment memory.** Each segment is generated in a separate
LLM call. The cluster_lambda prevents redundancy *within* a single
transport solution, but doesn't prevent the script generator from
repeating themes or quotes across segments. A passage about the fog
in segment 1 and a passage about the fog in segment 3 won't be
penalised if they're from different clusters — and even if they're
from the same cluster, the lambda penalty only applies within a single
expert's allocation.

**No cross-expert penalty.** If Blackstone gets c1:p1 (the fog) and
Hartley also gets c1:p3 (also the fog, different paragraph), there's
no cost interaction. The pipeline permits — even encourages — multiple
experts to discuss the same material from different angles. Whether
this is a bug or a feature depends on the editorial goal. The
cross-referencing data (54% cross-ref rate) suggests it creates
productive conversation, but it could also lead to repetitive episodes
where everyone discusses the fog.

**Interest score as a single number.** The enrichment assigns one
interest score per passage (0–5). This is used in arc selection
(cost = max(0, 10 - 2×interest)) but not directly in the main
expert-demand transport. High-interest passages are not systematically
preferred for expert demands — only for arc demands. A passage with
interest=1 and strong prov_social_critique gets the same base cost
as interest=5 with strong prov_social_critique. Adding an interest
bonus to the main transport (not just arcs) would improve passage
quality.

**Cluster quality is unvalidated.** The HDBSCAN clustering uses
min_cluster_size=20, producing clusters of passages with similar
enrichment profiles. But the cluster assignments aren't human-validated.
If the clustering puts a brilliant atmospheric passage in the same
cluster as a routine scene-setting paragraph (both score
atmosphere_setting=strong), the lambda penalty will discourage selecting
both even though they serve very different editorial purposes. The
clustering operates on enrichment features, not editorial value.

**The embedding pipeline has no equivalent protection.** The embedding
pipeline lacks any form of cluster_lambda or convex penalty. It
relies entirely on query diversity for deduplication. This is a
significant gap — and may partly explain why the embedding condition
shows higher cross-reference rates (56.0% vs 53.8% for transport):
without redundancy control, it selects more overlapping passages,
which gives experts more shared material to cross-reference. The
higher cross-reference rate may indicate *less* diversity, not *more*
conversation.


## Part 3: Alignment Between Components

### 3.1 Demand Profiles vs Persona Descriptions

| Expert | Persona emphasis | Top demand dimension | Aligned? |
|--------|-----------------|---------------------|----------|
| Hartley | "architecture of sentences", craft | narrative_technique (tied with character_dev) | Partial — character_dev dilutes |
| Blackstone | "Victorian institutions", legal context | social_critique (tied with atmosphere) | Partial — atmosphere dilutes |
| Woodcourt | "funny, moving", reading experience | humor_entertainment (dominant) | **Yes** |
| Edmund | "moral imagination", individual character | character_development (dominant) | **Yes** |
| Rosen | "class power", institutional critique | social_critique (dominant) | **Yes** |
| Trevelyan | "performer", "rhythms of the prose" | humor_entertainment (dominant) | **Yes** |

The alternative experts (Edmund, Rosen, Trevelyan) are better aligned
than the defaults (Hartley, Blackstone). This is because the
alternatives have more concentrated demand profiles (one dominant
dimension at 3, vs the defaults' flatter 2/2/1 profiles). The extreme
condition improves alignment by peaking the defaults' profiles to match
their persona descriptions.

### 3.2 Voice Policies vs Speaking Styles

Each persona has both a `voice_policy` (TTS parameters: rate, energy,
pause_bias, style) and a `speaking_style` (text instruction for the
LLM). These are used at different phases:
- `speaking_style` → appears in the system prompt for script generation
- `voice_policy` → used by TTS rendering (Gemini)

The speaking styles are specific enough to influence generation:
- Blackstone: "Measured, longer sentences kept fairly intact. Authority
  comes from syntactic control. Dry punchlines land with pause, not
  speed."
- Trevelyan: "Natural raconteur rhythm — varied sentence lengths, comic
  timing built into the phrasing."

The voice policies encode matching properties (Blackstone rate=0.96,
slower; Trevelyan rate=1.02, faster). This two-layer design —
text style for the LLM, acoustic style for TTS — is well-conceived.

### 3.3 The Coherence Gap

The segment design prompt (Phase 0) knows the expert panel and their
demand dimensions, but doesn't know:
- The actual passage supply per dimension
- The cluster structure
- The interest score distribution

The script generation prompt (Phase 3) knows the assigned passages and
their metadata, but doesn't know:
- Why the transport layer chose these passages
- What was discussed in previous segments
- What the expert's demand profile is (only the persona description)

This information loss across phases means each phase optimises locally
without full context. The transport layer (Phase 1) is the most
informed — it sees supply, demand, clusters, costs, and arcs — but it
only outputs passage assignments, not editorial rationale. The
downstream phases don't benefit from the transport layer's reasoning.
