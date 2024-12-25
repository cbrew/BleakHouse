from sentence_transformers import SentenceTransformer
import torch
from hybrid_distance_crp import hybrid_dd_crp
from decay_functions import torch_exponential_decay

# Example sentences
sentences, objects = zip(
    *[
        ("Artificial intelligence is transforming industries.", "finance"),
        ("Machine learning algorithms are widely used in AI.", "technology"),
        ("The stock market fluctuates based on economic factors.", "finance"),
        ("Capitalism is a political philosophy.", "philosophy"),
        ("Socialism is a burden on the economy.", "finance"),
        ("The pelican is a large water bird.", "animals"),
        ("The quick brown fox jumps over the lazy dog.", "animals"),
        ("Socialism is a drag on the economy.", "finance"),
        ("Speech recognition relies on neural network technology.", "technology"),
        ("Conservatism is a political philosophy.", "philosophy"),
        ("The bear is an undomesticated carnivorous mammal.", "animals"),
        ("Socialism is a political philosophy.", "philosophy"),
        ("Socialism is a blight on the economy.", "finance"),
        ("Speech recognition relies on acoustic factors.", "technology"),
        ("Speech recognition relies on perceptual factors.", "technology"),
        ("Financial predictions rely heavily on data analysis.", "finance"),
        ("The stock market fluctuates based on acoustic factors.", "finance"),
        ("The lion is a beast of the savannah.", "animals"),
        ("The swan is a large water bird.", "animals"),
        ("A fast auburn fox leaps across a sleepy canine.", "animals"),
        ("The dog is a domesticated carnivorous mammal.", "animals"),
        ("The cat is a domesticated carnivorous mammal.", "animals"),
        ("The wolf is an undomesticated carnivorous mammal.", "animals"),
    ]
)


# Generate embeddings using a sentence transformer model
model = SentenceTransformer("multi-qa-mpnet-base-cos-v1")
embeddings = torch.tensor(model.encode(sentences))

# Custom object distance function: binary match (0 if same, 1 if different)
def topic_distance(objects1, objects2):
    obj_tensor1 = torch.tensor([hash(obj) for obj in objects1], dtype=torch.float32)
    obj_tensor2 = torch.tensor([hash(obj) for obj in objects2], dtype=torch.float32)
    return (obj_tensor1.unsqueeze(1) != obj_tensor2.unsqueeze(0)).float()


# Parameters
alpha_text = 0.1  # Weight for text similarity
alpha = 1.2  # Weight for starting a new cluster
temperature = 0.1  # Softmax temperature
decay_rate = 0.1

# Call the hybrid_dd_crp function
assignments, clusters = hybrid_dd_crp(
    sentences=sentences,
    objects=objects,
    embeddings=embeddings,
    object_distance_function=topic_distance,
    alpha_text=alpha_text,
    alpha=alpha,
    temperature=temperature,
    decay_function=torch_exponential_decay,
    decay_params={"decay_rate": decay_rate},
    seed=348,
)

# Output results
print("Assignments:", assignments)
print("Clusters:", clusters)
objects = [[(sentences[i], objects[i]) for i in cluster] for cluster in clusters]
for i, objs in enumerate(objects):
    print(f"Cluster {i+1}:")
    for sentence, obj in objs:
        print(f"  - {obj}: {sentence}")
