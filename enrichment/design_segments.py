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

import anthropic
from pydantic import BaseModel, Field

from enrichment.podcast_types import ExpertPersona, SegmentTemplate  # pyright: ignore[reportMissingImports]
from enrichment.timing import Recorder, time_model
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


SYSTEM_PROMPT = """\
You are a podcast producer designing the segment structure for a literary \
analysis episode about {novel_ref}.

You will be given:
1. The expert panel (names, roles, and the analytical dimensions each cares about)
2. The character arcs being tracked and their importance

Your job: design 5-8 episode segments that make editorial sense for THIS \
specific panel.  Each segment needs:
- A compelling title (e.g. "The Fog and What It Hides", not just "Opening")
- A segment_type (opening, deep_dive, discussion, close_reading, closing)
- Which analytical dimensions it should draw from (prov_* field names)
- Which character arcs it should track (exact arc names from the input, or empty)
- Which experts should lead (exact expert names from the input, or empty for any)
- min/max passage counts (2-3 for short segments, 3-6 for deep dives)

Design principles:
- The opening should set the scene; the closing should synthesise
- Give each expert at least one segment where they lead
- Give each tracked arc at least one segment where it features
- Segment titles should be evocative and specific to the novel, not generic
- Total max_passages across all segments should be 25-35 (a 45-60 minute episode)
- Exactly one opening and one closing segment
- Only use dimensions that at least one expert demands or one arc requires — \
don't create demand for dimensions nobody on the panel cares about

Available dimensions (prov_* fields from the enrichment schema):
  prov_character_development, prov_plot_advancement, prov_thematic_depth,
  prov_social_critique, prov_humor_entertainment, prov_atmosphere_setting,
  prov_narrative_technique
"""

# V1 is the original prompt above; V2 adds supply awareness
SYSTEM_PROMPT_V1 = SYSTEM_PROMPT

SYSTEM_PROMPT_V2 = """\
You are a podcast producer designing the segment structure for a literary \
analysis episode about {novel_ref}.

You will be given:
1. The expert panel (names, roles, and the analytical dimensions each cares about)
2. The character arcs being tracked and their importance
3. The material supply — how many strong and weak passages exist per dimension

Your job: design 5-8 episode segments that make editorial sense for THIS \
specific panel.  Each segment needs:
- A compelling title (e.g. "The Fog and What It Hides", not just "Opening")
- A segment_type (opening, deep_dive, discussion, close_reading, closing)
- Which analytical dimensions it should draw from (prov_* field names)
- Which character arcs it should track (exact arc names from the input, or empty)
- Which experts should lead (exact expert names from the input, or empty for any)
- min/max passage counts (2-3 for short segments, 3-6 for deep dives)

Design principles:
- The opening should set the scene; the closing should synthesise
- Give each expert at least one segment where they lead
- Give each tracked arc at least one segment where it features
- Segment titles should be evocative and specific to the novel, not generic
- Total max_passages across all segments should be 25-35 (a 45-60 minute episode)
- Exactly one opening and one closing segment
- Only use dimensions that at least one expert demands or one arc requires — \
don't create demand for dimensions nobody on the panel cares about
- Weight segments toward dimensions with abundant strong supply.  \
A deep_dive on a scarce dimension (e.g. atmosphere_setting with few hundred \
strong passages) risks thin material.  A deep_dive on a rich dimension \
(e.g. character_development with 1,000+ strong passages) can draw from the best.

Available dimensions (prov_* fields from the enrichment schema):
  prov_character_development, prov_plot_advancement, prov_thematic_depth,
  prov_social_critique, prov_humor_entertainment, prov_atmosphere_setting,
  prov_narrative_technique
"""

SYSTEM_PROMPT_V3 = """\
You are a podcast producer designing the segment structure for a literary \
analysis episode about {novel_ref}.

You will be given:
1. The expert panel — names, roles, analytical dimensions, AND full \
personality/perspective descriptions
2. The character arcs being tracked and their importance
3. The material supply — how many strong and weak passages exist per dimension

Your job: design 5-8 episode segments that make editorial sense for THIS \
specific panel.  Each segment needs:
- A compelling title (e.g. "The Fog and What It Hides", not just "Opening")
- A segment_type (opening, deep_dive, discussion, close_reading, closing)
- Which analytical dimensions it should draw from (prov_* field names)
- Which character arcs it should track (exact arc names from the input, or empty)
- Which experts should lead (exact expert names from the input, or empty for any)
- min/max passage counts (2-3 for short segments, 3-6 for deep dives)

Design principles:
- The opening should set the scene; the closing should synthesise
- Give each expert at least one segment where they lead
- Give each tracked arc at least one segment where it features
- Segment titles should be evocative and specific to the novel, not generic
- Total max_passages across all segments should be 25-35 (a 45-60 minute episode)
- Exactly one opening and one closing segment
- Only use dimensions that at least one expert demands or one arc requires — \
don't create demand for dimensions nobody on the panel cares about
- Weight segments toward dimensions with abundant strong supply.  \
A deep_dive on a scarce dimension (e.g. atmosphere_setting with few hundred \
strong passages) risks thin material.  A deep_dive on a rich dimension \
(e.g. character_development with 1,000+ strong passages) can draw from the best.
- **Design segments that play to each expert's personality.**  A performer \
who hears rhythms should lead close_reading segments.  A historian who \
connects past to present should lead discussion segments on institutional \
themes.  A craft-obsessed writer should lead deep_dives on structure.  \
Match the segment type and topic to the expert's perspective, not just \
their demand dimensions.

Available dimensions (prov_* fields from the enrichment schema):
  prov_character_development, prov_plot_advancement, prov_thematic_depth,
  prov_social_critique, prov_humor_entertainment, prov_atmosphere_setting,
  prov_narrative_technique
"""

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

class SegmentDesignResult(BaseModel):
    """Wrapper for structured output: list of designed segments."""

    segments: list[SegmentTemplate] = Field(
        description="The designed episode segments (5-8 segments)"
    )


def design_segments(
    experts: list[ExpertProfile],
    arcs: list[ArcDemand],
    client: anthropic.Anthropic | None = None,
    model: str = MODEL,
    prompt_version: int = 2,
    personas: list[ExpertPersona] | None = None,
    recorder: Recorder | None = None,
) -> list[SegmentTemplate]:
    """Design segment templates for this panel configuration.

    prompt_version=1: original prompt (no supply info)
    prompt_version=2: supply-aware prompt (includes passage supply summary)
    prompt_version=3: v2 + expert persona descriptions for personality-aware design
    """
    if client is None:
        client = anthropic.Anthropic()

    novel_ref = _novel_ref()

    if prompt_version >= 3:
        panel_summary = _build_panel_summary(experts, arcs, personas=personas)
        supply_summary = _build_supply_summary()
        user_msg = (
            f"{panel_summary}\n\n{supply_summary}\n\n"
            "Design the episode segments for this panel."
        )
        system = SYSTEM_PROMPT_V3.format(novel_ref=novel_ref)
    elif prompt_version >= 2:
        panel_summary = _build_panel_summary(experts, arcs)
        supply_summary = _build_supply_summary()
        user_msg = (
            f"{panel_summary}\n\n{supply_summary}\n\n"
            "Design the episode segments for this panel."
        )
        system = SYSTEM_PROMPT_V2.format(novel_ref=novel_ref)
    else:
        panel_summary = _build_panel_summary(experts, arcs)
        user_msg = (
            f"{panel_summary}\n\n"
            "Design the episode segments for this panel."
        )
        system = SYSTEM_PROMPT_V1.format(novel_ref=novel_ref)

    logger.info("Designing segments (v%d) with %s ...", prompt_version, model)

    response = time_model(
        recorder,
        "phase0 segment design",
        lambda: client.messages.parse(
            model=model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
            output_format=SegmentDesignResult,
        ),
    )

    logger.info(
        "  Response: stop_reason=%s, input_tokens=%d, output_tokens=%d",
        response.stop_reason,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )

    assert response.parsed_output is not None, "Structured output parsing failed for segment design"
    templates = response.parsed_output.segments
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
