"""Plain RAG passage assignment: embed expert profiles, retrieve by cosine similarity.

No enrichment metadata used in selection. No LLM curation. No arc/structure obligations.
Passages are assigned to experts purely by vector similarity between expert persona
descriptions and pre-embedded passage text.

This provides a lower baseline to measure the value of enrichment and structured
assignment in the transport and embedding pipelines.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import lancedb
import numpy as np
import openai
from pathlib import Path

from enrichment.podcast_types import (  # pyright: ignore[reportMissingImports]
    ExpertPersona,
    SegmentTemplate,
)
from enrichment.transport_podcast import (  # pyright: ignore[reportMissingImports]
    ExpertProfile,
)

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "bleak_house_vectors"
EMBEDDING_MODEL = "text-embedding-3-small"
# Use text-only embeddings: no enrichment context, themes, characters, or summary.
# This ensures the plain RAG baseline doesn't benefit from the enrichment pipeline.
TABLE_NAME = "passages_text_only"


@dataclass
class PlainRAGConfig:
    passage_target: int = 32
    db_path: str = str(DB_PATH)
    table_name: str = TABLE_NAME
    embedding_model: str = EMBEDDING_MODEL


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------


def _embed_texts(texts: list[str], model: str = EMBEDDING_MODEL) -> list[np.ndarray]:
    """Embed a list of texts using OpenAI."""
    client = openai.OpenAI()
    response = client.embeddings.create(input=texts, model=model)
    return [np.array(d.embedding, dtype=np.float32) for d in response.data]


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    dot = float(np.dot(a, b))
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    return dot / norm if norm > 0 else 0.0


# ---------------------------------------------------------------------------
# Query builders
# ---------------------------------------------------------------------------


def build_expert_query(_profile: ExpertProfile, persona: ExpertPersona) -> str:
    """Build a natural-language query from expert persona description."""
    return (
        f"{persona.name}, {persona.role}.\n"
        f"{persona.description}\n"
        f"Speaking style: {persona.speaking_style}"
    )


def build_segment_query(template: SegmentTemplate) -> str:
    """Build a query from segment template."""
    parts = [f"Segment: {template.name}", f"Type: {template.segment_type}"]
    if template.preferred_dimensions:
        dims = ", ".join(d.replace("prov_", "") for d in template.preferred_dimensions)
        parts.append(f"Focus: {dims}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Core assignment
# ---------------------------------------------------------------------------


def assign_passages_plain_rag(
    experts: list[ExpertProfile],
    personas: list[ExpertPersona],
    templates: list[SegmentTemplate],
    enrichment_data: list[dict],
    config: PlainRAGConfig,
) -> tuple[dict, dict]:
    """Assign passages to experts by cosine similarity. Returns (phase1, phase2)."""

    # Build enrichment lookup by passage_id
    enrich_lookup: dict[str, dict] = {}
    for p in enrichment_data:
        pid = p["passage_id"]
        enrich_lookup[pid] = p

    # Load passage vectors from LanceDB
    logger.info("Loading passage vectors from LanceDB")
    db = lancedb.connect(config.db_path)
    table = db.open_table(config.table_name)
    df = table.to_pandas()

    # Filter to only Bleak House chapters (c1-c67, not F2/F3 front matter)
    df = df[df["chapter_id"].str.match(r"^c\d+$")]
    logger.info("  %d Bleak House passages with vectors", len(df))

    passage_ids = df["passage_id"].tolist()
    passage_vecs = np.stack(df["vector"].values)

    # Build expert and segment queries
    persona_lookup = {p.name: p for p in personas}
    expert_queries = []
    for exp in experts:
        persona = persona_lookup.get(exp.name)
        if persona:
            expert_queries.append(build_expert_query(exp, persona))
        else:
            expert_queries.append(f"{exp.name}, {exp.role}")

    segment_queries = [build_segment_query(t) for t in templates]

    # Embed all queries
    all_queries = expert_queries + segment_queries
    logger.info("Embedding %d queries (%d expert + %d segment)",
                len(all_queries), len(expert_queries), len(segment_queries))
    query_vecs = _embed_texts(all_queries, config.embedding_model)

    expert_vecs = query_vecs[:len(experts)]
    segment_vecs = query_vecs[len(experts):]

    # Compute similarities: experts × passages
    expert_sims = np.array([
        [_cosine_similarity(ev, pv) for pv in passage_vecs]
        for ev in expert_vecs
    ])  # shape: (n_experts, n_passages)

    # Compute similarities: segments × passages
    segment_sims = np.array([
        [_cosine_similarity(sv, pv) for pv in passage_vecs]
        for sv in segment_vecs
    ])  # shape: (n_segments, n_passages)

    # --- Step 1: Select top-k per expert ---
    per_expert = math.ceil(config.passage_target / len(experts))
    selected: dict[int, tuple[int, float]] = {}  # passage_idx -> (expert_idx, sim)

    for exp_idx in range(len(experts)):
        ranked = np.argsort(-expert_sims[exp_idx])
        count = 0
        for pidx in ranked:
            pidx = int(pidx)
            if pidx in selected:
                # Already claimed — keep if this expert has higher sim
                _, existing_sim = selected[pidx]
                if expert_sims[exp_idx, pidx] > existing_sim:
                    selected[pidx] = (exp_idx, float(expert_sims[exp_idx, pidx]))
            else:
                selected[pidx] = (exp_idx, float(expert_sims[exp_idx, pidx]))
                count += 1
            if count >= per_expert:
                break

    # If under target, fill from highest unselected similarities across all experts
    if len(selected) < config.passage_target:
        all_sims = expert_sims.max(axis=0)  # best expert sim per passage
        ranked_all = np.argsort(-all_sims)
        for pidx in ranked_all:
            pidx = int(pidx)
            if pidx not in selected:
                best_exp = int(np.argmax(expert_sims[:, pidx]))
                selected[pidx] = (best_exp, float(expert_sims[best_exp, pidx]))
            if len(selected) >= config.passage_target:
                break

    # Cap at target
    if len(selected) > config.passage_target:
        by_sim = sorted(selected.items(), key=lambda x: -x[1][1])
        selected = dict(by_sim[:config.passage_target])

    logger.info("Selected %d passages", len(selected))

    # --- Step 2: Build assignments ---
    assignments: list[dict] = []
    for pidx, (exp_idx, sim) in selected.items():
        pid = passage_ids[pidx]
        exp_name = experts[exp_idx].name
        row = df.iloc[pidx]

        # Get enrichment data for full fields
        enrich = enrich_lookup.get(pid, {})
        enrichment = enrich.get("enrichment", {})

        provisions = {}
        for dim in [
            "prov_character_development", "prov_plot_advancement",
            "prov_thematic_depth", "prov_social_critique",
            "prov_humor_entertainment", "prov_atmosphere_setting",
            "prov_narrative_technique",
        ]:
            provisions[dim] = enrichment.get(dim, "none")

        assignments.append({
            "passage_id": pid,
            "expert": exp_name,
            "dimension": "rag_similarity",
            "arc_name": None,
            "cost": 0,
            "chapter_id": str(row["chapter_id"]),
            "interest_score": int(row["interest_score"]),
            "characters_present": enrichment.get("characters_present", []),
            "provisions": provisions,
            "text": str(row["text"]),
            "summary": str(row.get("summary", "")),
            "best_quote": enrichment.get("best_quote", ""),
            "themes": enrichment.get("themes", []),
            "emotional_register": enrichment.get("emotional_register", []),
            "narrator": str(row.get("narrator", "unknown")),
        })

    # Sort by chapter for readability
    assignments.sort(key=lambda a: a["passage_id"])

    phase1 = {
        "pipeline_type": "plain_rag",
        "count": len(assignments),
        "assignments": assignments,
    }

    # --- Step 3: Assign to segments ---
    # For each passage, compute segment similarity and greedily fill
    seg_capacities = {i: t.max_passages for i, t in enumerate(templates)}
    seg_assignments: dict[int, list[dict]] = {i: [] for i in range(len(templates))}

    # Score each selected passage against each segment
    passage_seg_scores: list[tuple[int, int, float]] = []
    for pidx, (exp_idx, _) in selected.items():
        for seg_idx in range(len(templates)):
            passage_seg_scores.append((pidx, seg_idx, float(segment_sims[seg_idx, pidx])))

    passage_seg_scores.sort(key=lambda x: -x[2])
    assigned_passages: set[int] = set()

    for pidx, seg_idx, score in passage_seg_scores:
        if pidx in assigned_passages:
            continue
        if len(seg_assignments[seg_idx]) >= seg_capacities[seg_idx]:
            continue
        # Find the assignment dict for this passage
        pid = passage_ids[pidx]
        for a in assignments:
            if a["passage_id"] == pid:
                seg_assignments[seg_idx].append(a)
                assigned_passages.add(pidx)
                break

    # Any unassigned → segment with fewest passages
    for pidx in selected:
        if pidx in assigned_passages:
            continue
        pid = passage_ids[pidx]
        min_seg = min(seg_assignments, key=lambda s: len(seg_assignments[s]))
        for a in assignments:
            if a["passage_id"] == pid:
                seg_assignments[min_seg].append(a)
                assigned_passages.add(pidx)
                break

    segments_out = []
    for seg_idx, template in enumerate(templates):
        seg_a = seg_assignments[seg_idx]
        segments_out.append({
            "template": template.model_dump(),
            "assignments": [
                {
                    "passage_id": a["passage_id"],
                    "expert": a["expert"],
                    "dimension": a["dimension"],
                    "arc_name": a["arc_name"],
                    "chapter_id": a["chapter_id"],
                    "interest_score": a["interest_score"],
                }
                for a in seg_a
            ],
        })

    # Build report
    expert_counts = {}
    for a in assignments:
        expert_counts[a["expert"]] = expert_counts.get(a["expert"], 0) + 1
    chapter_set = {a["chapter_id"] for a in assignments}
    report_lines = [
        f"Plain RAG assignment: {len(assignments)} passages from {len(chapter_set)} chapters",
        f"Expert distribution: {expert_counts}",
        f"Segments: {', '.join(f'{t.name}({len(seg_assignments[i])})' for i, t in enumerate(templates))}",
    ]
    report = "\n".join(report_lines)

    phase2 = {
        "segments": segments_out,
        "total_null_flow": 0,
        "report": report,
    }

    return phase1, phase2
