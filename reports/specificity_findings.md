# Textual Engagement Specificity: Transport vs Embedding Pipeline

**Date:** 2026-03-09
**Basis:** 8 matched configuration pairs (baseline, more_jo, craft_v2, conservative, radical_panel, trevelyan_woodcourt, trevelyan_rosen, all_swapped), each run through both pipelines with identical Phase 0 (segment design) and Phase 3 (script generation). Total corpus: 70,473 transport words, 80,796 embedding words.

## Setup

Both pipelines select ~30 passages from the same enriched corpus and feed them to the same Phase 3 script generator (Sonnet). The only difference is *how* passages are selected:

- **Transport:** min-cost flow solver over structured metadata, with hard constraints for expert demands, character arcs, and episode structure.
- **Embedding:** vector retrieval + LLM curation, with the same obligations encoded as prompt instructions rather than flow constraints (the "fair" prompt with explicit arc, structure, and expert assignment types).

The question: does the selection method affect the *quality of engagement* in the generated scripts, even though the script generator is identical?

## Measures

1. **Quote recovery rate:** What fraction of assigned passages' `best_quote` fields appear (as 5-word subsequences) in the generated dialogue?
2. **Character mention density:** How many character-name mentions per 1,000 words of script?
3. **Unique characters:** How many distinct characters from the novel are mentioned per episode?
4. **Chapter reference density:** How often does the dialogue reference specific chapters, per 1,000 words?
5. **Sentence specificity:** Proportion of sentences containing a proper noun or quoted phrase.
6. **Textual deixis:** Frequency of close-reading markers ("that line," "notice how," "Dickens gives") per 1,000 words.

## Results

| Metric | Transport | Embedding | Winner |
|--------|:---------:|:---------:|--------|
| Quote recovery rate | 72% (171/238) | 90% (211/234) | Embedding |
| Character mentions / 1k words | 22.1 | 17.6 | Transport (+26%) |
| Unique characters per episode | 17.1 | 16.8 | Transport |
| Chapter references / 1k words | 0.67 | 1.35 | Embedding |
| Sentence specificity | 0.867 | 0.873 | Embedding (marginal) |
| Textual deixis / 1k words | 2.6 | 2.8 | Similar |

## Per-Pair Character Mention Density

Transport wins character density in all 8 pairs:

| Config | Transport | Embedding | Delta |
|--------|:---------:|:---------:|:-----:|
| baseline | 19.2 | 14.9 | +29% |
| more_jo | 21.6 | 17.3 | +25% |
| craft_v2 | 22.4 | 17.7 | +27% |
| conservative | 22.2 | 16.9 | +31% |
| radical_panel | 25.0 | 20.6 | +21% |
| trevelyan_woodcourt | 20.4 | 18.7 | +9% |
| trevelyan_rosen | 25.0 | 17.9 | +40% |
| all_swapped | 20.7 | 16.6 | +25% |

## Interpretation

The two pipelines produce scripts with **different kinds of specificity**:

**Transport scripts are character-dense.** The flow solver's arc constraints force passage diversity across characters, ensuring Richard, Jo, Lady Dedlock, Skimpole, Guppy, and others all appear with material that develops them. The script generator inherits this cast and weaves them into dialogue. Result: 26% more character mentions per 1,000 words, consistent across all 8 configurations (range: +9% to +40%).

**Embedding scripts integrate quotes more reliably.** The LLM curator sees the actual quotes and selects passages whose best lines are "usable" in dialogue. The flow solver optimises on metadata fields without seeing the text, so some of its selections have strong metadata profiles but quotes that the script generator doesn't pick up. Result: 90% vs 72% quote recovery.

**Embedding scripts reference chapter structure more.** The LLM curation's broader chapter spread (typically 19 chapters vs 15 for transport) gives the script generator more structural landmarks. The scripts reference "Chapter Forty-Seven" or "Chapter Two" twice as often.

**Sentence specificity is similar.** Unlike the 5-pair preliminary measurement (which showed transport ahead at 0.519 vs 0.470), the full 8-pair measurement shows near-parity (0.867 vs 0.873). Both pipelines produce scripts where ~87% of sentences contain proper nouns or quoted material. The selection method does not meaningfully affect how "grounded" individual sentences are.

**Close-reading style is indistinguishable.** Textual deixis (2.6/1k vs 2.8/1k) shows no meaningful difference. Both pipelines produce scripts that engage with the text at similar levels of analytical depth.

## Why This Matters for Comedy

In Bleak House, comedy is character-driven: Skimpole's parasitism, Guppy's proposals, Mrs. Jellyby's telescopic philanthropy, Chadband's sermons. Transport's arc constraints ensure these characters are present with material that develops them. The script generator can then *perform* the comedy rather than *describe* it. Embedding scripts tend to talk *about* humor ("Dickens' satirical voice," "the comedy is devastating") while transport scripts more often enact it through character interaction.

This is not a quality judgment — it's a structural consequence. Hard arc constraints produce character diversity; character diversity enables character-driven comedy. The embedding pipeline's LLM curation produces scripts that are smoother (better quote integration, more chapter landmarks) but less peopled.

## The Core Trade-off

| Dimension | Transport advantage | Embedding advantage |
|-----------|:------------------:|:-------------------:|
| **Character engagement** | +26% character mentions, wins all 8 pairs | — |
| **Textual fidelity** | — | +18pp quote recovery (90% vs 72%) |
| **Structural awareness** | — | 2× chapter references |
| **Sentence grounding** | — | Equivalent (~87%) |
| **Close-reading depth** | — | Equivalent (~2.7/1k) |

The transport pipeline selects *who* to talk about more effectively; the embedding pipeline selects *what to quote* more effectively. Both produce analytically engaged scripts — they just engage differently.

## Caveats

- 8 matched pairs across the full configuration space (expert swaps, arc demand overrides, panel composition changes).
- Both pipelines use the same Phase 3 prompt, so differences are entirely driven by passage selection.
- "Funnier" is an impressionistic judgment based on reading the scripts. The character-density metric is a proxy, not a direct measure of humor.
- The embedding pipeline uses the "fair" prompt (with explicit arc, structure, and expert assignment types), so the comparison is against the strongest version of the embedding approach.
- Passage overlap between pipelines is very low (mean Jaccard = 0.047), confirming they select fundamentally different material despite identical constraints.
