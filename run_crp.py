from sentence_transformers import SentenceTransformer
from bleak_house.distance_crp_torch import dd_crp
from bleak_house.decay_functions import torch_exponential_decay
import numpy as np
from collections import Counter

if __name__ == "__main__":
        some_sentences = [
                "The cat sat on the mat.",
                "A dog is running.",
                "Dogs are keen on running.",
                "Alsatians are a species of dog.",
                "A dog is running around in the grass.",
                "The mat was very comfortable.",
                "Dogs love running around in the grass.",
                "Cats are usually very quiet animals.",
                "The tiger is the largest cat species.",
                "Oranges are not the only fruit.",
                "In Bavaria, lemons are known as 'citrons'.",
                "The fruit of a lemon tree can be used for many purposes.",
                "Is an orange a type of lemon?",
                "Lemons are sour, but oranges are sweet.",
                "Is an Alsatian a type of cat?",
                "Cats are not so keen on running.",
                "Elephants can run faster than cats.",
                "Three elephants are running around in the grass.",
                "Elephants are the largest land animals.",
                "Elephants are known for their large ears.",
                "Two dogs are playing in the park.",
                "The park is full of dogs and cats.",
                "Dogs and cats are not always friends.",
            ]
        sentences = some_sentences*5
        rng = np.random.default_rng(42)
        rng.shuffle(sentences)

        # Load the SentenceTransformer model
        model = SentenceTransformer("BAAI/bge-large-en-v1.5")
        # Apply dd-CRP with PyTorch tensors
        alpha = 1.5
        seed = 42
        temperature = 1.0
        exponential_params = {'decay_rate': 2.0}

        assignments, clusters = dd_crp(
            sentences,
            model=model,
            alpha=alpha,
            decay_function=torch_exponential_decay,  # Torch-compatible decay function
            seed=seed,
            temperature=temperature,
            decay_params=exponential_params
        )

        # Display results
        counter = Counter(sentences)
        print("Total number of distinct_sentences:", len(counter))
        print("Total number of sentences:", len(sentences))
        print(f"Cluster assignments with alpha={alpha}, seed={seed}, temperature={temperature},decay=exponential, decay_rate={exponential_params['decay_rate']}:")
        print(assignments)
        for idx, cluster in enumerate(clusters):
            print(f"Cluster {idx + 1}:")
            counts = Counter(sentences[sentence_index] for sentence_index in cluster)
            print("Number of distinct_sentences in cluster:", len(counts))
            print("Number of sentences in cluster:", len(cluster))
            for item in counts.most_common():
                print(f"  - {item[0]} ({item[1]} occurrences)")

