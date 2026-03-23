# VISTA-Based Podcast Script Evaluation

## What VISTA Does

VISTA (Verification in Sequential Turn-based Assessment) is a 4-stage pipeline
for evaluating factual accuracy in conversational text:

1. **Claim Extraction** — Break each expert turn into atomic factual claims
2. **Verification** — Check each claim against reference text (VERIFIED / UNVERIFIABLE)
3. **Categorization** — Sort unverifiable claims into:
   - CONTRADICTED: claim opposes reference text
   - OUT-OF-SCOPE: opinion, recommendation, conversational remark
   - LACKING EVIDENCE: factual assertion but no supporting evidence
   - ABSTENTION: refusal or expression of uncertainty
4. **Contradiction Detection** — Find intra-conversation contradictions (optional)

Key property: it accumulates verified facts as the conversation progresses,
so later claims can be checked against both reference text AND earlier verified claims.

## Why This Matters for BleakHouse

Our podcast scripts have experts making claims about Dickens' novels. We already
verify quotes (fuzzy 5-word subsequence), but we don't verify:

- Whether expert claims about plot, character, or theme are accurate
- Whether experts contradict each other or themselves across turns
- Whether the LLM fabricated literary-critical assertions

VISTA gives us a principled way to measure **factual grounding** and
**intra-conversation consistency** — both key quality dimensions the paper claims
but doesn't yet measure.

## Adaptation Design

### Input Mapping

VISTA expects conversations with roles. Our podcast scripts map naturally:

| VISTA concept | BleakHouse equivalent |
|---|---|
| AGENT_ROLE | Expert speakers (Hartley, Blackstone, etc.) |
| USER_ROLE | Host (Sarah Chen) — not checked by VISTA |
| retrieved_document | Source passage text from phase1_assignments.json |
| background_knowledge | Novel metadata: chapter summaries, character list, enrichment |

Only expert turns are checked — host turns are excluded, matching VISTA's design
where only AGENT_ROLE is evaluated.

### Reference Text Construction

For each segment, the reference text is the union of:
1. **Passage text** — the actual Dickens passages assigned to that segment
2. **Enrichment metadata** — summary, themes, characters_present, best_quote
3. **Chapter context** — which chapter each passage comes from

This is richer than typical VISTA usage (which has a single retrieved document)
but aligns with our pipeline's structure.

### Stage Adaptations

**Stage 1 (Claim Extraction)**: Use as-is. Expert turns contain literary-critical
claims that decompose naturally into atomic statements. The pronoun resolution
and presupposition extraction are directly useful (e.g., "Unlike Trollope,
Dickens uses fog as..." yields a claim about Trollope too).

**Stage 2 (Verification)**: Modify reference text to include passage text +
enrichment. Claims about what happens in the novel can be verified against passage
text. Claims about literary interpretation are harder — many will correctly be
UNVERIFIABLE since interpretation isn't in the source text.

**Stage 3 (Categorization)**: Replace VISTA's categories with our own:
- PASSAGE_GROUNDED: claim is directly supported by the assigned passage text
- NOVEL_GROUNDED: claim is true about the novel but not in the assigned passages
- INTERPRETATION: literary opinion, comparative judgment, analytical claim
- FABRICATED: factual claim about plot/character/event that is wrong
- SELF_CONTRADICTION: contradicts something said earlier in the episode

VISTA's CONTRADICTED/OUT-OF-SCOPE/LACKING-EVIDENCE/ABSTENTION categories are
designed for customer-service chatbots. Ours reflect what matters in literary
podcast evaluation: we want interpretation (good), we tolerate novel-grounded
claims (acceptable), and we penalize fabrication (bad).

**Stage 4 (Contradiction Detection)**: Enable this. Cross-turn consistency is
important — if Hartley says Richard is naive in segment 2 and calculating in
segment 5, that's a quality problem. Our multi-segment structure makes this
especially valuable.

### Scoring

We define scores based on our categories:

```
passage_grounding  = PASSAGE_GROUNDED / factual_claims
novel_grounding    = (PASSAGE_GROUNDED + NOVEL_GROUNDED) / factual_claims
fabrication_rate   = FABRICATED / factual_claims
interpretation_pct = INTERPRETATION / total_claims
consistency        = 1 - (SELF_CONTRADICTION / total_claims)
```

where factual_claims = PASSAGE_GROUNDED + NOVEL_GROUNDED + FABRICATED
(interpretations excluded from grounding calculation since they are desirable).

### Per-Condition Comparison

The key analysis: do transport-selected passages produce more verifiable claims
than embedding or no-passages? We expect:
- Transport/embedding: high grounding (passages provide verification material)
- No-passages: lower grounding (experts confabulate without source text)
- Peaked/high-arc: similar grounding to baseline (different passages, same quality)

## Implementation Plan

### File Structure

```
enrichment/vista_eval/
├── PLAN.md              (this file)
├── __init__.py
├── convert.py           (episode JSON → VISTA input format)
├── reference.py         (build reference text from passages + enrichment)
├── run_vista.py         (orchestrate 4-stage pipeline)
├── prompts.py           (adapted prompt templates)
├── score.py             (compute grounding/hallucination/consistency scores)
└── report.py            (aggregate scores across runs, produce tables)
```

### Phase 1: Converter (convert.py)

Read `phase3_episode.json` + `phase1_assignments.json`, produce VISTA-format
JSON with:
- Turns mapped to USER_ROLE (host) and AGENT_ROLE (experts)
- Each expert turn paired with its segment's assigned passages as retrieved_document
- Background knowledge populated from enrichment metadata

### Phase 2: Reference Builder (reference.py)

For each segment, construct reference text from:
- Passage text (verbatim Dickens)
- Enrichment fields: summary, themes, characters_present, best_quote
- Chapter ID for context

### Phase 3: Pipeline Runner (run_vista.py)

Run the 4-stage VISTA pipeline using Anthropic API (Haiku for stages 1-3,
Sonnet for stage 4 contradiction detection). We don't need VISTA's model
infrastructure — we reimplement the prompts against our existing API client.

Invocation: `uv run python -m enrichment.vista_eval.run_vista [--runs arc_v01_baseline]`

### Phase 4: Scoring (score.py)

Compute per-episode and per-condition aggregates:
- vista_grounding, vista_hallucination, vista_consistency
- Breakdown by expert (do some experts hallucinate more?)
- Breakdown by condition (transport vs embedding vs no-passages)

### Phase 5: Integration (report.py)

Add VISTA metrics to compute_metrics.py output and paper tables.

## Cost Estimate

Per episode (~80-100 expert turns, ~8 segments):
- Stage 1: ~100 Haiku calls (claim extraction) ≈ $0.02
- Stage 2: ~300 Haiku calls (3 claims/turn avg × verification) ≈ $0.06
- Stage 3: ~100 Haiku calls (unverifiable subset) ≈ $0.02
- Stage 4: ~8 Haiku calls (per segment) ≈ $0.01

Per episode total: ~$0.11
For 400 episodes: ~$44

## Model Choice

Use Haiku for all stages. VISTA's claim extraction and verification are
classification tasks — Haiku is sufficient and 10x cheaper than Sonnet.
Stage 4 (contradiction) could use Sonnet for better reasoning, but start
with Haiku and upgrade if needed.

## Dependencies

No new dependencies. We reimplement VISTA's prompts against our existing
Anthropic client (already in the project). No torch/transformers needed.
