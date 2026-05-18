from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _StrictBase(BaseModel):
    # extra='forbid' produces `additionalProperties: false` in the
    # generated JSON Schema (Anthropic and OpenAI strict-mode both
    # require this) AND rejects unknown fields at Python validation
    # time. The earlier `json_schema_extra={"additionalProperties":
    # False}` form only set the JSON Schema key — Pydantic itself
    # silently accepted hallucinated extras. Migrated 2026-05-18 per
    # BleakHouse-vyo4.
    model_config = ConfigDict(extra="forbid")


class FieldReportEnrichment(_StrictBase):
    """Enrichment of a single paragraph for podcast production planning."""

    interest_score: int = Field(
        description="How interesting is this paragraph for a literary podcast? "
        "0=routine connective prose, 1=minor detail, 2=some interest, "
        "3=notable, 4=very interesting, 5=unmissable highlight"
    )
    interest_rationale: str = Field(
        description="One sentence explaining the interest score"
    )
    # Numerical caps deliberately NOT enforced at schema or Pydantic
    # level (per 2026-05-13 user direction: "make the schema liberal
    # but add recommendations in the prompt"). Description text carries
    # the count guidance; the model treats it as advisory. Provider
    # constraints like JSON Schema maxItems would be the only way to
    # decode-time enforce caps, but Anthropic rejects maxItems and the
    # benefit on other providers is marginal vs the complexity cost.
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


class ParagraphEnrichment(_StrictBase):
    paragraph_index: int = Field(
        description="The index of the paragraph in the chapter "
        "(matches [P{n}] marker)"
    )
    enrichment: FieldReportEnrichment


class ChapterEnrichmentResult(_StrictBase):
    chapter_id: str = Field(
        description="The chapter identifier, e.g. 'c1'"
    )
    enrichments: list[ParagraphEnrichment]


class Passage(BaseModel):
    passage_id: str = Field(description="e.g. 'c1:p7'")
    chapter_id: str
    chapter_title: str
    paragraph_index: int
    char_start: int
    char_end: int
    text: str
    enrichment: FieldReportEnrichment | None = None
    context: str | None = None
    literary_element_ids: list[str] = Field(default_factory=list)
