"""LLM-bound Pydantic schemas — single source of truth.

This file holds every Pydantic class that is used as a `response_model`
for a structured-output LLM call. Co-locating them satisfies the
recommendation in docs/structured_recommendations.md to treat schema
changes as breaking API changes: a contributor can answer "which
schemas does the LLM see?" by reading one file.

Internal data classes (Passage, PodcastEpisode, EpisodeMetadata,
VoicePolicy, ExpertPersona) do NOT live here — they're not LLM-bound
and have their own files.

================================================================
CHANGELOG
================================================================

2026-05-18 (BleakHouse-gfn2 epic — schemas consolidation):
  - Initial consolidation. The classes that now live in this file
    were previously scattered across:
      * enrichment/schemas.py: FieldReportEnrichment, ParagraphEnrichment,
        ChapterEnrichmentResult (+ _StrictBase, now deleted as redundant)
      * enrichment/podcast_types.py: SegmentTemplate, Utterance, Turn,
        EpisodeSegment, SentenceType, PreInterviewResponse, HostQuestion,
        HostBrief (plus the host_prep coercion helpers)
      * enrichment/design_segments.py: SegmentDesignResult
      * enrichment/embedding_podcast.py: CuratedAssignment, CurationResult
  - schema_version = '2026-05-18' set on every class as the baseline.
  - No semantic changes to any schema in this commit; pure relocation.
  - See docs/schemas_changelog.md for the full change-management
    policy + bump rules.

================================================================
TWO-TIER SCHEMA STRATEGY (host_prep cluster only, since 2026-05-18)
================================================================

The host_prep cluster — PreInterviewResponse, HostQuestion, HostBrief —
is the source of truth for the STRICT schema. All list fields declare
min_length / max_length plus extra='forbid'. These get emitted into the
Pydantic-generated JSON Schema as `minItems`, `maxItems`, and
`additionalProperties: false`.

How each provider sees this:
  * Qwen on DeepInfra honours minItems / maxItems at decode time, so
    valid output is produced by construction. No coercion needed.
  * Anthropic's output_config rejects minItems / maxItems / etc. The
    seam's Anthropic provider (enrichment/llm/providers/
    anthropic_provider.py) denatures the schema to an allowlist of
    Anthropic-supported keys before sending. Anthropic's response may
    therefore violate the strict schema. The `@field_validator(...,
    mode='before')` coercers on each model pad/truncate any list whose
    length is outside the [min_length, max_length] band and log when
    they fire. Pydantic validation then succeeds.

Placeholder values for padding:
  * list[str] → `PLACEHOLDER_STR` ("[unspecified]")
  * list[HostQuestion] → a HostQuestion-shaped dict whose own fields
    are valid placeholder strings; constructing a real HostQuestion
    via Pydantic would re-trigger the same coercion logic.

See also docs/structured_output_review.html (Addendum 2026-05-18).
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Host-prep coercion helpers — shared by PreInterviewResponse / HostBrief /
# HostQuestion validators (see "TWO-TIER SCHEMA STRATEGY" above).
# ---------------------------------------------------------------------------


PLACEHOLDER_STR: str = "[unspecified]"
"""Padding value for list[str] coercion when an Anthropic response
violates min_length. Grep-able for forensics."""


def _placeholder_question_dict() -> dict[str, Any]:
    """Shape-only HostQuestion placeholder for HostBrief.questions padding.

    Returns a raw dict (not a HostQuestion instance) because the
    before-validator runs on the raw input — Pydantic will construct
    HostQuestion from each dict in the validated list. Each string field
    is set to PLACEHOLDER_STR; `follow_up_for` has one PLACEHOLDER_STR
    so it satisfies its own min_length=1 constraint after recursive
    HostQuestion validation."""
    return {
        "target_expert": PLACEHOLDER_STR,
        "question": PLACEHOLDER_STR,
        "intent": PLACEHOLDER_STR,
        "follow_up_for": [PLACEHOLDER_STR],
    }


def _coerce_list_to_bounds(
    v: Any, field_name: str,
    min_len: int, max_len: int,
    placeholder: Any,
) -> Any:
    """Pad/truncate a list to satisfy [min_len, max_len].

    No-ops if the value isn't a list (lets Pydantic raise a clear type
    error). Logs INFO when coercion actually fires — Qwen-side responses
    should never trigger this, so a log line is the canary.
    """
    if not isinstance(v, list):
        return v
    if len(v) > max_len:
        logger.info(
            "schema coercion: field=%r had %d items, truncated to max_length=%d",
            field_name, len(v), max_len,
        )
        v = v[:max_len]
    if len(v) < min_len:
        n_to_add = min_len - len(v)
        logger.info(
            "schema coercion: field=%r had %d items, padded with %d placeholder(s) to min_length=%d",
            field_name, len(v), n_to_add, min_len,
        )
        if callable(placeholder):
            v = list(v) + [placeholder() for _ in range(n_to_add)]
        else:
            v = list(v) + [placeholder] * n_to_add
    return v


# ===========================================================================
# Passage enrichment (task='passage_enrichment')
# ===========================================================================


class FieldReportEnrichment(BaseModel):
    """Enrichment of a single paragraph for podcast production planning.

    21 fields capturing literary signals the production pipeline reads:
    character presence, narrator, plot function, emotional register,
    themes, quotability, accessibility, plus six `prov_*` provision
    dimensions used by the transport pipeline's demand-matching.

    Numerical count caps on the list fields are deliberately not
    enforced (description-only) — see docs/schema_complexity_review.md
    for the rationale and the open question about which `prov_*`
    dimensions are still load-bearing downstream.
    """

    schema_version: ClassVar[str] = "2026-05-18"
    model_config = ConfigDict(extra="forbid")

    interest_score: int = Field(
        description="How interesting is this paragraph for a literary podcast? "
        "0=routine connective prose, 1=minor detail, 2=some interest, "
        "3=notable, 4=very interesting, 5=unmissable highlight"
    )
    interest_rationale: str = Field(
        description="One sentence explaining the interest score"
    )
    characters_present: list[str] = Field(
        description="Distinct character names mentioned or present in this "
        "paragraph. Most paragraphs have 1-3 characters; crowded scenes "
        "may reach 6-8 named individuals. Avoid listing functional "
        "referents (\"bride's aunt\") or collective type-names as "
        "separate characters. Do not list any character more than once.",
    )
    characters_speaking: list[str] = Field(
        description="Distinct character names who have direct speech in "
        "this paragraph. Most paragraphs have 1-2 speakers; very rarely "
        "more. Do not list any character more than once.",
    )
    narrator: Literal["first_person", "omniscient", "unclear"] = Field(
        description="Which narrative voice is speaking in this paragraph. "
        "'first_person' for any first-person narrator (named or "
        "unnamed). 'omniscient' for any third-person omniscient "
        "narrator. 'unclear' when the voice cannot be determined "
        "from the paragraph."
    )
    plot_function: Literal[
        "action",
        "dialogue",
        "description",
        "exposition",
        "transition",
        "digression",
        "climax",
        "revelation",
    ] = Field(description="Primary narrative function of this paragraph")
    emotional_register: list[
        Literal[
            "comic",
            "tragic",
            "suspenseful",
            "satirical",
            "tender",
            "gothic",
            "polemical",
            "pastoral",
            "neutral",
        ]
    ] = Field(
        description="Distinct emotional tones present in this paragraph. "
        "Typically 1-2; up to 4 for tonally complex paragraphs. Each "
        "tone must be different — do not repeat any register value.",
    )
    themes: list[str] = Field(
        description="Distinct theme tags genuinely present in this "
        "paragraph. A typical paragraph has 2-4 themes — only the most "
        "important. Rich paragraphs may reach 8 themes. Use short "
        "lowercase tags drawn from this novel itself; do not import "
        "themes from other novels. Each tag must be unique.",
    )
    quotability: Literal["none", "weak", "strong"] = Field(
        description="Does this paragraph contain memorable, quotable lines "
        "suitable for reading aloud on a podcast?"
    )
    best_quote: str | None = Field(
        description="The most quotable line from this paragraph, if any. "
        "Extract verbatim from the text."
    )
    accessibility: Literal["easy", "moderate", "difficult"] = Field(
        description="Can a modern listener follow this paragraph without "
        "historical context or explanation?"
    )
    summary: str = Field(
        description="1-2 sentence summary of what happens or is described"
    )
    prov_character_development: Literal["none", "weak", "strong"] = Field(
        description="Does this paragraph develop, reveal, or transform a character?"
    )
    prov_plot_advancement: Literal["none", "weak", "strong"] = Field(
        description="Does this paragraph advance the story or reveal plot information?"
    )
    prov_thematic_depth: Literal["none", "weak", "strong"] = Field(
        description="Does this paragraph engage with the novel's central "
        "themes (judge against this novel's own thematic concerns, not a "
        "generic checklist)?"
    )
    prov_social_critique: Literal["none", "weak", "strong"] = Field(
        description="Does this paragraph contain the author's commentary "
        "on society, institutions, or class — as expressed through the "
        "narration or the characters?"
    )
    prov_humor_entertainment: Literal["none", "weak", "strong"] = Field(
        description="Is this paragraph funny, entertaining, or dramatically engaging?"
    )
    prov_atmosphere_setting: Literal["none", "weak", "strong"] = Field(
        description="Does this paragraph create mood, atmosphere, or "
        "vivid setting?"
    )
    prov_narrative_technique: Literal["none", "weak", "strong"] = Field(
        description="Does this paragraph demonstrate notable literary "
        "technique (irony, foreshadowing, imagery, free indirect style, "
        "symbolism, point-of-view shift)?"
    )


class ParagraphEnrichment(BaseModel):
    """One paragraph's index + its enrichment payload."""

    schema_version: ClassVar[str] = "2026-05-18"
    model_config = ConfigDict(extra="forbid")

    paragraph_index: int = Field(
        description="The index of the paragraph in the chapter "
        "(matches [P{n}] marker)"
    )
    enrichment: FieldReportEnrichment


class ChapterEnrichmentResult(BaseModel):
    """Batch result for a chapter's worth of paragraph enrichments."""

    schema_version: ClassVar[str] = "2026-05-18"
    model_config = ConfigDict(extra="forbid")

    chapter_id: str = Field(
        description="The chapter identifier, e.g. 'c1'"
    )
    enrichments: list[ParagraphEnrichment]


# ===========================================================================
# Segment design (task='design_segments')
# ===========================================================================


class SegmentTemplate(BaseModel):
    """Producer-defined episode segment with demand profile."""

    schema_version: ClassVar[str] = "2026-05-18"
    model_config = ConfigDict(extra="forbid")

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


class SegmentDesignResult(BaseModel):
    """Wrapper for structured output: list of designed segments."""

    schema_version: ClassVar[str] = "2026-05-18"
    model_config = ConfigDict(extra="forbid")

    segments: list[SegmentTemplate] = Field(
        description="The designed episode segments (5-8 segments)"
    )


# ===========================================================================
# Phase 3 generation (task='generate_podcast')
# ===========================================================================


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

    Each utterance carries delivery annotations that the TTS renderer
    uses to control pacing, emphasis, and quote handling.
    """

    schema_version: ClassVar[str] = "2026-05-18"
    model_config = ConfigDict(extra="forbid")

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

    schema_version: ClassVar[str] = "2026-05-18"
    model_config = ConfigDict(extra="forbid")

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

    schema_version: ClassVar[str] = "2026-05-18"
    model_config = ConfigDict(extra="forbid")

    title: str
    segment_type: str
    turns: list[Turn]


# ===========================================================================
# Host prep (tasks='host_prep_pre_interview_structured', 'host_prep_brief')
# ===========================================================================


class PreInterviewResponse(BaseModel):
    """One expert's pre-interview response for a segment.

    All list fields carry min_length=1, max_length=4. See the module
    docstring's "Two-tier schema strategy" section for the design.
    Qwen-on-DeepInfra honours the constraints at decode time; Anthropic
    sees them only as field descriptions (the keys are stripped by the
    seam's allowlist filter) and may emit violations, which the
    before-validator below coerces by padding with PLACEHOLDER_STR or
    truncating.
    """

    schema_version: ClassVar[str] = "2026-05-18"
    model_config = ConfigDict(extra="forbid")

    expert_name: str = Field(description="Name of the expert interviewed")
    key_points: list[str] = Field(
        min_length=1, max_length=4,
        description="2-4 main points this expert wants to make about the segment's material",
    )
    potential_quotes: list[str] = Field(
        min_length=1, max_length=4,
        description="1-3 passages or quotes the expert would most like to read aloud",
    )
    disagreement_angles: list[str] = Field(
        min_length=1, max_length=4,
        description="Points where this expert might disagree with or challenge the others",
    )
    strongest_take: str = Field(
        default="",
        description="The single most interesting or provocative thing this expert wants to say",
    )
    proposed_references: list[str] = Field(
        min_length=1, max_length=4,
        description=(
            "Scholarly references the expert proposed during pre-interview. "
            "Format: '[ref-N]' tags from the tool conversation."
        ),
    )

    @field_validator(
        "key_points", "potential_quotes",
        "disagreement_angles", "proposed_references",
        mode="before",
    )
    @classmethod
    def _coerce_str_lists(cls, v: Any, info) -> Any:
        return _coerce_list_to_bounds(
            v, info.field_name, min_len=1, max_len=4, placeholder=PLACEHOLDER_STR,
        )


class HostQuestion(BaseModel):
    """A planned question for the host to ask during a segment.

    follow_up_for is constrained to 1-4 items per the two-tier schema
    strategy (see module docstring)."""

    schema_version: ClassVar[str] = "2026-05-18"
    model_config = ConfigDict(extra="forbid")

    target_expert: str = Field(description="Name of the expert this question is primarily directed at")
    question: str = Field(description="The question itself — conversational, not academic")
    intent: str = Field(
        description="What this question is designed to draw out "
        "(e.g. 'provoke disagreement with Blackstone', 'get Hartley to read the fog passage')"
    )
    follow_up_for: list[str] = Field(
        min_length=1, max_length=4,
        description="Other experts who might want to jump in after the target responds",
    )

    @field_validator("follow_up_for", mode="before")
    @classmethod
    def _coerce_follow_up_for(cls, v: Any, info) -> Any:
        return _coerce_list_to_bounds(
            v, info.field_name, min_len=1, max_len=4, placeholder=PLACEHOLDER_STR,
        )


class HostBrief(BaseModel):
    """The host's preparation notes for one segment.

    Per the two-tier schema strategy (see module docstring): the list
    fields carry min_length/max_length constraints that Qwen enforces
    at decode time and Anthropic responses are coerced into via the
    before-validators below. `questions` is special-cased to
    min_length=3 (other lists are 1) — three is the prose-quality
    floor we want even after Anthropic over-production is capped.
    """

    schema_version: ClassVar[str] = "2026-05-18"
    model_config = ConfigDict(extra="forbid")

    segment_name: str = Field(description="Name of the segment this brief is for")
    questions: list[HostQuestion] = Field(
        # Special case: min_length=3 (not the cluster's usual 1). A
        # one-question brief isn't a podcast segment; three is the
        # prose floor. max_length=4 still caps Anthropic over-production.
        min_length=3, max_length=4,
        description="3-4 planned questions, in suggested order",
    )
    steering_notes: str = Field(
        default="",
        description="General notes on how to steer this segment's conversation",
    )
    cross_engagement_targets: list[str] = Field(
        min_length=1, max_length=4,
        description="Specific points where experts should be encouraged to respond to each other",
    )
    recommended_reading: list[str] = Field(
        min_length=1, max_length=4,
        description="Verified scholarly references relevant to this segment, for the host's sign-off",
    )

    @field_validator("questions", mode="before")
    @classmethod
    def _coerce_questions(cls, v: Any, info) -> Any:
        return _coerce_list_to_bounds(
            v, info.field_name, min_len=3, max_len=4,
            placeholder=_placeholder_question_dict,
        )

    @field_validator(
        "cross_engagement_targets", "recommended_reading",
        mode="before",
    )
    @classmethod
    def _coerce_str_lists(cls, v: Any, info) -> Any:
        return _coerce_list_to_bounds(
            v, info.field_name, min_len=1, max_len=4, placeholder=PLACEHOLDER_STR,
        )


# ===========================================================================
# Embedding-pipeline curation (task='embedding_podcast_curate')
# ===========================================================================


class CuratedAssignment(BaseModel):
    """One passage selected and assigned by the curation LLM."""

    schema_version: ClassVar[str] = "2026-05-18"
    model_config = ConfigDict(extra="forbid")

    passage_id: str
    expert: str = Field(
        description="Expert name, or empty string '' for arc-only/structure passages"
    )
    segment_name: str = Field(description="Segment name to assign this passage to")
    dimension: str = Field(description="Primary prov_* dimension motivating selection")
    arc_name: str = Field(
        default="",
        description="Character arc name if this passage serves an arc, else empty",
    )
    assignment_type: str = Field(
        default="expert",
        description="One of: 'expert', 'arc', 'structure'",
    )
    rationale: str = Field(description="One sentence: why this passage here")


class CurationResult(BaseModel):
    """The LLM's complete curation output."""

    schema_version: ClassVar[str] = "2026-05-18"
    model_config = ConfigDict(extra="forbid")

    assignments: list[CuratedAssignment]
    strategy: str = Field(
        description="2-3 sentence summary of overall selection strategy"
    )
