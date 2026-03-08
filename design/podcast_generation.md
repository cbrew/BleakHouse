# Design: Podcast Generation via Hybrid Transport

**Status:** Draft
**Depends on:** Transport podcast solver (`transport_podcast.py`), enrichment pipeline

## Overview

Generate a multi-voice literary podcast episode by combining two transport
solves with per-segment LLM generation.

**Phase 1 — Passage Selection** (existing `transport_podcast.py`):
Select passages and assign them to experts based on provision dimensions
and character arcs.

**Phase 2 — Segment Assignment** (new):
Organize (passage, expert) pairs into episode segments. Each segment is a
demand node with a thematic profile and capacity bounds. A second min-cost
flow assigns passages to segments, favoring narrative adjacency and
thematic coherence.

**Phase 3 — Script Generation** (new):
For each segment, an LLM writes a multi-voice discussion script. Each
expert discusses their assigned passages from their perspective. Small,
parallelizable calls — no progressive merge compression.

**Phase 4 — Assembly** (new):
Concatenate segment scripts with transitions. Optionally a final LLM pass
for episode-level coherence.

---

## Architecture

```
passages_enriched.json (6,916 passages)
        │
        ▼
transport_podcast.py (Phase 1)
  ├── per-dimension min-cost flow
  ├── character arc flow
  └── aggregation
        │
        ▼
AggregatedResult: ~25-30 (passage, expert, dimension) assignments
        │
        ▼
segment_transport.py (Phase 2)
  ├── segment templates (producer-defined episode structure)
  ├── min-cost flow: assign (passage, expert) → segment
  └── narrative adjacency + thematic coherence costs
        │
        ▼
SegmentPlan: ordered list of segments, each with assigned passages + experts
        │
        ▼
generate_podcast.py (Phase 3 + 4)
  ├── per-segment LLM call (passage text + enrichment + expert persona)
  ├── output: multi-voice script per segment
  └── assembly with transitions
        │
        ▼
PodcastEpisode (structured output)
```

---

## Phase 2: Segment Transport

### Segment Templates

The producer defines the episode structure as a list of segment templates.
Each template specifies:

```python
@dataclass
class SegmentTemplate:
    name: str                           # "Opening: London Fog"
    segment_type: str                   # "opening", "deep_dive", "discussion", "close_reading", "closing"
    preferred_dimensions: list[str]     # prov_* fields this segment wants
    preferred_arcs: list[str]           # character arc names (empty = no preference)
    min_passages: int                   # minimum passages to fill this segment
    max_passages: int                   # maximum passages
    preferred_experts: list[str]        # experts who should lead (empty = any)
```

Default episode structure for Bleak House:

| Segment | Type | Preferred Dimensions | Passages |
|---------|------|---------------------|----------|
| Opening: The World of Bleak House | opening | atmosphere_setting | 2-3 |
| Richard's Decline | deep_dive | character_development, arc:Richard | 4-6 |
| Institutions Under Fire | discussion | social_critique, thematic_depth | 3-5 |
| The Secret and the Chase | deep_dive | plot_advancement, arc:Lady Dedlock | 3-5 |
| Dickens at His Best | close_reading | narrative_technique, humor_entertainment | 3-4 |
| Jo's Story | deep_dive | social_critique, arc:Jo | 3-4 |
| Closing: What Bleak House Means Today | closing | thematic_depth | 2-3 |

### Flow Network

```
              ┌──────────────┐
              │ SUPER_SOURCE │
              └──────┬───────┘
                     │
         ┌───────────┼───────────┐
         │           │           │
         ▼           ▼           ▼
   ┌──────────┐ ┌──────────┐ ┌──────────┐
   │ passage  │ │ passage  │ │  NULL    │
   │ (p,exp)  │ │ (p,exp)  │ │          │
   │ supply=1 │ │ supply=1 │ │          │
   └────┬─────┘ └────┬─────┘ └────┬─────┘
        │             │             │
        ├─────┬───────┼─────┬───────┤
        │     │       │     │       │
        ▼     ▼       ▼     ▼       ▼
   ┌─────────┐ ┌─────────┐ ┌─────────┐
   │ Opening │ │Deep Dive│ │ Closing │
   │ cap=2-3 │ │ cap=4-6 │ │ cap=2-3 │
   └────┬────┘ └────┬────┘ └────┬────┘
        │            │            │
        └────────────┼────────────┘
                     ▼
              ┌─────────────┐
              │  SUPER_SINK │
              └─────────────┘
```

### Cost Structure

Each (passage, expert) → segment arc has cost based on:

1. **Dimension match** (0 if passage dimension ∈ segment's preferred_dimensions, else 5)
2. **Arc match** (0 if passage's arc ∈ segment's preferred_arcs, else 3 if passage has arc)
3. **Expert match** (0 if expert ∈ segment's preferred_experts, else 2)
4. **Narrative adjacency bonus**: Passages from nearby chapters get a cost
   reduction when assigned to the same segment. Computed as
   `max(0, chapter_distance - 5)` to encourage thematic clustering.

### Minimum fill

Each segment has `min_passages`. If a segment gets fewer than its minimum,
NULL flow fills the gap. The gap report tells the producer which segments
are thin and might need redesign or a broader transport solve.

---

## Phase 3: Script Generation

### Output Schema

```python
@dataclass
class Turn:
    speaker: str          # expert name or "Narrator"
    role: str             # "literary_critic", "social_historian", "close_reader", "narrator"
    content: str          # what they say
    quotes: list[str]     # quotes from the text they reference
    passage_refs: list[str]  # passage_ids they're discussing

@dataclass
class EpisodeSegment:
    title: str
    segment_type: str
    turns: list[Turn]

@dataclass
class PodcastEpisode:
    title: str
    segments: list[EpisodeSegment]
    metadata: EpisodeMetadata

@dataclass
class EpisodeMetadata:
    chapters_covered: list[str]
    characters_featured: list[str]
    arcs_tracked: list[str]
    total_passages: int
    generation_tag: str
```

### Per-Segment Prompt

Each segment LLM call receives:

1. **Segment template**: type, title, tone guidance
2. **Assigned passages**: For each passage:
   - Full text
   - Enrichment: summary, themes, characters, emotional_register, best_quote, narrator
   - Expert assignment: who discusses it and why (dimension)
   - Arc membership (if any)
3. **Expert personas**: Brief description of each expert's perspective
4. **Instruction**: Write a multi-voice discussion. Each expert discusses
   their assigned passages from their role's perspective. Include direct
   quotes from the text. The discussion should feel natural, with experts
   building on each other's observations.

### Expert Personas

```
Dr. Hartley (Literary Critic):
  Focuses on narrative technique, character development, and thematic depth.
  Notices structural choices, prose style, and how Dickens builds complexity.
  Tone: analytical but accessible, occasionally passionate about craft.

Prof. Blackstone (Social Historian):
  Focuses on social critique, institutional failure, and historical context.
  Connects passages to Victorian society, legal system, class structure.
  Tone: authoritative, sometimes indignant about injustice, contextualizing.

Ms. Woodcourt (Close Reader):
  Focuses on humor, atmosphere, character voice, and quotable moments.
  Reads passages aloud, catches verbal wit, notices emotional texture.
  Tone: warm, enthusiastic, attuned to the pleasure of reading.
```

### Generation Strategy

Use Claude (Haiku for cost, Sonnet for quality) with structured output.
Each segment is an independent LLM call — parallelizable.

Estimated cost: 7 segments × ~2K tokens input + ~1K output ≈ $0.50-2.00
depending on model.

---

## Phase 4: Assembly

Options:

**A. Simple concatenation**: Join segments with brief narrator transitions
("Moving from the fog of Chancery to the drawing rooms of Chesney Wold...").
Transitions can be generated per-segment or in a final pass.

**B. Final coherence pass**: Send all segment scripts to an LLM for a
light editing pass — smoothing transitions, ensuring arc threads are
connected, adding callbacks to earlier segments.

**Recommendation**: Start with A. Add B if the output feels disjointed.

---

## Implementation Files

| File | Purpose |
|------|---------|
| `enrichment/podcast_types.py` | New Pydantic models: SegmentTemplate, Turn, EpisodeSegment, PodcastEpisode |
| `enrichment/segment_transport.py` | Phase 2: assign passages to segments via min-cost flow |
| `enrichment/generate_podcast.py` | Phase 3+4: per-segment LLM generation + assembly |

---

## Configuration

The producer controls the episode by adjusting:

1. **Expert profiles** (existing): who wants what
2. **Arc demands** (existing): which character threads to track
3. **Redundancy penalty** (existing): how much to spread across clusters
4. **Segment templates** (new): episode structure and segment demands
5. **Expert personas** (new): voice and perspective descriptions

All are dataclasses with sensible defaults, overridable at runtime.
