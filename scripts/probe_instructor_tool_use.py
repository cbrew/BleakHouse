"""Probe: can Instructor handle multi-turn tool-use loops?

Resolves open question 1 from docs/instructor_evaluation.md and the
BleakHouse-305o ticket. Specifically: does the library's API support
driving a multi-turn loop (model emits tool_call → we execute → feed
back tool_result → model decides whether to call again), and can the
final response be parsed into a Pydantic model?

The host_prep pre-interview loop is the only multi-turn tool-use site
in BleakHouse. It uses 3 tools (search_openalex, search_wikipedia,
read_wikipedia_article) and runs up to MAX_TOOL_CALLS=6 iterations.

Test design:
  A. Anthropic native (claude-haiku-4-5): the production path the
     seam runs today. Replicate that shape via Instructor and observe.
  B. Qwen3-235B-A22B-Instruct-2507 on DeepInfra: the open-weight path.
     Should behave same as A if Instructor is consistent.

Approach (informed by surface inspection: Instructor exposes
`create`/`create_with_completion` only — no `tool_use_loop`):
  1. Wrap the provider client with instructor.from_anthropic /
     instructor.from_openai.
  2. Drive the loop manually using client.chat.completions.create
     (or the Anthropic equivalent) with raw `tools=[...]` and NO
     response_model. Check whether tool_calls come back intact.
  3. When the model stops emitting tool_calls, do a FINAL call with
     response_model=PreInterviewResponse (or trivial test model) to
     parse the loop's accumulated text into a Pydantic instance.

If step (2) works (the wrapped client passes raw tool_calls through
without trying to coerce to response_model), we have our answer:
hybrid is viable — keep manual loop driving, use Instructor for the
final structured parse step.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent

DEEPINFRA_BASE = "https://api.deepinfra.com/v1/openai"
QWEN_MODEL_DEEPINFRA = "Qwen/Qwen3-235B-A22B-Instruct-2507"
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"


# Three tools modelled on host_prep's catalogue.
SEARCH_WIKIPEDIA = {
    "type": "function",
    "function": {
        "name": "search_wikipedia",
        "description": "Search English Wikipedia for articles matching a query. Returns up to 5 (title, snippet) tuples tagged with [ref-N].",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
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
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}
READ_WIKIPEDIA_ARTICLE = {
    "type": "function",
    "function": {
        "name": "read_wikipedia_article",
        "description": "Fetch the body of a Wikipedia article by its [ref-N] tag.",
        "parameters": {
            "type": "object",
            "properties": {"ref_tag": {"type": "string"}},
            "required": ["ref_tag"],
            "additionalProperties": False,
        },
    },
}
OPENAI_TOOLS = [SEARCH_WIKIPEDIA, SEARCH_OPENALEX, READ_WIKIPEDIA_ARTICLE]

# Anthropic tool format is similar but uses input_schema, not parameters.
ANTHROPIC_TOOLS = [
    {
        "name": t["function"]["name"],
        "description": t["function"]["description"],
        "input_schema": t["function"]["parameters"],
    }
    for t in OPENAI_TOOLS
]


def _stub_executor(name: str, args: dict) -> str:
    if name == "search_wikipedia":
        return json.dumps([
            {"ref": "ref-1", "title": "Charles Dickens", "snippet": "English novelist (1812-1870)."},
            {"ref": "ref-2", "title": "Bleak House", "snippet": "1853 serialised novel."},
        ])
    if name == "search_openalex":
        return json.dumps([
            {"ref": "ref-3", "title": "Narrative voice in Bleak House", "authors": "Smith J"},
            {"ref": "ref-4", "title": "Dickens and serial publication", "authors": "Patel R"},
        ])
    if name == "read_wikipedia_article":
        return "Bleak House is a novel by Charles Dickens, first serialised 1852-1853. It contains Dickens's most pointed social commentary, especially on the Court of Chancery."
    return f'{{"error":"unknown tool {name!r}"}}'


# Small Pydantic model for the FINAL parse step (mimics the host_prep
# PreInterviewResponse shape but trimmed for probe simplicity).
class ResearchSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(description="The topic researched")
    key_findings: list[str] = Field(
        min_length=1, max_length=4,
        description="2-4 main findings from the research",
    )
    tags_used: list[str] = Field(
        min_length=0, max_length=10,
        description="[ref-N] tags drawn from the tool conversation",
    )


# ────────────────────────────────────────────────────────────────────
# Probe A — Anthropic native via Instructor
# ────────────────────────────────────────────────────────────────────

def probe_a_anthropic(max_iter: int = 5) -> dict:
    """Drive a 3-tool loop against Anthropic, then parse with Instructor."""
    import instructor
    import anthropic

    result: dict = {"probe": "A Anthropic claude-haiku-4-5 multi-turn loop"}
    if not os.environ.get("ANTHROPIC_API_KEY"):
        result["skipped"] = "ANTHROPIC_API_KEY not set"
        return result

    raw = anthropic.Anthropic()
    client = instructor.from_anthropic(raw, mode=instructor.Mode.ANTHROPIC_TOOLS)

    system = (
        "You are a research assistant. Use the three tools to gather "
        "1-3 pieces of context about Bleak House, then summarize. "
        "Use 1-3 tool calls total, then stop."
    )
    messages = [{"role": "user", "content": "Research the social-commentary themes in Bleak House."}]
    transcript: list[dict] = []
    final_text = ""

    # Step 1: drive the loop on the RAW anthropic client (Instructor
    # patches `client.chat.completions.create` for openai, not
    # `client.messages.create` for anthropic — but we can still call
    # the wrapped client directly for non-structured calls).
    try:
        for i in range(1, max_iter + 1):
            resp = raw.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=1024,
                system=system,
                tools=ANTHROPIC_TOOLS,
                messages=messages,
            )
            stop_reason = resp.stop_reason
            blocks = list(resp.content or [])
            tool_uses = [b for b in blocks if getattr(b, "type", None) == "tool_use"]
            text_blocks = [b for b in blocks if getattr(b, "type", None) == "text"]
            assistant_text = "".join(getattr(b, "text", "") for b in text_blocks)

            if not tool_uses:
                final_text = assistant_text
                transcript.append({"iter": i, "stop_reason": stop_reason, "tool_uses": 0, "text_chars": len(assistant_text)})
                break

            # Record the assistant turn
            messages.append({"role": "assistant", "content": [b.model_dump() if hasattr(b, "model_dump") else b for b in blocks]})

            tool_results = []
            for tu in tool_uses:
                output = _stub_executor(tu.name, dict(tu.input))
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": output,
                })
                transcript.append({"iter": i, "tool": tu.name, "args": dict(tu.input)})
            messages.append({"role": "user", "content": tool_results})
        else:
            result["loop_status"] = f"hit max_iter={max_iter} cap"

        # Step 2: parse final_text into a Pydantic model via Instructor
        # (the wrapped client's create method).
        if final_text:
            summary = client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=512,
                response_model=ResearchSummary,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Extract a ResearchSummary from this analyst's research notes:\n\n"
                        f"{final_text}"
                    ),
                }],
            )
            result["loop_iterations"] = transcript[-1]["iter"] if transcript else 0
            result["tool_calls_in_loop"] = len([t for t in transcript if "tool" in t])
            result["final_text_chars"] = len(final_text)
            result["parsed"] = summary.model_dump()
            result["success"] = True
        else:
            result["success"] = False
            result["reason"] = "no final text produced before iter cap"
    except Exception as e:
        result["success"] = False
        result["exception"] = f"{type(e).__name__}: {e}"
    return result


# ────────────────────────────────────────────────────────────────────
# Probe B — Qwen via DeepInfra via Instructor
# ────────────────────────────────────────────────────────────────────

def probe_b_qwen_deepinfra(max_iter: int = 5) -> dict:
    """Drive a 3-tool loop against Qwen-on-DeepInfra, then parse with Instructor."""
    import instructor
    import openai

    result: dict = {"probe": "B Qwen3-235B on DeepInfra multi-turn loop"}
    if not os.environ.get("DEEPINFRA_API_KEY"):
        result["skipped"] = "DEEPINFRA_API_KEY not set"
        return result

    raw = openai.OpenAI(
        api_key=os.environ["DEEPINFRA_API_KEY"],
        base_url=DEEPINFRA_BASE,
    )
    client = instructor.from_openai(raw, mode=instructor.Mode.JSON_SCHEMA)

    messages = [
        {"role": "system", "content": (
            "You are a research assistant. Use the three tools to gather "
            "1-3 pieces of context about Bleak House, then write a 2-3 "
            "sentence summary. Use 1-3 tool calls total, then stop."
        )},
        {"role": "user", "content": "Research the social-commentary themes in Bleak House."},
    ]
    transcript: list[dict] = []
    final_text = ""

    try:
        for i in range(1, max_iter + 1):
            resp = raw.chat.completions.create(
                model=QWEN_MODEL_DEEPINFRA,
                messages=messages,
                tools=OPENAI_TOOLS,
                tool_choice="auto",
                max_tokens=1024,
            )
            msg = resp.choices[0].message
            tcs = getattr(msg, "tool_calls", None) or []

            if not tcs:
                final_text = msg.content or ""
                transcript.append({"iter": i, "finish_reason": resp.choices[0].finish_reason, "tool_calls": 0, "text_chars": len(final_text)})
                break

            assistant_msg = {"role": "assistant", "content": msg.content or ""}
            assistant_msg["tool_calls"] = [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in tcs
            ]
            messages.append(assistant_msg)

            for tc in tcs:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                output = _stub_executor(tc.function.name, args)
                messages.append({
                    "role": "tool", "tool_call_id": tc.id,
                    "name": tc.function.name, "content": output,
                })
                transcript.append({"iter": i, "tool": tc.function.name, "args": args})
        else:
            result["loop_status"] = f"hit max_iter={max_iter} cap"

        # Step 2: final parse via Instructor (wrapped client).
        if final_text:
            summary = client.chat.completions.create(
                model=QWEN_MODEL_DEEPINFRA,
                response_model=ResearchSummary,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Extract a ResearchSummary from this analyst's research notes:\n\n"
                        f"{final_text}"
                    ),
                }],
                max_tokens=512,
            )
            result["loop_iterations"] = transcript[-1]["iter"] if transcript else 0
            result["tool_calls_in_loop"] = len([t for t in transcript if "tool" in t])
            result["final_text_chars"] = len(final_text)
            result["parsed"] = summary.model_dump()
            result["success"] = True
        else:
            result["success"] = False
            result["reason"] = "no final text produced before iter cap"
    except Exception as e:
        result["success"] = False
        result["exception"] = f"{type(e).__name__}: {e}"
    return result


def _print(r: dict) -> None:
    print()
    print(f"=== {r['probe']} ===")
    for k, v in r.items():
        if k == "probe": continue
        if isinstance(v, dict):
            print(f"  {k}:")
            for kk, vv in v.items():
                print(f"    {kk}: {vv}")
        else:
            print(f"  {k}: {v}")


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    a = probe_a_anthropic()
    _print(a)
    b = probe_b_qwen_deepinfra()
    _print(b)

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for r in (a, b):
        if r.get("skipped"):
            print(f"  [SKIP] {r['probe']} — {r['skipped']}")
        elif r.get("success"):
            print(f"  [PASS] {r['probe']} — {r.get('tool_calls_in_loop',0)} tool calls, parsed final OK")
        else:
            print(f"  [FAIL] {r['probe']} — {r.get('exception', r.get('reason', 'unknown'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
