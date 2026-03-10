# Plain RAG Pipeline Design (Third Baseline)

**Date:** 2026-03-10
**Status:** Design complete, not yet implemented

## Motivation

The existing comparison has two pipelines:
- **Transport:** min-cost flow over enriched metadata (provisions, arcs, interest scores)
- **Embedding:** vector retrieval + LLM curation with structured obligations

Both benefit from the enrichment pipeline's 20-field `FieldReportEnrichment` per passage.
The question: how much value does that enrichment add? A plain RAG baseline that uses
*none* of the enrichment can answer this.

## Design Principles

1. **No enrichment metadata.** The pipeline sees only raw passage text and expert descriptions.
2. **No LLM curation.** Assignment is purely by vector similarity — no chain-of-thought reasoning.
3. **No arc/structure obligations.** No knowledge of character arcs, episode structure, or provision dimensions.
4. **Same Phase 0 and Phase 3.** Segment design and script generation are identical, so differences are purely from passage selection.

## Pipeline

```
Phase 0: design_segments() → templates        [identical to other pipelines]
Phase 1+2: plain RAG assignment               [NEW — replaces flow solver and LLM curation]
Phase 3: generate_segment_script()            [identical to other pipelines]
```

### Phase 1+2: Plain RAG Assignment

**Step 1: Build expert query texts.**

For each expert, compose a natural-language profile from the `ExpertPersona` fields:

```
Eleanor Hartley, literary critic.
{persona.description}
Speaking style: {persona.speaking_style}
```

This is what gets embedded — the expert's identity as a text string. No mention of
provision dimensions, arc demands, or structured metadata.

**Step 2: Build segment query texts.**

For each segment template, compose a query from its name and description:

```
Segment: {template.name}
Type: {template.segment_type}
Focus: {template.description}
```

**Step 3: Embed everything.**

Use the existing LanceDB table (`data/bleak_house_vectors`, `passages` table) which
has pre-computed OpenAI `text-embedding-3-small` vectors for all 6,916 passages.

Embed the expert queries and segment queries using the same model.

**Step 4: Retrieve per expert.**

For each expert, retrieve top-k passages by cosine similarity to their profile embedding.
k = ceil(passage_target / num_experts) to get roughly equal allocation.

**Step 5: Retrieve per segment.**

For each segment template, retrieve top-k passages by cosine similarity to the segment query.
k = template.max_passages.

**Step 6: Merge and deduplicate.**

Union the expert-retrieved and segment-retrieved pools. For each passage, assign to the
expert with highest similarity. If a passage was retrieved by a segment query but not
any expert, assign to the expert whose profile is most similar.

Cap total at `passage_target` (default 32), prioritizing by similarity score.

**Step 7: Assign to segments.**

Distribute passages across segments using a simple greedy approach:
- For each segment, take passages whose segment-query similarity is highest,
  up to `template.max_passages`.
- Any unassigned passages go to the segment with fewest passages.

**Step 8: Build Phase 1 + Phase 2 output format.**

Convert to the same `phase1_assignments.json` and `phase2_plan.json` format
that Phase 3 expects. Populate fields:

```json
{
    "passage_id": "c10:p5",
    "expert": "Eleanor Hartley",
    "dimension": "rag_similarity",     // no real dimension — marker value
    "arc_name": null,                   // no arc knowledge
    "cost": 0,
    "chapter_id": "c10",
    "interest_score": <from original passage>,
    "characters_present": <from original passage>,
    "provisions": <from original passage>,
    "text": <raw text>,
    "summary": <from original passage>,
    "best_quote": <from original passage>,
    "themes": <from original passage>,
    "emotional_register": <from original passage>,
    "narrator": <from original passage>
}
```

The enrichment fields (provisions, themes, etc.) are passed through to Phase 3
because the script generator expects them — but they play **no role in selection**.

## Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Embedding model | text-embedding-3-small | Same as LanceDB table |
| passage_target | 32 | Same as other pipelines |
| Expert top-k | ceil(32/3) = 11 per expert | Equal allocation |
| Segment top-k | template.max_passages | Fill each segment |
| Dedup strategy | Highest similarity wins | Simple, no LLM needed |

## What This Tests

The plain RAG baseline isolates the contribution of:
1. **Enrichment metadata** (provisions, interest scores, themes) — transport uses these directly, embedding uses them via the enrichment fields in the curation prompt
2. **Structured obligations** (arc demands, expert demands, structure gaps) — both transport and embedding encode these as hard/soft constraints
3. **LLM reasoning about passage selection** — embedding pipeline uses Sonnet to curate

If plain RAG performs similarly to the other pipelines on downstream metrics (character density, vocabulary signature, quote recovery), then the enrichment and structured reasoning add little. If it performs worse, we can measure exactly what's lost.

## New Files

| File | Purpose |
|------|---------|
| `enrichment/plain_rag_podcast.py` | Core plain RAG assignment logic |
| `enrichment/plain_rag_run.py` | CLI runner (mirrors `embedding_run.py`) |
| `scripts/run_plain_rag_variants.sh` | Run all 20 panels |

## Implementation Notes

- Reuse `lancedb` connection and existing passage vectors — no new embedding needed for passages
- Need to embed ~3 expert profiles + ~6 segment descriptions per run (trivial cost)
- Use `openai.embeddings.create()` directly for the query embeddings
- The `--replace-expert` mechanism works the same way — swap persona, get different query embedding
- Run naming: `rag_v01_baseline`, `rag_v21_hartley_blackstone_edmund`, etc.
