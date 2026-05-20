# Tool-use probe: qwen-plus on DashScope (intl)

Date: 2026-05-20. Bypasses the seam; calls the DashScope openai-compat endpoint directly. Body extras: chat_template_kwargs={'enable_thinking': False}, frequency_penalty=0.5 (per the canonical qwen-plus call shape established under BleakHouse-el1j.1).

**Overall: PASS — fit for host_prep pre-interview loop**

## Probe A — single tool
- tool calls emitted: 1
- finish_reason: tool_calls
- pass: **True**

Details:
- `search_wikipedia({"query": "Charles Dickens"})` → args valid: True (ok); called expected tool: True

## Probe B — multi-turn three-tool
- iterations: 3
- tool calls total: 3
- all argument JSONs valid against declared schemas: True
- produced non-empty final text: True (483 chars)
- pass: **True**

Transcript:
- iter 1: `search_wikipedia({"query": "Bleak House social commentary"})` → valid: True (ok)
- iter 1: `search_openalex({"query": "Bleak House social commentary"})` → valid: True (ok)
- iter 2: `read_wikipedia_article({"ref_tag": "ref-2"})` → valid: True (ok)

Final text preview:

> Bleak House offers incisive social commentary, especially targeting the inefficiency and inhumanity of the Court of Chancery—a critique rooted in Dickens’s own experience as a law clerk and amplified by real-life cases like *Jennens v Jennens*. Scholarly work such as Smith (2019) analyzes how the no

## Interpretation

Probe A measures whether the model can emit a single tool call with valid JSON arguments — the baseline for any tool-use capability.

Probe B measures whether the model can run a multi-turn loop: emit a call, consume the tool result, decide whether to call again, eventually stop and produce a final text response. This is the shape host_prep's pre_interview loop uses.

If both pass, qwen-plus on DashScope is fit for the `host_prep_pre_interview` task (`enrichment/host_prep.py:203`, currently routed to Anthropic Haiku 4.5). The other three host_prep call sites (parse, brief, winnow) do not need tool use and have separate validation paths under BleakHouse-el1j.2.

If either fails, the specific failure mode dictates the next step: argument-JSON malformedness suggests the model needs `strict=true` tool defs (not supported by all openai-compat backends); failure to stop suggests we'd need a hard turn cap in production; failure to produce final text suggests the model treats `tool_choice='auto'` as effectively forced.