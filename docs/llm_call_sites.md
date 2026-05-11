# LLM call sites

Verified inventory of every place this repo calls an LLM, as of branch `experiment/cerebras-llm` (2026-04-22). Built to scope a possible Cerebras swap.

Status legend:
- **LIVE** — reachable from an active pipeline entry point (`enrichment/run_pipeline.py`, `enrichment/run_novel.py`, `enrichment/embedding_run.py`).
- **SCRIPT** — top-level CLI, run directly (`uv run python -m ...`), not imported by anything.
- **ORPHAN** — not imported, not a documented CLI entry point; likely dead or experimental.

No unified LLM wrapper exists. Each module instantiates its own client.

## OpenAI

OpenAI is reached indirectly through LanceDB's embedding-registry adapter, not via a direct `openai.OpenAI()` client. It supplies the vector embeddings that the `embedding` pipeline variant uses for passage retrieval.

| File:line | Call | Model | Imported by | Status |
|---|---|---|---|---|
| `enrichment/retrieval_schema.py:6` | `get_registry().get("openai").create(name=...)` (LanceDB adapter wraps `.embeddings.create`) | `text-embedding-3-small` | `enrichment/embed_passages.py`, `enrichment/experiment_ablation.py`, `enrichment/experiment_h14_cost.py` | **LIVE** (embedding-pipeline variant; Phase 0 contextual-passage embed) |

**Verdict on OpenAI usage:** the only live use of OpenAI is text-embedding-3-small via LanceDB, used by the `--pipeline embedding` variant to vector-index contextual passages. There are no OpenAI chat-completion calls anywhere — every text-generation call is Anthropic. `OPENAI_API_KEY` in `.env.example` exists solely to satisfy the LanceDB adapter.

## Anthropic

All call sites use `anthropic.Anthropic()` client and either `.messages.create`, `.messages.parse`, or `.beta.messages.count_tokens`.

### Core enrichment pipeline (LIVE, reached via `run_pipeline.py`)

| File:line | Call | Model | Role |
|---|---|---|---|
| `enrichment/submit_passages_enriched.py:144` | `.messages.batches.create` | `claude-haiku-4-5-20251001` | Phase 0: batch submit for chapter enrichment |
| `enrichment/collect_passages_enriched.py:75` | batch results retrieval | — | Phase 0: batch collect |
| `enrichment/retry_failed.py:50` | `.messages.create` | `claude-haiku-4-5-20251001` | Phase 0: retry failed batch items |
| `enrichment/design_segments.py:283` | `.messages.parse` | `claude-haiku-4-5-20251001` | Phase 1: LLM-driven segment structure |
| `enrichment/generate_podcast.py:558, 725` | `.messages.parse` | `claude-sonnet-4-6` | Phase 3: multi-voice script generation |
| `enrichment/embedding_podcast.py:554` | `.messages.parse` | `claude-sonnet-4-6` | Phase 3 (embedding variant): passage curation |

### Phase 2.5 (LIVE when `--host-prep` flag set)

| File:line | Call | Model | Role |
|---|---|---|---|
| `enrichment/host_prep.py:203` | `.messages.create` | `claude-haiku-4-5-20251001` | Pre-interview (agentic tool loop) |
| `enrichment/host_prep.py:245` | `.messages.parse` | `claude-haiku-4-5-20251001` | Structured pre-interview response |
| `enrichment/host_prep.py:398` | `.messages.parse` | `claude-sonnet-4-6` | Host brief / question plan |
| `enrichment/reference_tools.py:444` | `.messages.create` | `claude-haiku-4-5-20251001` | Reading-list winnowing (called from `host_prep`) |

### Context batch utilities (LIVE, reached from `run_pipeline.py`)

| File:line | Call | Model | Role |
|---|---|---|---|
| `enrichment/submit_passage_contexts.py` | batch submit | `claude-haiku-4-5-20251001` | Passage contextualisation |
| `enrichment/collect_passage_contexts.py` | batch collect | — | Passage contextualisation |

### Utilities and diagnostics

| File:line | Call | Model | Status |
|---|---|---|---|
| `enrichment/test_single.py:60` | `.messages.create` | `claude-haiku-4-5-20251001` | **SCRIPT** (single-passage sanity check before batch) |

## Gemini

| File:line | Call | Model | Status |
|---|---|---|---|
| `enrichment/render_audio.py:140` | `client.models.generate_content` | `gemini-2.5-flash-preview-tts` / `gemini-2.5-pro-preview-tts` | **LIVE** (Phase 4 TTS for the main pipeline) |
| `enrichment/tts_voices/classic.py:96` | delegates to `render_audio` | as above | **LIVE** |
| `enrichment/tts_voices/trevelyan_v2.py` | `generate_content` | `gemini-3.1-flash-tts-preview` | **LIVE** (alt voice set for trevelyan panel) |

Gemini's only role is TTS. No text-generation calls.

## Summary

| Provider | LIVE | SCRIPT | ORPHAN |
|---|---|---|---|
| Anthropic | ~12 call sites across 10 files (main pipeline, batch utilities, Phase 2.5) | 1 (`test_single.py`) | 0 |
| OpenAI | 1 (`retrieval_schema.py`, embeddings via LanceDB adapter, used by `embed_passages.py` + experiments) | 0 | 0 |
| Gemini | 3 files (all TTS) | 0 | 0 |

**Core literary pipeline = Anthropic end-to-end for text generation, Gemini for TTS.** OpenAI's sole role is supplying `text-embedding-3-small` to the LanceDB-backed embedding-pipeline variant. No OpenAI chat-completion calls exist anywhere in the tree.

## Implications for a Cerebras experiment

Cerebras offers an OpenAI-compatible chat API. No embedding models as of this writing.

1. **Drop-in targets (OpenAI-compatible):** none exist on the live path. The one OpenAI call site (`retrieval_schema.py`) is for embeddings, which Cerebras doesn't offer. There are no OpenAI chat-completion calls to swap.
2. **The interesting swap is Anthropic → Cerebras** in one of the Phase-0/Phase-3 call sites (`design_segments.py` or `generate_podcast.py`). That requires an adapter: Cerebras's API is chat-completions-shaped, but these modules use `.messages.parse(...)` with Pydantic schemas. Replacing it means JSON-mode + client-side validation, or using Cerebras's tool-calling as a structured-output proxy.
3. **Batch API:** Cerebras does not have an Anthropic-style batch API. `submit_passages_enriched.py` / `collect_passages_enriched.py` have no drop-in Cerebras equivalent; Cerebras calls would be synchronous.