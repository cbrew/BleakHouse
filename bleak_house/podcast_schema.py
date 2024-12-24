from typing import List, Union
from pydantic import BaseModel, Field
from bleak_house.literary_elements import (
    KeyMoments,
    ThemesAndAnalysis,
    CharacterHighlight,
    BehindTheScenesInsight,
    CrossReferences,
    ModernRelevance,
    NarrativeStructure,
    LiteraryStyle,
)


class Segment(BaseModel):
    Title: str = Field(..., description="The title of the segment.")
    LiteraryElements: List[
        Union[
            KeyMoments,
            ThemesAndAnalysis,
            CharacterHighlight,
            BehindTheScenesInsight,
            CrossReferences,
            ModernRelevance,
            NarrativeStructure,
            LiteraryStyle,
        ]
    ] = Field(
        ..., description="A list of literary elements associated with the segment."
    )


class PodcastScript(BaseModel):
    Title: str = Field(..., description="The title of the podcast script.")
    Segments: List[Segment] = Field(
        ..., description="The list of segments that make up the podcast script."
    )
