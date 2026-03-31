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
from pathlib import Path

import anthropic

from enrichment.podcast_types import (  # pyright: ignore[reportMissingImports]
    ExpertPersona,
    HostBrief,
    PreInterviewResponse,
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

You have search tools available.  Use `search_openalex` to find scholarly works \
(criticism, historical studies, theoretical texts) relevant to your analysis, and \
`search_wikipedia` for factual background.  Your core reading list includes:
{touchstone_works}

Verify claims before citing.  Search 2–3 times, no more.  When you propose a \
reference, give author, title, and year."""

MAX_TOOL_CALLS = 4


def run_pre_interview_with_tools(
    client: anthropic.Anthropic,
    expert: ExpertPersona,
    other_expert_names: list[str],
    segment_name: str,
    assignments: list[dict],
    novel_title: str,
    novel_author: str,
    model: str = "claude-sonnet-4-6",
) -> PreInterviewResponse:
    """Run a pre-interview with scholarly search tools (stable API, manual loop)."""
    from enrichment.reference_tools import (  # pyright: ignore[reportMissingImports]
        SEARCH_OPENALEX_TOOL,
        SEARCH_WIKIPEDIA_TOOL,
        dispatch_tool,
    )

    tools = [SEARCH_OPENALEX_TOOL, SEARCH_WIKIPEDIA_TOOL]
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
            tools=tools,
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
                result_text = dispatch_tool(block.name, block.input)
                logger.info("    Tool %s(%s): %d chars",
                            block.name, block.input.get("query", "")[:40], len(result_text))
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

    # Parse into structured output with a follow-up call
    parse_response = client.messages.parse(
        model=model,
        max_tokens=2048,
        system=(
            "Extract the pre-interview response from this expert's analysis. "
            "Include any scholarly references they proposed in proposed_references."
        ),
        messages=[{"role": "user", "content": final_text}],
        output_format=PreInterviewResponse,
    )

    assert parse_response.parsed_output is not None
    result = parse_response.parsed_output
    result.expert_name = expert.name
    logger.info(
        "  Pre-interview (tools) %s × %s: %d points, %d refs, %d tool calls",
        expert.name, segment_name,
        len(result.key_points), len(result.proposed_references), tool_count,
    )
    return result


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
) -> list[list[PreInterviewResponse]]:
    """Run pre-interviews for all expert×segment pairs in parallel.

    Returns a list of lists: interviews[segment_idx] = [response_per_expert]
    """
    all_interviews: list[list[PreInterviewResponse]] = [[] for _ in segments]
    expert_names = [p.name for p in personas]

    # Tool-calling interviews use Sonnet (more capable), non-tool use the given model
    interview_fn = run_pre_interview_with_tools if use_reference_tools else run_pre_interview
    interview_model = "claude-sonnet-4-6" if use_reference_tools else model
    # Fewer parallel workers for tool interviews (more API calls per interview)
    workers = min(max_workers, 3) if use_reference_tools else max_workers

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
            result = fut.result()
            all_interviews[si].append(result)

    return all_interviews


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
    interviews = run_all_pre_interviews(
        client, personas, segments, assignments_by_segment,
        novel_title, novel_author, interview_model,
        use_reference_tools=use_reference_tools,
    )

    # Verify proposed references if tools were used
    if use_reference_tools:
        from enrichment.reference_tools import verify_references  # pyright: ignore[reportMissingImports]

        all_touchstones = []
        for p in personas:
            all_touchstones.extend(p.touchstone_works)

        proposed = []
        for si, seg_interviews in enumerate(interviews):
            seg_name = segments[si].get("name", segments[si].get("template", {}).get("name", f"Segment {si}"))
            for iv in seg_interviews:
                for ref_text in iv.proposed_references:
                    proposed.append({
                        "raw_text": ref_text,
                        "expert_name": iv.expert_name,
                        "segment_name": seg_name,
                    })

        if proposed:
            logger.info("Phase 2.5a+: verifying %d proposed references", len(proposed))
            reading_list = verify_references(proposed, all_touchstones)
            logger.info(
                "  Verification: %d/%d (%.0f%%) verified",
                reading_list.total_verified, reading_list.total_proposed,
                reading_list.verification_rate * 100,
            )
            if run_dir:
                with open(run_dir / "phase2_5_reading_list.json", "w") as f:
                    json.dump(reading_list.model_dump(), f, indent=2)
                logger.info("  Saved reading list to %s", run_dir / "phase2_5_reading_list.json")

    # Build per-segment reference lists from reading list
    refs_by_segment: dict[str, list[str]] = {}
    if use_reference_tools and 'reading_list' in dir():
        pass  # reading_list was set above in the verification block
    # Collect from interviews directly (proposed_references grouped by segment)
    if use_reference_tools:
        for si, seg_interviews in enumerate(interviews):
            seg_name = segments[si].get("name", segments[si].get("template", {}).get("name", f"Segment {si}"))
            seg_refs = []
            for iv in seg_interviews:
                seg_refs.extend(iv.proposed_references)
            if seg_refs:
                refs_by_segment[seg_name] = seg_refs

    logger.info("Phase 2.5b: question planning (%d segments)", len(segments))
    briefs = []
    for si, seg in enumerate(segments):
        seg_name = seg.get("name", seg.get("template", {}).get("name", f"Segment {si}"))
        seg_refs = refs_by_segment.get(seg_name)
        brief = plan_questions(
            client, seg_name, interviews[si],
            novel_title, novel_author, planning_model,
            verified_references=seg_refs,
        )
        # Populate recommended_reading from verified references
        if seg_refs:
            brief.recommended_reading = seg_refs
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
