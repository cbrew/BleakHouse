# Manipulability and Conversational Responsiveness

**Date:** 2026-03-11
**Git:** 4325ec4
**Data:** 7 conditions × 20 panels = 132 runs (ext has 17/20 at time of extreme analysis, 20/20 for responsiveness)

Two related questions explored here. First: does changing transport
parameters actually change what gets produced, and if so, how? Second:
the pipeline feeds all experts the same passages per segment — does this
produce genuine conversation, or parallel monologues?

## 1. Two Manipulability Experiments

### 1.1 High-Arc Demands: Additive, Not Transformative

The high-arc condition doubled all character arc demands (Richard 6→12,
Lady Dedlock 5→10, Jo 4→8) while holding everything else constant.

**What happened:** The solver assigned exactly 15 more passages per panel
(46.1 vs 31.1), matching the extra demand units (6+5+4 = 15). The
Jaccard overlap with baseline transport is 0.555 — more than half the
passages are identical. The solver keeps the original selection and bolts
on 15 more arc-relevant passages.

| Metric | Transport | High-Arc | Change |
|--------|----------|----------|--------|
| Passages/panel | 31.1 | 46.1 | +48% |
| Richard mentions/run | 31.6 | 41.0 | +30% |
| Jo mentions/run | 38.6 | 42.9 | +11% |
| Lady Dedlock mentions/run | 13.0 | 13.9 | +7% |
| Quote verification | 87.3% | 86.7% | ~same |

Chapter distribution shifts predictably toward arc-heavy chapters:

| Chapter | Transport | High-Arc | Content |
|---------|----------|----------|---------|
| c17 | 2.0/panel | 8.0/panel | Esther narrative, Richard |
| c18 | 0/panel | 3.2/panel | Lady Dedlock |
| c23 | 0/panel | 2.0/panel | Richard's deterioration |
| c11 | 4.4/panel | 7.1/panel | Jo ("Our Dear Brother") |

**Verdict:** Arc demand doubling is inspectable (you can trace exactly
which 15 passages were added and why) but not interestingly manipulable.
The output is quantitatively more arc-heavy but qualitatively the same
podcast. Uniform scaling of demands preserves relative profiles.

### 1.2 Peaked Expert Demands: Genuine Reshaping

The extreme condition peaked each expert's demand vector — amplifying
their defining dimension while zeroing or flattening secondaries:

| Expert | Transport profile | Peaked profile |
|--------|------------------|----------------|
| Hartley | narrative 2, character 2, thematic 1 | narrative **6**, character 1, thematic 0 |
| Blackstone | social 2, atmosphere 2, thematic 1 | social **6**, atmosphere 1, thematic 0 |
| Woodcourt | humor 2, character 1, atmosphere 1 | humor **6**, character 0, atmosphere 1 |
| Edmund | character 3, thematic 2, narrative 1 | character **7**, thematic 1, narrative 0 |
| Rosen | social 3, atmosphere 2, character 1 | social **8**, atmosphere 0, character 0 |
| Trevelyan | humor 3, atmosphere 2, narrative 2 | humor **8**, atmosphere 0, narrative 0 |

**What happened:** The solver assigned qualitatively different passages.
Jaccard overlap with transport is 0.490 — less than half the passages
are shared, lower than high-arc's 0.555.

The dimension profiles are strikingly concentrated:

| Expert | Transport top dimension | Extreme top dimension |
|--------|------------------------|----------------------|
| Rosen | 56% social_critique | **100% social_critique** |
| Trevelyan | 53% humor | **100% humor** |
| Woodcourt | 73% humor | **92% humor** |
| Blackstone | 42% social_critique | **86% social_critique** |
| Edmund | 54% character_dev | **87% character_dev** |
| Hartley | 42% character_dev | **77% narrative_technique** (flipped!) |

Hartley's profile actually changed its dominant dimension — from
character_development to narrative_technique — because the peaked
demand suppressed her character_development demand from 2 to 1 while
boosting narrative_technique from 2 to 6.

**Script output rebalanced:**

| Expert | Transport words/panel | Extreme words/panel | Change |
|--------|---------------------:|--------------------:|-------:|
| Edmund Leigh | 822 | 1,330 | **+62%** |
| Daniel Rosen | 879 | 1,249 | **+42%** |
| Oliver Trevelyan | 953 | 1,298 | **+36%** |
| Eleanor Hartley | 1,522 | 1,285 | −16% |
| James Blackstone | 1,535 | 1,274 | −17% |
| Caroline Woodcourt | 1,353 | 1,152 | −15% |

Transport's "big three" (Hartley, Blackstone, Woodcourt) dominated
airtime because they appear in more panels. Peaked demands redistribute
airtime toward the alternatives, making the panel more balanced.

**Verdict:** Changing the *shape* of demand vectors — not just their
magnitude — is the interesting manipulability knob. It forces the solver
to pick different passages entirely, which changes expert prominence,
thematic focus, and material coverage. This is the finding the paper
needs: peaked demands produce a qualitatively different podcast, not
just more of the same.

### 1.3 Contrast

| | High-Arc | Extreme |
|---|---------|---------|
| What changes | Arc demand magnitudes | Expert demand *shapes* |
| Passage overlap (Jaccard) | 0.555 | 0.490 |
| Effect on output | More arc-character mentions | Different expert prominence, different themes |
| Mechanism | Additive (bolt on 15 more passages) | Substitutive (swap which passages are chosen) |
| Quote verification | 86.7% | 87.0% |
| Manipulability story | Weak — quantitative only | **Strong — qualitative change** |


## 2. Conversational Responsiveness

The pipeline generates each segment's script in a single LLM call.
All experts see all passages assigned to the segment, each labelled
with its owning expert. This design choice ensures segment coherence
but raises the question: does it produce genuine conversation, or do
experts talk past each other?

Three measures, applied across all 7 conditions.

### 2.1 Cross-Passage Referencing

Each utterance has a `passage_ref` field linking it to the passage being
discussed. When an expert cites a passage assigned to another expert,
that's a cross-reference — the expert is engaging with someone else's
material, not just their own.

| Condition | Refs/run | Own | Cross | Cross-ref rate |
|-----------|---------|-----|-------|---------------|
| Embedding | 202.4 | 87.7 | 114.7 | **56.0%** |
| Extreme | 178.3 | 80.0 | 98.3 | **54.9%** |
| Transport | 142.1 | 65.6 | 76.5 | **53.8%** |
| High-Arc | 101.4 | 47.9 | 53.5 | **52.5%** |
| RAG | 367.1 | 188.9 | 178.2 | **48.4%** |
| Random | 314.4 | 172.4 | 141.9 | **44.8%** |
| No Passages | 0 | 0 | 0 | — |

Across passage-grounded conditions, experts reference other experts'
passages **45–56% of the time** they cite any passage. This is not
parallel monologue.

Per-expert breakdown (transport):

| Expert | Cross-refs | Total refs | Rate |
|--------|-----------|-----------|------|
| Caroline Woodcourt | 511 | 787 | **64.9%** |
| Edmund Leigh | 298 | 503 | **59.2%** |
| Oliver Trevelyan | 292 | 549 | **53.2%** |
| James Blackstone | 488 | 944 | **51.7%** |
| Daniel Rosen | 273 | 560 | **48.8%** |
| Eleanor Hartley | 432 | 919 | **47.0%** |

Woodcourt is the most conversationally engaged — nearly two-thirds of
her passage references are to material assigned to other experts. This
aligns with her being the most *responsive* expert in the variation
analysis (highest paired within-panel distance, lowest vocabulary
stability). Hartley and Blackstone, the more *rigid* experts, are also
the least likely to cross-reference — they stick to their own material.

### 2.2 Directionality: Responsive vs Proactive Cross-References

A cross-reference is *responsive* if the passage's owner already cited
it earlier in the segment — the expert is reacting to what was just
discussed. It's *proactive* if the expert references the passage before
its owner has introduced it.

| Condition | Responsive | Proactive | Responsive rate |
|-----------|-----------|----------|----------------|
| High-Arc | 852 | 218 | **79.6%** |
| Random | 2,125 | 714 | **74.9%** |
| Extreme | 1,435 | 531 | **73.0%** |
| RAG | 2,545 | 1,018 | **71.4%** |
| Embedding | 1,793 | 731 | **71.0%** |
| Transport | 1,599 | 695 | **69.7%** |

Across all conditions, **70–80% of cross-references are responsive.**
The dominant pattern is: Expert A introduces a passage, Expert B
picks it up and responds. This is genuine conversational turn-taking,
not coincidental overlap.

The high responsive rate is a consequence of the shared-context design:
because the LLM sees all passages and knows who owns each one, it
naturally structures the conversation as introduction → response.

### 2.3 Name-Checking: Direct Expert-to-Expert Address

How often does an expert mention another expert by first name in their
turn? ("As James was saying...", "I'd push back on what Eleanor
suggested...")

| Condition | Name-checks | Opportunities | Rate |
|-----------|------------|--------------|------|
| No Passages | 381 | 1,214 | **31.4%** |
| RAG | 332 | 1,147 | **28.9%** |
| High-Arc | 333 | 1,185 | **28.1%** |
| Random | 309 | 1,100 | **28.1%** |
| Extreme | 286 | 1,221 | **23.4%** |
| Embedding | 319 | 1,391 | **22.9%** |
| Transport | 347 | 1,738 | **20.0%** |

A counterintuitive inversion: **no-passages has the highest
name-checking rate**, while transport has the lowest. Without passages
to ground the discussion, experts compensate by addressing each other
more directly — reacting to opinions rather than material. With good
passage grounding, experts let the text do the conversational work:
they respond to the *passages* rather than to each other by name.

This is not a deficiency of the passage-grounded conditions. Rather,
it reflects two different conversational modes:
- **Passage-grounded:** "Let me read this passage... [reads]. Notice
  how Dickens..." (passage carries the conversation)
- **Ungrounded:** "As James was saying, I think the fog represents..."
  (expert-to-expert address substitutes for textual evidence)

### 2.4 Lexical Overlap Between Consecutive Turns

Mean Jaccard similarity of content words (4+ characters) between
consecutive non-Host turns by different speakers:

| Condition | Mean Jaccard | n pairs |
|-----------|-------------|---------|
| High-Arc | 0.079 | 937 |
| No Passages | 0.077 | 1,015 |
| RAG | 0.076 | 944 |
| Extreme | 0.076 | 981 |
| Random | 0.076 | 888 |
| Embedding | 0.075 | 1,089 |
| Transport | 0.075 | 1,367 |

Essentially flat across conditions (~0.075-0.079). This is expected:
lexical overlap is a blunt instrument. Experts can respond to each
other's ideas using entirely different vocabulary — "I agree about the
institutional critique" doesn't share many words with the passage about
Chancery that prompted it. The cross-passage reference rate (§2.1) and
directionality (§2.2) are more revealing measures of responsiveness.


## 3. Synthesis

### The Manipulability Finding

Uniform scaling of demands (high-arc) produces additive effects — more
of the same passages bolted on. Changing the *shape* of demand vectors
(peaked/extreme) produces substitutive effects — genuinely different
passages selected, different expert prominence, different thematic
coverage. The interesting manipulability knob is the demand profile
shape, not the magnitude.

Both conditions maintain quote verification rates at ~87%, comparable to
baseline transport (87.3%). Changing what the solver selects doesn't
degrade the quality of passage use in the generated scripts.

### The Conversational Responsiveness Finding

The shared-context architecture (all experts see all passages per
segment) produces genuine conversation:

1. **54% cross-referencing** — experts discuss each other's passages as
   much as their own
2. **70% responsive directionality** — cross-references predominantly
   follow the owner's introduction, creating natural turn-taking
3. **Inverse name-checking** — passage-grounded conditions rely on
   passages for conversational structure; ungrounded conditions
   substitute expert-to-expert address

The responsive cross-referencing rate correlates with the expert
variation analysis: Woodcourt (most responsive expert, highest paired
distance) has the highest cross-reference rate (64.9%), while Hartley
(more rigid) has the lowest (47.0%). Experts who change their output
most in response to different passages are also the ones who engage
most with other experts' material.

### Together

These two findings reinforce each other. The manipulability claim
requires that changing transport parameters changes the *conversation*,
not just the passage selection. The responsiveness analysis shows that
experts genuinely engage with each other's passages — so when the solver
assigns different passages (as in the extreme condition), the resulting
conversation is structurally different, not just cosmetically relabelled.
Passage selection flows through cross-referencing into the conversation's
actual content.
