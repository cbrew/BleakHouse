# Five-Way Pipeline Comparison: Methodology and Provisional Results

**Date:** 2026-03-10 (updated)
**Status:** Complete — 100/100 conditions, all 20 panels × 5 conditions
**Basis:** 20 panels with all 5 conditions (full balanced design)

## 1. Research Question

When an LLM generates a literary podcast script about a novel it has encountered in training, what are the relative contributions of:

1. **Prior knowledge** — what the model already knows about the novel
2. **Passage presence** — having some text from the novel as grounding context
3. **Passage selection quality** — having text chosen to match the discussion's needs

These factors are nested: (3) requires (2), which requires (1). Our experimental design constructs five conditions that progressively add each factor, forming a ladder from pure prior knowledge to fully optimised passage selection.

## 2. Experimental Design

### 2.1 The Five Conditions

All conditions share the same Phase 0 (LLM-designed segment structure) and Phase 3 (Sonnet script generation with structured output). They differ only in what passages, if any, are provided to Phase 3.

**No Passages (`nop_v*`).** Phase 3 receives expert personas and segment templates but zero passages. The prompt instructs: "No specific passages are assigned. Drawing on your knowledge of Bleak House by Charles Dickens, produce a rich discussion that fits this segment's theme. Reference specific chapters, characters, scenes, and quotes from the novel as you remember them." This isolates the LLM's prior knowledge.

**Random Passages (`rand_v*`).** 32 passages drawn uniformly at random from Bleak House chapters c1–c67, using a deterministic seed derived from the panel composition (SHA-256 hash of sorted expert names). Passages are assigned round-robin to experts with no relevance matching. Enrichment metadata (provisions, themes, best_quote) passes through to Phase 3 because all other conditions also provide it. This tests whether passage *identity* matters or just *presence*.

**Plain RAG (`rag_v*`).** Expert persona descriptions are embedded via OpenAI text-embedding-3-small. Passage embeddings use raw text only — no enrichment context, themes, or character metadata. Top-k passages per expert are selected by cosine similarity between the expert's profile embedding and each passage embedding. No LLM reasoning, no arc constraints, no structural obligations. This is minimal relevance-based selection.

**Embedding (`emb_v*`).** Passages are retrieved using contextual embeddings (text + enrichment context), then an LLM (Sonnet) curates the selection using chain-of-thought reasoning about expert demands, character arc coverage, and segment fit. The curation prompt includes explicit obligations for arc coverage, structural diversity, and expert-demand satisfaction. This is "smart retrieval."

**Transport (`v*`).** Passages are assigned via min-cost flow optimisation over enrichment metadata. Expert demands, character arc obligations (Esther, Richard, Jo, Lady Dedlock, Jarndyce), provision dimensions (7 fields including character development, plot advancement, social critique, humour), and interest scores all feed into edge costs. A global optimum is found subject to capacity and structural constraints. This is the "full system."

### 2.2 Panel Design

Each condition is run across 20 expert panels — all C(6,3) = 20 possible 3-expert combinations drawn from 6 experts: Eleanor Hartley (literary critic), James Blackstone (legal historian), Caroline Woodcourt (performance scholar), Edmund Leigh (conservative critic), Daniel Rosen (Marxist sociologist), Oliver Trevelyan (actor/director). Each expert appears in exactly 10 of the 20 panels.

The balanced panel design controls for expert composition effects and allows per-expert analysis across conditions. Panel naming follows the transport convention (v01_baseline through v30_woodcourt_edmund_trevelyan).

### 2.3 Controlled Variables

Across all five conditions and all 20 panels:

- **Phase 0:** Identical segment design process (Haiku LLM designs 6–7 segments per episode)
- **Phase 3:** Identical script generation (Sonnet, structured output, same system prompt, same persona descriptions, same output schema)
- **Expert personas:** Identical descriptions, speaking styles, and role definitions
- **Output format:** Same EpisodeSegment Pydantic schema with typed utterances

The only experimental manipulation is what appears in the "Assigned Passages" section of the Phase 3 user prompt.

### 2.4 Data Collection Status

| Condition | Complete | Target |
|-----------|----------|--------|
| Transport | 20/20 | 20 |
| Embedding | 20/20 | 20 |
| Plain RAG | 20/20 | 20 |
| No Passages | 20/20 | 20 |
| Random | 20/20 | 20 |
| **Total** | **100/100** | **100** |

All 20 panels have all 5 conditions complete. The balanced design is fully realised.

## 3. Metrics

### 3.1 Character Mention Density

Count of character name mentions per 1,000 words of script text. Character names are matched case-insensitively against a list of 23 Bleak House characters: Esther, Richard, Ada, Lady Dedlock, Sir Leicester, Jarndyce, Tulkinghorn, Jo, Bucket, Guppy, Skimpole, Woodcourt (character), Caddy, Krook, Nemo, Hortense, Charley, Rosa, George, Smallweed, Snagsby, Jellyby, Dedlock. This measures how character-populated the discussion is.

### 3.2 Unique Characters

Count of distinct characters mentioned per episode. Measures breadth of character coverage.

### 3.3 Character Distribution Entropy

Shannon entropy H = −Σ p(c) log₂ p(c) over the character mention distribution. Higher entropy indicates more even coverage across characters; lower entropy indicates concentration on a few dominant characters. Maximum possible entropy for 23 characters is log₂(23) ≈ 4.52.

### 3.4 Quote Count

Number of direct quotations (text within quotation marks attributed to a Dickens character or narrated as Dickens's prose) per episode. Counted from the structured output `quote_reading` and `quote_setup` sentence types.

### 3.5 Total Word Count

Total words in the generated script. A proxy for episode length and verbosity.

### 3.6 Vocabulary Signature (per expert)

TF-IDF vectors computed from all words spoken by a given expert across episodes within a condition. Top-10 distinctive words per expert per condition identify the expert's vocabulary signature. Cross-condition cosine similarity for the same expert measures how much expert identity persists across conditions.

### 3.7 Existing Metrics (Transport vs Embedding only)

From prior two-way analysis (8 matched pairs):
- **Quote recovery rate:** Fraction of assigned passages' `best_quote` fields appearing in the script
- **Chapter reference density:** References to specific chapter numbers per 1,000 words
- **Sentence specificity:** Proportion of sentences containing a proper noun or quoted phrase
- **Textual deixis:** Close-reading markers per 1,000 words

## 4. Results

### 4.1 Aggregate Comparison

Mean values across all 20 panels per condition:

| Metric | Transport | Embedding | Plain RAG | No Passages | Random |
|--------|-----------|-----------|-----------|-------------|--------|
| Panels (n) | 20 | 20 | 20 | 20 | 20 |
| Words per episode | 9,267 | 9,958 | 9,403 | 10,561 | 8,597 |
| Quotes per episode | 40.8 | 43.8 | 37.7 | 41.2 | 33.6 |
| Char mentions / 1k words | 22.32 | 17.59 | 23.05 | 23.82 | 22.07 |
| Unique characters | 14.4 | 11.6 | 16.2 | 16.0 | 18.5 |
| Character entropy | 3.432 | 2.905 | 3.483 | 3.283 | 3.708 |

### 4.2 Pairwise Differences (relative to Transport)

| vs Transport | Char Density | Entropy | Word Count | Quotes |
|-------------|-------------|---------|------------|--------|
| Embedding | −21% | −15% | +7% | +7% |
| Plain RAG | +3% | +1% | +1% | −8% |
| No Passages | +7% | −4% | +14% | +1% |
| Random | −1% | +8% | −7% | −18% |

### 4.3 Per-Panel Consistency (all 20 five-way panels)

| Panel | Transport | Embedding | RAG | No Passages | Random |
|-------|-----------|-----------|-----|-------------|--------|
| **Character density / 1k words** |
| v01_baseline | 19.4 | 15.5 | 20.2 | 28.7 | 25.9 |
| v10_conservative | 23.6 | 17.9 | 27.6 | 24.3 | 24.7 |
| v11_marxist | 23.8 | 13.0 | 22.9 | 27.1 | 22.1 |
| v12_radical_panel | 23.2 | 21.5 | 28.3 | 26.7 | 23.6 |
| v14_trevelyan_for_woodcourt | 20.6 | 18.9 | 18.5 | 24.2 | 22.8 |
| v15_trevelyan_for_hartley | 21.6 | 21.1 | 22.4 | 23.1 | 20.1 |
| v16_trevelyan_for_blackstone | 24.4 | 15.9 | 22.4 | 23.6 | 23.0 |
| v17_trevelyan_edmund | 24.8 | 16.1 | 26.5 | 25.5 | 20.8 |
| v18_trevelyan_rosen | 25.1 | 19.2 | 23.6 | 25.1 | 19.1 |
| v19_all_swapped | 20.7 | 17.8 | 25.3 | 21.9 | 25.2 |
| v21_hartley_blackstone_edmund | 22.8 | 16.3 | 22.3 | 25.5 | 19.4 |
| v22_hartley_blackstone_rosen | 20.7 | 19.2 | 20.4 | 24.7 | 24.0 |
| v23_hartley_woodcourt_rosen | 23.6 | 13.8 | 23.7 | 28.3 | 24.1 |
| v24_hartley_edmund_rosen | 25.0 | 18.5 | 24.1 | 20.1 | 23.1 |
| v25_hartley_rosen_trevelyan | 21.6 | 17.0 | 20.3 | 23.5 | 16.2 |
| v26_blackstone_woodcourt_edmund | 20.1 | 20.5 | 23.4 | 23.0 | 18.4 |
| v27_blackstone_edmund_rosen | 21.3 | 17.6 | 20.8 | 19.8 | 21.5 |
| v28_blackstone_edmund_trevelyan | 19.6 | 16.8 | 22.0 | 17.8 | 20.7 |
| v29_blackstone_rosen_trevelyan | 21.8 | 16.3 | 18.7 | 22.2 | 21.2 |
| v30_woodcourt_edmund_trevelyan | 22.6 | 19.0 | 27.6 | 21.4 | 25.6 |
| **Character entropy** |
| v01_baseline | 3.33 | 2.92 | 3.33 | 3.09 | 3.98 |
| v10_conservative | 3.40 | 2.95 | 3.56 | 3.35 | 3.73 |
| v11_marxist | 3.55 | 3.13 | 3.40 | 3.33 | 3.85 |
| v12_radical_panel | 3.40 | 3.17 | 3.41 | 3.39 | 3.62 |
| v14_trevelyan_for_woodcourt | 3.43 | 2.86 | 3.64 | 3.28 | 3.73 |
| v15_trevelyan_for_hartley | 3.25 | 2.87 | 3.44 | 3.42 | 3.68 |
| v16_trevelyan_for_blackstone | 3.41 | 2.87 | 3.45 | 3.44 | 3.54 |
| v17_trevelyan_edmund | 3.48 | 2.98 | 3.63 | 3.23 | 3.87 |
| v18_trevelyan_rosen | 3.53 | 2.96 | 3.55 | 3.53 | 3.97 |
| v19_all_swapped | 3.32 | 2.97 | 3.47 | 3.51 | 3.56 |
| v21_hartley_blackstone_edmund | 3.53 | 3.02 | 3.49 | 3.17 | 3.66 |
| v22_hartley_blackstone_rosen | 3.39 | 2.80 | 3.53 | 3.28 | 3.67 |
| v23_hartley_woodcourt_rosen | 3.27 | 3.08 | 3.25 | 3.35 | 3.76 |
| v24_hartley_edmund_rosen | 3.33 | 2.89 | 3.57 | 3.04 | 3.79 |
| v25_hartley_rosen_trevelyan | 3.67 | 2.92 | 3.77 | 3.24 | 3.30 |
| v26_blackstone_woodcourt_edmund | 3.36 | 3.02 | 3.35 | 3.10 | 3.70 |
| v27_blackstone_edmund_rosen | 3.49 | 2.94 | 3.38 | 3.12 | 3.62 |
| v28_blackstone_edmund_trevelyan | 3.63 | 1.87 | 3.54 | 3.23 | 3.78 |
| v29_blackstone_rosen_trevelyan | 3.36 | 3.06 | 3.36 | 3.41 | 3.52 |
| v30_woodcourt_edmund_trevelyan | 3.53 | 2.83 | 3.56 | 3.12 | 3.81 |

Across all 20 five-way panels, embedding has the lowest character density in 15/20 cases and the lowest entropy in 20/20 cases. Random has the highest entropy in 19/20 cases. These patterns are robust across all panel compositions.

### 4.4 Character Focus by Pipeline

Top 5 characters mentioned (aggregated across all matched panels):

| Rank | Transport | Embedding | RAG | No Passages | Random |
|------|-----------|-----------|-----|-------------|--------|
| 1 | Richard (392) | Jo (446) | Esther (416) | Esther (326) | Esther (266) |
| 2 | Esther (373) | Richard (426) | Richard (355) | Jo (275) | Richard (143) |
| 3 | Jarndyce (310) | Dedlock (283) | Jarndyce (306) | Richard (263) | Jarndyce (113) |
| 4 | Jo (307) | Lady Dedlock (258) | Dedlock (279) | Jarndyce (212) | Dedlock (99) |
| 5 | Tulkinghorn (195) | Esther (250) | Lady Dedlock (235) | Dedlock (180) | George (85) |

Notable patterns:
- **Embedding** uniquely foregrounds Jo and the Dedlock family; Esther drops to 5th
- **Transport** is the only condition where Tulkinghorn appears in the top 5
- **Random** uniquely surfaces George (Trooper George) and has the most even distribution; also surfaces Smallweed (65) and Guppy (69) — characters absent from other conditions' top ranks
- **No-passages** defaults to the novel's most famous characters (Esther, Jo, Richard)
- **RAG** surfaces Skimpole (195) and Sir Leicester (167) more prominently than other conditions, suggesting text-similarity retrieval picks up passages featuring these secondary characters
- **RAG** and **Transport** share a similar top-5 structure, differing mainly in the Dedlock/Tulkinghorn balance

### 4.5 Expert Identity Across Conditions

#### 4.5.1 Cross-Condition Vocabulary Cosine (same expert)

Mean pairwise cosine similarity between an expert's TF-IDF vocabulary vectors across conditions (averaged across all 6 experts):

| Pair | Mean Cosine | Interpretation |
|------|-------------|----------------|
| Embedding ↔ Transport | 0.44 | Most similar — same enrichment base, different optimisation |
| No Passages ↔ Transport | 0.36 | Moderate — no input text, still recognisable |
| No Passages ↔ Embedding | 0.40 | Moderate — prior knowledge aligns with enriched selection |
| RAG ↔ Transport | 0.35 | Moderate — different selection method, same expert voice |
| RAG ↔ Embedding | 0.37 | Moderate |
| No Passages ↔ RAG | 0.31 | Moderate-low |
| Random ↔ Transport | 0.30 | Low — random passages disrupt expert vocabulary |
| Random ↔ RAG | 0.31 | Low |
| Random ↔ Embedding | 0.25 | Low |
| Random ↔ No Passages | 0.26 | Low — random is the most disruptive condition |

**Key finding:** Random passages disrupt expert identity *more* than having no passages at all. The no-passages ↔ transport cosine (0.36) exceeds the random ↔ transport cosine (0.30) consistently. Irrelevant grounding text actively interferes with the persona prompt. The embedding ↔ transport pair remains the most similar (0.44), reflecting their shared enrichment foundation despite different assignment algorithms.

#### 4.5.2 Expert Vocabulary Signatures

Distinctive words (top TF-IDF terms) for each expert, showing persistence across conditions:

**James Blackstone** (legal historian): Across all conditions, his vocabulary centres on institutional and legal language. In transport: *kenge, oath, trickery, spoliation, inheritance*. In no-passages: *jennens, disease, scarecrow, graveyard, pauper*. In random: *smallweed, george, guppy, bucket* (displaced by random passage content). The legal focus persists in transport, embedding, RAG, and no-passages but is disrupted in random.

**Eleanor Hartley** (literary critic): Consistently uses narrative and structural vocabulary. In transport: *evermore, afar, piper, hope, court*. In no-passages: *skimpole, dead, death, voices, relentless*. The analytical lens persists but the specific content shifts with available material.

**Oliver Trevelyan** (actor/director): Performance-oriented vocabulary across conditions. In transport: *afar, comic, tulkinghorn, extraordinary, constancy*. In embedding: *chapter, city, says, moonlight, voice*. Highest cross-condition cosine (embedding ↔ transport: 0.577), suggesting his performance focus is the most passage-independent.

#### 4.5.3 Per-Expert Quote Patterns

Average quotes per expert per condition (n = sample size in parentheses):

| Expert | Transport | Embedding | RAG | No Passages | Random |
|--------|-----------|-----------|-----|-------------|--------|
| Caroline Woodcourt | 14.9 (7) | 17.0 (6) | 13.6 (7) | 16.5 (6) | 13.0 (6) |
| Eleanor Hartley | 15.4 (7) | 17.3 (7) | 12.6 (7) | 11.0 (4) | 11.2 (4) |
| James Blackstone | 10.8 (6) | 12.2 (5) | 11.2 (6) | 8.2 (4) | 8.2 (4) |
| Oliver Trevelyan | 17.0 (6) | 17.3 (6) | 14.7 (6) | 18.0 (3) | 11.7 (3) |
| Edmund Leigh | 9.6 (5) | 11.2 (5) | 10.8 (5) | 11.5 (2) | 13.5 (2) |
| Daniel Rosen | 10.8 (5) | 14.5 (4) | 12.2 (5) | 12.0 (2) | 11.0 (2) |

Blackstone quotes least in no-passages and random (8.2) and most in embedding (12.2). His legal-institutional focus has fewer memorable quotable passages in the LLM's training memory, so he benefits most from being given actual text to quote from.

Trevelyan (the actor) quotes at consistently high rates in passage-provided conditions (14.7–17.3) and peaks in no-passages (18.0), but drops sharply with random passages (11.7). This suggests his performance persona generates quotation fluently from memory but is disrupted by irrelevant material — mirroring the broader random-disruption pattern.

Embedding consistently produces the highest or near-highest quote counts for every expert, reinforcing its profile as the "verbose, quote-heavy" condition.

### 4.6 Prior Results (Transport vs Embedding, 8 Matched Pairs)

These results from a more mature dataset inform interpretation of the five-way data:

| Metric | Transport | Embedding |
|--------|-----------|-----------|
| Quote recovery rate | 72% | 90% |
| Char mentions / 1k words | 22.1 | 17.6 |
| Chapter references / 1k words | 0.67 | 1.35 |
| Sentence specificity | 0.867 | 0.873 |
| Textual deixis / 1k words | 2.6 | 2.8 |
| Passage overlap (Jaccard) | 0.047 (near-zero) | — |
| Within-expert vocabulary cosine | 0.549 | — |
| Within-expert character Jaccard | 0.430 | — |

### 4.7 Material Similarity (Transport vs Embedding, Per Expert)

From the 4-tier material similarity analysis:

| Tier | Measure | Value | Interpretation |
|------|---------|-------|----------------|
| 1a | Provision centroid distance | 1.85 / 5.3 max | Moderately different metadata profiles |
| 1b | Character JSD | 0.518 / 0.69 max | Substantially different character coverage |
| 1c | Theme JSD | 0.411 / 0.69 max | Moderately different thematic focus |
| 1d | Chapter Jaccard | 0.074 | Near-zero chapter overlap |
| 2 | TF-IDF nearest-neighbour | 0.068 same-expert, 0.126 diff-expert | Cross-pipeline passages are *less* similar to each other than to different-expert passages — genuinely different material |
| 3 | Script vocabulary cosine | 0.549 | Partial convergence in scripts despite different input |
| 3 | Script character Jaccard | 0.430 | Moderate character overlap in output |
| 4 | Embedding space MMD | 1.1× null ratio | Distributional difference indistinguishable from noise |

## 5. Discussion

### 5.1 The Passage Ladder: Does More Sophistication Help?

The five conditions were designed to test whether each step up the ladder — from no passages to random to RAG to enriched selection to optimisation — improves script quality. The provisional data challenges this linear expectation.

**No-passages is surprisingly strong on surface metrics but unreliable on quotation.** At 23.82 character mentions per 1k words, no-passages produces the *highest* character density of any condition. The LLM draws heavily on its training knowledge of Bleak House, name-dropping characters more frequently than when anchored to specific passages. However, its entropy (3.283) is lower than RAG (3.483) or random (3.708), indicating concentration on the most canonical characters. And critically, its adjusted quote verification rate (52.4%) is dramatically lower than all passage-grounded conditions (91–96%) — see Section 6.

**Random is surprisingly good on diversity.** Random passages produce the highest character entropy (3.708) and most unique characters per episode (18.5). Random sampling naturally covers more of the novel than any intentional selection method, surfacing characters like Smallweed, George, Caddy, and Guppy that arc-constrained transport passes over.

**Plain RAG closely matches transport.** Character density (23.05 vs 22.32), entropy (3.483 vs 3.432), and word count (9,403 vs 9,267) are all within 3% of transport across the full 20-panel dataset. Simple text-similarity retrieval produces scripts statistically indistinguishable from optimised selection on these aggregate metrics.

**Embedding is the unexpected outlier.** Rather than sitting between RAG and transport on the sophistication ladder, embedding produces distinctly different scripts: lowest character density (17.59), lowest entropy (2.905), fewest unique characters (11.6), but highest word count (9,958) and most quotes (43.8). The LLM curation step appears to concentrate selections on high-drama, high-interest passages (Jo's story, the Dedlock mystery, Richard's decline), producing verbose scripts about fewer characters rather than broader coverage.

### 5.2 Character Arc Constraints: Structured Focus vs Natural Breadth

**Prediction:** Transport's arc constraints should produce the broadest, most even character coverage.

**Finding:** Transport produces the most *structurally intentional* character coverage, but not the broadest. Arc constraints ensure designated characters (Esther, Richard, Jo, Lady Dedlock, Jarndyce) appear in the proportions the episode structure demands. But this comes at the cost of characters outside the arc system — random passages surface more minor characters simply by sampling more widely.

The value of arc constraints is not *breadth* but *coherence*. Transport is the only condition where Tulkinghorn consistently appears in the top 5 mentions — because his role in the Lady Dedlock arc makes him structurally important. Random produces more character names but less narrative coherence around them.

### 5.3 Expert Identity: The Dominant Force

**Prediction:** Expert persona prompts shape script content more than passage selection.

**Finding:** Strongly supported. Same-expert vocabulary cosine across conditions averages 0.35–0.50 for intentional selection methods and 0.41 for no-passages, indicating recognisable expert identity even without any source text. Blackstone always gravitates to legal and institutional language. Hartley always analyses narrative structure. Trevelyan always foregrounds performance and voice.

**The random disruption effect.** Random passages are the only condition that substantially disrupts expert identity (cosine 0.24–0.29 with other conditions). When given irrelevant material, experts are pulled toward discussing whatever they've been given rather than what their persona would naturally focus on. This means random passages are not just neutral grounding — they actively compete with persona for control of the discussion.

This creates a paradox: no passages preserves expert identity better than random passages, while random passages produce higher character diversity. The best scripts may require expert-relevant passage selection not primarily for content accuracy, but to *avoid undermining the expert persona*.

### 5.4 The Embedding Pipeline Anomaly

Embedding's consistent underperformance on character diversity (−20% density, −14% entropy vs transport) warrants investigation. Three possible explanations:

1. **Curation concentrates on drama.** The LLM curator, asked to select the "best" passages, may preferentially choose high-stakes dramatic passages (Jo's death, Lady Dedlock's flight, Richard's ruin) over quieter character-building passages. This would explain the Jo and Dedlock dominance in embedding's character profile.

2. **Higher interest scores narrow the cast.** Embedding selects passages with mean interest score 4.3 (vs 3.3 for transport). High-interest passages may feature fewer characters in more intense scenes, reducing character diversity.

3. **Wordiness displaces character mentions.** Embedding scripts are 16% longer, suggesting the LLM curation selects passages that generate more analytical prose. More words spent on analysis means fewer words spent naming characters.

### 5.5 Implications for Pipeline Design

If these provisional results hold with complete data:

1. **The case for enrichment is weaker than expected.** Plain RAG matches transport on character density and entropy. The 20-field enrichment pipeline and min-cost flow solver may not improve downstream script quality enough to justify their complexity.

2. **The case for *any* selection is still strong.** Random passages disrupt expert identity and produce less coherent character coverage. Simple relevance matching (plain RAG) preserves expert voice while providing grounding text. The minimum viable pipeline may be: embed expert profiles, retrieve by cosine similarity, generate.

3. **The no-passages baseline reveals the LLM's contribution — and its limits.** The LLM produces character-dense, quotation-rich scripts from memory alone. But the quote audit (Section 6) shows that nearly half of no-passages "quotes" are fabricated, compared to only 4–9% in passage-grounded conditions. Passages provide accuracy and verifiable textual grounding, which turns out to be their primary value — not surface-level metrics like character density.

4. **Arc constraints provide structural value, not breadth.** Their contribution is narrative coherence — ensuring the right characters appear at the right structural moments — rather than maximising character diversity.

## 6. Quote Verification and Confabulation Analysis

### 6.1 Methodology

Every podcast script contains text presented as direct quotation from *Bleak House*. We audited all such quotes across 102 runs (all five conditions) using a two-phase pipeline (`scripts/quote_audit.py`):

**Phase 1: Quote extraction and intent classification.** Quotes are detected by two methods: (a) structured output tags (`is_quote`, `quote_reading`, `quote_mode="reading"`) and (b) regex extraction of text within quotation marks (minimum 15 characters). For inline quotes, a tiered classifier determines whether the quoted text represents a genuine quotation attempt or analytical/rhetorical use:

- *High-precision features*: repetition patterns ("X... X... X...", 86% precision), topic-as-subject ("'Move on' is cruel", ~90%), emphasis fragments (short + dash, ~80%)
- *Robust heuristic features*: speech verbs ("Dickens writes"), colons/em-dashes before quotes, intro nouns ("that passage")
- *spaCy dependency parse*: speech/writing verbs within 80 characters of the quote, intro nouns nearby
- Categories: "quotation", "topic", "emphasis", "repetition", "uncertain"

**Phase 2: Fuzzy verification against the source text.** A 4-gram inverted index over normalised *Bleak House* text (329,574 unique 4-grams, 1.86M characters across 68 chapters) enables fast candidate region lookup. For each quote, the system tries exact substring match, then n-gram indexed fuzzy matching using `SequenceMatcher` with anchored windowing (threshold: 0.75). Quotes are tested as full text, then cleaned of meta-commentary, then as extracted sub-quotes.

### 6.2 Raw Verification Results

| Pipeline | Runs | Total Quotes | Tagged | Inline | Verified | Rate |
|----------|------|-------------|--------|--------|----------|------|
| Transport | 30 | 1,453 | 1,195 | 258 | 1,268 | 87.3% |
| Embedding | 22 | 1,230 | 930 | 300 | 1,097 | 89.2% |
| RAG | 20 | 898 | 744 | 154 | 722 | 80.4% |
| No Passages | 20 | 805 | 775 | 30 | 309 | 38.4% |
| Random | 20 | 783 | 607 | 176 | 647 | 82.6% |

### 6.3 Three-Way Classification of Unverified Quotes

Not all unverified quotes are confabulations. We classify each unverified quote into three categories:

1. **Verifier false negatives** (match ratio ≥ 0.60): The quote is probably real but the fuzzy matcher couldn't reach the 0.75 threshold. These are near-misses — slight word substitutions, truncations, or normalisation artifacts.
2. **Detector false positives** (short inline fragments < 50 chars, or metacommentary detected by regex): The classifier flagged analytical or rhetorical text as a quotation attempt. These were never intended as verbatim quotes.
3. **True confabulations**: Sentence-length text tagged or classified as quotation with a low match ratio. The LLM fabricated text it presented as Dickens's words.

| Category | Count | Share |
|----------|-------|-------|
| Verifier false negatives | 382 | 34% |
| Detector false positives | 117 | 10% |
| True confabulations | 627 | 56% |
| **Total unverified** | **1,126** | |

### 6.4 Adjusted Verification Rates

Counting verifier false negatives as verified and excluding detector false positives from the denominator:

| Pipeline | Total | Verified | Vrfr FN | Det FP | Confab | Raw Rate | Adjusted Rate |
|----------|-------|----------|---------|--------|--------|----------|---------------|
| Transport | 1,453 | 1,268 | 99 | 23 | 63 | 87.3% | **95.6%** |
| Embedding | 1,230 | 1,097 | 46 | 34 | 53 | 89.2% | **95.6%** |
| RAG | 898 | 722 | 71 | 27 | 78 | 80.4% | **91.0%** |
| Random | 783 | 647 | 58 | 24 | 54 | 82.6% | **92.9%** |
| No Passages | 805 | 309 | 108 | 9 | 379 | 38.4% | **52.4%** |

Transport and embedding achieve near-identical adjusted rates (95.6%). RAG and random are close behind (91–93%). No-passages stands apart: even after generous adjustment, roughly half its "quotes" are fabricated.

### 6.5 Confabulation Deep-Dive

For each of the 627 true confabulations, we searched for the 5 closest matching passages in the source text using a broader search than the initial verification (more n-gram candidates, brute-force fallback for zero-hit quotes). Each confabulation was then classified by type based on its best-match ratio.

#### 6.5.1 Confabulation Types

| Type | Count | Share | Description |
|------|-------|-------|-------------|
| **Blend** | 430 | 69% | Modified, truncated, or combined real Dickens text. Best-match ratio typically 0.45–0.70. The LLM *knows* the passage but reproduces it imprecisely. |
| **Paraphrase** | 167 | 27% | Captures the gist of a real passage but substitutes most words. Ratio 0.30–0.45. The LLM remembers the *idea* but not the *text*. |
| **Invention** | 30 | 5% | No close source passage. Ratio < 0.30. The LLM generates plausible-sounding Dickens with no identifiable original. |

The dominance of blends (69%) is the central finding. The LLM rarely invents from nothing — even its confabulations are *recognisably close* to real text. This has implications for how we interpret "quotation accuracy": the model is doing something more like imperfect recall than wholesale fabrication.

#### 6.5.2 Confabulation Types by Pipeline

| Pipeline | Total | Blend | Paraphrase | Invention |
|----------|-------|-------|------------|-----------|
| Transport | 63 | 47 (75%) | 11 (17%) | 5 (8%) |
| Embedding | 53 | 38 (72%) | 6 (11%) | 9 (17%) |
| RAG | 78 | 55 (71%) | 21 (27%) | 2 (3%) |
| No Passages | 379 | 247 (65%) | 121 (32%) | 11 (3%) |
| Random | 54 | 43 (80%) | 8 (15%) | 3 (6%) |

No-passages has the highest paraphrase share (31%) — without source text to anchor quotation, the LLM falls back to remembered content and paraphrases more freely. Embedding has the highest invention rate (17%), possibly because its curated high-interest passages encourage quotation from dramatic scenes the LLM has memorised imprecisely.

#### 6.5.3 Confabulations by Expert

| Expert | Transport | Embedding | RAG | No Passages | Random | Total |
|--------|-----------|-----------|-----|-------------|--------|-------|
| Oliver Trevelyan | 7 | 10 | 8 | 86 | 10 | 121 |
| Caroline Woodcourt | 16 | 8 | 7 | 85 | 3 | 119 |
| Edmund Leigh | 11 | 7 | 15 | 62 | 10 | 105 |
| Eleanor Hartley | 17 | 5 | 16 | 55 | 9 | 102 |
| Daniel Rosen | 3 | 13 | 19 | 49 | 13 | 97 |
| James Blackstone | 8 | 10 | 13 | 42 | 9 | 82 |

Oliver Trevelyan (actor/director) and Caroline Woodcourt (performance scholar) confabulate most, particularly in no-passages (86 and 85 confabulations respectively). Both personas emphasise dramatic readings and close textual engagement — without source text, they "perform" fabricated quotes. Blackstone (legal historian) confabulates least (82 total), consistent with his more analytical, less quotation-dependent persona. The expert effect is concentrated in no-passages; in passage-grounded conditions, confabulation rates are low across all experts.

#### 6.5.4 Examples by Confabulation Type

##### Blends (69% of confabulations)

Blends are the dominant confabulation mode. The LLM reproduces the most *memorable* portion of a passage accurately, then truncates, substitutes, or continues from memory where its recall becomes uncertain — analogous to how a human might quote from memory.

**Near-verbatim truncation** (ratio 0.88, RAG, Oliver Trevelyan):
> "In manner, close and dry. In voice, husky and low. In face, watchful behind a blind."

Source (Chapter 27): *"In manner, close and dry. In voice, husky and low. In face, watchful behind a blind; habitually not uncensorious and contemptuous perhaps."* The LLM nails the iconic tricolon but drops the qualifying clause that follows. This pattern recurs: it appears in four separate RAG runs, always truncated at exactly the same point.

**Accurate core, drifting continuation** (ratio 0.84, Random, Daniel Rosen):
> "I will not begin it in the old way now. I have learned a lesson now, sir. It was a hard one, but you shall be assured, indeed, that I have learned it."

Source (Chapter 65): *"I will not begin it in the old way now," said Richard with a sad smile. "I have learned a lesson now, sir. It was a hard one, but you shall be assured..."* The opening and middle are verbatim. The LLM omits the stage direction ("said Richard with a sad smile") and extends beyond where its recall is reliable.

**Mid-range blend** (ratio 0.54, Transport, Caroline Woodcourt):
> "He hears Jarndyce say, almost directly to his face, 'if you entertain the supposition that any real success was ever wrested from Fortune by fits and starts, leave that wrong idea here...'"

Source (Chapter 13): *"...any real success, in great things or in small, ever was or could be, ever will or can be, wrested from Fortune by fits and starts, leave that wrong idea here or leave your cousin Ada here."* The distinctive phrase "wrested from Fortune by fits and starts" is preserved; the rhythmic parallelism around it is compressed.

**Low-ratio blend** (ratio 0.45, No Passages, Caroline Woodcourt):
> "I had a curious sensation of having seen it somewhere before — as though some forgotten dream had come to me."

No single passage matches closely, but the language is a mosaic of Esther's narrative style from multiple chapters — phrases like "curious sensation," "forgotten dream," and the first-person introspective register. The LLM has synthesised a plausible Esther utterance from the *style* of the text rather than any specific passage.

##### Paraphrases (26% of confabulations)

Paraphrases capture the gist of a real scene or speech but substitute most words. They retain meaning, characters, and context while losing verbatim fidelity.

**Scene compression** (ratio 0.45, No Passages, James Blackstone):
> "not one of Mrs. Pardiggle's Tockahoopo Indians; not a genuine foreign-grown savage; he is the ordinary home-made article."

Source (Chapter 47): *"He is not one of Mrs. Pardiggle's Tockahoopo Indians; he is not one of Mrs. Jellyby's lambs, being wholly unconnected with Borrioboola-Gha; he is not softened by distance and unfamiliarity; he is not a genuine foreign-grown savage."* The LLM preserves the rhetorical structure and key phrases ("Tockahoopo Indians," "genuine foreign-grown savage") but compresses the middle catalogue, dropping Mrs. Jellyby and Borrioboola-Gha.

**Thematic paraphrase** (ratio 0.42, No Passages, Eleanor Hartley):
> "There was an air about him that was not the air of a man who lived in the light."

No single source sentence matches, but the characterisation echoes Dickens's descriptions of Tulkinghorn (secretive, shadowy) and Nemo (hidden, desolate). The LLM has abstracted a character impression into a Dickensian-sounding sentence.

**Dialogue reconstruction** (ratio 0.45, No Passages, Edmund Leigh):
> "'Jo,' says Allan. 'I am here.' 'I hear you, sir,' he answers. 'Don't you fret yourself no more about it.'"

This paraphrases Jo's deathbed scene (Chapter 47) but substitutes Allan Woodcourt for the actual speakers and invents specific dialogue that *sounds* right but doesn't appear in the text. The emotional register is correct; the words are fabricated.

**Style pastiche** (ratio 0.34, No Passages, Caroline Woodcourt):
> "He writes that Vholes had a presence that seemed to consume the very air of the room — that when he put his black gloves on, it was as if he were dressing for a funeral."

Vholes is indeed associated with death imagery and suffocating presence throughout the novel, and "black gloves" is a real Vholes detail. But no passage contains this specific metaphor. The LLM has generated a plausible Dickens sentence about Vholes by combining remembered character traits with its own imagery.

##### Inventions (4% of confabulations)

True inventions have no identifiable source passage. They are rare but instructive.

**Elaborate fabrication with real fragments** (ratio 0.02, RAG, James Blackstone):
> "It is a street of perishing blind houses, with their eyes stoned out, without a pane of glass, without so much as a window-frame, with the bare blank shutters tumbling from their hinges..."

The phrase "street of perishing blind houses" sounds authentically Dickensian, but no such sentence exists in *Bleak House*. The closest match is Chapter 48's description of Lincoln's Inn: *"half-a-dozen of its greatest mansions seem to have been slowly stared into stone."* The LLM has generated an original passage in Dickens's architectural-decay register, possibly conflating *Bleak House* with other Dickens novels.

**Plausible character speech** (ratio 0.06, No Passages, Oliver Trevelyan):
> "I have better knowledge of my own heart than to believe that I could, at my time of life, find a young lady so perfectly suited to my happiness as my dear Esther."

This sounds like Jarndyce proposing to Esther, but the actual proposal (Chapters 44 and 64) uses different language entirely. The LLM has *imagined* how Jarndyce would phrase such a speech, producing something tonally correct but textually novel.

**Meta-commentary fabrication** (ratio 0.04, Transport, Caroline Woodcourt):
> "Dickens even frames it as unanswerable: 'Whether his whole soul is devoted to the great or whether he yields them nothing beyond the services he sells is his personal secret.'"

Strikingly, the quoted fragment *does* appear in Chapter 12 — but the wrapping meta-commentary ("Dickens even frames it as unanswerable") caused the n-gram search to miss it. This highlights a category boundary: some "inventions" are real quotes wrapped in fabricated attribution that defeats the search heuristics.

#### 6.5.5 The Deeper Search Effect

The confabulation deep-dive's broader search (40 candidate regions vs 20, brute-force fallback) recovered 28 quotes at ratio ≥ 0.75 that the original audit missed. This suggests the true confabulation count is somewhat lower than 504 — likely closer to 470–480. The 28 recovered quotes were concentrated in RAG (12) and random (6), where truncated but substantially correct quotes occasionally fell below the narrower search window of the original audit.

Additionally, several "inventions" (ratio < 0.30) turned out on manual inspection to contain real Dickens fragments wrapped in framing commentary. The LLM's tendency to introduce quotes with metacommentary ("Dickens writes that...", "And she has named those birds — and this is one of the passages I find myself coming back to —") can defeat automated verification even when the core quotation is genuine. This suggests a small number of inventions would be reclassified as blends under manual review.

### 6.6 Quote Audit: Key Findings

1. **Passage-grounded conditions achieve 91–96% adjusted verification rates.** Transport, embedding, RAG, and random all produce scripts where the vast majority of attempted quotations correspond to real Dickens text.

2. **No-passages confabulates at scale.** 379 of 627 confabulations (60%) come from the no-passages condition, which accounts for only 20% of panel-conditions. The model's prior knowledge of *Bleak House* is strong enough to discuss characters, themes, and plot accurately, but when it attempts verbatim quotation from memory, it fails roughly half the time.

3. **Most confabulations are blends, not inventions.** 69% of confabulations are recognisably close to real text (ratio 0.45–0.70). The LLM rarely invents from nothing — it blends, truncates, and paraphrases real passages. Only 5% of confabulations have no identifiable source in the text.

4. **Expert persona influences confabulation rate.** Performance-oriented experts (Woodcourt, Trevelyan) who emphasise dramatic reading confabulate more than analytical experts (Blackstone, Rosen). This confirms that confabulation is not purely a function of passage availability — persona prompt design affects quotation behaviour.

5. **Random passages reduce confabulation more than expected.** Random's adjusted rate (92.6%) is close to transport (95.6%), suggesting that *any* source text — even irrelevant — gives the LLM enough grounding to quote more accurately from its training memory. The passages may serve as retrieval cues.

## 7. Listener Value: What Are We Actually Measuring?

### 7.1 The Gap Between Metrics and Listener Experience

Our current metrics — character mention density, character entropy, unique character count, quote count, word count, vocabulary cosine — are *measurable* properties of the generated text. But a podcast listener cares about none of these directly. A listener cares about whether the episode is:

1. **Engaging** — does it hold attention, create moments of surprise or recognition?
2. **Illuminating** — does it reveal something about the novel the listener didn't notice?
3. **Authentic** — do the experts sound like real scholars with genuine perspectives?
4. **Accurate** — are the claims, quotes, and attributions correct?
5. **Coherent** — does the discussion build, rather than listing disconnected observations?

Our metrics are at best *proxies* for these qualities, and at worst orthogonal to them.

### 7.2 What Each Metric Actually Probes

**Character mention density** (our primary metric) correlates weakly with engagement. A script that mentions 15 characters per 1,000 words could be a rich tapestry of interwoven character analysis — or it could be a breathless catalogue that name-drops without depth. The metric cannot distinguish "Esther's relationship with Jarndyce evolves through three phases" (deep, 2 mentions) from "Esther, Jarndyce, Ada, Richard, Jo, and Lady Dedlock all appear in Chapter 3" (shallow, 6 mentions). No-passages' high character density (23.82/1k) may partly reflect this shallower mode: the LLM, lacking specific textual anchoring, reverts to surveying characters rather than analysing them.

**Character entropy** probes breadth of coverage but not depth. Random's high entropy (3.708) reflects that random passages scatter attention across many characters — but a listener might prefer focused depth on 5 characters to superficial mention of 18. Entropy penalises the kind of narrative focus that makes good storytelling.

**Quote count** is a weak proxy for textual engagement, and now we know it is also misleading for the no-passages condition. No-passages generates 40.6 quotes per episode — comparable to transport (40.8) — but the quote audit (Section 6) shows that only ~52% of those quotes are real. Raw quote count without verification overstates no-passages' textual engagement. For passage-grounded conditions, quote count is more trustworthy (91–96% verified), but still doesn't distinguish between well-chosen and generic quotations. Embedding's high quote count (43.8) reflects genuine textual richness — its 95.6% verification rate means most of those quotes are real.

**Vocabulary cosine** (cross-condition expert stability) probes expert identity persistence, which maps to *authenticity*. If Blackstone sounds like Blackstone regardless of input, the persona prompt is working. This metric has the strongest connection to listener value — listeners would notice if an expert's voice changed episode to episode.

**Word count** is almost meaningless for quality. Longer is not better; shorter is not better. It matters only insofar as it reveals that some conditions (embedding: +7%, no-passages: +14%) produce wordier scripts, which might indicate either richer analysis or padding.

### 7.3 What We Cannot Measure But Should

**Analytical depth.** The most valuable content in a literary podcast is a specific, non-obvious insight about the text — e.g., "Dickens uses Esther's housekeeping vocabulary to mirror the Court of Chancery's administrative failures." No automated metric captures this. A script could have low character density and high analytical depth, or high character density and no depth at all.

**Moment quality.** Great podcast episodes have 3–5 memorable moments: a surprising reading, a heated exchange, a perfectly chosen quote. These moments are what listeners remember and share. Our metrics average over the entire episode, washing out the difference between "uniformly adequate" and "mostly adequate with three brilliant moments."

**Quote aptness.** We count quotes but don't assess whether they're well-chosen. A perfectly apt quote — one that crystallises a point the expert is making — is worth more than five generic ones. Quote *recovery rate* (measured only for transport vs embedding) gets closer: it asks whether the system selected quotes that the LLM then chose to use. But even recovery rate doesn't measure aptness.

**Conversational dynamics.** A three-expert podcast should have genuine exchange: experts building on, challenging, or reframing each other's observations. Our metrics treat each expert independently. We don't measure whether Expert A's insight provokes a response from Expert B, or whether the experts are simply taking turns delivering monologues.

**Factual accuracy.** The quote audit (Section 6) confirms that no-passages scripts fabricate nearly half their attempted quotations, while passage-grounded conditions achieve 91–96% accuracy. But factual accuracy extends beyond quotes to include plot descriptions, character attributions, and chapter references — aspects not yet audited.

### 7.4 Implications for Interpreting Results

Given these gaps, our headline findings should be read with caution:

**"No-passages produces the highest character density"** does not mean no-passages produces the best episodes. It may mean the LLM, unconstrained by specific textual evidence, surveys characters more broadly but more shallowly. A human evaluator might rate these episodes lower despite higher density.

**"Random produces the highest character entropy"** does not mean random produces the most interesting character coverage. Random entropy is driven by *noise* — the LLM tries to discuss whatever it was given, producing scattered coverage rather than intentional breadth. A human evaluator would likely perceive this as incoherent rather than diverse.

**"Plain RAG matches transport on aggregate metrics"** may be the most reliable finding, since the metrics where RAG and transport converge (density, entropy) both point the same direction. But even this convergence might mask differences in analytical depth that our metrics cannot detect.

**"Embedding is the outlier"** is robust and listener-relevant: embedding's concentration on fewer characters with more words may actually produce more *focused, analytically deep* episodes. If so, embedding's apparent underperformance on diversity metrics might correspond to superior listener experience.

### 7.5 Toward Better Approximations

Several approaches could close the gap between automated metrics and listener value:

1. **LLM-as-judge evaluation.** Use a capable LLM (Opus, GPT-4) to rate scripts on specific quality dimensions: analytical depth, conversational flow, insight novelty, textual grounding. Systematic bias is possible but calibratable against human ratings on a small sample.

2. **Pairwise preference ranking.** Present matched pairs (same panel, different conditions) to human evaluators or LLM judges: "Which episode would you rather listen to?" This sidesteps the problem of absolute quality metrics and directly measures comparative listener preference.

3. **Specificity scoring.** Classify each expert utterance as *specific* (references a particular scene, character action, or textual detail) or *generic* (makes a general claim about the novel). The proportion of specific utterances is a better proxy for analytical depth than character density. Preliminary data from the transport-vs-embedding comparison (sentence specificity 0.867 vs 0.873) suggested near-parity, but extending this to all five conditions would be informative.

4. **Quote integration quality.** Rather than counting quotes, assess how each quote is introduced: is it set up with context, followed by analysis, and woven into the argument? Or is it dropped in without framing? This could be approximated by checking whether quote_reading sentences are preceded by quote_setup sentences and followed by analytical utterances.

5. **Turn-taking dynamics.** Measure the distribution of consecutive utterances by the same expert. More interleaving suggests more genuine conversation; long runs suggest monologue. This is extractable from the structured output schema.

6. **Audio quality proxy.** Since these scripts are rendered to audio via Gemini TTS, metrics on the audio output itself — pacing, prosodic variety, natural pause distribution — could capture aspects of listener experience that text metrics miss.

### 7.6 Recommendation

The current automated metrics are useful for *screening* — they reliably identify that embedding is different from the other four conditions, that random disrupts expert identity, and that no-passages produces recognisably character-dense output. But they should not be used to *rank* conditions by quality. For that, we need either LLM-as-judge evaluation on the full dataset or targeted human evaluation on a stratified sample.

The most informative next analysis would be pairwise preference ranking across the fourteen five-way panels, asking: "Given scripts from conditions A and B for the same panel, which produces the better episode?" This directly measures what we care about without requiring us to specify which automated proxies map to listener value.

## 8. Limitations and Next Steps

### 8.1 Current Limitations

- **Sample size.** All 20 panels have all 5 conditions (100/100 complete). The balanced design is fully realised, though 20 panels may still be insufficient for detecting small effects.
- **No human evaluation.** All metrics are automated. Character density and vocabulary signatures are proxies for script quality, not direct measures.
- **Confabulation classification is heuristic.** The three-way split (verifier false negative / detector false positive / true confabulation) uses ratio thresholds and text-length heuristics. Edge cases exist, particularly for blends with ratios near 0.60.
- **No coherence metric.** Character entropy measures breadth of coverage but not whether the character mentions form a coherent narrative. Random's high entropy may reflect topic drift rather than rich characterisation.
- **Embedding pipeline has known curation bias.** The LLM curation step may be suboptimally tuned; a different curation prompt might produce different results.

### 8.2 Planned Additional Analyses

1. ~~**Quote validity audit**~~ — **Complete.** See Section 6. Adjusted verification rates: transport/embedding 95.6%, RAG 91.0%, random 92.6%, no-passages 51.9%. Confabulation deep-dive found 69% blends, 26% paraphrases, 4% inventions.
2. **Passage-script attribution** — For each condition with passages, measure what fraction of script content is traceable to assigned passages vs generated from prior knowledge.
3. **Coherence scoring** — Develop a metric for narrative coherence that distinguishes intentional character diversity from topic drift.
4. **Stripped metadata condition** — Use transport's passage selections but strip enrichment metadata from Phase 3 input, isolating metadata's contribution to script generation (as distinct from selection).
5. ~~**Complete dataset**~~ — **Complete.** All 100 conditions (20 panels × 5 conditions) finished. Results above reflect the full dataset.
6. **LLM-as-judge evaluation** — Pairwise preference ranking across five-way panels using Opus or equivalent, rating analytical depth, conversational dynamics, and overall listener value (see Section 6.5).

### 8.3 Provisional Conclusions

Five findings are confirmed with the complete 100/100 dataset:

1. **Expert persona is the strongest single force** shaping script content, more influential than any passage selection method.
2. **The embedding pipeline's LLM curation step narrows rather than broadens** character coverage, producing an unexpected outlier pattern (lowest density in 15/20 panels, lowest entropy in 20/20).
3. **Random passages disrupt expert identity more than having no passages**, suggesting that passage relevance matters not just for content accuracy but for preserving the intended expert voice.
4. **Passage grounding is essential for quotation accuracy.** All four passage-based conditions achieve 91–96% adjusted quote verification; no-passages manages only 52%. The LLM's prior knowledge of *Bleak House* is sufficient for character discussion but insufficient for accurate verbatim quotation.
5. **Most confabulations are blends, not inventions.** When the LLM fabricates a quote, 69% of the time it produces a recognisable modification of real text — truncating, substituting words, or combining passages. Only 4% of confabulations have no identifiable source. This suggests the model's problem is imprecise *recall*, not lack of *knowledge*.

These findings suggest that the optimal pipeline design prioritises: (a) expert persona engineering for script identity, (b) simple relevance-based retrieval for textual grounding, and (c) passage availability as a quotation accuracy safeguard — rather than sophisticated passage optimisation.
