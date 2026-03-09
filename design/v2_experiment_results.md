# V2 Experiment Results — Phase 0 Architecture

## Architecture

Phase 0 (LLM segment design, Haiku) → Phase 1 (passage selection, min-cost flow) →
Phase 2 (segment assignment, min-cost flow) → Phase 3 (script generation, Sonnet) →
Phase 4 (audio rendering, Gemini TTS).

Phase 0 designs episode segments tailored to the expert panel before passage selection.
Supplementary demand feeds back into Phase 1 to ensure segments can be filled.

Expert names: Eleanor Hartley (literary critic), James Blackstone (social historian),
Caroline Woodcourt (close reader).  Alternatives: Edmund Leigh (traditionalist),
Daniel Rosen (Marxist), Oliver Trevelyan (performer/wit).

Previous runs archived in `data/runs_archived_v1/`.

---

## 20 Variants

### Round 1: Parameter Tuning (V01–V10)

| ID | Name | Change | Segs | Pass | NULL | Chapters |
|----|------|--------|------|------|------|----------|
| V01 | baseline | defaults | 7 | 31 | 0 | 14 |
| V02 | more_jo | Jo arc 4→8 | 7 | 27 | 0 | 15 |
| V03 | strict | cluster_lambda 5→20 | 6 | 24 | 0 | 14 |
| V04 | craft_focus | per_expert_min 8→12 | 6 | 24 | 0 | 15 |
| V05 | craft_v2 | Hartley narrative=4, thematic=3 | 6 | 25 | 0 | 19 |
| V06 | quality | weak_cost 3→15 | 6 | 27 | 0 | 17 |
| V07 | skip_dedlock | Dedlock arc=0 | 6 | 24 | 0 | 14 |
| V08 | tight_budget | total_budget 60→25 | 7 | 29 | 0 | 15 |
| V09 | diverse | cluster_lambda 5→30 | 6 | 27 | 0 | 15 |
| V10 | conservative | Blackstone→Edmund Leigh | 6 | 27 | 0 | 15 |

### Round 2: Expert Swaps (V11–V14)

| ID | Name | Change | Segs | Pass | NULL | Chapters |
|----|------|--------|------|------|------|----------|
| V11 | marxist | Hartley→Rosen | 7 | 29 | 0 | 18 |
| V12 | radical_panel | Blackstone→Edmund + Hartley→Rosen | 6 | 27 | 0 | 17 |
| V13 | rosen_jo | Hartley→Rosen + Jo=8 | 7 | 30 | 0 | 18 |
| V14 | trevelyan_for_woodcourt | Woodcourt→Trevelyan | 7 | 29 | 1 | 13 |

### Round 3: Trevelyan Integration (V15–V20)

| ID | Name | Change | Segs | Pass | NULL | Chapters |
|----|------|--------|------|------|------|----------|
| V15 | trevelyan_for_hartley | Hartley→Trevelyan | 7 | 31 | 0 | 17 |
| V16 | trevelyan_for_blackstone | Blackstone→Trevelyan | 7 | 29 | 0 | 15 |
| V17 | trevelyan_edmund | Blackstone→Edmund + Woodcourt→Trevelyan | 6 | 25 | 0 | 17 |
| V18 | trevelyan_rosen | Hartley→Trevelyan + Blackstone→Rosen | 6 | 29 | 0 | 16 |
| V19 | all_swapped | Hartley→Trevelyan + Blackstone→Edmund + Woodcourt→Rosen | 6 | 25 | 0 | 13 |
| V20 | trevelyan_jo | Woodcourt→Trevelyan + Jo=8 | 7 | 30 | 0 | 13 |

---

## Segment Design Variation

Segment titles are LLM-designed (Haiku) and adapt to the panel.  All 20 variants have unique segment structures.

### Opening segments

| Variant | Opening Title |
|---------|---------------|
| V01 | Fog and the Law: Entering Bleak House |
| V02 | The Fog Descends: Welcome to Bleak House |
| V05 | Into the Fog: Chancery's Web |
| V09 | The Machinery of Misery: Opening the Case |
| V11 | Fog and Chancery: The World of Bleak House |
| V12 | The Court of Chancery Wakes: System and Soul in Bleak House |
| V13 | Fog, Law, and the Machinery of Misery |
| V16 | The Fog That Conceals All |
| V18 | The Fog and the Labyrinth: Opening the Case |
| V19 | The Fog Descends: Welcome to Bleak House |

### Closing segments

| Variant | Closing Title |
|---------|---------------|
| V01 | The Cost of Complexity: What Bleak House Demands of Its Reader |
| V10 | The Persistence of Mystery: Dickens's Final Word |
| V12 | Fog Lifting: Systems, Secrets, and Sympathy |
| V13 | The System Persists: What Bleak House Leaves Unresolved |
| V17 | The Question of Blame and Compassion |
| V19 | Into the Light: Dickens' Vision of Redemption and Reckoning |
| V20 | The House Remains: What Dickens Leaves Us |

### Expert influence on segment character

- **Rosen present** → titles use "Machinery", "Parasitic System", "System Persists"
- **Edmund present** → titles use "Mystery", "Blame and Compassion", "Soul"
- **Trevelyan present** → titles use "Laughter", "Comedy", "Wit and Darkness"
- **Jo arc boosted** → Jo segment promoted to slot 2 with intimate titles ("The Boy Nobody Knows")
- **Dedlock arc zeroed** → Dedlock segment disappears, replaced by craft-focused segment

---

## Passage Overlap Analysis

**88 unique passages** drawn across 20 variants.  Average 31.3 per variant.

### Frequency distribution

| Appears in | Count | Description |
|------------|-------|-------------|
| All 20 | 10 | Core canon (c11, c13, c17 — Richard/plot) |
| 15–19 | 8 | Near-universal |
| 10–14 | 10 | Common but panel-sensitive |
| 5–9 | 14 | Moderately selective |
| 2–4 | 17 | Rare, expert-driven |
| Only 1 | 29 | Unique to one variant |

### Core passages (in all 20 variants)

- c17:p19, c13:p99, c13:p115, c11:p100, c13:p124, c11:p78, c13:p113, c13:p118, c11:p74, c11:p87

### Pairwise similarity

- **Mean Jaccard:** 0.521 (variants share ~half their passages)
- **Most different:** V07 (skip_dedlock) vs V10 (conservative) — J=0.239
- **Most similar:** V02 (more_jo) vs V04 (craft_focus) — J=0.882

### Chapter coverage

Ranges from 13 to 19 chapters.  V05 (craft_v2, boosted Hartley demands) reaches the widest spread (19 chapters).  Compact variants (V19, V20) focus on 13 chapters.

---

## Key Findings

1. **NULL=0 in 19/20 variants.**  The Phase 0 architecture with supplementary demand reliably fills all segments.

2. **Segment design genuinely adapts** to expert composition.  Titles, ordering, and thematic focus change meaningfully.

3. **1/3 of passages are variant-specific** (29/88 appear in only one variant).  Expert demands shape the material, not just the framing.

4. **Parameter tuning has limited effect** compared to expert swaps.  V03 (strict) and V04 (craft_focus) barely differ from baseline in passage selection.  Expert replacement creates far more variation.

5. **Expert demand profiles matter more than arc overrides** for passage diversity.  Jo=8 changes passage count but not chapter coverage.  Swapping Blackstone for Rosen changes both.

---

## Selected for Phase 3 (Script Generation)

| ID | Name | Rationale |
|----|------|-----------|
| V01 | baseline | Reference point |
| V02 | more_jo | Jo-focused variant, most popular arc override |
| V05 | craft_v2 | Widest chapter coverage (19), boosted craft demands |
| V10 | conservative | Edmund replaces Blackstone — traditionalist perspective |
| V12 | radical_panel | Edmund + Rosen — maximum ideological contrast |
| V14 | trevelyan_for_woodcourt | Trevelyan replaces Woodcourt — performer perspective |
| V18 | trevelyan_rosen | Trevelyan + Rosen — entertainment meets politics |
| V19 | all_swapped | All three experts replaced — most different panel |
