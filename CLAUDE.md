# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BleakHouse is a research project with two main workstreams built on **Hamilton** (dataflow orchestration) and **Burr** (state machine management):

1. **Literary Podcast Pipeline** (core) - Transforms Dickens' *Bleak House* into structured podcast scripts using LLM-driven literary analysis
2. **RAG Tutorial Pipeline** (secondary) - A modular blog-ingestion and question-answering system


## Build & Run

Uses uv with PEP 621 pyproject.toml. Python 3.12+.

```bash
uv sync                    # install dependencies
uv run dvc pull -r r2      # materialise data/runs/ from DVC remote (~165 MB)
uv run python <script>     # run any script
uv run pytest              # run tests
uv run ruff check .        # lint
uv run pyright             # type check
uv run mypy .              # type check (alternative)
```

After producing a new run locally:

```bash
uv run dvc commit <stage>@<run_id>   # records the on-disk hash
uv run dvc push -r r2                # uploads to R2
git add config.json runs.yaml dvc.lock
git commit && git push
```

Deploy the Fly demo (replaces the live site):

```bash
bash scripts/deploy_demo.sh          # tar data/runs/, fly deploy --local-only
```

Onboard a new novel end-to-end (download → segment → enrichment batch →
contexts batch → clustering):

```bash
bash scripts/add_novel.sh <novel_id>   # e.g. mrs_dalloway, oliver_twist
```

The script is idempotent (each step skips if its output is on disk) and
verifies that the novel is registered in `enrichment/axes.py`,
`enrichment/segment_novel.py`, and `enrichment/novel_prompts.py` before
it touches the network. Wall-clock is ~1-2 hours for a typical novel,
dominated by the two batch waits.

**Adding a novel** = three manual registry edits before `add_novel.sh`:
- `enrichment/axes.py` — `NOVELS` tuple (key, id, title, author, year)
- `enrichment/segment_novel.py` — `NOVELS` dict (gutenberg_id, html_filename; for chapterless modernist novels, set `chunk_paragraphs` + `start_marker` + `end_marker`)
- `enrichment/novel_prompts.py` — `NOVEL_CONFIGS` entry + a 3-arc list under `get_novel_arcs`

The data tree (~165 MB, JSON only) is baked into the image at build
time via a tarball with symlinks dereferenced. Audio mp3s stay in R2
and are 302-redirected by the webapp using URLs parsed from `dvc.lock`
at app startup. No DVC binary or R2 secrets in the container.

Note: `dvc pull` is **not** run by `deploy_demo.sh` — it deletes
git-tracked files from removed stages (run_manifest in particular).
Run it manually after `git pull` to refresh your local cache.

No CI/CD.

## Gotchas

- **DVC-tracked files are read-only symlinks.** `data/experiments.db` and per-run JSONs (`phase2_5_reading_list.json`, etc.) point into the DVC cache; mutation fails with `readonly database` or `Permission denied`. Run `uv run dvc unprotect <path>` before writing.
- **`build_manifest` runs before the listener-pick winnower**, so `manifest.json`'s embedded `host_prep.reading_list` is the unfiltered candidate set. The winnowed `recommended` only lands in `data/runs/<id>/phase2_5_reading_list.json` — read that file as source of truth.
- **Three reading-list schemas coexist:** new (`entries` + `recommended`), legacy (`verified` + `unverified`), and hybrid (legacy fields *plus* a 3-5-item `recommended` from the listener-pick post-pass). Route any manifest with non-empty `recommended` through the new-schema renderer.
- **Webapp run discovery is DB-driven.** New runs need (1) `scripts/generate_run_manifest.py --run <id>` to write `run_manifest.json`, then (2) `uv run python -m enrichment.expdb scan` to refresh `data/experiments.db` (which itself usually needs `dvc unprotect` first).
- **`dvc.lock` carries perpetual churn** from unrelated `render_audio.py` md5 updates that aren't from the current branch. `git checkout -- dvc.lock` before staging feature commits unless you're deliberately updating DVC tracking.

## Architecture

### Literary Podcast Pipeline (core system)

This is the main, most developed part of the project. The pipeline:
1. Downloads and parses *Bleak House* from Project Gutenberg
2. Uses an LLM to generate structured literary analysis per chapter
3. Progressively merges chapter notes into a podcast script via a Burr state machine

**Pydantic schema hierarchy** (the backbone of the system):
- `literary_elements.py` - Base types: `KeyMoments`, `ThemesAndAnalysis`, `CharacterHighlight`, `BehindTheScenesInsight`, `CrossReferences`, `ModernRelevance`, `NarrativeStructure`, `LiteraryStyle`
- `chapter_schema.py` - `ChapterSchema` wraps a list of literary elements (per-chapter LLM output)
- `podcast_schema.py` - `Segment` -> `PodcastScript` (the merge target)

**Data acquisition:**
- `download.py` - Hamilton module: fetches Gutenberg HTML zip, parses chapters via lxml xpath
- `driver.py` - Hamilton driver that executes the download pipeline

**LLM prompting:**
- `notes_prompt.py` - System prompt + few-shot example for chapter -> `ChapterSchema` extraction
- `podcast_prompt.py` - Example `Segment` and `PodcastScript` for merge prompts

**Orchestration** (in `BleakHouse.ipynb`):
- Burr state machine with actions: `obtain_chapters` -> `make_notes` -> `first_merge`/`merge` -> `end_reading`
- `make_notes` calls OpenAI structured output to produce `ChapterSchema` per chapter
- `first_merge` combines the first two chapters' notes into a `PodcastScript`
- `merge` progressively folds each new chapter's notes into the running script
- `metrics.py` - Token counting via Anthropic API (Hamilton `@config.when` dispatch)

### RAG Pipeline (secondary, self-contained)

A tutorial-style modular RAG app, progressively refined through v1/v2/v3 in `TwoLayer.ipynb`:
- `actions/ingest_blog.py` - Scrapes blog HTML, chunks text with overlapping windows, embeds with OpenAI, stores in LanceDB
- `actions/ask_question.py` - Retrieves relevant chunks from LanceDB + OpenAI/Anthropic completion
- `two_layer_app.py` - Burr app wiring ingest and Q&A with Hamilton drivers, OpenTelemetry tracing

**Text-to-speech:**
- `enrichment/render_audio.py` - Renders structured podcast episodes to audio via Gemini TTS (flash/pro), with per-speaker voice assignment, accent direction, delivery annotations, and disk caching

## Policy: No Guessing, No Unsupported Claims

**Do not state things as fact without evidence.** This applies to everything, not just APIs:

- **APIs:** Do not claim what an API can or cannot do without checking the codebase or documentation first.
- **Literary claims:** Do not assert that a novel is "Dickens's most comedic" or "has strong social themes" without evidence. Use the enrichment data (provision dimensions) as the formal measure of what each novel affords. If no data exists, say so.
- **Technical claims:** Do not assert that data is "too large for git" or that a process "will take X minutes" without checking. Look at file sizes, check timing data, read the code.
- **Causal claims:** Do not invent explanations for observed patterns. If a correlation exists, report it. If you don't know the mechanism, say "I don't know why."

The standard is: *check first, then speak.* If you cannot verify a claim, frame it as a question or hypothesis, not as a fact. Post-hoc rationalisation is worse than saying "I don't know." And if you don't need to say it, just don't.

Anthropic structured output is used in this project via `output_config={"format": {"type": "json_schema", "schema": schema}}`. See `enrichment/test_single.py` for the canonical pattern.

## Key Dependencies

- **Hamilton** - Dataflow orchestration (with `@config.when` for conditional dispatch)
- **Burr** - State machine for multi-step LLM workflows (podcast pipeline, RAG app)
- **Pydantic** - Schema definitions for structured LLM output
- **OpenAI / Anthropic** - LLM APIs (structured output via `beta.chat.completions.parse`)
- **LanceDB** - Vector store for RAG pipeline
- **lxml** - HTML parsing for Gutenberg text


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ca08a54f -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->
