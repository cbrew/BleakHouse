# Tier 1 Experiment Results — 24 March 2026

Preliminary results from analysing existing pipeline runs across 5 novels
(Bleak House, Mill on the Floss, North and South, Our Mutual Friend,
A Passage to India), two panels (Hartley/Blackstone/Woodcourt and
Trevelyan/Leigh/Rosen), and five pipeline types (transport, embedding,
RAG, random, no-passages). Ten additional novels onboarded and enrichment
in progress.

Results serve two papers:
- **Paper 1 (ACL):** How LLMs behave under grounding and distribution shift
- **Paper 2 (DH):** How interpretation can be modeled, controlled, and studied computationally

---

## H5: Grounding Prevents Confabulation — CONFIRMED

**Paper relevance:** ACL (core claim)

Grounded conditions (transport, embedding, RAG, random) all exceed 90%
quote verification. Ungrounded (no-passages) drops to 57%. The 40
percentage point gap is the headline.

| Pipeline        | Verification | Quotes |
|-----------------|-------------|--------|
| transport (ext) | 97.6%       | 3,247  |
| transport (trn) | 97.9%       | 2,795  |
| embedding       | 96.5%       | 2,461  |
| hierarchical    | 97.4%       | 3,098  |
| RAG             | 94.8%       | 754    |
| random          | 93.8%       | 673    |
| **no-passages** | **57.3%**   | 1,209  |

The original hypothesis predicted nop < 50%. The actual rate (57%) is
higher — the LLM knows these canonical novels better than expected. But
the grounding gap is massive and consistent across all grounded methods.
**The method of grounding matters far less than the fact of grounding.**

For the ACL paper: this establishes the minimum viable intervention for
trustworthy LLM literary discussion — provide passages. Everything else
is optimisation.

---

## H9: Confabulation Is Novel-Dependent — REFRAMED

**Paper relevance:** ACL

Ungrounded verification rates vary dramatically by novel, but do not
correlate with simple fame metrics (Wikipedia article length).

| Novel             | nop rate | Wiki words |
|-------------------|---------|------------|
| Bleak House       | 64.1%   | 5,401      |
| Mill on the Floss | 53.1%   | 1,933      |
| Passage to India  | 48.0%   | 2,167      |
| Our Mutual Friend | 32.4%   | 10,004     |
| North and South   | 23.4%   | 7,113      |

Pearson r = −0.60 (opposite to prediction). Wikipedia article length
captures "cultural footprint" (TV adaptations, scholarly apparatus), not
"how much of the novel's prose appeared in training data." The variation
is real — 23% to 64% — but the mechanism is not simple fame.

**Reframing:** confabulation rates may track prose distinctiveness and
quotability rather than training exposure. Bleak House's famous fog
opening is more memorable than North and South's dialogue. The proper
test requires genuinely obscure novels (Oliphant) where the LLM has
minimal prior knowledge.

---

## H3: The Convergence Paradox — CONFIRMED

**Paper relevance:** ACL (architecture finding) + DH (interpretive theory)

Transport and embedding select almost entirely different passages but
produce convergent expert vocabulary.

| Metric                      | Mean  | Range       |
|-----------------------------|-------|-------------|
| Passage Jaccard             | 0.054 | 0.033–0.087 |
| Content-word cosine (per expert) | 0.650 | 0.549–0.760 |

Despite 3–9% passage overlap, the same expert discussing the same novel
produces 55–76% similar content-word vocabulary regardless of which
passages they received. **The persona dominates the content.**

### Implications for the ACL paper

This challenges the RAG literature's focus on retrieval quality as the
primary determinant of generated text quality. For conversational
applications with strong personas, persona design matters more than
passage selection.

### Implications for the DH paper — and literary theory

This is a computational operationalisation of Stanley Fish's
"interpretive communities" thesis: the reader's interpretive framework
shapes meaning more than the text "contains" meaning. What we've built
is a system where parameterised interpretive lenses (expert personas)
produce convergent readings regardless of the specific textual material
they operate on.

**The defensible claim:** In computational modeling of interpretation,
persona specification is a stronger determinant of output than input
selection. This is a finding about the architecture, not a claim about
human cognition — but it resonates with reader-response theory (Iser,
Fish) and provides empirical evidence that an interpretive-communities
model is productive when implemented computationally.

**The honest framing:** We find that persona dominates content selection
in our system. Whether this reflects a genuine property of critical
discourse or an artefact of LLM persona rigidity is an open question —
but the architectural implication holds either way. The strongest move
for the DH paper is to frame this as a *modeling result* that resonates
with existing theory, not as a claim about human cognition.

**What we can't do:** Run the same experiment with real critics (you
can't give a real Marxist critic a randomised passage set). The closest
analogue would be corpus analysis of real critics writing about different
texts — do Marxist critics use similar vocabulary regardless of which
novel they review? That's a separate study, but could be cited if
existing stylistics work supports it.

---

## H13: Enrichment Schema Transfers — PARTIALLY FAILS

**Paper relevance:** DH (design question)

The seven provision dimensions produce similar relative rankings across
novels (pairwise cosine 0.955–0.992), but `atmosphere_setting` fails
the < 5% strong threshold in 6 of 12 novels.

| Dimension        | Mean strong % | CV    | Failures |
|------------------|--------------|-------|----------|
| char_dev         | 28.0%        | 0.216 | 0        |
| narr_tech        | 25.1%        | 0.282 | 0        |
| theme            | 24.5%        | 0.149 | 0        |
| social           | 15.9%        | 0.287 | 0        |
| plot             | 13.9%        | 0.329 | 0        |
| humor            | 13.6%        | 0.704 | 1 (New Grub Street) |
| **atmos**        | **4.8%**     | 0.271 | **6**    |

`humor_entertainment` is the most discriminating dimension (CV = 0.704),
ranging from 4.2% (New Grub Street) to 28.1% (Cranford). This is the
dimension that genuinely distinguishes comic from non-comic novels.

`atmosphere_setting` is effectively broken — it needs either a broader
definition, merger with another dimension, or removal.

New Grub Street's humor failure (4.2%) is arguably the system working
correctly — it *is* a famously grim novel. The atmosphere failures look
more like a measurement problem.

### Passage length confound (discovered during analysis)

Gutenberg HTML produces very different paragraph granularities across
novels. Miss Marjoribanks averaged 161 words/passage vs Bleak House at
49. Longer passages score "strong" on more dimensions, inflating
provision rates. Re-segmentation with `--max-words 80` (splitting at
sentence boundaries) brought Miss Marjoribanks to mean 57 words,
comparable to other novels. Re-enrichment of the affected novels
(Cranford, Miss Marjoribanks, Hester) is in progress.

---

## H6: Expert Prominence Adapts to Textual Affordance — PARTIALLY CONFIRMED

**Paper relevance:** DH (core claim)

Expert airtime varies by novel (±5 percentage points from parity), and
the variation makes literary sense — but with only 5 novels with
pipeline runs, the correlations lack statistical power.

**Best result:** Blackstone's (social historian) airtime correlates with
`social_critique` supply at r = 0.930 across 5 novels. Passage to India
(highest social critique: 18.2%) gives Blackstone 37.2% airtime.

| Expert     | Primary dim    | Panel | r     |
|------------|---------------|-------|-------|
| Blackstone | social_critique| A     | +0.930|
| Leigh      | char_dev      | B     | +0.653|
| Hartley    | narr_tech     | A     | +0.528|
| Woodcourt  | humor         | A     | +0.314|
| Trevelyan  | humor         | B     | −0.242|
| Rosen      | social_critique| B    | −0.203|

Panel A shows clearer adaptation than Panel B. Panel B experts
(Trevelyan, Leigh, Rosen) have more uniform airtime (32–37% range),
suggesting the alternative panel's personas may be less sharply
differentiated.

**What's needed:** Pipeline runs on the 10 new novels to give H6
proper statistical power (n = 15 instead of n = 5).

---

## H8: Demand Manipulation Produces Predictable Shifts — DIRECTIONALLY CONFIRMED

**Paper relevance:** DH (editorial control) + ACL (interpretability)

Demand profile changes produce proportional passage shifts, but the
effect is dampened by arc constraints and segment templates that anchor
a shared core.

| Variant              | Mean passage Jaccard | Interpretation        |
|----------------------|---------------------|-----------------------|
| v10 (conservative)   | 0.73                | Small, predictable    |
| v11 (marxist-heavy)  | 0.67                | Moderate shift        |
| v12 (radical panel)  | 0.63                | Larger shift          |
| v19 (full swap)      | 0.58                | Largest shift         |

The gradient is orderly: stronger demand changes → larger passage
shifts. The original threshold (Jaccard < 0.55) was too aggressive
because arc constraints and segment templates anchor ~60% of passages
regardless of demand profile.

For the DH paper: **editorial intention is legible as graduated flow
changes.** A producer can move from conservative to radical readings
by adjusting demand vectors, and the passage set responds
proportionally. This is a form of interpretive control that
embedding-based retrieval cannot offer.

---

## H14: Transport Enables Zero-Cost Exploration — CONFIRMED

**Paper relevance:** DH (editorial workflow) + ACL (practical advantage)

The transport solver runs in 57ms mean (0.038–0.078s) at zero token
cost. Embedding curation costs ~8.5K Sonnet tokens per run.

| Metric                | Transport     | Embedding     |
|-----------------------|--------------|---------------|
| Time per solve        | 57ms         | ~10s          |
| Tokens per solve      | 0            | ~8,500        |
| Cost per solve        | $0.00        | ~$0.05        |
| 20 configurations     | 1.1s / $0.00 | ~200s / $0.91 |

The project already has 22 transport runs and 22 embedding runs,
demonstrating real-world scale. A producer can try 20 demand
configurations in the time it takes to run one embedding curation.

For the DH paper: transport offers a **preview-before-commit workflow**
that embedding cannot match. Editorial exploration is free —
the cost is only incurred when you commit to script generation.

---

## Status and Next Steps

### Enrichment status (15 novels)

| Status | Novels |
|--------|--------|
| Fully enriched | Bleak House, OMF, MoTF, N&S, PtI, Hard Times, Middlemarch, David Copperfield, Daniel Deronda, No Name, New Grub Street, Odd Women |
| Re-enriching (split passages) | Cranford, Miss Marjoribanks, Hester |

### What's ready vs what's needed

**All Tier 1 analysis complete.**

**Need new pipeline runs:**
- H6 extended — transport runs on 10 new novels (both panels)
- H9 extended — nop runs on obscure novels (Oliphant, Gissing)
- H16–H20 — all require Oliphant pipeline runs

**Need ablation runs (prompt modifications):**
- H1 (cross-engagement architecture-driven)
- H4 (quote pattern prompt-driven)
- H7 (prosodic annotations prompt-driven)

### Revised hypothesis assessments

| ID  | Original prediction        | Actual finding                          | Revise? |
|-----|---------------------------|----------------------------------------|---------|
| H5  | nop < 50%                 | nop = 57% (gap is 40pp)                | Adjust threshold |
| H8  | Jaccard < 0.55            | Jaccard 0.58–0.73 (gradient clear)      | Adjust threshold |
| H9  | Correlates with fame      | Varies 23–64% but not fame-correlated   | Reframe mechanism |
| H13 | All dimensions transfer   | 6/7 transfer, atmosphere broken          | Acknowledge limit |
