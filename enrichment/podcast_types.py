"""Pydantic models for multi-voice podcast episode generation.

Defines the output schema for the hybrid transport pipeline:
  SegmentTemplate  — producer's episode structure definition
  Utterance        — atomic TTS unit (one sentence/clause with delivery annotations)
  Turn             — one speaker's contribution in a segment
  EpisodeSegment   — a segment of the episode with turns
  PodcastEpisode   — the complete episode
  EpisodeMetadata  — provenance and coverage information
  VoicePolicy      — per-speaker rendering defaults for TTS
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

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
        preferred_experts=["Caroline Woodcourt"],
    ),
    SegmentTemplate(
        name="Richard's Decline",
        segment_type="deep_dive",
        preferred_dimensions=["prov_character_development"],
        preferred_arcs=["Richard's deterioration"],
        min_passages=4,
        max_passages=6,
        preferred_experts=["Eleanor Hartley"],
    ),
    SegmentTemplate(
        name="Institutions Under Fire",
        segment_type="discussion",
        preferred_dimensions=["prov_social_critique", "prov_thematic_depth"],
        min_passages=3,
        max_passages=5,
        preferred_experts=["James Blackstone"],
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
        preferred_experts=["Caroline Woodcourt"],
    ),
    SegmentTemplate(
        name="Jo's Story",
        segment_type="deep_dive",
        preferred_dimensions=["prov_social_critique"],
        preferred_arcs=["Jo's suffering"],
        min_passages=3,
        max_passages=4,
        preferred_experts=["James Blackstone"],
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
# Output schema (Phase 3 output) — sentence-level for TTS rendering
# ---------------------------------------------------------------------------


class SentenceType(str, Enum):
    """Functional role of an utterance in the conversation flow."""

    intro = "intro"
    question = "question"
    quote_setup = "quote_setup"
    quote_reading = "quote_reading"
    analysis = "analysis"
    punchline = "punchline"
    transition = "transition"
    closing = "closing"


class Utterance(BaseModel):
    """One sentence or clause — the atomic unit for TTS synthesis.

    Each utterance carries delivery annotations that the TTS renderer uses
    to control pacing, emphasis, and quote handling.
    """

    text: str = Field(
        description="The spoken text (one sentence or short clause, max ~25 words)"
    )
    sentence_type: SentenceType = Field(
        description=(
            "Functional role: intro, question, quote_setup, quote_reading, "
            "analysis, punchline, transition, closing"
        )
    )
    is_quote: bool = Field(
        default=False,
        description="True if this utterance is a direct quote from the novel read aloud",
    )
    quote_mode: Literal["none", "setup", "reading", "commentary"] = Field(
        default="none",
        description=(
            "Quote handling: 'none' for normal speech, 'setup' for text leading "
            "into a quote, 'reading' for the quote itself, 'commentary' for "
            "text immediately following a quote"
        ),
    )
    rate: float = Field(
        default=1.0,
        description=(
            "Speaking rate multiplier relative to speaker default "
            "(0.90-1.05; use 0.92-0.95 for quotes, 1.02-1.05 for excited analysis)"
        ),
    )
    pause_before_ms: int = Field(
        default=0,
        description=(
            "Silence before this utterance in ms (0 normal; 120-220 before quotes; "
            "180-260 after speaker switch)"
        ),
    )
    pause_after_ms: int = Field(
        default=300,
        description=(
            "Silence after this utterance in ms (300 normal sentence; 500 emphasis; "
            "800 paragraph break; 1500 section break)"
        ),
    )
    emphasis_words: list[str] = Field(
        default_factory=list,
        description="Content words deserving slight emphasis (max 2-3 per utterance)",
    )
    passage_ref: str = Field(
        default="",
        description="passage_id being discussed (empty if none)",
    )


class Turn(BaseModel):
    """One speaker's contribution in a podcast segment, broken into utterances."""

    speaker: str = Field(
        description="Expert name, 'Host', or 'Narrator'"
    )
    role: str = Field(
        description="Role: literary_critic, social_historian, close_reader, host, narrator"
    )
    utterances: list[Utterance] = Field(
        description="Sentence-level units for TTS rendering, in speaking order"
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
# Expert personas and voice policies (used in Phase 3 prompts)
# ---------------------------------------------------------------------------


class VoicePolicy(BaseModel):
    """Per-speaker TTS rendering defaults."""

    rate: float = Field(description="Base speaking rate multiplier")
    energy: str = Field(description="Energy level: medium_low, medium, medium_high")
    pause_bias_ms: int = Field(description="Base inter-sentence pause bias in ms")
    style: str = Field(description="TTS style preset identifier")


class ExpertPersona(BaseModel):
    """Description of an expert's voice and perspective for script generation."""

    name: str
    role: str
    description: str
    voice_policy: VoicePolicy
    speaking_style: str = Field(
        default="",
        description="TTS-level sentence style guidance for this speaker",
    )


DEFAULT_PERSONAS = [
    ExpertPersona(
        name="Eleanor Hartley",
        role="literary_critic",
        description=(
            "Dr. Eleanor Hartley — a novelist herself who teaches creative writing.  Obsessed with how "
            "Dickens constructs his effects — the architecture of sentences, the "
            "dual narration, the way a single image can carry a chapter's meaning.  "
            "Gets visibly excited when she spots a structural choice she admires.  "
            "Has a gift for making technical craft feel thrilling rather than dry."
        ),
        voice_policy=VoicePolicy(
            rate=1.01,
            energy="medium_high",
            pause_bias_ms=170,
            style="analytic_bright",
        ),
        speaking_style=(
            "Agile, medium-length sentences.  Slightly faster when excited "
            "about craft.  Technical terms made vivid, never dry."
        ),
    ),
    ExpertPersona(
        name="James Blackstone",
        role="social_historian",
        description=(
            "Prof. James Blackstone — a legal historian who specializes in Victorian institutions.  Brings "
            "the real-world context — what Chancery actually was, how the Poor Law "
            "worked, what it meant to be Jo.  Can get genuinely angry about "
            "injustice, past and present.  Connects Dickens' world to modern "
            "parallels without being heavy-handed about it.  Dry wit."
        ),
        voice_policy=VoicePolicy(
            rate=0.96,
            energy="medium_low",
            pause_bias_ms=260,
            style="measured_dry",
        ),
        speaking_style=(
            "Measured, longer sentences kept fairly intact.  Authority comes "
            "from syntactic control.  Dry punchlines land with pause, not speed."
        ),
    ),
    ExpertPersona(
        name="Caroline Woodcourt",
        role="close_reader",
        description=(
            "Ms. Caroline Woodcourt — a book critic and lifelong Dickens reader who came to the novel as a "
            "teenager and has re-read it five times.  Focuses on the experience of "
            "reading — what's funny, what's moving, what makes you stop and re-read "
            "a sentence.  Loves reading passages aloud and catching the verbal music.  "
            "Has strong opinions about which characters deserve better."
        ),
        voice_policy=VoicePolicy(
            rate=0.97,
            energy="medium",
            pause_bias_ms=240,
            style="reflective_intimate",
        ),
        speaking_style=(
            "Emotionally engaged, intimate.  Shorter sentences when moved.  "
            "Slightly slower, more pauses.  Savours the verbal music."
        ),
    ),
]

ALTERNATIVE_PERSONAS: dict[str, ExpertPersona] = {
    "sir_edmund": ExpertPersona(
        name="Edmund Leigh",
        role="traditionalist_critic",
        description=(
            "Sir Edmund Leigh — a retired Oxford don and lifelong Tory who believes Dickens' genius lies "
            "in his moral imagination, not his social programme.  Reads Bleak House as "
            "a novel about individual character tested by circumstance — about Esther's "
            "goodness, Jarndyce's self-sacrifice, Richard's weakness of will.  Suspicious "
            "of politicised readings.  Thinks the fog is a literary device, not a metaphor "
            "for capitalism.  Beautifully spoken, occasionally withering, always courteous.  "
            "Quotes Dr. Johnson and Burke as readily as Dickens."
        ),
        voice_policy=VoicePolicy(
            rate=0.94,
            energy="medium_low",
            pause_bias_ms=280,
            style="patrician_measured",
        ),
        speaking_style=(
            "Stately, carefully composed sentences.  Unhurried.  Occasional "
            "withering asides delivered with perfect courtesy.  Long pauses "
            "before the key word."
        ),
    ),
    "dr_rosen": ExpertPersona(
        name="Daniel Rosen",
        role="marxist_critic",
        description=(
            "Dr. Daniel Rosen — a cultural historian who reads Bleak House as an anatomy of class power.  "
            "Every institution in the novel — Chancery, the law, philanthropy, the "
            "aristocracy — is a mechanism for extracting value from the poor and protecting "
            "the rich.  Sees Jo not as a sentimental figure but as the novel's clearest "
            "image of what the system actually produces.  Can be fierce but is never "
            "dogmatic in a tiresome way — he earns his anger with evidence.  Thinks "
            "Dickens was more radical than Dickens himself knew."
        ),
        voice_policy=VoicePolicy(
            rate=0.99,
            energy="medium_high",
            pause_bias_ms=200,
            style="passionate_precise",
        ),
        speaking_style=(
            "Precise, purposeful sentences that build an argument.  Bursts of "
            "controlled intensity.  Evidence first, then the verdict — delivered "
            "with quiet force."
        ),
    ),
    "trevelyan": ExpertPersona(
        name="Oliver Trevelyan",
        role="performer_and_wit",
        description=(
            "Actor, writer, and the voice of more Dickens audiobooks than anyone alive.  "
            "Approaches Bleak House as a performer first — he hears the rhythms of the "
            "prose, spots the comic timing, catches the moments Dickens wrote for the "
            "voice rather than the page.  Endlessly quotable himself.  Loves the "
            "grotesques (Krook, Smallweed, Chadband) with genuine delight.  Gets quiet "
            "and serious when the novel earns it — Jo's death, Esther's illness — but "
            "always returns to the pleasure of the text.  Believes Dickens was above all "
            "an entertainer of genius."
        ),
        voice_policy=VoicePolicy(
            rate=1.02,
            energy="medium_high",
            pause_bias_ms=190,
            style="raconteur_warm",
        ),
        speaking_style=(
            "Natural raconteur rhythm — varied sentence lengths, comic timing "
            "built into the phrasing.  Reads quotes with theatrical relish.  "
            "Knows when to let silence do the work."
        ),
    ),
}

HOST_VOICE_POLICY = VoicePolicy(
    rate=0.98,
    energy="medium",
    pause_bias_ms=220,
    style="presenter_warm",
)
