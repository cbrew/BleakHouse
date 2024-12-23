from sentence_transformers import SentenceTransformer
from bleak_house.distance_crp_torch import dd_crp, torch_logistic_decay


if __name__ == "__main__":
        sentences = [
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
            ] * 3

        # Load the SentenceTransformer model
        model = SentenceTransformer("BAAI/bge-large-en-v1.5")
        # Apply dd-CRP with PyTorch tensors
        alpha = 2.0
        seed = 42
        temperature = 1.0
        logistic_params = {'mu': 0.5, 'kappa': 2.0}  # Parameters for logistic decay

        assignments, clusters = dd_crp(
            sentences,
            model=model,
            alpha=alpha,
            decay_function=torch_logistic_decay,  # Torch-compatible decay function
            seed=seed,
            temperature=temperature,
            decay_params=logistic_params
        )

        # Display results
        print(f"Cluster assignments with alpha={alpha}, seed={seed}, temperature={temperature}:", assignments)
        for idx, cluster in enumerate(clusters):
            print(f"Cluster {idx + 1}:")
            for sentence_index in cluster:
                print(f"  - {sentences[sentence_index]}")
