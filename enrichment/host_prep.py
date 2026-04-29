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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Any

import anthropic

from enrichment.podcast_types import (  # pyright: ignore[reportMissingImports]
    ExpertPersona,
    HostBrief,
    PreInterviewResponse,
)
from enrichment.reference_tools import (
    ALL_TOOLS,
    CitationRecord,
    CitationRegistry,
    dispatch_tool,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Phase 2.5a: Pre-interviews (Haiku, parallel)
# ---------------------------------------------------------------------------

_INTERVIEW_SYSTEM = """\
You are a podcast host preparing for a literary discussion about \
**{novel_title}** by **{novel_author}**.  You are interviewing \
**{expert_name}**, {expert_description}

Your goal is to find out:
1. What strikes this expert most about the passages assigned to this segment?
2. Which passage would they most want to quote aloud, and why?
3. Where might they disagree with or challenge the other experts ({other_experts})?
4. What is the single most interesting or provocative claim they want to make?
5. What specific finding emerges when they apply their own methods to these \
passages?  Be concrete: if they would parse a sentence, show the parse.  \
If they would compute a ratio, estimate it.  If they would cite a historical \
source, name it.  This is the place to demonstrate what their discipline \
actually reveals about the text.

Be specific.  Reference passage IDs and actual text.  Think about what \
will make good radio — moments of genuine intellectual excitement, \
productive disagreement, or emotional connection to the text."""

_INTERVIEW_USER = """\
## Segment: {segment_name}

The passages assigned to this segment are:

{passage_block}

What are your thoughts?  What strikes you?  Where would you push back \
against the other panelists?  Which passage would you most want to \
read aloud?

Apply your specific methods to these passages.  Show your working — not \
just "I would use dependency parsing" but "the structure is X and it \
reveals Y."  Be concrete and specific.  This is your chance to do the \
methodological work before the live discussion."""


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
    client: anthropic.Anthropic,
    expert: ExpertPersona,
    other_expert_names: list[str],
    segment_name: str,
    assignments: list[dict],
    novel_title: str,
    novel_author: str,
    model: str = "claude-haiku-4-5-20251001",
) -> PreInterviewResponse:
    """Run a single pre-interview for one expert on one segment."""
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

    max_attempts = 3
    response = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.messages.parse(
                model=model,
                max_tokens=2048,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=PreInterviewResponse,
            )
            break
        except Exception as e:
            if attempt < max_attempts:
                logger.warning(
                    "  Pre-interview attempt %d/%d failed for %s × %s: %s. Retrying...",
                    attempt, max_attempts, expert.name, segment_name, e,
                )
            else:
                raise

    assert response is not None and response.parsed_output is not None
    result = response.parsed_output
    result.expert_name = expert.name
    logger.info(
        "  Pre-interview %s × %s: %d points, %d quotes, %d disagreements",
        expert.name, segment_name,
        len(result.key_points), len(result.potential_quotes),
        len(result.disagreement_angles),
    )
    return result


_INTERVIEW_TOOLS_ADDENDUM = """

You have three search tools.  Use `search_openalex` for scholarly works \
(criticism, historical studies, theoretical texts) relevant to your analysis. \
Use `search_wikipedia` for canonical works, Acts, named events, and well-known \
people.  When a Wikipedia article looks central, call `read_wikipedia_article` \
on its tag to access the works listed in that article's bibliography — those \
items become citable as new tags too.

Your core reading list includes:
{touchstone_works}

Each tool result prefixes candidates with stable [ref-N] tags.  In your \
structured output, populate `proposed_references` with these tags ONLY \
(e.g. ["ref-3", "ref-7"]).  Do not invent citation text.  If a citation \
isn't tagged, you can't propose it — search again first.  Search 3–5 times \
total."""

MAX_TOOL_CALLS = 6


def run_pre_interview_with_tools(
    client: anthropic.Anthropic,
    expert: ExpertPersona,
    other_expert_names: list[str],
    segment_name: str,
    assignments: list[dict],
    novel_title: str,
    novel_author: str,
    model: str = "claude-sonnet-4-6",
) -> tuple[PreInterviewResponse, CitationRegistry]:
    """Run a pre-interview with scholarly search tools (stable API, manual loop).

    Returns (response, registry) — the registry holds every CitationRecord
    referenced by tag in response.proposed_references, with full metadata.
    """
    registry = CitationRegistry()
    touchstone_block = "\n".join(f"- {w}" for w in expert.touchstone_works) if expert.touchstone_works else "(none)"

    system = _INTERVIEW_SYSTEM.format(
        novel_title=novel_title,
        novel_author=novel_author,
        expert_name=expert.name,
        expert_description=expert.description,
        other_experts=", ".join(other_expert_names),
    ) + _INTERVIEW_TOOLS_ADDENDUM.format(touchstone_works=touchstone_block)

    user = _INTERVIEW_USER.format(
        segment_name=segment_name,
        passage_block=_build_passage_summary(assignments),
    )

    # Agentic tool loop (stable API, not beta)
    messages: list = [{"role": "user", "content": user}]
    tool_count = 0
    all_text: list[str] = []

    for _iteration in range(MAX_TOOL_CALLS + 1):
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system,
            messages=messages,
            tools=ALL_TOOLS,
        )

        # Collect any text from this response
        for block in response.content:
            if block.type == "text":
                all_text.append(block.text)

        if response.stop_reason != "tool_use":
            break

        # Process tool calls, build tool_result blocks
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result_text = dispatch_tool(
                    block.name, block.input, registry, client,
                )
                arg = block.input.get("query") or block.input.get("ref_tag") or ""
                logger.info("    Tool %s(%s): %d chars",
                            block.name, str(arg)[:40], len(result_text))
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                })
                tool_count += 1

        # Append assistant response + tool results to conversation
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    final_text = "\n".join(all_text)
    if not final_text.strip():
        final_text = (
            f"Expert {expert.name} was interviewed about segment '{segment_name}' "
            f"but produced no text response. Please generate a default response."
        )

    # Parse into structured output with a follow-up call. Tell the parser
    # explicitly that proposed_references must be the [ref-N] tags from
    # the conversation, not free-text strings.
    available_tags = [r.tag for r in registry.all()]
    tag_hint = (
        f"Available tags issued during this interview: {available_tags}. "
        "proposed_references must be a subset of these tags."
        if available_tags else
        "No reference tags were issued; proposed_references must be empty."
    )
    parse_response = client.messages.parse(
        model=model,
        max_tokens=2048,
        system=(
            "Extract the pre-interview response from this expert's analysis. "
            "proposed_references must contain ONLY [ref-N] tags from the "
            "tool conversation — never free-text citations. " + tag_hint
        ),
        messages=[{"role": "user", "content": final_text}],
        output_format=PreInterviewResponse,
    )

    assert parse_response.parsed_output is not None
    result = parse_response.parsed_output
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
    return result, registry


def run_all_pre_interviews(
    client: anthropic.Anthropic,
    personas: list[ExpertPersona],
    segments: list[dict],
    assignments_by_segment: list[list[dict]],
    novel_title: str,
    novel_author: str,
    model: str = "claude-haiku-4-5-20251001",
    max_workers: int = 6,
    use_reference_tools: bool = False,
) -> tuple[list[list[PreInterviewResponse]], list[list[CitationRegistry]]]:
    """Run pre-interviews for all expert×segment pairs in parallel.

    Returns (interviews, registries):
      interviews[seg_idx] = [response_per_expert]
      registries[seg_idx] = [registry_per_expert]    (only populated in
                                                     tools mode; empty
                                                     CitationRegistry
                                                     placeholders otherwise)
    """
    all_interviews: list[list[PreInterviewResponse]] = [[] for _ in segments]
    all_registries: list[list[CitationRegistry]] = [[] for _ in segments]
    expert_names = [p.name for p in personas]

    interview_model = "claude-sonnet-4-6" if use_reference_tools else model
    workers = min(max_workers, 3) if use_reference_tools else max_workers

    def _no_tools_wrapper(*args, **kwargs):
        return run_pre_interview(*args, **kwargs), CitationRegistry()

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
                    client, expert, others, seg_name,
                    seg_assignments, novel_title, novel_author, interview_model,
                )
                futures[fut] = si

        for fut in as_completed(futures):
            si = futures[fut]
            response, registry = fut.result()
            all_interviews[si].append(response)
            all_registries[si].append(registry)

    return all_interviews, all_registries


# ---------------------------------------------------------------------------
# Phase 2.5b: Question planning (Sonnet, per segment)
# ---------------------------------------------------------------------------

_QUESTION_PLANNING_SYSTEM = """\
You are a podcast host planning questions for a segment of a literary \
discussion about **{novel_title}** by **{novel_author}**.

You've just finished pre-interviews with each expert.  Your job is to \
plan 3–5 targeted questions that will:

1. Draw out each expert's strongest, most interesting take
2. Set up productive disagreements between experts
3. Create moments where experts respond to each other's points
4. Target specific passages for quotation — name the passage ID
5. Keep the energy informal and conversational — pub with smart friends, \
   not conference panel

Each question should name a specific expert.  After that expert responds, \
the others should feel free to jump in.  Your questions open threads, \
not slots for single answers.

When crafting questions, focus on the *findings* from each expert's \
pre-interview, not their methods.  Instead of "can you tell us about \
the dependency parsing?" write "you noticed that Dickens strips the \
agent from every sentence here — what does that do to us as readers?"  \
The host never asks an expert to demonstrate a method — the host asks \
about what the method revealed.

Also note any cross-engagement opportunities: places where one expert's \
pre-interview response directly contradicts or complements another's."""

_QUESTION_PLANNING_USER = """\
## Segment: {segment_name}

## Pre-interview responses:

{interview_block}

Plan 3–5 questions for this segment.  Make them specific, conversational, \
and designed to produce good radio."""


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
    client: anthropic.Anthropic,
    segment_name: str,
    interviews: list[PreInterviewResponse],
    novel_title: str,
    novel_author: str,
    model: str = "claude-sonnet-4-6",
    verified_references: list[str] | None = None,
) -> HostBrief:
    """Plan questions for one segment based on pre-interviews."""
    system = _QUESTION_PLANNING_SYSTEM.format(
        novel_title=novel_title,
        novel_author=novel_author,
    )
    user = _QUESTION_PLANNING_USER.format(
        segment_name=segment_name,
        interview_block=_format_interviews(interviews),
    )
    if verified_references:
        user += "\n\n## Verified scholarly references for this segment\n\n"
        user += "These works were found and verified during pre-interviews. "
        user += "The host may draw on them when framing questions — referencing "
        user += "what scholars have argued, not asking experts to demonstrate methods.\n\n"
        for ref in verified_references:
            user += f"- {ref}\n"

    response = client.messages.parse(
        model=model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_format=HostBrief,
    )

    assert response.parsed_output is not None
    brief = response.parsed_output
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


def _segment_name(seg: dict, idx: int) -> str:
    return seg.get("name", seg.get("template", {}).get("name", f"Segment {idx}"))


def run_host_prep(
    client: anthropic.Anthropic,
    personas: list[ExpertPersona],
    segments: list[dict],
    assignments_by_segment: list[list[dict]],
    novel_title: str,
    novel_author: str,
    interview_model: str = "claude-haiku-4-5-20251001",
    planning_model: str = "claude-sonnet-4-6",
    use_reference_tools: bool = False,
    run_dir: Path | None = None,
) -> tuple[list[HostBrief], list[list[PreInterviewResponse]]]:
    """Run the full Phase 2.5 pipeline: pre-interviews + question planning.

    Returns (briefs, interviews) where interviews[seg_idx] is a list of
    PreInterviewResponse per expert.
    """
    tools_label = " with reference tools" if use_reference_tools else ""
    logger.info("Phase 2.5a: pre-interviews%s (%d experts × %d segments)",
                tools_label, len(personas), len(segments))
    interviews, registries = run_all_pre_interviews(
        client, personas, segments, assignments_by_segment,
        novel_title, novel_author, interview_model,
        use_reference_tools=use_reference_tools,
    )

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

        # Listener-facing recommendations: the unique general-audience entries
        # actually proposed by experts, in registry order.
        all_proposed_tags = {
            t for entries in proposed_tags_by_segment.values()
            for entry in entries for t in entry["tags"]
        }
        recommended_tags = [
            r.tag for r in canonical.all()
            if r.tag in all_proposed_tags and r.audience == "general"
        ]
        # Resolve recommended tags to full CitationRecord dicts (for the
        # listener-facing reading_list.json) and a parallel list of
        # one-line strings (for HostBrief.recommended_reading, which is
        # an internal working doc).
        recommended_entries: list[dict[str, Any]] = []
        recommended_text: list[str] = []
        for t in recommended_tags:
            rec = canonical.get(t)
            if rec is None:
                continue
            recommended_entries.append(asdict(rec))
            recommended_text.append(_format_record_for_host(rec))

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
                    "interview": "claude-sonnet-4-6",
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
                "  Saved reading list: %d entries, %d proposed, %d recommended",
                len(entries_payload), len(all_proposed_tags), len(recommended_tags),
            )
    else:
        recommended_text = []

    logger.info("Phase 2.5b: question planning (%d segments)", len(segments))
    briefs: list[HostBrief] = []
    for si, seg in enumerate(segments):
        seg_name = _segment_name(seg, si)
        seg_refs = refs_text_by_segment.get(seg_name)
        brief = plan_questions(
            client, seg_name, interviews[si],
            novel_title, novel_author, planning_model,
            verified_references=seg_refs,
        )
        if recommended_text:
            brief.recommended_reading = recommended_text
        briefs.append(brief)

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

    client = anthropic.Anthropic()
    from enrichment.podcast_types import DEFAULT_PERSONAS  # pyright: ignore[reportMissingImports]

    briefs, interviews = run_host_prep(
        client, DEFAULT_PERSONAS, segments, assignments_by_segment,
        cfg.title, cfg.author,
        args.interview_model, args.planning_model,
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
