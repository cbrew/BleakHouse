from typing import List, Union
from pydantic import BaseModel, Field


class LiteraryElement(BaseModel):
    pass


class KeyMoments(LiteraryElement):
    Summary: str = Field(
        ...,
        description="A compelling summary of the chapter's pivotal scenes or twists.",
    )
    Quotes: List[str] = Field(
        ..., description="Quotes from the text that illustrate the literary element."
    )


class ThemesAndAnalysis(LiteraryElement):
    Discussion: str = Field(
        ...,
        description="Major themes or messages in the chapter, explained in an engaging manner.",
    )
    Quotes: List[str] = Field(
        ..., description="Quotes from the text that illustrate the literary element."
    )


class CharacterHighlight(LiteraryElement):
    CharacterName: str = Field(..., description="Name of the character.")
    Analysis: str = Field(
        ..., description="Exploration of the character's role, growth, or complexity."
    )
    Quotes: List[str] = Field(
        ..., description="Quotes from the text that illustrate the literary element."
    )


class BehindTheScenesInsight(LiteraryElement):
    Insight: str = Field(
        ...,
        description="Imagined segment on the author's inspiration, historical context, or parallels.",
    )
    Quotes: List[str] = Field(
        ..., description="Quotes from the text that illustrate the literary element."
    )


class CrossReferences(LiteraryElement):
    SimilarWorks: List[str] = Field(
        ..., description="Other works or authors with similar themes or styles."
    )
    Connection: str = Field(
        ..., description="How these references add depth to the chapter discussion."
    )
    Quotes: List[str] = Field(
        ..., description="Quotes from the text that illustrate the literary element."
    )


class ModernRelevance(LiteraryElement):
    ContemporaryIssues: str = Field(
        ..., description="Connections to modern societal or cultural issues."
    )
    Discussion: str = Field(
        ..., description="How the chapter resonates with or critiques these issues."
    )
    Quotes: List[str] = Field(
        ..., description="Quotes from the text that illustrate the literary element."
    )


class NarrativeStructure(LiteraryElement):
    StructureElement: str = Field(
        ...,
        description="Key structural element, such as foreshadowing or a narrative twist.",
    )
    Analysis: str = Field(
        ..., description="Explanation of how the structure impacts the story."
    )
    Quotes: List[str] = Field(
        ..., description="Quotes from the text that illustrate the literary element."
    )


class LiteraryStyle(LiteraryElement):
    StylisticElement: str = Field(
        ..., description="Elements like imagery, tone, or use of metaphors."
    )
    Analysis: str = Field(
        ..., description="How the stylistic element enriches the text."
    )
    Quotes: List[str] = Field(
        ..., description="Quotes from the text that illustrate the literary element."
    )
