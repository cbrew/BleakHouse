from sentence_transformers import SentenceTransformer
from crp.core_crp import dd_crp_with_hybrid_distance
from crp.dataset_generator import generate_dickensian_sentences
from crp.scoring import cluster_scores
import pandas as pd
from collections import Counter

from crp.decay_functions import torch_exponential_decay

if __name__ == "__main__":
    # Initialize SentenceTransformer model
    model = SentenceTransformer("BAAI/bge-large-en-v1.5")

    # Generate dataset
    num_sentences = 600
    num_chapters = 70
    sentences, chapters = generate_dickensian_sentences(
        num_sentences, num_chapters, seed=42
    )

    book = pd.DataFrame({"Chapter": chapters, "Sentence": sentences})
    for sentence, grouped in book.groupby("Sentence"):
        print(f"{sentence}")
        counter = Counter(int(x) for x in grouped["Chapter"].values)
        for chapter, count in counter.items():
            print(f"    - Chapter {chapter}: {count} occurrences")

    # Encode sentences into embeddings
    embeddings = model.encode(sentences, convert_to_tensor=True)

    # CRP parameters
    alpha = 3.0  # Likelihood of starting a new cluster
    alpha_text = 0.5  # Weight for text similarity in hybrid distance
    temperature = 1.0  # Softmax temperature
    decay_function = torch_exponential_decay
    decay_params = {"decay_rate": 0.10}
    seed = 17629

    # Run the Distance-Dependent Chinese Restaurant Process (dd-CRP)
    assignments, clusters = dd_crp_with_hybrid_distance(
        sentences,
        chapters,
        embeddings,
        alpha,
        temperature,
        alpha_text,
        seed=seed,
        decay_function=torch_exponential_decay,
        decay_params=decay_params,
    )

    # Display results: clusters sorted by chapter
    print("\nCluster Assignments:")
    for idx, cluster in enumerate(clusters):
        # Sort sentences within each cluster by chapter
        sorted_cluster = sorted(cluster, key=lambda i: chapters[i])
        print(f"Cluster {idx + 1}:")
        for sentence_idx in sorted_cluster:
            print(f"  - Chapter {chapters[sentence_idx]}: {sentences[sentence_idx]}")

    # Calculate and display cluster scores
    print("\nCalculating cluster scores...")
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

    print("\nSaving cluster Scores:")
    df_scores.to_json("cluster_scores.json", indent=4)
    print("Scores written to cluster_scores.json")
