"""Floor protocol tests."""
from __future__ import annotations

from enrichment.llm.eval import floors


def test_listener_pick_floor_set_overlap() -> None:
    f = floors.floor_for_task("listener_pick")
    assert f.task == "listener_pick"
    assert f.task_class == "small_structured"
    assert f.schema_validity_min == 1.0
    assert f.set_overlap_min == 0.85
    assert f.field_presence_min is None
    assert f.blinded_preference_min is None


def test_passage_enrichment_floor_field_presence() -> None:
    f = floors.floor_for_task("passage_enrichment")
    assert f.task_class == "structured_intermediate"
    assert f.field_presence_min == 0.95
    assert f.set_overlap_min is None


def test_prose_short_floor_blinded_preference() -> None:
    f = floors.floor_for_task("generate_podcast_short")
    assert f.task_class == "prose_short"
    assert f.blinded_preference_min == 0.45


def test_unknown_task_returns_schema_validity_only_fallback() -> None:
    f = floors.floor_for_task("some_new_task")
    assert f.task_class == "unknown"
    assert f.schema_validity_min == 1.0
    assert f.set_overlap_min is None
    assert "No task-specific floor" in f.description


def test_known_floors_sorted() -> None:
    known = floors.known_floors()
    assert "listener_pick" in known
    assert "passage_enrichment" in known
    assert list(known) == sorted(known)


def test_register_floor_overrides() -> None:
    custom = floors.Floor(
        task="test_custom",
        task_class="small_structured",
        schema_validity_min=1.0,
        set_overlap_min=0.5,
    )
    floors.register_floor(custom)
    f = floors.floor_for_task("test_custom")
    assert f.set_overlap_min == 0.5


def test_floor_outcome_enum_values() -> None:
    assert floors.FloorOutcome.PASS.value == "pass"
    assert floors.FloorOutcome.FAIL.value == "fail"
    assert floors.FloorOutcome.INCONCLUSIVE.value == "inconclusive"
