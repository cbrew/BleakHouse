# Five-Way Pipeline Comparison: Methodology and Results

**Date:** 2026-03-10 (updated)
**Status:** Complete — 100/100 conditions, all 20 panels × 5 conditions
**Basis:** 20 panels with all 5 conditions (full balanced design)

## 1. Research Question

The transport-based pipeline makes every passage selection decision visible as a cost, a flow, and a constraint, producing *inspectable, manipulable* editorial choices. Expert personas are deliberately stereotyped caricatures — the Marxist always finds class struggle, the performer always finds comedy — 
and the system encodes these stereotypes as adjustable demand vectors rather than hiding them in prompts. The result is a navigable configuration space: changing , eadjusting an arc emphasis, or swapping an expert produces measurably different output, and the *reasons* for those differences are legible.

This report asks: **does the transport pipeline's structured approach to passage selection produce measurably different — and characterfully different — outputs compared to simpler alternatives?** We construct four ablation conditions that progressively remove the transport system's distinctive features:

1. **No passages** — removes passage grounding entirely, isolating the LLM's prior knowledge
2. **Random passages** — adds passage *presence* without relevance, testing whether any grounding text suffices
3. **Plain RAG** — adds relevance matching without enrichment metadata or structural constraints
4. **Embedding + LLM curation** — adds enrichment-aware retrieval with LLM reasoning, but without the transport formulation's inspectability and manipulability

These ablations test whether each layer of the transport pipeline's design — enrichment metadata, structural constraints, demand profiles, min-cost optimisation — contributes to the system's ability to produce characterful, controllable caricatures of expert discussion.

## 2. Experimental Design

### 2.1 The Five Conditions

All conditions share the same Phase 0 (LLM-designed segment structure) and Phase 3 (Sonnet script generation with structured output). They differ only in what passages, if any, are provided to Phase 3. The transport pipeline is the system under study; the other four are ablations that test what happens when its distinctive features are removed.

**Transport (`v*`) — the full system.** Passages are assigned via min-cost flow optimisation over enrichment metadata. Expert demands, character arc obligations (Esther, Richard, Jo, Lady Dedlock, Jarndyce), provision dimensions (7 fields including character development, plot advancement, social critique, humour), and interest scores all feed into edge costs. A global optimum is found subject to capacity and structural constraints. Every selection decision is visible as a cost, a flow, and a constraint — the user can inspect why any passage was assigned to any expert, adjust demand profiles, and re-solve to explore alternatives.

**Embedding (`emb_v*`) — ablates inspectability.** Passages are retrieved using contextual embeddings (text + enrichment context), then an LLM (Sonnet) curates the selection using chain-of-thought reasoning about expert demands, character arc coverage, and segment fit. This uses the same enrichment metadata as transport but replaces the inspectable, manipulable optimisation with opaque LLM reasoning. The user cannot see *why* a passage was chosen or adjust selection criteria without re-prompting.

**Plain RAG (`rag_v*`) — ablates enrichment metadata.** Expert persona descriptions are embedded via OpenAI text-embedding-3-small. Passage embeddings use raw text only — no enrichment context, themes, or character metadata. Top-k passages per expert are selected by cosine similarity. No LLM reasoning, no arc constraints, no structural obligations. This tests whether relevance alone, without the structured metadata that makes transport's decisions legible, produces comparable results.

**Random Passages (`rand_v*`) — ablates relevance (diagnostic probe).** 32 passages drawn uniformly at random from Bleak House chapters c1–c67, using a deterministic seed derived from the panel composition (SHA-256 hash of sorted expert names). Passages are assigned round-robin to experts with no relevance matching. This is a diagnostic probe: do irrelevant passages make the experts say silly things? Neither this nor no-passages would be used in production — they exist to test specific hypotheses about how passage selection shapes the output.

**No Passages (`nop_v*`) — ablates grounding entirely (diagnostic probe).** Phase 3 receives expert personas and segment templates but zero passages. The prompt instructs: "No specific passages are assigned. Drawing on your knowledge of Bleak House by Charles Dickens, produce a rich discussion that fits this segment's theme." This isolates what the LLM can produce from prior knowledge alone, testing whether passages are doing work at all. The answer is clearly yes (Section 6).

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

### 5.1 What the Ablations Reveal

The ablations were designed to test what each layer of the transport pipeline contributes. The central question is not "which pipeline is best?" — these are caricatures, not scholarship — but "what does each design decision do to the character and controllability of the output?"

**Without passages, the LLM produces generic canonical coverage.** No-passages achieves the *highest* character density (23.82/1k) but this is breadth without depth: the LLM defaults to the novel's most famous characters (Esther, Jo, Richard) and discusses them in familiar terms. The caricature effect weakens — experts sound more alike without passage-specific material to differentiate their analyses. Critically, its adjusted quote verification rate (52.4%) is dramatically lower than all passage-grounded conditions (91–96%) — see Section 6.

**Random passages make the experts say silly things.** Random passages produce the highest character entropy (3.708) and most unique characters per episode (18.5), surfacing characters like Smallweed, George, and Guppy. But this diversity is *noise*, not *editorial choice*. The random condition is a diagnostic probe for a specific concern: does giving experts irrelevant material actively distort the caricatures? It does — random produces the lowest vocabulary cosine with all other conditions, meaning experts forced to discuss random passages lose their characteristic voice. They discuss whatever they were given rather than what their persona would naturally focus on (see Section 5.3).

**Plain RAG matches transport on aggregate metrics but lacks manipulability.** Character density (23.05 vs 22.32), entropy (3.483 vs 3.432), and word count (9,403 vs 9,267) are within 3%. On surface metrics, simple cosine retrieval is indistinguishable from min-cost flow. But RAG provides no mechanism to ask "what if I emphasise the Lady Dedlock arc?" or "what happens when the Marxist demands more social critique?" The aggregate similarity masks a fundamental difference in what the user can *do* with the pipeline.

**Embedding with LLM curation narrows rather than broadens.** Embedding produces the most distinctive scripts — lowest character density (17.59), lowest entropy (2.905), fewest unique characters (11.6) — but highest word count (9,958) and most quotes (43.8). The LLM curator concentrates on high-drama passages (Jo's death, Lady Dedlock's flight, Richard's ruin), producing verbose scripts about fewer characters. This is an editorial choice, but an *opaque* one: the user cannot inspect or adjust the curator's reasoning. The embedding condition demonstrates what happens when editorial judgement is delegated to an LLM rather than expressed as adjustable constraints.

### 5.2 Arc Constraints as Inspectable Editorial Choices

Transport's arc constraints (Esther, Richard, Jo, Lady Dedlock, Jarndyce) do not produce the *broadest* character coverage — random does. What they produce is *intentional* coverage: designated characters appear in the proportions the episode structure demands, and those proportions are adjustable. Transport is the only condition where Tulkinghorn consistently appears in the top 5 mentions, because his role in the Lady Dedlock arc makes him structurally important — and this importance is legible as a constraint in the flow formulation.

This illustrates the transport pipeline's core value proposition: arc constraints are not hidden in a prompt or emergent from retrieval — they are explicit, inspectable parameters. A user can ask "what happens if I double the Lady Dedlock arc?" and get a computable answer, rather than hoping the LLM will infer the change from a revised prompt. The sacrifice is breadth: random surfaces more minor characters simply by sampling more widely. The gain is *manipulability* — the ability to explore the configuration space deliberately.

### 5.3 Expert Caricatures: The Dominant Force

The expert personas are deliberately stereotyped — the Marxist always finds class struggle, the legal historian always finds institutional failure, the performer always finds comedy. The system's value depends on these caricatures being *recognisable and consistent*: listeners should hear Blackstone's legal focus whether he's discussing Chapter 1 or Chapter 67.

Same-expert vocabulary cosine across conditions averages 0.35–0.50 for intentional selection methods and 0.41 for no-passages, confirming that expert identity persists regardless of input material. Blackstone gravitates to legal and institutional language. Hartley analyses narrative structure. Trevelyan foregrounds performance and voice. The caricatures work.

**The random disruption effect reveals why passage selection matters for persona.** Random passages are the only condition that substantially disrupts expert identity (cosine 0.24–0.29 with other conditions). When given irrelevant material, experts are pulled toward discussing whatever they've been given rather than what their persona would naturally focus on. Random passages actively *compete with persona for control of the discussion*.

This is the strongest argument for relevance-based passage selection. The transport pipeline assigns passages *to serve each expert's stereotyped perspective* — Blackstone gets legally relevant passages, the Marxist gets passages about class. This alignment between passage selection and persona is what preserves the caricature. Without it (random condition), expert identity degrades. Without passages at all (no-passages condition), expert identity persists but quotation accuracy collapses. The transport formulation is the only approach that makes this alignment inspectable and adjustable: the demand vectors that encode each expert's interests are first-class objects in the optimisation, not implicit in a prompt.

### 5.4 The Embedding Pipeline: Opaque Curation as Cautionary Example

Embedding's consistent narrowing of character coverage (−20% density, −14% entropy vs transport) is instructive not as a failure but as a demonstration of what happens when editorial judgement is delegated to an LLM without inspectable constraints:

1. **The LLM curator makes unaccountable editorial choices.** It concentrates on high-stakes dramatic passages (Jo's death, Lady Dedlock's flight, Richard's ruin) — a defensible choice, but one the user cannot see, adjust, or argue with. In the transport formulation, the equivalent choice would be a visible demand profile weighting drama over other dimensions.

2. **The narrowing is consistent and systematic.** Embedding has the lowest entropy in 20/20 panels and lowest density in 15/20. This is not random variation — the LLM curator has a stable editorial preference that is hidden inside its chain-of-thought reasoning.

3. **The result is a different kind of caricature — but an uncontrolled one.** Embedding produces verbose, quote-heavy scripts focused on a few dramatic characters. This is a valid editorial stance, but the user has no lever to change it. In transport, the same effect could be achieved by adjusting the demand profile toward high-interest passages — and then reversed by adjusting it back.

### 5.5 What Transport Uniquely Provides

The ablations show that plain RAG matches transport on *aggregate surface metrics* (character density, entropy, word count). If the goal were simply "produce a decent podcast script," RAG would be sufficient. But the goal is to produce *characterful, controllable caricatures* — and here the aggregate metrics miss what matters:

1. **Inspectability.** Transport is the only condition where every selection decision has a legible explanation: this passage was assigned to this expert because of the interaction between the passage's enrichment metadata and the expert's demand profile. RAG cannot answer "why was this passage selected?" beyond "it was similar." Embedding's LLM curator has reasons but they are locked inside chain-of-thought reasoning the user never sees.

2. **Manipulability.** Transport is the only condition where the user can ask "what if?" questions and get computable answers. What happens if the Marxist demands more social critique? If we double the Lady Dedlock arc? If we replace the performer with the legal historian? These are changes to demand vectors and constraints — they produce different solutions in seconds, without re-running any LLM. The ablation conditions offer no equivalent: changing a RAG query requires regenerating embeddings; changing an LLM curator's preferences requires re-prompting and hoping.

3. **Passage grounding with quotation accuracy.** All four passage-based conditions achieve 91–96% quote verification, vs 52% for no-passages. Passages provide accuracy and verifiable textual grounding. But only transport and embedding use the enrichment metadata that makes passages *topically appropriate* to each expert's interests, preserving the caricature.

4. **Structural coherence through arc constraints.** Transport's arc constraints ensure designated characters appear at structurally appropriate moments — not because the LLM happened to retrieve relevant passages, but because the constraint was explicit. The sacrifice is breadth (random surfaces more minor characters), but the gain is *intentional* character coverage whose rationale is inspectable.

The point is not that transport produces "better" scripts by some absolute standard — these are caricatures of academic discourse, deliberately closer to parody than scholarship. The point is that transport turns editorial bias into a first-class object: something that can be inspected, compared, and argued about.

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

### 6.5 What the Unverified Quotes Actually Are

The label "confabulation" is misleading for most of the 627 unverified quotes. A deeper search for the 5 closest matching passages in the source text reveals that the majority are imprecise but recognisable reproductions of real Dickens text — not fabrications. The unverified quotes divide into three categories with very different implications for listeners.

#### 6.5.1 Three Categories of Unverified Quote

| Category | Count | Share | Listener concern | Description |
|----------|-------|-------|------------------|-------------|
| **Blend** | 430 | 69% | **Low** | Modified, truncated, or combined real Dickens text. Best-match ratio typically 0.45–0.70. The LLM *knows* the passage but reproduces it imprecisely — analogous to quoting from memory. A listener would hear a recognisable, substantially correct reference to the novel. |
| **Paraphrase** | 167 | 27% | **Low–moderate** | Captures the gist of a real passage but substitutes most words. Ratio 0.30–0.45. The LLM remembers the *idea* but not the *text*. Whether this matters depends on context: a paraphrase introduced as "Dickens writes something like..." is legitimate; one presented as verbatim quotation is misleading but not harmful. |
| **Invention** | 30 | 5% | **High** | No close source passage. Ratio < 0.30. The LLM generates plausible-sounding Dickens with no identifiable original. These are the genuinely problematic cases — a listener would be misled into thinking Dickens wrote something he did not. |

The dominance of blends (69%) is the central finding. The verification pipeline's 0.75 threshold necessarily classifies many imprecise-but-real quotations as failures. This is a measurement limitation, not a content problem. The LLM is doing something more like imperfect recall than wholesale fabrication — and imperfect recall is how most humans quote novels too.

The genuinely concerning cases — the 30 inventions — are rare: roughly 0.6% of all 5,169 attempted quotations across the full dataset.

#### 6.5.2 Categories by Pipeline

| Pipeline | Total unverified | Blend | Paraphrase | Invention |
|----------|-----------------|-------|------------|-----------|
| Transport | 63 | 47 (75%) | 11 (17%) | 5 (8%) |
| Embedding | 53 | 38 (72%) | 6 (11%) | 9 (17%) |
| RAG | 78 | 55 (71%) | 21 (27%) | 2 (3%) |
| No Passages | 379 | 247 (65%) | 121 (32%) | 11 (3%) |
| Random | 54 | 43 (80%) | 8 (15%) | 3 (6%) |

The invention count tells a different story from the total. Transport has 5 inventions — comparable to embedding's 9 despite very different total counts. No-passages has the most inventions in absolute terms (11) but the lowest *rate* of invention among its unverified quotes (3%) — its dominant failure mode is blending and paraphrasing, not making things up. Embedding has the highest invention *rate* (17%), possibly because its curated high-interest passages encourage quotation from dramatic scenes the LLM has memorised imprecisely.

#### 6.5.3 Unverified Quotes by Expert

| Expert | Transport | Embedding | RAG | No Passages | Random | Total |
|--------|-----------|-----------|-----|-------------|--------|-------|
| Oliver Trevelyan | 7 | 10 | 8 | 86 | 10 | 121 |
| Caroline Woodcourt | 16 | 8 | 7 | 85 | 3 | 119 |
| Edmund Leigh | 11 | 7 | 15 | 62 | 10 | 105 |
| Eleanor Hartley | 17 | 5 | 16 | 55 | 9 | 102 |
| Daniel Rosen | 3 | 13 | 19 | 49 | 13 | 97 |
| James Blackstone | 8 | 10 | 13 | 42 | 9 | 82 |

These raw totals are dominated by no-passages counts and are misleading about actual listener risk. Most of Trevelyan's 86 no-passages "failures" are blends and paraphrases — imprecise quotation from memory, not fabrication. The more informative comparison is across passage-grounded conditions, where expert differences are modest (3–17 per expert per condition) and all experts produce scripts with 91–96% adjusted verification rates.

The expert effect that *does* matter is in passage-grounded conditions: Rosen has 13 unverified quotes in both embedding and random (highest of any expert in those conditions), while Woodcourt has only 3 in random and 7 in RAG. This suggests analytical personas (Rosen, Leigh) are more likely to *attempt* quotation outside their provided passages, while performance personas (Woodcourt) stick closer to given material when it's available.

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

**Search failure misclassified as invention** (ratio 0.04, Transport, Caroline Woodcourt):
> "Dickens even frames it as unanswerable: 'Whether his whole soul is devoted to the great or whether he yields them nothing beyond the services he sells is his personal secret.'"

The quoted fragment *does* appear in Chapter 12 — but the wrapping meta-commentary ("Dickens even frames it as unanswerable") caused the n-gram search to miss it entirely, yielding a near-zero ratio. This is not a confabulation at all but a **search failure**: the verification pipeline's n-gram index cannot match quotes embedded in framing commentary. Several other "inventions" likely fall into this category — real Dickens text wrapped in the expert's analytical voice, invisible to automated verification.

#### 6.5.5 Limitations of Automated Verification

The confabulation counts reported above are *upper bounds* on actual confabulation. Two systematic biases inflate them:

**Search window limitations.** The confabulation deep-dive's broader search (40 candidate regions vs 20, brute-force fallback) recovered 28 quotes at ratio ≥ 0.75 that the original audit missed. These were concentrated in RAG (12) and random (6), where truncated but substantially correct quotes fell outside the narrower search window. The true confabulation count is likely closer to 470–480 than the reported 504.

**Meta-commentary defeats n-gram matching.** The LLM frequently wraps real Dickens text in analytical framing: "Dickens writes that...", "And she has named those birds — and this is one of the passages I find myself coming back to —". When the framing text dominates the extracted quote string, the n-gram index cannot locate the genuine fragment inside it. The "meta-commentary fabrication" example in Section 6.5.4 illustrates this: a real Chapter 12 quote scored ratio 0.04 because it was embedded in commentary. An unknown number of other low-ratio "confabulations" — including some classified as inventions — are likely search failures rather than genuine fabrications.

These limitations mean that the 30 reported inventions are themselves an upper bound. Some are real quotes that the search pipeline could not find. The *floor* on genuine inventions — quotes where no plausible source exists even under generous manual inspection — is probably closer to 15–20, or roughly 0.3% of all quotes across all conditions.

### 6.6 Quote Audit: Key Findings

1. **Passage grounding is essential for quotation accuracy.** All four passage-based conditions achieve 91–96% adjusted verification rates; no-passages manages only 52%. The LLM's prior knowledge of *Bleak House* supports accurate discussion of characters, themes, and plot, but is insufficient for verbatim quotation.

2. **The dominant failure mode is imprecise recall, not fabrication.** 69% of unverified quotes are blends — recognisable modifications of real text where the LLM truncates, substitutes words, or merges passages. Another 26% are paraphrases that capture the gist of a real scene. From a listener's perspective, these are indistinguishable from slightly loose quotation and pose minimal risk to the podcast's credibility.

3. **Genuine inventions are rare.** Only 30 quotes (0.6% of all quotes, 5% of unverified quotes) have no identifiable source passage, and even this count is inflated by search limitations (Section 6.5.5). The true invention count is likely 15–20. These are the only unverified quotes that represent a genuine listener concern.

4. **No-passages drives most of the unverified count but not most of the risk.** 379 of 627 unverified quotes (60%) come from no-passages, but 65% of those are blends — the LLM recalling real text imprecisely from memory. No-passages has 11 inventions, which is the highest absolute count but only 3% of its unverified total. The condition's problem is not that it *invents* but that it *misremembers*.

5. **Random passages reduce confabulation more than expected.** Random's adjusted rate (92.6%) is close to transport (95.6%), suggesting that *any* source text — even irrelevant — gives the LLM enough grounding to quote more accurately. The passages may serve as retrieval cues that activate more precise recall.

6. **Automated verification has systematic blind spots.** Quotes wrapped in meta-commentary, truncated at non-obvious boundaries, or embedded in analytical framing can defeat n-gram search, inflating the unverified count. The reported confabulation figures are upper bounds.

## 7. Evaluation: What Are We Actually Measuring?

### 7.1 The Gap Between Metrics and the System's Goals

Our current metrics — character mention density, character entropy, unique character count, quote count, word count, vocabulary cosine — are *measurable* properties of the generated text. But the system's goal is not to maximise any of these metrics. The goal is to produce *characterful, recognisable caricatures of expert discussion* whose editorial choices are inspectable and manipulable. Good metrics would measure whether:

1. **Caricatures are recognisable** — does each expert sound consistently like their stereotyped persona?
2. **Configurations produce different outputs** — do changes to panel composition, arc emphasis, or demand profiles produce measurably different scripts?
3. **Differences are legible** — can the user trace output differences back to specific selection decisions?
4. **Quotation is grounded** — are the claims, quotes, and attributions traceable to real text?
5. **The discussion is coherent** — does the script build a narrative rather than listing disconnected observations?

Our current metrics address (1) partially (vocabulary cosine), (4) well (quote verification), and (2) indirectly (aggregate differences between conditions). They do not address (3) or (5) at all. They are at best *proxies* for the system's actual goals.

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

Given these gaps, the aggregate metrics should not be read as a quality ranking:

**"No-passages produces the highest character density"** likely reflects shallow survey rather than deep analysis. The LLM, unconstrained by specific textual evidence, name-drops more characters but engages less deeply with each. This is the *opposite* of the focused caricature the system aims to produce.

**"Random produces the highest character entropy"** reflects noise, not editorial breadth. Random entropy is driven by the LLM trying to discuss whatever it was given, producing scattered coverage rather than intentional focus. From the system's perspective this is a failure: random undermines the expert caricatures more than any other condition.

**"Plain RAG matches transport on aggregate metrics"** is the finding that most needs the inspectability/manipulability framing. These aggregate metrics cannot distinguish between two pipelines that produce similar *average* outputs but differ fundamentally in what the user can *do* with them. Transport's value is not in producing a different mean — it is in making the space of possible outputs navigable.

**"Embedding is the outlier"** demonstrates what happens when editorial judgement is delegated to an LLM: a consistent, defensible, but uncontrollable narrowing. The user of an embedding pipeline cannot ask "what if I want broader coverage?" without rewriting the curation prompt and hoping.

### 7.5 Toward Better Approximations

Several approaches could close the gap between automated metrics and listener value:

1. **LLM-as-judge evaluation.** Use a capable LLM (Opus, GPT-4) to rate scripts on specific quality dimensions: analytical depth, conversational flow, insight novelty, textual grounding. Systematic bias is possible but calibratable against human ratings on a small sample.

2. **Pairwise preference ranking.** Present matched pairs (same panel, different conditions) to human evaluators or LLM judges: "Which episode would you rather listen to?" This sidesteps the problem of absolute quality metrics and directly measures comparative listener preference.

3. **Specificity scoring.** Classify each expert utterance as *specific* (references a particular scene, character action, or textual detail) or *generic* (makes a general claim about the novel). The proportion of specific utterances is a better proxy for analytical depth than character density. Preliminary data from the transport-vs-embedding comparison (sentence specificity 0.867 vs 0.873) suggested near-parity, but extending this to all five conditions would be informative.

4. **Quote integration quality.** Rather than counting quotes, assess how each quote is introduced: is it set up with context, followed by analysis, and woven into the argument? Or is it dropped in without framing? This could be approximated by checking whether quote_reading sentences are preceded by quote_setup sentences and followed by analytical utterances.

5. **Turn-taking dynamics.** Measure the distribution of consecutive utterances by the same expert. More interleaving suggests more genuine conversation; long runs suggest monologue. This is extractable from the structured output schema.

6. **Audio quality proxy.** Since these scripts are rendered to audio via Gemini TTS, metrics on the audio output itself — pacing, prosodic variety, natural pause distribution — could capture aspects of listener experience that text metrics miss.

### 7.6 Recommendation

The current automated metrics confirm that the five conditions produce measurably different outputs — the ablation design works. But they cannot assess the system's core claim: that transport's inspectability and manipulability make it a better *thinking tool* than opaque alternatives. No automated metric measures whether a user can productively explore the configuration space.

Two evaluation approaches would address this gap:

1. **Pairwise preference ranking** across panels, asking: "Given scripts from conditions A and B for the same panel, which produces a more characterful, engaging caricature?" This directly tests output quality without requiring us to specify which automated proxies matter.

2. **Configuration exploration study**: give users the transport pipeline's configuration interface and ask them to produce a script they find interesting. Measure how many configurations they explore, whether they can predict the effect of changes, and whether they prefer the final result to a RAG or embedding baseline. This directly tests the claim that inspectability and manipulability have user value.

## 8. Limitations and Next Steps

### 8.1 Current Limitations

- **Sample size.** All 20 panels have all 5 conditions (100/100 complete). The balanced design is fully realised, though 20 panels may still be insufficient for detecting small effects.
- **No human evaluation.** All metrics are automated. Character density and vocabulary signatures are proxies for caricature quality, not direct measures of whether the generated discussions are characterful or the configuration space is productively navigable.
- **No inspectability/manipulability evaluation.** The report documents output differences but does not directly test whether users can productively explore the transport pipeline's configuration space or whether its legible selection rationale has practical value.
- **Confabulation classification is heuristic.** The three-way split (verifier false negative / detector false positive / true confabulation) uses ratio thresholds and text-length heuristics. Edge cases exist, particularly for blends with ratios near 0.60.
- **No coherence metric.** Character entropy measures breadth of coverage but not whether the character mentions form a coherent narrative. Random's high entropy may reflect topic drift rather than rich characterisation.
- **Embedding pipeline has known curation bias.** The LLM curation step may be suboptimally tuned; a different curation prompt might produce different results.

### 8.2 Planned Additional Analyses

1. ~~**Quote validity audit**~~ — **Complete.** See Section 6. Adjusted verification rates: transport/embedding 95.6%, RAG 91.0%, random 92.6%, no-passages 51.9%. Confabulation deep-dive found 69% blends, 26% paraphrases, 4% inventions.
2. **Passage-script attribution** — For each condition with passages, measure what fraction of script content is traceable to assigned passages vs generated from prior knowledge.
3. **Coherence scoring** — Develop a metric for narrative coherence that distinguishes intentional character diversity from topic drift.
4. **Stripped metadata condition** — Use transport's passage selections but strip enrichment metadata from Phase 3 input, isolating metadata's contribution to script generation (as distinct from selection).
5. ~~**Complete dataset**~~ — **Complete.** All 100 conditions (20 panels × 5 conditions) finished. Results above reflect the full dataset.
6. **LLM-as-judge evaluation** — Pairwise preference ranking across five-way panels using Opus or equivalent, rating caricature recognisability, conversational dynamics, and engagement (see Section 7.6).
7. **Configuration exploration study** — User study testing whether transport's inspectability and manipulability translate to productive exploration of the configuration space (see Section 7.6).

### 8.3 Conclusions

The ablations answer "when would we use each approach?":

**No passages: never.** The no-passages condition demonstrates that passages are doing real work. Without them, the LLM produces fluent but generically canonical discussion and fabricates nearly half its attempted quotations. No-passages is a useful *probe* — it isolates the LLM's prior knowledge — but not a viable production approach.

**Random passages: never.** The random condition is a probe for a specific risk: do irrelevant passages make the experts say silly things? The answer is yes — random passages actively disrupt expert identity (lowest vocabulary cosine with all other conditions) and scatter attention across characters without narrative coherence. Random is informative as a diagnostic but would never be chosen as a design.

**Plain RAG: when inspectability doesn't matter.** RAG produces scripts statistically indistinguishable from transport on aggregate surface metrics, with comparable quotation accuracy (91% vs 96%). If the goal is simply "produce a decent podcast script with minimal infrastructure," RAG is the pragmatic choice. But it provides no mechanism for the user to explore alternatives: no demand profiles, no arc constraints, no legible selection rationale.

**Embedding with LLM curation: when you trust the curator.** Embedding produces the most distinctive scripts — focused, quote-heavy, drama-centred — but the editorial choices behind that focus are opaque. If the curator's implicit preferences align with the user's goals, the results are good. If they don't, there is no lever to adjust them. The embedding condition is a cautionary example of delegating editorial judgement to an LLM.

**Transport: when you want to think.** The transport pipeline's advantage is not in producing "better" scripts by some absolute standard — the aggregate metrics show RAG is comparable. Its advantage is in turning editorial bias into a first-class object. The expert stereotypes are encoded as demand vectors, not hidden in prompts. The arc constraints are explicit parameters, not emergent from retrieval. Every selection decision is visible as a cost, a flow, and a constraint. Because solving a flow is cheap compared to regenerating with an LLM, the user gets a flexible thinking tool for rapid exploration of alternatives: twenty configurations produce measurably different outputs, and the *reasons* for those differences are legible.

Five additional findings are confirmed across the full 100/100 dataset:

1. **Expert persona is the strongest single force** shaping script content — the caricatures work regardless of passage selection method.
2. **Passage grounding is essential for quotation accuracy.** All passage-based conditions achieve 91–96% adjusted verification; no-passages manages 52%.
3. **Most unverified quotes are imprecise recall, not fabrication.** 69% are blends of real text; only 0.6% of all quotes are genuine inventions.
4. **Irrelevant passages actively undermine expert identity**, more than having no passages at all — passage *relevance* matters for preserving the intended caricature.
5. **LLM curation narrows rather than broadens** character coverage, demonstrating the risk of opaque editorial delegation.
