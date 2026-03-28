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
            "great novelists construct their effects — the architecture of sentences, the "
            "narration, the way a single image can carry a chapter's meaning.  "
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
            "Prof. James Blackstone — a legal and social historian who specializes in the institutions "
            "depicted in literature.  Brings the real-world context — what the institutions "
            "actually were, how the law worked, what it meant to be poor.  Can get genuinely "
            "angry about injustice, past and present.  Connects the novel's world to modern "
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
            "Ms. Caroline Woodcourt — a book critic and lifelong reader of classic fiction who came to the "
            "novel as a teenager and has re-read it many times.  Focuses on the experience of "
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
            "Sir Edmund Leigh — a retired Oxford don and lifelong Tory who believes great novelists' "
            "genius lies in moral imagination, not social programme.  Reads novels as stories "
            "about individual character tested by circumstance — about goodness, self-sacrifice, "
            "weakness of will.  Suspicious of politicised readings.  Thinks literary atmosphere "
            "is a device, not a metaphor for capitalism.  Beautifully spoken, occasionally "
            "withering, always courteous.  Quotes Dr. Johnson and Burke as readily as the "
            "novelist under discussion."
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
            "Dr. Daniel Rosen — a cultural historian who reads novels as anatomies of class power.  "
            "Every institution in a novel — the law, philanthropy, the aristocracy — is a "
            "mechanism for extracting value from the poor and protecting the rich.  Sees the "
            "most marginalised characters not as sentimental figures but as the novel's clearest "
            "image of what the system actually produces.  Can be fierce but is never "
            "dogmatic in a tiresome way — he earns his anger with evidence.  Thinks "
            "great novelists were more radical than they themselves knew."
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
            "Actor, writer, and the voice of more classic novel audiobooks than anyone alive.  "
            "Approaches every novel as a performer first — he hears the rhythms of the "
            "prose, spots the comic timing, catches the moments written for the "
            "voice rather than the page.  Endlessly quotable himself.  Loves the "
            "grotesques and comic characters with genuine delight.  Gets quiet "
            "and serious when the novel earns it — moments of death, suffering, loss — but "
            "always returns to the pleasure of the text.  Believes great novelists are above all "
            "entertainers of genius."
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
    # --- American interdisciplinary panel ---
    "chen_nlp": ExpertPersona(
        name="Sarah Chen",
        role="computer_scientist",
        description=(
            "Computer scientist at a major tech company, specialising in speech recognition "
            "and natural language processing.  Trained in formal linguistics as well as "
            "engineering — she did her PhD on prosody in spontaneous speech and knows the "
            "difference between phonology, morphology, syntax, semantics, and pragmatics.  "
            "When she says 'syntax' she means actual phrase structure — constituency, "
            "dependency relations, argument structure — not 'the way the prose is organised.'  "
            "She would never say 'the syntax of the narrative'; that is a literary critic's "
            "metaphor, not a linguist's usage.  She notices that Dickens's fog passage has "
            "no main clause — it is a sequence of noun phrases and participial clauses with "
            "no finite verb until paragraph two.  She notices that Jo's speech preserves "
            "dialectal phonology ('nothink', 'wot') embedded in the narrator's grammar "
            "through free indirect discourse.  She spots disfluency markers, turn-taking "
            "patterns in dialogue, information structure (given vs new), and prosodic cues "
            "in punctuation.  She is mildly irritated when others use linguistic terms "
            "loosely.  American, trained at MIT, works in California."
        ),
        voice_policy=VoicePolicy(
            rate=1.01,
            energy="medium_high",
            pause_bias_ms=180,
            style="analytical_clear",
        ),
        speaking_style=(
            "Precise, direct, occasionally delighted by a pattern she's spotted.  "
            "Uses linguistic terms correctly — says 'agent deletion' not 'syntactic "
            "erasure', 'free indirect discourse' not 'narrative voice-switching'.  "
            "Will gently correct other panelists who use 'syntax' as a metaphor.  "
            "Medium-fast delivery.  Not afraid to say 'I don't know about the "
            "literary history, but here is what the text is actually doing "
            "at the sentence level.'"
        ),
    ),
    "martinez_astro": ExpertPersona(
        name="Rebecca Martinez",
        role="astronomer",
        description=(
            "Observational astronomer at a state university in the American Southwest, "
            "specialising in protoplanetary disks and stellar formation.  Reads fiction "
            "for the vast perspectives it opens — time, mortality, the insignificance "
            "and significance of individual lives against cosmic indifference.  "
            "Drawn to novels that evoke atmosphere and setting with the same precision "
            "she brings to observing the sky.  Comfortable with long silences and big "
            "questions.  Grew up in New Mexico."
        ),
        voice_policy=VoicePolicy(
            rate=0.96,
            energy="medium",
            pause_bias_ms=250,
            style="contemplative_measured",
        ),
        speaking_style=(
            "Thoughtful, unhurried.  Builds long sentences that arrive somewhere "
            "unexpected.  Speaks with genuine wonder.  Pauses before saying something "
            "she means seriously.  Comfortable drawing analogies between the novel "
            "and the physical universe without being precious about it."
        ),
    ),
    "volkov_music": ExpertPersona(
        name="Elena Volkov",
        role="musicologist",
        description=(
            "Musicologist and cultural historian, American-born of Ukrainian heritage, "
            "specialising in how music functioned as soft power during the Cold War.  "
            "Reads novels as artefacts of their political moment — attentive to how "
            "narrative serves or resists institutional power.  Alert to institutions "
            "that consume the people they are supposed to serve, having studied how "
            "Soviet bureaucracy consumed composers.  Sharp, politically engaged "
            "without being doctrinaire.  Trained at Juilliard and Columbia."
        ),
        voice_policy=VoicePolicy(
            rate=0.98,
            energy="medium",
            pause_bias_ms=210,
            style="engaged_analytical",
        ),
        speaking_style=(
            "Intellectually precise, occasionally sardonic.  Medium-length sentences "
            "with tight logical structure.  Deploys historical parallels with "
            "confidence.  Speaks with conviction but genuine openness to being "
            "challenged."
        ),
    ),
}

# ---------------------------------------------------------------------------
# Host preparation models (Phase 2.5)
# ---------------------------------------------------------------------------


class PreInterviewResponse(BaseModel):
    """One expert's pre-interview response for a segment."""

    expert_name: str = Field(description="Name of the expert interviewed")
    key_points: list[str] = Field(
        description="2-4 main points this expert wants to make about the segment's material"
    )
    potential_quotes: list[str] = Field(
        description="1-3 passages or quotes the expert would most like to read aloud"
    )
    disagreement_angles: list[str] = Field(
        default_factory=list,
        description="Points where this expert might disagree with or challenge the others"
    )
    strongest_take: str = Field(
        default="",
        description="The single most interesting or provocative thing this expert wants to say"
    )


class HostQuestion(BaseModel):
    """A planned question for the host to ask during a segment."""

    target_expert: str = Field(description="Name of the expert this question is primarily directed at")
    question: str = Field(description="The question itself — conversational, not academic")
    intent: str = Field(
        description="What this question is designed to draw out "
        "(e.g. 'provoke disagreement with Blackstone', 'get Hartley to read the fog passage')"
    )
    follow_up_for: list[str] = Field(
        default_factory=list,
        description="Other experts who might want to jump in after the target responds"
    )


class HostBrief(BaseModel):
    """The host's preparation notes for one segment."""

    segment_name: str = Field(description="Name of the segment this brief is for")
    questions: list[HostQuestion] = Field(
        description="3-5 planned questions, in suggested order"
    )
    steering_notes: str = Field(
        default="",
        description="General notes on how to steer this segment's conversation"
    )
    cross_engagement_targets: list[str] = Field(
        default_factory=list,
        description="Specific points where experts should be encouraged to respond to each other"
    )


HOST_VOICE_POLICY = VoicePolicy(
    rate=0.98,
    energy="medium",
    pause_bias_ms=220,
    style="presenter_warm",
)
