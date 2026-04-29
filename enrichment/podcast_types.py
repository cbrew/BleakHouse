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
# Post-generation role normalisation
# ---------------------------------------------------------------------------


def fix_turn_roles(
    episode_dict: dict,
    personas: list["ExpertPersona"],
) -> dict:
    """Overwrite each turn's ``role`` field with the persona's canonical role.

    The LLM sometimes invents roles like ``close_reader`` or ``social_historian``
    instead of using the persona's actual role.  This fixes them in-place.
    """
    name_to_role: dict[str, str] = {p.name: p.role for p in personas}
    name_to_role["Host"] = "host"
    name_to_role["Narrator"] = "narrator"

    for seg in episode_dict.get("segments", []):
        for turn in seg.get("turns", []):
            speaker = turn.get("speaker", "")
            if speaker in name_to_role:
                turn["role"] = name_to_role[speaker]
    return episode_dict


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
    script_description: str = Field(
        default="",
        description=(
            "Shorter description for Phase 3 script generation — perspective "
            "and voice, not methods. Falls back to description when empty."
        ),
    )
DEFAULT_PERSONAS = [
    ExpertPersona(
        name="Eleanor Hartley",
        role="novelist_and_craft_teacher",
        description=(
            "Dr. Eleanor Hartley — a novelist herself who teaches creative writing at "
            "university level.  Her method is the writer's workshop: she takes passages "
            "apart to see how they achieve their effects.  She will propose craft exercises "
            "— rewrite this passage in a different tense and see what breaks, identify "
            "the single load-bearing sentence in a paragraph, trace an image pattern across "
            "chapters and ask what it accumulates.  She reads as a maker: every structural "
            "choice is a decision that could have gone differently, and she wants to know "
            "why this choice and not another.  She gets visibly excited when she spots "
            "something she would teach.  What she brings is not just admiration for craft "
            "but a toolkit for reverse-engineering it."
        ),
        script_description=(
            "Novelist and creative writing teacher.  Reads as a maker — every structural "
            "choice is a decision that could have gone differently.  Gets visibly excited "
            "when she spots something she would teach.  Notices craft: load-bearing "
            "sentences, image patterns, the effect of tense and point of view."
        ),
        voice_policy=VoicePolicy(
            rate=1.01,
            energy="medium_high",
            pause_bias_ms=170,
            style="analytic_bright",
        ),
        speaking_style=(
            "Agile, medium-length sentences.  Slightly faster when excited "
            "about craft.  Proposes exercises and experiments with the text.  "
            "Technical terms made vivid, never dry."
        ),
    ),
    ExpertPersona(
        name="James Blackstone",
        role="legal_and_social_historian",
        description=(
            "Prof. James Blackstone — a legal and social historian who works with "
            "primary sources: court records, parliamentary debates, Poor Law documents, "
            "charity commission reports.  His method is archival: when the novel depicts "
            "an institution, he asks what the historical record says about that institution "
            "— which court is this, what statute governs it, what did it actually cost the "
            "people caught in it.  He will name specific Acts of Parliament, cite case law, "
            "compare the novel's depiction to documented reality.  He gets genuinely angry "
            "about injustice, past and present, but his anger is grounded in evidence, not "
            "rhetoric.  What he brings is not just context but the historian's discipline "
            "of checking claims against the record."
        ),
        script_description=(
            "Legal and social historian who works with primary sources.  When the novel "
            "depicts an institution, he knows what the historical record says about it.  "
            "Gets genuinely angry about injustice, but his anger is grounded in evidence.  "
            "Names specific Acts, cases, dates."
        ),
        voice_policy=VoicePolicy(
            rate=0.96,
            energy="medium_low",
            pause_bias_ms=260,
            style="measured_dry",
        ),
        speaking_style=(
            "Measured, longer sentences kept fairly intact.  Authority comes "
            "from evidence, not assertion.  Names dates, statutes, cases.  "
            "Dry punchlines land with pause, not speed."
        ),
    ),
    ExpertPersona(
        name="Caroline Woodcourt",
        role="critic_and_lifelong_reader",
        description=(
            "Ms. Caroline Woodcourt — a book critic who has read this novel many times "
            "over decades and brings the method of sustained re-reading.  Her toolkit is "
            "the reader's own experience tracked over time: she notices what struck her "
            "at sixteen, what she missed until her thirties, what only becomes visible "
            "on a fifth reading.  She proposes reading experiments — read this passage "
            "aloud and notice where your voice changes, cover the last paragraph and "
            "predict what it says, compare your emotional response to Chapter 3 with "
            "your response to Chapter 50.  She tracks identification — which character "
            "she roots for and when that shifts — as data about the novel's moral "
            "design.  What she brings is not just feeling but the discipline of noticing "
            "what reading actually does to a reader."
        ),
        script_description=(
            "Book critic who has read this novel many times over decades.  Notices what "
            "struck her at different ages, what only becomes visible on re-reading.  "
            "Tracks her own identification — which character she roots for and when that "
            "shifts — as evidence about the novel's moral design.  Emotionally engaged."
        ),
        voice_policy=VoicePolicy(
            rate=0.97,
            energy="medium",
            pause_bias_ms=240,
            style="reflective_intimate",
        ),
        speaking_style=(
            "Emotionally engaged, intimate.  Shorter sentences when moved.  "
            "Proposes experiments with reading and re-reading.  "
            "Slightly slower, more pauses.  Savours the verbal music."
        ),
    ),
]

ALTERNATIVE_PERSONAS: dict[str, ExpertPersona] = {
    "sir_edmund": ExpertPersona(
        name="Edmund Leigh",
        role="moral_philosopher",
        description=(
            "Sir Edmund Leigh — a retired Oxford don whose method is moral-philosophical "
            "analysis in the tradition of Johnson and Burke.  He reads novels as case studies "
            "in practical ethics: which virtue is tested in this scene, what would a person "
            "of good character do, where does the novelist show weakness of will as distinct "
            "from wickedness.  His toolkit includes: mapping the moral architecture of a plot "
            "— who is tested, by what, with what result; comparing the novelist's moral "
            "intuitions to explicit philosophical frameworks (Aristotelian virtue ethics, "
            "Burkean conservatism, Johnsonian common sense); and identifying moments where "
            "the novel's moral structure contradicts its surface politics.  Beautifully spoken, "
            "occasionally withering, always courteous.  What he brings is not nostalgia but "
            "a rigorous method for extracting ethical propositions from narrative."
        ),
        voice_policy=VoicePolicy(
            rate=0.94,
            energy="medium_low",
            pause_bias_ms=280,
            style="patrician_measured",
        ),
        script_description=(
            "Retired Oxford don.  Reads novels as case studies in practical ethics — "
            "which virtue is tested, where does weakness of will shade into wickedness.  "
            "Beautifully spoken, occasionally withering, always courteous."
        ),
        speaking_style=(
            "Stately, carefully composed sentences.  Unhurried.  Applies named "
            "philosophical frameworks to specific passages.  Occasional "
            "withering asides delivered with perfect courtesy."
        ),
    ),
    "dr_rosen": ExpertPersona(
        name="Daniel Rosen",
        role="marxist_cultural_historian",
        description=(
            "Dr. Daniel Rosen — a cultural historian whose method is materialist analysis.  "
            "For any scene he asks: who owns what, what labour is visible and invisible, "
            "what economic relationship determines this character's options.  His toolkit "
            "includes: mapping property relations across the plot, identifying the class "
            "position of every character, tracing how economic structure constrains or "
            "enables the story, comparing the novel's implicit economics to documented "
            "Victorian economic conditions (wages, rents, cost of living).  He will cite "
            "specific historical data — what a clerk earned in 1853, what Chancery fees "
            "actually were — and compare them to the novel's depiction.  Can be fierce but "
            "earns his anger with evidence.  What he brings is not just 'I see class struggle' "
            "but a systematic method for analysing how economic power structures a narrative."
        ),
        voice_policy=VoicePolicy(
            rate=0.99,
            energy="medium_high",
            pause_bias_ms=200,
            style="passionate_precise",
        ),
        script_description=(
            "Cultural historian who asks: who owns what, what labour is visible and "
            "invisible, what economic relationship determines this character's options.  "
            "Cites specific historical data — wages, rents, costs.  Can be fierce but "
            "earns his anger with evidence."
        ),
        speaking_style=(
            "Precise, purposeful sentences that build an argument.  Cites economic "
            "data and historical conditions.  Bursts of controlled intensity.  "
            "Evidence first, then the verdict."
        ),
    ),
    "trevelyan": ExpertPersona(
        name="Oliver Trevelyan",
        role="actor_and_narrator",
        description=(
            "Oliver Trevelyan — actor, writer, and the voice of more classic novel audiobooks "
            "than anyone alive.  His method is performance analysis: he reads every passage as "
            "a script.  His toolkit includes: identifying the beats in a scene (where the "
            "energy shifts, where a character's intention changes), mapping the vocal register "
            "each character requires, discovering the rhythm the prose demands when spoken "
            "aloud — where it speeds up, where it insists on pauses, where the comedy is "
            "built into the sentence structure rather than the content.  He will propose "
            "staging: how would you cast this scene, what does the physical space look like, "
            "where would an actor stand.  He notices what silent reading misses — the breath "
            "patterns, the tongue-twisters, the passages that only make sense as speech acts.  "
            "What he brings is not just theatrical enthusiasm but the performer's technical "
            "analysis of how prose works as sound and action."
        ),
        voice_policy=VoicePolicy(
            rate=1.02,
            energy="medium_high",
            pause_bias_ms=190,
            style="raconteur_warm",
        ),
        script_description=(
            "Actor, writer, and the voice of more classic novel audiobooks than anyone "
            "alive.  Notices what silent reading misses — breath patterns, tongue-twisters, "
            "passages that only make sense as speech acts.  Natural raconteur with "
            "theatrical relish."
        ),
        speaking_style=(
            "Natural raconteur rhythm — varied sentence lengths, comic timing "
            "built into the phrasing.  Proposes staging and vocal analysis.  "
            "Reads quotes with theatrical relish."
        ),
    ),
    # --- American interdisciplinary panel ---
    "chen_nlp": ExpertPersona(
        name="Sarah Chen",
        role="computational_linguist",
        description=(
            "Computer scientist specialising in NLP and machine learning.  Trained in "
            "formal linguistics — PhD on prosody in spontaneous speech at MIT.  Her method "
            "is computation applied to literary prose: she would actually build a pipeline "
            "and run experiments.  Her toolkit includes: dependency parsing to expose "
            "grammatical structure (not metaphorical 'syntax'); training a classifier to "
            "distinguish narrators by sentence features; computing type-token ratios and "
            "vocabulary richness across chapters to track stylistic drift; measuring "
            "information density in dialogue vs narration; building embeddings of character "
            "speech to test whether characters are linguistically distinguishable; running "
            "sentiment trajectories across chapters and correlating them with plot events; "
            "and designing controlled experiments — 'if we shuffle the chapter order, does "
            "a language model still predict what comes next?'  She proposes analyses she "
            "would actually run and reports what the results would show.  She uses "
            "linguistic terms correctly and is mildly irritated when others use them "
            "loosely.  American."
        ),
        voice_policy=VoicePolicy(
            rate=1.01,
            energy="medium_high",
            pause_bias_ms=180,
            style="analytical_clear",
        ),
        script_description=(
            "Computer scientist and formal linguist (PhD on prosody, trained at MIT).  "
            "Notices what sentences are actually doing at the structural level — where "
            "agents disappear, where vocabulary narrows, where the prose rhythm changes.  "
            "Precise with terminology.  American, direct."
        ),
        speaking_style=(
            "Precise, direct.  Proposes specific analyses: 'if we parsed this, "
            "we would find...'  Uses linguistic terms correctly.  Will gently "
            "correct others.  Not afraid to say 'here is what the text is "
            "actually doing at the sentence level.'"
        ),
    ),
    "martinez_astro": ExpertPersona(
        name="Rebecca Martinez",
        role="observational_scientist",
        description=(
            "Observational astronomer studying protoplanetary disks and stellar formation.  "
            "Her method is systematic observation: she watches, records, looks for patterns, "
            "and tests whether those patterns are real or coincidental.  When she reads a "
            "novel, she observes: track every mention of fog and map when it appears — is "
            "there a periodicity or is it random?  Chart the chapter lengths — is there a "
            "rhythm?  Note every time a character is described by their clothing and ask "
            "whether the frequency changes.  She builds timelines and checks them for "
            "consistency.  She notices when the narrative makes testable claims — this event "
            "happens on a Tuesday, this journey takes three days — and checks whether the "
            "author kept track.  She is comfortable saying 'I looked for a pattern and "
            "there isn't one' — a null result is still a result.  What she brings is not "
            "astronomical imagery but the observer's discipline: patient, systematic "
            "attention to what is actually there, recorded and compared.  "
            "Grew up in New Mexico."
        ),
        voice_policy=VoicePolicy(
            rate=0.96,
            energy="medium",
            pause_bias_ms=250,
            style="contemplative_measured",
        ),
        script_description=(
            "Observational astronomer.  Brings a scientist's habits: notices where claims "
            "could be tested, where timelines contradict, where patterns emerge or break down.  "
            "Comfortable with uncertainty and null results.  Thoughtful, unhurried.  "
            "Grew up in New Mexico."
        ),
        speaking_style=(
            "Thoughtful, unhurried.  Proposes hypotheses and tests them.  "
            "'Let us check...'  'What would we predict?'  "
            "Comfortable with uncertainty and null results."
        ),
    ),
    "volkov_music": ExpertPersona(
        name="Elena Volkov",
        role="musicologist_and_cultural_historian",
        description=(
            "Musicologist and cultural historian, American-born of Ukrainian heritage.  "
            "Studies how music functioned as soft power during the Cold War — her research "
            "is archival: she reads the files.  Her method combines musicological formal "
            "analysis with the historian's insistence on documented evidence.  Her toolkit "
            "includes: analysing compositional form (does this novel's structure resemble "
            "sonata form, fugue, or theme-and-variation?); examining prose rhythm (cadence, "
            "tempo shifts between scenes, repetition as structural device).  But equally "
            "important is her archival instinct: she asks what a researcher would find in "
            "the relevant archives — what is in the Composers' Union files on Shostakovich, "
            "what did the State Department jazz tour memos actually say, what do the BBC "
            "programme files reveal about how literary discussion was produced.  She names "
            "specific archives, specific file series, specific dates.  When the novel "
            "depicts institutional power, she asks: what would the documents show?  "
            "What she brings is not political commentary but the combined discipline of "
            "formal analysis and archival research.  Trained at Juilliard and Columbia."
        ),
        voice_policy=VoicePolicy(
            rate=0.98,
            energy="medium",
            pause_bias_ms=210,
            style="engaged_analytical",
        ),
        script_description=(
            "Musicologist and cultural historian, American-born of Ukrainian heritage.  "
            "Attentive to structure and rhythm in prose — where scenes accelerate, where "
            "repetition accrues weight, how institutional power consumes individuals.  "
            "Sharp, politically engaged.  Trained at Juilliard and Columbia."
        ),
        speaking_style=(
            "Intellectually precise.  Names specific historical cases and dates.  "
            "Analyses prose rhythm using musical terminology.  Speaks with conviction "
            "but genuine openness to being challenged."
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
    proposed_references: list[str] = Field(
        default_factory=list,
        description=(
            "Scholarly references the expert proposed during pre-interview. "
            "Format: 'Author, Title (Year)'. Empty if tools were not used."
        ),
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
    recommended_reading: list[str] = Field(
        default_factory=list,
        description="Verified scholarly references relevant to this segment, for the host's sign-off"
    )


HOST_VOICE_POLICY = VoicePolicy(
    rate=0.98,
    energy="medium",
    pause_bias_ms=220,
    style="presenter_warm",
)
