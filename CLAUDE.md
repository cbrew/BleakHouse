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
uv run python <script>     # run any script
uv run pytest              # run tests
uv run ruff check .        # lint
uv run pyright             # type check
uv run mypy .              # type check (alternative)
```

No tests exist yet. No CI/CD.

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

## Policy: No Guessing About APIs

Do not state API capabilities, limitations, or feature availability as fact without verification. Before making claims about what an API can or cannot do: (1) search the codebase for existing usage patterns, (2) check documentation if the codebase doesn't clarify, (3) if still uncertain, say "I'm not sure." This applies to Anthropic, OpenAI, Google, and all other external APIs.

Anthropic structured output is used in this project via `output_config={"format": {"type": "json_schema", "schema": schema}}`. See `enrichment/test_single.py` for the canonical pattern.

## Key Dependencies

- **Hamilton** - Dataflow orchestration (with `@config.when` for conditional dispatch)
- **Burr** - State machine for multi-step LLM workflows (podcast pipeline, RAG app)
- **Pydantic** - Schema definitions for structured LLM output
- **OpenAI / Anthropic** - LLM APIs (structured output via `beta.chat.completions.parse`)
- **LanceDB** - Vector store for RAG pipeline
- **lxml** - HTML parsing for Gutenberg text
