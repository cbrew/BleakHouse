# Five-Way Comparison: Design and Hypotheses

**Date:** 2026-03-10
**Status:** Data collection in progress (54/100 conditions complete)

## The Core Question

When an LLM generates a podcast script about Bleak House, where does the quality come from? Three possible sources contribute:

1. **Prior knowledge** — Sonnet has read Bleak House in its training data. It can discuss characters, themes, and plot without any passage input at all.
2. **Passage presence** — Having *some* Dickens text as grounding context, regardless of which text is selected.
3. **Passage selection quality** — Having the *right* text, chosen to match expert interests, character arcs, and episode structure.

These sources are nested. You cannot have (3) without (2), and you cannot have (2) without (1). The five experimental conditions form a ladder that progressively adds each source:

```
No passages     → pure prior knowledge (1 only)
Random passages → prior knowledge + grounding context (1 + 2)
Plain RAG       → prior knowledge + text-similarity selection (1 + 2 + weak 3)
Embedding       → prior knowledge + enriched selection + LLM curation (1 + 2 + strong 3)
Transport       → prior knowledge + enriched selection + optimization (1 + 2 + strong 3)
```

## The Five Conditions

### No Passages (`nop_v*`)
Phase 3 receives expert personas and segment structure but zero passages. The prompt tells the LLM: "No specific passages are assigned. Drawing on your knowledge of Bleak House by Charles Dickens, produce a rich discussion that fits this segment's theme." This isolates the LLM's prior knowledge — what it can produce from training alone.

### Random Passages (`rand_v*`)
32 passages drawn uniformly at random from Bleak House chapters (c1-c67), seeded deterministically by panel composition for reproducibility. Assigned round-robin to experts with no attempt to match interests. Distributed to segments by filling each to capacity. Enrichment metadata (provisions, themes, best_quote) passes through to Phase 3 because the other pipelines also provide it — but it played no role in selection.

### Plain RAG (`rag_v*`)
Expert persona descriptions are embedded via OpenAI text-embedding-3-small. Passages are embedded using raw text only (no enrichment context). Top-k passages per expert are selected by cosine similarity. No LLM reasoning, no arc constraints, no structural obligations. This tests whether simple text-level relevance matching captures enough for good scripts.

### Embedding (`emb_v*`)
Passages are retrieved using contextual embeddings (text + enrichment context), then an LLM curates the selection using chain-of-thought reasoning about expert demands, arc coverage, and segment fit. Uses enrichment metadata throughout. This is the "smart retrieval" condition.

### Transport (`v*`)
Passages are assigned via min-cost flow optimization over enrichment metadata. Expert demands, character arc obligations, provision dimensions, and interest scores all feed into edge costs. The optimizer finds a globally optimal assignment subject to capacity and structural constraints. This is the "full system" condition.

## What Each Comparison Isolates

### No-passages vs Random: Does grounding text help at all?

If the LLM already knows Bleak House well from training, random passages might add noise rather than signal. The passages could even *hurt* by anchoring the discussion on irrelevant material that distracts from what the LLM already knows.

- **Expected:** Random is better — some grounding helps, even irrelevant grounding.
- **Surprise if:** No-passages is comparable or better. That would mean the LLM's training knowledge is sufficient and passages are more scaffold than substance.
- **Strong surprise if:** Random is actively worse than no-passages. The LLM gets confused by irrelevant material and produces less coherent scripts than when drawing purely on memory.

### Random vs Plain RAG: Does passage identity matter?

Plain RAG uses cosine similarity between expert profiles and passage text — a minimal relevance signal. Random uses no relevance signal at all. The gap between them measures whether *which* passages you select matters, or just that you select *some*.

- **Expected:** Plain RAG is better — even simple relevance matching helps.
- **Surprise if:** Random is comparable. That would mean passage identity doesn't matter much — the LLM uses any Dickens text as a springboard for what it already knows. This would be a damaging finding for the entire enrichment enterprise.

### Plain RAG vs Embedding/Transport: Does enrichment add value?

Both enriched pipelines use 20-field passage metadata (provisions, themes, characters, interest scores, emotional register) to guide selection. Plain RAG uses only text similarity. The gap measures whether editorial annotation of passages improves downstream script quality.

- **Expected:** Enriched pipelines produce more character-dense, structurally coherent scripts.
- **Surprise if:** Plain RAG matches enriched pipelines. That would mean text-embedding similarity captures the same information as 20-field enrichment, making the enrichment pipeline (hours of Haiku calls, ~$12) unnecessary for this application.

### Embedding vs Transport: Does optimization beat LLM curation?

Both use the same enrichment metadata but differ in how they assign passages. Transport uses min-cost flow with hard constraints (arc coverage, demand satisfaction, capacity limits). Embedding uses LLM reasoning to curate a shortlist.

- **Already partially answered:** They produce genuinely different selections (Jaccard 0.047) with different strengths. Transport favours character density (+26% character mentions), embedding favours text fidelity (90% vs 72% quote recovery). Neither clearly dominates.
- **What 20-panel data adds:** Whether these differences are robust across all panel compositions, or whether some panels equalize the two.

## Metrics and What They Probe

| Metric | What it tests | Key comparison |
|--------|--------------|----------------|
| **Character mention density** (per 1k words) | Does the script name specific characters? | No-passages vs others: can the LLM populate a cast from memory? |
| **Unique characters mentioned** | Character diversity in discussion | Transport vs others: do arc constraints broaden the cast? |
| **Quote count** | How many direct Dickens quotes appear? | All conditions: does having source text increase quoting? |
| **Quote recovery rate** | Are quotes from assigned passages actually used? | Random vs enriched: does relevant material get quoted more? (N/A for no-passages) |
| **Quote validity** | Are "quotes" real Dickens or confabulated? | No-passages specifically: does the LLM hallucinate quotes? |
| **Chapter references** | Does the script cite specific chapters? | Random vs RAG: does relevant selection ground discussion in specific locations? |
| **Vocabulary signature** (Kilgarriff G2 keywords) | Does expert identity persist across conditions? | All conditions: is expert persona the dominant force regardless of passages? |
| **Character Jaccard** (cross-condition, same expert) | Do same-expert scripts discuss the same characters? | Transport vs no-passages: if sets converge, prior knowledge dominates |
| **Sentence specificity** | Are claims concrete or vague? | Random vs enriched: does relevant material produce more specific analysis? |
| **Textual deixis** (per 1k words) | References to specific textual locations | No-passages vs others: does the LLM produce vague or specific references without source text? |

## Hypotheses and Possible Outcomes

### Hypothesis 1: Prior knowledge dominates everything

If no-passages scripts are 80%+ as good on character density, specificity, and structural coherence, then the entire passage selection apparatus — enrichment, optimization, curation — is window dressing. The LLM already knows enough to produce rich literary discussion.

**What to look for:** Character mention density in no-passages scripts close to transport/embedding levels. Vocabulary signatures identical across all conditions. High sentence specificity even without source text.

**Implication:** The value of the pipeline is in *structure* (segment design, expert personas, episode format) rather than *content* (passage selection). This would redirect the project toward prompt engineering and away from retrieval.

### Hypothesis 2: Passages help, but selection quality doesn't

If random passages produce scripts comparable to transport/embedding, then the value is in *grounding* (having concrete text to quote and react to) rather than *relevance* (having the right text for the expert and segment). Any Dickens passage serves as a springboard for the LLM's prior knowledge.

**What to look for:** Random and enriched pipelines comparable on character density and specificity. Gap primarily between no-passages and everything-else, not between random and enriched.

**Implication:** Simple RAG is sufficient. The enrichment pipeline, min-cost flow solver, and LLM curation add engineering complexity without downstream benefit.

### Hypothesis 3: Expert persona overwhelms passage effects

We already have moderate evidence: vocabulary signatures (G2 keywords) are stable for the same expert across transport and embedding pipelines, despite completely different input passages (vocabulary cosine 0.549, character Jaccard 0.430). If this pattern extends to all five conditions — Hartley always discusses narrative structure, Blackstone always discusses law, regardless of whether they receive relevant passages, irrelevant passages, or no passages at all — then the *prompt* is doing most of the work.

**What to look for:** G2 keyword lists for each expert stable across all 5 conditions. Cross-condition vocabulary cosine for same-expert scripts ≥ 0.5. Within-condition cross-expert cosine much lower.

**Implication:** The expert persona prompt is the primary lever for script quality and character. Passage selection influences *details* (which specific scenes get discussed) but not *identity* (what the expert cares about and how they talk).

### Hypothesis 4: No-passages confabulates badly

The LLM might generate plausible-sounding but incorrect quotes, misattribute plot points to wrong characters, or blend Bleak House with other Dickens novels. It might reference chapters that don't contain the events described. This would be strong evidence that passages provide essential *accuracy* even if they don't change the *style* or *structure* of discussion.

**What to look for:** Quote validity audit — cross-reference "quotes" in no-passages scripts against the full Bleak House text. Character-event attribution errors. References to non-existent chapters or scenes.

**Implication:** Passages serve as a factual anchor. The LLM's knowledge of Bleak House is broad but imprecise, and source text prevents hallucination. This would be the strongest case for passage-based generation.

### Hypothesis 5: Random passages actively hurt

If random passages produce *worse* scripts than no passages — e.g., the LLM gets anchored on irrelevant material, tries to discuss passage content that doesn't fit the segment theme, produces incoherent transitions — that would mean the LLM's prior knowledge is *better* than noise-contaminated grounding.

**What to look for:** No-passages scoring higher than random on coherence, specificity, or character density. Random scripts showing more topic drift or forced relevance to unrelated passages.

**Implication:** Passage selection quality is not just helpful but *necessary*. Bad passages are worse than no passages. This would be the strongest case for sophisticated selection (enrichment + optimization).

### Hypothesis 6: Enrichment value is captured by embeddings

If plain RAG (text similarity only) matches the enriched pipelines on all metrics, then the contextual embeddings already capture the information that enrichment metadata provides. The 20-field enrichment per passage (provisions, themes, characters, interest scores, emotional register) adds no information beyond what's latent in the text.

**What to look for:** Plain RAG and enriched pipelines indistinguishable on character density, vocabulary signature, quote recovery. Gap only between random/no-passages and the three selection-based methods.

**Implication:** Text embeddings are better than expected. The enrichment pipeline's value was in making information *explicit* for the min-cost flow solver, not in discovering new information. A simpler pipeline (embed and retrieve) would suffice.

## Character Arc Hypothesis

### Background

The transport pipeline encodes character arc obligations as hard constraints: specific characters (Esther, Richard, Lady Dedlock, Jo, Jarndyce) must appear in designated proportions. The embedding pipeline receives these as soft preferences in its curation prompt. Plain RAG, random, and no-passages have no arc awareness at all.

### Hypothesis

Character arcs are the unique structural contribution of the transport pipeline. Without them, scripts will still discuss major characters (because the LLM knows they're important), but will over-represent the most famous characters (Esther, Lady Dedlock) and under-represent less prominent ones (Jo, Richard in his declining arc, Jarndyce's quiet generosity).

### What to measure

- **Character distribution entropy:** Higher entropy = more even coverage across characters. Transport should have highest entropy because arc constraints force coverage of less-prominent characters.
- **Long-tail character coverage:** How many characters mentioned only 1-2 times? Transport should surface more minor characters through arc-adjacent passages.
- **Character co-occurrence patterns:** Do certain characters always appear together? Arc constraints might break default co-occurrence patterns (e.g., discussing Jo independently of Lady Dedlock, or Richard independently of Ada).
- **Per-character mention rates across conditions:** For each of the ~15 most-mentioned characters, how does mention rate change from no-passages → random → RAG → embedding → transport?

### Expected gradient

```
No-passages:  Dominated by Esther, Lady Dedlock, Jarndyce (most famous)
Random:       Similar to no-passages but with some random character surfacing
Plain RAG:    Skewed toward characters in expert persona descriptions
Embedding:    Broader coverage from enrichment-aware curation
Transport:    Broadest coverage, enforced by arc constraints
```

**Surprise if:** No-passages achieves broad character coverage anyway — the LLM knows the full cast and distributes attention without prompting. This would diminish the unique value of arc constraints.

**Surprise if:** Plain RAG matches transport on character diversity — text similarity naturally surfaces diverse passages because different characters appear in different textual contexts, achieving arc-like coverage without explicit arc modeling.

## Expert Profile Hypothesis

### Background

Each expert has a persona description (role, speaking style, intellectual focus) and a set of demands (specific topics they want passages about). The persona shapes *how* the expert talks. The demands shape *what passages* they receive (in transport and embedding). In plain RAG, the persona description serves as the retrieval query. In random and no-passages, demands are irrelevant to selection.

### Hypothesis

Expert identity is the strongest single force shaping script content, stronger than passage selection method. The persona prompt creates a "lens" through which the expert interprets any material. Hartley will find narrative technique in any passage. Blackstone will find legal implications in any passage. Woodcourt will find performance possibilities in any passage.

### What to measure

- **Vocabulary signature stability:** For each expert, compute G2 keywords from their speech across all 5 conditions. Measure pairwise overlap. If the same keywords appear regardless of condition, persona dominates.
- **Cross-condition vocabulary cosine:** For the same expert, compute TF-IDF vectors of their speech in each condition. Cosine between conditions measures how much the expert's language changes.
- **Within-condition cross-expert divergence:** For a given condition, how different are the three experts' vocabularies from each other? If experts are always distinct (even with random/no passages), persona is the differentiator.
- **Demand satisfaction across conditions:** In transport, expert demands are explicitly satisfied by passage selection. In no-passages, the expert must satisfy their own demands from memory. Does the expert still discuss their demanded topics? If so, the demands are redundant — the persona description already encodes them.

### Expected pattern

```
                    Same-expert     Cross-expert
                    cross-condition within-condition
                    similarity      divergence
Expert persona      HIGH            HIGH            ← persona dominates
strong:

Expert persona      LOW             LOW             ← passages dominate
weak:
```

We expect expert persona to be strong — the existing data (vocabulary cosine 0.549 across transport/embedding for same expert) already suggests this. The question is whether it remains strong even in the extreme conditions (no-passages, random).

**Key test:** If Blackstone's vocabulary signature in no-passages scripts is recognizably "Blackstone" (legal language, institutional critique, Chancery focus), then the persona prompt alone creates his identity. The passages he receives in transport/embedding refine his discussion but don't define it.

**Surprise if:** Expert vocabularies collapse in no-passages — without specific passages to react to, experts become generic and interchangeable. This would mean passages are essential not just for content but for *differentiation* — the persona prompt alone isn't enough to create distinct voices.

**Surprise if:** Expert vocabularies shift substantially with random passages — irrelevant material pulls experts off their natural topics more than having no material at all. This would suggest a tension between persona and passage effects, where bad passages can override persona more than absent passages can.

## Analysis Structure

### Wave 1: Headline comparison (once 6+ matched panels available)

A single script that, for every panel where all 5 conditions are complete:
- Extracts character mentions, quotes, chapter references, word counts
- Computes per-condition averages and confidence intervals
- Produces a comparison table answering: does the ladder matter?

### Wave 2: Expert and character deep dives

- G2 vocabulary signatures per expert per condition
- Character distribution entropy per condition
- Cross-condition convergence matrices (vocabulary cosine, character Jaccard)
- Demand satisfaction audit for no-passages (does the expert address their demands from memory?)

### Wave 3: Accuracy audit (if no-passages is surprisingly strong)

- Quote validity: cross-reference all "quotes" in no-passages scripts against the Bleak House corpus
- Event attribution: do characters get associated with correct plot events?
- Chapter reference accuracy: do cited chapters actually contain the described content?

## Evidence Inventory (Prior to Five-Way)

These findings from the transport-vs-embedding comparison inform our expectations:

| Finding | Evidence | Implication for five-way |
|---------|----------|--------------------------|
| Passage sets are disjoint (Jaccard 0.047) | 8+ matched pairs | Selection method matters — but does *any* selection beat random? |
| Transport: +26% character mentions | 8 pairs, consistent | Arc constraints surface more characters — will this gap widen against no-passages? |
| Embedding: 90% vs 72% quote recovery | 8 pairs | Text-faithful selection helps quoting — what happens with random passages? |
| Expert vocabulary signatures stable across pipelines | G2 keywords, 20+ runs | Persona dominates — will it hold across 5 conditions? |
| Vocabulary cosine 0.549 for same expert across pipelines | 8 matched pairs | Partial convergence despite different passages — how far does this extend? |
| Embedding-space distance between pipeline selections indistinguishable from noise | MMD test, 1.1× null ratio | Passages are semantically similar even when disjoint — will random passages be equally close? |
