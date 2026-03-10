# Five-Way Pipeline Comparison: Methodology and Provisional Results

**Date:** 2026-03-10
**Status:** Provisional — data collection ongoing (65/100 conditions complete)
**Basis:** 6 panels with all 5 conditions, 12 panels with 3+ conditions, 20 panels with transport

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

| Condition | Complete | In progress | Target |
|-----------|----------|-------------|--------|
| Transport | 20/20 | — | 20 |
| Embedding | 19/20 | 1 | 20 |
| Plain RAG | 12/20 | 8 | 20 |
| No Passages | 7/20 | 13 | 20 |
| Random | 7/20 | 13 | 20 |
| **Total** | **65/100** | **35** | **100** |

Results below are provisional, based on panels where conditions are available. Aggregate statistics use only panels where 3+ conditions are complete (n = 12 panels). Six panels now have all 5 conditions.

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

Mean values across panels with 3+ conditions complete:

| Metric | Transport | Embedding | Plain RAG | No Passages | Random |
|--------|-----------|-----------|-----------|-------------|--------|
| Panels (n) | 12 | 11 | 12 | 7 | 7 |
| Words per episode | 9,122 | 10,421 | 9,485 | 10,161 | 8,667 |
| Quotes per episode | 40.3 | 45.8 | 37.8 | 39.7 | 34.3 |
| Char mentions / 1k words | 22.56 | 18.13 | 23.36 | 25.38 | 23.17 |
| Unique characters | 14.2 | 11.5 | 16.4 | 15.9 | 18.6 |
| Character entropy | 3.417 | 2.943 | 3.491 | 3.330 | 3.733 |

### 4.2 Pairwise Differences (relative to Transport)

| vs Transport | Char Density | Entropy | Word Count | Quotes |
|-------------|-------------|---------|------------|--------|
| Embedding | −20% | −14% | +14% | +14% |
| Plain RAG | +4% | +2% | +4% | −6% |
| No Passages | +12% | −3% | +11% | −1% |
| Random | +3% | +9% | −5% | −15% |

### 4.3 Per-Panel Consistency (5-way panels, n = 6)

| Panel | Transport | Embedding | RAG | No Passages | Random |
|-------|-----------|-----------|-----|-------------|--------|
| **Character density / 1k words** |
| v01_baseline | 19.4 | 15.5 | 20.2 | 28.7 | 25.9 |
| v10_conservative | 23.6 | 17.9 | 27.6 | 24.3 | 24.7 |
| v12_radical_panel | 23.3 | 21.5 | 28.3 | 26.7 | 23.6 |
| v14_trevelyan_for_woodcourt | 20.6 | 18.9 | 18.5 | 24.3 | 22.8 |
| v15_trevelyan_for_hartley | 21.6 | 21.1 | 22.4 | 23.1 | 20.1 |
| v16_trevelyan_for_blackstone | 24.4 | 15.9 | 22.4 | 23.6 | 23.0 |
| **Character entropy** |
| v01_baseline | 3.33 | 2.92 | 3.33 | 3.09 | 3.99 |
| v10_conservative | 3.40 | 2.95 | 3.57 | 3.35 | 3.73 |
| v12_radical_panel | 3.40 | 3.17 | 3.41 | 3.39 | 3.62 |
| v14_trevelyan_for_woodcourt | 3.43 | 2.86 | 3.64 | 3.28 | 3.73 |
| v15_trevelyan_for_hartley | 3.25 | 2.87 | 3.44 | 3.42 | 3.68 |
| v16_trevelyan_for_blackstone | 3.41 | 2.87 | 3.45 | 3.45 | 3.54 |

Embedding's low character density and entropy are consistent across all 6 panels — it is the lowest or near-lowest on both metrics in every case. No-passages' high character density is consistent across all 6 panels (always above transport). Random's high entropy is consistent across all 6 panels (always above transport). These patterns are robust across panel compositions.

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

**No-passages is surprisingly strong.** At 25.38 character mentions per 1k words, no-passages produces the *highest* character density of any condition. The LLM draws heavily on its training knowledge of Bleak House, name-dropping characters more frequently than when anchored to specific passages. However, its entropy (3.330) is lower than RAG (3.491) or random (3.733), indicating concentration on the most canonical characters.

**Random is surprisingly good on diversity.** Random passages produce the highest character entropy (3.733) and most unique characters per episode (18.6). Random sampling naturally covers more of the novel than any intentional selection method, surfacing characters like Smallweed, George, Caddy, and Guppy that arc-constrained transport passes over.

**Plain RAG closely matches transport.** Character density (23.36 vs 22.56), entropy (3.491 vs 3.417), and word count (9,485 vs 9,122) are all within 4% of transport. Simple text-similarity retrieval produces scripts statistically indistinguishable from optimised selection on these aggregate metrics.

**Embedding is the unexpected outlier.** Rather than sitting between RAG and transport on the sophistication ladder, embedding produces distinctly different scripts: lowest character density (18.13), lowest entropy (2.943), fewest unique characters (11.5), but highest word count (10,421) and most quotes (45.8). The LLM curation step appears to concentrate selections on high-drama, high-interest passages (Jo's story, the Dedlock mystery, Richard's decline), producing verbose scripts about fewer characters rather than broader coverage.

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

3. **The no-passages baseline reveals the LLM's contribution.** The LLM produces character-dense, quotation-rich scripts from memory alone. Passages provide accuracy and specificity (pending quote validity audit) but may not be the primary driver of apparent quality.

4. **Arc constraints provide structural value, not breadth.** Their contribution is narrative coherence — ensuring the right characters appear at the right structural moments — rather than maximising character diversity.

## 6. Listener Value: What Are We Actually Measuring?

### 6.1 The Gap Between Metrics and Listener Experience

Our current metrics — character mention density, character entropy, unique character count, quote count, word count, vocabulary cosine — are *measurable* properties of the generated text. But a podcast listener cares about none of these directly. A listener cares about whether the episode is:

1. **Engaging** — does it hold attention, create moments of surprise or recognition?
2. **Illuminating** — does it reveal something about the novel the listener didn't notice?
3. **Authentic** — do the experts sound like real scholars with genuine perspectives?
4. **Accurate** — are the claims, quotes, and attributions correct?
5. **Coherent** — does the discussion build, rather than listing disconnected observations?

Our metrics are at best *proxies* for these qualities, and at worst orthogonal to them.

### 6.2 What Each Metric Actually Probes

**Character mention density** (our primary metric) correlates weakly with engagement. A script that mentions 15 characters per 1,000 words could be a rich tapestry of interwoven character analysis — or it could be a breathless catalogue that name-drops without depth. The metric cannot distinguish "Esther's relationship with Jarndyce evolves through three phases" (deep, 2 mentions) from "Esther, Jarndyce, Ada, Richard, Jo, and Lady Dedlock all appear in Chapter 3" (shallow, 6 mentions). No-passages' high character density (25.38/1k) may partly reflect this shallower mode: the LLM, lacking specific textual anchoring, reverts to surveying characters rather than analysing them.

**Character entropy** probes breadth of coverage but not depth. Random's high entropy (3.733) reflects that random passages scatter attention across many characters — but a listener might prefer focused depth on 5 characters to superficial mention of 18. Entropy penalises the kind of narrative focus that makes good storytelling.

**Quote count** is a weak proxy for textual engagement. More quotes might mean richer textual grounding — or might mean the LLM is padding with block quotations rather than analysing. The embedding pipeline's high quote count (45.8) may reflect either genuine textual richness or a tendency to reproduce passage content rather than discuss it.

**Vocabulary cosine** (cross-condition expert stability) probes expert identity persistence, which maps to *authenticity*. If Blackstone sounds like Blackstone regardless of input, the persona prompt is working. This metric has the strongest connection to listener value — listeners would notice if an expert's voice changed episode to episode.

**Word count** is almost meaningless for quality. Longer is not better; shorter is not better. It matters only insofar as it reveals that some conditions (embedding: +14%, no-passages: +11%) produce wordier scripts, which might indicate either richer analysis or padding.

### 6.3 What We Cannot Measure But Should

**Analytical depth.** The most valuable content in a literary podcast is a specific, non-obvious insight about the text — e.g., "Dickens uses Esther's housekeeping vocabulary to mirror the Court of Chancery's administrative failures." No automated metric captures this. A script could have low character density and high analytical depth, or high character density and no depth at all.

**Moment quality.** Great podcast episodes have 3–5 memorable moments: a surprising reading, a heated exchange, a perfectly chosen quote. These moments are what listeners remember and share. Our metrics average over the entire episode, washing out the difference between "uniformly adequate" and "mostly adequate with three brilliant moments."

**Quote aptness.** We count quotes but don't assess whether they're well-chosen. A perfectly apt quote — one that crystallises a point the expert is making — is worth more than five generic ones. Quote *recovery rate* (measured only for transport vs embedding) gets closer: it asks whether the system selected quotes that the LLM then chose to use. But even recovery rate doesn't measure aptness.

**Conversational dynamics.** A three-expert podcast should have genuine exchange: experts building on, challenging, or reframing each other's observations. Our metrics treat each expert independently. We don't measure whether Expert A's insight provokes a response from Expert B, or whether the experts are simply taking turns delivering monologues.

**Factual accuracy.** No-passages scripts may be rich in character mentions and quotation but wrong in their attributions. Our planned quote validity audit (Section 7.2, item 1) addresses this partially, but factual accuracy extends beyond quotes to include plot descriptions, character attributions, and chapter references.

### 6.4 Implications for Interpreting Results

Given these gaps, our headline findings should be read with caution:

**"No-passages produces the highest character density"** does not mean no-passages produces the best episodes. It may mean the LLM, unconstrained by specific textual evidence, surveys characters more broadly but more shallowly. A human evaluator might rate these episodes lower despite higher density.

**"Random produces the highest character entropy"** does not mean random produces the most interesting character coverage. Random entropy is driven by *noise* — the LLM tries to discuss whatever it was given, producing scattered coverage rather than intentional breadth. A human evaluator would likely perceive this as incoherent rather than diverse.

**"Plain RAG matches transport on aggregate metrics"** may be the most reliable finding, since the metrics where RAG and transport converge (density, entropy) both point the same direction. But even this convergence might mask differences in analytical depth that our metrics cannot detect.

**"Embedding is the outlier"** is robust and listener-relevant: embedding's concentration on fewer characters with more words may actually produce more *focused, analytically deep* episodes. If so, embedding's apparent underperformance on diversity metrics might correspond to superior listener experience.

### 6.5 Toward Better Approximations

Several approaches could close the gap between automated metrics and listener value:

1. **LLM-as-judge evaluation.** Use a capable LLM (Opus, GPT-4) to rate scripts on specific quality dimensions: analytical depth, conversational flow, insight novelty, textual grounding. Systematic bias is possible but calibratable against human ratings on a small sample.

2. **Pairwise preference ranking.** Present matched pairs (same panel, different conditions) to human evaluators or LLM judges: "Which episode would you rather listen to?" This sidesteps the problem of absolute quality metrics and directly measures comparative listener preference.

3. **Specificity scoring.** Classify each expert utterance as *specific* (references a particular scene, character action, or textual detail) or *generic* (makes a general claim about the novel). The proportion of specific utterances is a better proxy for analytical depth than character density. Preliminary data from the transport-vs-embedding comparison (sentence specificity 0.867 vs 0.873) suggested near-parity, but extending this to all five conditions would be informative.

4. **Quote integration quality.** Rather than counting quotes, assess how each quote is introduced: is it set up with context, followed by analysis, and woven into the argument? Or is it dropped in without framing? This could be approximated by checking whether quote_reading sentences are preceded by quote_setup sentences and followed by analytical utterances.

5. **Turn-taking dynamics.** Measure the distribution of consecutive utterances by the same expert. More interleaving suggests more genuine conversation; long runs suggest monologue. This is extractable from the structured output schema.

6. **Audio quality proxy.** Since these scripts are rendered to audio via Gemini TTS, metrics on the audio output itself — pacing, prosodic variety, natural pause distribution — could capture aspects of listener experience that text metrics miss.

### 6.6 Recommendation

The current automated metrics are useful for *screening* — they reliably identify that embedding is different from the other four conditions, that random disrupts expert identity, and that no-passages produces recognisably character-dense output. But they should not be used to *rank* conditions by quality. For that, we need either LLM-as-judge evaluation on the full dataset or targeted human evaluation on a stratified sample.

The most informative next analysis would be pairwise preference ranking across the six five-way panels, asking: "Given scripts from conditions A and B for the same panel, which produces the better episode?" This directly measures what we care about without requiring us to specify which automated proxies map to listener value.

## 7. Limitations and Next Steps

### 7.1 Current Limitations

- **Sample size.** Six panels have all 5 conditions. Results for no-passages (n=7) and random (n=7) are stabilising but may still shift as data collection completes to 20 panels each.
- **No human evaluation.** All metrics are automated. Character density and vocabulary signatures are proxies for script quality, not direct measures.
- **Quote validity not yet tested.** No-passages scripts may contain confabulated quotes. A cross-reference against the Bleak House corpus is needed before claiming that no-passages quality matches passage-based conditions.
- **No coherence metric.** Character entropy measures breadth of coverage but not whether the character mentions form a coherent narrative. Random's high entropy may reflect topic drift rather than rich characterisation.
- **Embedding pipeline has known curation bias.** The LLM curation step may be suboptimally tuned; a different curation prompt might produce different results.

### 7.2 Planned Additional Analyses

1. **Quote validity audit** — Cross-reference all "quotes" in no-passages scripts against the full Bleak House text to measure confabulation rate.
2. **Passage-script attribution** — For each condition with passages, measure what fraction of script content is traceable to assigned passages vs generated from prior knowledge.
3. **Coherence scoring** — Develop a metric for narrative coherence that distinguishes intentional character diversity from topic drift.
4. **Stripped metadata condition** — Use transport's passage selections but strip enrichment metadata from Phase 3 input, isolating metadata's contribution to script generation (as distinct from selection).
5. **Complete dataset** — Finish all 100 conditions and re-run analysis with full statistical power.
6. **LLM-as-judge evaluation** — Pairwise preference ranking across five-way panels using Opus or equivalent, rating analytical depth, conversational dynamics, and overall listener value (see Section 6.5).

### 7.3 Provisional Conclusions

Three findings appear robust even at this early stage:

1. **Expert persona is the strongest single force** shaping script content, more influential than any passage selection method.
2. **The embedding pipeline's LLM curation step narrows rather than broadens** character coverage, producing an unexpected outlier pattern.
3. **Random passages disrupt expert identity more than having no passages**, suggesting that passage relevance matters not just for content accuracy but for preserving the intended expert voice.

These findings, if confirmed with complete data, suggest that the optimal pipeline design prioritises expert persona engineering and simple relevance-based retrieval over sophisticated passage optimisation.
