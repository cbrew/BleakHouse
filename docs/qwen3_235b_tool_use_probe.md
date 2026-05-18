# Tool-use probe: Qwen/Qwen3-235B-A22B-Instruct-2507 on DeepInfra

Date: 2026-05-17. Bypasses the seam; calls the openai-compat endpoint directly.

**Overall: PASS — fit for host_prep pre-interview loop**

## Probe A — single tool
- tool calls emitted: 1
- finish_reason: tool_calls
- pass: **True**

Details:
- `search_wikipedia({"query": "Charles Dickens"})` → args valid: True (ok); called expected tool: True

## Probe B — multi-turn three-tool
- iterations: 4
- tool calls total: 3
- all argument JSONs valid against declared schemas: True
- produced non-empty final text: True (292 chars)
- pass: **True**

Transcript:
- iter 1: `search_wikipedia({"query": "Bleak House themes"})` → valid: True (ok)
- iter 2: `read_wikipedia_article({"ref_tag": "ref-2"})` → valid: True (ok)
- iter 3: `search_openalex({"query": "Bleak House social commentary"})` → valid: True (ok)

Final text preview:

> Bleak House by Charles Dickens offers profound social commentary, particularly critiquing the Court of Chancery and its impact on society. Scholarly analysis highlights its narrative structure and serialized form as key to its critique of 19th-century legal and social systems [ref-3][ref-4].

## Interpretation

Probe A measures whether the model can emit a single tool call with valid JSON arguments — the baseline for any tool-use capability.

Probe B measures whether the model can run a multi-turn loop: emit a call, consume the tool result, decide whether to call again, eventually stop and produce a final text response. This is the shape host_prep's pre_interview loop uses.

If both pass, qwen3-235b-a22b-instruct-2507 on DeepInfra is fit for the `host_prep_pre_interview` task (`enrichment/host_prep.py:203`, currently routed to Anthropic Haiku 4.5). The other three host_prep call sites (parse, brief, winnow) do not need tool use and have separate validation paths.

If either fails, the specific failure mode dictates the next step: argument-JSON malformedness suggests the model needs `strict=true` tool defs (not supported by all openai-compat backends); failure to stop suggests we'd need a hard turn cap in production; failure to produce final text suggests the model treats `tool_choice='auto'` as effectively forced.