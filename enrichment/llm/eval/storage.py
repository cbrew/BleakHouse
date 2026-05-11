"""Persist per-input eval results to JSON-on-disk.

Layout:
    data/eval/<run_id>/<task>.json

Each file holds the full results for one task in one eval run:
provider/model used, per-input metrics, summary scores, and the
floor outcome.

JSON-on-disk (vs SQLite per the plan's 'sqlite or JSON-on-disk'
option) because at our scale (~5-20 fixture inputs per task,
small handful of tasks) it's the simpler choice. Round-tripping
is just json.loads / json.dumps; diffs across runs are git-
diffable.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
EVAL_ROOT = REPO_ROOT / "data" / "eval"


def _dataclass_to_dict(obj: Any) -> Any:
    """Recursively convert dataclasses to dicts; pass through other
    types unchanged."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _dataclass_to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [_dataclass_to_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _dataclass_to_dict(v) for k, v in obj.items()}
    return obj


def save_results(
    run_id: str,
    task: str,
    payload: dict[str, Any],
    *,
    root: Path | None = None,
) -> Path:
    """Atomically write `payload` to <root>/<run_id>/<task>.json.

    Returns the final path. `root` defaults to the module-level
    EVAL_ROOT (looked up at call time so tests can monkeypatch it).
    The payload is converted to plain dicts via _dataclass_to_dict
    so callers can pass dataclasses freely.
    """
    if root is None:
        root = EVAL_ROOT
    out_dir = root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{task}.json"

    data = _dataclass_to_dict(payload)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"

    with tempfile.NamedTemporaryFile(
        dir=out_dir, prefix=f".{path.name}.", suffix=".tmp",
        mode="w", delete=False, encoding="utf-8",
    ) as f:
        tmp = Path(f.name)
        f.write(text)
    os.replace(tmp, path)
    return path


def load_results(
    run_id: str,
    task: str,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Load a previously-persisted eval result. `root` defaults to
    the module-level EVAL_ROOT (looked up at call time)."""
    if root is None:
        root = EVAL_ROOT
    path = root / run_id / f"{task}.json"
    return json.loads(path.read_text())
