"""Centralised, novel-aware path resolution.

Each helper returns a resolved Path. Helpers DO NOT check whether the
file itself exists (that's the caller's choice — required vs. optional).
Helpers DO raise FileNotFoundError when the novel or run *directory*
is missing — at that point the input is wrong and no caller can
recover.

This module is the canonical answer to 'where is X for novel Y'. No
caller reconstructs paths bespoke; no caller has 'if novel ==
\"bleak_house\":' special cases. Adding a novel = registering it in
enrichment/axes.py + ensuring its data/novels/<id>/ directory exists.
"""
from __future__ import annotations

from pathlib import Path

# Repo root is two levels up from this file (cas/paths.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _REPO_ROOT / "data"


def _novel_dir(novel: str) -> Path:
    d = _DATA_DIR / "novels" / novel
    if not d.is_dir():
        raise FileNotFoundError(
            f"novel {novel!r} not registered: expected {d} to exist"
        )
    return d


def passages_enriched(novel: str, variant: str | None = None) -> Path:
    """Path to the enrichment file for `novel`.

    variant=None       → passages_enriched.json (canonical Anthropic-derived)
    variant="<suffix>" → passages_enriched.<suffix>.json (e.g. "openai_5_mini")

    The variant is a literal filename suffix; the caller picks a name that
    matches what the producer (e.g. enrichment.collect_passages_enriched_openai)
    actually writes. We do not validate that the variant file exists; that's
    the caller's choice (preflight checks read existence separately)."""
    name = (
        "passages_enriched.json"
        if variant is None
        else f"passages_enriched.{variant}.json"
    )
    return _novel_dir(novel) / name


def clusters_literary(novel: str) -> Path:
    return _novel_dir(novel) / "clusters_literary.json"


def clusters_characters(novel: str) -> Path:
    return _novel_dir(novel) / "clusters_characters.json"


def _run_dir(run_id: str) -> Path:
    d = _DATA_DIR / "runs" / run_id
    if not d.is_dir():
        raise FileNotFoundError(
            f"run {run_id!r} not found: expected {d} to exist"
        )
    return d


def assignments(run_id: str) -> Path:
    return _run_dir(run_id) / "phase1_assignments.json"


def reading_list(run_id: str) -> Path:
    return _run_dir(run_id) / "phase2_5_reading_list.json"


def episode(run_id: str) -> Path:
    return _run_dir(run_id) / "phase3_episode.json"


def shards_manifest(run_id: str) -> Path:
    return _run_dir(run_id) / "audio" / "shards.json"


def audio_assets(run_id: str) -> Path:
    return _run_dir(run_id) / "audio" / "assets.json"
