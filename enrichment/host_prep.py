"""Phase 2.5: Host preparation — pre-interviews and question planning.

Phase 2.5a: For each expert–segment pair, a short Haiku interview extracts
what the expert finds most interesting, what they'd quote, and where they
might disagree with others.

Phase 2.5b: For each segment, Sonnet synthesises all experts' interviews
into a HostBrief with 3–5 targeted questions and steering notes.

Usage (standalone, for testing):
    uv run python -m enrichment.host_prep --novel bleak_house \
        --plan data/runs/ext_v01_baseline/phase2_plan.json \
        --assignments data/runs/ext_v01_baseline/phase1_assignments.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Any


from enrichment.llm.schemas import (
    HostBrief,
    PreInterviewResponse,
)
from enrichment.personas import ExpertPersona
from enrichment.reference_tools import (
    CitationRecord,
    CitationRegistry,
)
from enrichment.timing import Recorder

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Phase 2.5a: Pre-interviews (Haiku, parallel)
# ---------------------------------------------------------------------------
# Prompt templates moved to enrichment/llm/host_prep_prompts.py
# (2026-05-18, BleakHouse-mz2g). The module-level aliases below
# preserve the existing _INTERVIEW_* names used throughout this file.

from enrichment.llm.host_prep_prompts import (  # noqa: E402
    INTERVIEW_STRUCTURED_PARSE_SYSTEM as _INTERVIEW_STRUCTURED_PARSE_SYSTEM,
    INTERVIEW_SYSTEM as _INTERVIEW_SYSTEM,
    INTERVIEW_TOOLS_ADDENDUM as _INTERVIEW_TOOLS_ADDENDUM,
    INTERVIEW_USER as _INTERVIEW_USER,
    LISTENER_PICK_SYSTEM as _LISTENER_PICK_SYSTEM,
    QUESTION_COUNT_LONG as _QUESTION_COUNT_LONG,
    QUESTION_COUNT_SHORT as _QUESTION_COUNT_SHORT,
    QUESTION_PLANNING_SYSTEM as _QUESTION_PLANNING_SYSTEM,
    QUESTION_PLANNING_USER as _QUESTION_PLANNING_USER,
)


def _build_passage_summary(assignments: list[dict]) -> str:
    """Build a compact passage summary for the interview prompt."""
    parts = []
    for a in assignments:
        pid = a.get("passage_id", "?")
        expert = a.get("expert", "")
        text = a.get("text", "")[:300]
        best_quote = a.get("best_quote", "")
        summary = a.get("summary", "")
        lines = [f"### {pid} (assigned to {expert})"]
        if summary:
            lines.append(f"Summary: {summary}")
        if best_quote:
            lines.append(f'Best quote: "{best_quote}"')
        lines.append(f"Text: {text}...")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def run_pre_interview(
    expert: ExpertPersona,
    other_expert_names: list[str],
    segment_name: str,
    assignments: list[dict],
    novel_title: str,
    novel_author: str,
) -> PreInterviewResponse:
    """Run a single pre-interview for one expert on one segment.

    Routes through the LLM seam (task='host_prep_pre_interview') so the
    active provider profile picks the model. Retries 3× on Pydantic
    validation failure — the structured-output contract is brittle.
    """
    system = _INTERVIEW_SYSTEM.format(
        novel_title=novel_title,
        novel_author=novel_author,
        expert_name=expert.name,
        expert_description=expert.description,
        other_experts=", ".join(other_expert_names),
    )
    user = _INTERVIEW_USER.format(
        segment_name=segment_name,
        passage_block=_build_passage_summary(assignments),
    )

    from enrichment.llm import generate as llm_generate
    from enrichment.llm.types import GenerationRequest

    schema = PreInterviewResponse.model_json_schema()
    max_attempts = 3
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = llm_generate(GenerationRequest(
                task="host_prep_pre_interview",
                system=system,
                user=user,
                max_tokens=2048,
                json_schema=schema,
                reasoning_effort="minimal",
            ))
            parsed = PreInterviewResponse.model_validate_json(result.text)
            break
        except Exception as e:
            last_error = e
            if attempt < max_attempts:
                logger.warning(
                    "  Pre-interview attempt %d/%d failed for %s × %s: %s. Retrying...",
                    attempt, max_attempts, expert.name, segment_name, e,
                )
            else:
                raise
    else:
        # Defensive — loop exited without break or raise (shouldn't happen).
        raise RuntimeError(
            f"pre_interview exhausted retries without raising: {last_error!r}"
        )

    parsed.expert_name = expert.name
    logger.info(
        "  Pre-interview %s × %s: %d points, %d quotes, %d disagreements",
        expert.name, segment_name,
        len(parsed.key_points), len(parsed.potential_quotes),
        len(parsed.disagreement_angles),
    )
    return parsed


MAX_TOOL_CALLS = 6


def run_pre_interview_with_tools(
    expert: ExpertPersona,
    other_expert_names: list[str],
    segment_name: str,
    assignments: list[dict],
    novel_title: str,
    novel_author: str,
) -> tuple[PreInterviewResponse, CitationRegistry, Recorder]:
    """Run a pre-interview with scholarly search tools through the LLM seam.

    Two-phase:
      1. Agentic tool loop (task='host_prep_pre_interview'): the model issues
         search_openalex / search_wikipedia / read_wikipedia_article calls;
         the seam dispatches them via executors and feeds results back.
         Terminates when the model stops emitting tool calls or
         MAX_TOOL_CALLS is hit. Yields accumulated text.
      2. Structured-output extract (task='host_prep_pre_interview_structured'):
         a no-tools call that parses the accumulated text into a
         PreInterviewResponse, with a tag-discipline prompt that constrains
         proposed_references to the registry's tags.

    Returns (response, registry, recorder) — the registry holds every
    CitationRecord referenced by tag in response.proposed_references; the
    recorder holds aggregated timing for the loop + the parse call.
    """
    registry = CitationRegistry()
    recorder = Recorder(expert=expert.name, segment=segment_name)

    system = _INTERVIEW_SYSTEM.format(
        novel_title=novel_title,
        novel_author=novel_author,
        expert_name=expert.name,
        expert_description=expert.description,
        other_experts=", ".join(other_expert_names),
    ) + _INTERVIEW_TOOLS_ADDENDUM

    user = _INTERVIEW_USER.format(
        segment_name=segment_name,
        passage_block=_build_passage_summary(assignments),
    )

    # ── Phase 1: seam-mediated tool loop ────────────────────────────
    from enrichment.llm import generate as llm_generate
    from enrichment.llm.types import GenerationRequest, ToolSpec
    from enrichment.reference_tools import (
        SEARCH_OPENALEX_TOOL,
        SEARCH_WIKIPEDIA_TOOL,
        READ_WIKIPEDIA_ARTICLE_TOOL,
        execute_search_openalex,
        execute_search_wikipedia,
        execute_read_wikipedia_article,
    )

    # Translate Anthropic-shaped tool defs into the seam's neutral ToolSpec.
    # Anthropic's ToolUnionParam dict already uses input_schema as the JSON
    # Schema key (same as ToolSpec), so this is largely a re-shape.
    def _tool_spec_from_anthropic(t: dict) -> ToolSpec:
        return ToolSpec(
            name=str(t["name"]),
            description=str(t["description"]),
            input_schema=dict(t["input_schema"]),
        )

    tools = (
        _tool_spec_from_anthropic(SEARCH_OPENALEX_TOOL),
        _tool_spec_from_anthropic(SEARCH_WIKIPEDIA_TOOL),
        _tool_spec_from_anthropic(READ_WIKIPEDIA_ARTICLE_TOOL),
    )

    # Per-tool executors. The seam normalises arguments to a parsed dict
    # before calling, so these just route to the existing implementations.
    executors = {
        "search_openalex": lambda args: execute_search_openalex(
            args.get("query", ""), registry, recorder=recorder,
        ),
        "search_wikipedia": lambda args: execute_search_wikipedia(
            args.get("query", ""), registry, recorder=recorder,
        ),
        "read_wikipedia_article": lambda args: execute_read_wikipedia_article(
            args.get("ref_tag", ""), registry, recorder,
        ),
    }

    import time as _time
    _t0 = _time.monotonic()
    loop_result = llm_generate(GenerationRequest(
        task="host_prep_pre_interview",
        system=system,
        user=user,
        max_tokens=4096,
        tools=tools,
        tool_executors=executors,
        max_tool_iterations=MAX_TOOL_CALLS,
        reasoning_effort="minimal",
    ))
    if recorder is not None:
        recorder.record(
            kind="model",
            name=loop_result.model,
            label="interview_loop (aggregated)",
            duration_s=_time.monotonic() - _t0,
            started_at=_t0,
            input_tokens=loop_result.input_tokens or 0,
            output_tokens=loop_result.output_tokens or 0,
            cache_creation_input_tokens=loop_result.cache_creation_input_tokens or 0,
            cache_read_input_tokens=loop_result.cache_read_input_tokens or 0,
        )
    tool_count = len(loop_result.tool_transcript)
    for tc in loop_result.tool_transcript:
        arg = tc.arguments.get("query") or tc.arguments.get("ref_tag") or ""
        logger.info("    Tool %s(%s): %d chars",
                    tc.name, str(arg)[:40], len(tc.output))

    final_text = loop_result.text
    if not final_text.strip():
        final_text = (
            f"Expert {expert.name} was interviewed about segment '{segment_name}' "
            f"but produced no text response. Please generate a default response."
        )

    # ── Phase 2: structured-output extract ──────────────────────────
    available_tags = [r.tag for r in registry.all()]
    tag_hint = (
        f"Available tags issued during this interview: {available_tags}. "
        "proposed_references must be a subset of these tags."
        if available_tags else
        "No reference tags were issued; proposed_references must be empty."
    )

    _t1 = _time.monotonic()
    parse_result = llm_generate(GenerationRequest(
        task="host_prep_pre_interview_structured",
        system=_INTERVIEW_STRUCTURED_PARSE_SYSTEM + tag_hint,
        user=final_text,
        max_tokens=2048,
        json_schema=PreInterviewResponse.model_json_schema(),
        reasoning_effort="minimal",
    ))
    if recorder is not None:
        recorder.record(
            kind="model",
            name=parse_result.model,
            label="interview_parse",
            duration_s=_time.monotonic() - _t1,
            started_at=_t1,
            input_tokens=parse_result.input_tokens or 0,
            output_tokens=parse_result.output_tokens or 0,
            cache_creation_input_tokens=parse_result.cache_creation_input_tokens or 0,
            cache_read_input_tokens=parse_result.cache_read_input_tokens or 0,
        )
    result = PreInterviewResponse.model_validate_json(parse_result.text)
    result.expert_name = expert.name
    # Discipline: drop any "tags" the parser invented that aren't in the registry.
    result.proposed_references = [
        t for t in result.proposed_references if registry.get(t) is not None
    ]
    logger.info(
        "  Pre-interview (tools) %s × %s: %d points, %d refs, %d tool calls",
        expert.name, segment_name,
        len(result.key_points), len(result.proposed_references), tool_count,
    )
    return result, registry, recorder


def run_all_pre_interviews(
    personas: list[ExpertPersona],
    segments: list[dict],
    assignments_by_segment: list[list[dict]],
    novel_title: str,
    novel_author: str,
    max_workers: int = 6,
    use_reference_tools: bool = False,
    progress_path: Path | None = None,
) -> tuple[
    list[list[PreInterviewResponse]],
    list[list[CitationRegistry]],
    list[list[Recorder]],
]:
    """Run pre-interviews for all expert×segment pairs in parallel.

    All interviews route through the LLM seam — the active provider
    profile decides the model (see params.yaml task_models).

    Returns (interviews, registries, recorders):
      interviews[seg_idx] = [response_per_expert]
      registries[seg_idx] = [registry_per_expert]    (empty in non-tools mode)
      recorders[seg_idx]  = [recorder_per_expert]    (empty in non-tools mode)
    """
    all_interviews: list[list[PreInterviewResponse]] = [[] for _ in segments]
    all_registries: list[list[CitationRegistry]] = [[] for _ in segments]
    all_recorders: list[list[Recorder]] = [[] for _ in segments]
    expert_names = [p.name for p in personas]
    workers = max_workers

    def _no_tools_wrapper(
        expert: ExpertPersona, others: list[str],
        seg_name: str, seg_assignments: list[dict],
        novel_title: str, novel_author: str,
    ) -> tuple[PreInterviewResponse, "CitationRegistry", "Recorder"]:
        result = run_pre_interview(
            expert, others, seg_name, seg_assignments,
            novel_title, novel_author,
        )
        return result, CitationRegistry(), Recorder()

    interview_fn = (
        run_pre_interview_with_tools if use_reference_tools
        else _no_tools_wrapper
    )

    futures = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for si, seg in enumerate(segments):
            seg_name = seg.get("name", seg.get("template", {}).get("name", f"Segment {si}"))
            seg_assignments = assignments_by_segment[si]
            for expert in personas:
                others = [n for n in expert_names if n != expert.name]
                fut = pool.submit(
                    interview_fn,
                    expert, others, seg_name,
                    seg_assignments, novel_title, novel_author,
                )
                futures[fut] = si

        completed = 0
        total = len(futures)
        for fut in as_completed(futures):
            si = futures[fut]
            response, registry, recorder = fut.result()
            all_interviews[si].append(response)
            all_registries[si].append(registry)
            all_recorders[si].append(recorder)
            completed += 1
            logger.info("    interview %d/%d done (segment %d)",
                        completed, total, si)
            # Incremental flush — every captured event survives a crash,
            # and a watcher tailing phase2_5_timings.json sees progress.
            if progress_path is not None:
                merged = Recorder()
                for seg_recs in all_recorders:
                    for r in seg_recs:
                        merged.merge(r)
                progress_path.write_text(json.dumps(merged.to_dict(), indent=2))

    return all_interviews, all_registries, all_recorders


# ---------------------------------------------------------------------------
# Phase 2.5b: Question planning (Sonnet, per segment)
# ---------------------------------------------------------------------------

def _format_interviews(interviews: list[PreInterviewResponse]) -> str:
    """Format pre-interview responses for the question planning prompt."""
    parts = []
    for iv in interviews:
        lines = [f"### {iv.expert_name}"]
        lines.append(f"**Key points:** {'; '.join(iv.key_points)}")
        if iv.potential_quotes:
            lines.append(f"**Wants to quote:** {'; '.join(iv.potential_quotes)}")
        if iv.disagreement_angles:
            lines.append(f"**Might push back on:** {'; '.join(iv.disagreement_angles)}")
        if iv.strongest_take:
            lines.append(f"**Strongest take:** {iv.strongest_take}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def plan_questions(
    segment_name: str,
    interviews: list[PreInterviewResponse],
    novel_title: str,
    novel_author: str,
    verified_references: list[str] | None = None,
    recorder: Recorder | None = None,
    length: str = "long",
) -> HostBrief:
    """Plan questions for one segment based on pre-interviews.

    length: 'long' asks for 3–5 questions per segment (production
    default); 'short' asks for 1–2 questions per segment, since each
    Q+A round contributes 6–10 turns (~3 min audio per round) and
    short-form episodes only have ~3 min budget per segment total."""
    if length == "short":
        question_count_phrase = _QUESTION_COUNT_SHORT
    elif length == "long":
        question_count_phrase = _QUESTION_COUNT_LONG
    else:
        raise ValueError(f"unknown length {length!r} (expected 'long' or 'short')")
    system = _QUESTION_PLANNING_SYSTEM.format(
        novel_title=novel_title,
        novel_author=novel_author,
        question_count_phrase=question_count_phrase,
    )
    user = _QUESTION_PLANNING_USER.format(
        segment_name=segment_name,
        interview_block=_format_interviews(interviews),
        question_count_phrase=question_count_phrase,
    )
    if verified_references:
        user += "\n\n## Verified scholarly references for this segment\n\n"
        user += "These works were found and verified during pre-interviews. "
        user += "The host may draw on them when framing questions — referencing "
        user += "what scholars have argued, not asking experts to demonstrate methods.\n\n"
        for ref in verified_references:
            user += f"- {ref}\n"

    from enrichment.llm import generate as llm_generate
    from enrichment.llm.types import GenerationRequest

    import time as _time
    _t0 = _time.monotonic()
    result = llm_generate(GenerationRequest(
        task="host_prep_brief",
        system=system,
        user=user,
        max_tokens=4096,
        json_schema=HostBrief.model_json_schema(),
        reasoning_effort="minimal",
    ))
    if recorder is not None:
        recorder.record(
            kind="model",
            name=result.model,
            label="plan_questions",
            duration_s=_time.monotonic() - _t0,
            started_at=_t0,
            input_tokens=result.input_tokens or 0,
            output_tokens=result.output_tokens or 0,
            cache_creation_input_tokens=result.cache_creation_input_tokens or 0,
            cache_read_input_tokens=result.cache_read_input_tokens or 0,
        )
    brief = HostBrief.model_validate_json(result.text)
    brief.segment_name = segment_name
    logger.info(
        "  Question plan for '%s': %d questions, %d cross-engagement targets",
        segment_name, len(brief.questions), len(brief.cross_engagement_targets),
    )
    return brief


def _format_record_for_host(record: CitationRecord) -> str:
    """Render a CitationRecord as a one-line 'Author, Title (Year)' string
    for inclusion in the question-planner prompt."""
    author_str = ", ".join(record.authors[:3]) if record.authors else "—"
    year = record.year or "?"
    return f"{author_str}, \"{record.title}\" ({year})"


# _LISTENER_PICK_SYSTEM is imported from enrichment.llm.host_prep_prompts
# at module top. The criterion — "would a general listener actually
# pursue this?" — has too many soft edges to encode as a rule
# (book-vs-article isn't enough; some scholarly books are eminently
# readable, some trade-press books are dense, some review articles are
# accessible essays). Haiku gets the candidate metadata and decides;
# "Zero Framework Cognition" applies — let the model do the squishy
# judgement we can't formalise.


_LISTENER_PICK_TAGS_RE = re.compile(r"\{[^{}]*\"tags\"[^{}]*\}", re.DOTALL)


def _select_listener_recommendations(
    candidates: list[CitationRecord],
    novel_title: str,
    novel_author: str,
    recorder: Recorder | None = None,
) -> list[str]:
    """Filter that shrinks the proposed-references list to a listener-
    friendly subset. Returns a list of tags (subset of the input).
    Routes through the LLM seam (task='listener_pick') so the active
    provider profile decides the model. On parse failure or empty
    input, falls back to the full list — better to over-show than
    under-show.
    """
    if not candidates:
        return []

    lines = [f"Candidates ({len(candidates)}):"]
    for c in candidates:
        authors = ", ".join(c.authors[:2]) or "—"
        year = c.year or "?"
        type_ = c.type or "—"
        pub = c.publisher or "—"
        cited = f"cited_by={c.cited_by}" if c.cited_by else ""
        lines.append(
            f"  [{c.tag}] {authors}. \"{c.title}\" ({year}) "
            f"[type={type_}, publisher={pub}] {cited}".rstrip()
        )
        if c.description:
            lines.append(f"    {c.description[:240]}")

    system = _LISTENER_PICK_SYSTEM.format(
        novel_title=novel_title, novel_author=novel_author,
    )
    from enrichment.llm import generate as llm_generate
    from enrichment.llm.types import GenerationRequest

    import time as _time
    _t0 = _time.monotonic()
    result = llm_generate(GenerationRequest(
        task="listener_pick",
        system=system,
        user="\n".join(lines),
        max_tokens=512,
        reasoning_effort="minimal",
    ))
    if recorder is not None:
        recorder.record(
            kind="model",
            name=result.model,
            label="listener_pick",
            duration_s=_time.monotonic() - _t0,
            started_at=_t0,
            input_tokens=result.input_tokens or 0,
            output_tokens=result.output_tokens or 0,
            cache_creation_input_tokens=result.cache_creation_input_tokens or 0,
            cache_read_input_tokens=result.cache_read_input_tokens or 0,
        )
    text = result.text
    m = _LISTENER_PICK_TAGS_RE.search(text)
    if m is None:
        logger.warning("listener-pick: no JSON in response, falling back to all candidates")
        return [c.tag for c in candidates]
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        logger.warning("listener-pick: JSON decode failed (%s), falling back to all", exc)
        return [c.tag for c in candidates]
    raw = data.get("tags") or []
    available = {c.tag for c in candidates}
    picks = [t for t in raw if t in available]
    logger.info(
        "  listener-pick: kept %d of %d candidates", len(picks), len(candidates),
    )
    return picks or [c.tag for c in candidates]


def filter_reading_list_recommended(
    reading_list_path: Path,
    novel_title: str,
    novel_author: str,
    recorder: Recorder | None = None,
) -> int:
    """Post-pass that shrinks `recommended[]` in a phase2_5_reading_list.json
    to a listener-friendly subset of the proposed entries. Routes through
    the LLM seam (task='listener_pick') so the active provider profile
    decides the model.

    Idempotent: reads the file, runs the soft filter, writes it back. The
    full proposed set stays in `entries[]` (audit trail). Returns the
    count of recommended entries written. No-op if the file is missing
    or has no entries.
    """
    if not reading_list_path.exists():
        return 0
    payload = json.loads(reading_list_path.read_text())
    entries_dicts: list[dict[str, Any]] = payload.get("entries") or []
    if not entries_dicts:
        return 0
    candidates = [CitationRecord(**e) for e in entries_dicts]
    picks = _select_listener_recommendations(
        candidates, novel_title, novel_author, recorder=recorder,
    )
    pick_set = set(picks)
    payload["recommended"] = [e for e in entries_dicts if e.get("tag") in pick_set]
    reading_list_path.write_text(json.dumps(payload, indent=2))
    logger.info(
        "  Filtered reading list: %d → %d recommended (listener-friendly subset)",
        len(entries_dicts), len(payload["recommended"]),
    )
    return len(payload["recommended"])


def _segment_name(seg: dict, idx: int) -> str:
    return seg.get("name", seg.get("template", {}).get("name", f"Segment {idx}"))


def run_host_prep(
    personas: list[ExpertPersona],
    segments: list[dict],
    assignments_by_segment: list[list[dict]],
    novel_title: str,
    novel_author: str,
    use_reference_tools: bool = False,
    run_dir: Path | None = None,
    length: str = "long",
) -> tuple[list[HostBrief], list[list[PreInterviewResponse]]]:
    """Run the full Phase 2.5 pipeline: pre-interviews + question planning.

    All LLM calls route through the seam — the active provider profile
    decides the model.

    Returns (briefs, interviews) where interviews[seg_idx] is a list of
    PreInterviewResponse per expert.
    """
    tools_label = " with reference tools" if use_reference_tools else ""
    logger.info("Phase 2.5a: pre-interviews%s (%d experts × %d segments)",
                tools_label, len(personas), len(segments))
    flush_path = (run_dir / "phase2_5_timings.json") if run_dir else None
    # The aggregator owns the on-disk timing sidecar. As sub-recorders
    # are merged in (one per interview, then per brief), the sidecar
    # rewrites automatically — no separate plumbing per call site.
    timing = Recorder(flush_path=flush_path)
    interviews, registries, recorders = run_all_pre_interviews(
        personas, segments, assignments_by_segment,
        novel_title, novel_author,
        use_reference_tools=use_reference_tools,
        progress_path=flush_path,
    )
    for seg_recorders in recorders:
        for r in seg_recorders:
            timing.merge(r)

    # Build a global registry from per-interview registries. Records are
    # canonicalised by URL: the same OpenAlex/Wikipedia work registered in
    # different interviews collapses to a single entry under one canonical
    # tag. proposed_tags_by_segment maps segment_name -> [{expert, tags}],
    # using the canonical tags.
    canonical = CitationRegistry()
    proposed_tags_by_segment: dict[str, list[dict[str, Any]]] = {}
    refs_text_by_segment: dict[str, list[str]] = {}

    if use_reference_tools:
        for si, seg_interviews in enumerate(interviews):
            seg_name = _segment_name(segments[si], si)
            seg_proposed: list[dict[str, Any]] = []
            seg_text_refs: list[str] = []
            for iv, reg in zip(seg_interviews, registries[si]):
                expert_tag_set: list[str] = []
                seen_canonical: set[str] = set()
                for tag in iv.proposed_references:
                    rec = reg.get(tag)
                    if rec is None:
                        continue
                    # Re-register into the canonical registry; the URL-based
                    # dedup picks the canonical tag.
                    canonical_tag = canonical.register(
                        title=rec.title,
                        authors=rec.authors,
                        year=rec.year,
                        type=rec.type,
                        publisher=rec.publisher,
                        description=rec.description,
                        cited_by=rec.cited_by,
                        url=rec.url,
                        doi=rec.doi,
                        source=rec.source,
                        parent_tag=rec.parent_tag,
                    )
                    if canonical_tag in seen_canonical:
                        continue
                    seen_canonical.add(canonical_tag)
                    expert_tag_set.append(canonical_tag)
                    canonical_rec = canonical.get(canonical_tag)
                    if canonical_rec is not None:
                        seg_text_refs.append(_format_record_for_host(canonical_rec))
                if expert_tag_set:
                    seg_proposed.append({
                        "expert_name": iv.expert_name,
                        "tags": expert_tag_set,
                    })
            if seg_proposed:
                proposed_tags_by_segment[seg_name] = seg_proposed
            if seg_text_refs:
                refs_text_by_segment[seg_name] = seg_text_refs

        # All unique entries the experts proposed during their interviews
        # become `entries[]` AND `recommended[]` in the output. The
        # listener-friendly soft filter (filter_reading_list_recommended)
        # runs as a post-processing step *after* phase 3 — the script
        # generator no longer mentions specific works in the sign-off,
        # so the reading list filter doesn't gate any script content.
        all_proposed_tags = {
            t for entries in proposed_tags_by_segment.values()
            for entry in entries for t in entry["tags"]
        }
        proposed_records = [
            r for r in canonical.all() if r.tag in all_proposed_tags
        ]
        recommended_entries: list[dict[str, Any]] = [
            asdict(r) for r in proposed_records
        ]

        if run_dir:
            entries_payload = canonical.to_dicts()
            stats: dict[str, Any] = {
                "total_entries": len(entries_payload),
                "by_source": {},
                "total_proposed_tags": len(all_proposed_tags),
            }
            for r in canonical.all():
                by_source = stats["by_source"]
                by_source[r.source] = by_source.get(r.source, 0) + 1
            payload = {
                "schema_version": 2,
                "novel_title": novel_title,
                "novel_author": novel_author,
                "models": {
                    "interview": "claude-haiku-4-5",
                    "enrich": "claude-haiku-4-5",
                },
                "entries": entries_payload,
                "proposed_by_segment": proposed_tags_by_segment,
                # Listener-facing recommendations as structured records.
                # Each carries full metadata: title, authors, year, type,
                # publisher, description, cited_by, url, doi, source,
                # parent_tag, audience.
                "recommended": recommended_entries,
                "stats": stats,
                "total_proposed": len(all_proposed_tags),
                "total_verified": len(all_proposed_tags),
                "verification_rate": 1.0,
            }
            with open(run_dir / "phase2_5_reading_list.json", "w") as f:
                json.dump(payload, f, indent=2)
            logger.info(
                "  Saved reading list: %d entries, %d proposed (all in recommended; filter is a post-pass)",
                len(entries_payload), len(all_proposed_tags),
            )

    logger.info("Phase 2.5b: question planning (%d segments)", len(segments))
    briefs: list[HostBrief] = []
    for si, seg in enumerate(segments):
        seg_name = _segment_name(seg, si)
        seg_refs = refs_text_by_segment.get(seg_name)
        plan_recorder = Recorder(segment=seg_name)
        brief = plan_questions(
            seg_name, interviews[si],
            novel_title, novel_author,
            verified_references=seg_refs,
            recorder=plan_recorder,
            length=length,
        )
        timing.merge(plan_recorder)  # auto-flushes via flush_path
        briefs.append(brief)
        logger.info("    brief %d/%d done (%s)", si + 1, len(segments), seg_name)

    if run_dir is not None:
        logger.info("  Saved timings (%d events) to %s",
                    len(timing.events), run_dir / "phase2_5_timings.json")

    return briefs, interviews


# ---------------------------------------------------------------------------
# CLI for standalone testing
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Run host preparation (Phase 2.5)")
    parser.add_argument("--novel", required=True, help="Novel key")
    parser.add_argument("--plan", required=True, help="Path to phase2_plan.json")
    parser.add_argument("--assignments", required=True, help="Path to phase1_assignments.json")
    parser.add_argument("--interview-model", default="claude-haiku-4-5-20251001")
    parser.add_argument("--planning-model", default="claude-sonnet-4-6")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")

    os.environ["BLEAKHOUSE_NOVEL"] = args.novel

    from enrichment.novel_prompts import get_active_novel  # pyright: ignore[reportMissingImports]
    cfg = get_active_novel(args.novel)

    with open(args.plan) as f:
        plan = json.load(f)
    with open(args.assignments) as f:
        raw = json.load(f)
    assignments = raw.get("assignments", raw) if isinstance(raw, dict) else raw

    # Build per-segment assignment lists
    pa_lookup = {a["passage_id"]: a for a in assignments}
    segments = plan["segments"]
    assignments_by_segment = []
    for seg in segments:
        seg_assignments = []
        for a in seg.get("assignments", []):
            full = pa_lookup.get(a.get("passage_id", ""), a)
            seg_assignments.append(full)
        assignments_by_segment.append(seg_assignments)

    from enrichment.personas import DEFAULT_PERSONAS  # pyright: ignore[reportMissingImports]

    briefs, interviews = run_host_prep(
        DEFAULT_PERSONAS, segments, assignments_by_segment,
        cfg.title, cfg.author,
    )

    # Output
    for si, brief in enumerate(briefs):
        if interviews[si]:
            print(f"\n--- Pre-interviews for {brief.segment_name} ---")
            for iv in interviews[si]:
                print(f"  {iv.expert_name}: {'; '.join(iv.key_points[:2])}")
    for brief in briefs:
        print(f"\n{'='*60}")
        print(f"Segment: {brief.segment_name}")
        print(f"Steering: {brief.steering_notes}")
        for q in brief.questions:
            print(f"  → [{q.target_expert}] {q.question}")
            print(f"    Intent: {q.intent}")
            if q.follow_up_for:
                print(f"    Follow-up from: {', '.join(q.follow_up_for)}")
        if brief.cross_engagement_targets:
            print(f"  Cross-engagement: {'; '.join(brief.cross_engagement_targets)}")


if __name__ == "__main__":
    main()
