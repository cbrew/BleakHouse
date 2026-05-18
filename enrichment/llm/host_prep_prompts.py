"""Prompt templates for Phase 2.5 (host preparation).

Each prompt is a module-level string constant with a sibling
`*_VERSION` constant tracking when it was last changed materially.
Edits to these strings need a version bump + a changelog entry in
`docs/prompts_changelog.md`. See CLAUDE.md "Schema changes are
breaking API changes" — the same policy applies to prompts.

Three task families live here:
  Phase 2.5a — per-expert pre-interview (INTERVIEW_*).
  Phase 2.5b — per-segment question planning (QUESTION_PLANNING_*).
  Phase 2.5c — listener-pick reading-list winnow (LISTENER_PICK_SYSTEM).

The runtime call sites live in enrichment/host_prep.py; this file is
text-only.

History: these prompts were inline in host_prep.py until 2026-05-18,
when BleakHouse-mz2g (child of BleakHouse-pd1u) moved them here as
part of the version-pinning propagation epic.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Phase 2.5a — per-expert pre-interview
# ---------------------------------------------------------------------------

INTERVIEW_SYSTEM_VERSION = "2026-05-18"
INTERVIEW_SYSTEM = """\
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


INTERVIEW_USER_VERSION = "2026-05-18"
INTERVIEW_USER = """\
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


INTERVIEW_TOOLS_ADDENDUM_VERSION = "2026-05-18"
INTERVIEW_TOOLS_ADDENDUM = """

You have three search tools.  Use `search_openalex` for scholarly works \
(criticism, historical studies, theoretical texts) relevant to your analysis. \
Use `search_wikipedia` for canonical works, Acts, named events, and well-known \
people.  When a Wikipedia article looks central, call `read_wikipedia_article` \
on its tag to access the works listed in that article's bibliography — those \
items become citable as new tags too.

Search based on what the passages actually contain — the novel and \
author at hand, the historical period, the specific topics in front of \
you.  Don't anchor on works from other novels you might have studied.

Each tool result prefixes candidates with stable [ref-N] tags.  In your \
structured output, populate `proposed_references` with these tags ONLY \
(e.g. ["ref-3", "ref-7"]).  Do not invent citation text.  If a citation \
isn't tagged, you can't propose it — search again first.  Search 3–5 times \
total."""


# The structured-parse step that runs after the tool loop. Was inline
# in host_prep.py:323-329 until 2026-05-18.
INTERVIEW_STRUCTURED_PARSE_VERSION = "2026-05-18"
INTERVIEW_STRUCTURED_PARSE_SYSTEM = (
    "Extract the pre-interview response from this expert's analysis. "
    "proposed_references must contain ONLY [ref-N] tags from the "
    "tool conversation — never free-text citations. "
)


# ---------------------------------------------------------------------------
# Phase 2.5b — per-segment question planning
# ---------------------------------------------------------------------------

QUESTION_PLANNING_SYSTEM_VERSION = "2026-05-18"
QUESTION_PLANNING_SYSTEM = """\
You are a podcast host planning questions for a segment of a literary \
discussion about **{novel_title}** by **{novel_author}**.

You've just finished pre-interviews with each expert.  Your job is to \
plan {question_count_phrase} targeted questions that will:

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


QUESTION_PLANNING_USER_VERSION = "2026-05-18"
QUESTION_PLANNING_USER = """\
## Segment: {segment_name}

## Pre-interview responses:

{interview_block}

Plan {question_count_phrase} questions for this segment.  Make them \
specific, conversational, and designed to produce good radio."""


# Count-phrase substitutions for the question-planning prompt.
# Changed "3–5" → "3–4" on 2026-05-18 to match HostBrief.questions
# max_length=4 (BleakHouse-vyo4 / the host_prep two-tier strategy).
QUESTION_COUNT_LONG = "3–4"
QUESTION_COUNT_SHORT = "1–2"


# ---------------------------------------------------------------------------
# Phase 2.5c — listener-pick reading-list winnow
# ---------------------------------------------------------------------------

LISTENER_PICK_SYSTEM_VERSION = "2026-05-18"
LISTENER_PICK_SYSTEM = """\
You are curating a short reading list for a podcast about
**{novel_title}** by {novel_author}. The experts on the show proposed
many references during their pre-interviews. Your job is to pick the
3-8 a *general listener* — someone driving home who enjoyed the
episode, not a Victorianist or specialist — would actually pursue.

LEAN TOWARD:
- Books a listener could find in a public library or order from a
  bookshop.
- Works readable without specialist training — popular history, trade
  biographies, accessible criticism, primary literary works.
- Items that genuinely illuminate the novel under discussion.
- Variety: avoid three picks by the same author or on the same narrow
  sub-topic.

LEAN AWAY FROM:
- Journal articles, conference proceedings, dissertations, archival
  reports — listeners can't easily access these and they read like
  homework.
- Specialist academic monographs, unless the work is a famously
  readable exception.
- Items where the title looks like a paraphrase ("essay on X by Y")
  rather than a real published title.
- Multiple Wikipedia articles on the same subject (pick at most one).

You're not applying a hard rule; use judgement. If a "scholarly"
candidate is genuinely the best Cranford-criticism book a listener
should know about, include it. If a "popular" book is shallow, skip it.

Output ONE JSON object only — no prose, no code fences:

{{"tags": ["ref-3", "ref-7", ...]}}

Pick 3-8 tags. If fewer than 3 candidates qualify, return what you have.
"""
