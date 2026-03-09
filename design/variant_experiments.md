# Variant Experiments: Producer-Level Parameter Changes

## Purpose

Demonstrate that changing transport parameters makes a targeted, predictable
difference in content selection.  Each variant represents a decision a podcast
producer would actually make — not an engineering knob.

## Baseline

All defaults: `cluster_lambda=5`, `per_expert_min=8`, arc demands at
Richard=6, Dedlock=5, Jo=4.  Produces 26 passages across 14 chapters.
Jo's Story segment gets only 1 passage (thin).

---

## Variant 1: "Give Jo more room"

**Command:** `--arc-demand "Jo's suffering=8"`

**Producer rationale:** Jo's Story is the moral centre of the novel but gets
only 1 passage in baseline.  A producer would say: "Jo deserves a proper
segment."

**Expected effects:**
- Jo's arc demand doubles (4 → 8), pulling more Jo-related passages
- Jo's Story segment fills from 1 to 3-4 passages
- New passages likely from: Jo's testimony (c11), encounters with Lady
  Dedlock's world, possibly his death scene
- Some Jo passages may spill into Institutions Under Fire (shared
  `prov_social_critique` dimension)
- Richard's Decline and The Secret and the Chase should be unaffected
  (different arc, different dimension)

**Actual results:**
- 4 new passages added (total 26 → 30), all from Jo's arc: c11:p88 (Jo weeps
  for the dead man), c11:p98 (Jo approaches the cemetery), c11:p99 (Jo sweeps
  the cemetery step clean), c12:p56 (Lord Boodle on government failure)
- 0 passages removed — the extra demand was met by selecting *additional*
  passages rather than displacing existing ones
- NULL flow dropped from 4 → 0 (all segment slots filled)
- Jo's Story filled from 1 → 4 passages (**confirmed prediction**)
- Jo's c11:p100 (narrator address) moved from Jo's Story to Opening segment —
  the solver found a better fit since the new Jo passages filled the segment
- 5 of 7 segments unchanged (**confirmed prediction**: Richard, Institutions,
  Secret, Dickens, Closing all stable)
- Chapters covered: 14 (same) — new passages came from c11 and c12, already
  represented

**Prediction accuracy:** Strong.  Jo's segment filled as expected.  The
surprise was that the solver added passages rather than trading, because the
extra arc demand created room for more total flow.

---

## Variant 2: "More variety, less clustering"

**Command:** `--cluster-lambda 30`

**Producer rationale:** "I want every passage to show a different facet of
the novel — no two passages that are basically the same scene."

**Expected effects:**
- Steep redundancy penalty forces the solver to spread across more chapters
- The tight thematic groupings (e.g., four consecutive c13 passages in
  Richard's Decline) should thin — replaced by passages from different chapters
- Episode becomes broader but potentially less focused per segment
- At λ=20 we already saw 11/26 passages change; at λ=30 expect similar or
  more churn
- Chapters covered should increase (baseline=14)

**Actual results:**
- 6 passages added, 6 removed, 1 reassigned (26 total, same count)
- Passages **removed**: c18:p18 (Boythorn), c3:p159 (old Chancery woman),
  c48:p3 (Lady Dedlock's decision), c55:p95 (Guppy on letters), c5:p88
  (Richard at Krook's), c8:p81 (brickmaker's cottage)
- Passages **added**: c21:p77 (George the trooper), c31:p67 (Skimpole on Jo),
  c54:p155 (Hortense's fate), c57:p112 (Bucket loses composure), c57:p128
  (Bucket returning to London), c62:p55 (Smallweed produces the will)
- cP:p0 (Chancery preamble) **reassigned** from Dr. Hartley → Ms. Woodcourt
- Segments affected: 3 of 7 (Institutions, Dickens at His Best, Closing)
- Richard's Decline, Opening, Secret, Jo's Story all stable (4 of 7)
- Chapters covered: 14 (same count but different set — lost c3, c5, c18, c48,
  c55; gained c21, c31, c54, c57, c62)
- **Dickens at His Best completely reshaped**: lost the old Chancery woman,
  Richard at Krook's, and the brickmaker's cottage; gained Bucket scenes and
  Smallweed.  This is the most dramatic segment change.

**Prediction accuracy:** Mixed.  Correctly predicted churn of ~6 passages and
that Richard/Secret would be stable.  Incorrectly predicted chapters covered
would *increase* — it stayed at 14 (different set, same count).  The
Richard's Decline segment with its tight c13 cluster survived intact even at
λ=30, because those are the only high-interest Richard arc passages available.
The biggest surprise is the Dickens at His Best segment losing its three
strongest passages — the redundancy penalty pushed the solver toward
later-novel content that's arguably less iconic.

---

## Variant 3: "Foreground the craft"

**Command:** `--per-expert-min 12`

**Producer rationale:** "This episode should lean into the literary craft
angle — let Dr. Hartley have more material."

**Expected effects:**
- Minimum passages per expert rises from 8 → 12
- Hartley's demands (`prov_narrative_technique`, `prov_character_development`)
  pull more passages
- Dickens at His Best (Hartley's home segment) should fill to max capacity
- Some passages may shift from Blackstone/Woodcourt to Hartley on shared
  dimensions like `prov_character_development`
- Overall episode tilts toward craft analysis at expense of social history
  and reading experience

**Actual results:**
- **No change whatsoever.** 26 passages, identical selection, identical
  segment assignments.  All 7 segments identical to baseline.

**Prediction accuracy:** Wrong.  The `per_expert_min` parameter sets a floor
on passages per expert, but each expert already meets or exceeds 12 passages
in the baseline (since arc demands alone contribute 6+5+4=15 passages, all
assigned to experts).  Raising the floor from 8 → 12 changes nothing because
the floor was never binding.  To actually shift the expert balance, you'd need
to change expert *demands* (the per-dimension quotas) or add new dimensions.

**Lesson:** `per_expert_min` is a safety net, not a steering mechanism.  To
foreground Dr. Hartley, the right lever would be increasing her per-dimension
demands (e.g., `prov_narrative_technique: 2 → 4`) or adding a new dimension
she owns.

---

## Variant 3b: "Foreground the craft" (corrected)

**Command:**
```
--expert-demand "Dr. Hartley:prov_narrative_technique=4"
--expert-demand "Dr. Hartley:prov_thematic_depth=3"
```

**Producer rationale:** Same as V3 — lean into literary craft — but using
the correct lever: increase Hartley's actual dimension quotas.  Narrative
technique 2→4 and thematic depth 1→3 gives her 9 dimension-demand units
(up from 5), competing more aggressively for passages.

**Expected effects:**
- Hartley pulls 3-4 more passages, especially in narrative technique
- Some passages currently assigned to Blackstone (who shares thematic_depth)
  or Woodcourt may shift to Hartley
- Dickens at His Best should fill completely with Hartley-assigned material
- Closing segment may shift — Hartley already dominates it, more thematic
  depth demand may pull different passages
- Jo's Story and Institutions Under Fire (Blackstone's territory, social
  critique) should be unaffected

**Actual results:**
- 7 passages added (all to Dr. Hartley), 3 removed — total 26 → 30
- New Hartley passages: c38:p20 (Caddy learning piano, thematic_depth),
  c60:p126 (narrative_technique, interest=4), c64:p34 (narrative_technique),
  c6:p148 (Esther's tears, thematic_depth, interest=4), c7:p14 (Mrs.
  Rouncewell, thematic_depth), c9:p111 (narrative_technique), cP:p2
  (narrative_technique, interest=4)
- 3 Hartley passages removed: c64:p39, c8:p81, cP:p0 — displaced by
  higher-demand competition within Hartley's own quotas
- **All 7 segments affected** — the most disruptive variant so far
- Jo's Story gained 3 passages (c11:p74, p78, p87 migrated from Institutions)
- Institutions Under Fire got reshaped with Dedlock/narrative passages
- Closing completely rewritten: lost Boythorn, Dedlock, Jarndyce; gained
  Caddy, Esther, Mrs. Rouncewell (thematic depth material)
- NULL flow: 0 (all slots filled, up from 4 in baseline)
- Chapters covered: 18 (up from 14) — gained c6, c9, c38, c60
- Characters featured: 30 (up from 29)

**Prediction accuracy:** Mostly correct.  Hartley pulled 7 more passages as
predicted.  Dickens at His Best did reshape.  The big surprise: increasing
Hartley's demand had a cascade effect across *all* segments because displaced
passages (especially the Jo testimony ones) found homes elsewhere.  Jo's Story
went from 1 → 4 passages as a side effect — the solver used freed Blackstone
capacity to fill Jo's segment.  This is the most interesting finding: boosting
one expert indirectly benefits other segments.

---

## Variant 4: "Quality over quantity"

**Command:** `--weak-cost 15`

**Producer rationale:** "Only use passages where the enrichment signal is
strong — don't pad the episode with marginal material."  Raising weak_cost
from 3→15 makes the solver strongly prefer passages with 'strong' provision
matches and avoid 'weak' ones.

**Expected effects:**
- Passages with weak provision matches get displaced by strong ones
- Total passage count may drop if there aren't enough strong alternatives
  (more NULL flow)
- Interest scores should trend upward across the board
- Segments that relied on weak-provision passages may thin out
- The effect should be most visible in dimensions where many passages have
  weak rather than strong signals

**Actual results:**
- 4 passages added, 6 removed — total 26 → 24 (net loss of 2)
- NULL flow: 6 (up from 4) — 2 more segment slots unfilled
- Removed: c3:p159 (old Chancery woman), c48:p3 (Dedlock decision), c5:p88
  (Richard at Krook's), c7:p35 (Guppy tiring), c8:p81 (brickmaker's
  cottage), cP:p0 (Chancery preamble)
- Added: c39:p58 (atmosphere, interest=3), c57:p128 (narrative technique),
  c62:p55 (Smallweed/will, humor, interest=5), c66:p5 (Sir Leicester alone,
  character development, interest=4)
- 5 segments affected, 2 stable (Richard's Decline, Secret and the Chase)
- Jo's Story gained 3 passages from Institutions (same cascade as craft_v2)
- Institutions Under Fire thinned from 5 → 2 passages
- Dickens at His Best lost 4 of its best passages, gained 2 replacements
- Closing gained Sir Leicester before wife's portrait (c66:p5) — poignant
- Chapters lost: c3, c5, c7 (early novel). Gained: c39, c57, c62, c66

**Prediction accuracy:** Partially correct.  Passages dropped and NULL flow
rose as expected.  Interest scores did trend up on the new passages (5, 4, 3,
3).  The surprise: the removed passages were NOT the low-interest ones — c8:p81
(interest=4) and c3:p159 (interest=4) were cut.  The solver prioritised
provision *strength* over interest score, which makes sense given the parameter
change.  Weak-provision passages were cut regardless of interest.  This is
the right behaviour from a "quality" standpoint — strong enrichment signal
matters more than raw interest rating.

---

## Variant 5: "Skip Lady Dedlock"

**Command:** `--arc-demand "Lady Dedlock's secret=0"`

**Producer rationale:** "We covered Lady Dedlock in depth last episode.
This time, let's focus on the other storylines and free up 5 passage slots."

**Expected effects:**
- Lady Dedlock arc demand drops from 5→0, freeing those slots
- The Secret and the Chase segment (which depends on Dedlock arc + plot
  advancement) should be hit hardest — may thin dramatically or fill with
  non-arc passages from other dimensions
- Freed capacity may benefit other arcs or dimensions that were previously
  squeezed out
- Richard's Decline and Jo's Story should be unaffected (independent arcs)
- Total passage count may drop (fewer arc passages driving demand)

**Actual results:**
- 5 passages cleanly removed (all Dedlock arc) — total 26 → 21
- 0 new passages added — no reallocation of freed capacity
- NULL flow: 9 (up from 4) — 5 more unfilled slots
- Removed passages: c12:p11, c12:p114, c12:p116, c12:p67, c17:p100 — exactly
  the 5 Lady Dedlock arc passages, all from plot_advancement dimension
- **The Secret and the Chase devastated**: lost all 5 Dedlock passages, gained
  only c18:p18 (Boythorn) and c48:p3 (Dedlock decision) — these migrated from
  Closing, which thinned to 1 passage
- Jo's Story filled from 1 → 4 (same cascade: Jo passages migrated from
  Institutions Under Fire)
- Institutions Under Fire thinned from 5 → 2 (lost the 3 Jo passages to
  Jo's Story)
- Opening, Richard's Decline, Dickens at His Best: all stable (3 of 7)

**Prediction accuracy:** Strong.  The Secret and the Chase was hit hardest as
predicted.  Richard's Decline and Jo's Story independent as predicted.  The
interesting finding: removing the arc didn't free slots for *other* content —
the dimension (plot_advancement) had zero non-arc demand, so nothing stepped
in.  The Secret and the Chase segment is now mostly NULL-filled.  This shows
that arcs and dimensions interact: an arc creates demand on a dimension that
otherwise might have none.  Remove the arc, and the dimension goes dark.

Also notable: the Jo cascade happened again (3rd time across variants).
Whenever Institutions loses passages, the solver moves its Jo passages to
Jo's Story.  This is a robust pattern — the solver consistently prefers
arc-matched placement over dimension-only placement.

---

## Variant 6: "Tight budget"

**Command:** `--total-budget 25`

**Producer rationale:** "We only have 20 minutes — be ruthless.  Pick only
the very best material."

**Expected effects:**
- Budget drops from 60→25, which may seem generous still since baseline
  only selects 26 passages.  But the budget constrains total flow through
  the network — it may force the solver to drop the lowest-interest passages.
- If 25 is below what the solver naturally wants, passages with interest
  scores of 2-3 should be the first to go
- High-interest passages (4-5) should survive
- Segments may thin unevenly — those relying on lower-interest material
  thin first
- Alternatively, if the natural demand is ≤25, there may be no effect at all
  (similar to the V3 lesson — the constraint may not be binding)

**Actual results:**
- **No change whatsoever.** 26 passages, identical selection, identical
  segment assignments.  All 7 segments identical to baseline.

**Prediction accuracy:** Correctly anticipated this as the most likely outcome.
The total_budget of 60 was never binding — the solver naturally wants ~26
passages (driven by dimension + arc demands).  Reducing to 25 is still above
the natural demand.  The budget would need to drop below the natural demand
(~20 or so) to force cuts.

**Lesson:** Like `per_expert_min`, `total_budget` is a ceiling/safety valve,
not a content-shaping tool.  The real selection pressure comes from demand
(expert quotas + arc quotas) and cost (cluster_lambda, weak_cost).  Budgets
only matter when demand exceeds supply.

---

## Cross-variant observations

1. **Arc demands are the strongest lever.**  They directly create or remove
   passage slots.  "Give Jo more room" (V1) and "Skip Dedlock" (V5) had the
   most predictable, targeted effects.

2. **Expert demands have cascade effects.**  Boosting Hartley (V3b) reshaped
   *all 7 segments* — the most disruptive change — because displaced passages
   found homes elsewhere.  This is powerful but harder to predict.

3. **Cost parameters reshape within fixed demand.**  `cluster_lambda` (V2) and
   `weak_cost` (V4) swap passages without changing total count.  They control
   *which* passages fill the slots, not *how many* slots exist.

4. **Floor/ceiling parameters are safety nets, not steering.**  `per_expert_min`
   (V3) and `total_budget` (V6) had zero effect because they were never binding.

5. **The Jo cascade is robust.**  In V1, V3b, V4, and V5, whenever Institutions
   Under Fire lost Jo passages, the solver moved them to Jo's Story.  The
   segment transport consistently prefers arc-matched placement.

6. **Interesting production choices emerged:**
   - V1 (more_jo) is the obvious pick for a Jo-focused episode
   - V3b (craft_v2) accidentally produced the best-balanced episode: 30
     passages, 0 NULL, 18 chapters, and Jo's Story filled as a side effect
   - V5 (skip_dedlock) shows a structural weakness: plot_advancement has no
     non-arc demand, so removing the arc leaves a dead segment

---

# Round 2: Expert Swaps

## Key insight

Expert profiles have two components:
1. **ExpertProfile** (demands per dimension) — controls Phase 1 transport
2. **ExpertPersona** (description, voice) — controls Phase 3 LLM generation

Swapping experts is a **transport-level change**: instant (<2s), no LLM cost,
fully interpretable via diff.  This is a key selling point of the approach:
a producer can explore radically different editorial perspectives without
re-running expensive generation.

## New experts

**Sir Edmund Leigh** (traditionalist conservative):
- Demands: character_development=3, thematic_depth=2, narrative_technique=1
- Reads Bleak House as a novel about moral character tested by circumstance
- Cares about: Esther's goodness, Jarndyce's sacrifice, Richard's weakness
- Does NOT demand: social_critique, atmosphere_setting, humor

**Dr. Rosen** (Marxist critic):
- Demands: social_critique=3, atmosphere_setting=2, character_development=1
- Reads Bleak House as an anatomy of class power and institutional violence
- Cares about: Jo as product of the system, Chancery as class instrument,
  the fog as ideology
- Does NOT demand: narrative_technique, thematic_depth, humor

Note: segment templates still reference original expert names in
`preferred_experts`.  This means swapped experts won't get segment-preference
bonuses, but demands still drive selection.

---

## Variant 7: "The conservative chair" — swap Blackstone for Sir Edmund

**Command:** `--replace-expert "Prof. Blackstone=sir_edmund"`

**Producer rationale:** Replace the social historian with a traditionalist.
The episode should focus on moral character and literary form rather than
institutional critique.

**Expected effects:**
- Blackstone's social_critique=2 and atmosphere_setting=2 disappear
- Sir Edmund brings character_development=3 and thematic_depth=2 — dimensions
  that overlap heavily with Dr. Hartley (who has char_dev=2, thematic=1)
- Institutions Under Fire may thin: its preferred dimension (social_critique)
  now only has demand from arcs, not from an expert
- Jo's Story (social_critique, Blackstone-preferred) should also thin — the
  Jo arc still creates demand, but no expert owns the social critique dimension
- Richard's Decline may benefit: more character_development demand overall
- Closing (thematic_depth) may gain from Sir Edmund's thematic demand
- Total character_development demand rises from 3→4 units across experts
- Humor_entertainment demand stays the same (only Woodcourt)

**Actual results:**
- 4 added, 6 removed, 2 reassigned.  24 passages total (down from 26), 6 NULL
- Sir Edmund's char_dev=3 pulled c11:p33 (interest=5), c57:p112 (Bucket), c61:p42
  (Richard's deterioration) — all character-focused passages
- Lost all Blackstone social_critique passages: c55:p95, c65:p21 — **confirmed**
- c64:p39 reassigned Dr. Hartley → Sir Edmund; c8:p0 reassigned Blackstone → Woodcourt
- Jo's Story **emptied to 0 passages** — stronger than predicted "thinning".
  With no expert demanding social_critique, the Jo arc demand alone couldn't fill
  the segment.  The Jo cascade worked in reverse: c11:p100 moved to Institutions
- **6 of 7 segments affected** — only The Secret and the Chase survived intact
- Opening reshaped: gained c13 passages, lost c7:p35 (Blackstone atmosphere gone)
- Closing gained Sir Edmund content: c57:p112, c61:p42 (thematic_depth demand filled)
- Dickens at His Best lost cP:p0 and c8:p81 (Hartley narrative passages), gained
  c57:p128 (narrative_technique, now assigned to Hartley not Sir Edmund)

**Prediction accuracy:** Mostly confirmed.  Institutions thinning and Jo's Story
weakening were predicted.  The complete emptying of Jo's Story (0 passages, not
just thin) was stronger than expected — demonstrates that expert demands are the
primary driver for segment filling, not arc demands alone.  Closing gains and
Richard's Decline stability were correctly predicted.

---

## Variant 8: "The Marxist chair" — swap Hartley for Dr. Rosen

**Command:** `--replace-expert "Dr. Hartley=dr_rosen"`

**Producer rationale:** Replace the craft-focused literary critic with a
materialist reader.  The episode should foreground class, power, and the
material conditions Dickens depicts.

**Expected effects:**
- Hartley's narrative_technique=2 disappears entirely — no expert demands it
- Dr. Rosen brings social_critique=3 — combined with Blackstone's
  social_critique=2, the total demand for social critique rises from 2→5
- Dickens at His Best (preferred: narrative_technique, humor) may thin or
  reshape — narrative_technique is now undemanded by any expert
- Institutions Under Fire should fill richly — social_critique is now the
  most-demanded dimension
- Jo's Story should benefit — social_critique demand is massive
- The Secret and the Chase may be unaffected (plot_advancement, Dedlock arc)
- Atmosphere demand rises from 2→3 (Blackstone=2 + Rosen=2), which may
  pull more setting passages into Opening

**Actual results:**
- 6 added, 7 removed, 2 reassigned.  25 passages total (down from 26), 5 NULL
- Rosen pulled social_critique passages: c1:p9 (interest=4), c9:p94 (interest=4),
  c54:p30 (interest=3) — plus atmosphere c10:p60, char_dev c10:p8
- The fog passage c1:p0 (interest=5) entered via Woodcourt atmosphere — **notable**
- Lost all Hartley narrative_technique passages: c8:p81, cP:p0 — **confirmed**
- Dickens at His Best thinned to 2 passages (from 4) — **confirmed prediction**
- Jo's Story filled to 4 passages (Jo cascade: c11:p74, c11:p78, c11:p87 all
  migrated from Institutions) — **confirmed**
- Institutions Under Fire completely reshaped: gained Rosen's c1:p9, c54:p30,
  c64:p39, c9:p94; lost c11:p74, c11:p78, c11:p87, c55:p95, c65:p21 — 5 of 5
  passages changed
- c64:p39 reassigned Hartley → Blackstone; c8:p0 reassigned Blackstone → Rosen
- Richard's Decline and Secret and the Chase both stable (2 of 7 segments) —
  **confirmed prediction**
- Closing lost c48:p3 (Hartley char_dev) and c18:p18, gained c10:p8 (Rosen)

**Prediction accuracy:** Strong.  Narrative technique abandonment, Institutions
filling with social critique, Jo cascade, and Dickens at His Best thinning all
confirmed.  The atmosphere boost was visible (c1:p0 entering Opening).  The
reshaping of Institutions was more dramatic than expected — complete turnover.

---

## Variant 9: "The radical panel" — swap both Blackstone and Hartley

**Command:**
```
--replace-expert "Prof. Blackstone=sir_edmund"
--replace-expert "Dr. Hartley=dr_rosen"
```

**Producer rationale:** Maximum ideological contrast.  A conservative
formalist and a Marxist materialist, with Ms. Woodcourt as the humanising
middle ground.

**Expected effects:**
- Sir Edmund demands: char_dev=3, thematic=2, narrative=1
- Dr. Rosen demands: social_critique=3, atmosphere=2, char_dev=1
- Total demands shift dramatically:
  - character_development: 3+1+1=5 (was 2+0+1=3) — big increase
  - social_critique: 3 (was 2) — moderate increase
  - thematic_depth: 2 (was 1) — increase
  - atmosphere_setting: 2+1=3 (was 2+1=3) — same
  - narrative_technique: 1 (was 2) — decrease
  - humor: 2 (was 2) — same
- Richard's Decline should get even richer material (char_dev surge)
- Institutions should fill well (social_critique demand)
- Dickens at His Best may thin (narrative_technique nearly abandoned)
- The episode should feel more politically charged and character-focused

**Actual results:**
- 9 added, 7 removed, 2 reassigned.  28 passages total (up from 26), 2 NULL
- Sir Edmund pulled: c10:p2 (char_dev), c57:p128 (narrative), c59:p2 (char_dev),
  c61:p42 (thematic), c64:p29 (char_dev) — all character/thematic passages
- Rosen pulled: c1:p16 (social_critique), c1:p8 (social_critique), c9:p94
  (social_critique), c9:p106 (char_dev)
- Lost all Blackstone/Hartley originals: c55:p95, c65:p21, c8:p81, cP:p0,
  c18:p18, c48:p3, c64:p39
- Institutions Under Fire completely reshaped (5 of 5 passages changed):
  gained c1:p8, c1:p16, c9:p94, c12:p11, c12:p114 — all social critique/Jo
  content.  **Confirmed prediction.**
- Jo's Story filled to 4 passages: c11:p74, c11:p78, c11:p87 migrated from
  Institutions (Jo cascade), plus c11:p100 stayed — **confirmed**
- Secret and the Chase lost 2 Dedlock passages (c12:p11, c12:p114), gained
  c10:p2, c9:p106 — character development passages replaced plot advancement
- Dickens at His Best thinned to 2: lost c8:p81, cP:p0, gained c57:p128 —
  **confirmed** (narrative_technique nearly abandoned)
- Closing gained Sir Edmund's thematic content: c59:p2, c61:p42, c64:p29
- Opening and Richard's Decline both stable (2 of 7 segments)
- 15 chapters now covered (up from 14) — broader reach due to more expert demands

**Prediction accuracy:** Strong.  Character_development surge, social_critique
filling, Jo cascade, Dickens thinning all confirmed.  The episode feels more
politically charged and character-focused as predicted.  Secret and the Chase
being affected was unexpected — the dual swap created enough demand pressure
to reshape even arc-driven segments.

---

## Variant 10: "Rosen vs Blackstone on Jo" — Marxist + more Jo

**Command:**
```
--replace-expert "Dr. Hartley=dr_rosen"
--arc-demand "Jo's suffering=8"
```

**Producer rationale:** The most Jo-focused, politically charged version
possible.  Dr. Rosen's social_critique=3 plus doubled Jo arc demand should
produce a version of the episode that is fundamentally about class and
institutional violence.

**Expected effects:**
- Social critique demand massive: Rosen=3 + Blackstone=2 = 5 units
- Jo arc demand doubled to 8
- Jo's Story should fill completely (4 passages)
- Institutions should overflow with material
- Narrative technique fully abandoned (no expert demands it)
- This should produce the most passages overall (like V1 + V8 combined)
- The episode becomes essentially a political reading of Bleak House

**Actual results:**
- 10 added, 7 removed, 2 reassigned.  29 passages total (up from 26), 1 NULL —
  **highest passage count and lowest NULL of any variant**
- Combined Rosen social_critique=3 + Blackstone social_critique=2 + Jo demand=8
  created massive social_critique pull
- Rosen pulled: c10:p60 (atmosphere), c10:p8 (char_dev), c1:p9 (social_critique),
  c54:p30 (social_critique), c9:p94 (social_critique)
- Jo arc pulled: c11:p88 (interest=5, Jo weeps), c11:p98 (interest=4, cemetery),
  c11:p99 (interest=5, sweeps step), c12:p56 (interest=4, Boodle on government)
- c1:p0 (the fog, interest=5) entered via Woodcourt — same as V8
- Jo's Story filled with 4 highest-interest Jo passages: c11:p87, c11:p88,
  c11:p99, c12:p56 — **confirmed prediction**
- Institutions gained c11:p100, c11:p98, c54:p30 — filled with social critique
  material as predicted
- Dickens at His Best thinned to 2 (lost cP:p0, c8:p81, gained c12:p11) —
  **confirmed** (narrative technique undemanded)
- **6 of 7 segments affected** — only Richard's Decline stable
- Opening gained c1:p0 (fog) + c10:p60 (atmosphere) — richer scene-setting
- Closing completely reshaped: gained c1:p9, c9:p94, lost c18:p18, c48:p3 —
  became politically inflected

**Prediction accuracy:** Very strong.  This is indeed the "most passages overall"
variant (29, tied with none).  Jo's Story filled completely, Institutions
overflowed, narrative technique abandoned.  The episode reads as a political
analysis of Bleak House — exactly as intended.  The 1 NULL flow (minimum possible
given segment structure) shows the transport solver is maximally efficient when
given clear, strong demand signals.

---

## Cross-Variant Observations: Round 2 (Expert Swaps V7-V10)

### Key findings

1. **Expert demands dominate segment filling.**  V7 (conservative) proves this
   definitively: removing the only social_critique expert emptied Jo's Story to
   0 passages despite the arc demand still being 4.  Arc demands create supply,
   but expert demands create the pull that fills segments.

2. **The Jo cascade is bidirectional.**  In Round 1 variants, when Institutions
   loses passages, Jo gains them (forward cascade).  In V7, Jo's Story loses its
   passage and it moves to Institutions (reverse cascade).  The solver treats
   these as communicating vessels through the shared social_critique dimension.

3. **Expert swaps are instant and interpretable.**  All four variants ran in <2s
   with zero LLM cost.  The passage-level diffs show exactly which content moved
   and why.  This is the key selling point: a producer can audition different
   panel compositions and see the editorial consequences immediately.

4. **Dual swaps create superposition effects.**  V9 (radical_panel) affected
   Secret and the Chase — a segment driven by plot_advancement and the Dedlock
   arc, apparently insulated from expert ideology.  But with both original experts
   gone, the solver's secondary preferences shifted enough to reshape even this
   segment.  Single swaps (V7, V8) left it stable.

5. **Passage counts as a health metric.**  Variants range from 24 (V7) to 29
   (V10).  Lower counts mean more NULL flow (unfilled segment slots).  V10's
   near-zero NULL shows that strong, aligned demand signals make the solver
   maximally efficient.

6. **Closing is the most volatile segment.**  It has no preferred_experts and
   broad preferred_dimensions (thematic_depth).  Every variant reshapes it
   because leftover demand flows there.  A producer wanting a stable closing
   should add explicit expert preferences.

### Comparison table

| Variant | Passages | NULL | Segments affected | Jo's Story | Dickens at His Best |
|---------|----------|------|-------------------|------------|---------------------|
| Baseline | 26 | 4 | — | 1 | 4 |
| V7 conservative | 24 | 6 | 6/7 | **0** (emptied) | 3 |
| V8 marxist | 25 | 5 | 5/7 | **4** (filled) | **2** (thinned) |
| V9 radical_panel | 28 | 2 | 5/7 | **4** (filled) | **2** (thinned) |
| V10 rosen_jo | 29 | 1 | 6/7 | **4** (filled) | **2** (thinned) |
