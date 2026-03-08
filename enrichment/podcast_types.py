"""Pydantic models for multi-voice podcast episode generation.

Defines the output schema for the hybrid transport pipeline:
  SegmentTemplate  — producer's episode structure definition
  Turn             — one speaker's contribution in a segment
  EpisodeSegment   — a segment of the episode with turns
  PodcastEpisode   — the complete episode
  EpisodeMetadata  — provenance and coverage information
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Segment templates (input to Phase 2 transport)
# ---------------------------------------------------------------------------


class SegmentTemplate(BaseModel):
    """Producer-defined episode segment with demand profile."""

    name: str = Field(description="Segment title, e.g. 'Opening: The Fog'")
    segment_type: str = Field(
        description="Category: opening, deep_dive, discussion, close_reading, closing"
    )
    preferred_dimensions: list[str] = Field(
        default_factory=list,
        description="prov_* fields this segment wants",
    )
    preferred_arcs: list[str] = Field(
        default_factory=list,
        description="Character arc names this segment tracks",
    )
    min_passages: int = Field(default=2, description="Minimum passages to fill")
    max_passages: int = Field(default=5, description="Maximum passages")
    preferred_experts: list[str] = Field(
        default_factory=list,
        description="Experts who should lead (empty = any)",
    )


# ---------------------------------------------------------------------------
# Default episode structure for Bleak House
# ---------------------------------------------------------------------------

DEFAULT_SEGMENT_TEMPLATES = [
    SegmentTemplate(
        name="Opening: The World of Bleak House",
        segment_type="opening",
        preferred_dimensions=["prov_atmosphere_setting"],
        min_passages=2,
        max_passages=3,
        preferred_experts=["Ms. Woodcourt"],
    ),
    SegmentTemplate(
        name="Richard's Decline",
        segment_type="deep_dive",
        preferred_dimensions=["prov_character_development"],
        preferred_arcs=["Richard's deterioration"],
        min_passages=4,
        max_passages=6,
        preferred_experts=["Dr. Hartley"],
    ),
    SegmentTemplate(
        name="Institutions Under Fire",
        segment_type="discussion",
        preferred_dimensions=["prov_social_critique", "prov_thematic_depth"],
        min_passages=3,
        max_passages=5,
        preferred_experts=["Prof. Blackstone"],
    ),
    SegmentTemplate(
        name="The Secret and the Chase",
        segment_type="deep_dive",
        preferred_dimensions=["prov_plot_advancement", "prov_character_development"],
        preferred_arcs=["Lady Dedlock's secret"],
        min_passages=3,
        max_passages=5,
    ),
    SegmentTemplate(
        name="Dickens at His Best",
        segment_type="close_reading",
        preferred_dimensions=["prov_narrative_technique", "prov_humor_entertainment"],
        min_passages=3,
        max_passages=4,
        preferred_experts=["Ms. Woodcourt"],
    ),
    SegmentTemplate(
        name="Jo's Story",
        segment_type="deep_dive",
        preferred_dimensions=["prov_social_critique"],
        preferred_arcs=["Jo's suffering"],
        min_passages=3,
        max_passages=4,
        preferred_experts=["Prof. Blackstone"],
    ),
    SegmentTemplate(
        name="Closing: What Bleak House Means Today",
        segment_type="closing",
        preferred_dimensions=["prov_thematic_depth"],
        min_passages=2,
        max_passages=3,
    ),
]


# ---------------------------------------------------------------------------
# Output schema (Phase 3 output)
# ---------------------------------------------------------------------------


class Turn(BaseModel):
    """One speaker's contribution in a podcast segment."""

    speaker: str = Field(description="Expert name or 'Narrator'")
    role: str = Field(
        description="Role: literary_critic, social_historian, close_reader, narrator"
    )
    content: str = Field(description="What the speaker says")
    quotes: list[str] = Field(
        default_factory=list,
        description="Direct quotes from the text referenced in this turn",
    )
    passage_refs: list[str] = Field(
        default_factory=list,
        description="passage_ids being discussed",
    )


class EpisodeSegment(BaseModel):
    """One segment of the podcast episode."""

    title: str
    segment_type: str
    turns: list[Turn]


class EpisodeMetadata(BaseModel):
    """Provenance and coverage information for the episode."""

    chapters_covered: list[str] = Field(default_factory=list)
    characters_featured: list[str] = Field(default_factory=list)
    arcs_tracked: list[str] = Field(default_factory=list)
    total_passages: int = 0
    generation_tag: str = ""


class PodcastEpisode(BaseModel):
    """Complete multi-voice podcast episode."""

    title: str
    segments: list[EpisodeSegment]
    metadata: EpisodeMetadata = Field(default_factory=EpisodeMetadata)


# ---------------------------------------------------------------------------
# Expert personas (used in Phase 3 prompts)
# ---------------------------------------------------------------------------


class ExpertPersona(BaseModel):
    """Description of an expert's voice and perspective for script generation."""

    name: str
    role: str
    description: str


DEFAULT_PERSONAS = [
    ExpertPersona(
        name="Dr. Hartley",
        role="literary_critic",
        description=(
            "A novelist herself who teaches creative writing.  Obsessed with how "
            "Dickens constructs his effects — the architecture of sentences, the "
            "dual narration, the way a single image can carry a chapter's meaning.  "
            "Gets visibly excited when she spots a structural choice she admires.  "
            "Has a gift for making technical craft feel thrilling rather than dry."
        ),
    ),
    ExpertPersona(
        name="Prof. Blackstone",
        role="social_historian",
        description=(
            "A legal historian who specializes in Victorian institutions.  Brings "
            "the real-world context — what Chancery actually was, how the Poor Law "
            "worked, what it meant to be Jo.  Can get genuinely angry about "
            "injustice, past and present.  Connects Dickens' world to modern "
            "parallels without being heavy-handed about it.  Dry wit."
        ),
    ),
    ExpertPersona(
        name="Ms. Woodcourt",
        role="close_reader",
        description=(
            "A book critic and lifelong Dickens reader who came to the novel as a "
            "teenager and has re-read it five times.  Focuses on the experience of "
            "reading — what's funny, what's moving, what makes you stop and re-read "
            "a sentence.  Loves reading passages aloud and catching the verbal music.  "
            "Has strong opinions about which characters deserve better."
        ),
    ),
]
