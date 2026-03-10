# Embeddings vs. Transport: What the Experiments Aim to Show, and What They Actually Show

## 1. The Question

Standard Retrieval-Augmented Generation retrieves passages by embedding similarity:
embed the query, embed the corpus, return the nearest neighbours. This works well
for topical retrieval. But the podcast pipeline needs more than topical relevance
--- it needs to select passages that *serve specific editorial functions* (social
critique, character development, atmosphere) and allocate them across experts and
episode segments under explicit constraints.

The experiments test a specific hypothesis: **structured enrichment metadata and
min-cost flow assignment do essential work that embedding-based retrieval alone
cannot replicate.** The alternative hypothesis is that embeddings encode enough
of the enrichment structure that the transport layer is just optimisation polish
on a solid foundation.

The answer determines where the system's value lies. If embeddings carry most of
the load, the contribution is the enrichment pipeline and contextual retrieval.
If they don't, the contribution is demonstrating that combinatorial optimisation
over structured metadata solves problems the dominant paradigm cannot.

## 2. The Two Representations

Every passage has three representations:

1. **Raw text** --- the original Dickens prose.
2. **Embedding vector** --- 1,536 dimensions from OpenAI `text-embedding-3-small`,
   with input composed from situating context + text + selected metadata fields.
3. **Enrichment metadata** --- 20 structured fields from LLM analysis, including
   7 provision dimensions (`prov_character_development`, `prov_plot_advancement`,
   `prov_thematic_depth`, `prov_social_critique`, `prov_humor_entertainment`,
   `prov_atmosphere_setting`, `prov_narrative_technique`), each rated
   none/weak/strong.

Embeddings capture distributional semantics --- what words appear near what
other words, compressed into geometry. They're good at topical similarity,
lexical paraphrase, and register. They're weak at or blind to narrative function
(a passage that *describes* poverty and one that *satirises* it embed similarly),
structural position (a chapter opening and its climax discuss the same topic),
arc progression (Richard hopeful in chapter 5 and Richard destroyed in chapter 50
both mention Richard and the law), and literary quality (two passages with identical
themes but different prose --- one quotable, one pedestrian --- embed similarly).

The enrichment pipeline was designed to capture what embeddings miss. The question
is whether the two representations are complementary, redundant, or in tension.

## 3. Evaluation Strategy

No human editorial judgments are available --- no user studies, no expert panels.
The experiments use the enrichment metadata itself as the reference standard,
measuring whether embedding-based retrieval recovers the structure that enrichment
identified. This is schema-internal validation: circular in principle (we're
measuring the system against itself) but informative in practice, because
embeddings and enrichment are produced by different processes (geometric
compression vs. structured LLM analysis). Where they agree, both representations
capture something real. Where they diverge, we learn which aspects of the text
each representation encodes and which it drops.

## 4. The Six Experiments

### Experiment 1: Retrieval Precision Against Enrichment Fields

**Aim.** When we retrieve the top-*k* passages for a natural-language query, how
often do the results have the enrichment properties we expect? This measures the
gap between "topically relevant" (what embeddings find) and "editorially useful"
(what downstream applications need).

**Method.** 30 probe queries, each with expected enrichment properties (e.g.,
"fog and atmosphere in London" expects `prov_atmosphere_setting=strong`; "satirical
commentary on the legal system" expects both `prov_social_critique=strong` and
`prov_humor_entertainment=strong`). Four retrieval strategies tested: vector
search alone, metadata-only filtering, hybrid (vector + metadata filter), and
vector search with re-ranking by metadata match count.

**Results.**

| Strategy       | Precision@10 | Precision@20 |
|----------------|:------------:|:------------:|
| Vector only    |     0.667    |     0.650    |
| Metadata only  |     1.000    |     1.000    |
| Hybrid         |     0.757    |     0.743    |
| Vector+rerank  |     0.960    |     0.883    |

**What this shows.** Pure vector search recovers the right enrichment properties
about two-thirds of the time --- good enough for casual retrieval but not for an
editorial pipeline that needs to fill specific roles. One passage in three has
the right topic but the wrong function: it mentions institutions but doesn't
critique them, or describes a character without developing them. Metadata-only
filtering is perfect by construction (it checks the fields directly), but
requires a structured query rather than natural language. Re-ranking closes most
of the gap, getting to 96% precision at *k*=10 --- but it still needs enrichment
metadata for the re-ranking step. Embeddings alone are insufficient; embeddings
*plus* metadata get close.

**What this means for the transport pipeline.** The transport solver uses
enrichment metadata directly as its cost function. It doesn't suffer the 33%
miss rate of pure vector search because it never relies on embedding similarity
for assignment decisions. This is the core engineering argument for the system.

### Experiment 2: Character Arc Retrieval

**Aim.** Can embedding-based retrieval reconstruct a character arc --- not just
find passages about a character, but find them *across the full span* of their
trajectory through the novel?

**Method.** Three characters with clear arcs: Richard Carstone (27 chapters),
Lady Dedlock (31 chapters), Esther Summerson (42 chapters). For each, a
single query retrieves the top 30 passages by vector similarity, then we
measure chapter coverage (fraction of the character's chapters represented in
results), Kendall's tau (ordering correlation with true chapter sequence), and
arc endpoint coverage (whether early and late chapters appear).

**Results.**

| Character        | Strategy          | Coverage | Kendall &tau; | Endpoints |
|------------------|-------------------|:--------:|:-------------:|:---------:|
| Richard Carstone | Vector retrieval  |   0.370  |     1.000     |   1.000   |
| Richard Carstone | Metadata filtered |   1.000  |     1.000     |   1.000   |
| Lady Dedlock     | Vector retrieval  |   0.194  |     1.000     |   1.000   |
| Lady Dedlock     | Metadata filtered |   1.000  |     1.000     |   1.000   |
| Esther Summerson | Vector retrieval  |   0.310  |     1.000     |   1.000   |
| Esther Summerson | Metadata filtered |   1.000  |     1.000     |   1.000   |

**What this shows.** Embedding retrieval finds passages about each character but
clusters in a few chapters rather than spanning the arc: it covers only 19--37%
of the chapters where the character appears. Lady Dedlock is worst hit --- her
arc moves through very different narrative registers (composed society hostess,
exposed mother, fugitive), and embedding similarity clusters in one mode. Where
vector retrieval does find passages, the ordering is correct (Kendall &tau; = 1.0,
arc endpoints present), so the signal isn't wrong, just incomplete.

Metadata filtering achieves 100% coverage trivially: filter by
`characters_present` and `prov_character_development != none`, sort by chapter.
The structured metadata *has* the arc; the embedding *loses* it.

**What this means for the transport pipeline.** The transport solver assigns
passages to character arcs via dedicated arc-demand constraints, drawing from
specific chapters. It doesn't suffer the clustering problem because it treats
arc coverage as a constraint to satisfy, not a similarity to maximise. The
experiment confirms that this explicit arc modelling does work that embedding
retrieval cannot.

### Experiment 3: Embedding Input Ablation

**Aim.** Does including enrichment metadata in the embedding input improve
retrieval precision, or add noise?

**Method.** Four embedding variants for all passages: text only; context + text;
context + text + all metadata (the production configuration); and context + text
+ selected metadata (provision descriptions only).

**Results.**

| Embedding variant | Precision@10 | Precision@20 | Chapter spread @10 |
|-------------------|:------------:|:------------:|:------------------:|
| Text only         |     0.607    |     0.610    |        8.0         |
| Context + text    |     0.663    |     0.622    |        6.8         |
| All metadata      |     0.667    |     0.650    |        7.0         |
| Selected metadata |     0.707    |     0.657    |        6.7         |

**What this shows.** Each layer of metadata improves precision modestly. Context
alone adds about 6 percentage points over raw text. Adding enrichment metadata
gets another 4 points. The best configuration --- including only the provision
dimensions rather than all metadata --- reaches 0.707 at *k*=10, a meaningful
improvement over text-only (0.607) but still well below the metadata-filtering
ceiling of 1.0.

An interesting side effect: context and metadata *reduce* chapter spread.
Text-only embeddings spread results across 8 chapters at *k*=10; the enriched
variants concentrate in 6--7. Adding metadata makes results more precise but
more clustered --- the embedding homes in on passages with matching metadata
fields, which tend to come from the same narrative stretches.

**What this means.** Embeddings encode *some* enrichment information when you
put it in the input, but the encoding is lossy. The 0.707 precision ceiling ---
30% miss rate even with the best embedding composition --- shows that the
transport layer's direct use of metadata fields isn't redundant; it accesses
information that embeddings can represent only imperfectly.

### Experiment 4: Redundancy Analysis

**Aim.** When the transport solver penalises redundancy (via convex cluster
penalties), are the passages it swaps out "redundant" in embedding space too?
Or does transport-redundancy capture something different?

**Method.** Run the transport solver at three cluster penalty levels:
&lambda;=0 (no penalty), &lambda;=5 (default), &lambda;=20 (strict).
For each pair of penalty levels, identify passages that were replaced and measure:
embedding distance (cosine) between replaced and replacement, enrichment profile
distance (L1 on the 7-dimensional provision vector), and whether the replacement
comes from a different chapter/narrator/character cluster.

**Results.**

Across all pairwise comparisons (25 passage swaps):

| Category                           | Count |   %  |
|------------------------------------|:-----:|:----:|
| Both close (genuine duplicates)    |   0   |   0  |
| Embedding close, enrichment far    |   0   |   0  |
| Embedding far, enrichment close    |  19   |  76  |
| Both far                           |   6   |  24  |

Mean embedding distance between replaced/replacement pairs: 0.53 (moderate to
large in cosine space). Mean enrichment distance: 2.75--3.20 (modest, on a scale
where the maximum is 14). 100% of swaps moved to a different chapter. 70--100%
moved to a different character cluster.

**What this shows.** Transport-redundancy is *not* embedding-redundancy. In 76%
of cases, the solver swaps passages that are far apart in embedding space but
close in enrichment space --- they provide similar editorial function
(similar provision profiles) despite being about different topics, in different
chapters, using different vocabulary. The solver suppresses *functional*
redundancy: "I already have a strong social-critique passage for this expert,
so take one from a different cluster even though it's semantically distant."

This is the most striking finding. No zero cases in the "both close" or
"embedding close, enrichment far" categories means there are no passages
being swapped that a standard embedding-based deduplication system would have
caught. The transport layer's notion of redundancy is invisible to embeddings.

**What this means.** Standard RAG deduplication (maximal marginal relevance,
cosine-based diversity) would not have achieved the same diversity. The
transport solver's redundancy control operates in enrichment space --- a
functional, editorial notion of diversity that embeddings don't encode.

### Experiment 5: Transport Costs --- Metadata vs. Embeddings

**Aim.** If we replace the metadata-derived cost function with embedding
similarity as the transport cost, how different are the resulting passage
assignments?

**Method.** Embed expert profile descriptions with the same model, compute
cosine similarity between each passage and each expert profile, quantise to
integer costs. Run the Phase 1 transport problem twice: once with
metadata-based costs (provision strength: strong=1, weak=3) and once with
embedding-based costs (1 &minus; cosine similarity, scaled to 1--10).

**Results.**

| Metric                    | Metadata costs | Embedding costs |
|---------------------------|:--------------:|:---------------:|
| Passages assigned         |       10       |       12        |
| **Overlap (shared passages)** |   **0**    |    **0**        |
| Mean interest score       |      3.29      |      2.36       |
| Mean provision strength   |      7.71      |      6.55       |

Provision strength breakdown for metadata-only passages:

| Dimension              | strong | weak | none |
|------------------------|:------:|:----:|:----:|
| prov_humor_entertainment |   3   |  0   |  4   |
| prov_social_critique    |   3   |  1   |  3   |
| prov_character_development | 1  |  5   |  1   |

For embedding-only passages:

| Dimension              | strong | weak | none |
|------------------------|:------:|:----:|:----:|
| prov_humor_entertainment |   1   |  2   |  8   |
| prov_social_critique    |   3   |  4   |  4   |
| prov_character_development | 6  |  4   |  1   |

**What this shows.** Zero overlap. The two cost functions select completely
disjoint passage sets. This is the strongest possible evidence that embedding
similarity and enrichment metadata encode different things: when used as cost
functions in the same optimisation framework, they route different passages to
different experts.

Metadata-based costs select passages with higher interest scores (3.29 vs. 2.36)
and stronger provision ratings (7.71 vs. 6.55 mean total strength). They also
find more humor: 3 strong humor passages vs. 1. Embedding costs over-index on
character development (6 strong vs. 1) --- passages that mention the expert's
thematic concerns without necessarily serving the editorial function the expert
needs.

The difference is between "this passage is *about* the social historian's
interests" (embedding similarity) and "this passage *provides* what the social
historian needs" (metadata costs). These are not the same thing.

### Experiment 6 (implicit): Variant Analysis

**Aim.** Do different transport configurations produce measurably different
podcast scripts --- not just different passage selections, but different
*language*?

**Method.** 20 variant configurations run through the full pipeline (transport
selection + LLM script generation). 8 selected for detailed analysis using
Kilgarriff G2 log-likelihood keyword comparison, pairwise chi-squared lexical
distance, and speaker distribution analysis.

**Results.**

- **88 unique passages** drawn across 20 variants, with a mean of 31.3 per variant.
- **10 core passages** appear in all 20 variants (Richard and plot-heavy material
  from chapters 11, 13, and 17).
- **29 passages (33%)** are unique to a single variant.
- **Mean pairwise Jaccard similarity: 0.521** --- variants share about half their
  passages.
- **Most different:** V07 (skip Dedlock) vs. V10 (conservative panel) at J=0.239.
- **Most similar:** V02 (more Jo) vs. V04 (craft focus) at J=0.882.
- **Chapter coverage ranges from 13 to 19** depending on configuration.
- **NULL flow = 0 in 19/20 variants** --- the transport solver reliably fills all
  segments regardless of configuration.

Keyword analysis confirms that passage-level differences propagate through
LLM generation into vocabulary: expert-panel swaps produce distinctive vocabulary
profiles (Rosen-present variants emphasise "system", "class", "machinery";
Trevelyan-present variants emphasise "laughter", "comedy", "wit"; Edmund-present
variants emphasise "moral", "mystery", "soul"). The G2 keywords are recognisable
*caricatures* of academic discourse --- exactly the parody the system aims to expose.

## 5. What the Experiments Collectively Show

### The intended claim

Embeddings and enrichment capture partially overlapping, partially orthogonal
information. The transport layer does essential work that embedding-only RAG
cannot replicate: it selects passages by editorial function rather than topical
similarity, enforces arc coverage as a constraint rather than hoping similarity
recovers it, controls functional redundancy in a space invisible to embeddings,
and produces interpretably different outputs when parameters change.

### What the evidence actually supports

The claim holds, but with qualifications.

**Strong evidence:**

- **Retrieval precision gap is real** (Experiment 1). Vector search has a 33%
  miss rate on enrichment properties. The transport layer's direct metadata use
  eliminates this.
- **Arc coverage gap is dramatic** (Experiment 2). Vector search covers 19--37%
  of character arcs; metadata covers 100%. The transport solver's arc constraints
  do work embeddings cannot.
- **Transport-redundancy is invisible to embeddings** (Experiment 4). 76% of
  redundancy swaps involve passages that are far apart in embedding space.
  Standard RAG diversity methods would not catch them.
- **Cost functions select disjoint passages** (Experiment 5). Zero overlap between
  metadata-cost and embedding-cost assignments. The two representations route
  different material to the same experts.
- **Configuration changes propagate to language** (Experiment 6). Different
  passage selections produce measurably different vocabulary, confirming the
  pipeline is not washing out upstream differences.

**Weaker evidence:**

- **Embedding enrichment helps modestly** (Experiment 3). Including provision
  metadata in the embedding input improves precision by 10 percentage points
  over text-only. The gap between best-embedding (0.707) and metadata-only (1.0)
  is narrower than the gap between text-only (0.607) and metadata-only, but
  still substantial.

**What the experiments do not show:**

- Whether the generated podcasts are *good*. The experiments measure internal
  coherence (does the pipeline recover its own enrichment structure?) and
  configuration sensitivity (do parameter changes produce different outputs?).
  They do not measure whether any configuration produces something a listener
  would want to hear.
- Whether a human producer benefits from the inspectability. The claim that
  interacting with gap reports and coverage maps produces observations the user
  wouldn't otherwise reach is a hypothesis, not a finding. Testing it requires
  user studies with literary scholars.
- Whether the enrichment schema is correct. The schema was designed, and the
  experiments measure the system against itself. A Dickens scholar might disagree
  with some annotations. The contribution is the *infrastructure* for comparing
  representations, not a claim that the current schema is definitive.

### The honest summary

The experiments show that embedding similarity and structured enrichment encode
genuinely different information about literary passages. Embeddings capture
topical proximity; enrichment captures editorial function. The transport layer
exploits the difference: it selects by function, enforces constraints embeddings
cannot express, and controls a notion of redundancy that embeddings don't
encode. Twenty configurations, varying panel composition and arc emphasis, produce
measurably different outputs --- different passages, different vocabulary,
different caricatures of academic discourse.

The system's value is *diagnostic*. It makes the relationship between editorial
assumptions and generated output navigable, turning a black-box pipeline into a
space of configurations that can be explored, compared, and critiqued. The
experiments don't prove the system is useful for podcast production. They prove
it's doing something that standard RAG provably does not.
