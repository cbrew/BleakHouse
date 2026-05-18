# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BleakHouse is a research project that turns Victorian novels — *Bleak House* foremost among them — into structured podcast scripts via LLM-driven literary analysis, then renders them to audio. The pipeline is a hand-rolled phase-based runner in `enrichment/run_pipeline.py` that dispatches on a `--pipeline` flag (`transport` / `no-passages` / `embedding`) and writes per-run JSON artefacts into `data/runs/<run_id>/`. A `data/content.db` (sqlite, built from those JSONs) backs the FastAPI webapp. Audio is rendered via Gemini TTS and stored in R2 through the small content-addressed store in `cas/`.


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

The pipeline is plain Python — no DAG framework, no state machine library. Each phase reads JSON from `data/runs/<run_id>/` and writes JSON back; the runner in `enrichment/run_pipeline.py` orchestrates them sequentially.

**Entry point:**
- `enrichment/run_pipeline.py` — unified runner with `--pipeline {transport,no-passages,embedding}` dispatch and optional `--host-prep`. Replaces the earlier separate run.py/no_passages_run.py/embedding_run.py modules. The wrapper `scripts/add_novel.sh` chains download → segment → enrichment batch → contexts batch → clustering for a new novel.

**Phases (per run):**
- Phase 0 — `enrichment/segment_novel.py` / `enrichment/segment.py`: downloads a novel from Project Gutenberg and segments it into passages.
- Phase 1–2 — passage selection. Three dispatch strategies share schemas but differ in retrieval:
  - `transport` — `enrichment/transport_podcast.py` uses OR-tools to assign passages to arcs under demand constraints.
  - `embedding` — `enrichment/embedding_podcast.py` uses cosine-similarity ranking against arc embeddings.
  - `no-passages` — bypasses passage selection; lets the host LLM speak from memory.
- Phase 2.5 — `enrichment/run_pipeline.py:run_phase_2_5` builds the reading list (`phase2_5_reading_list.json`) via `enrichment/host_prep.py` + `enrichment/reference_tools.py` + `enrichment/reference_verify.py`.
- Phase 3+ — rendering: `enrichment/render_audio.py` calls Gemini TTS (flash/pro) with per-speaker voice assignment, accent direction, delivery annotations, and disk-backed shard caching. Shards are stored by md5 in the CAS and pushed to R2.

**Structured output:**
The schemas that the active pipeline uses for LLM `output_config={"format": {"type": "json_schema", "schema": ...}}` calls live in `enrichment/` (e.g. arc demands, expert briefs, citation registry).

**Webapp:**
- `webapp/app.py` — FastAPI app deployed on Fly. Reads `data/content.db` (built by `scripts/build_content_db.py` from per-run JSONs) and 302-redirects audio URLs to R2 via `cas.store.url(md5)`.
- `webapp_v2/` — newer, cleaner-room reimplementation in progress (see `BleakHouse-tgow`); not yet the deployed app.

## Policy: No Guessing, No Unsupported Claims

**Do not state things as fact without evidence.** This applies to everything, not just APIs:

- **APIs:** Do not claim what an API can or cannot do without checking the codebase or documentation first.
- **Literary claims:** Do not assert that a novel is "Dickens's most comedic" or "has strong social themes" without evidence. Use the enrichment data (provision dimensions) as the formal measure of what each novel affords. If no data exists, say so.
- **Technical claims:** Do not assert that data is "too large for git" or that a process "will take X minutes" without checking. Look at file sizes, check timing data, read the code.
- **Causal claims:** Do not invent explanations for observed patterns. If a correlation exists, report it. If you don't know the mechanism, say "I don't know why."

The standard is: *check first, then speak.* If you cannot verify a claim, frame it as a question or hypothesis, not as a fact. Post-hoc rationalisation is worse than saying "I don't know." And if you don't need to say it, just don't.

Anthropic structured output is used in this project via `output_config={"format": {"type": "json_schema", "schema": schema}}`. See `enrichment/test_single.py` for the canonical pattern.

## Policy: Wikipedia-sourced DOIs and ISBNs are authoritative

When a citation entry's `source` is `wikipedia_further_reading` (i.e. it was extracted from a `{{cite book}}`/`{{cite journal}}` template in a Wikipedia article via `mwparserfromhtml`), its DOI and ISBN fields are *authoritative*. They were entered by Wikipedia editors and are part of a curated bibliography.

In the verification cascade (`enrichment/reference_verify.py`):

- A constructed URL from a Wikipedia-sourced DOI (`https://doi.org/<doi>`) or ISBN (`https://openlibrary.org/isbn/<isbn>`) is **admitted regardless of HEAD outcome**. The HEAD check is recorded in `ResolverResult.head_verified` for forensics, but failure is not grounds to drop the citation.
- Rationale: HEAD failures on these endpoints have two common causes — (1) OpenLibrary doesn't have the specific edition catalogued; (2) the DOI registrar is temporarily down or rate-limiting. Neither invalidates the underlying identifier. Wikipedia's editorial process is the warrant.
- For non-Wikipedia identifiers (e.g., a DOI surfaced by an LLM tool call without bibliographic provenance), the strict HEAD-verify rule still applies.

We accept the residual risk: if a Wikipedia editor entered a wrong ISBN, we will surface it. That is the editorial system's responsibility, not ours. We will never be blamed for trusting a Wikipedia-curated identifier; we *would* be blamed for dropping a legitimate citation because a downstream resolver was flaky.

## Policy: Schema changes are breaking API changes

Every Pydantic class used as a `response_model` for a structured-output LLM call lives in `enrichment/llm/schemas.py`. Each class carries a `schema_version: ClassVar[str]` field and an in-file CHANGELOG block. Schema edits are governed by `docs/schemas_changelog.md`: patch (no migration), minor (verified-compatible tightening), major (saved data needs a migration script). When you edit `enrichment/llm/schemas.py`, add a changelog entry in `docs/schemas_changelog.md` and bump the affected class's `schema_version` if the change isn't a pure patch.

The bump rules are spelled out in `docs/schemas_changelog.md`. The empirical test is: run `model_validate` against `data/runs/*/phase3_episode.json` (or the relevant artefact) with the new schema. If it fails on any saved run, you're in major-bump territory.

The seam (`enrichment/llm/`) does not mutate schemas at runtime — `_strictify_for_openai` and `_StrictBase` were removed in BleakHouse-vyo4. All strictness comes from `model_config = ConfigDict(extra='forbid')` declared per-class, and any structural constraints (`min_length`, `max_length`) come from the Pydantic Field declaration.

## Key Dependencies

- **Anthropic / OpenAI / Google GenAI / Cerebras** — LLM APIs. Anthropic structured output via `output_config={"format": {"type": "json_schema", ...}}` (see `enrichment/test_single.py` for the canonical pattern); Gemini for TTS.
- **Pydantic** — schema definitions for structured LLM output.
- **FastAPI / uvicorn** — webapp serving `data/content.db`.
- **boto3** — R2 client for CAS push/pull.
- **mwparserfromhtml** — Wikipedia bibliography parsing (post-`BleakHouse-hgws`).
- **OR-tools** — assignment optimisation in `transport_podcast.py`.
- **LanceDB** — vector store for the embedding-pipeline variant.
- **lxml** — HTML parsing for Gutenberg text.
- **pydub** — mp3 export (needs `ffmpeg`).
- **playwright** — used by webapp end-to-end tests.


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
