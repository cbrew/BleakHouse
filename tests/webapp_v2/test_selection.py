"""Selection-rule tests for webapp_v2.selection.

Exercises the canonical-run picker against a fixture content.db built
with a deliberate cross-section of runs (multiple variants per
coordinate, audio/no-audio, short/long).
"""
from __future__ import annotations

from pathlib import Path

from webapp_v2.selection import canonical_run_for, list_canonical_episodes


def test_only_audio_bearing_buckets_surface(fixture_db: Path) -> None:
    eps = list_canonical_episodes()
    # bh literary, bh alternatives, wh literary — three buckets with audio.
    # ot literary has no audio, so it must be absent.
    keys = {(e.novel, e.panel) for e in eps}
    assert ("bleak_house", "literary") in keys
    assert ("bleak_house", "alternatives") in keys
    assert ("wuthering_heights", "literary") in keys
    assert ("oliver_twist", "literary") not in keys
    assert len(eps) == 3


def test_short_wins_over_long(fixture_db: Path) -> None:
    """bh alternatives has both bh_trn_alternatives (long) and
    bh_trn_alternatives_short — short must win invisibly."""
    ep = canonical_run_for("bleak_house", "alternatives")
    assert ep is not None
    assert ep.run_id == "bh_trn_alternatives_short"
    assert ep.length == "short"


def test_hostprep_wins_when_length_equal(fixture_db: Path) -> None:
    """bh literary has only one audio-bearing run (hostprep). Trivial
    case but confirms the rule selects it deterministically."""
    ep = canonical_run_for("bleak_house", "literary")
    assert ep is not None
    assert ep.run_id == "bh_trn_literary_hostprep"
    assert ep.hostprep is True


def test_canonical_run_for_returns_none_when_no_audio(fixture_db: Path) -> None:
    assert canonical_run_for("oliver_twist", "literary") is None


def test_canonical_run_for_returns_none_when_unknown_novel(fixture_db: Path) -> None:
    assert canonical_run_for("nonesuch_novel", "literary") is None
