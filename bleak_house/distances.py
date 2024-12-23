from transformers import AutoTokenizer, AutoModel
from typing import List,Tuple,Callable
import torch
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from scipy.special import softmax

def calculate_distance_matrix_bge(sentences, model_name='BAAI/bge-base-en-v1.5'):
    """
    Calculates the pairwise cosine distance matrix for a list of sentences using BGE embeddings.

    Parameters:
        sentences (list of str): The sentences to process.
        model_name (str): The pre-trained BGE model to use.

    Returns:
        np.ndarray: A distance matrix where each entry (i, j) represents the distance between sentence i and j.
    """
    # Load tokenizer and model
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name)

    # Tokenize and encode sentences
    inputs = tokenizer(sentences, return_tensors="pt", padding=True, truncation=True)
    with torch.no_grad():
        outputs = model(**inputs)
        # Extract embeddings from the [CLS] token (first token)
        embeddings = outputs.last_hidden_state[:, 0, :].numpy()

    # Calculate cosine similarity and convert to distances
    similarity_matrix = cosine_similarity(embeddings)
    distance_matrix = 1 - similarity_matrix
    return distance_matrix


def dd_crp_with_alpha(sentences, distance_matrix, alpha=1.0,
                      decay_function=None,
                      seed:int = 17629):
    """
    Implements the Distance-Dependent Chinese Restaurant Process (dd-CRP) with a concentration parameter.

    Parameters:
        sentences (list of str): The sentences to cluster.
        distance_matrix (np.ndarray): A precomputed distance matrix (NxN) for the sentences.
        alpha (float): The concentration parameter controlling the likelihood of creating new clusters.
        decay_function (callable): A decay function for distances (e.g., exponential). If None, defaults to exponential
            decay.
        seed (int): The random seed for reproducibility.

    Returns:
        list: A list of cluster assignments for each sentence.
    """
    if decay_function is None:
        decay_function = lambda d: np.exp(-d)  # Default to exponential decay
    rng = np.random.default_rng(seed)
    num_sentences = len(sentences)
    assignments = [-1] * num_sentences  # Cluster assignments (-1 indicates unassigned)
    clusters = []  # List of clusters (each cluster is a list of sentence indices)

    for i in range(num_sentences):
        # Calculate probabilities of linking to existing points
        link_probs = []
        for j in range(i):  # Only consider previous points
            distance = distance_matrix[i, j]
            prob = decay_function(distance)
            link_probs.append(prob)
        link_probs.append(alpha)  # Add alpha as the probability for a new cluster
        link_probs = np.array(link_probs) / np.sum(link_probs)  # Normalize to make probabilities sum to 1

        # Sample a link

        sampled_index = rng.choice(len(link_probs), p=link_probs)


        if sampled_index == len(link_probs) - 1:  # New cluster
            new_cluster_id = len(clusters)
            clusters.append([i])
            assignments[i] = new_cluster_id
        else:  # Join existing cluster
            assigned_cluster = assignments[sampled_index]
            clusters[assigned_cluster].append(i)
            assignments[i] = assigned_cluster

    return assignments, clusters




def dd_crp_with_softmax(
    sentences: List[str],
    distance_matrix: np.ndarray,
    alpha: float = 1.0,
    decay_function: Callable[[float], float] = None,
    seed: int = None,
    temperature: float = 1.0
) -> Tuple[List[int], List[List[int]]]:
    """
    Implements the Distance-Dependent Chinese Restaurant Process (dd-CRP) using softmax for normalization.

    Parameters:
        sentences (list of str): The sentences to cluster.
        distance_matrix (np.ndarray): A precomputed distance matrix (NxN) for the sentences.
        alpha (float): The concentration parameter controlling the likelihood of creating new clusters.
        decay_function (callable): A decay function for distances (e.g., exponential). If None, no decay is applied.
        seed (int): Random seed for replicability.
        temperature (float): Temperature parameter for softmax scaling.

    Returns:
        tuple: (assignments, clusters)
            - assignments (list of int): Cluster assignments for each sentence.
            - clusters (list of list): A list of clusters, where each cluster is a list of sentence indices.
    """
    if decay_function is None:
        decay_function = lambda d: np.exp(-d)  # Default to exponential decay

    rng = np.random.default_rng(seed)  # Create a generator with a seed

    num_sentences = len(sentences)
    assignments = [-1] * num_sentences  # Cluster assignments (-1 indicates unassigned)
    clusters = []  # List of clusters (each cluster is a list of sentence indices)

    for i in range(num_sentences):
        # Calculate unnormalized scores for linking to existing points
        link_scores = []
        for j in range(i):  # Only consider previous points
            distance = distance_matrix[i, j]
            score = decay_function(distance)
            link_scores.append(score)
        link_scores.append(alpha)  # Add alpha as the score for a new cluster

        # Apply softmax with temperature scaling
        link_probs = softmax(np.array(link_scores) / temperature)

        # Sample a link using the generator
        sampled_index = rng.choice(len(link_probs), p=link_probs)

        if sampled_index == len(link_probs) - 1:  # New cluster
            new_cluster_id = len(clusters)
            clusters.append([i])
            assignments[i] = new_cluster_id
        else:  # Join existing cluster
            assigned_cluster = assignments[sampled_index]
            clusters[assigned_cluster].append(i)
            assignments[i] = assigned_cluster

    return assignments, clusters
