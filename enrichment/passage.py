"""Passage data class — internal pipeline structure.

NOT an LLM-bound schema. A Passage is a chunk of novel text plus
its (optional) enrichment payload and context. Used as the unit of
passage selection (Phase 1) and as the join key for assignment
back to segments (Phase 2).

LLM-bound schemas live in `enrichment/llm/schemas.py`. This file
exists because Passage is structural data, not a model response,
and grouping it with the LLM schemas would mislead readers about
its provenance.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from enrichment.llm.schemas import FieldReportEnrichment


class Passage(BaseModel):
    """A passage of novel text with optional enrichment and context."""

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
