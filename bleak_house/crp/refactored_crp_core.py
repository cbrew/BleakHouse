"""
Module for performing Distance-Dependent Chinese Restaurant Process (DD-CRP) with a hybrid distance metric.

This module provides:
    - Computation of hybrid distance matrices combining text similarity and generic object proximity.
    - A pipeline for clustering sentences using a distance-dependent CRP algorithm.

Functions:
    - _compute_distance_matrix: Computes a pairwise hybrid distance matrix.
    - _prepare_distance_matrix: Prepares the distance matrix and object range.
    - _dd_crp_with_hybrid_distance: Performs DD-CRP clustering using a precomputed distance matrix.
    - hybrid_dd_crp: Top-level procedure combining distance computation and DD-CRP clustering.

Usage:
    Call `hybrid_dd_crp` with sentences, object information, embeddings, and parameters to compute clusters.
"""

import torch
from typing import List, Callable, Tuple, TypeVar

# Define a type variable for the object type
O = TypeVar("O")


def compute_distance_matrix(
    embeddings: torch.Tensor,
    objects: List[O],
    object_distance_function: Callable[[List[O], List[O]], torch.Tensor],
    alpha_text: float,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """
    Compute the pairwise hybrid distance matrix for embeddings and objects.

    Parameters:
        embeddings: Tensor of precomputed embeddings (n_samples x embedding_dim).
        objects: Arbitrary objects for computing distances.
        object_distance_function: Callable to compute pairwise object distances.
        alpha_text: Weight for text similarity in hybrid distance.

    Returns:
        A symmetric matrix of hybrid distances.
    """
    # Compute cosine similarity for all pairs
    cosine_similarity_matrix = torch.mm(embeddings, embeddings.t())
    text_distance_matrix = 1 - cosine_similarity_matrix

    # Compute object distance matrix using the provided function
    object_distance_matrix = object_distance_function(objects, objects)

    # Compute hybrid distance matrix
    hybrid_distance_matrix = (
        alpha_text * text_distance_matrix + (1 - alpha_text) * object_distance_matrix
    )

    return hybrid_distance_matrix, text_distance_matrix, object_distance_matrix


def _dd_crp_with_hybrid_distance(
    sentences: List[str],
    distance_matrix: torch.Tensor,
    alpha: float,
    temperature: float,
    seed: int = 42,
    decay_function: Callable[[torch.Tensor, ...], torch.Tensor] = None,
    decay_params: dict = None,
) -> Tuple[List[int], List[List[int]]]:
    """
    Distance-Dependent CRP using precomputed hybrid distance matrices.

    Parameters:
        sentences: List of sentences.
        distance_matrix: Precomputed distance matrix (n_samples x n_samples).
        alpha: Weight for starting a new cluster.
        temperature: Softmax temperature.

    Returns:
        Cluster assignments and cluster groups.
    """
    if decay_function is None:
        raise ValueError("A decay function must be provided.")
    if decay_params is None:
        decay_params = {}

    torch.manual_seed(seed)

    assignments = []
    clusters = []

    for i in range(len(sentences)):
        link_scores = []

        if i > 0:
            link_scores = distance_matrix[i, :i].tolist()

        # Apply decay function
        link_scores = torch.tensor(link_scores)
        link_scores = decay_function(link_scores, **decay_params).tolist()
        # Add alpha for new cluster creation
        link_scores.append(alpha)
        link_scores = torch.tensor(link_scores)

        # Compute probabilities with softmax
        link_probs = torch.softmax(link_scores / temperature, dim=0)

        # Sample a cluster assignment
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


def hybrid_dd_crp(
    sentences: List[str],
    objects: List,
    embeddings: torch.Tensor,
    object_distance_function: Callable[[List, List], torch.Tensor],
    alpha_text: float,
    alpha: float,
    temperature: float,
    seed: int = 42,
    decay_function: Callable[[torch.Tensor, ...], torch.Tensor] = None,
    decay_params: dict = None,
) -> Tuple[List[int], List[List[int]]]:
    """
    Top-level procedure to compute distance matrix and perform CRP.

    Parameters:
        sentences: List of sentences.
        objects: Arbitrary objects for computing distances.
        embeddings: Tensor of precomputed embeddings (n_samples x embedding_dim).
        object_distance_function: Callable to compute pairwise object distances.
        alpha_text: Weight for text similarity in hybrid distance.
        alpha: Weight for starting a new cluster.
        temperature: Softmax temperature.
        seed: Random seed.
        decay_function: Function to apply decay to distances.
        decay_params: Parameters for the decay function.

    Returns:
        Cluster assignments and cluster groups.
    """
    # Compute distance matrix
    distance_matrix, _, _ = compute_distance_matrix(
        embeddings, objects, object_distance_function, alpha_text
    )

    # Perform CRP
    return _dd_crp_with_hybrid_distance(
        sentences,
        distance_matrix,
        alpha,
        temperature,
        seed,
        decay_function,
        decay_params,
    )
