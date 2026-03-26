# Experimental Design: The 120-Run Matrix

## Design

The experiment matrix crosses four factors in a full factorial design:

| Factor | Levels | Description |
|--------|--------|-------------|
| **Novel** | 15 | Victorian and modernist novels spanning 5 authors, 1850–1924 |
| **Panel** | 2 | Panel A (Hartley/Blackstone/Woodcourt) vs Panel B (Trevelyan/Leigh/Rosen) |
| **Pipeline** | 2 | Transport (min-cost flow) vs Embedding (RAG with LLM curation) |
| **Host prep** | 2 | Without vs with Phase 2.5 host preparation |

This gives 15 × 2 × 2 × 2 = **120 conditions**, each producing a
full podcast episode script (7 segments, ~7,000–14,000 words).

The novels are:

| Author | Novels | Period |
|--------|--------|--------|
| Dickens | *Bleak House*, *Our Mutual Friend*, *David Copperfield*, *Hard Times* | 1850–1865 |
| Eliot | *Mill on the Floss*, *Middlemarch*, *Daniel Deronda* | 1860–1876 |
| Gaskell | *North and South*, *Cranford* | 1853–1855 |
| Forster | *A Passage to India* | 1924 |
| Collins | *No Name* | 1862 |
| Gissing | *New Grub Street*, *The Odd Women* | 1891–1893 |
| Oliphant | *Miss Marjoribanks*, *Hester* | 1866–1883 |

The selection ranges from highly canonical (Bleak House, Middlemarch)
to genuinely obscure (Miss Marjoribanks, Hester), providing variation
in likely LLM training exposure.

## Shared structure

Phases 0–2 are shared between host-prep and non-host-prep conditions
for each novel × panel × pipeline combination.  This means:

- **Phase 0** (segment design): one Haiku call produces a 7-segment
  episode plan.  The same plan is used for both the host-prep and
  non-host-prep versions.
- **Phase 1** (passage selection): transport uses a deterministic
  min-cost flow solver (zero LLM calls); embedding uses vector
  retrieval plus one Sonnet curation call.
- **Phase 2** (segment assignment): deterministic assignment of
  selected passages to segments.

Only Phase 2.5 (host preparation) and Phase 3 (script generation)
differ between the two host-prep conditions.  Phase 2.5 adds
pre-interviews (21 Haiku calls) and question planning (7 Sonnet
calls).  Phase 3 generates the script using the same Sonnet model
in both cases, but the host-prep version includes a HostBrief
with prepared questions for each segment.

## Planned comparisons

### 1. Grounding effect (Pipeline × Novel)

**Question:** Does providing explicit passages prevent confabulation,
and does the method of passage selection matter?

**Comparison:** For each novel and panel, compare the transport
and embedding conditions on quote verification rate (fuzzy 5-word
subsequence matching against source text).

**Prior result (5 novels):** All grounded conditions achieve >93%
verification.  Transport (97.7%) and embedding (97.2%) are
indistinguishable.  The grounding method does not matter; the
fact of grounding does.

**With 15 novels:** We can test whether this holds for obscure
novels where the LLM has minimal prior knowledge.  If Oliphant
novels show the same high verification rate under grounding, the
result generalises beyond canonical texts.

### 2. Host preparation effect (Host-prep × Novel × Pipeline)

**Question:** Does host preparation transform monologue-like scripts
into dialogue, and does this generalise across novels and pipelines?

**Metrics:** Questions per segment, reactive markers per segment
(regex count of agreement/disagreement phrases), host word fraction,
expert airtime proportions.

**Comparison:** For each novel × panel × pipeline, compare the
host-prep and non-host-prep versions.  The hostprep "lift" (delta
in Q/seg and reactive markers) is the primary measure.

**Prior result (6 novels):** Host prep increases questions per
segment from 0.4–2.4 to 5.0–7.6 (mean lift +4.8 Q/seg) and
reactive markers from 3.3–7.6 to 15.4–25.1 per segment (mean
lift +14.2).  The effect is consistent across novels, panels, and
both pipeline types.

**H20 test:** If the hostprep lift is larger for obscure novels
(Oliphant, Gissing) than for well-known novels (Dickens, Eliot),
this suggests that host preparation compensates for the LLM's lack
of prior knowledge.  Prior result (6 novels, all canonical): no
evidence of differential lift — the effect appears to be a fixed
addition to conversational structure.

### 3. Expert identity preservation (Host-prep × Panel)

**Question:** Does host preparation change *who speaks* or only
*how they speak*?

**Metrics:** Per-expert TF-IDF vocabulary cosine between host-prep
and non-host-prep versions (same panel, same novel, same pipeline).
Cross-expert cosine as a discriminability baseline.

**Prior result:** Same-expert cosine (0.71–0.73) consistently
exceeds cross-expert cosine (0.61–0.67).  Expert airtime proportions
shift by less than ±2 percentage points.

### 4. Passage selection manipulability (Transport-specific)

**Question:** Does changing the demand vector produce predictable,
proportional changes in the passage set?

**Comparison:** This uses the 20-panel BH data (v01–v30) rather
than the 120-run matrix.  For each pair of configurations, compute
the L1 distance between their demand vectors and the Jaccard
similarity of their passage sets.  A tight correlation means the
transport solver is a predictable editorial tool.

**Prior result (20 BH configs):** Clear gradient — 1 expert swap
produces Jaccard ~0.7–0.86, 2 swaps ~0.57–0.76, 3 swaps ~0.57–0.58.

### 5. Convergence paradox (Transport vs Embedding × Panel)

**Question:** Do transport and embedding select different passages
but produce convergent scripts?

**Comparison:** For each novel and panel, compute passage-level
Jaccard between transport and embedding (expected near zero), then
per-expert TF-IDF cosine between the two pipeline's scripts
(expected >0.5).

**Prior result (5 novels):** Passage Jaccard 0.033–0.087 (nearly
disjoint).  Per-expert content-word cosine 0.549–0.760 (strongly
convergent).  The persona dominates the content.

**With 15 novels:** We can test whether convergence holds for novels
where the LLM has less prior knowledge.  If the persona still
dominates on Oliphant, the result is robust.

### 6. Enrichment schema transfer (Cross-novel)

**Question:** Do the seven provision dimensions capture meaningful
variation across all 15 novels, or are they biased toward Dickensian
features?

**Metrics:** Per-dimension percentage of passages rated "strong."
A dimension is problematic if <5% of passages are strong for any
novel.

**Prior result (12 novels):** Six of seven dimensions transfer.
`atmosphere_setting` fails in 6/12 novels (<5% strong).
`humor_entertainment` is the most discriminating dimension
(CV=0.704), ranging from 4.2% (New Grub Street) to 28.1%
(Cranford).

### 7. Novel-dependent confabulation (No-passages baseline)

**Question:** When the LLM generates without passage grounding,
does the confabulation rate vary by novel in ways that reflect
training exposure?

**Note:** The 120-run matrix does not include a no-passages
condition.  This comparison uses the separate nop_ runs that exist
for 5 of the original novels.  Extension to the 10 new novels
(especially Oliphant) requires additional nop runs.

## Summary of statistical structure

The 120-run matrix provides:

- **60 matched pairs** for the host-prep effect (with vs without,
  same passages)
- **60 matched pairs** for the pipeline effect (transport vs
  embedding, same panel and host-prep setting, different passages)
- **60 matched pairs** for the panel effect (A vs B, same pipeline
  and host-prep setting)
- **15 within-novel clusters** for cross-novel comparison, each
  containing all 8 conditions

Each comparison is paired by design — the shared Phase 0–2 outputs
ensure that the only difference between matched pairs is the factor
being tested.
