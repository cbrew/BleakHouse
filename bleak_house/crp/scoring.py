import pandas as pd
import torch
from typing import List, Dict, Any
from crp.hybrid_distance import compute_hybrid_distance


def cluster_scores(
    clusters: List[List[int]],
    sentences: List[str],
    chapters: List[int],
    embeddings: List[torch.Tensor],
    alpha_text: float,
    max_chapter: int,
    min_chapter: int,
    alpha: float,
    temperature: float,
    decay_params: Dict[str, Any],
) -> pd.DataFrame:
    """
    Compute the hybrid cluster score for each member of a cluster.

    Parameters:
        clusters: List of clusters, each containing indices of the sentences.
        sentences: List of all sentences.
        chapters: List of chapter numbers for each sentence.
        embeddings: List of sentence embeddings.
        alpha_text: Weight for text similarity in the hybrid distance.
        max_chapter: Maximum chapter number for normalization.
        min_chapter: Minimum chapter number for normalization.
        alpha: Likelihood of starting a new cluster.
        temperature: Softmax temperature.
        decay_params: Parameters for the decay function.

    Returns:
        pd.DataFrame: A DataFrame with columns:
            - "Cluster": Cluster ID.
            - "Sentence": The sentence.
            - "Chapter": Chapter number of the sentence.
            - "Closest Partner": Closest sentence within the cluster.
            - "Closest Chapter": Chapter number of the closest partner.
            - "Normalized Text Distance": The normalized text-based distance.
            - "Normalized Chapter Distance": The normalized chapter-based distance.
            - "Hybrid Distance": The hybrid distance.
            - Additional columns for each decay function parameter.
    """
    records = []

    for cluster_id, cluster in enumerate(clusters):
        for i in cluster:
            current_sentence = sentences[i]
            current_embedding = embeddings[i]
            current_chapter = chapters[i]

            # Initialize minimum distances
            min_hybrid_distance = float("inf")
            closest_partner = None
            closest_chapter = None
            normalized_text_distance = None
            normalized_chapter_distance = None

            # Compare with other members in the cluster
            for j in cluster:
                if i == j:  # Skip self-comparison
                    continue

                partner_sentence = sentences[j]
                partner_embedding = embeddings[j]
                partner_chapter = chapters[j]

                # Use refactored compute_hybrid_distance
                text_distance, chapter_distance, hybrid_dist = compute_hybrid_distance(
                    current_embedding,
                    partner_embedding,
                    current_chapter,
                    partner_chapter,
                    alpha_text,
                    max_chapter,
                    min_chapter,
                )

                # Update closest partner if a smaller hybrid distance is found
                if hybrid_dist < min_hybrid_distance:
                    min_hybrid_distance = hybrid_dist
                    closest_partner = partner_sentence
                    closest_chapter = partner_chapter
                    normalized_text_distance = text_distance
                    normalized_chapter_distance = chapter_distance

            # Record data for this sentence
            record = {
                "Cluster": cluster_id + 1,
                "Sentence": current_sentence,
                "Chapter": current_chapter,
                "Closest Partner": closest_partner,
                "Closest Chapter": closest_chapter,
                "Normalized Text Distance": normalized_text_distance,
                "Normalized Chapter Distance": normalized_chapter_distance,
                "Hybrid Distance": min_hybrid_distance,
                "Alpha": alpha,
                "Temperature": temperature,
                "Alpha Text": alpha_text,
                "Max Chapter": max_chapter,
                "Min Chapter": min_chapter,
            }

            # Add decay function parameters
            for param_name, param_value in decay_params.items():
                record[param_name] = param_value

            records.append(record)

    # Create a DataFrame from the records
    return pd.DataFrame.from_records(records).fillna(0.0)
