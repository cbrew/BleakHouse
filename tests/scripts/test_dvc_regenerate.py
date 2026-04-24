"""Unit tests for scripts.dvc_regenerate.

Exercises the pure argv-construction logic. The subprocess-invoking
handlers themselves are covered by dvc repro integration.
"""
from __future__ import annotations

from scripts.dvc_regenerate import _pipeline_argv, PHASES  # pyright: ignore[reportMissingImports]


def test_phases_registered() -> None:
    assert set(PHASES) == {
        "phase0", "phase1", "phase2",
        "phase2_5", "phase2_5_reading_list",
        "phase3", "phase4_post", "phase4_audio",
    }


def test_pipeline_argv_transport_hostprep() -> None:
    cfg = {
        "novel": "bleak_house",
        "axes": {
            "pipeline": "trn",
            "hostprep": True,
            "generator": "anthropic_sonnet_4_6",
        },
    }
    argv = _pipeline_argv("bh_trn_literary_hostprep", cfg, phase=3, resume_from=3)
    assert "--name" in argv and "bh_trn_literary_hostprep" in argv
    assert "--novel" in argv and "bleak_house" in argv
    assert "--pipeline" in argv and "transport" in argv
    assert "--phase" in argv and "3" in argv
    assert "--resume-from" in argv and "3" in argv
    assert "--host-prep" in argv
    assert "--generator" in argv and "anthropic_sonnet_4_6" in argv


def test_pipeline_argv_no_passages_non_bh() -> None:
    cfg = {
        "novel": "mill_on_the_floss",
        "axes": {"pipeline": "nop", "hostprep": False},
    }
    argv = _pipeline_argv("motf_nop_literary", cfg, phase=3, resume_from=3)
    assert "mill_on_the_floss" in argv
    assert "no-passages" in argv
    assert "--host-prep" not in argv


def test_pipeline_argv_embedding() -> None:
    cfg = {"novel": "bleak_house", "axes": {"pipeline": "emb"}}
    argv = _pipeline_argv("bh_emb_literary", cfg, phase=3, resume_from=None)
    assert "embedding" in argv
    assert "--resume-from" not in argv


def test_pipeline_argv_unknown_pipeline_passes_through() -> None:
    """If the axis value isn't in the map, it's used verbatim (forward compat)."""
    cfg = {"novel": "bleak_house", "axes": {"pipeline": "custom_new_thing"}}
    argv = _pipeline_argv("bh_custom_test", cfg, phase=3, resume_from=3)
    assert "custom_new_thing" in argv
