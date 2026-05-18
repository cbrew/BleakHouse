"""Probe: does Instructor work against DeepInfra via custom openai base_url?

Resolves open question 2 from docs/instructor_evaluation.md and the
BleakHouse-fupq ticket. Scope is SINGLE-SHOT structured output only —
the tool-use probe is BleakHouse-305o.

Probes:
  A. Trivial schema, Mode.JSON_SCHEMA: does the basic wrapper work?
  B. Trivial schema, Mode.TOOLS: does tool-mode structured output work?
  C. Our actual HostQuestion model (with min_length / max_length /
     extra='forbid'): does Instructor honour the Pydantic constraints
     and use the right mode for DeepInfra?
  D. Same as A but routing via OpenRouter — fallback comparison.

For each probe we record: which mode Instructor picked, whether it
succeeded, raw token counts where accessible, any quirks observed.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
FINDINGS = REPO_ROOT / "docs" / "instructor_probe_findings.md"

DEEPINFRA_BASE = "https://api.deepinfra.com/v1/openai"
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
QWEN_MODEL_DEEPINFRA = "Qwen/Qwen3-235B-A22B-Instruct-2507"
QWEN_MODEL_OPENROUTER = "qwen/qwen3-235b-a22b-2507"


def _build_clients():
    import instructor
    import openai

    di_key = os.environ.get("DEEPINFRA_API_KEY")
    or_key = os.environ.get("OPENROUTER_API_KEY")
    if not di_key:
        print("WARNING: DEEPINFRA_API_KEY not set", file=sys.stderr)
    if not or_key:
        print("WARNING: OPENROUTER_API_KEY not set (OpenRouter probe will be skipped)", file=sys.stderr)

    di_raw = openai.OpenAI(api_key=di_key, base_url=DEEPINFRA_BASE) if di_key else None
    or_raw = openai.OpenAI(api_key=or_key, base_url=OPENROUTER_BASE) if or_key else None
    return di_raw, or_raw, instructor


def _record(probe_name: str, result: dict) -> None:
    print(f"\n=== {probe_name} ===")
    for k, v in result.items():
        if k == "exception":
            print(f"  {k}: {type(v).__name__}: {v}")
        else:
            print(f"  {k}: {v}")


def probe_a_trivial_json_schema(di_raw, instructor_mod) -> dict:
    """Trivial schema, Mode.JSON_SCHEMA on DeepInfra."""
    from pydantic import BaseModel, Field

    class Person(BaseModel):
        name: str = Field(description="Person's name")
        age: int = Field(description="Person's age in years")

    result = {"probe": "A trivial JSON_SCHEMA on DeepInfra", "mode": "JSON_SCHEMA"}
    try:
        client = instructor_mod.from_openai(di_raw, mode=instructor_mod.Mode.JSON_SCHEMA)
        person, completion = client.chat.completions.create_with_completion(
            model=QWEN_MODEL_DEEPINFRA,
            response_model=Person,
            messages=[{"role": "user", "content": "John is 30 years old. Give me his info."}],
            max_tokens=200,
        )
        result["success"] = True
        result["parsed"] = person.model_dump()
        u = getattr(completion, "usage", None)
        if u:
            result["input_tokens"] = u.prompt_tokens
            result["output_tokens"] = u.completion_tokens
    except Exception as e:
        result["success"] = False
        result["exception"] = e
    return result


def probe_b_trivial_tools(di_raw, instructor_mod) -> dict:
    """Trivial schema, Mode.TOOLS on DeepInfra."""
    from pydantic import BaseModel, Field

    class Person(BaseModel):
        name: str = Field(description="Person's name")
        age: int = Field(description="Person's age in years")

    result = {"probe": "B trivial TOOLS on DeepInfra", "mode": "TOOLS"}
    try:
        client = instructor_mod.from_openai(di_raw, mode=instructor_mod.Mode.TOOLS)
        person, completion = client.chat.completions.create_with_completion(
            model=QWEN_MODEL_DEEPINFRA,
            response_model=Person,
            messages=[{"role": "user", "content": "John is 30 years old. Give me his info."}],
            max_tokens=200,
        )
        result["success"] = True
        result["parsed"] = person.model_dump()
        u = getattr(completion, "usage", None)
        if u:
            result["input_tokens"] = u.prompt_tokens
            result["output_tokens"] = u.completion_tokens
    except Exception as e:
        result["success"] = False
        result["exception"] = e
    return result


def probe_c_our_hostquestion(di_raw, instructor_mod) -> dict:
    """Real BleakHouse Pydantic model — HostQuestion with min/max + extra='forbid'."""
    from enrichment.podcast_types import HostQuestion

    result = {
        "probe": "C HostQuestion (production model) on DeepInfra",
        "mode": "JSON_SCHEMA (fallback to TOOLS if first fails)",
    }
    for mode_name in ("JSON_SCHEMA", "TOOLS"):
        result["attempted_mode"] = mode_name
        try:
            client = instructor_mod.from_openai(
                di_raw, mode=getattr(instructor_mod.Mode, mode_name),
            )
            q, completion = client.chat.completions.create_with_completion(
                model=QWEN_MODEL_DEEPINFRA,
                response_model=HostQuestion,
                messages=[{
                    "role": "user",
                    "content": (
                        "Generate one podcast question. Target expert is 'Edmund Leigh', "
                        "the question should be about Gaskell's Margaret Hale, intent is "
                        "to draw out a close-reading observation, follow_up_for should "
                        "list one or two other experts who might want to add."
                    ),
                }],
                max_tokens=400,
            )
            result["success"] = True
            result["parsed"] = q.model_dump()
            u = getattr(completion, "usage", None)
            if u:
                result["input_tokens"] = u.prompt_tokens
                result["output_tokens"] = u.completion_tokens
            return result
        except Exception as e:
            result.setdefault("exceptions_by_mode", {})[mode_name] = f"{type(e).__name__}: {e}"
    result["success"] = False
    return result


def probe_d_openrouter(or_raw, instructor_mod) -> dict:
    """Same trivial schema via OpenRouter route to qwen3-235b-a22b-2507."""
    from pydantic import BaseModel, Field

    class Person(BaseModel):
        name: str = Field(description="Person's name")
        age: int = Field(description="Person's age in years")

    result = {"probe": "D trivial via OpenRouter→Qwen", "mode": "JSON_SCHEMA"}
    if or_raw is None:
        result["skipped"] = "OPENROUTER_API_KEY not set"
        return result
    try:
        client = instructor_mod.from_openai(or_raw, mode=instructor_mod.Mode.JSON_SCHEMA)
        person, completion = client.chat.completions.create_with_completion(
            model=QWEN_MODEL_OPENROUTER,
            response_model=Person,
            messages=[{"role": "user", "content": "John is 30 years old. Give me his info."}],
            max_tokens=200,
        )
        result["success"] = True
        result["parsed"] = person.model_dump()
        u = getattr(completion, "usage", None)
        if u:
            result["input_tokens"] = u.prompt_tokens
            result["output_tokens"] = u.completion_tokens
    except Exception as e:
        result["success"] = False
        result["exception"] = e
    return result


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    di_raw, or_raw, instructor_mod = _build_clients()

    results: list[dict] = []

    if di_raw is not None:
        results.append(probe_a_trivial_json_schema(di_raw, instructor_mod))
        _record("A", results[-1])
        results.append(probe_b_trivial_tools(di_raw, instructor_mod))
        _record("B", results[-1])
        results.append(probe_c_our_hostquestion(di_raw, instructor_mod))
        _record("C", results[-1])

    results.append(probe_d_openrouter(or_raw, instructor_mod))
    _record("D", results[-1])

    # Print summary
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for r in results:
        ok = "PASS" if r.get("success") else ("SKIP" if r.get("skipped") else "FAIL")
        print(f"  [{ok}] {r['probe']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
