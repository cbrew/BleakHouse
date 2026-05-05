# LLM call sites

Verified inventory of every place this repo calls an LLM, as of branch `experiment/cerebras-llm` (2026-04-22). Built to scope a possible Cerebras swap.

Status legend:
- **LIVE** — reachable from an active pipeline entry point (`enrichment/run_pipeline.py`, `enrichment/run_novel.py`, `enrichment/embedding_run.py`, `enrichment/plain_rag_run.py`, or `two_layer_app.py`).
- **SCRIPT** — top-level CLI, run directly (`uv run python -m ...`), not imported by anything.
- **ORPHAN** — not imported, not a documented CLI entry point; likely dead or experimental.
- **NOTEBOOK** — manual-run only.

No unified LLM wrapper exists. Each module instantiates its own client.

## OpenAI

Confirmed instantiation sites (exhaustive):

| File:line | Call | Model | Imported by | Status |
|---|---|---|---|---|
| `actions/ask_question.py:24` | `openai.OpenAI()` → `.chat.completions.create` | `gpt-4o-mini` | `two_layer_app.py` | **LIVE** (RAG tutorial app, secondary pipeline) |
| `enrichment/plain_rag_podcast.py:54` | `openai.OpenAI()` → `.embeddings.create` | `text-embedding-3-small` | `enrichment/plain_rag_run.py` | **LIVE** (plain-RAG baseline variant) |
| `enrichment/experiment_transport_costs.py:116` | `OpenAI()` → `.embeddings.create` | `text-embedding-3-small` | nothing | **SCRIPT** (one-off cost experiment) |
| `demotts.py:40` | `OpenAI()` → `.audio.speech.create` | `tts-1` voice `shimmer` | nothing | **SCRIPT** (demo TTS; not wired into Phase 4) |

**Verdict on OpenAI usage:** OpenAI is **not used anywhere in the core literary podcast pipeline** (`run_pipeline.py` → enrichment → Phase 2.5 → Phase 3 → TTS). Its two live uses are:
1. The RAG tutorial app (`two_layer_app.py` / `actions/ask_question.py`) — a separate, secondary pipeline per CLAUDE.md, there for pedagogical purposes.
2. A plain-RAG baseline (`plain_rag_run.py`) that uses OpenAI embeddings — this is a comparison variant, not the main run path.

The other two OpenAI files (`demotts.py`, `experiment_transport_costs.py`) are standalone experiments that nothing else depends on.

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
| `bleak_house/metrics.py:14` | `.beta.messages.count_tokens` | `claude-3-5-sonnet-20241022` | **ORPHAN** (Hamilton DAG node, not invoked by active drivers) |
| `enrichment/test_single.py:60` | `.messages.create` | `claude-haiku-4-5-20251001` | **SCRIPT** (single-passage sanity check before batch) |

## Gemini

| File:line | Call | Model | Status |
|---|---|---|---|
| `enrichment/render_audio.py:140` | `client.models.generate_content` | `gemini-2.5-flash-preview-tts` / `gemini-2.5-pro-preview-tts` | **LIVE** (Phase 4 TTS for the main pipeline) |
| `enrichment/tts_voices/classic.py:96` | delegates to `render_audio` | as above | **LIVE** |
| `enrichment/tts_voices/trevelyan_v2.py` | `generate_content` | `gemini-3.1-flash-tts-preview` | **LIVE** (alt voice set for trevelyan panel) |

Gemini's only role is TTS. No text-generation calls.

## Notebooks (NOTEBOOK)

- `BleakHouse.ipynb` — early Burr state machine prototype; instantiates `openai.OpenAI()` and `anthropic.Anthropic()` in exploration cells. Superseded by `enrichment/run_pipeline.py` for the literary workstream.
- `TwoLayer.ipynb` — RAG tutorial walkthrough (v1/v2/v3); instantiates `openai.OpenAI()` and `anthropic.Anthropic()` across cells. This notebook is the teaching counterpart to the `actions/` + `two_layer_app.py` RAG app.

Neither notebook is imported by runtime code.

## Summary

| Provider | LIVE | SCRIPT | ORPHAN |
|---|---|---|---|
| Anthropic | ~12 call sites across 10 files (main pipeline, batch utilities, Phase 2.5) | 1 (`test_single.py`) | 1 (`metrics.py`) |
| OpenAI | 2 files (`ask_question.py`, `plain_rag_podcast.py`) — both in peripheral pipelines | 2 (`demotts.py`, `experiment_transport_costs.py`) | 0 |
| Gemini | 3 files (all TTS) | 0 | 0 |

**Core literary pipeline = Anthropic end-to-end for text generation, Gemini for TTS.** OpenAI appears only in the RAG tutorial and in an OpenAI-embeddings-based baseline variant. No OpenAI call is on the critical path to a podcast episode.

## Implications for a Cerebras experiment

Cerebras offers an OpenAI-compatible chat API. No embedding models as of this writing.

1. **Drop-in targets (OpenAI-compatible):** very few exist and none are on the main path. `ask_question.py` and `plain_rag_podcast.py` are the only live OpenAI-chat call sites, and `plain_rag_podcast.py` uses embeddings (which Cerebras doesn't offer), leaving only `ask_question.py` as a trivial chat swap — but that's the RAG tutorial, not the pipeline we care about benchmarking.
2. **The interesting swap is Anthropic → Cerebras** in one of the Phase-0/Phase-3 call sites (`design_segments.py` or `generate_podcast.py`). That requires an adapter: Cerebras's API is chat-completions-shaped, but these modules use `.messages.parse(...)` with Pydantic schemas. Replacing it means JSON-mode + client-side validation, or using Cerebras's tool-calling as a structured-output proxy.
3. **Batch API:** Cerebras does not have an Anthropic-style batch API. `submit_passages_enriched.py` / `collect_passages_enriched.py` have no drop-in Cerebras equivalent; Cerebras calls would be synchronous.