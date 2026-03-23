"""Phase 3+4: Generate multi-voice podcast script from segment plan.

For each segment, sends passage text + enrichment + expert persona to an LLM.
The LLM writes a multi-voice discussion script with sentence-level TTS annotations.
Segments are independent and could be parallelized.

Usage: uv run python -m enrichment.generate_podcast [--model claude-sonnet-4-6]
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
        vp = p.voice_policy
        lines.append(
            f"**{p.name}** ({p.role}): {p.description}\n"
            f"  Voice: rate={vp.rate}, energy={vp.energy}, "
            f"pause_bias={vp.pause_bias_ms}ms, style={vp.style}"
        )
    return "\n\n".join(lines)


def _build_speaker_styles(personas: list[ExpertPersona]) -> str:
    """Build per-speaker sentence style guidance from persona data."""
    lines = ["**Per-speaker sentence style:**"]
    for p in personas:
        if p.speaking_style:
            lines.append(f"- {p.name}: {p.speaking_style}")
    lines.append("- Host: adaptive clause segmentation for intros.  Clear, guiding.")
    return "\n".join(lines)


def _build_passage_block(
    assignments: list[PassageAssignment],
    prompt_version: int = 2,
) -> str:
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
            if prompt_version >= 2:
                meta_lines.append(
                    "*(Use this quote or extract another verbatim from the text below.)*"
                )
        elif prompt_version >= 2:
            meta_lines.append(
                "*(No pre-selected quote — extract one verbatim from the text below.)*"
            )

        text_block = f"**Text:**\n{pa.text}" if pa.text else ""

        parts = [header] + meta_lines + [text_block]
        blocks.append("\n".join(p for p in parts if p))

    return "\n\n---\n\n".join(blocks)


def _novel_info() -> tuple[str, str, str]:
    """Return (title, author, show_name) for the active novel."""
    from enrichment.novel_prompts import get_active_novel  # pyright: ignore[reportMissingImports]
    cfg = get_active_novel()
    show_name = f"{cfg.title} Unpacked"
    return cfg.title, cfg.author, show_name


SYSTEM_PROMPT = """\
You are a podcast scriptwriter for "{show_name}," a high-quality \
literary discussion about **{novel_title}** by **{novel_author}** in the \
style of BBC Radio 4 or a fine public-radio roundtable.  The tone is \
restrained expressiveness: warm but not gushing, intellectually rigorous \
but never pedantic, with strong phrasing and careful pauses — especially \
around quotations from the novel.

**CRITICAL: This episode discusses {novel_title} by {novel_author} ONLY.  \
All discussion, quotes, characters, and references must be from \
{novel_title}.  Do not reference, quote from, or discuss any other novel \
— not even other novels by the same author.  Every quote must come \
verbatim from the passage text provided below, never from memory.**

The host is an articulate, warmly curious presenter who steers the \
conversation with confidence and genuine affection for the material.  \
{num_experts} expert guests join, each bringing a distinct perspective and voice.

The experts are:
{personas}

The host's voice policy: rate=0.98, energy=medium, pause_bias=220ms, \
style=presenter_warm.

**Style guidelines:**
- Think literary roundtable with brilliant friends, not academic conference.
- Expertise is valued — deep knowledge is welcome — but expressed \
  naturally.  No jargon without explanation.
- Experts react to each other: agree, push back gently, riff on each \
  other's ideas.  This is a conversation, not parallel monologues.
- Direct quotes from the novel are gold.  Set them up, read them with \
  relish, then unpack why they're wonderful.{quote_sourcing}
- No gimmicky filler words.  No "so," "well," "you know" padding.  \
  Every sentence should earn its place.

**For the first segment of the episode**, the host should open by \
welcoming listeners, briefly introducing the show's premise, and then \
introducing each expert with a sentence or two about who they are and \
what they bring.  Subsequent segments need only a brief host transition.

**Critical: sentence-level structured output for TTS**

Each turn must be broken into individual utterances — one sentence or \
short clause each.  Every utterance will be rendered separately by a \
text-to-speech engine, so the annotations you provide directly control \
the listener's experience.

For each utterance, you MUST set:

- **text**: One sentence or short clause.  Max ~25 words.  Split long \
  compound sentences into two utterances.  Treat em dashes as possible \
  clause boundaries.
- **sentence_type**: The functional role — one of: intro, question, \
  quote_setup, quote_reading, analysis, punchline, transition, closing.
- **is_quote**: True only when the utterance IS a direct quote from the \
  novel being read aloud (not paraphrased or discussed).
- **quote_mode**: Controls quote pacing:
  - "none" — normal speech
  - "setup" — text leading into a quote (slightly slower, tiny pause \
    at end)
  - "reading" — the quote itself (slow down ~5-8%, more weight)
  - "commentary" — text immediately after a quote (resume normal pace)
- **rate**: Speaking rate multiplier relative to speaker's base rate.
  - 1.0 = speaker's default
  - 0.92-0.95 = for quote readings and weighty lines
  - 1.02-1.05 = for excited analysis or quick transitions
  - Stay within 0.90-1.05 range.  Conservative variation.
- **pause_before_ms**: Silence before this utterance.
  - 0 = continuation within a thought
  - 120-220 = before a quoted passage
  - 180-260 = after speaker switch (start of turn)
  - 260-420 = after a joke or sting line from previous speaker
- **pause_after_ms**: Silence after this utterance.
  - 300 = normal sentence break
  - 500 = slight emphasis or new thought
  - 800 = paragraph-level break between points
  - 1500 = section break (end of turn before next speaker)
  - The last utterance of each turn: 800-1500.
  - After a weighty quote from the novel: 300-500.
- **emphasis_words**: 0-3 content words deserving slight stress.  Use \
  sparingly.  Best for key literary terms, character names on first \
  mention, or the crux of an argument.
- **passage_ref**: The passage_id being discussed, if any.

**Quote handling is critical.**  When a speaker sets up and reads a \
quote from the novel, use this pattern:
1. quote_setup utterance (quote_mode="setup", rate=0.98, pause_after_ms=150)
2. quote_reading utterance (quote_mode="reading", is_quote=true, \
   rate=0.93, pause_before_ms=150, pause_after_ms=400)
3. quote_commentary utterance (quote_mode="commentary", rate=1.0)

{speaker_styles}

**Turn structure:**
- The Host opens and closes each segment, steering the conversation.
- Each expert: 2-4 turns per segment, 3-8 utterances per turn.
- Experts build on each other — agreement, friendly disagreement, \
  "that reminds me of..."
- Include at least one direct quote from the novel per expert turn{quote_source_turn}.
- **Do NOT re-welcome listeners or re-introduce the show after the first \
  segment.**  Subsequent segments should flow naturally from the previous \
  one, with only a brief host bridge (1-2 sentences).
- End each segment with a host line that bridges to the next segment's \
  topic.  If this is the **final segment**, end with a warm sign-off \
  thanking the experts and listeners — no forward tease.
- Use the enrichment metadata (themes, emotional register) to inform \
  the discussion, but never mention the metadata itself.

**Inter-speaker timing (set via pause_before_ms on first utterance of turn):**
- Same speaker continuation: 120-180 ms
- Speaker switch after analysis: 180-260 ms
- Speaker switch after joke/sting: 260-420 ms
- Before segment pivot or "Welcome back": 500-900 ms
"""


_QUOTE_SOURCING_V2 = """
- **Quote from the assigned passages.**  Each passage includes a \
best_quote — use it.  If a passage's best_quote is null or you \
need a second quote, extract one verbatim from the passage text.  \
Do not invent quotations or quote from memory — every quote \
must come from a passage provided in this segment.  If an expert \
wants to reference a passage assigned to another expert, that \
is encouraged (it makes for better conversation), but the quote \
must still be verbatim from that passage's text."""


def build_messages(
    segment: PlannedSegment,
    personas: list[ExpertPersona],
    is_first_segment: bool = False,
    prompt_version: int = 2,
    previous_segment_title: str | None = None,
    next_segment_title: str | None = None,
) -> tuple[str, str]:
    """Build system and user messages for a segment's LLM call.

    prompt_version=1: original prompts
    prompt_version=2: passage-grounded quoting instructions
    """
    if prompt_version >= 2:
        quote_sourcing = _QUOTE_SOURCING_V2
        quote_source_turn = ",\n  drawn from the assigned passages"
    else:
        quote_sourcing = ""
        quote_source_turn = ""

    title, author, show_name = _novel_info()

    system = SYSTEM_PROMPT.format(
        personas=_build_persona_block(personas),
        num_experts=len(personas),
        speaker_styles=_build_speaker_styles(personas),
        quote_sourcing=quote_sourcing,
        quote_source_turn=quote_source_turn,
        show_name=show_name,
        novel_title=title,
        novel_author=author,
    )

    user_parts: list[str] = [
        f"## Segment: {segment.template.name}",
        f"**Type:** {segment.template.segment_type}",
    ]

    if is_first_segment:
        user_parts.append(
            "\n**This is the FIRST segment of the episode.**  The host should "
            "welcome listeners, briefly introduce the show's premise, and then "
            "introduce each expert with warmth — who they are, what makes them "
            f"interesting, why their perspective matters for *{title}*."
        )
    elif previous_segment_title:
        user_parts.append(
            f"\n**This is a CONTINUATION of the episode** (not the first segment).  "
            f"Do NOT welcome listeners or re-introduce the show or experts.  "
            f"The previous segment was: \"{previous_segment_title}\".  "
            f"The host should open with a brief 1-2 sentence bridge that connects "
            f"what was just discussed to this segment's topic."
        )

    if next_segment_title:
        user_parts.append(
            f"\n**Next segment preview:** The segment after this one is called "
            f"\"{next_segment_title}\".  End with a host line that naturally "
            f"bridges to that topic — a brief tease, not a full introduction."
        )
    elif not is_first_segment:
        user_parts.append(
            "\n**This is the FINAL segment of the episode.**  End with a warm "
            "sign-off: the host thanks the experts by name, reflects briefly on "
            "what was covered, and thanks the listeners.  No forward tease."
        )

    if segment.assignments:
        user_parts.extend([
            "",
            "## Assigned Passages",
            "",
            _build_passage_block(segment.assignments, prompt_version),
        ])
    else:
        user_parts.extend([
            "",
            "## No Assigned Passages",
            "",
            "No specific passages are assigned for this segment. Drawing on your "
            f"knowledge of *{title}* by {author}, produce a rich discussion "
            f"that fits this segment's theme: **{segment.template.name}** "
            f"({segment.template.segment_type}).",
            "",
            "Reference specific chapters, characters, scenes, and quotes from the "
            "novel as you remember them. The discussion should be as detailed and "
            "grounded as if you had passages in front of you.",
        ])

    return system, "\n".join(user_parts)


# ---------------------------------------------------------------------------
# LLM generation
# ---------------------------------------------------------------------------


def generate_segment_script(
    segment: PlannedSegment,
    client: anthropic.Anthropic,
    model: str,
    personas: list[ExpertPersona],
    is_first_segment: bool = False,
    prompt_version: int = 2,
    previous_segment_title: str | None = None,
    next_segment_title: str | None = None,
) -> EpisodeSegment:
    """Generate a multi-voice script for one segment via structured output."""
    system_msg, user_msg = build_messages(
        segment, personas, is_first_segment, prompt_version,
        previous_segment_title=previous_segment_title,
        next_segment_title=next_segment_title,
    )

    logger.info(
        "Generating script for segment '%s' (%d passages)",
        segment.template.name,
        len(segment.assignments),
    )

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.messages.parse(
                model=model,
                max_tokens=16384,
                system=system_msg,
                messages=[{"role": "user", "content": user_msg}],
                output_format=EpisodeSegment,
            )

            logger.info(
                "  Response: stop_reason=%s, input_tokens=%d, output_tokens=%d",
                response.stop_reason,
                response.usage.input_tokens,
                response.usage.output_tokens,
            )

            assert response.parsed_output is not None, (
                f"Structured output parsing failed for segment '{segment.template.name}'"
            )
            return response.parsed_output
        except (Exception,) as e:
            if attempt < max_attempts:
                logger.warning(
                    "  Attempt %d/%d failed for '%s': %s. Retrying...",
                    attempt, max_attempts, segment.template.name, e,
                )
            else:
                raise


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
        title=f"{_novel_info()[0]}: A Literary Discussion",
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
    """Generate a human-readable script report with TTS annotations."""
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
            lines.append(f"[{turn.speaker}]")
            for utt in turn.utterances:
                prefix = "  > " if utt.is_quote else "  "
                ref = f"  [{utt.passage_ref}]" if utt.passage_ref else ""

                # Timing annotations
                timing_parts: list[str] = []
                if utt.pause_before_ms > 0:
                    timing_parts.append(f"+{utt.pause_before_ms}ms")
                if utt.pause_after_ms > 500:
                    timing_parts.append(f"<{utt.pause_after_ms}ms>")
                if utt.rate != 1.0:
                    timing_parts.append(f"@{utt.rate:.2f}x")
                if utt.quote_mode != "none":
                    timing_parts.append(f"[{utt.quote_mode}]")
                if utt.emphasis_words:
                    timing_parts.append(f"*{','.join(utt.emphasis_words)}*")

                timing = f"  ({' '.join(timing_parts)})" if timing_parts else ""
                lines.append(f"{prefix}{utt.text}{ref}{timing}")
            lines.append("")
        lines.append("-" * 72)
        lines.append("")

    # Metadata
    lines.append("METADATA")
    lines.append(f"  Chapters: {', '.join(episode.metadata.chapters_covered)}")
    lines.append(f"  Characters: {', '.join(episode.metadata.characters_featured[:20])}")
    lines.append(f"  Arcs: {', '.join(episode.metadata.arcs_tracked)}")
    lines.append(f"  Total passages: {episode.metadata.total_passages}")

    # Stats
    total_utterances = sum(
        len(t.utterances) for s in episode.segments for t in s.turns
    )
    total_quotes = sum(
        1 for s in episode.segments for t in s.turns
        for u in t.utterances if u.is_quote
    )
    quote_setups = sum(
        1 for s in episode.segments for t in s.turns
        for u in t.utterances if u.quote_mode == "setup"
    )
    lines.append(f"  Total utterances: {total_utterances}")
    lines.append(f"  Total quotes: {total_quotes}")
    lines.append(f"  Quote setups: {quote_setups}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate podcast script")
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-6",
        help="Anthropic model to use (default: claude-sonnet-4-6)",
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
    for i, seg in enumerate(plan.segments):
        prev_title = plan.segments[i - 1].template.name if i > 0 else None
        next_title = plan.segments[i + 1].template.name if i < len(plan.segments) - 1 else None
        episode_seg = generate_segment_script(
            seg, client, args.model, personas, is_first_segment=(i == 0),
            previous_segment_title=prev_title,
            next_segment_title=next_title,
        )
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
