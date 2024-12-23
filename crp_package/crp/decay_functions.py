import torch


def torch_exponential_decay(distance: torch.Tensor, decay_rate: float = 1.0,**kwargs) -> torch.Tensor:
    return torch.exp(-decay_rate * distance)


def torch_window_decay(distance: torch.Tensor, delta: float = 1.0,**kwargs) -> torch.Tensor:
    return (distance <= delta).float()


def torch_logistic_decay(distance: torch.Tensor, mu: float = 0.5, kappa: float = 1.0,**kwargs) -> torch.Tensor:
    return 1 / (1 + torch.exp(kappa * (distance - mu)))
