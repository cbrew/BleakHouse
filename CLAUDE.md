# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BleakHouse is a research project with two main workstreams built on **Hamilton** (dataflow orchestration) and **Burr** (state machine management):

1. **Literary Podcast Pipeline** (core) - Transforms Dickens' *Bleak House* into structured podcast scripts using LLM-driven literary analysis
2. **RAG Tutorial Pipeline** (secondary) - A modular blog-ingestion and question-answering system


## First-time setup (clone → working system)

System deps:
- `ffmpeg` (pydub mp3 export). `apt install ffmpeg` on Debian/Ubuntu;
  `brew install ffmpeg` on macOS.
- `bd` (beads issue tracker). Install via the project's standard
  route — see https://github.com/steveyegge/beads. The bootstrap
  script wires up `git config core.hooksPath` and rehydrates the
  issue tree from the committed `.beads/issues.jsonl`.
- (Optional, for `tools/forced_align/` GPU): a CUDA runtime matching
  the torch wheel pulled by `uv sync` in that subdir. CPU torch works
  too; just slower.

Then:

```bash
git clone <repo>
cd BleakHouse
cp .env.example .env
chmod u+w .env && $EDITOR .env && chmod u-w .env   # fill in keys
bash scripts/bootstrap.sh                          # uv sync × 2 + playwright + bd hooks/import + ffmpeg probe
# bash scripts/bootstrap.sh --pull-cas             # also prefetch ~7 GB CAS bytes from R2
```

`BLEAKHOUSE_CAS_ROOT` in `.env` is per-machine. Leave unset for the
in-repo default (`<repo>/data/cas/`); set to a path on a fast / large
volume if you'd rather host CAS bytes elsewhere. See the comments in
`.env.example` for the conventions used on the Mac dev box vs Linux.

## Beads state in git

The bd issue tree (issues, dependencies, memories) is committed at
`.beads/issues.jsonl` so a fresh clone sees the same history. The
binary Dolt database (`.beads/dolt/`), runtime sockets/locks, the
credential key, and `.beads/backup/` are gitignored via
`.beads/.gitignore`.

`scripts/bootstrap.sh` step 5/6 runs `bd hooks install` (sets
`core.hooksPath = .beads/hooks/` — a per-clone setting that git
itself does NOT commit) and `bd import` (rehydrates the local Dolt
db from the committed JSONL). Auto-import would do the same on first
read; running it during bootstrap surfaces errors loudly.

`bd init --stealth` adds `.beads/` to `.git/info/exclude` to hide
the tracker entirely from git. We deliberately operate in non-stealth
mode so the issue tree travels with the repo. If you ever see
`auto-export: git add failed: exit status 1` warnings on `bd update`
/ `bd close`, check `.git/info/exclude` for a stray `.beads/` line.

## Build & Run

Uses uv with PEP 621 pyproject.toml. Python 3.12+.

```bash
uv sync                    # install dependencies
uv run python <script>     # run any script
uv run pytest              # run tests
uv run ruff check .        # lint
uv run pyright             # type check
uv run mypy .              # type check (alternative)
```

After producing a new run locally:

```bash
# enrichment/render_audio.py auto-puts shard bytes into <CAS_ROOT>/files/md5/...
# Push to R2 explicitly via the migration script's populate phase, or per-md5
# via cas.store.push(md5).
uv run python -c "from cas import store; [store.push(m) for m in <md5_list>]"
git add config.json data/runs/<id>/ ...
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
time via a tarball. Audio mp3s stay in R2 and are 302-redirected by
the webapp using URLs built from per-run `audio/assets.json` and
`audio/shards.json` at app startup. No R2 secrets in the container.

No CI/CD.

## Storage: CAS replaces DVC

DVC was retired in BleakHouse-zmlw (2026-05-07). Bytes are now
addressed by md5 via the `cas/` package:

- `cas.store.put(path) -> md5` — copy bytes into `<CAS_ROOT>/files/md5/<prefix>/<rest>` and return md5
- `cas.store.url(md5) -> str` — R2 public URL
- `cas.store.local_path(md5) -> Path | None` — `None` if not in local CAS
- `cas.store.push(md5)` / `cas.store.pull(md5)` — R2 round-trip

`<CAS_ROOT>` defaults to `<repo>/data/cas`; override with
`BLEAKHOUSE_CAS_ROOT`. R2 push/pull needs `R2_ACCESS_KEY_ID`,
`R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT_URL`. Webapp does NOT need
credentials — it serves redirects only.

Per-run audio metadata (no audio bytes in working tree):

- `data/runs/<id>/audio/assets.json` — legacy single-mp3 runs:
  `{"schema_version":1, "assets": {"podcast.mp3": "<md5>", ...}}`
- `data/runs/<id>/audio/shards.json` — per-turn shard runs:
  same shape as before; each shard has `md5` populated by `cas.put`

## Gotchas

- **`build_manifest` runs before the listener-pick winnower**, so `manifest.json`'s embedded `host_prep.reading_list` is the unfiltered candidate set. The winnowed `recommended` only lands in `data/runs/<id>/phase2_5_reading_list.json` — read that file as source of truth.
- **Three reading-list schemas coexist:** new (`entries` + `recommended`), legacy (`verified` + `unverified`), and hybrid (legacy fields *plus* a 3-5-item `recommended` from the listener-pick post-pass). Route any manifest with non-empty `recommended` through the new-schema renderer.
- **Webapp run discovery is DB-driven.** New runs need (1) `scripts/generate_run_manifest.py --run <id>` to write `run_manifest.json`, then (2) `uv run python -m enrichment.expdb scan` to refresh `data/experiments.db`.

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
   git push
   git status  # MUST show "up to date with origin"
   ```
   Do NOT run `bd dolt push`. This repo has no Dolt remote and doesn't
   need one — bd's cross-machine sync is via the committed
   `.beads/issues.jsonl`, which `git push` already handles. `bd dolt
   push` will prompt to configure a remote; ignore it.
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->
