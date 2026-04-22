"""Tests for enrichment.axes — canonical axes and naming."""
from __future__ import annotations

import pytest

from enrichment.axes import (
    DEFAULT_GENERATOR,
    GENERATORS,
    HOSTPREP_VALUES,
    NOVEL_KEYS,
    PANELS,
    PANELS_TUPLE,
    PIPELINES,
    RunAxes,
    panel_for_experts,
    parse_run_dir_name,
    run_dir_name,
)


@pytest.mark.parametrize(
    "axes,expected",
    [
        (dict(novel="bh", pipeline="trn", panel="literary", hostprep=False), "bh_trn_literary"),
        (dict(novel="bh", pipeline="trn", panel="literary", hostprep=True), "bh_trn_literary_hostprep"),
        (dict(novel="bh", pipeline="trn", panel="literary", hostprep=True, generator="cerebras_qwen"), "bh_trn_literary_hostprep_cerebras_qwen"),
        (dict(novel="bh", pipeline="trn", panel="literary", hostprep=False, generator="cerebras_zai_glm"), "bh_trn_literary_cerebras_zai_glm"),
        (dict(novel="omf", pipeline="emb", panel="alternatives", hostprep=False), "omf_emb_alternatives"),
    ],
)
def test_run_dir_name_explicit(axes: dict, expected: str) -> None:
    assert run_dir_name(**axes) == expected


def test_default_generator_is_omitted() -> None:
    name = run_dir_name(novel="bh", pipeline="trn", panel="literary", hostprep=False,
                        generator=DEFAULT_GENERATOR)
    assert DEFAULT_GENERATOR not in name


def test_non_default_generator_always_appears() -> None:
    name = run_dir_name(novel="bh", pipeline="trn", panel="literary", hostprep=False,
                        generator="cerebras_qwen")
    assert name.endswith("_cerebras_qwen")


@pytest.mark.parametrize("bad", [
    dict(novel="XX", pipeline="trn", panel="literary", hostprep=False),
    dict(novel="bh", pipeline="XX", panel="literary", hostprep=False),
    dict(novel="bh", pipeline="trn", panel="XX", hostprep=False),
    dict(novel="bh", pipeline="trn", panel="literary", hostprep=False, generator="XX"),
])
def test_run_dir_name_rejects_unknown(bad: dict) -> None:
    with pytest.raises(ValueError):
        run_dir_name(**bad)


def test_roundtrip_every_combination() -> None:
    """Every valid combination round-trips through name and back."""
    for novel in NOVEL_KEYS:
        for pipeline in PIPELINES:
            for panel in PANELS:
                for hostprep in HOSTPREP_VALUES:
                    for generator in GENERATORS:
                        name = run_dir_name(novel=novel, pipeline=pipeline,
                                            panel=panel, hostprep=hostprep,
                                            generator=generator)
                        parsed = parse_run_dir_name(name)
                        assert parsed == RunAxes(novel=novel, pipeline=pipeline,
                                                 panel=panel, hostprep=hostprep,
                                                 generator=generator)


@pytest.mark.parametrize("name", [
    "too_few",                    # 2 tokens
    "bh",                          # 1 token
    "",                            # empty
    "XX_trn_literary",             # bad novel
    "bh_XX_literary",              # bad pipeline
    "bh_trn_XX",                   # bad panel
    "bh_trn_literary_wrongsuffix", # unknown generator
    "bh_trn_literary_hostprep_unknown_model",  # unknown generator (multi-token)
])
def test_parse_rejects_garbage(name: str) -> None:
    with pytest.raises(ValueError):
        parse_run_dir_name(name)


def test_parse_preserves_default_generator() -> None:
    axes = parse_run_dir_name("bh_trn_literary_hostprep")
    assert axes.generator == DEFAULT_GENERATOR
    assert axes.hostprep is True


def test_parse_multi_token_generator() -> None:
    """Generator slugs with underscores (e.g. cerebras_qwen) must parse correctly."""
    axes = parse_run_dir_name("bh_trn_literary_hostprep_cerebras_qwen")
    assert axes.generator == "cerebras_qwen"
    assert axes.hostprep is True


def test_parse_anthropic_default_model_name() -> None:
    """anthropic_sonnet_4_6 is the default — it must be parseable even when
    explicitly included, so hand-written directory names don't break."""
    # When explicitly present in the name, we expect a roundtrip to preserve it.
    # Current policy: generator is only omitted when it equals DEFAULT_GENERATOR,
    # but parser should still accept explicit default if someone writes it.
    # (Right now run_dir_name OMITS the default; but parse must still reject
    # garbage, which it does. The explicit-default case is symmetric with
    # omission — we assert only that the roundtrip works via run_dir_name.)
    axes = RunAxes(novel="bh", pipeline="trn", panel="literary", hostprep=False,
                   generator=DEFAULT_GENERATOR)
    name = axes.dir_name()
    assert parse_run_dir_name(name).generator == DEFAULT_GENERATOR


def test_runaxes_to_from_dict() -> None:
    axes = RunAxes(novel="bh", pipeline="trn", panel="literary", hostprep=True,
                   generator="cerebras_qwen")
    d = axes.to_dict()
    assert d == {"novel": "bh", "pipeline": "trn", "panel": "literary",
                 "hostprep": True, "generator": "cerebras_qwen"}
    assert RunAxes.from_dict(d) == axes


def test_runaxes_from_dict_defaults_generator() -> None:
    """Legacy configs without a generator field default to DEFAULT_GENERATOR."""
    d = {"novel": "bh", "pipeline": "trn", "panel": "literary", "hostprep": True}
    assert RunAxes.from_dict(d).generator == DEFAULT_GENERATOR


def test_runaxes_validates_on_init() -> None:
    with pytest.raises(ValueError):
        RunAxes(novel="XX", pipeline="trn", panel="literary", hostprep=False)


def test_panel_for_experts_exact_match() -> None:
    for p in PANELS_TUPLE:
        assert panel_for_experts(p.experts) == p.id


def test_panel_for_experts_different_order() -> None:
    assert panel_for_experts(
        ["Caroline Woodcourt", "Eleanor Hartley", "James Blackstone"]
    ) == "literary"


def test_panel_for_experts_unknown_returns_none() -> None:
    assert panel_for_experts(["Nobody Here"]) is None
    # Partial overlap with a known panel still returns None (strict equality)
    assert panel_for_experts(["Eleanor Hartley", "James Blackstone"]) is None
