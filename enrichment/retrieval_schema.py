"""LanceDB schema for contextual passage embeddings."""

from lancedb.embeddings import get_registry
from lancedb.pydantic import LanceModel, Vector

embedding_model = get_registry().get("openai").create(name="text-embedding-3-small")


class ContextualPassage(LanceModel):
    """A passage with contextual retrieval metadata, embedded for vector search."""

    passage_id: str
    chapter_id: str
    chapter_title: str
    paragraph_index: int
    narrator: str
    interest_score: int
    themes: str
    characters: str
    summary: str
    text: str
    context: str
    embedding_input: str = embedding_model.SourceField()
    vector: Vector(dim=embedding_model.ndims()) = embedding_model.VectorField()  # type: ignore[valid-type]
