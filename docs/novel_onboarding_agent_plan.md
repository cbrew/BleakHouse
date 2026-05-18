# Novel-onboarding meta-agent — plan

Status: PLAN (not implemented). Tracked in beads — see footer for issue IDs.

## What this is

Today, when we add a novel to the BleakHouse corpus, the conversational
flow is:

1. User says "let's add X" (or `bash scripts/add_novel.sh <id>` fails
   because the registries don't know about X yet).
2. Claude (in the Claude Code session) reads CLAUDE.md, finds the
   three registries that need editing
   (`enrichment/axes.py:NOVELS`,
   `enrichment/segment_novel.py:NOVELS`,
   `enrichment/novel_prompts.py:NOVEL_CONFIGS` + `get_novel_arcs`),
   looks at peer-novel entries to crib structure, reads the Gutenberg
   HTML to decide chapter/paragraph segmentation, proposes the three
   edits, applies them, and only then is `add_novel.sh` runnable.
3. User reviews the diff. Often there's a round trip on arcs/axes.
4. Once the diff is committed, `add_novel.sh` runs the deterministic
   pipeline (download, segment, batch enrichment, batch contexts,
   clustering).

The creative work — picking arcs, choosing axes values, deciding
chapterless-vs-chaptered segmentation, picking start/end markers for
modernist novels — is done by Claude in-session, not by a human.
But it's done by re-deriving the recipe from CLAUDE.md each time
rather than following a documented playbook, which means:

- Quality varies across sessions because different Claude invocations
  weight CLAUDE.md guidance differently.
- The output is conversational text + edits, not a structured
  artifact you can diff against a previous Claude's output.
- We can't tell from `git log` whether a particular arc choice was
  considered against alternatives or just the first thing that came
  to mind.

The "agentify" move is to **make the implicit recipe explicit**: a
documented playbook (and, if it earns its keep, a Claude Code skill
or script wrapper) that any Claude session executes deterministically
enough to produce comparable outputs across sessions, while keeping
the human-review gate before commit.

## Scope

In scope:

- Producing the three registry edits for a new novel from
  `(novel_id, gutenberg_id, [optional] hints)`.
- A smoke-test pass that confirms the edits parse and segmentation
  works on a small text slice.
- An artefact the human reviews before commit (draft diff or branch).

Out of scope:

- Running `add_novel.sh` itself — that's already deterministic.
- Generating audio, rendering podcast scripts, anything past the
  registry edits.
- Modifying segmentation strategies (chapterless paragraph windows,
  start/end markers, etc.) themselves — only choosing among existing
  strategies per-novel.
- Tier L / Tier P benchmark fixtures, eval, or scoring.
- Changing global axes definitions in `enrichment/axes.py:AXES`
  (only adding the per-novel entry to `NOVELS`).

## Recipe (the agent's loop, prose form)

Given `(novel_id, gutenberg_id, optional hints)`:

1. **Confirm Gutenberg metadata**: fetch `https://www.gutenberg.org/cache/epub/<id>/pg<id>-images.html`; verify title + author match the novel_id. Surface the HTML filename to use in `segment_novel.py:NOVELS`.

2. **Segmentation probe**: scan the HTML for chapter markers (`<h2>CHAPTER`, `<h2>Chapter`, etc.) and count them. Classify:
   - **Chaptered** (most Victorian novels): record `gutenberg_id`, `html_filename`. Standard segmentation.
   - **Chapterless modernist** (e.g. Mrs Dalloway): no `<h2>` chapter markers; needs `chunk_paragraphs`, `start_marker`, `end_marker` instead. Read the opening + closing 2k chars to propose plausible markers and a `chunk_paragraphs` value derived from peer-novel paragraph density.

3. **Axes lookup**: read `enrichment/axes.py:AXES` for the current axis catalog. Read peer-novel entries in `NOVELS` for shape. Decide axes values for the new novel — this is judgement work and should produce *evidence* alongside each choice (one-line "why" per axis value).

4. **Arc proposal**: read the existing `get_novel_arcs` entries for stylistic reference. Propose 3 arcs for the new novel. Each arc has a name + a 2-3 sentence framing. The recipe must require that arcs come from a deliberate reading of the text (or, if Claude knows the novel from training, an explicit acknowledgement of that with cited features — not vibes).

5. **NOVEL_CONFIGS entry**: produce the `NOVEL_CONFIGS` block, cribbing from peer novels for the unfamiliar fields.

6. **Smoke test**: run the new registry edits through a dry-run import (Python `from enrichment import axes, segment_novel, novel_prompts; …`). Then run segmentation on the first ~5000 chars of the HTML to confirm it produces non-empty passages.

7. **Output**: write the three diffs to a branch (or `git diff > artefact.patch`) plus a one-page rationale doc explaining the axis/arc choices and what evidence they're based on. The human approves the diff and merges.

## Tools the agent needs

- `bash`: file reads, `git diff`, `python -c "..."` smoke imports.
- HTML fetch (curl or Python `urllib`) for the Gutenberg text.
- Edit/Read on the three registry files.
- (Optional) WebFetch for the Gutenberg landing page if the canonical
  HTML URL has changed format.

Nothing in this list requires the LangChain/AgentExecutor frame; the
existing Claude Code tool set is sufficient.

## Verification gates (must pass before the human sees the diff)

1. The three edited files still import cleanly
   (`uv run python -c "import enrichment.axes, enrichment.segment_novel, enrichment.novel_prompts"`).
2. `enrichment.segment_novel.segment(novel_id)` runs without error
   over the first N paragraphs of the HTML and produces ≥1 passage.
3. `get_novel_arcs(novel_id)` returns a 3-element list.
4. `axes.py:NOVELS` entry has all required fields.
5. The rationale doc names *evidence* for each axis value and arc
   choice (failing this gate ⇒ Claude has to re-derive rather than
   ship vibes).

## Failure modes to plan for

- **Chapterless novel where opening prose looks like prose anywhere**
  (e.g. *Ulysses* opening): start/end markers are ambiguous; agent
  should escalate to human rather than guess.
- **Novel Claude doesn't know well**: arc and axis choices become
  speculation. Recipe must require either reading enough of the HTML
  to ground the proposals, or explicit "I don't have enough evidence,
  please provide arcs" failure mode.
- **Gutenberg HTML structure variations**: occasional novels have
  `<div class="chapter">` instead of `<h2>`, or front-matter that
  looks like chapter 1. Smoke-test (4) catches this; recipe should
  not silently produce zero passages.
- **Duplicate axis values across novels skewing analysis**: not the
  agent's call to fix, but it should surface "this novel's axes
  values are identical to <peer> — confirm intentional".

## Open questions (decide before implementing)

1. **Form factor**: a Claude Code skill (`/onboard-novel <gutenberg_id>`)?
   A plain playbook doc that conversational Claude reads? A standalone
   Python script? Skill is the closest match to existing patterns
   (cf. `init`, `review`, `simplify` skills); the playbook-doc option
   is the lightest weight.
2. **Where does the rationale doc live**? `data/novels/<novel_id>/onboarding_rationale.md`? `docs/novels/`? In the commit message?
3. **What does "Claude knows the novel from training" look like as evidence?** A list of structural features (chapter count, narrator, principal characters) cross-checked against the actual HTML? A summary the human can spot-check?
4. **Does the agent ever run `add_novel.sh`** after the diff is reviewed, or does that stay a separate manual step? Separate is safer; chained is faster.
5. **How do we test the agent**? Cherry-pick a novel from the existing corpus, blank out its registry entries, and have the agent re-derive them. Compare against the committed truth.

## Out-of-scope adjacent ideas

These keep coming up; they're not part of this plan:

- Generalised "do anything an agent" framework. Resist. (CLAUDE.md:
  "no DAG framework, no state machine library.")
- LLM-judge on the arc choices. The user has been explicit that
  preferences-vs-quality at this scale is human-judged (cf. memory
  `feedback_human_first_quality_judging`).
- Automating axes addition (vs picking from the existing catalog).
  That's a bigger architectural call and shouldn't ride on this
  ticket.

## Beads tracking

This plan is tracked in beads. The parent epic links here; child
issues capture spec, implementation, pilot, and documentation phases.
See bd for current state.
