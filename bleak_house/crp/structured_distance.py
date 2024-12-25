import abc
from dataclasses import dataclass, field
from typing import List, Tuple, TypeVar, Dict
import torch

# Define a type variable for the object type
O = TypeVar("O")


class HybridDistanceComponent(abc.ABC):
    """
    Abstract base class for hybrid distance components.
    Must be able to compute pairwise distances between objects and provide a decay function.
    """

    def __init__(self, objects: List[O], **kwargs):
        self.distance_matrix = self.object_distance_function(objects)
        self.kwargs = kwargs

    @abc.abstractmethod
    def object_distance_function(self, objects: List[O]) -> torch.Tensor:
        """
        Compute pairwise distances between a list of objects.

        Parameters:
            objects: List of objects.

        Returns:
            Tensor of pairwise distances.
        """
        pass

    @abc.abstractmethod
    def decay_function(
        self, distances: torch.Tensor, new_object: O, cluster_objects: List[O]
    ) -> torch.Tensor:
        """
        Apply decay to distances based on cluster context.

        Parameters:
            distances: Tensor of pairwise distances.
            new_object: The object to be added to the clustering.
            cluster_members: Objects already in the clustering.

        Returns:
            Tensor of decayed distances.
        """
        pass


@dataclass
class StructuredObject:
    """
    Base class for structured objects.
    Each object can define fields that are relevant for clustering.
    """

    id: int
    label: str
    position: int
    embedding: torch.Tensor
    unavailable: Dict = field(default_factory=dict)


class StructuredObjectComponent(HybridDistanceComponent):
    """
    Component for clustering structured objects using dynamic rules.
    """

    def __init__(self, objects: List[StructuredObject], **kwargs):
        super().__init__(objects, **kwargs)
        self.objects = objects

    def object_distance_function(self, objects: List[StructuredObject]) -> torch.Tensor:
        """
        Compute pairwise distances for structured objects.

        Parameters:
            objects: List of structured objects.

        Returns:
            Tensor of combined distances based on rules (e.g., position, embedding).
        """
        n = len(objects)

        # Compute positional and embedding-based distances
        positions = torch.tensor([obj.position for obj in objects], dtype=torch.float32)
        embeddings = torch.stack([obj.embedding for obj in objects])

        # Normalize positions and compute distances
        min_pos, max_pos = positions.min(), positions.max()
        normalized_positions = (positions - min_pos) / (max_pos - min_pos)
        position_distances = torch.abs(
            normalized_positions.unsqueeze(0) - normalized_positions.unsqueeze(1)
        )

        # Compute cosine embedding distances
        cosine_similarity_matrix = torch.mm(embeddings, embeddings.t())
        embedding_distances = 1 - cosine_similarity_matrix

        # Combine distances
        distance_matrix = position_distances + embedding_distances
        return distance_matrix

    def decay_function(
        self,
        distances: torch.Tensor,
        new_object: StructuredObject,
        cluster_objects: List[List[StructuredObject]],
    ) -> torch.Tensor:
        """
        Apply decay rules for structured objects.

        Parameters:
            distances: Tensor of pairwise distances.
            new_object: The structured object to be added.
            cluster_objects: List of objects already in each cluster.

        Returns:
            Tensor of decayed distances, enforcing availability constraints.
        """
        mytype = new_object.label
        for cluster in cluster_objects:
            for member in cluster:
                if mytype in member.unavailable:
                    # we know none of the other members will be available either
                    break
                elif mytype == "person":
                    member.unavailable[mytype] = True

        unavailable_indices = sorted(
            (obj.id - 1)
            for cluster in cluster_objects
            for obj in cluster
            if mytype in obj.unavailable
        )
        distances[unavailable_indices] = float(-9999.0)

        return distances


def _dd_crp_structured(
    objects: List[StructuredObject],
    components: List[HybridDistanceComponent],
    component_weights: List[float],
    alpha: float,
    temperature: float,
    seed: int = 42,
) -> Tuple[List[int], List[List[int]]]:
    """
    Distance-Dependent CRP using multiple components with their specific decay functions.

    Parameters:
        sentences: List of sentences.
        components: List of HybridDistanceComponent objects.
        alpha: Weight for starting a new cluster.
        temperature: Softmax temperature.

    Returns:
        Cluster assignments and cluster groups.
    """
    torch.manual_seed(seed)

    assignments = []
    clusters = []

    for i, object in enumerate(objects):
        link_scores = []

        if i > 0:
            for component, weight in zip(components, component_weights):
                # we are going to mess with the distances, so we need a fresh copy
                distances = component.distance_matrix[i, :i].detach().clone()
                cluster_objects = [
                    [objects[j] for j in cluster] for cluster in clusters
                ]
                decayed_distances = weight * component.decay_function(
                    distances,
                    new_object=object,
                    cluster_objects=cluster_objects,
                )
                link_scores.append(decayed_distances.tolist())

            # Flatten and sum the scores from all components
            link_scores = torch.tensor(link_scores).sum(dim=0)
            link_scores = link_scores.tolist()

        # Add alpha for new cluster creation
        link_scores.append(alpha)

        # Compute probabilities with softmax
        link_probs = torch.softmax(torch.tensor(link_scores) / temperature, dim=0)

        # Sample a cluster assignment
        sampled_index = torch.multinomial(link_probs, 1).item()

        if sampled_index == len(link_probs) - 1:
            cluster_id = len(clusters)
            clusters.append([i])
            assignments.append(cluster_id)
        else:
            cluster_id = assignments[sampled_index]
            clusters[cluster_id].append(i)
            assignments.append(cluster_id)

    return assignments, clusters


def hybrid_dd_crp(
    objects: List[StructuredObject],
    components: List[HybridDistanceComponent],
    component_weights: List[float],
    alpha: float,
    temperature: float,
    seed: int = 42,
) -> Tuple[List[int], List[List[int]]]:
    """

    :param objects:
    :param components:
    :param component_weights:
    :param alpha:
    :param temperature:
    :param cluster_callback:
    :param seed:
    :return:
    """
    return _dd_crp_structured(
        objects,
        components,
        component_weights,
        alpha,
        temperature,
        seed,
    )


if __name__ == "__main__":
    # Example structured objects
    objects = [
        StructuredObject(id=1, label="person", position=1, embedding=torch.rand(5)),
        StructuredObject(id=2, label="location", position=2, embedding=torch.rand(5)),
        StructuredObject(
            id=3, label="organization", position=10, embedding=torch.rand(5)
        ),
        StructuredObject(id=4, label="location", position=12, embedding=torch.rand(5)),
        StructuredObject(id=5, label="person", position=20, embedding=torch.rand(5)),
        StructuredObject(id=6, label="location", position=25, embedding=torch.rand(5)),
        StructuredObject(id=7, label="person", position=25, embedding=torch.rand(5)),
        StructuredObject(id=8, label="location", position=25, embedding=torch.rand(5)),
        StructuredObject(id=9, label="person", position=25, embedding=torch.rand(5)),
    ]

    structured_component = StructuredObjectComponent(objects)

    # Perform clustering
    assignments, clusters = _dd_crp_structured(
        objects=objects,
        components=[structured_component],  # Your initialized components
        component_weights=[1.0],  # Weights for each component
        alpha=0.5,
        temperature=0.7,
        seed=71,
    )

    print("Assignments:", assignments)
    print("Clusters:", clusters)
    for object in objects:
        print(
            f"Object {object.id} assigned to cluster {assignments[object.id - 1]} {object.label} {object.position} {object.embedding} {object.unavailable}"
        )
