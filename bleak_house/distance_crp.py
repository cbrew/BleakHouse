import numpy as np
from scipy.special import softmax
from typing import Callable, List, Tuple

# Decay Functions
def exponential_decay(distance: float) -> float:
    """Exponential decay: f(d) = exp(-d)."""
    return np.exp(-distance)

def window_decay(distance: float, delta: float = 1.0) -> float:
    """Window decay: f(d) = 1 if d <= delta, else 0."""
    return 1.0 if distance <= delta else 0.0

def logistic_decay(distance: float, mu: float = 1.0, kappa: float = 1.0) -> float:
    """Logistic decay: f(d) = 1 / (1 + exp(kappa * (d - mu)))."""
    return 1.0 / (1.0 + np.exp(kappa * (distance - mu)))

# Distance computation
def compute_distance(embedding1: np.ndarray, embedding2: np.ndarray) -> float:
    """Computes the Euclidean distance between two embeddings."""
    return np.linalg.norm(embedding1 - embedding2)

# Streaming dd-CRP
def dd_crp_streaming_with_decay(
    sentences: List[str],
    embedder,  # A function or model to generate embeddings (e.g., from BGE or SentenceTransformer)
    alpha: float = 1.0,
    decay_function: Callable[[float], float] = exponential_decay,  # Default to exponential decay
    seed: int = None,
    temperature: float = 1.0,
    decay_params: dict = None  # Optional parameters for the decay function
) -> Tuple[List[int], List[List[int]]]:
    """
    Implements a streaming Distance-Dependent Chinese Restaurant Process (dd-CRP) with customizable decay functions.

    Parameters:
        sentences (list of str): The sentences to cluster.
        embedder (callable): A function that takes a list of sentences and returns their embeddings.
        alpha (float): The concentration parameter controlling the likelihood of creating new clusters.
        decay_function (callable): A callable decay function for distances.
        seed (int): Random seed for replicability.
        temperature (float): Temperature parameter for softmax scaling.
        decay_params (dict): Optional parameters for the decay function.

    Returns:
        tuple: (assignments, clusters)
            - assignments (list of int): Cluster assignments for each sentence.
            - clusters (list of list): A list of clusters, where each cluster is a list of sentence indices.
    """
    if decay_params is None:
        decay_params = {}

    rng = np.random.default_rng(seed)  # Create a generator with a seed
    embeddings = []  # Store embeddings for processed sentences
    assignments = []  # Cluster assignments
    clusters = []  # List of clusters (each cluster is a list of sentence indices)

    for i, sentence in enumerate(sentences):
        # Generate embedding for the current sentence
        current_embedding = embedder([sentence])[0]

        # Compute distances to all previous embeddings
        link_scores = []
        for j, embedding in enumerate(embeddings):
            distance = compute_distance(current_embedding, embedding)
            score = decay_function(distance, **decay_params)  # Pass optional params to the decay function
            link_scores.append(score)

        # Add alpha as the score for creating a new cluster
        link_scores.append(alpha)

        # Apply softmax with temperature scaling
        link_probs = softmax(np.array(link_scores) / temperature)

        # Sample a link using the generator
        sampled_index = rng.choice(len(link_probs), p=link_probs)

        if sampled_index == len(link_probs) - 1:  # New cluster
            new_cluster_id = len(clusters)
            clusters.append([i])
            assignments.append(new_cluster_id)
        else:  # Join existing cluster
            assigned_cluster = assignments[sampled_index]
            clusters[assigned_cluster].append(i)
            assignments.append(assigned_cluster)

        # Store the embedding of the current sentence
        embeddings.append(current_embedding)

    return assignments, clusters
