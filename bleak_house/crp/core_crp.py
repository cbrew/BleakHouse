import torch
from torch.nn.functional import softmax
from typing import List, Tuple, Callable
from crp.hybrid_distance import compute_hybrid_distance


def dd_crp_with_hybrid_distance(
    sentences: List[str],
    chapters: List[int],
    embeddings: List[torch.Tensor],
    alpha: float,
    temperature: float,
    alpha_text: float,
    seed: int = 42,
    decay_function: Callable[[float], float] = None,
    decay_params: dict = None,
) -> Tuple[List[int], List[List[int]]]:
    """
    Distance-Dependent CRP using hybrid distance.

    Parameters:
        sentences: List of sentences.
        chapters: Corresponding chapter numbers.
        embeddings: List of precomputed embeddings.
        alpha: Weight for starting a new cluster.
        temperature: Softmax temperature.
        alpha_text: Weight for text similarity in hybrid distance.

    Returns:
        Cluster assignments and cluster groups.
    """

    if decay_function is None:
        raise ValueError("A decay function must be provided.")
    if decay_params is None:
        decay_params = {}

    assignments = []
    clusters = []
    max_chapter = max(chapters)
    min_chapter = min(chapters)

    for i, (current_embedding, current_chapter) in enumerate(zip(embeddings, chapters)):
        link_scores = []

        if i > 0:
            for j in range(i):
                prev_embedding = embeddings[j]
                prev_chapter = chapters[j]
                dist, _, _ = compute_hybrid_distance(
                    current_embedding,
                    prev_embedding,
                    current_chapter,
                    prev_chapter,
                    max_chapter,
                    min_chapter,
                    alpha_text,
                )
                # Apply decay function to the distance
                link_scores.append(dist)
        link_scores.append(alpha)
        link_scores = decay_function(torch.tensor(link_scores), **decay_params)
        link_probs = softmax(link_scores / temperature, dim=0)
        sampled_index = torch.multinomial(link_probs, 1).item()

        if sampled_index == len(link_probs) - 1:
            cluster_id = len(clusters)
            clusters.append([i])
            assignments.append(cluster_id)
        else:
            cluster_id = assignments[sampled_index]
            clusters[cluster_id].append(i)
            assignments.append(cluster_id)

    return assignments, clusters
