"""Load DVC-tracked parameters from params.yaml.

Thin, eager loader. Called at import time by the modules whose
constants live in params.yaml so the in-memory dicts match what DVC
sees on disk.

If params.yaml is missing, every consumer raises on import. That's
intentional — running the pipeline without a pinned params file would
silently destroy DVC's provenance guarantees.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_PARAMS_PATH = Path(__file__).resolve().parent.parent / "params.yaml"


@lru_cache(maxsize=1)
def load_params() -> dict[str, Any]:
    """Return the parsed params.yaml. Cached; safe to call many times."""
    if not _PARAMS_PATH.exists():
        raise FileNotFoundError(
            f"DVC params file missing at {_PARAMS_PATH}. "
            "This project requires params.yaml at the repo root; "
            "see BleakHouse-ati / docs/dvc.md."
        )
    with open(_PARAMS_PATH) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{_PARAMS_PATH}: expected top-level mapping")
    return data


def get(*keys: str, default: Any = None) -> Any:
    """Nested-dict getter: get('speakers', 'voices') returns the voices map."""
    cur: Any = load_params()
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur
