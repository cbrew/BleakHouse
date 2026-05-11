"""Fixture loading tests."""
from __future__ import annotations

import json
from pathlib import Path

from enrichment.llm.eval import fixtures_io


def test_load_minimal_fixture(tmp_path: Path) -> None:
    payload = {
        "task": "listener_pick",
        "description": "tiny",
        "inputs": [
            {
                "id": "x",
                "system": "be brief",
                "user": "u",
                "max_tokens": 100,
                "json_schema": None,
                "baseline": {"tags": ["ref-1"]},
            },
        ],
    }
    p = tmp_path / "f.json"
    p.write_text(json.dumps(payload))
    f = fixtures_io.load_fixture(p)
    assert f.task == "listener_pick"
    assert f.description == "tiny"
    assert len(f.inputs) == 1
    assert f.inputs[0].id == "x"
    assert f.inputs[0].system == "be brief"
    assert f.inputs[0].user == "u"
    assert f.inputs[0].max_tokens == 100
    assert f.inputs[0].json_schema is None
    assert f.inputs[0].baseline == {"tags": ["ref-1"]}


def test_load_fixture_optional_fields_default_to_none(tmp_path: Path) -> None:
    payload = {
        "task": "t",
        "description": "",
        "inputs": [
            # Only required fields present.
            {"id": "1", "user": "u", "max_tokens": 10},
        ],
    }
    p = tmp_path / "f.json"
    p.write_text(json.dumps(payload))
    f = fixtures_io.load_fixture(p)
    assert f.inputs[0].system is None
    assert f.inputs[0].json_schema is None
    assert f.inputs[0].baseline is None


def test_example_fixture_loads_and_parses() -> None:
    """The committed listener_pick_example.json must always be loadable."""
    f = fixtures_io.load_fixture_by_name("listener_pick_example")
    assert f.task == "listener_pick"
    assert len(f.inputs) == 3
    for inp in f.inputs:
        assert inp.baseline is not None
        assert "tags" in inp.baseline
