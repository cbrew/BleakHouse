from hybrid_distance_crp import (
    TextSimilarityComponent,
    PositionalHybridDistanceComponent,
    TopicMatchComponent,
    hybrid_dd_crp,
)
import torch
from sentence_transformers import SentenceTransformer
import pandas as pd

# Example sentences and their positions on a timeline


sentences, positions, topics = zip(
    *[
        ("Artificial intelligence is transforming industries.", 1, "economics"),
        ("Machine learning algorithms are widely used in AI.", 1, "technology"),
        ("The stock market fluctuates based on economic factors.", 2, "economics"),
        ("Capitalism is a political philosophy.", 4, "philosophy"),
        ("Socialism is a burden on the economy.", 9, "economics"),
        ("The pelican is a large water bird.", 5, "animals"),
        ("The quick brown fox jumps over the lazy dog.", 6, "animals"),
        ("Socialism is a drag on the economy.", 7, "economics"),
        ("Speech recognition relies on neural network technology.", 6, "technology"),
        ("Conservatism is a political philosophy.", 4, "philosophy"),
        ("The bear is an undomesticated carnivorous mammal.", 10, "animals"),
        ("Socialism is a political philosophy.", 4, "philosophy"),
        ("Socialism is a blight on the economy.", 12, "economics"),
        ("Speech recognition relies on acoustic factors.", 13, "technology"),
        ("Speech recognition relies on perceptual factors.", 13, "technology"),
        ("Financial predictions rely heavily on data analysis.", 15, "technology"),
        ("The stock market fluctuates based on acoustic factors.", 16, "economics"),
        ("The lion is a beast of the savannah.", 13, "animals"),
        ("The swan is a large water bird.", 13, "animals"),
        ("A fast auburn fox leaps across a sleepy canine.", 19, "animals"),
        ("The dog is a domesticated carnivorous mammal.", 10, "animals"),
        ("The cat is a domesticated carnivorous mammal.", 10, "animals"),
        ("The wolf is an undomesticated carnivorous mammal.", 10, "animals"),
    ]
)


# Generate sentence embeddings using SentenceTransformer
model = SentenceTransformer("multi-qa-mpnet-base-cos-v1", device="mps")
embeddings = [torch.tensor(model.encode(sentence)) for sentence in sentences]

# Create components
text_similarity_component = TextSimilarityComponent(embeddings, decay_rate=1.0)
positional_component = PositionalHybridDistanceComponent(positions, kappa=1.0)
topical_component = TopicMatchComponent(topics)


# Perform hybrid DD-CRP
alpha = 1.0
temperature = 0.3
components = [text_similarity_component, positional_component, topical_component]
assignments, clusters = hybrid_dd_crp(
    sentences=sentences,
    components=components,
    component_weights=[0.1, 0.1, 0.8],
    alpha=alpha,
    temperature=temperature,
    seed=42,
)

# Output results
print("Assignments:", assignments)
print("Clusters:", clusters)
for i, cluster in enumerate(clusters):
    print(f"Cluster {i+1}:")
    for j in cluster:
        print(f"  - {sentences[j]} {positions[j]} {topics[j]}")
