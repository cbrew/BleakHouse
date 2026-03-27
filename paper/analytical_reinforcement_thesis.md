# Document 1: The Analytical Reinforcement Thesis

## The Claim

An LLM's ability to quote a novel faithfully from memory depends not on whether the novel's text appears in its training data — all 15 of our novels are on Project Gutenberg and almost certainly do — but on the volume of **analytical reinforcement**: the secondary literature (study guides, academic papers, Wikipedia articles, blog posts, teaching materials) that quotes and re-quotes specific passages.

## The Empirical Process

### Step 1: The puzzle

Our no-passages (nop) experimental condition asks the LLM to generate literary discussion from prior knowledge alone. Across 15 novels, the rate at which the LLM produces verifiable quotes ranges from 57% (Middlemarch) to 0% (Hester, No Name). This is a dramatic gradient.  Why?

The naive explanation — "the model hasn't seen the text" — is almost certainly wrong.  All 15 novels are in the public domain, available from Project Gutenberg, and Gutenberg texts are a standard component of web-scraped training corpora (C4, The Pile, etc.).  The raw text of Hester is in the training data.  Yet the model cannot quote it.

### Step 2: The hypothesis

If the text itself is present, the gradient must reflect something about the *reinforcement* of specific passages.  Carlini et al. (2023) showed that LLM memorisation grows log-linearly with three factors: model capacity, data duplication, and prompt length.  For novels, model capacity and prompt length are constant across our experiments.  The variable is **data duplication** — not of the source text (which appears once on Gutenberg) but of its most-quoted passages, which are duplicated across secondary sources.

A famous passage from Bleak House — the fog opening, Jo's death, Lady Dedlock's flight — appears not only in the Gutenberg text but in:
- SparkNotes and CliffsNotes summaries
- LitCharts and Shmoop study guides
- Hundreds of academic papers
- Thousands of blog posts, reviews, and social media discussions
- Wikipedia articles with lengthy plot summaries and analysis
- University course materials and reading lists

A passage from Hester appears in the Gutenberg text and virtually nowhere else.

The hypothesis: **the LLM's per-novel quote fidelity tracks the volume of secondary analytical discussion, not the presence of the primary text.**

### Step 3: The measurement

We constructed a composite "critical attention score" for each novel using three proxies:

1. **Goodreads ratings count** — a proxy for present-day readership.  Log-normalised to reduce the effect of extreme popularity.
2. **Wikipedia article word count** — a proxy for encyclopaedic/analytical attention.  Longer articles contain more plot summary, analysis, and quoted excerpts.
3. **Study guide presence** — a binary indicator of curriculum presence (SparkNotes, LitCharts, or equivalent).  Study guides are particularly important because they systematically excerpt and re-quote key passages.

Each proxy was normalised to [0, 100] and combined with equal weights to produce a composite score.

### Step 4: The results

| Novel | Nop% | GR Ratings | Wiki Words | Study Guide | Attention |
|---|---|---|---|---|---|
| Middlemarch | 57 | 181,000 | 8,750 | Y | 79.2 |
| Bleak House | 53 | 98,000 | 8,750 | Y | 75.9 |
| David Copperfield | 44 | 261,000 | 19,000 | Y | 100.0 |
| Hard Times | 39 | 75,000 | 6,750 | Y | 70.8 |
| A Passage to India | 39 | 73,000 | 4,350 | Y | 66.2 |
| Mill on the Floss | 37 | 59,000 | 3,000 | Y | 62.6 |
| Cranford | 33 | 48,000 | 2,900 | N | 27.9 |
| Daniel Deronda | 30 | 27,000 | 3,500 | Y | 59.3 |
| Our Mutual Friend | 29 | 32,000 | 8,750 | Y | 69.8 |
| New Grub Street | 20 | 6,300 | 3,200 | N | 17.5 |
| The Odd Women | 6 | 5,500 | 1,200 | N | 13.1 |
| Miss Marjoribanks | 3 | 2,600 | 850 | N | 8.4 |
| **North and South** | **2** | **182,000** | **8,750** | **Y** | **79.2** |
| Hester | 0 | 548 | 1,300 | N | 0.8 |
| No Name | 0 | 7,900 | 3,200 | N | 18.7 |

**All 15 novels: Pearson r = 0.72, Spearman ρ = 0.70**

**Excluding North and South: Pearson r = 0.89, Spearman ρ = 0.90**

### Step 5: The outlier

North and South is the single dramatic outlier: an attention score of 79.2 (comparable to Middlemarch and Bleak House) but a nop verification rate of only 2%.  Its Goodreads popularity is almost certainly inflated by the 2004 BBC television adaptation starring Daniela Denby-Ashe and Richard Armitage, which generated a large modern fandom.  But this fandom discusses the *adaptation* — its casting, its romance, its divergences from the novel — not the novel's prose passage by passage.

North and South has a LitCharts study guide (contributing to the attention score) but the study guide does not generate the kind of passage-level duplication that SparkNotes/CliffsNotes do for novels like Middlemarch, which are routinely assigned in literature courses.

This suggests a refinement: what matters is not generic "attention" but specifically **passage-quoting attention** — secondary literature that reproduces specific textual fragments.

### Step 6: The connection to Carlini

Carlini et al. (2021, 2023) showed:
- LLMs memorise training data and can reproduce it verbatim
- Memorisation grows log-linearly with data duplication
- More-duplicated sequences are more extractable

Our findings are the literary-critical face of this technical phenomenon:
- The fog opening of Bleak House is duplicated across hundreds of secondary sources → the LLM can reproduce it from memory
- A passage from Chapter 12 of Hester appears once on Gutenberg and nowhere else → the LLM cannot reproduce it

The gradient from 57% to 0% is a **literary-critical measurement of data duplication effects**.

## Conclusions

1. The raw presence of a text in training data is necessary but not sufficient for an LLM to quote it faithfully.  What matters is **analytical reinforcement** — the duplication of specific passages across secondary literature.

2. This reinforcement tracks what we might call **critical-cultural prominence**: the degree to which a novel has been absorbed into the analytical apparatus of literary culture (study guides, academic papers, Wikipedia, teaching materials).

3. The composite attention score predicts nop verification rate with r = 0.89 (excluding one outlier), suggesting that 79% of the variance in LLM quotation fidelity is explained by critical attention.

4. The North and South outlier reveals that **popularity ≠ analytical engagement**.  A novel can be widely read (or widely watched) without generating the passage-level analytical discussion that reinforces specific textual fragments in training data.

5. This reframes the "hallucination" gradient as a **cultural-historical measurement**: the LLM's differential ability to quote novels is a measurable trace of each novel's position in the critical-cultural ecosystem, refracted through the composition of web-scraped training corpora.
