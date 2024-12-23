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


class ChapterSchema(BaseModel):
    Title: str = Field(..., description="The title of the chapter.")
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
    ] = Field(..., description="List of literary elements associated with the chapter.")
