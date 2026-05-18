"""Phase 0: LLM-driven segment design based on the expert panel.

Given the expert profiles and arc demands, ask a fast model (Haiku) to design
the episode segment structure.  This runs BEFORE Phase 1 so that segment
preferences can feed back into passage selection as supplementary demand.

The key output is twofold:
  1. A list of SegmentTemplate objects for Phase 2
  2. Supplementary dimension demand — demand implied by the segment structure
     that exceeds what experts already provide — fed into Phase 1

Usage (standalone test):
    uv run python -m enrichment.design_segments --experts default --arcs default
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from enrichment.llm.schemas import SegmentDesignResult, SegmentTemplate  # pyright: ignore[reportMissingImports]
from enrichment.personas import ExpertPersona
from enrichment.timing import Recorder
from enrichment.transport_podcast import (  # pyright: ignore[reportMissingImports]
    ArcDemand,
    ExpertProfile,
    load_passages,
)

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"

# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _novel_ref() -> str:
    """Return 'Author's *Title*' for the active novel."""
    from enrichment.novel_prompts import get_active_novel  # pyright: ignore[reportMissingImports]
    cfg = get_active_novel()
    return f"{cfg.author}'s *{cfg.title}*"


# Prompt templates moved to enrichment/llm/design_segments_prompts.py
# (2026-05-18, BleakHouse-mz2g). Aliases kept for in-file readability;
# all other importers should pull from the new location.

from enrichment.llm.design_segments_prompts import (  # noqa: E402
    SEGMENT_COUNT_LONG as _SEGMENT_COUNT_LONG,
    SEGMENT_COUNT_SHORT as _SEGMENT_COUNT_SHORT,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_V1,
    SYSTEM_PROMPT_V2,
    SYSTEM_PROMPT_V3,
    TOTAL_PASSAGES_LONG as _TOTAL_PASSAGES_LONG,
    TOTAL_PASSAGES_SHORT as _TOTAL_PASSAGES_SHORT,
)

PROVISION_DIMENSIONS = [
    "prov_character_development",
    "prov_plot_advancement",
    "prov_thematic_depth",
    "prov_social_critique",
    "prov_humor_entertainment",
    "prov_atmosphere_setting",
    "prov_narrative_technique",
]


def _build_supply_summary() -> str:
    """Summarise passage supply per provision dimension from enrichment data."""
    from collections import Counter

    passages = load_passages()
    lines = ["## Material Supply\n"]
    lines.append(
        f"Strong passages available per dimension (of {len(passages):,} total):"
    )
    for dim in PROVISION_DIMENSIONS:
        strengths: Counter[str] = Counter()
        for p in passages:
            strengths[p.provisions.get(dim, "none")] += 1
        lines.append(
            f"  {dim}: {strengths['strong']:>5,} strong, {strengths['weak']:>5,} weak"
        )

    interest: Counter[int] = Counter()
    for p in passages:
        interest[p.interest_score] += 1
    high = sum(v for k, v in interest.items() if k >= 4)
    lines.append(f"\nInterest distribution: {dict(sorted(interest.items()))}")
    lines.append(f"Only {high} passages score 4+ (genuinely remarkable material).")
    return "\n".join(lines)


def _build_panel_summary(
    experts: list[ExpertProfile],
    arcs: list[ArcDemand],
    personas: list[ExpertPersona] | None = None,
) -> str:
    persona_lookup = {p.name: p for p in personas} if personas else {}
    lines = ["## Expert Panel\n"]
    for exp in experts:
        demands = ", ".join(f"{k}={v}" for k, v in exp.demands.items() if v > 0)
        persona = persona_lookup.get(exp.name)
        if persona:
            lines.append(f"- **{exp.name}** ({exp.role}): {persona.description}")
            lines.append(f"  Demands: {demands}")
        else:
            lines.append(f"- **{exp.name}** ({exp.role}): demands {demands}")
    lines.append("\n## Character Arcs\n")
    for arc in arcs:
        lines.append(
            f"- **{arc.name}** (character: {arc.character}, "
            f"demand={arc.demand}, dimension={arc.require_field})"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

# SegmentDesignResult moved to enrichment/llm/schemas.py under
# BleakHouse-gfn2 (2026-05-18). Imported above; this file no longer
# defines an LLM-bound class.


def design_segments(
    experts: list[ExpertProfile],
    arcs: list[ArcDemand],
    prompt_version: int = 2,
    personas: list[ExpertPersona] | None = None,
    recorder: Recorder | None = None,
    length: str = "long",
) -> list[SegmentTemplate]:
    """Design segment templates for this panel configuration.

    Routes through the LLM seam (task='design_segments') so the active
    provider profile picks the model.

    prompt_version=1: original prompt (no supply info)
    prompt_version=2: supply-aware prompt (includes passage supply summary)
    prompt_version=3: v2 + expert persona descriptions for personality-aware design

    length: 'long' targets 5-8 segments / 25-35 passages / 45-60 min episodes;
    'short' targets 4-5 segments / 12-18 passages / 20-30 min episodes.
    """
    novel_ref = _novel_ref()

    if length == "short":
        segment_count_phrase = _SEGMENT_COUNT_SHORT
        total_passages_phrase = _TOTAL_PASSAGES_SHORT
    elif length == "long":
        segment_count_phrase = _SEGMENT_COUNT_LONG
        total_passages_phrase = _TOTAL_PASSAGES_LONG
    else:
        raise ValueError(f"unknown length {length!r} (expected 'long' or 'short')")

    if prompt_version >= 3:
        panel_summary = _build_panel_summary(experts, arcs, personas=personas)
        supply_summary = _build_supply_summary()
        user_msg = (
            f"{panel_summary}\n\n{supply_summary}\n\n"
            "Design the episode segments for this panel."
        )
        system = SYSTEM_PROMPT_V3.format(
            novel_ref=novel_ref,
            segment_count_phrase=segment_count_phrase,
            total_passages_phrase=total_passages_phrase,
        )
    elif prompt_version >= 2:
        panel_summary = _build_panel_summary(experts, arcs)
        supply_summary = _build_supply_summary()
        user_msg = (
            f"{panel_summary}\n\n{supply_summary}\n\n"
            "Design the episode segments for this panel."
        )
        system = SYSTEM_PROMPT_V2.format(
            novel_ref=novel_ref,
            segment_count_phrase=segment_count_phrase,
            total_passages_phrase=total_passages_phrase,
        )
    else:
        panel_summary = _build_panel_summary(experts, arcs)
        user_msg = (
            f"{panel_summary}\n\n"
            "Design the episode segments for this panel."
        )
        system = SYSTEM_PROMPT_V1.format(novel_ref=novel_ref)

    logger.info("Designing segments (v%d) via seam task='design_segments' ...", prompt_version)

    from enrichment.llm import generate as llm_generate
    from enrichment.llm.types import GenerationRequest

    import time as _time
    _t0 = _time.monotonic()
    result = llm_generate(GenerationRequest(
        task="design_segments",
        system=system,
        user=user_msg,
        max_tokens=4096,
        json_schema=SegmentDesignResult.model_json_schema(),
        # Reasoning-class models (gpt-5 family) would otherwise consume
        # the entire token budget on internal deliberation and emit
        # nothing visible. Structured extraction is the canonical
        # minimal-effort use case. Anthropic ignores the field.
        reasoning_effort="minimal",
    ))
    if recorder is not None:
        recorder.record(
            kind="model",
            name=result.model,
            label="phase0 segment design",
            duration_s=_time.monotonic() - _t0,
            started_at=_t0,
            input_tokens=result.input_tokens or 0,
            output_tokens=result.output_tokens or 0,
            cache_creation_input_tokens=result.cache_creation_input_tokens or 0,
            cache_read_input_tokens=result.cache_read_input_tokens or 0,
        )
    logger.info(
        "  Response: input_tokens=%d, output_tokens=%d",
        result.input_tokens or 0, result.output_tokens or 0,
    )

    parsed = SegmentDesignResult.model_validate_json(result.text)
    templates = parsed.segments
    logger.info("Designed %d segments: %s", len(templates), [t.name for t in templates])

    # Validate constraints
    types = [t.segment_type for t in templates]
    if types.count("opening") != 1:
        logger.warning("Expected 1 opening, got %d", types.count("opening"))
    if types.count("closing") != 1:
        logger.warning("Expected 1 closing, got %d", types.count("closing"))

    return templates


# ---------------------------------------------------------------------------
# Supplementary demand: what segments need beyond what experts already provide
# ---------------------------------------------------------------------------


@dataclass
class SupplementaryDemand:
    """Extra dimension demand implied by the segment structure."""

    dimension_boost: dict[str, int]  # prov_field -> additional units needed
    total_boost: int


def compute_supplementary_demand(
    templates: list[SegmentTemplate],
    experts: list[ExpertProfile],
) -> SupplementaryDemand:
    """Compare segment demand to expert supply and return the gap.

    For each dimension, take the largest min_passages among segments that
    want it.  This represents the episode's structural minimum for that
    dimension — enough to fill the most demanding single segment.  Phase 2
    handles distributing across multiple segments.

    Compare to the total expert demand for that dimension.  Any shortfall
    becomes supplementary demand that Phase 1 should satisfy.
    """
    # Segment demand: for each dimension, take the max min_passages needed
    # by any single segment wanting it (passages are shared, not duplicated)
    segment_demand: dict[str, int] = {}
    for t in templates:
        for dim in t.preferred_dimensions:
            segment_demand[dim] = max(
                segment_demand.get(dim, 0), t.min_passages
            )

    # Expert supply: for each dimension, sum expert demands
    expert_supply: dict[str, int] = {}
    for exp in experts:
        for dim, demand in exp.demands.items():
            if demand > 0:
                expert_supply[dim] = expert_supply.get(dim, 0) + demand

    # Gap = segment demand - expert supply, floored at 0
    boost: dict[str, int] = {}
    for dim, seg_need in segment_demand.items():
        exp_have = expert_supply.get(dim, 0)
        gap = seg_need - exp_have
        if gap > 0:
            boost[dim] = gap
            logger.info(
                "  Segment demand for %s: %d, expert supply: %d → boost +%d",
                dim, seg_need, exp_have, gap,
            )

    total = sum(boost.values())
    if total > 0:
        logger.info("  Total supplementary demand: +%d units", total)
    else:
        logger.info("  No supplementary demand needed (experts cover all segment needs)")

    return SupplementaryDemand(dimension_boost=boost, total_boost=total)


# ---------------------------------------------------------------------------
# CLI for standalone testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser(description="Design segments for a panel")
    parser.add_argument(
        "--run", default=None,
        help="Load expert/arc config from a named run",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    from enrichment.run_config import RunConfig  # pyright: ignore[reportMissingImports]

    if args.run:
        config = RunConfig.load(args.run)
        experts = config.experts
        arcs_list = config.arcs
    else:
        from enrichment.transport_podcast import (  # pyright: ignore[reportMissingImports]
            DEFAULT_ARCS,
            DEFAULT_EXPERTS,
        )
        experts = list(DEFAULT_EXPERTS)
        arcs_list = list(DEFAULT_ARCS)

    templates = design_segments(experts, arcs_list)
    supp = compute_supplementary_demand(templates, experts)

    print(f"\n{'='*60}")
    print(f"Designed {len(templates)} segments:")
    print(f"{'='*60}")
    for i, t in enumerate(templates):
        print(f"\n  {i+1}. {t.name} ({t.segment_type})")
        print(f"     Dimensions: {t.preferred_dimensions}")
        if t.preferred_arcs:
            print(f"     Arcs: {t.preferred_arcs}")
        if t.preferred_experts:
            print(f"     Lead: {t.preferred_experts}")
        print(f"     Passages: {t.min_passages}-{t.max_passages}")
    print(f"\n  Total capacity: {sum(t.max_passages for t in templates)} max passages")

    if supp.total_boost > 0:
        print(f"\n  Supplementary demand: {supp.dimension_boost}")
    else:
        print("\n  No supplementary demand (experts cover all segment needs)")
