"""Pure scoring-function tests."""
from __future__ import annotations

from enrichment.llm.eval import scoring


# ── schema_validity ──────────────────────────────────────────────


def test_schema_validity_no_schema_always_ok() -> None:
    """Free-text task = 1.0 regardless of content."""
    assert scoring.schema_validity("anything", None) == 1.0
    assert scoring.schema_validity("", None) == 1.0


def test_schema_validity_valid_object() -> None:
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
    assert scoring.schema_validity('{"x": 1}', schema) == 1.0


def test_schema_validity_invalid_json() -> None:
    schema = {"type": "object"}
    assert scoring.schema_validity("not json", schema) == 0.0


def test_schema_validity_wrong_top_type() -> None:
    """An object-typed schema with a list response is invalid."""
    schema = {"type": "object"}
    assert scoring.schema_validity("[1, 2, 3]", schema) == 0.0


def test_schema_validity_array_top_type() -> None:
    schema = {"type": "array"}
    assert scoring.schema_validity("[1, 2, 3]", schema) == 1.0
    assert scoring.schema_validity('{"x": 1}', schema) == 0.0


# ── set_overlap_jaccard ──────────────────────────────────────────


def test_set_overlap_identical() -> None:
    assert scoring.set_overlap_jaccard({"a", "b", "c"}, {"a", "b", "c"}) == 1.0


def test_set_overlap_disjoint() -> None:
    assert scoring.set_overlap_jaccard({"a", "b"}, {"c", "d"}) == 0.0


def test_set_overlap_partial() -> None:
    # 2 shared / 4 union = 0.5
    assert scoring.set_overlap_jaccard({"a", "b", "c"}, {"b", "c", "d"}) == 0.5


def test_set_overlap_both_empty_is_one() -> None:
    """Both-empty = perfect agreement (no picks expected, no picks
    given)."""
    assert scoring.set_overlap_jaccard(set(), set()) == 1.0


def test_set_overlap_one_empty_is_zero() -> None:
    assert scoring.set_overlap_jaccard({"a"}, set()) == 0.0
    assert scoring.set_overlap_jaccard(set(), {"a"}) == 0.0


def test_set_overlap_accepts_lists() -> None:
    """Inputs can be list or set; both get deduplicated."""
    assert scoring.set_overlap_jaccard(["a", "b", "a"], ["a", "b"]) == 1.0


# ── field_presence_match ─────────────────────────────────────────


def test_field_presence_all_present() -> None:
    candidate = {"a": 1, "b": 2, "c": 3}
    assert scoring.field_presence_match(candidate, ["a", "b", "c"]) == 1.0


def test_field_presence_half_present() -> None:
    candidate = {"a": 1, "b": 2}
    assert scoring.field_presence_match(candidate, ["a", "b", "c", "d"]) == 0.5


def test_field_presence_none_value_counts_as_absent() -> None:
    """A field with a None value isn't 'populated' for our purposes."""
    candidate = {"a": 1, "b": None}
    assert scoring.field_presence_match(candidate, ["a", "b"]) == 0.5


def test_field_presence_empty_expected() -> None:
    """Empty expected list = trivially full coverage."""
    assert scoring.field_presence_match({"a": 1}, []) == 1.0


# ── extract_tags_from_listener_pick_response ─────────────────────


def test_extract_tags_clean_json() -> None:
    text = '{"tags": ["ref-1", "ref-2", "ref-3"]}'
    assert scoring.extract_tags_from_listener_pick_response(text) == [
        "ref-1", "ref-2", "ref-3",
    ]


def test_extract_tags_json_in_prose() -> None:
    """The actual host_prep regex tolerates prose around the JSON
    blob; mirror that here."""
    text = 'Here are my picks: {"tags": ["ref-5"]} done.'
    assert scoring.extract_tags_from_listener_pick_response(text) == ["ref-5"]


def test_extract_tags_no_match() -> None:
    assert scoring.extract_tags_from_listener_pick_response("no json here") == []


def test_extract_tags_malformed_json() -> None:
    """A regex-match-looking blob that isn't valid JSON returns []."""
    text = '{"tags": [ref-1]}'   # unquoted ref-1 — invalid JSON
    assert scoring.extract_tags_from_listener_pick_response(text) == []


def test_extract_tags_skips_non_strings() -> None:
    text = '{"tags": ["ref-1", 99, "ref-2"]}'
    assert scoring.extract_tags_from_listener_pick_response(text) == [
        "ref-1", "ref-2",
    ]
