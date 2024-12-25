import torch
import abc
from typing import List, Tuple, TypeVar

# Define a type variable for the object type
O = TypeVar("O")

"""
Module for performing Distance-Dependent Chinese Restaurant Process (DD-CRP) with a hybrid distance metric.

This module provides:
    - A pipeline for clustering sentences using a distance-dependent CRP algorithm with multiple distance components.

Classes:
    - HybridDistanceComponent: Abstract base class for defining distance components.

Functions:
    - _dd_crp_with_hybrid_distance: Performs DD-CRP clustering using component-specific decay functions.
    - hybrid_dd_crp: Top-level procedure for DD-CRP clustering using multiple components.

Usage:
    Define custom subclasses of HybridDistanceComponent for each distance metric and use them in `hybrid_dd_crp`.
"""


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
        self, distances: torch.Tensor, new_object: O, cluster_members: List[O]
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


class TextSimilarityComponent(HybridDistanceComponent):
    """
    Component for computing text similarity using cosine similarity of embeddings.
    Applies exponential decay to the distances.
    """

    def __init__(self, objects: List[torch.Tensor], decay_rate: float = 1.0, **kwargs):
        self.decay_rate = decay_rate
        super().__init__(objects, **kwargs)

    def object_distance_function(self, objects: List[torch.Tensor]) -> torch.Tensor:
        """
        Compute pairwise cosine distances between sentence embeddings.

        Parameters:
            objects: List of sentence embeddings.

        Returns:
            Tensor of pairwise cosine distances.
        """
        embeddings = torch.stack(objects)
        cosine_similarity_matrix = torch.mm(embeddings, embeddings.t())
        text_distance_matrix = 1 - cosine_similarity_matrix
        return text_distance_matrix

    def decay_function(
        self,
        distances: torch.Tensor,
        new_object: torch.Tensor,
        cluster_members: List[torch.Tensor],
    ) -> torch.Tensor:
        """
        Apply exponential decay to distances.

        Parameters:
            distances: Tensor of pairwise distances.
            new_object: The object to be added to the clustering.
            cluster_members: Objects already in the clustering.

        Returns:
            Tensor of decayed distances.
        """
        return torch.exp(-self.decay_rate * distances)


class PositionalHybridDistanceComponent(HybridDistanceComponent):
    """
    Component for computing positional distances on a normalized timeline.
    Applies logistic decay to the distances.
    """

    def __init__(self, objects: List[int], kappa: float = 1.0, **kwargs):
        self.kappa = kappa
        super().__init__(objects, **kwargs)

    def object_distance_function(self, objects: List[int]) -> torch.Tensor:
        """
        Compute pairwise distances on a normalized timeline [0, 1].

        Parameters:
            objects: List of integer positions.

        Returns:
            Tensor of pairwise distances normalized to [0, 1].
        """
        positions = torch.tensor(objects, dtype=torch.float32)
        min_pos, max_pos = positions.min(), positions.max()
        normalized_positions = (positions - min_pos) / (max_pos - min_pos)
        diff_matrix = torch.abs(
            normalized_positions.unsqueeze(0) - normalized_positions.unsqueeze(1)
        )
        return diff_matrix

    def decay_function(
        self, distances: torch.Tensor, new_object: int, cluster_members: List[int]
    ) -> torch.Tensor:
        """
        Apply logistic decay to distances.

        Parameters:
            distances: Tensor of pairwise distances.
            new_object: The position of the new object to be added to the clustering.
            cluster_members: Positions of objects already in the clustering.

        Returns:
            Tensor of decayed distances.
        """
        return 1 / (1 + torch.exp(self.kappa * distances))


# Custom object distance function: binary match (0 if same, 1 if different)
def topic_distance(objects1, objects2):
    obj_tensor1 = torch.tensor([hash(obj) for obj in objects1], dtype=torch.float32)
    obj_tensor2 = torch.tensor([hash(obj) for obj in objects2], dtype=torch.float32)
    return (obj_tensor1.unsqueeze(1) != obj_tensor2.unsqueeze(0)).float()


class TopicMatchComponent(HybridDistanceComponent):
    """
    Component for computing binary match between topics.
    Applies window decay to the distances.
    """

    def __init__(self, objects: List[O], delta: float = 1.0, **kwargs):
        self.delta = delta
        super().__init__(objects, **kwargs)

    def object_distance_function(self, objects: List[O]) -> torch.Tensor:
        """
        Compute pairwise binary match between topics.

        Parameters:
            objects: List of topics.

        Returns:
            Tensor of pairwise binary match distances.
        """
        return topic_distance(objects, objects)

    def decay_function(
        self, distances: torch.Tensor, new_object: O, cluster_members: List[O]
    ) -> torch.Tensor:
        """
        Apply window decay to distances.

        Parameters:
            distances: Tensor of pairwise distances.
            new_object: The topic to be added to the clustering.
            cluster_members: Topics already in the clustering.

        Returns:
            Tensor of decayed distances.
        """
        return (distances <= self.delta).float()


def _dd_crp_with_hybrid_distance(
    sentences: List[str],
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

    for i, sentence in enumerate(sentences):
        link_scores = []

        if i > 0:
            for component, weight in zip(components, component_weights):
                distances = component.distance_matrix[i, :i]
                decayed_distances = weight * component.decay_function(
                    distances,
                    new_object=component.distance_matrix[i],
                    cluster_members=[component.distance_matrix[j] for j in range(i)],
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
    sentences: List[str],
    components: List[HybridDistanceComponent],
    component_weights: List[float],
    alpha: float,
    temperature: float,
    seed: int = 42,
) -> Tuple[List[int], List[List[int]]]:
    """
    Top-level procedure to perform DD-CRP clustering using multiple components.

    Parameters:
        sentences: List of sentences.
        components: List of HybridDistanceComponent objects.
        alpha: Weight for starting a new cluster.
        temperature: Softmax temperature.
        seed: Random seed.

    Returns:
        Cluster assignments and cluster groups.
    """
    return _dd_crp_with_hybrid_distance(
        sentences, components, component_weights, alpha, temperature, seed
    )
