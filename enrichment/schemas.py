from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _StrictBase(BaseModel):
    model_config = ConfigDict(json_schema_extra={"additionalProperties": False})


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
    characters_present: list[str] = Field(
        description="Character names mentioned or present in this paragraph"
    )
    characters_speaking: list[str] = Field(
        description="Character names who have direct speech in this paragraph"
    )
    narrator: Literal["esther", "omniscient", "unclear"] = Field(
        description="Which narrative voice: Esther Summerson's first-person "
        "narration, the omniscient third-person narrator, or unclear"
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
        description="Emotional tones present in this paragraph (may be multiple)"
    )
    themes: list[str] = Field(
        description="Theme tags present, e.g. 'law', 'poverty', 'identity', "
        "'class', 'family', 'duty', 'corruption'. Use short lowercase tags."
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
        description="Does this paragraph engage with the novel's themes "
        "(justice, identity, class, institutional failure)?"
    )
    prov_social_critique: Literal["none", "weak", "strong"] = Field(
        description="Does this paragraph contain Dickens' commentary on "
        "Victorian society, law, poverty, or institutions?"
    )
    prov_humor_entertainment: Literal["none", "weak", "strong"] = Field(
        description="Is this paragraph funny, entertaining, or dramatically engaging?"
    )
    prov_atmosphere_setting: Literal["none", "weak", "strong"] = Field(
        description="Does this paragraph create mood, atmosphere, or vivid setting "
        "(fog, Gothic, London, Chesney Wold)?"
    )
    prov_narrative_technique: Literal["none", "weak", "strong"] = Field(
        description="Does this paragraph demonstrate notable literary technique "
        "(irony, foreshadowing, imagery, dual narration, symbolism)?"
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
