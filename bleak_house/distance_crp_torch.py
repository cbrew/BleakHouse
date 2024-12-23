import torch
from torch.nn.functional import softmax
from sentence_transformers import SentenceTransformer
from typing import Callable, List, Tuple, Dict


def dd_crp(
    sentences: List[str],
    model: SentenceTransformer,
    alpha: float = 1.0,
    decay_function: Callable[[torch.Tensor, Dict[str, float]], torch.Tensor] = None,
    seed: int = None,
    temperature: float = 1.0,
    decay_params: Dict[str, float] = None,
    batch_size: int = 32
) -> Tuple[List[int], List[List[int]]]:
    """
    Implements a Distance-Dependent Chinese Restaurant Process (dd-CRP) using PyTorch tensors.

    Parameters:
        sentences (List[str]): Sentences to cluster.
        model (SentenceTransformer): Pretrained SentenceTransformer model.
        alpha (float): Concentration parameter for starting a new cluster.
        decay_function (Callable): Function to apply a decay to distances. Must accept a tensor of distances and a dictionary of parameters.
        seed (int): Random seed for replicability.
        temperature (float): Temperature parameter for softmax scaling.
        decay_params (Dict[str, float]): Parameters for the decay function.
        batch_size (int): Batch size for encoding sentences.

    Returns:
        Tuple[List[int], List[List[int]]]:
            - List[int]: Cluster assignments for each sentence.
            - List[List[int]]: Groups of clusters, each containing sentence indices.
    """
    if decay_function is None:
        raise ValueError("A decay function must be provided.")
    if not callable(decay_function):
        raise ValueError("The decay function must be callable.")
    if decay_params is None:
        decay_params = {}

    # Set the random seed for PyTorch
    if seed is not None:
        torch.manual_seed(seed)

    # Initialize variables
    embeddings: List[torch.Tensor] = []  # List of sentence embeddings
    assignments: List[int] = []  # Cluster assignments
    clusters: List[List[int]] = []  # Clustered groups

    # Encode sentences in batches
    sentence_embeddings = model.encode(sentences, convert_to_tensor=True, batch_size=batch_size)

    # Iterate through each sentence
    for i, current_embedding in enumerate(sentence_embeddings):
        # Compute similarity and distances
        link_scores: List[float] = []
        if embeddings:  # Only compute if there are previous embeddings
            all_embeddings = torch.stack(embeddings)  # Combine previous embeddings into a tensor
            similarities = torch.nn.functional.cosine_similarity(
                current_embedding.unsqueeze(0), all_embeddings, dim=1
            )  # Compute cosine similarity
            distances = 1 - similarities  # Convert similarity to distance
            link_scores = decay_function(distances, **decay_params).tolist()  # Apply decay

        # Add score for starting a new cluster
        link_scores.append(alpha)

        # Apply softmax for probabilistic sampling
        link_probs = softmax(torch.tensor(link_scores) / temperature, dim=0)

        # Sample a cluster
        sampled_index = torch.multinomial(link_probs, 1).item()

        # Assign to a cluster or create a new one
        if sampled_index == len(link_probs) - 1:  # Start a new cluster
            new_cluster_id = len(clusters)
            clusters.append([i])
            assignments.append(new_cluster_id)
        else:  # Join an existing cluster
            assigned_cluster = assignments[sampled_index]
            clusters[assigned_cluster].append(i)
            assignments.append(assigned_cluster)

        # Store the embedding of the current sentence
        embeddings.append(current_embedding)

    return assignments, clusters

