"""Probe: does qwen-plus on DashScope (intl) support multi-turn tool
use well enough for the host_prep pre-interview loop?

Companion to scripts/probe_qwen3_235b_tool_use.py — same two probes,
same tool definitions, different provider. Tracks BleakHouse-el1j.2,
the host_prep validation gate for the all-DashScope pipeline epic
(BleakHouse-el1j). qwen-plus passage_enrichment is already proven
(el1j.1); tool-use is the next-most-complex shape to verify.

Bypasses the seam intentionally: a direct openai-SDK call is more
diagnostic for "does tool use work at all" than a seam-mediated one,
because seam adapters and our prompt scaffolding can mask provider-side
behaviour we want to see raw.

Two probes:
  A. Single-tool: one `search_wikipedia` definition, one prompt that
     should trigger one call. Check: tool_calls present, arguments
     parse as JSON, the JSON matches the input_schema.
  B. Multi-turn three-tool: the same three tools host_prep actually
     uses (search_openalex, search_wikipedia, read_wikipedia_article).
     Stub executors return plausible-shaped results. Loop until the
     model stops emitting calls or 6 iterations elapse (matches
     host_prep.MAX_TOOL_CALLS).

PASS criteria (both probes must satisfy):
  - HTTP 200 every iteration.
  - tool_calls list contains entries with valid JSON arguments
    matching the declared input_schema.
  - Multi-turn probe completes without infinite loop or schema-invalid
    final response.

USAGE:
    uv run python scripts/probe_qwen_plus_tool_use.py

Requires ALIBABA_API_KEY in .env. Writes a one-page summary to
docs/qwen_plus_tool_use_probe.md.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = REPO_ROOT / "docs" / "qwen_plus_tool_use_probe.md"

MODEL = "qwen-plus"
BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

# qwen-plus quirks established under BleakHouse-el1j.1:
#   enable_thinking=False suppresses <think>...</think> leak;
#   frequency_penalty=0.5 is anti-repetition belt-and-braces.
# Carried over here because they're now part of the canonical
# qwen-plus-on-DashScope call shape — see scripts/run_qwen_plus_realtime_chapter.py.
QWEN_PLUS_EXTRA = {
    "chat_template_kwargs": {"enable_thinking": False},
}
QWEN_PLUS_BODY_EXTRAS = {
    "frequency_penalty": 0.5,
}

# Tool definitions — same shape host_prep uses. The schema is the bit
# the model has to satisfy when emitting a call.
SEARCH_WIKIPEDIA = {
    "type": "function",
    "function": {
        "name": "search_wikipedia",
        "description": "Search English Wikipedia for articles matching a query. Returns up to 5 (title, snippet) tuples.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms."},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}
SEARCH_OPENALEX = {
    "type": "function",
    "function": {
        "name": "search_openalex",
        "description": "Search OpenAlex (scholarly works) for works matching a query. Returns up to 5 references with [ref-N] tags.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms."},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}
READ_WIKIPEDIA_ARTICLE = {
    "type": "function",
    "function": {
        "name": "read_wikipedia_article",
        "description": "Fetch the body of a Wikipedia article by its [ref-N] tag (issued in a previous search_wikipedia result).",
        "parameters": {
            "type": "object",
            "properties": {
                "ref_tag": {"type": "string", "description": "A tag like 'ref-3' from a prior search result."},
            },
            "required": ["ref_tag"],
            "additionalProperties": False,
        },
    },
}


def _stub_search_wikipedia(args: dict) -> str:
    return json.dumps([
        {"ref": "ref-1", "title": "Charles Dickens", "snippet": "English novelist (1812–1870)."},
        {"ref": "ref-2", "title": "Bleak House", "snippet": "1853 novel by Charles Dickens."},
    ])


def _stub_search_openalex(args: dict) -> str:
    return json.dumps([
        {"ref": "ref-3", "title": "Narrative voice in Bleak House", "authors": "Smith J", "year": 2019},
        {"ref": "ref-4", "title": "Dickens and serial publication", "authors": "Patel R", "year": 2021},
    ])


def _stub_read_wikipedia_article(args: dict) -> str:
    return (
        "Bleak House is a novel by Charles Dickens, first published as a serial "
        "between March 1852 and September 1853. It contains some of Dickens's most "
        "trenchant social commentary, centred on the Court of Chancery."
    )


STUBS = {
    "search_wikipedia": _stub_search_wikipedia,
    "search_openalex": _stub_search_openalex,
    "read_wikipedia_article": _stub_read_wikipedia_article,
}


def _validate_args_against_schema(args_str: str, schema: dict) -> tuple[bool, str]:
    """Return (ok, reason). Light validation — JSON-parseable + required keys present."""
    try:
        args = json.loads(args_str)
    except Exception as e:
        return False, f"not JSON: {e}"
    if not isinstance(args, dict):
        return False, f"not an object: {type(args).__name__}"
    required = schema.get("required", [])
    missing = [k for k in required if k not in args]
    if missing:
        return False, f"missing required keys: {missing}"
    return True, "ok"


def probe_a_single_tool(client: OpenAI) -> dict:
    """One tool, one prompt, expect one call with valid args."""
    print("\n=== Probe A: single tool ===", flush=True)
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You are a research assistant. Use the search_wikipedia tool when the user asks you to look something up."},
            {"role": "user", "content": "Look up Charles Dickens on Wikipedia."},
        ],
        tools=[SEARCH_WIKIPEDIA],
        tool_choice="auto",
        max_tokens=512,
        extra_body=QWEN_PLUS_EXTRA,
        **QWEN_PLUS_BODY_EXTRAS,
    )
    msg = resp.choices[0].message
    tcs = getattr(msg, "tool_calls", None) or []
    result = {
        "n_tool_calls": len(tcs),
        "finish_reason": resp.choices[0].finish_reason,
        "calls": [],
    }
    for tc in tcs:
        name = tc.function.name
        args_str = tc.function.arguments
        schema = SEARCH_WIKIPEDIA["function"]["parameters"]
        ok, reason = _validate_args_against_schema(args_str, schema)
        result["calls"].append({
            "name": name,
            "args_raw": args_str,
            "args_valid": ok,
            "args_validation_note": reason,
            "called_expected_tool": name == "search_wikipedia",
        })
    result["pass"] = (
        len(tcs) >= 1
        and all(c["args_valid"] and c["called_expected_tool"] for c in result["calls"])
    )
    print(f"  tool_calls={len(tcs)}, finish_reason={resp.choices[0].finish_reason}, pass={result['pass']}", flush=True)
    for c in result["calls"]:
        print(f"    {c['name']}({c['args_raw']}) → valid={c['args_valid']} ({c['args_validation_note']})", flush=True)
    return result


def probe_b_multi_turn(client: OpenAI, max_iter: int = 6) -> dict:
    """Three tools, multi-turn loop, expect 2-5 calls then a final text response."""
    print("\n=== Probe B: multi-turn three-tool ===", flush=True)
    tools = [SEARCH_WIKIPEDIA, SEARCH_OPENALEX, READ_WIKIPEDIA_ARTICLE]
    schemas_by_name = {t["function"]["name"]: t["function"]["parameters"] for t in tools}
    messages = [
        {"role": "system", "content": (
            "You are a scholarly research assistant preparing background for a podcast on "
            "Charles Dickens's Bleak House. You have three tools: search_wikipedia, "
            "search_openalex, read_wikipedia_article. Use them to gather context, then "
            "produce a 2-3 sentence summary of what you found. Each tool result prefixes "
            "candidates with [ref-N] tags. Use 2-4 tool calls total, then stop."
        )},
        {"role": "user", "content": "Research the social-commentary themes in Bleak House. Surface 2-3 scholarly references."},
    ]
    transcript = []
    final_text = None
    iteration = 0
    for iteration in range(1, max_iter + 1):
        print(f"  iter {iteration}: calling model...", flush=True)
        resp = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            max_tokens=1024,
            extra_body=QWEN_PLUS_EXTRA,
            **QWEN_PLUS_BODY_EXTRAS,
        )
        msg = resp.choices[0].message
        finish = resp.choices[0].finish_reason
        tcs = getattr(msg, "tool_calls", None) or []
        if not tcs:
            final_text = msg.content or ""
            print(f"  iter {iteration}: no more tool calls; finish={finish}; final text {len(final_text)} chars", flush=True)
            break

        # record assistant tool-call message
        assistant_msg = {"role": "assistant", "content": msg.content or ""}
        assistant_msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in tcs
        ]
        messages.append(assistant_msg)

        for tc in tcs:
            name = tc.function.name
            args_str = tc.function.arguments
            schema = schemas_by_name.get(name, {})
            ok, reason = _validate_args_against_schema(args_str, schema)
            transcript.append({
                "iter": iteration, "name": name, "args_raw": args_str,
                "args_valid": ok, "args_validation_note": reason,
            })
            print(f"    {name}({args_str}) → valid={ok} ({reason})", flush=True)
            stub = STUBS.get(name)
            if not stub:
                tool_output = f'{{"error": "unknown tool {name!r}"}}'
            else:
                try:
                    args = json.loads(args_str) if ok else {}
                except Exception:
                    args = {}
                tool_output = stub(args)
            messages.append({
                "role": "tool", "tool_call_id": tc.id,
                "name": name, "content": tool_output,
            })

    result = {
        "iterations": iteration,
        "n_tool_calls": len(transcript),
        "all_args_valid": all(t["args_valid"] for t in transcript) if transcript else False,
        "produced_final_text": bool(final_text and final_text.strip()),
        "final_text_chars": len(final_text or ""),
        "final_text_preview": (final_text or "")[:300],
        "transcript": transcript,
    }
    result["pass"] = (
        result["n_tool_calls"] >= 2
        and result["all_args_valid"]
        and result["produced_final_text"]
        and result["iterations"] < max_iter   # stopped on its own, not on cap
    )
    print(f"  → iterations={result['iterations']}, calls={result['n_tool_calls']}, "
          f"all_args_valid={result['all_args_valid']}, produced_text={result['produced_final_text']}, "
          f"pass={result['pass']}", flush=True)
    return result


def _write_report(probe_a: dict, probe_b: dict) -> None:
    overall_pass = probe_a["pass"] and probe_b["pass"]
    lines = [
        f"# Tool-use probe: {MODEL} on DashScope (intl)",
        "",
        f"Date: 2026-05-20. Bypasses the seam; calls the DashScope openai-compat endpoint directly. "
        f"Body extras: chat_template_kwargs={{'enable_thinking': False}}, frequency_penalty=0.5 "
        f"(per the canonical qwen-plus call shape established under BleakHouse-el1j.1).",
        f"",
        f"**Overall: {'PASS — fit for host_prep pre-interview loop' if overall_pass else 'FAIL — not fit; details below'}**",
        "",
        "## Probe A — single tool",
        f"- tool calls emitted: {probe_a['n_tool_calls']}",
        f"- finish_reason: {probe_a['finish_reason']}",
        f"- pass: **{probe_a['pass']}**",
        "",
        "Details:",
    ]
    for c in probe_a["calls"]:
        lines.append(f"- `{c['name']}({c['args_raw']})` → args valid: {c['args_valid']} ({c['args_validation_note']}); called expected tool: {c['called_expected_tool']}")
    lines += [
        "",
        "## Probe B — multi-turn three-tool",
        f"- iterations: {probe_b['iterations']}",
        f"- tool calls total: {probe_b['n_tool_calls']}",
        f"- all argument JSONs valid against declared schemas: {probe_b['all_args_valid']}",
        f"- produced non-empty final text: {probe_b['produced_final_text']} ({probe_b['final_text_chars']} chars)",
        f"- pass: **{probe_b['pass']}**",
        "",
        "Transcript:",
    ]
    for t in probe_b["transcript"]:
        lines.append(f"- iter {t['iter']}: `{t['name']}({t['args_raw']})` → valid: {t['args_valid']} ({t['args_validation_note']})")
    if probe_b.get("final_text_preview"):
        lines += ["", "Final text preview:", "", "> " + probe_b["final_text_preview"].replace("\n", " ")]
    lines += [
        "",
        "## Interpretation",
        "",
        "Probe A measures whether the model can emit a single tool call with valid JSON arguments — the baseline for any tool-use capability.",
        "",
        "Probe B measures whether the model can run a multi-turn loop: emit a call, consume the tool result, decide whether to call again, eventually stop and produce a final text response. This is the shape host_prep's pre_interview loop uses.",
        "",
        "If both pass, qwen-plus on DashScope is fit for the `host_prep_pre_interview` task (`enrichment/host_prep.py:203`, currently routed to Anthropic Haiku 4.5). The other three host_prep call sites (parse, brief, winnow) do not need tool use and have separate validation paths under BleakHouse-el1j.2.",
        "",
        "If either fails, the specific failure mode dictates the next step: argument-JSON malformedness suggests the model needs `strict=true` tool defs (not supported by all openai-compat backends); failure to stop suggests we'd need a hard turn cap in production; failure to produce final text suggests the model treats `tool_choice='auto'` as effectively forced.",
    ]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines))
    print(f"\nReport written → {REPORT_PATH.relative_to(REPO_ROOT)}", flush=True)


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    api_key = os.environ.get("ALIBABA_API_KEY")
    if not api_key:
        print("ERROR: ALIBABA_API_KEY not set (checked .env and shell env).", file=sys.stderr)
        return 2
    client = OpenAI(api_key=api_key, base_url=BASE_URL)
    probe_a = probe_a_single_tool(client)
    probe_b = probe_b_multi_turn(client)
    _write_report(probe_a, probe_b)
    overall_pass = probe_a["pass"] and probe_b["pass"]
    print(f"\n=== Overall: {'PASS' if overall_pass else 'FAIL'} ===")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
