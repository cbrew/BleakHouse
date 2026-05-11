"""Storage round-trip + atomic-write tests."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from enrichment.llm.eval import storage


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    payload = {
        "run_id": "test-run",
        "task": "listener_pick",
        "metrics": {"set_overlap_mean": 0.9},
        "per_input": [
            {"id": "ex-1", "schema_valid": 1.0, "set_overlap": 1.0},
            {"id": "ex-2", "schema_valid": 1.0, "set_overlap": 0.8},
        ],
    }
    path = storage.save_results("test-run", "listener_pick", payload, root=tmp_path)
    assert path.exists()
    loaded = storage.load_results("test-run", "listener_pick", root=tmp_path)
    assert loaded == payload


def test_save_dataclasses_serialised_via_asdict(tmp_path: Path) -> None:
    @dataclass
    class _Inner:
        name: str
        score: float

    @dataclass
    class _Outer:
        run_id: str
        inner: _Inner

    payload = {
        "run_id": "x",
        "data": _Outer(run_id="x", inner=_Inner(name="metric", score=0.5)),
    }
    storage.save_results("x", "t", payload, root=tmp_path)
    loaded = storage.load_results("x", "t", root=tmp_path)
    assert loaded == {
        "run_id": "x",
        "data": {"run_id": "x", "inner": {"name": "metric", "score": 0.5}},
    }


def test_save_is_atomic_no_tmp_leftovers(tmp_path: Path) -> None:
    """Tmp file should be gone after a successful save."""
    storage.save_results("a", "t", {"k": "v"}, root=tmp_path)
    out_dir = tmp_path / "a"
    tmpfiles = [
        p for p in out_dir.iterdir()
        if p.name.startswith(".") and p.name.endswith(".tmp")
    ]
    assert tmpfiles == []


def test_save_creates_run_dir(tmp_path: Path) -> None:
    """save_results creates the run_id subdirectory if missing."""
    storage.save_results("new-run-dir", "t", {"k": "v"}, root=tmp_path)
    assert (tmp_path / "new-run-dir").is_dir()
