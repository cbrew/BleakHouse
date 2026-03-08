"""Phase 3+4: Generate multi-voice podcast script from segment plan.

For each segment, sends passage text + enrichment + expert persona to an LLM.
The LLM writes a multi-voice discussion script.  Segments are independent
and could be parallelized.

Usage: uv run python -m enrichment.generate_podcast [--model claude-haiku-4-5-20251001]
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from enrichment.podcast_types import (  # pyright: ignore[reportMissingImports]
    DEFAULT_PERSONAS,
    EpisodeMetadata,
    EpisodeSegment,
    ExpertPersona,
    PodcastEpisode,
    Turn,
)
from enrichment.segment_transport import (  # pyright: ignore[reportMissingImports]
    PassageAssignment,
    PlannedSegment,
    SegmentPlan,
    build_passage_assignments,
    solve_segment_assignment,
)
from enrichment.transport_podcast import (  # pyright: ignore[reportMissingImports]
    load_passages,
    run_pipeline,
)

load_dotenv()

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"

# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _build_persona_block(personas: list[ExpertPersona]) -> str:
    """Format expert personas for the system prompt."""
    lines: list[str] = []
    for p in personas:
        lines.append(f"**{p.name}** ({p.role}): {p.description}")
    return "\n".join(lines)


def _build_passage_block(assignments: list[PassageAssignment]) -> str:
    """Format passage assignments for the user prompt."""
    blocks: list[str] = []
    for pa in assignments:
        expert_tag = f" — assigned to {pa.expert}" if pa.expert else ""
        arc_tag = f" [Character arc: {pa.arc_name}]" if pa.arc_name else ""
        dim_tag = f" (dimension: {pa.dimension})"

        header = f"### {pa.passage_id} (Chapter {pa.chapter_id}){expert_tag}{dim_tag}{arc_tag}"
        meta_lines: list[str] = []
        if pa.summary:
            meta_lines.append(f"**Summary:** {pa.summary}")
        if pa.characters_present:
            meta_lines.append(f"**Characters:** {', '.join(pa.characters_present)}")
        if pa.themes:
            meta_lines.append(f"**Themes:** {', '.join(pa.themes)}")
        if pa.emotional_register:
            meta_lines.append(f"**Emotional register:** {', '.join(pa.emotional_register)}")
        if pa.narrator:
            meta_lines.append(f"**Narrator:** {pa.narrator}")
        if pa.best_quote:
            meta_lines.append(f"**Best quote:** \"{pa.best_quote}\"")

        text_block = f"**Text:**\n{pa.text}" if pa.text else ""

        parts = [header] + meta_lines + [text_block]
        blocks.append("\n".join(p for p in parts if p))

    return "\n\n---\n\n".join(blocks)


SYSTEM_PROMPT = """\
You are a podcast scriptwriter for a literary analysis show about Charles \
Dickens' "Bleak House."  The show features three expert panelists who \
discuss passages from the novel, each bringing their unique perspective.

The experts are:
{personas}

Write a natural, engaging discussion for the segment described below.  \
Each expert should discuss the passages assigned to them, but they can \
also react to each other's observations.  Include direct quotes from the \
text.  The discussion should feel like a real conversation — not a series \
of isolated monologues.

Output your response as a JSON object with this exact structure:
{{
  "title": "segment title",
  "segment_type": "segment type",
  "turns": [
    {{
      "speaker": "expert name or Narrator",
      "role": "literary_critic | social_historian | close_reader | narrator",
      "content": "what they say",
      "quotes": ["quotes from the text"],
      "passage_refs": ["passage_ids discussed"]
    }}
  ]
}}

Guidelines:
- Start with a brief narrator introduction setting up the segment's theme
- Each expert should have 2-4 substantial turns
- Experts should build on each other's points, agree, disagree, or add context
- End with a transition or summary that leads to the next segment
- Use the enrichment metadata (themes, emotional register) to inform the discussion
- Keep each turn to 2-4 sentences — podcast pacing, not essay writing
- Include at least one direct quote from the text per expert turn
"""


def build_messages(
    segment: PlannedSegment,
    personas: list[ExpertPersona],
) -> tuple[str, str]:
    """Build system and user messages for a segment's LLM call."""
    system = SYSTEM_PROMPT.format(personas=_build_persona_block(personas))

    user_parts: list[str] = [
        f"## Segment: {segment.template.name}",
        f"**Type:** {segment.template.segment_type}",
        "",
        "## Assigned Passages",
        "",
        _build_passage_block(segment.assignments),
    ]

    return system, "\n".join(user_parts)


# ---------------------------------------------------------------------------
# LLM generation
# ---------------------------------------------------------------------------


def generate_segment_script(
    segment: PlannedSegment,
    client: anthropic.Anthropic,
    model: str,
    personas: list[ExpertPersona],
) -> EpisodeSegment:
    """Generate a multi-voice script for one segment via LLM."""
    if not segment.assignments:
        # Empty segment — return a narrator-only placeholder
        return EpisodeSegment(
            title=segment.template.name,
            segment_type=segment.template.segment_type,
            turns=[
                Turn(
                    speaker="Narrator",
                    role="narrator",
                    content=f"[This segment — {segment.template.name} — "
                    f"has no assigned passages.]",
                    quotes=[],
                    passage_refs=[],
                )
            ],
        )

    system_msg, user_msg = build_messages(segment, personas)

    logger.info(
        "Generating script for segment '%s' (%d passages)",
        segment.template.name,
        len(segment.assignments),
    )

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_msg,
        messages=[{"role": "user", "content": user_msg}],
    )

    # Extract text content
    raw_text = ""
    for block in response.content:
        if block.type == "text":
            raw_text += block.text

    # Parse JSON from response
    # Strip markdown code fences if present
    text = raw_text.strip()
    if text.startswith("```"):
        # Remove opening fence (possibly with language tag)
        first_newline = text.index("\n")
        text = text[first_newline + 1 :]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning(
            "Failed to parse JSON for segment '%s', returning raw text",
            segment.template.name,
        )
        return EpisodeSegment(
            title=segment.template.name,
            segment_type=segment.template.segment_type,
            turns=[
                Turn(
                    speaker="Narrator",
                    role="narrator",
                    content=raw_text,
                    quotes=[],
                    passage_refs=[],
                )
            ],
        )

    # Build EpisodeSegment from parsed data
    turns: list[Turn] = []
    for turn_data in data.get("turns", []):
        turns.append(
            Turn(
                speaker=turn_data.get("speaker", "Unknown"),
                role=turn_data.get("role", "narrator"),
                content=turn_data.get("content", ""),
                quotes=turn_data.get("quotes", []),
                passage_refs=turn_data.get("passage_refs", []),
            )
        )

    return EpisodeSegment(
        title=data.get("title", segment.template.name),
        segment_type=data.get("segment_type", segment.template.segment_type),
        turns=turns,
    )


# ---------------------------------------------------------------------------
# Episode assembly
# ---------------------------------------------------------------------------


def assemble_episode(
    segments: list[EpisodeSegment],
    plan: SegmentPlan,
) -> PodcastEpisode:
    """Assemble segments into a complete episode with metadata."""
    all_chapters: set[str] = set()
    all_chars: set[str] = set()
    all_arcs: set[str] = set()
    total_passages = 0

    for seg in plan.segments:
        for pa in seg.assignments:
            all_chapters.add(pa.chapter_id)
            all_chars.update(pa.characters_present)
            if pa.arc_name:
                all_arcs.add(pa.arc_name)
            total_passages += 1

    tag = _make_tag()

    return PodcastEpisode(
        title="Bleak House: A Literary Discussion",
        segments=segments,
        metadata=EpisodeMetadata(
            chapters_covered=sorted(all_chapters),
            characters_featured=sorted(all_chars),
            arcs_tracked=sorted(all_arcs),
            total_passages=total_passages,
            generation_tag=tag,
        ),
    )


def _make_tag() -> str:
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        git_hash = result.stdout.strip()
    except Exception:
        git_hash = "unknown"
    return f"{ts}_{git_hash}"


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def build_script_report(episode: PodcastEpisode) -> str:
    """Generate a human-readable script report."""
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append(f"PODCAST SCRIPT: {episode.title}")
    lines.append(f"Tag: {episode.metadata.generation_tag}")
    lines.append("=" * 72)
    lines.append("")

    for seg in episode.segments:
        lines.append(f"### {seg.title} ({seg.segment_type})")
        lines.append("")
        for turn in seg.turns:
            speaker_label = f"[{turn.speaker}]"
            lines.append(f"{speaker_label}")
            lines.append(turn.content)
            if turn.quotes:
                for q in turn.quotes:
                    lines.append(f'  > "{q}"')
            if turn.passage_refs:
                lines.append(f"  (refs: {', '.join(turn.passage_refs)})")
            lines.append("")
        lines.append("-" * 72)
        lines.append("")

    # Metadata
    lines.append("METADATA")
    lines.append(f"  Chapters: {', '.join(episode.metadata.chapters_covered)}")
    lines.append(f"  Characters: {', '.join(episode.metadata.characters_featured[:20])}")
    lines.append(f"  Arcs: {', '.join(episode.metadata.arcs_tracked)}")
    lines.append(f"  Total passages: {episode.metadata.total_passages}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate podcast script")
    parser.add_argument(
        "--model",
        default="claude-haiku-4-5-20251001",
        help="Anthropic model to use (default: claude-haiku-4-5-20251001)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run Phase 1+2 only, skip LLM generation",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    # Phase 1: passage selection
    logger.info("Phase 1: passage selection")
    result = run_pipeline()
    passages = load_passages()

    # Build enriched assignments
    assignments = build_passage_assignments(result, passages)

    # Phase 2: segment assignment
    logger.info("Phase 2: segment assignment")
    plan = solve_segment_assignment(assignments)

    # Print segment plan
    from enrichment.segment_transport import build_segment_report  # pyright: ignore[reportMissingImports]

    print(build_segment_report(plan))

    if args.dry_run:
        logger.info("Dry run — skipping LLM generation")
        return

    # Phase 3: per-segment script generation
    logger.info("Phase 3: script generation (model=%s)", args.model)
    client = anthropic.Anthropic()
    personas = DEFAULT_PERSONAS

    episode_segments: list[EpisodeSegment] = []
    for seg in plan.segments:
        episode_seg = generate_segment_script(seg, client, args.model, personas)
        episode_segments.append(episode_seg)
        logger.info(
            "  Segment '%s': %d turns generated",
            episode_seg.title,
            len(episode_seg.turns),
        )

    # Phase 4: assemble
    episode = assemble_episode(episode_segments, plan)

    # Save outputs
    tag = _make_tag()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # Save JSON
    episode_path = DATA_DIR / "podcast_episode.json"
    with open(episode_path, "w") as f:
        json.dump(episode.model_dump(), f, indent=2)
    logger.info("Saved episode JSON to %s", episode_path)

    # Save script report
    report = build_script_report(episode)
    report_path = REPORTS_DIR / f"podcast_script_{tag}.txt"
    with open(report_path, "w") as f:
        f.write(report)
    logger.info("Saved script report to %s", report_path)

    print("\n" + report)


if __name__ == "__main__":
    main()
