"""Embedding-only podcast pipeline: retrieval + LLM curation.

Replaces Phases 1+2 of the transport pipeline with:
  1. Multi-query vector retrieval to build a candidate pool
  2. LLM curation to select and assign passages to experts and segments

The output is compatible with Phase 3 (generate_podcast.py).

Usage: called from embedding_run.py, not standalone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import anthropic
import lancedb
from enrichment.llm.schemas import (  # pyright: ignore[reportMissingImports]
    CuratedAssignment,
    CurationResult,
    SegmentTemplate,
)
from enrichment.timing import Recorder, time_model
from enrichment.transport_podcast import (  # pyright: ignore[reportMissingImports]
    ArcDemand,
    ExpertProfile,
    PROVISION_DIMENSIONS,
)

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "bleak_house_vectors"

# Novel data override: set via BLEAKHOUSE_NOVEL env var
def _db_path() -> Path:
    import os
    novel = os.environ.get("BLEAKHOUSE_NOVEL")
    if novel and novel != "bleak_house":
        return DATA_DIR / "novels" / novel / "vectors"
    return DB_PATH

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DIMENSION_DESCRIPTIONS: dict[str, str] = {
    "prov_character_development": (
        "character development, transformation, and psychological depth"
    ),
    "prov_plot_advancement": (
        "plot advancement, revelations, and story progression"
    ),
    "prov_thematic_depth": (
        "thematic resonance with justice, identity, class, and institutional failure"
    ),
    "prov_social_critique": (
        "social critique of institutions, law, poverty, and class"
    ),
    "prov_humor_entertainment": (
        "humor, comedy, satire, and dramatic entertainment"
    ),
    "prov_atmosphere_setting": (
        "atmosphere, mood, setting, and sense of place"
    ),
    "prov_narrative_technique": (
        "literary technique — irony, foreshadowing, imagery, symbolism"
    ),
}


@dataclass
class RetrievalConfig:
    """Parameters for the embedding retrieval + curation phase."""

    candidates_per_query: int = 15
    total_candidate_cap: int = 100  # deduplicated pool ceiling
    final_passage_target: int = 32
    min_interest_score: int = 2
    curation_model: str = "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Step 1: Multi-query retrieval
# ---------------------------------------------------------------------------


@dataclass
class RetrievalQuery:
    """A single vector search query with optional metadata filters."""

    text: str
    source: str  # e.g. "expert:Eleanor Hartley x segment:Opening"
    filters: list[str] = field(default_factory=list)
    top_k: int = 15


@dataclass
class CandidatePassage:
    """A retrieved passage with its enrichment metadata and retrieval score."""

    passage_id: str
    chapter_id: str
    text: str
    summary: str
    best_quote: str
    narrator: str
    interest_score: int
    characters_present: list[str]
    themes: list[str]
    emotional_register: list[str]
    provisions: dict[str, str]  # prov_field -> none/weak/strong
    # Retrieval metadata
    best_distance: float = 999.0
    query_hits: int = 0  # how many queries returned this passage


def _compose_query_text(
    expert: ExpertProfile | None,
    segment: SegmentTemplate | None,
    arc: ArcDemand | None,
) -> str:
    """Build a natural-language query paragraph from expert/segment/arc context."""
    parts: list[str] = []

    if expert:
        dim_prose = [
            DIMENSION_DESCRIPTIONS[d]
            for d in expert.demands
            if expert.demands[d] > 0 and d in DIMENSION_DESCRIPTIONS
        ]
        parts.append(
            f"From the perspective of a {expert.role} interested in "
            f"{', '.join(dim_prose)}."
        )

    if segment:
        seg_dims: list[str] = [
            DIMENSION_DESCRIPTIONS.get(d) or d for d in segment.preferred_dimensions
        ]
        parts.append(
            f"For a podcast segment about {segment.name}: {', '.join(seg_dims)}."
        )
        if segment.preferred_arcs:
            parts.append(f"Tracking character arcs: {', '.join(segment.preferred_arcs)}.")

    if arc:
        parts.append(
            f"Passages featuring {arc.character} relevant to {arc.name}."
        )

    if not parts:
        from enrichment.novel_prompts import get_active_novel  # pyright: ignore[reportMissingImports]
        cfg = get_active_novel()
        parts.append(f"Interesting and quotable passages from {cfg.title}.")

    return " ".join(parts)


def build_retrieval_queries(
    experts: list[ExpertProfile],
    arcs: list[ArcDemand],
    templates: list[SegmentTemplate],
    config: RetrievalConfig,
) -> list[RetrievalQuery]:
    """Generate the full set of vector search queries."""
    queries: list[RetrievalQuery] = []

    # 1. Per (expert, segment) — most targeted
    for exp in experts:
        exp_dims = {d for d, v in exp.demands.items() if v > 0}
        for seg in templates:
            seg_dims = set(seg.preferred_dimensions)
            # Only pair if there's dimensional overlap or expert is preferred
            if exp_dims & seg_dims or exp.name in seg.preferred_experts:
                queries.append(RetrievalQuery(
                    text=_compose_query_text(exp, seg, arc=None),
                    source=f"expert:{exp.name} x segment:{seg.name}",
                    top_k=config.candidates_per_query,
                ))

    # 2. Per arc — character-focused
    for arc in arcs:
        queries.append(RetrievalQuery(
            text=_compose_query_text(expert=None, segment=None, arc=arc),
            source=f"arc:{arc.name}",
            filters=[f"characters LIKE '%{arc.character}%'"],
            top_k=config.candidates_per_query,
        ))

    # 3. Per expert — broad
    for exp in experts:
        queries.append(RetrievalQuery(
            text=_compose_query_text(exp, segment=None, arc=None),
            source=f"expert:{exp.name}",
            top_k=config.candidates_per_query,
        ))

    # 4. Per segment — thematic
    for seg in templates:
        queries.append(RetrievalQuery(
            text=_compose_query_text(expert=None, segment=seg, arc=None),
            source=f"segment:{seg.name}",
            top_k=config.candidates_per_query,
        ))

    logger.info("Built %d retrieval queries", len(queries))
    return queries


def retrieve_candidate_pool(
    queries: list[RetrievalQuery],
    enrichment_data: list[dict],
    config: RetrievalConfig,
) -> list[CandidatePassage]:
    """Execute all queries against LanceDB and build a deduplicated candidate pool."""
    db = lancedb.connect(str(_db_path()))
    table = db.open_table("passages")

    enr_map: dict[str, dict] = {}
    for p in enrichment_data:
        enr_map[p["passage_id"]] = p

    pool: dict[str, CandidatePassage] = {}

    for q in queries:
        search = table.search(q.text, query_type="vector")

        if q.filters:
            search = search.where(" AND ".join(q.filters))

        try:
            results = search.limit(q.top_k).to_pandas()
        except Exception as e:
            logger.warning("Query '%s' failed: %s", q.source, e)
            continue

        for _, row in results.iterrows():
            pid = row["passage_id"]
            distance = float(row.get("_distance", 999.0))

            if pid in pool:
                pool[pid].query_hits += 1
                pool[pid].best_distance = min(pool[pid].best_distance, distance)
                continue

            raw = enr_map.get(pid, {})
            enr = raw.get("enrichment", {})

            interest = int(enr.get("interest_score", 0))
            if interest < config.min_interest_score:
                continue

            provisions = {
                dim: enr.get(dim, "none") for dim in PROVISION_DIMENSIONS
            }

            pool[pid] = CandidatePassage(
                passage_id=pid,
                chapter_id=raw.get("chapter_id", row.get("chapter_id", "")),
                text=raw.get("text", row.get("text", "")),
                summary=enr.get("summary", ""),
                best_quote=enr.get("best_quote", ""),
                narrator=enr.get("narrator", row.get("narrator", "")),
                interest_score=interest,
                characters_present=enr.get("characters_present", []),
                themes=enr.get("themes", []),
                emotional_register=enr.get("emotional_register", []),
                provisions=provisions,
                best_distance=distance,
                query_hits=1,
            )

    # Sort by composite score: query_hits (desc), distance (asc), interest (desc)
    candidates = sorted(
        pool.values(),
        key=lambda c: (-c.query_hits, c.best_distance, -c.interest_score),
    )

    # Cap the pool
    if len(candidates) > config.total_candidate_cap:
        candidates = candidates[: config.total_candidate_cap]

    logger.info(
        "Candidate pool: %d passages from %d queries (filtered from %d raw hits)",
        len(candidates),
        len(queries),
        sum(c.query_hits for c in candidates),
    )
    return candidates


# ---------------------------------------------------------------------------
# Step 2: LLM curation
# ---------------------------------------------------------------------------


# CuratedAssignment and CurationResult moved to enrichment/llm/schemas.py
# under BleakHouse-gfn2 (2026-05-18). Imported above; this file no
# longer defines LLM-bound classes.


# CURATION_SYSTEM_PROMPT moved to enrichment/llm/curation_prompts.py
# (2026-05-18, BleakHouse-mz2g).
from enrichment.llm.curation_prompts import CURATION_SYSTEM_PROMPT  # noqa: E402


def _format_expert_profile(exp: ExpertProfile) -> str:
    demands = ", ".join(
        f"{d}={v}" for d, v in exp.demands.items() if v > 0
    )
    return f"**{exp.name}** ({exp.role}): demands {demands}"


def _format_segment_profile(seg: SegmentTemplate) -> str:
    parts = [f"**{seg.name}** ({seg.segment_type})"]
    parts.append(f"  Dimensions: {', '.join(seg.preferred_dimensions)}")
    if seg.preferred_arcs:
        parts.append(f"  Arcs: {', '.join(seg.preferred_arcs)}")
    if seg.preferred_experts:
        parts.append(f"  Lead experts: {', '.join(seg.preferred_experts)}")
    parts.append(f"  Passages: {seg.min_passages}-{seg.max_passages}")
    return "\n".join(parts)


def _format_arc_profile(arc: ArcDemand) -> str:
    dim_desc = DIMENSION_DESCRIPTIONS.get(arc.require_field) or arc.require_field
    return (
        f"- **{arc.name}**: MUST select {arc.demand} passages featuring "
        f"{arc.character}.  Required dimension: {arc.require_field} "
        f"({dim_desc}) must be weak or strong.  "
        f"Prefer interest_score >= {arc.prefer_min_interest}."
    )


def _format_candidate(c: CandidatePassage) -> str:
    """Format one candidate for the curation prompt — metadata only, no full text."""
    prov_str = ", ".join(
        f"{d.replace('prov_', '')}={v}" for d, v in c.provisions.items() if v != "none"
    )
    chars = ", ".join(c.characters_present[:5]) if c.characters_present else "none"
    themes = ", ".join(c.themes[:5]) if c.themes else "none"
    emotion = ", ".join(c.emotional_register[:3]) if c.emotional_register else ""
    quote = f'  Quote: "{c.best_quote[:120]}"' if c.best_quote else ""

    lines = [
        f"### {c.passage_id} ({c.chapter_id})",
        f"  Interest: {c.interest_score} | Narrator: {c.narrator}",
        f"  Provisions: {prov_str or 'none strong/weak'}",
        f"  Characters: {chars}",
        f"  Themes: {themes}",
    ]
    if emotion:
        lines.append(f"  Register: {emotion}")
    if c.summary:
        lines.append(f"  Summary: {c.summary[:150]}")
    if quote:
        lines.append(quote)
    return "\n".join(lines)


def _compute_structure_demand(
    templates: list[SegmentTemplate],
    experts: list[ExpertProfile],
) -> dict[str, int]:
    """Compute supplementary demand: dimensions segments need but experts don't cover.

    Same logic as design_segments.compute_supplementary_demand but inlined to
    avoid circular import issues.
    """
    # Segment demand: for each dimension, take the max min_passages
    seg_demand: dict[str, int] = {}
    for t in templates:
        for dim in t.preferred_dimensions:
            seg_demand[dim] = max(seg_demand.get(dim, 0), t.min_passages)

    # Expert supply: for each dimension, sum expert demands
    exp_supply: dict[str, int] = {}
    for exp in experts:
        for dim, demand in exp.demands.items():
            if demand > 0:
                exp_supply[dim] = exp_supply.get(dim, 0) + demand

    # Gap
    boost: dict[str, int] = {}
    for dim, need in seg_demand.items():
        have = exp_supply.get(dim, 0)
        gap = need - have
        if gap > 0:
            boost[dim] = gap
    return boost


def _format_structure_demand(boost: dict[str, int]) -> str:
    if not boost:
        return "No structural gaps — experts and arcs cover all segment needs."
    lines = ["The following dimensions have gaps between what segments need and "
             "what experts supply.  Fill these with structure assignments "
             "(assignment_type=\"structure\", expert=\"_episode_structure\"):"]
    for dim, count in boost.items():
        desc = DIMENSION_DESCRIPTIONS.get(dim) or dim
        lines.append(f"- {dim} ({desc}): {count} additional passage(s) needed")
    lines.append(f"\nTotal structure passages needed: {sum(boost.values())}")
    return "\n".join(lines)


def curate_passages(
    candidates: list[CandidatePassage],
    experts: list[ExpertProfile],
    arcs: list[ArcDemand],
    templates: list[SegmentTemplate],
    config: RetrievalConfig,
    recorder: Recorder | None = None,
) -> CurationResult:
    """Ask the LLM to select and assign passages from the candidate pool."""
    total_min = sum(t.min_passages for t in templates)
    total_max = sum(t.max_passages for t in templates)
    arc_total = sum(a.demand for a in arcs)
    structure_boost = _compute_structure_demand(templates, experts)
    structure_total = sum(structure_boost.values())
    target = min(config.final_passage_target, total_max)
    n_experts = len(experts)
    # Expert passages = target minus arc and structure slots
    expert_budget = max(0, target - arc_total - structure_total)
    min_per = max(1, expert_budget // (n_experts + 1))
    max_per = max(min_per + 1, expert_budget - (n_experts - 1) * min_per)

    from enrichment.novel_prompts import get_active_novel  # pyright: ignore[reportMissingImports]
    novel_cfg = get_active_novel()

    system = CURATION_SYSTEM_PROMPT.format(
        target=target,
        pool_size=len(candidates),
        novel_title=novel_cfg.title,
        expert_profiles="\n\n".join(_format_expert_profile(e) for e in experts),
        segment_profiles="\n\n".join(_format_segment_profile(s) for s in templates),
        arc_profiles="\n\n".join(_format_arc_profile(a) for a in arcs),
        structure_demand=_format_structure_demand(structure_boost),
        min_per_expert=min_per,
        max_per_expert=max_per,
    )

    candidate_blocks = "\n\n".join(_format_candidate(c) for c in candidates)
    user_msg = (
        f"## Candidate Passages ({len(candidates)} total)\n\n"
        f"{candidate_blocks}\n\n"
        f"Select approximately {target} passages and assign each to one expert "
        f"and one segment.  Segment min/max bounds: total {total_min}-{total_max}."
    )

    logger.info(
        "Curation prompt: ~%d chars system, ~%d chars user (%d candidates)",
        len(system),
        len(user_msg),
        len(candidates),
    )

    client = anthropic.Anthropic()
    response = time_model(
        recorder,
        "phase1_2 embedding curation",
        lambda: client.messages.parse(
            model=config.curation_model,
            max_tokens=8192,
            system=system,
            messages=[{"role": "user", "content": user_msg}],
            output_format=CurationResult,
        ),
    )

    logger.info(
        "Curation response: stop_reason=%s, input_tokens=%d, output_tokens=%d",
        response.stop_reason,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )

    assert response.parsed_output is not None, "Curation structured output parsing failed"
    result = response.parsed_output

    logger.info(
        "Curated %d passages. Strategy: %s",
        len(result.assignments),
        result.strategy[:120],
    )
    return result


# ---------------------------------------------------------------------------
# Step 3: Convert to Phase 3-compatible format
# ---------------------------------------------------------------------------


def build_phase_outputs(
    curation: CurationResult,
    candidates: list[CandidatePassage],
    enrichment_data: list[dict],
    templates: list[SegmentTemplate],
) -> tuple[dict, dict]:
    """Convert curation results to phase1 and phase2 JSON formats.

    Returns (phase1_data, phase2_data) compatible with run_phase3().
    """
    # Build lookup maps
    cand_map = {c.passage_id: c for c in candidates}
    enr_map: dict[str, dict] = {}
    for p in enrichment_data:
        enr_map[p["passage_id"]] = p

    # Build PassageAssignment dicts (phase1 format)
    phase1_assignments: list[dict] = []
    for ca in curation.assignments:
        cand = cand_map.get(ca.passage_id)
        raw = enr_map.get(ca.passage_id, {})
        enr = raw.get("enrichment", {})

        pa_dict = {
            "passage_id": ca.passage_id,
            "expert": ca.expert,
            "dimension": ca.dimension,
            "arc_name": ca.arc_name or None,
            "cost": 0,  # no transport cost in embedding pipeline
            "chapter_id": cand.chapter_id if cand else raw.get("chapter_id", ""),
            "interest_score": cand.interest_score if cand else int(enr.get("interest_score", 0)),
            "characters_present": cand.characters_present if cand else enr.get("characters_present", []),
            "provisions": cand.provisions if cand else {},
            "text": cand.text if cand else raw.get("text", ""),
            "summary": cand.summary if cand else enr.get("summary", ""),
            "best_quote": cand.best_quote if cand else enr.get("best_quote", ""),
            "themes": cand.themes if cand else enr.get("themes", []),
            "emotional_register": cand.emotional_register if cand else enr.get("emotional_register", []),
            "narrator": cand.narrator if cand else enr.get("narrator", ""),
        }

        phase1_assignments.append(pa_dict)

    phase1_data = {
        "assignments": phase1_assignments,
        "count": len(phase1_assignments),
    }

    # Group into segments (phase2 format)
    template_map = {t.name: t for t in templates}
    seg_groups: dict[str, list[dict]] = {t.name: [] for t in templates}

    for ca, pa_dict in zip(curation.assignments, phase1_assignments):
        seg_name = ca.segment_name
        # Fuzzy match if LLM didn't use exact segment name
        if seg_name not in seg_groups:
            for tname in seg_groups:
                if seg_name.lower() in tname.lower() or tname.lower() in seg_name.lower():
                    seg_name = tname
                    break
            else:
                # Fall back to first non-full segment
                for tname in seg_groups:
                    tmpl = template_map[tname]
                    if len(seg_groups[tname]) < tmpl.max_passages:
                        seg_name = tname
                        break

        if seg_name in seg_groups:
            seg_groups[seg_name].append({
                "passage_id": pa_dict["passage_id"],
                "chapter_id": pa_dict["chapter_id"],
                "expert": pa_dict["expert"],
                "dimension": pa_dict["dimension"],
                "interest_score": pa_dict["interest_score"],
                "arc_name": pa_dict["arc_name"],
            })

    segments_out = []
    for t in templates:
        assignments = seg_groups.get(t.name, [])
        # Sort by chapter order
        assignments.sort(key=lambda a: a["chapter_id"])
        segments_out.append({
            "template": t.model_dump(),
            "assignments": assignments,
        })

    phase2_data = {
        "segments": segments_out,
        "total_null_flow": 0,
        "report": _build_curation_report(curation, templates, seg_groups),
    }

    return phase1_data, phase2_data


def _build_curation_report(
    curation: CurationResult,
    templates: list[SegmentTemplate],
    seg_groups: dict[str, list[dict]],
) -> str:
    """Build a human-readable report of the curation results."""
    lines = [
        "=" * 60,
        "EMBEDDING PIPELINE: CURATION REPORT",
        "=" * 60,
        "",
        f"Strategy: {curation.strategy}",
        f"Total passages selected: {len(curation.assignments)}",
        "",
    ]

    # Per-segment summary
    for t in templates:
        assigned = seg_groups.get(t.name, [])
        status = "OK" if t.min_passages <= len(assigned) <= t.max_passages else "!"
        lines.append(
            f"  [{status}] {t.name}: {len(assigned)} passages "
            f"(target {t.min_passages}-{t.max_passages})"
        )

    # By assignment type
    type_counts: dict[str, int] = {}
    expert_counts: dict[str, int] = {}
    arc_counts: dict[str, int] = {}
    for ca in curation.assignments:
        atype = ca.assignment_type
        type_counts[atype] = type_counts.get(atype, 0) + 1
        if atype == "expert" and ca.expert:
            expert_counts[ca.expert] = expert_counts.get(ca.expert, 0) + 1
        if atype == "arc" and ca.arc_name:
            arc_counts[ca.arc_name] = arc_counts.get(ca.arc_name, 0) + 1

    lines.append("")
    lines.append("  Assignment types:")
    for atype, count in sorted(type_counts.items()):
        lines.append(f"    {atype}: {count} passages")

    if expert_counts:
        lines.append("")
        lines.append("  Expert assignments:")
        for exp, count in sorted(expert_counts.items()):
            lines.append(f"    {exp}: {count} passages")

    if arc_counts:
        lines.append("")
        lines.append("  Arc assignments:")
        for arc, count in sorted(arc_counts.items()):
            lines.append(f"    {arc}: {count} passages")

    # Chapter coverage
    chapters = {ca.passage_id.split(":")[0] for ca in curation.assignments}
    lines.append(f"\n  Chapters covered: {len(chapters)}")
    lines.append("")

    return "\n".join(lines)
