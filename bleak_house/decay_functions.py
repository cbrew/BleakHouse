import torch

def torch_exponential_decay(distance: torch.Tensor,
                            decay_rate: float = 1.0,**kwargs) -> torch.Tensor:
    """
    Exponential decay function: f(d) = exp(-d).

    Parameters:
        distance (torch.Tensor): The distance tensor.

    Returns:
        torch.Tensor: Decay values for the distances.
    """
    return torch.exp(-decay_rate*distance)


def torch_window_decay(distance: torch.Tensor, delta: float = 1.0, **kwargs) -> torch.Tensor:
    """
    Window decay function: f(d) = 1 if d <= delta, else 0.

    Parameters:
        distance (torch.Tensor): The distance tensor.
        delta (float): Threshold distance for decay.

    Returns:
        torch.Tensor: Decay values for the distances.
    """
    return (distance <= delta).float()


def torch_logistic_decay(distance: torch.Tensor, mu: float = 0.5, kappa: float = 2.0, **kwargs) -> torch.Tensor:
    """
    Soft version of windowing function.
    Logistic decay function: f(d) = 1 / (1 + exp(kappa * (d - mu))).


    Parameters:
        distance (torch.Tensor): The distance tensor.
        mu (float): Midpoint of the logistic curve (where f(d) = 0.5).
        kappa (float): Steepness of the logistic curve.

    Returns:
        torch.Tensor: Decay values for the distances.
    """
    return 1 / (1 + torch.exp(kappa * (distance - mu)))
