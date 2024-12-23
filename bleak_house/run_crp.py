from typing import Tuple, List, Any, Dict, Optional
from collections import Counter

import pandas as pd
from sentence_transformers import SentenceTransformer
from crp.core_crp import dd_crp_with_hybrid_distance
from crp.dataset_generator import generate_dickensian_sentences
from crp.scoring import cluster_scores
from crp.decay_functions import torch_exponential_decay


def encode_sentences(sentences):
    model = SentenceTransformer("BAAI/bge-large-en-v1.5")
    embeddings = model.encode(sentences, convert_to_tensor=True)
    return embeddings


def generate_sentences(
    num_sentences: int = 100, num_chapters: int = 10, seed: int = 42
) -> Tuple[List[str], List[int]]:
    sentences, chapters = generate_dickensian_sentences(
        num_sentences, num_chapters, seed=seed
    )
    return sentences, chapters


def display_dataset(sentences: List[str], chapters: list[int]) -> None:
    book = pd.DataFrame({"Chapter": chapters, "Sentence": sentences})
    for sentence, grouped in book.groupby("Sentence"):
        print(f"{sentence}")
        counter = Counter(int(x) for x in grouped["Chapter"].values)
        for chapter, count in counter.items():
            print(f"    - Chapter {chapter}: {count} occurrences")


def display_clusters(
    sentences: List[str], chapters: List[int], clusters: List[List[int]]
) -> None:
    print("\nCluster Assignments:")
    for idx, cluster in enumerate(clusters):
        # Sort sentences within each cluster by chapter
        sorted_cluster = sorted(cluster, key=lambda i: chapters[i])
        print(f"Cluster {idx + 1}:")
        for sentence_idx in sorted_cluster:
            print(f"  - Chapter {chapters[sentence_idx]}: {sentences[sentence_idx]}")


def score_clusters(
    sentences,
    chapters,
    clusters,
    embeddings,
    alpha_text,
    alpha,
    temperature,
    decay_params,
) -> pd.DataFrame:
    max_chapter = max(chapters)
    min_chapter = min(chapters)
    df_scores = cluster_scores(
        clusters,
        sentences,
        chapters,
        embeddings,
        alpha_text,
        max_chapter,
        min_chapter,
        alpha,
        temperature,
        decay_params,
    )
    return df_scores


def main(
    alpha: float,  # Likelihood of starting a new cluster
    alpha_text: float = 0.75,  # Weight for text similarity in hybrid distance
    temperature: float = 1.0,  # Softmax temperature
    decay_function=torch_exponential_decay,
    decay_params: Optional[Dict[str, Any]] = None,
    seed: int = 17629,
    num_sentences: int = 600,
    num_chapters: int = 70,
) -> None:
    # Generate dataset

    if decay_params is None:
        decay_params = {"decay_rate": 0.05}

    sentences, chapters = generate_sentences(num_sentences, num_chapters, seed=42)
    display_dataset(sentences, chapters)
    embeddings = encode_sentences(sentences)

    # CRP parameters

    # Run the Distance-Dependent Chinese Restaurant Process (dd-CRP)
    assignments, clusters = dd_crp_with_hybrid_distance(
        sentences,
        chapters,
        embeddings,
        alpha,
        temperature,
        alpha_text,
        seed=seed,
        decay_function=decay_function,
        decay_params=decay_params,
    )
    display_clusters(sentences, chapters, clusters)
    return score_clusters(
        sentences,
        chapters,
        clusters,
        embeddings,
        alpha_text,
        alpha,
        temperature,
        decay_params,
    )


if __name__ == "__main__":
    alpha = 4.0  # Likelihood of starting a new cluster
    alpha_text = 0.75  # Weight for text similarity in hybrid distance
    temperature = 1.0  # Softmax temperature
    decay_function = torch_exponential_decay
    decay_params = {"decay_rate": 0.05}
    seed = 17629
    main(
        alpha=alpha,
        alpha_text=alpha_text,
        temperature=temperature,
        decay_function=decay_function,
        decay_params=decay_params,
        num_sentences=800,
        num_chapters=70,
        seed=seed,
    ).to_json("cluster_scores.json", orient="records")
