"""In-memory episode containers.

Three pieces:
  EpisodeMetadata  — provenance and coverage information
  PodcastEpisode   — top-level container wrapping a list of segments
  fix_turn_roles   — post-generation helper that normalises
                     LLM-emitted role labels against the canonical
                     persona roles

These live separately from `enrichment/personas.py` (which holds the
persona/voice configuration the LLM is briefed with) and from
`enrichment/llm/schemas.py` (which holds the schemas the LLM produces).

History note: these were in `enrichment/podcast_types.py` until
2026-05-18, when that file was retired under BleakHouse-gfn2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from enrichment.llm.schemas import EpisodeSegment

if TYPE_CHECKING:
    from enrichment.personas import ExpertPersona


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


def fix_turn_roles(
    episode_dict: dict,
    personas: "list[ExpertPersona]",
) -> dict:
    """Overwrite each turn's ``role`` field with the persona's canonical role.

    The LLM sometimes invents roles like ``close_reader`` or ``social_historian``
    instead of using the persona's actual role. This fixes them in-place.
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
