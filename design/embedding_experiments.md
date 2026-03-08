# Can Embeddings Carry the Load?

**Context:** The contextual retrieval pipeline embeds 6,916 enriched passages
into LanceDB using `text-embedding-3-small`. The transport-based applications
(podcast assignment, study guide) depend on these embeddings for retrieval. But
retrieval is only the first step — the harder question is whether embedding
similarity is a sufficient basis for the editorial and analytical decisions the
system makes.

This document identifies where embeddings are likely to succeed, where they're
likely to fail, and proposes experiments to find the boundaries — all without
requiring human editorial judgment.

---

## What Embeddings Encode and What They Don't

Text embeddings capture distributional semantics — "what words appear near what
other words" compressed into a dense vector. They're good at:

- **Topical similarity.** Passages about fog cluster together.
- **Lexical paraphrase.** "The court delayed proceedings" is near "Chancery
  postponed the hearing."
- **Genre/register similarity.** Formal legal prose clusters separately from
  intimate first-person narration.

They're weak at or blind to:

- **Narrative function.** A passage that *describes* poverty and one that
  *satirizes* poverty embed similarly but serve different editorial purposes.
- **Structural position.** A chapter opening and its climax may discuss the
  same topic but have very different value.
- **Negation and stance.** "Jarndyce trusted Richard" and "Jarndyce no longer
  trusted Richard" are close in embedding space but opposite in meaning.
- **Literary quality.** Two passages with identical themes but different prose
  — one quotable, one pedestrian — embed similarly.
- **Arc progression.** Richard in chapter 5 (hopeful) and Richard in chapter 50
  (destroyed) embed near each other because both mention Richard and the law,
  but they represent opposite endpoints of an arc.

The enrichment pipeline was designed to capture what embeddings miss:
`plot_function`, `interest_score`, `quotability`, `narrator`, the `prov_*`
fields. The question is whether the two representations — embedding vectors
and enrichment metadata — are complementary, redundant, or in tension.

---

## The Core Engineering Question

The system has three representations of each passage:

1. **Raw text** — the original Dickens prose
2. **Embedding vector** — 1536-dimensional dense representation
3. **Enrichment metadata** — 20 structured fields from LLM analysis

The embedding input currently concatenates context + text + metadata:

```
{context}

{text}

Characters: {characters_present}
Themes: {themes}
Summary: {summary}
```

This means the embedding already encodes *some* enrichment information. But how
much? And is the encoding faithful? When we search for "social critique of
institutions," do we get passages where `prov_social_critique: strong`, or
passages that happen to mention institutions in any context?

---

## Evaluation Without Human Judges

No editorial quality evaluation is available within the scope of this work —
no user studies, no expert panels. This constrains the experiments but does
not prevent useful findings, because the enrichment metadata itself serves as
the reference standard.

The enrichment data was produced by an LLM reading each passage against a
20-field schema and validated during the enrichment pipeline. It is not ground
truth in the strong sense — a Dickens scholar might disagree with some
annotations. But it is the best structured annotation we have, it is
internally consistent, and it captures distinctions (narrative function,
quotability, character development) that embeddings plausibly cannot.

Using enrichment as the reference standard makes the experiments a test of
*internal coherence*: does the embedding representation faithfully encode
what the enrichment pipeline found? Do retrieval and transport recover the
structure that enrichment identified? This is circular in principle — we're
measuring the system against itself. But it is informative in practice,
because embeddings and enrichment are produced by *different processes*
(geometric compression vs. structured LLM analysis). Where they agree, both
representations are capturing something real. Where they diverge, we learn
which aspects of the text each representation encodes and which it drops.

The claims this supports:

- Embeddings and enrichment capture partially overlapping, partially orthogonal
  information. (Which fields overlap, which don't?)
- Retrieval by embedding similarity alone does or does not recover editorially
  relevant properties. (How large is the gap?)
- The transport layer produces materially different assignments when using
  metadata costs vs. embedding costs. (Different how?)
- Redundancy in transport space does or does not correspond to redundancy in
  embedding space. (What notion of redundancy does each representation encode?)

None of these claims requires a human to say "this podcast is good." The
editorial quality question — does the system help a human produce a better
podcast? — is a separate study requiring user evaluation and time we don't
have. The contribution here is characterizing the representations and the
division of labor between them.

---

## Experiments

### Experiment 1: Embedding Space Structure (Descriptive)

**Question:** What does the embedding space of Bleak House look like?

**Method:**
1. UMAP or t-SNE projection of all 6,916 passage embeddings to 2D.
2. Color by: chapter, narrator, interest_score, dominant theme, plot_function.
3. Identify clusters. Do they correspond to chapters? Characters? Themes?
   Narrator voice? Something else?
4. Find anomalies: passages that embed far from their chapter neighbors.

**What we learn:** The geometry that embeddings impose on the novel. If
passages cluster primarily by chapter (likely — chapter text is in the
context), the embedding space is organized by locality, not by the thematic
and functional dimensions the transport layer needs. This would confirm that
embeddings and enrichment metadata serve fundamentally different purposes.

**Evaluation:** Purely descriptive. No reference standard needed.

### Experiment 2: Embedding-Enrichment Alignment (Quantitative)

**Question:** How well do embedding neighborhoods correspond to enrichment
field values?

**Method:**
1. For each enrichment field (e.g. `prov_social_critique`), partition passages
   into groups by field value (none / weak / strong).
2. Compute mean embedding vector per group.
3. Measure separation: cosine distance between group centroids, intra-group
   variance, silhouette score.
4. Repeat for all 20 fields.

**Expected results:** Some fields will align well with embedding space
(`narrator`, `themes` — strong lexical correlates). Others won't
(`quotability`, `interest_score` — prose quality and editorial judgment that
embeddings don't capture).

**What we learn:** Which enrichment fields are redundant with embeddings (and
thus don't need to be in the embedding input), and which carry orthogonal
information (and thus are essential for the transport layer).

**Evaluation:** Silhouette scores and centroid distances are measurements, not
judgments.

### Experiment 3: Retrieval Precision Against Enrichment Fields

**Question:** When we retrieve the top-k passages for a query, how often do
the results have the enrichment properties we want?

**Method:**
1. Construct 20-30 probe queries derived from the enrichment schema's own
   categories. Each query has expected enrichment properties:
   - "fog and atmosphere in London" → `prov_atmosphere_setting: strong`
   - "Esther's feelings about her identity" → `narrator: esther`,
     `prov_character_development: strong`
   - "satirical commentary on the legal system" →
     `prov_social_critique: strong`, `prov_humor_entertainment: strong`
   - "quotable passages about Chancery" → `quotability: strong`
2. For each query, retrieve top-20 by vector search.
3. Score: fraction of results matching the expected enrichment properties.
4. Compare: (a) vector search alone, (b) metadata-only filtering,
   (c) hybrid (vector + metadata filter), (d) vector re-ranked by metadata.

**What we learn:** The gap between "topically relevant" (what embeddings find)
and "editorially useful" (what downstream applications need). If the gap is
large, the transport layer is doing essential work that retrieval can't.

**Evaluation:** The queries are constructed from the schema, and precision is
measured against enrichment fields. This is schema-internal validation — it
tests whether retrieval can recover the structure that enrichment found, not
whether that structure is "correct." That's the right question for an
engineering paper.

### Experiment 4: Contextual Retrieval Validation

**Question:** Does prepending LLM-generated situating context before embedding
actually help for this corpus?

**Method:**
1. Embed passages into two separate LanceDB tables: with and without context
   (both versions exist from the generate_contexts pipeline step).
2. Run the probe query set from Experiment 3 against both.
3. Measure: precision against enrichment fields, chapter diversity of results,
   and whether context-enhanced retrieval surfaces passages from non-obvious
   chapters.

**What we learn:** The Anthropic contextual retrieval paper reports 35-67%
improvement on generic corpora. Bleak House is unusual: a single coherent novel
with strong chapter-level locality. Context might help less (passages already
carry strong chapter signal) or more (context disambiguates passages that are
locally similar within a chapter but serve different roles). Either finding is
informative.

**Evaluation:** Same automatic metrics as Experiment 3.

### Experiment 5: Embedding Input Ablation

**Question:** Does including enrichment metadata in the embedding input improve
retrieval, or add noise?

**Method:**
1. Create four embedding variants for all passages:
   - (a) Text only
   - (b) Context + text
   - (c) Context + text + all metadata (current approach)
   - (d) Context + text + selected metadata (only fields that showed weak
     alignment in Experiment 2 — the fields embeddings *don't* already capture)
2. Run the probe queries, measure retrieval precision at k=5, k=10, k=20.
3. Also measure result diversity: chapter spread, narrator balance.

**What we learn:** Whether the kitchen-sink embedding input helps or whether a
targeted composition (adding only metadata that embeddings miss) is better.
Experiment 2 tells us which fields are orthogonal; this experiment tests
whether injecting those fields into the embedding input actually improves
retrieval or just dilutes the signal.

**Evaluation:** Automatic metrics against enrichment fields. Depends on
Experiment 2 results to inform variant (d).

### Experiment 6: Character Arc Retrieval

**Question:** Can embedding-based retrieval reconstruct a character arc?

**Method:**
1. Select characters with clear arcs: Richard Carstone (hopeful → obsessed →
   destroyed), Lady Dedlock (composed → exposed → flight), Esther (uncertain
   → secure).
2. For each, query: "Richard Carstone's relationship with Jarndyce and
   Jarndyce" (etc.).
3. Retrieve top-30 by vector search. Order results by chapter.
4. Measure automatically:
   - **Coverage:** What fraction of chapters where the character appears
     (known from `characters_present` in enrichment) are represented in
     the retrieved set?
   - **Ordering:** Kendall's tau between the chapter order of retrieved
     passages and the true chapter sequence.
   - **Arc endpoint coverage:** Are passages from the first and last
     quarters of the character's appearances included?
5. Compare against: metadata-filtered retrieval (`characters_present` contains
   the character, `prov_character_development != "none"`, ordered by chapter).

**What we learn:** Embeddings retrieve by similarity, which is unordered. Arcs
are ordered. If the embedding-retrieved set clusters in a few chapters rather
than spanning the character's trajectory, that's evidence the transport layer
(which can enforce chapter-order progression via sequential arc pricing) is
essential for narrative applications.

**Evaluation:** Coverage, Kendall's tau, and endpoint coverage are all
automatic. The list of "character chapters" comes from the enrichment data.

### Experiment 7: Transport Assignments — Embeddings vs. Metadata Costs

**Question:** If we use embedding similarity as the transport cost function
instead of enrichment-derived costs, how different are the assignments?

**Method:**
1. Run the podcast expert assignment transport problem twice:
   - (a) Costs from enrichment metadata: expert demand matched against
     passage provision fields.
   - (b) Costs from embedding similarity: expert profile embedded as text,
     cost = 1 - cosine_similarity(passage, expert_profile).
2. Measure divergence: overlap percentage, which passages differ, enrichment
   profiles of differing passages.
3. For divergent assignments, characterize the difference: does the
   embedding-cost version assign passages with lower interest_score? Wrong
   narrator? Lower quotability? The enrichment fields provide the
   characterization without human judgment.

**What we learn:** Whether embeddings can substitute for structured enrichment
in the transport cost function. If the assignments are very different — and if
the embedding-cost version systematically assigns passages with weaker
enrichment profiles — that confirms the enrichment layer is doing non-trivial
work that embedding similarity cannot recover.

**Evaluation:** Divergence metrics and enrichment profile comparison. No
quality judgment needed — if the embedding-cost version assigns a
`quotability: none` passage where the metadata-cost version assigns
`quotability: strong`, the enrichment field is the reference standard.

### Experiment 8: The Redundancy Question

**Question:** When the transport solver penalizes redundancy (via convex costs),
are embedding-similar passages being suppressed, or something else?

**Method:**
1. Run transport assignment without redundancy penalties. Record assignments.
2. Run with redundancy penalties (arc duplication trick). Record assignments.
3. For each replaced passage, measure:
   - Embedding distance between replaced and replacement
   - Enrichment profile distance (Hamming distance on discretized fields)
   - Whether the replacement comes from a different chapter, narrator, or
     character cluster
4. Characterize: is transport-redundancy the same as embedding-redundancy
   (near-duplicate text), enrichment-redundancy (same metadata profile), or
   a distinct notion constructed from the interaction of supply, demand, and
   cost structure?

**What we learn:** Whether redundancy in transport space corresponds to
redundancy in embedding space. If they diverge — passages that are
"redundant" for transport purposes are far apart in embedding space — the
transport layer captures a notion of redundancy that embeddings don't encode.
This would be a concrete example of the transport layer doing work that the
standard RAG paradigm cannot.

**Evaluation:** Distances and profile comparisons. Purely computational.

---

## Execution Plan

### Data Requirements

All experiments use the same base data:
- `data/passages_enriched.json` — 6,916 passages with 20-field enrichment
- `data/passages_contextual.json` — same, with situating context
- `data/bleak_house_vectors/` — LanceDB table with embeddings

Additional artifacts (built as needed):
- **Probe query set** (Experiments 3-5) — 20-30 queries with expected
  enrichment properties. Constructed once from the schema categories.
- **Alternate embedding tables** (Experiments 4-5) — same passages, different
  embedding input compositions. Four tables total.
- **Expert profile embeddings** (Experiment 7) — expert descriptions as text,
  embedded with the same model.
- **Visualization** (Experiment 1) — UMAP + matplotlib. Lightweight.

### Suggested Order

```
Experiment 1: Embedding Space Structure
    ↓ (informs which fields to focus on)
Experiment 2: Embedding-Enrichment Alignment
    ↓ (identifies orthogonal fields)
Experiment 3: Retrieval Precision
Experiment 4: Contextual Retrieval Validation
    ↓ (these two share the probe query set)
Experiment 5: Embedding Input Ablation
    ↓ (uses orthogonal fields from Exp 2)
Experiment 6: Character Arc Retrieval
    ↓ (independent, can run in parallel with 3-5)
Experiment 7: Transport Assignments
Experiment 8: Redundancy
    ↓ (these two require the transport implementation)
```

Experiments 1-6 can run with the existing pipeline. Experiments 7-8 require
the transport assignment implementation (see `transport_applications.md`).

Start with Experiment 1 because it's cheap, fast, and tells you what questions
to sharpen. Everything downstream benefits from knowing the embedding space
geometry before measuring it.

---

## What's at Stake

If embeddings carry most of the load — if retrieval alone recovers 90% of the
enrichment structure — then the transport layer is optimization polish on a
solid foundation. The paper's contribution is the enrichment pipeline and
contextual retrieval; transport is a refinement.

If embeddings fail on the dimensions that matter — narrative function, arc
progression, quotability, the difference between describing poverty and
satirizing it — then the transport layer is essential infrastructure. The
paper's contribution is demonstrating that structured metadata and
combinatorial optimization solve problems the dominant paradigm (embed
everything, retrieve by similarity) cannot.

The answer is almost certainly "embeddings handle some things, metadata handles
others, and the interesting question is the interaction." But *which* things,
and *how much* of the load each carries, is an empirical question. The current
RAG and contextual retrieval literature hasn't addressed it for literary or
long-document analytical tasks, where the text has narrative structure,
character arcs, shifting register, and editorial dimensions that go beyond
topical relevance.

These experiments won't tell us whether the system produces a good podcast.
They will tell us what the representations encode, where they agree, where
they diverge, and what that implies for any system that depends on them. That's
a contribution to the engineering foundations of document analysis, applicable
beyond this project.
