import torch
from typing import Tuple


def compute_hybrid_distance(
    embedding1: torch.Tensor,
    embedding2: torch.Tensor,
    chapter1: int,
    chapter2: int,
    alpha_text: float,
    max_chapter: int,
    min_chapter: int
) -> Tuple[float, float, float]:
    """
    Compute normalized text distance, normalized chapter distance, and hybrid distance.

    Parameters:
        embedding1: Embedding of the first sentence.
        embedding2: Embedding of the second sentence.
        chapter1: Chapter number of the first sentence.
        chapter2: Chapter number of the second sentence.
        alpha_text: Weight for text similarity in the hybrid distance.
        max_chapter: Maximum chapter number for normalization.
        min_chapter: Minimum chapter number for normalization.

    Returns:
        Tuple[float, float, float]: Normalized text distance, normalized chapter distance, and hybrid distance.
    """
    # Text distance (normalized to [0, 1])
    text_similarity = torch.nn.functional.cosine_similarity(
        embedding1.unsqueeze(0), embedding2.unsqueeze(0)
    ).item()
    text_distance = 1 - text_similarity  # Cosine distance

    # Chapter distance (normalized to [0, 1])
    chapter_distance = abs(chapter1 - chapter2) / (max_chapter - min_chapter)

    # Hybrid distance
    hybrid_distance = alpha_text * text_distance + (1 - alpha_text) * chapter_distance

    return text_distance, chapter_distance, hybrid_distance




def hybrid_distance(
    embedding1: torch.Tensor,
    embedding2: torch.Tensor,
    chapter1: int,
    chapter2: int,
    max_chapter: int,
    min_chapter: int,
    alpha: float = 0.7
) -> float:
    text_similarity = 1 - torch.nn.functional.cosine_similarity(embedding1.unsqueeze(0), embedding2.unsqueeze(0)).item()
    chapter_distance = abs(chapter1 - chapter2)
    normalized_chapter_distance = chapter_distance / (max_chapter - min_chapter)
    return alpha * text_similarity + (1 - alpha) * normalized_chapter_distance
