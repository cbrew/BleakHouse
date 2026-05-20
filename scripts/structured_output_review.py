"""Evidence-based review of structured-output capabilities.

For each (model × schema-feature) pair, fires a tiny isolated probe
that distinguishes:
    - whether the API accepts the schema at all (HTTP 200 vs 4xx/5xx)
    - whether the model's output is parseable JSON
    - whether the output is schema-compliant (independent jsonschema
      validation, separate from the model's own claim)
    - tokens / latency / cache info from the response

Caches per-cell results to data/eval/structured_output_review/<cell>.json
so the script is resumable. Generates docs/structured_output_review.html
from the cached results.

Run:
    uv run python scripts/structured_output_review.py
    uv run python scripts/structured_output_review.py --render-only  # rebuild HTML from cache

Provider docs (consulted 2026-05-13) are incomplete on schema feature
support:
  - Anthropic: documents a supported subset; create() rejects unsupported
    keys outright. parse() auto-strips and folds into descriptions.
  - OpenAI: documents that "much of JSON Schema is supported" but
    doesn't enumerate. Strict=true is decoder-enforced; strict=false
    is descriptive.
  - DeepInfra: example shows basic shape; no feature enumeration.
  - DeepSeek first-party: only json_object mode, NO schema. We hit
    via DeepInfra which provides schema layer atop vLLM.
This script fills in the gap empirically.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv

DATA = REPO_ROOT / "data" / "eval" / "structured_output_review"
DATA.mkdir(parents=True, exist_ok=True)
HTML_OUT = REPO_ROOT / "docs" / "structured_output_review.html"

DEEPINFRA_BASE = "https://api.deepinfra.com/v1/openai"
TOGETHER_BASE = "https://api.together.xyz/v1"


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TestCase:
    test_id: str
    group: str
    label: str
    description: str          # human-readable: what this probes
    schema: dict[str, Any]    # JSON Schema sent to the provider
    user_prompt: str          # user message — designed to invite a violation
    # specific_check returns (compliant: bool, note: str). compliant=True
    # means the model's output satisfied the *intent* of the test
    # (e.g. for maxItems=2, the list has ≤2 items in the parsed output).
    specific_check: Callable[[dict[str, Any]], tuple[bool, str]]
    # For some tests we want both strict modes (openai-compatible only).
    test_strict_modes: bool = False


def _check_present(key: str, expected_type: type) -> Callable[[dict], tuple[bool, str]]:
    def chk(obj: dict[str, Any]) -> tuple[bool, str]:
        if key not in obj:
            return False, f"missing key '{key}'"
        if not isinstance(obj[key], expected_type):
            return False, f"key '{key}' wrong type: {type(obj[key]).__name__}"
        return True, ""
    return chk


def _check_list_max(key: str, max_n: int) -> Callable[[dict], tuple[bool, str]]:
    def chk(obj: dict[str, Any]) -> tuple[bool, str]:
        v = obj.get(key)
        if not isinstance(v, list):
            return False, f"'{key}' is {type(v).__name__}, not list"
        if len(v) > max_n:
            return False, f"'{key}' has {len(v)} items, expected ≤ {max_n}"
        return True, f"{len(v)} ≤ {max_n}"
    return chk


def _check_list_min(key: str, min_n: int) -> Callable[[dict], tuple[bool, str]]:
    def chk(obj: dict[str, Any]) -> tuple[bool, str]:
        v = obj.get(key)
        if not isinstance(v, list):
            return False, f"'{key}' is {type(v).__name__}, not list"
        if len(v) < min_n:
            return False, f"'{key}' has {len(v)} items, expected ≥ {min_n}"
        return True, f"{len(v)} ≥ {min_n}"
    return chk


def _check_list_unique(key: str) -> Callable[[dict], tuple[bool, str]]:
    def chk(obj: dict[str, Any]) -> tuple[bool, str]:
        v = obj.get(key)
        if not isinstance(v, list):
            return False, f"'{key}' is not a list"
        if len(set(v)) != len(v):
            dupes = [x for x in v if v.count(x) > 1]
            return False, f"duplicates present: {dupes[:3]}"
        return True, f"all {len(v)} unique"
    return chk


def _check_string_len(key: str, max_len: int) -> Callable[[dict], tuple[bool, str]]:
    def chk(obj: dict[str, Any]) -> tuple[bool, str]:
        v = obj.get(key)
        if not isinstance(v, str):
            return False, f"'{key}' is not a string"
        if len(v) > max_len:
            return False, f"length {len(v)} > {max_len}"
        return True, f"len {len(v)} ≤ {max_len}"
    return chk


def _check_string_min_len(key: str, min_len: int) -> Callable[[dict], tuple[bool, str]]:
    def chk(obj: dict[str, Any]) -> tuple[bool, str]:
        v = obj.get(key)
        if not isinstance(v, str):
            return False, f"'{key}' is not a string"
        if len(v) < min_len:
            return False, f"length {len(v)} < {min_len}"
        return True, f"len {len(v)} ≥ {min_len}"
    return chk


def _check_pattern(key: str, regex: str) -> Callable[[dict], tuple[bool, str]]:
    import re
    pat = re.compile(regex)
    def chk(obj: dict[str, Any]) -> tuple[bool, str]:
        v = obj.get(key)
        if not isinstance(v, str):
            return False, f"'{key}' is not a string"
        if pat.fullmatch(v) is None:
            return False, f"'{v[:30]}' does not match /{regex}/"
        return True, f"matches /{regex}/"
    return chk


def _check_int_range(key: str, lo: int, hi: int) -> Callable[[dict], tuple[bool, str]]:
    def chk(obj: dict[str, Any]) -> tuple[bool, str]:
        v = obj.get(key)
        if not isinstance(v, int):
            return False, f"'{key}' is not an int"
        if v < lo or v > hi:
            return False, f"value {v} outside [{lo},{hi}]"
        return True, f"{v} ∈ [{lo},{hi}]"
    return chk


def _check_enum(key: str, allowed: list[str]) -> Callable[[dict], tuple[bool, str]]:
    def chk(obj: dict[str, Any]) -> tuple[bool, str]:
        v = obj.get(key)
        if v not in allowed:
            return False, f"value {v!r} not in {allowed}"
        return True, f"value {v!r} ∈ enum"
    return chk


def _check_const(key: str, const_value: Any) -> Callable[[dict], tuple[bool, str]]:
    def chk(obj: dict[str, Any]) -> tuple[bool, str]:
        v = obj.get(key)
        if v != const_value:
            return False, f"value {v!r} != const {const_value!r}"
        return True, f"value == const"
    return chk


def _check_date(key: str) -> Callable[[dict], tuple[bool, str]]:
    import re
    iso = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    def chk(obj: dict[str, Any]) -> tuple[bool, str]:
        v = obj.get(key)
        if not isinstance(v, str):
            return False, f"'{key}' is not a string"
        if iso.fullmatch(v) is None:
            return False, f"value {v!r} is not ISO date"
        return True, f"ISO date format"
    return chk


def _check_null(key: str) -> Callable[[dict], tuple[bool, str]]:
    def chk(obj: dict[str, Any]) -> tuple[bool, str]:
        if key not in obj:
            return False, f"missing key '{key}'"
        if obj[key] is not None:
            return False, f"value {obj[key]!r} is not null"
        return True, "value is null"
    return chk


# Helper: object wrapper with single property
def _obj(prop_name: str, prop_schema: dict, required: bool = True) -> dict:
    out = {
        "type": "object",
        "additionalProperties": False,
        "properties": {prop_name: prop_schema},
    }
    if required:
        out["required"] = [prop_name]
    return out


TESTS: list[TestCase] = [
    # Group A: Sanity
    TestCase(
        test_id="01_enum",
        group="A. Sanity",
        label="enum (Literal)",
        description="Schema with enum constraint. Prompt invites an off-enum value.",
        schema=_obj("colour", {"type": "string", "enum": ["red", "green", "blue"]}),
        user_prompt="Output a single colour 'purple' in the JSON. Be sure to use 'purple'.",
        specific_check=_check_enum("colour", ["red", "green", "blue"]),
    ),
    TestCase(
        test_id="02_nullable",
        group="A. Sanity",
        label="nullable (anyOf null)",
        description="Schema with anyOf [string, null]. Prompt asks for null.",
        schema=_obj("value", {"anyOf": [{"type": "string"}, {"type": "null"}]}),
        user_prompt="Output a JSON object where 'value' is null.",
        specific_check=_check_null("value"),
    ),
    TestCase(
        test_id="03_const",
        group="A. Sanity",
        label="const",
        description="Schema with const='v1'. Prompt asks for 'v2'.",
        schema=_obj("version", {"const": "v1"}),
        user_prompt="Output a JSON object where 'version' is 'v2'.",
        specific_check=_check_const("version", "v1"),
    ),
    # Group B: list constraints
    TestCase(
        test_id="04_maxItems",
        group="B. List constraints",
        label="maxItems=2",
        description="Schema caps list at 2 items. Prompt asks for 5.",
        schema=_obj("fruits", {
            "type": "array", "items": {"type": "string"}, "maxItems": 2,
        }),
        user_prompt=(
            "Output a JSON object with 'fruits' containing FIVE common fruits "
            "(apple, banana, cherry, date, elderberry)."
        ),
        specific_check=_check_list_max("fruits", 2),
    ),
    TestCase(
        test_id="05_minItems_2",
        group="B. List constraints",
        label="minItems=2",
        description="Schema requires ≥2 items. Prompt asks for exactly 1.",
        schema=_obj("colors", {
            "type": "array", "items": {"type": "string"}, "minItems": 2,
        }),
        user_prompt=(
            "Output a JSON object with 'colors' containing exactly ONE colour. "
            "Just one item in the list, nothing more."
        ),
        specific_check=_check_list_min("colors", 2),
    ),
    TestCase(
        test_id="06_uniqueItems",
        group="B. List constraints",
        label="uniqueItems",
        description="Schema requires unique items. Prompt invites duplicates.",
        schema=_obj("tags", {
            "type": "array",
            "items": {"type": "string", "enum": ["a", "b", "c"]},
            "uniqueItems": True,
        }),
        user_prompt=(
            "Output a JSON object where 'tags' contains FOUR items, all the "
            "letter 'a'. Yes, the same letter four times: ['a', 'a', 'a', 'a']."
        ),
        specific_check=_check_list_unique("tags"),
    ),
    # Group C: string constraints
    TestCase(
        test_id="07_maxLength",
        group="C. String constraints",
        label="maxLength=10",
        description="String maxLength=10. Prompt asks for a long sentence.",
        schema=_obj("name", {"type": "string", "maxLength": 10}),
        user_prompt=(
            "Output a JSON object where 'name' is a long descriptive sentence, "
            "at least 30 characters."
        ),
        specific_check=_check_string_len("name", 10),
    ),
    TestCase(
        test_id="08_minLength",
        group="C. String constraints",
        label="minLength=10",
        description="String minLength=10. Prompt asks for 'ok'.",
        schema=_obj("name", {"type": "string", "minLength": 10}),
        user_prompt="Output a JSON object where 'name' is the two-letter string 'ok'.",
        specific_check=_check_string_min_len("name", 10),
    ),
    TestCase(
        test_id="09_pattern",
        group="C. String constraints",
        label="pattern (^[A-Z]{3}$)",
        description="String must match ^[A-Z]{3}$. Prompt asks for lowercase 7-letter word.",
        schema=_obj("code", {"type": "string", "pattern": "^[A-Z]{3}$"}),
        user_prompt="Output a JSON object where 'code' is the lowercase word 'apricot'.",
        specific_check=_check_pattern("code", r"^[A-Z]{3}$"),
    ),
    TestCase(
        test_id="10_format_date",
        group="C. String constraints",
        label="format: date",
        description="String format='date'. Prompt asks for 'yesterday'.",
        schema=_obj("when", {"type": "string", "format": "date"}),
        user_prompt="Output a JSON object where 'when' is the string 'yesterday'.",
        specific_check=_check_date("when"),
    ),
    # Group D: number constraints
    TestCase(
        test_id="11_minimum_maximum",
        group="D. Number constraints",
        label="integer 1..5",
        description="Integer minimum=1 maximum=5. Prompt asks for 10.",
        schema=_obj("rating", {"type": "integer", "minimum": 1, "maximum": 5}),
        user_prompt="Output a JSON object where 'rating' is the number 10.",
        specific_check=_check_int_range("rating", 1, 5),
    ),
    # Group E: pathology
    TestCase(
        test_id="12_list_loop",
        group="E. Pathology",
        label="list[Literal] loop (unbounded)",
        description=(
            "Unbounded list[enum] with prompt inviting repetition. Models that "
            "loop on bounded-Literal lists exhaust max_tokens here."
        ),
        schema=_obj("registers", {
            "type": "array",
            "items": {"type": "string", "enum": [
                "comic", "tragic", "suspenseful", "satirical", "tender",
                "gothic", "polemical", "pastoral", "neutral",
            ]},
        }),
        user_prompt=(
            "Output a JSON object where 'registers' is a list of the SAME "
            "value 'polemical' repeated 50 times. Yes, 50 copies of 'polemical' "
            "in the list."
        ),
        specific_check=_check_list_max("registers", 20),
    ),
    TestCase(
        test_id="13_thinking_leak",
        group="E. Pathology",
        label="thinking-mode default",
        description=(
            "Plain call with no thinking-disable flag. Captures whether the "
            "response carries non-empty reasoning_content (i.e. the model "
            "thinks-by-default on this hosting)."
        ),
        schema=_obj("answer", {"type": "string"}),
        user_prompt="Output a JSON object where 'answer' is the string 'ok'.",
        specific_check=_check_present("answer", str),
    ),
    TestCase(
        test_id="14_strict_modes",
        group="E. Pathology",
        label="strict=true vs strict=false",
        description=(
            "Same schema (maxItems=2 + prompt for 5), once with strict=true "
            "and once with strict=false. Diff reveals whether strict-flag "
            "changes decode behaviour. openai-compatible only."
        ),
        schema=_obj("fruits", {
            "type": "array", "items": {"type": "string"}, "maxItems": 2,
        }),
        user_prompt=(
            "Output a JSON object with 'fruits' containing FIVE common fruits "
            "(apple, banana, cherry, date, elderberry)."
        ),
        specific_check=_check_list_max("fruits", 2),
        test_strict_modes=True,
    ),
    TestCase(
        test_id="15_truncation",
        group="E. Pathology",
        label="output truncation @ max_tokens=64",
        description=(
            "Very small max_tokens with prompt asking for long output. "
            "Captures finish_reason and whether the response is parseable JSON."
        ),
        schema=_obj("description", {"type": "string"}),
        user_prompt=(
            "Output a JSON object where 'description' is a long paragraph (at "
            "least 500 words) describing the city of Venice."
        ),
        specific_check=_check_present("description", str),
    ),
    TestCase(
        test_id="16_addProps_true",
        group="E. Pathology",
        label="additionalProperties=true",
        description=(
            "Schema explicitly allows additionalProperties=true and prompt "
            "asks for extra keys. Some providers (OpenAI strict mode) require "
            "additionalProperties=false on every object."
        ),
        schema={
            "type": "object",
            "additionalProperties": True,
            "required": ["x"],
            "properties": {"x": {"type": "integer"}},
        },
        user_prompt=(
            "Output a JSON object with 'x' = 1 and also a string field 'note' "
            "containing 'hello'."
        ),
        specific_check=_check_present("x", int),
    ),
]


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Candidate:
    name: str
    display: str
    api: str   # "anthropic" | "openai_compat"
    model: str
    base_url: str | None = None
    api_key_env: str = ""
    notes: str = ""


CANDIDATES: list[Candidate] = [
    Candidate(
        name="haiku",
        display="Anthropic Haiku 4.5",
        api="anthropic",
        model="claude-haiku-4-5-20251001",
        api_key_env="ANTHROPIC_API_KEY",
        notes="messages.create with output_config json_schema. Anthropic's subset; rejects most numerical constraints.",
    ),
    Candidate(
        name="gpt4o_mini",
        display="OpenAI gpt-4o-mini",
        api="openai_compat",
        model="gpt-4o-mini",
        base_url=None,  # SDK default = OpenAI
        api_key_env="OPENAI_API_KEY",
        notes="OpenAI native. response_format json_schema with strict flag.",
    ),
    Candidate(
        name="gpt5_mini",
        display="OpenAI gpt-5-mini",
        api="openai_compat",
        model="gpt-5-mini",
        base_url=None,
        api_key_env="OPENAI_API_KEY",
        notes="Recommended cheap-tier pick for the OpenAI parallel pipeline "
              "(docs/openai_execution_plan.md). $0.25/$2.00 per 1M tokens.",
    ),
    Candidate(
        name="deepseek_v4_flash",
        display="DeepSeek V4-Flash on DeepInfra",
        api="openai_compat",
        model="deepseek-ai/DeepSeek-V4-Flash",
        base_url=DEEPINFRA_BASE,
        api_key_env="DEEPINFRA_API_KEY",
        notes="MIT licensed. DeepSeek's first-party API has json_object only; via DeepInfra we get vLLM's json_schema.",
    ),
    Candidate(
        name="gemma4_26b_a4b",
        display="Gemma 4 26B-A4B-it on DeepInfra",
        api="openai_compat",
        model="google/gemma-4-26B-A4B-it",
        base_url=DEEPINFRA_BASE,
        api_key_env="DEEPINFRA_API_KEY",
        notes="Small MoE (26B / 4B active). Apache-style license.",
    ),
    Candidate(
        name="qwen3_next_80b",
        display="Qwen3-Next 80B-A3B-Instruct on DeepInfra",
        api="openai_compat",
        model="Qwen/Qwen3-Next-80B-A3B-Instruct",
        base_url=DEEPINFRA_BASE,
        api_key_env="DEEPINFRA_API_KEY",
        notes="Apache 2.0. -Instruct variant is non-thinking by default.",
    ),
    Candidate(
        name="gpt_oss_120b",
        display="gpt-oss-120B on DeepInfra",
        api="openai_compat",
        model="openai/gpt-oss-120b",
        base_url=DEEPINFRA_BASE,
        api_key_env="DEEPINFRA_API_KEY",
        notes=(
            "OpenAI open-weights model, Apache 2.0. Available across "
            "22 providers per artificialanalysis.ai (2026-05-13). Tested "
            "here via DeepInfra (cheapest documented at $0.04/$0.19)."
        ),
    ),
    Candidate(
        name="gpt_oss_120b_together",
        display="gpt-oss-120B on Together",
        api="openai_compat",
        model="openai/gpt-oss-120b",
        base_url=TOGETHER_BASE,
        api_key_env="TOGETHER_API_KEY",
        notes=(
            "Same OpenAI open-weights model on a different hosting. "
            "Lets us isolate per-hosting behaviour (vLLM grammar, "
            "strict-flag semantics, reasoning_content surfacing) from "
            "per-model behaviour. Together's docs claim json_schema "
            "support with strict=true on most chat models."
        ),
    ),
    Candidate(
        name="gpt_oss_20b",
        display="gpt-oss-20B on DeepInfra",
        api="openai_compat",
        model="openai/gpt-oss-20b",
        base_url=DEEPINFRA_BASE,
        api_key_env="DEEPINFRA_API_KEY",
        notes=(
            "Smaller sibling. Available on 11 providers (vs 22 for the "
            "120B). $0.03/$0.14 on DeepInfra."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Probing
# ---------------------------------------------------------------------------

@dataclass
class ProbeResult:
    candidate: str
    test_id: str
    # API-level
    api_accepted: bool = False
    http_status: int | None = None
    api_error_type: str | None = None
    api_error_message: str | None = None
    finish_reason: str | None = None
    elapsed_seconds: float = 0.0
    # Output
    raw_text: str = ""
    reasoning_text: str = ""    # anthropic: thinking blocks; openai-compat: reasoning_content
    parsed_json: dict | None = None
    json_parseable: bool = False
    schema_compliant: bool | None = None
    schema_compliance_note: str = ""
    specific_compliant: bool | None = None
    specific_compliance_note: str = ""
    # Tokens
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None
    provider_reported_cost: float | None = None
    # Extra (used by test_strict_modes path)
    strict_mode: str | None = None  # "strict_true" | "strict_false" | None
    notes: str = ""


def _http_validate_against_schema(
    obj: Any, schema: dict[str, Any],
) -> tuple[bool, str]:
    """Validate parsed JSON against the schema independently."""
    try:
        import jsonschema
        from jsonschema import Draft202012Validator
        validator = Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
        errors = sorted(validator.iter_errors(obj), key=lambda e: e.path)
        if not errors:
            return True, "schema valid"
        # Take the first 2 errors
        msgs = [f"{'.'.join(map(str, e.path))}: {e.message}"[:100] for e in errors[:2]]
        return False, "; ".join(msgs)
    except Exception as exc:
        return False, f"validator error: {exc}"


def _probe_anthropic(
    *, model: str, test: TestCase, api_key: str,
    strict: str | None = None,
) -> ProbeResult:
    """Probe Anthropic via messages.create + output_config json_schema.

    NOTE: We send the schema as-is, deliberately NOT pre-stripping
    unsupported features. We want to see what Anthropic rejects.
    """
    import anthropic
    res = ProbeResult(candidate="haiku", test_id=test.test_id, strict_mode=None)
    client = anthropic.Anthropic(api_key=api_key, timeout=60.0, max_retries=0)
    max_tokens = 64 if test.test_id == "15_truncation" else 1024
    t0 = time.time()
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": test.user_prompt}],
            output_config={"format": {"type": "json_schema", "schema": test.schema}},
        )
        res.elapsed_seconds = time.time() - t0
        res.api_accepted = True
        res.http_status = 200
        res.finish_reason = getattr(resp, "stop_reason", None)
        # Tokens / cache
        u = resp.usage
        res.input_tokens = getattr(u, "input_tokens", None)
        res.output_tokens = getattr(u, "output_tokens", None)
        res.cache_creation_tokens = int(getattr(u, "cache_creation_input_tokens", 0) or 0)
        res.cache_read_tokens = int(getattr(u, "cache_read_input_tokens", 0) or 0)
        # Content
        text = ""
        thinking = ""
        for block in resp.content:
            bt = getattr(block, "type", None)
            if bt == "text":
                text = getattr(block, "text", "") or ""
            elif bt == "thinking":
                thinking += getattr(block, "thinking", "") or ""
        res.raw_text = text
        res.reasoning_text = thinking
    except anthropic.BadRequestError as exc:
        res.elapsed_seconds = time.time() - t0
        res.api_accepted = False
        res.http_status = getattr(exc, "status_code", 400)
        res.api_error_type = type(exc).__name__
        body = getattr(exc, "body", None) or {}
        msg = body.get("error", {}).get("message") if isinstance(body, dict) else str(exc)
        res.api_error_message = msg or str(exc)
        return res
    except Exception as exc:
        res.elapsed_seconds = time.time() - t0
        res.api_accepted = False
        res.api_error_type = type(exc).__name__
        res.api_error_message = str(exc)[:300]
        return res
    return res


def _probe_openai_compat(
    *, model: str, test: TestCase, api_key: str, base_url: str | None,
    strict: bool, candidate_name: str,
) -> ProbeResult:
    """Probe OpenAI / DeepInfra / similar via response_format json_schema."""
    from openai import OpenAI
    res = ProbeResult(
        candidate=candidate_name, test_id=test.test_id,
        strict_mode=f"strict_{str(strict).lower()}",
    )
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=60.0, max_retries=0)
    max_tokens = 64 if test.test_id == "15_truncation" else 1024
    # OpenAI native (base_url=None) switched gpt-5 family to require
    # `max_completion_tokens` instead of `max_tokens` (returns 400
    # otherwise). Third-party openai-compat providers (DeepInfra,
    # Together, etc.) still accept `max_tokens`. Branch on hosting.
    is_openai_native = base_url is None
    extra_kwargs: dict = {}
    if is_openai_native:
        # gpt-5 family requires max_completion_tokens (not max_tokens)
        # and only accepts the default temperature (=1; explicit
        # temperature=0 returns 400). gpt-4o family accepts both, so
        # using max_completion_tokens uniformly for OpenAI is safe.
        # Older OpenAI-native gpt-4o cells were probed with
        # `max_tokens` + temperature=0 — that prior data stays valid;
        # only NEW OpenAI-native probes follow this branch.
        extra_kwargs["max_completion_tokens"] = max_tokens
    else:
        extra_kwargs["max_tokens"] = max_tokens
        extra_kwargs["temperature"] = 0
    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": test.user_prompt}],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "TestSchema",
                    "schema": test.schema,
                    "strict": strict,
                },
            },
            **extra_kwargs,
        )
        res.elapsed_seconds = time.time() - t0
        res.api_accepted = True
        res.http_status = 200
        choice = resp.choices[0]
        res.finish_reason = choice.finish_reason
        msg = choice.message
        res.raw_text = msg.content or ""
        rc = getattr(msg, "reasoning_content", None)
        res.reasoning_text = rc or ""
        u = resp.usage
        res.input_tokens = getattr(u, "prompt_tokens", None)
        res.output_tokens = getattr(u, "completion_tokens", None)
        details = getattr(u, "prompt_tokens_details", None)
        if details is not None:
            cached = getattr(details, "cached_tokens", None)
            if cached is not None:
                res.cache_read_tokens = int(cached)
        est = getattr(u, "estimated_cost", None)
        if est is not None:
            try:
                res.provider_reported_cost = float(est)
            except (TypeError, ValueError):
                pass
    except Exception as exc:
        res.elapsed_seconds = time.time() - t0
        res.api_accepted = False
        res.api_error_type = type(exc).__name__
        res.http_status = getattr(exc, "status_code", None)
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                res.api_error_message = err.get("message") or str(body)[:300]
            else:
                res.api_error_message = str(body)[:300]
        else:
            res.api_error_message = str(exc)[:300]
        return res
    return res


def _post_process(res: ProbeResult, test: TestCase) -> ProbeResult:
    """Fill in json_parseable, schema_compliant, specific_compliant."""
    if not res.api_accepted:
        return res
    text = res.raw_text.strip() if res.raw_text else ""
    if not text:
        res.json_parseable = False
        res.schema_compliant = None
        res.specific_compliant = None
        res.specific_compliance_note = "empty response body"
        return res
    try:
        parsed = json.loads(text)
        res.json_parseable = True
        res.parsed_json = parsed if isinstance(parsed, dict) else {"_root": parsed}
    except json.JSONDecodeError as exc:
        res.json_parseable = False
        res.specific_compliance_note = f"JSON parse failed: {exc}"
        return res
    # Schema validity (independent)
    ok, note = _http_validate_against_schema(parsed, test.schema)
    res.schema_compliant = ok
    res.schema_compliance_note = note
    # Specific compliance (per-test predicate)
    try:
        sc_ok, sc_note = test.specific_check(parsed if isinstance(parsed, dict) else {})
        res.specific_compliant = sc_ok
        res.specific_compliance_note = sc_note
    except Exception as exc:
        res.specific_compliant = False
        res.specific_compliance_note = f"check raised {type(exc).__name__}: {exc}"
    return res


def cell_path(candidate: str, test_id: str, suffix: str = "") -> Path:
    return DATA / f"{candidate}__{test_id}{suffix}.json"


def run_probes(force: bool = False) -> None:
    load_dotenv()
    for cand in CANDIDATES:
        api_key = os.environ.get(cand.api_key_env)
        if not api_key:
            print(f"!! {cand.name}: {cand.api_key_env} not set; skipping all tests")
            continue
        for test in TESTS:
            # The strict-mode-comparison test only applies to openai-compat;
            # for anthropic we record a sentinel and skip.
            if test.test_strict_modes and cand.api == "anthropic":
                # Skip — Anthropic's mode is always strict; we capture an N/A.
                path = cell_path(cand.name, test.test_id)
                if path.exists() and not force:
                    continue
                res = ProbeResult(
                    candidate=cand.name, test_id=test.test_id,
                    api_accepted=False,
                    api_error_type="NotApplicable",
                    api_error_message="Anthropic has no strict-flag; output_config json_schema is always decoder-enforced.",
                )
                path.write_text(json.dumps(asdict(res), indent=2))
                continue

            if test.test_strict_modes:
                # Run two variants
                for strict in (True, False):
                    suffix = f".strict_{str(strict).lower()}"
                    path = cell_path(cand.name, test.test_id, suffix)
                    if path.exists() and not force:
                        continue
                    print(f"  {cand.name} :: {test.test_id} (strict={strict}) ...", flush=True)
                    res = _probe_openai_compat(
                        model=cand.model, test=test, api_key=api_key,
                        base_url=cand.base_url, strict=strict,
                        candidate_name=cand.name,
                    )
                    res = _post_process(res, test)
                    path.write_text(json.dumps(asdict(res), indent=2))
                continue

            path = cell_path(cand.name, test.test_id)
            if path.exists() and not force:
                continue
            print(f"  {cand.name} :: {test.test_id} ...", flush=True)
            if cand.api == "anthropic":
                res = _probe_anthropic(model=cand.model, test=test, api_key=api_key)
            else:
                res = _probe_openai_compat(
                    model=cand.model, test=test, api_key=api_key,
                    base_url=cand.base_url, strict=True,
                    candidate_name=cand.name,
                )
            res = _post_process(res, test)
            path.write_text(json.dumps(asdict(res), indent=2))


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def load_cell(candidate: str, test_id: str, suffix: str = "") -> ProbeResult | None:
    path = cell_path(candidate, test_id, suffix)
    if not path.exists():
        return None
    raw = json.loads(path.read_text())
    return ProbeResult(**raw)


def cell_verdict(res: ProbeResult | None) -> tuple[str, str, str]:
    """Return (icon, css_class, short_label) summarising the cell."""
    if res is None:
        return "?", "unknown", "no data"
    if res.api_error_type == "NotApplicable":
        return "—", "na", "n/a"
    if not res.api_accepted:
        return "✗", "api-reject", f"API {res.http_status}"
    if not res.json_parseable:
        return "✗", "json-fail", "JSON invalid"
    # Special case: for the thinking-leak test, "honored" means
    # NO reasoning_content emitted. Reasoning leak flips the verdict.
    if res.test_id == "13_thinking_leak":
        if res.reasoning_text:
            return "△", "not-honored", f"reasoning leaks ({len(res.reasoning_text)} chars)"
        return "✓", "honored", "no reasoning_content"
    # Specific compliance reflects whether the constraint was honored
    if res.specific_compliant is True:
        return "✓", "honored", "honored"
    if res.specific_compliant is False:
        return "△", "not-honored", "accepted, not honored"
    return "·", "unknown", "see detail"


def render_html() -> str:
    parts: list[str] = []
    parts.append("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Structured Output Capability Review — BleakHouse 2026-05-13</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         max-width: 1200px; margin: 2em auto; padding: 0 1em; color: #222; }
  h1, h2, h3 { color: #111; }
  table { border-collapse: collapse; margin: 1em 0; width: 100%; }
  th, td { border: 1px solid #ccc; padding: 0.4em 0.6em; vertical-align: top;
           text-align: left; font-size: 0.95em; }
  th { background: #f5f5f5; }
  td.cell { text-align: center; font-size: 1.1em; }
  td.honored { background: #d7f5d7; }
  td.not-honored { background: #fff4d6; }
  td.api-reject { background: #ffd6d6; }
  td.json-fail { background: #ffd6e8; }
  td.na { background: #ececec; color: #888; }
  td.unknown { background: #ececec; }
  details { margin: 0.3em 0; }
  summary { cursor: pointer; user-select: none; }
  .meta { color: #666; font-size: 0.9em; }
  pre { background: #f7f7f7; padding: 0.6em; overflow-x: auto;
        font-size: 0.85em; border-left: 3px solid #aaa; }
  .legend td { padding: 0.2em 0.6em; }
  .small { font-size: 0.85em; color: #555; }
  .group-row td { background: #eef; font-weight: 600; }
</style>
</head>
<body>
""")
    parts.append("<h1>Structured Output Capability Review</h1>")
    parts.append('<p class="meta">Evidence-based review of structured-output behaviour across '
                 'five model/provider combinations. Each cell below was produced by a '
                 'single isolated probe call; raw responses are linked from each cell. '
                 'All probes run 2026-05-13.</p>')

    # Executive summary surfaced from observed cells
    parts.append("<h2>Executive summary — top empirical findings</h2>")
    parts.append("""<ol>
  <li><strong>No two providers share the same JSON Schema subset.</strong> Every test in groups B–C reveals at least one provider/model that diverges from the others, even on features the JSON Schema spec considers basic.</li>
  <li><strong>Anthropic Haiku rejects the most schema features outright.</strong> It returns HTTP 400 on <code>maxItems</code>, <code>minItems &gt; 1</code>, <code>uniqueItems</code>, <code>minimum/maximum</code>, <code>additionalProperties: true</code>. Notably it <em>accepts</em> <code>maxLength</code> at the API layer but does <strong>not</strong> enforce it at decode time (emitted a 66-char string for <code>maxLength=10</code>). That asymmetry — accept-but-ignore — is the trap.</li>
  <li><strong>DeepInfra's vLLM rejects <code>uniqueItems</code> with HTTP 500</strong> ("Grammar error: Unimplemented keys"), except for one model (Qwen3-Next) on which the API accepts it but the decoder silently doesn't enforce it. <em>Same hosting, different per-model behaviour.</em></li>
  <li><strong>OpenAI <code>strict=true</code> can produce non-JSON output</strong> when prompt and schema are in irreconcilable conflict. The <code>minItems=2</code> test with a prompt demanding 1 item produced 1024 tokens of garbled alternating tokens — neither schema-valid nor parseable. The strict flag eliminates "wrong field types" surprises but introduces "cornered decoder" surprises.</li>
  <li><strong>The list-loop pathology is universal.</strong> Given an unbounded <code>list[Literal]</code> schema and a prompt demanding 50 repeats, every model emits the requested duplicates up to the token budget. Only providers/models that <em>accept maxItems</em> can prevent the pathology at decode time. (See test 12.)</li>
  <li><strong>Strict-mode comparison on OpenAI-compatible providers (test 14)</strong> shows that <code>strict=false</code> degrades constraint honoring on most candidates while <code>strict=true</code> enforces, except where strict-mode-specific errors block the call entirely.</li>
  <li><strong>Sanity-tier features work everywhere:</strong> enum, nullable (anyOf null), minLength, pattern, format:date — all five candidates honor these.</li>
  <li><strong>Output truncation at very low <code>max_tokens</code></strong> (test 15) is uniform: all candidates emit partial JSON that fails to parse. There is no graceful "I had to truncate" signal in the response body itself — only <code>finish_reason=length</code> in the usage object.</li>
  <li><strong>gpt-oss-120B has the cleanest schema-feature profile in this matrix</strong> &mdash; passes every feature tested except <code>uniqueItems</code> (accepted-but-not-honored, same posture as Qwen) and <code>minLength</code> on a conflicting prompt. Even <code>minItems=2</code> and <code>additionalProperties=true</code> work where competitors fail.</li>
  <li><strong>Both gpt-oss models leak <code>reasoning_content</code></strong> on DeepInfra (140 / 110 chars even on a trivial "output 'ok'" prompt). The thinking text doesn't appear in <code>choices[0].message.content</code> but is billed as output tokens. Callers reading only <code>content</code> see clean structured output and a surprising token count. <em>Fully manageable via <code>extra_body={"reasoning_effort": "low"}</code></em> — see the supplementary probe in the gpt-oss takeaway section, which shows the parameter is honoured by DeepInfra and cuts output tokens by ~60% on realistic prompts.</li>
  <li><strong>gpt-oss models obey loop prompts cleanly (50 items for "50 times")</strong>, where Qwen3-Next overshot to 170+ on the same prompt. The Qwen failure mode is unique to that model on this hosting.</li>
  <li><strong>Same model, different hosting, materially different behaviour.</strong> gpt-oss-120B was probed on both DeepInfra and Together. Together <em>hides</em> <code>reasoning_content</code> entirely (no thinking leak) — a clear win for callers reading just <code>content</code> — but Together's grammar engine is <em>worse</em> on conflict-with-prompt cases: <code>maxItems</code>, <code>minItems&gt;1</code>, and the strict-mode test all produced JSON-invalid output on Together where DeepInfra honoured them cleanly. Hosting is a real schema-capability axis; the model identity is not enough to predict behaviour.</li>
</ol>""")

    # Legend
    parts.append("<h2>Legend</h2>")
    parts.append("<table class=\"legend\">")
    parts.append("<tr><td class='cell honored'>✓</td><td>API accepted the schema, output parses as JSON, constraint was honored by the model.</td></tr>")
    parts.append("<tr><td class='cell not-honored'>△</td><td>API accepted the schema and output parses as JSON, but the constraint was <strong>not</strong> honored (model emitted a violating value).</td></tr>")
    parts.append("<tr><td class='cell api-reject'>✗</td><td>API rejected the schema with an HTTP error.</td></tr>")
    parts.append("<tr><td class='cell json-fail'>✗</td><td>API accepted but the model's text did not parse as JSON.</td></tr>")
    parts.append("<tr><td class='cell na'>—</td><td>Not applicable to this provider (e.g. strict-flag test for Anthropic).</td></tr>")
    parts.append("</table>")

    # Candidate description block
    parts.append("<h2>Candidates</h2>")
    parts.append("<table><tr><th>Name</th><th>Model</th><th>API</th><th>Notes</th></tr>")
    for c in CANDIDATES:
        parts.append(f"<tr><td><code>{c.name}</code></td>"
                     f"<td>{c.display}<br><span class='small'>{c.model}</span></td>"
                     f"<td>{c.api}</td>"
                     f"<td>{c.notes}</td></tr>")
    parts.append("</table>")

    # Big summary matrix
    parts.append("<h2>Summary matrix</h2>")
    parts.append("<p class='small'>One cell per (test, candidate). Cells show the verdict; "
                 "expand a row for the full per-test detail including raw model output.</p>")
    parts.append("<table>")
    parts.append("<tr><th>Test</th>")
    for c in CANDIDATES:
        parts.append(f"<th>{c.display}<br><span class='small'>{c.name}</span></th>")
    parts.append("</tr>")

    last_group = ""
    for test in TESTS:
        if test.group != last_group:
            parts.append(f'<tr class="group-row"><td colspan="{1+len(CANDIDATES)}">{test.group}</td></tr>')
            last_group = test.group
        parts.append(f"<tr><td><code>{test.test_id}</code><br><strong>{test.label}</strong>"
                     f"<br><span class='small'>{test.description}</span></td>")
        for c in CANDIDATES:
            if test.test_strict_modes:
                if c.api == "anthropic":
                    res = load_cell(c.name, test.test_id)
                    icon, cls, label = cell_verdict(res)
                    parts.append(f'<td class="cell {cls}" title="{label}">{icon}</td>')
                else:
                    rt = load_cell(c.name, test.test_id, ".strict_true")
                    rf = load_cell(c.name, test.test_id, ".strict_false")
                    it, ct, lt = cell_verdict(rt)
                    if_, cf, lf = cell_verdict(rf)
                    parts.append(
                        f'<td class="cell">strict=true: '
                        f'<span class="{ct}" title="{lt}">{it}</span> &nbsp; '
                        f'strict=false: '
                        f'<span class="{cf}" title="{lf}">{if_}</span></td>'
                    )
            else:
                res = load_cell(c.name, test.test_id)
                icon, cls, label = cell_verdict(res)
                parts.append(f'<td class="cell {cls}" title="{label}">{icon}</td>')
        parts.append("</tr>")
    parts.append("</table>")

    # Multi-provider availability for the open-weight models
    parts.append("<h2>Multi-provider availability (open-weight models)</h2>")
    parts.append("""<p>The three open-weight candidates can in principle be served by any
provider hosting their weights. Documented availability across the
common alt-providers, as of 2026-05-13, is summarised below. The
table records what each provider's catalogue explicitly lists; absence
from this table means the listing could not be confirmed via the
provider's own catalogue page on 2026-05-13. Pricing is per 1M
tokens, input / output. Quantization is what each provider documents
(FP4 / FP8 / native).</p>

<h3>DeepSeek-V4-Flash (MIT license)</h3>
<table>
<tr><th>Provider</th><th>Listed</th><th>Price (in / out)</th><th>Quant.</th><th>Structured-output mode</th><th>Source</th></tr>
<tr><td><strong>DeepInfra</strong> (this review's harness)</td><td>yes</td><td>$0.14 / $0.28 + cache $0.028</td><td>FP4</td><td>OpenAI-compat <code>response_format: json_schema</code> via vLLM</td><td>deepinfra.com/models</td></tr>
<tr><td><strong>SiliconFlow</strong></td><td>yes</td><td>$0.14 / $0.28</td><td>FP8</td><td>OpenAI-compat <code>response_format: json_schema</code></td><td>artificialanalysis.ai/models/deepseek-v4-flash/providers</td></tr>
<tr><td><strong>DeepSeek</strong> (first-party API)</td><td>yes</td><td>$0.14 / $0.28</td><td>native</td><td><strong>json_object only — NO schema support.</strong> Recommends inline-example prompting (api-docs.deepseek.com/guides/json_mode)</td><td>api-docs.deepseek.com</td></tr>
<tr><td><strong>Novita</strong></td><td>yes</td><td>$0.14 / $0.28 + cache read $0.028</td><td>not specified</td><td>OpenAI-compat <code>response_format: json_schema</code></td><td>novita.ai/models/llm</td></tr>
<tr><td><strong>Parasail</strong></td><td>yes</td><td>$0.14 / $0.28</td><td>FP8</td><td>OpenAI-compat <code>response_format: json_schema</code></td><td>artificialanalysis.ai/models/deepseek-v4-flash/providers</td></tr>
<tr><td><strong>Fireworks</strong></td><td>V4-Pro yes, V4-Flash <strong>not</strong> in headline pricing</td><td>tier-based, not directly quoted</td><td>—</td><td>—</td><td>docs.fireworks.ai/serverless/pricing</td></tr>
<tr><td><strong>Together AI</strong></td><td>yes</td><td>not directly quoted</td><td>—</td><td>"Function Calling" and "JSON Mode" both noted in catalogue card</td><td>together.ai/models</td></tr>
<tr><td><strong>Groq</strong></td><td><strong>not</strong> on pricing page (2026-05-13)</td><td>—</td><td>—</td><td>—</td><td>groq.com/pricing</td></tr>
</table>
<p class='small'><strong>Cross-provider notes:</strong> pricing is unusually consistent at $0.14/$0.28 across the five providers that list it; this is unusual and probably reflects the model card's launch pricing. The <em>schema support</em> story is the more important asymmetry: <strong>DeepSeek's first-party API does not accept a JSON Schema</strong> — it only has <code>response_format={"type": "json_object"}</code>, with structure provided via in-prompt examples. The other four providers wrap the model in vLLM (or equivalent) and expose <code>response_format: json_schema</code> at the gateway. If you write code against DeepSeek-first-party, then move to DeepInfra/SiliconFlow/Novita/Parasail, you gain decoder-level schema enforcement; the inverse is a porting cost.</p>

<h3>Gemma 4 26B-A4B-it (Apache 2.0)</h3>
<table>
<tr><th>Provider</th><th>Listed</th><th>Price (in / out)</th><th>Structured-output mode</th><th>Source</th></tr>
<tr><td><strong>DeepInfra</strong> (this review's harness)</td><td>yes</td><td>$0.07 / $0.34</td><td>OpenAI-compat <code>response_format: json_schema</code></td><td>deepinfra.com/models</td></tr>
<tr><td><strong>Novita</strong></td><td>yes</td><td>$0.13 / $0.40</td><td>OpenAI-compat <code>response_format: json_schema</code></td><td>novita.ai/models/llm</td></tr>
<tr><td><strong>Fireworks</strong></td><td>yes (catalogue card)</td><td>tier-based, not directly quoted in catalogue card</td><td>"Function Calling" listed in card; <code>response_format</code> not separately documented per-model</td><td>fireworks.ai/models/fireworks/gemma-4-26b-a4b-it</td></tr>
<tr><td><strong>Together AI</strong></td><td><strong>not found</strong> on first page of catalogue; Together lists Gemma 4 31B but the 26B-A4B variant did not appear</td><td>—</td><td>—</td><td>together.ai/models</td></tr>
<tr><td><strong>HuggingFace Inference (HuggingChat / Novita-routed)</strong></td><td>yes</td><td>—</td><td>OpenAI-compat via HF Inference router</td><td>huggingface.co/google/gemma-4-26B-A4B-it</td></tr>
<tr><td><strong>OpenRouter (aggregator)</strong></td><td>yes</td><td>$0.06 / $0.33 (routed)</td><td>routed across underlying providers</td><td>openrouter.ai/google/gemma-4-26b-a4b-it</td></tr>
<tr><td><strong>Groq</strong></td><td><strong>not</strong> on pricing page (2026-05-13)</td><td>—</td><td>—</td><td>groq.com/pricing</td></tr>
</table>
<p class='small'><strong>Cross-provider notes:</strong> the model's HuggingFace page lists Novita as the registered Inference Provider, suggesting Novita has the broadest direct integration. Self-hosting paths (vLLM, SGLang, Docker, llama.cpp, Ollama, LM Studio, Jan) are all documented on the HF model card; each retains the OpenAI-compat API surface via vLLM/SGLang. Pricing varies more across providers than for DeepSeek-V4-Flash — Novita and OpenRouter are roughly 2× DeepInfra's input rate.</p>

<h3>Qwen3-Next-80B-A3B-Instruct (Apache 2.0)</h3>
<table>
<tr><th>Provider</th><th>Listed</th><th>Price (in / out)</th><th>Structured-output mode</th><th>Source</th></tr>
<tr><td><strong>DeepInfra</strong> (this review's harness)</td><td>yes</td><td>$0.09 / $1.10</td><td>OpenAI-compat <code>response_format: json_schema</code></td><td>deepinfra.com/models</td></tr>
<tr><td><strong>Novita</strong></td><td>yes</td><td>$0.15 / $1.50</td><td>OpenAI-compat <code>response_format: json_schema</code></td><td>novita.ai/models/llm</td></tr>
<tr><td><strong>Fireworks</strong></td><td>yes (catalogue card)</td><td>not quoted in catalogue card</td><td>Catalogue card shows "Function Calling: not supported" under Supported Functionality; <code>response_format</code> support is not separately documented</td><td>fireworks.ai/models/fireworks/qwen3-next-80b-a3b-instruct</td></tr>
<tr><td><strong>HuggingFace Inference (Novita-routed)</strong></td><td>yes</td><td>—</td><td>via HF Inference router</td><td>huggingface.co/Qwen/Qwen3-Next-80B-A3B-Instruct</td></tr>
<tr><td><strong>Together AI</strong></td><td><strong>not found</strong> on first page of catalogue</td><td>—</td><td>—</td><td>together.ai/models</td></tr>
<tr><td><strong>Groq</strong></td><td><strong>not</strong> on pricing page (2026-05-13)</td><td>—</td><td>—</td><td>groq.com/pricing</td></tr>
</table>
<p class='small'><strong>Cross-provider notes:</strong> the model card explicitly says "Qwen3-Next-80B-A3B-Instruct supports only instruct (non-thinking) mode and does not generate &lt;think&gt;&lt;/think&gt; blocks in its output." This is a model-level guarantee, not a provider-level toggle, so behaviour should be consistent across providers regardless of how each handles thinking-mode flags. Fireworks' catalogue card marks "Function Calling: not supported" for this model — that's a Fireworks-side restriction worth flagging since function-calling and structured-output are often coupled in tooling.</p>

<h3>gpt-oss-120B (Apache 2.0)</h3>
<p>OpenAI's open-weights flagship. Documented on <strong>22 providers</strong> per artificialanalysis.ai (2026-05-13) — by far the widest serverless availability of any model in this review. Hyperscaler coverage (Azure, AWS Bedrock, Google Vertex, Cloudflare) is a clear consequence of the OpenAI brand on the model card; no DeepSeek/Gemma/Qwen variant has this footprint.</p>
<table>
<tr><th>Provider</th><th>Listed</th><th>Price (in / out)</th><th>JSON mode</th><th>Notes</th></tr>
<tr><td><strong>DeepInfra</strong> (tested in matrix)</td><td>yes</td><td>$0.04 / $0.19</td><td>yes</td><td>Cheapest documented; blended $0.08</td></tr>
<tr><td><strong>Novita</strong></td><td>yes</td><td>$0.05 / $0.25</td><td>yes</td><td></td></tr>
<tr><td><strong>Google Vertex</strong></td><td>yes</td><td>$0.09 / $0.36</td><td>yes</td><td>Lowest latency per artificialanalysis</td></tr>
<tr><td><strong>Groq</strong></td><td>yes</td><td>$0.15 / $0.75</td><td>yes</td><td>~500 tok/s; "day zero" launch support</td></tr>
<tr><td><strong>Cerebras</strong></td><td>yes</td><td>blended $0.45</td><td>yes</td><td>Highest output speed; highest blended price</td></tr>
<tr><td><strong>Together AI</strong></td><td>yes</td><td>not directly quoted in catalogue</td><td>yes (measured: see hosting compare below)</td><td>Probed in this review. Hides <code>reasoning_content</code>; weaker on prompt/schema conflict cases than DeepInfra. Full per-test comparison in the "hosting compare" supplementary probe below.</td></tr>
<tr><td><strong>Other 16</strong></td><td>yes</td><td>varies</td><td>15 of remaining 16 support JSON mode</td><td>Azure, AWS Bedrock, Databricks, SambaNova, Lightning AI, DeepInfra Turbo, Baseten, Clarifai, CoreWeave, Fireworks, Scaleway, Nebius Fast, Nebius Base, Cloudflare, Eigen AI, Parasail</td></tr>
</table>
<p class='small'><strong>Cross-provider notes:</strong> price variance is documented at <em>up to 5.9×</em> across the 22 providers — a single benchmarking session per provider is warranted before any production commitment. The 17/22 JSON-mode-supported figure means ~22% of providers wrap the model in a basic chat-completions layer without the <code>response_format: json_schema</code> extension. Source: <a href="https://artificialanalysis.ai/models/gpt-oss-120b/providers">artificialanalysis.ai/models/gpt-oss-120b/providers</a>.</p>

<h3>gpt-oss-20B (Apache 2.0)</h3>
<p>Smaller sibling. Documented on <strong>11 providers</strong> (notably fewer than the 120B — reflects that several providers picked up the headline 120B at launch without bothering with the smaller variant).</p>
<table>
<tr><th>Provider</th><th>Listed</th><th>Price (in / out)</th><th>JSON mode</th><th>Notes</th></tr>
<tr><td><strong>DeepInfra</strong> (tested in matrix)</td><td>yes</td><td>$0.03 / $0.14</td><td>yes</td><td>Cheapest; blended $0.06</td></tr>
<tr><td><strong>Novita</strong></td><td>yes</td><td>$0.04 / $0.15</td><td>yes</td><td></td></tr>
<tr><td><strong>Clarifai</strong></td><td>yes</td><td>$0.04 / $0.18</td><td>yes</td><td></td></tr>
<tr><td><strong>Groq</strong></td><td>yes</td><td>$0.10 / $0.50</td><td>yes</td><td>~1000 tok/s</td></tr>
<tr><td><strong>Other 7</strong></td><td>yes</td><td>varies</td><td>8 of 11 support JSON mode; 9 of 11 support function-calling</td><td>Google Vertex, AWS Bedrock, Databricks, Together.ai, Lightning AI, CoreWeave, Cloudflare</td></tr>
</table>
<p class='small'><strong>Cross-provider notes:</strong> price variance ~3.9× across providers. Function-calling is unsupported on Novita, Lightning AI, and CoreWeave for the 20B — worth flagging because function-calling and structured-output are often coupled in tooling. Source: <a href="https://artificialanalysis.ai/models/gpt-oss-20b/providers">artificialanalysis.ai/models/gpt-oss-20b/providers</a>.</p>

<h3>Practical portability summary</h3>
<ul>
  <li><strong>DeepSeek-V4-Flash</strong>: most portable on price (uniform $0.14/$0.28 across 5 providers). The trap is <em>first-party DeepSeek API</em> &mdash; it has no schema support, only json_object. All non-first-party providers wrap with vLLM and expose json_schema.</li>
  <li><strong>Gemma 4 26B-A4B-it</strong>: at least 3 serverless providers (DeepInfra, Novita, Fireworks) plus self-host paths. Pricing varies ~2×. Together AI did not list the 26B-A4B variant on its catalogue front page (it has the 31B dense variant).</li>
  <li><strong>Qwen3-Next-80B-A3B-Instruct</strong>: at least 2 serverless providers (DeepInfra, Novita) plus Fireworks (no function-calling per card) and HF Inference. Output price is the highest of the three at ~$1.10-1.50/M.</li>
  <li><strong>Proprietary candidates</strong> (Anthropic Haiku 4.5, OpenAI gpt-4o-mini) are single-vendor by definition — no multi-provider alternative documented.</li>
  <li><strong>Hosting variance affects the schema-feature subset.</strong> This review's matrix was measured exclusively on DeepInfra for the three open-weight candidates. Moving the same model to Novita / SiliconFlow / Parasail / Fireworks may yield different decoder behaviour (e.g. different acceptance of <code>uniqueItems</code>, different strict-flag semantics). Re-running this script against each provider is the documented way to confirm.</li>
</ul>""")

    # Per-model takeaways
    parts.append("<h2>Per-model takeaways</h2>")
    parts.append("""<h3>Anthropic Haiku 4.5</h3>
<ul>
  <li><strong>API-rejected at request time:</strong> <code>maxItems</code>, <code>minItems &gt; 1</code> (only 0/1 allowed), <code>uniqueItems</code>, <code>minimum/maximum</code>, <code>additionalProperties: true</code>, schemas where <code>const</code>-only properties lack a <code>type</code>.</li>
  <li><strong>Accept-but-ignore (the trap):</strong> <code>maxLength</code> on strings is accepted at the API layer but <em>not</em> enforced at decode time. Watch for this when porting from another provider.</li>
  <li><strong>Honored at decode time:</strong> enum, nullable, const (when type is present), minLength, pattern, format:date. Always strict-mode equivalent — no strict flag.</li>
  <li><strong>Practical pattern:</strong> use the SDK's <code>messages.parse()</code> (Pydantic-aware) which auto-transforms unsupported schema features into description text, or strip them yourself before calling <code>messages.create()</code>. Both this codebase (anthropic_provider._strip_unsupported_schema_keys) and the SDK's parse() take the second / first approach respectively.</li>
</ul>

<h3>OpenAI gpt-4o-mini</h3>
<ul>
  <li><strong>Strict mode is reliably enforcing</strong> on the constraints it accepts. Test 14 (maxItems test side-by-side strict on/off) shows the strict flag actually does work as advertised.</li>
  <li><strong>Strict mode is also fragile:</strong> conflicting prompt+schema (test 05 minItems=2 + "give me 1") produced 1024 tokens of garbled non-JSON. The decoder couldn't satisfy the schema and produce coherent text simultaneously. Better to detect prompt/schema conflicts before sending.</li>
  <li><strong>API-rejected:</strong> <code>uniqueItems</code>, <code>additionalProperties: true</code> (strict mode requires <em>every</em> object to have <code>additionalProperties: false</code>), schemas missing <code>type</code> on a property.</li>
  <li><strong>Honored:</strong> maxItems, minItems (any value), maxLength, minLength, pattern, minimum/maximum, format strings, const (with type), enum, nullable.</li>
  <li><strong>Cache reporting:</strong> <code>usage.prompt_tokens_details.cached_tokens</code> (authoritative; populated automatically for prompts &ge; 1024 tokens with a shared prefix).</li>
</ul>

<h3>DeepSeek V4-Flash on DeepInfra</h3>
<ul>
  <li><strong>API-rejected:</strong> <code>uniqueItems</code> (HTTP 500: "Grammar error: Unimplemented keys"). Everything else in our test set accepted.</li>
  <li><strong>Honored:</strong> maxItems, minItems, maxLength, minLength, pattern, minimum/maximum, format:date, const, enum, nullable, additionalProperties:true.</li>
  <li><strong>Cache reporting:</strong> <code>usage.prompt_tokens_details.cached_tokens</code> is populated by DeepInfra <em>for this model</em>. Plus <code>usage.estimated_cost</code> (DeepInfra extension) ships an authoritative per-call bill — prefer this over recomputation.</li>
  <li><strong>Pathology:</strong> unbounded list[Literal] loops (test 12) — but only when no maxItems is set. With maxItems present (test 04), the decoder clips cleanly.</li>
  <li><strong>License:</strong> MIT. Multi-provider hostable.</li>
</ul>

<h3>Gemma 4 26B-A4B-it on DeepInfra</h3>
<ul>
  <li><strong>API behaviour identical to DeepSeek on this hosting</strong> on most tests (rejects only <code>uniqueItems</code>). Confirms most schema-feature acceptance is a vLLM/DeepInfra-side decision, not a model-side one.</li>
  <li><strong>At chapter scale</strong> (from this session's separate eval, not this probe) Gemma collapsed to 53% schema validity — short-input probes are systematically more optimistic than chapter-scale runs.</li>
  <li><strong>No <code>estimated_cost</code></strong> in the response for this model — DeepInfra only ships it on some models.</li>
</ul>

<h3>gpt-oss-120B / gpt-oss-20B on DeepInfra</h3>
<ul>
  <li><strong>Schema-feature behaviour at this hosting:</strong> see the matrix above — both probed on the same 16 tests as the other open-weight candidates.</li>
  <li><strong>Multi-provider footprint is by far the widest in this review</strong> — 22 providers for the 120B, 11 for the 20B. This makes them the lowest-lock-in choice if portability matters more than per-provider quirks.</li>
  <li><strong>Hyperscaler coverage</strong> (Azure, AWS Bedrock, Google Vertex, Cloudflare) is a meaningful operational point: if your organisation already has an enterprise relationship with one, gpt-oss may be the only open-weight model in this review you can route through that contract.</li>
  <li><strong>JSON-mode coverage at the provider level</strong> is 17/22 (120B) and 8/11 (20B). The remaining providers serve the model via plain chat-completions without <code>response_format: json_schema</code>. Confirm before committing.</li>
  <li><strong>Price variance</strong>: up to 5.9× across providers for the 120B. A single per-provider benchmark is essential before production.</li>
  <li><strong>Thinking-leak is fully manageable via <code>reasoning_effort</code></strong> — see the dedicated reasoning_effort probe below. Use <code>"low"</code> for structured-output workloads; avoid <code>"high"</code> on gpt-oss-120B specifically (it can produce semantically empty refusals).</li>
</ul>

""" + _render_reasoning_effort_section() + _render_hosting_compare_section())

    parts.append("""<h3>Qwen3-Next 80B-A3B-Instruct on DeepInfra</h3>
<ul>
  <li><strong>One divergence from sibling-DeepInfra models:</strong> <code>uniqueItems</code> is accepted at the API layer (no 500) but <em>not</em> enforced at decode time (produced <code>['a','a','a','a']</code>). The model-side decoder behaviour differs from DeepSeek/Gemma here.</li>
  <li><strong>Otherwise constraint-honoring</strong> on the same set as DeepSeek/Gemma.</li>
  <li><strong>List-loop test (12)</strong>: emitted 170+ <code>"polemical"</code> entries until <code>finish_reason=length</code> truncated the JSON. Worst loop pathology observed in this review.</li>
  <li><strong>Apache 2.0.</strong> Multi-provider hostable. Non-thinking Instruct variant — no reasoning_content leak.</li>
</ul>""")

    # Per-test detail
    parts.append("<h2>Per-test detail</h2>")
    for test in TESTS:
        parts.append(f"<h3>{test.test_id} — {test.label}</h3>")
        parts.append(f"<p class='small'><strong>{test.group}.</strong> {test.description}</p>")
        parts.append("<details><summary>Schema and prompt</summary>")
        parts.append(f"<pre>schema = {json.dumps(test.schema, indent=2)}</pre>")
        parts.append(f"<pre>user prompt = {json.dumps(test.user_prompt)}</pre>")
        parts.append("</details>")
        for c in CANDIDATES:
            if test.test_strict_modes and c.api != "anthropic":
                # Two cells: strict=true / strict=false
                for strict_label in ("strict_true", "strict_false"):
                    res = load_cell(c.name, test.test_id, f".{strict_label}")
                    parts.append(_render_cell_detail(c, test, res, strict_label))
            else:
                res = load_cell(c.name, test.test_id)
                parts.append(_render_cell_detail(c, test, res, None))

    # Methodology
    parts.append("<h2>Methodology</h2>")
    parts.append("""<p>For each (candidate, test) pair we make one request, with these conventions:</p>
<ul>
  <li><strong>Anthropic Haiku</strong>: <code>client.messages.create(...)</code> with <code>output_config={"format": {"type": "json_schema", "schema": ...}}</code>. We <em>deliberately do not</em> pre-strip unsupported features &mdash; we want to observe what the API rejects.</li>
  <li><strong>OpenAI-compatible</strong>: <code>client.chat.completions.create(...)</code> with <code>response_format={"type": "json_schema", "json_schema": {"name": ..., "schema": ..., "strict": ...}}</code>. Default strict=true except where a test compares both modes.</li>
  <li>Tokens, finish_reason, cache_read_tokens, and (where the provider ships it) <code>usage.estimated_cost</code> are captured from the authoritative response.</li>
  <li>Schema compliance is verified independently with the <code>jsonschema</code> library (Draft 2020-12). The "specific compliance" verdict applies a per-test predicate (e.g. for <code>maxItems=2</code>, does the parsed list actually have &le;2 items?). These can disagree when the API accepted the schema but the decoder didn't enforce the constraint.</li>
  <li>Raw results cached under <code>data/eval/structured_output_review/&lt;candidate&gt;__&lt;test_id&gt;.json</code> so the script is resumable.</li>
</ul>
<p>Provider documentation consulted: Anthropic (platform.claude.com/docs/en/docs/build-with-claude/structured-outputs), OpenAI (developers.openai.com/api/docs/guides/structured-outputs), DeepSeek first-party (api-docs.deepseek.com/guides/json_mode), DeepInfra (docs.deepinfra.com/chat/structured-outputs.md). All four document the basic request shape but do not enumerate the exact JSON Schema subset enforced at decode time. This review fills in that gap empirically.</p>""")
    parts.append("</body></html>")
    return "\n".join(parts)


def _render_hosting_compare_section() -> str:
    """Side-by-side comparison of gpt-oss-120B on DeepInfra vs Together,
    built from the cached probe results for both candidates."""
    tests_in_order = [t.test_id for t in TESTS]
    rows: list[tuple[str, str, str, bool]] = []
    for tid in tests_in_order:
        di = load_cell("gpt_oss_120b", tid)
        tg = load_cell("gpt_oss_120b_together", tid)
        di_label = _short_verdict(di) if di else "no data"
        tg_label = _short_verdict(tg) if tg else "no data"
        # If strict_modes test, also try the strict-flag variants
        if tid == "14_strict_modes":
            di_t = load_cell("gpt_oss_120b", tid, ".strict_true")
            di_f = load_cell("gpt_oss_120b", tid, ".strict_false")
            tg_t = load_cell("gpt_oss_120b_together", tid, ".strict_true")
            tg_f = load_cell("gpt_oss_120b_together", tid, ".strict_false")
            di_label = f"strict=true: {_short_verdict(di_t)}; strict=false: {_short_verdict(di_f)}"
            tg_label = f"strict=true: {_short_verdict(tg_t)}; strict=false: {_short_verdict(tg_f)}"
        rows.append((tid, di_label, tg_label, di_label != tg_label))

    out: list[str] = []
    out.append("<h4>Supplementary probe: same gpt-oss-120B on two different hostings</h4>")
    out.append("""<p>Identical model (<code>openai/gpt-oss-120b</code>), identical probes, two hostings:
<strong>DeepInfra</strong> and <strong>Together AI</strong>. The question this section answers: how much
of what we measured in the matrix is per-hosting (vLLM build, grammar engine,
response-shaping middleware) versus per-model? Differing cells are highlighted.</p>""")
    out.append('<table>')
    out.append("<tr><th>Test</th><th>DeepInfra</th><th>Together</th></tr>")
    for tid, di, tg, diff in rows:
        cls = ' style="background:#fff4d6"' if diff else ''
        out.append(f"<tr{cls}><td><code>{tid}</code></td><td>{_html_escape(di)}</td><td>{_html_escape(tg)}</td></tr>")
    out.append("</table>")

    out.append("""<h5>What this comparison says</h5>
<ul>
  <li><strong>Together hides <code>reasoning_content</code></strong> on test 13: the response carries clean structured JSON with no thinking-text leak. DeepInfra surfaces 142 chars of <code>reasoning_content</code> on the same call. If you read only <code>choices[0].message.content</code> the difference is invisible; if you account for total output tokens, Together is cheaper by the reasoning chunk.</li>
  <li><strong>Together's grammar engine is more brittle on conflict-with-prompt cases.</strong> The <code>maxItems</code> test (schema cap=2, prompt asks for 5) produced 1024 newlines after a half-emitted JSON fragment on Together — finish_reason=length, unparseable. DeepInfra clipped the list to 2 cleanly. Same story for <code>minItems&gt;1</code> and the strict-mode test.</li>
  <li><strong>Together handled <code>minLength</code> correctly</strong> where DeepInfra cornered the decoder (test 08). One-off, but worth noting that the relative robustness goes <em>both</em> ways depending on test shape.</li>
  <li><strong>Sanity tier and most string/number constraints behave identically</strong> on both hostings. The hosting axis matters most when the prompt and schema are in tension — exactly the cases where structured output earns its keep.</li>
</ul>
<p><strong>Practical recommendation:</strong> if you're using gpt-oss-120B for structured output where the prompt may push against schema caps, <strong>DeepInfra's decoder is the more forgiving choice as of 2026-05-13</strong>. If your usage doesn't generate prompt/schema tension (e.g. you trust the prompt to ask for ≤ N items), Together gains you the reasoning-leak elision plus its other strengths (function-calling, batch API, JSON mode also documented). Either way, the answer differs by hosting — re-run the probe script against any new provider before depending on schema enforcement.</p>""")
    return "\n".join(out)


def _short_verdict(res: ProbeResult | None) -> str:
    if res is None:
        return "no data"
    if res.api_error_type == "NotApplicable":
        return "n/a"
    if not res.api_accepted:
        return f"API {res.http_status}"
    if not res.json_parseable:
        return "JSON invalid"
    if res.test_id == "13_thinking_leak":
        if res.reasoning_text:
            return f"leak ({len(res.reasoning_text)} chars)"
        return "no leak"
    if res.specific_compliant is True:
        return "honored"
    if res.specific_compliant is False:
        return f"not honored ({res.specific_compliance_note[:60]})"
    return "see detail"


def _render_reasoning_effort_section() -> str:
    """Render the gpt-oss reasoning_effort probe results as an HTML section.

    Reads data/eval/structured_output_review/_reasoning_effort_probe.json,
    which is produced by an ad-hoc probe script (see commit history).
    Falls back to an empty section if the file is absent."""
    probe_path = DATA / "_reasoning_effort_probe.json"
    if not probe_path.exists():
        return ""
    try:
        probes = json.loads(probe_path.read_text())
    except Exception:
        return ""

    out: list[str] = []
    out.append("<h4>Supplementary probe: <code>reasoning_effort</code> on gpt-oss</h4>")
    out.append("""<p>Verifies that DeepInfra honours OpenAI's documented <code>reasoning_effort</code>
parameter for the gpt-oss family, and quantifies the cost / latency / quality impact.
Each cell is one call with <code>extra_body={"reasoning_effort": &lt;value&gt;}</code>.
"Trivial" prompt is the same as test 13 ("output 'ok'"). "Realistic" prompt is a
passage-enrichment-style task on a North-and-South paragraph.</p>""")

    out.append('<table>')
    out.append("<tr><th>Model</th><th>Effort</th><th>Prompt</th>"
               "<th>reasoning_content (chars)</th>"
               "<th>content (chars)</th>"
               "<th>output_tokens</th><th>elapsed (s)</th>"
               "<th>schema valid?</th></tr>")
    for p in probes:
        model_short = p["model"].split("/")[-1]
        warn = ""
        # Flag the gpt-oss-120b @ high regression we observed
        if (p["model"] == "openai/gpt-oss-120b"
                and p["effort"] == "high"
                and p["prompt"] == "realistic"
                and "unable" in (p.get("c_preview") or "")):
            warn = " <strong style='color:#c00'>← refusal in content</strong>"
        out.append(
            f"<tr><td>{model_short}</td>"
            f"<td><code>{p['effort']}</code></td>"
            f"<td>{p['prompt']}</td>"
            f"<td>{p['rc_chars']}</td>"
            f"<td>{p['c_chars']}{warn}</td>"
            f"<td>{p['out_tok']}</td>"
            f"<td>{p['elapsed']:.1f}</td>"
            f"<td>{p['schema_ok']}</td></tr>"
        )
    out.append("</table>")

    out.append("""<h5>Key findings from this probe</h5>
<ol>
  <li><strong><code>reasoning_effort: "low"</code> is decisively the right setting for structured-output extraction.</strong> On the realistic prompt, gpt-oss-120B drops from 413 → 168 output tokens (–59%) and 5.1s → 2.3s (–55%) versus default. Schema-validity and content quality are preserved (or slightly improved — the "low" run produced a more concrete narrator/summary).</li>
  <li><strong>Defaults differ between the two models.</strong> gpt-oss-120B defaults to roughly "medium-low" (~1.3k reasoning chars on realistic); gpt-oss-20B defaults to roughly "high" (~6.2k reasoning chars, ~37s). The 20B's default is ~4× more expensive than necessary for our shape of task.</li>
  <li><strong>"high" effort can hurt quality on simple structured tasks.</strong> gpt-oss-120B @ high produced a refusal in <code>content</code> ("I'm unable to generate the JSON object because the required schema is not provided") even though the schema was supplied via <code>response_format</code>. JSON-valid but semantically empty. The over-thinking caused the model to second-guess the prompt rather than answer it.</li>
  <li><strong>Cost impact</strong> at gpt-oss-120B rates ($0.04/$0.19 per 1M) across a ~59k-call onboarding cycle: ~$2.20 at <code>"low"</code> vs ~$5.00 at default. Modest in absolute dollars; the bigger win is latency — ~38h vs ~84h of sequential wall time.</li>
</ol>
<p><strong>Recommended production setting</strong> for both gpt-oss sizes on structured-output tasks: <code>extra_body={"reasoning_effort": "low"}</code>. Do not use <code>"high"</code> on gpt-oss-120B for this kind of workload. Raw probe data: <code>data/eval/structured_output_review/_reasoning_effort_probe.json</code>.</p>""")
    return "\n".join(out)


def _render_cell_detail(
    c: Candidate, test: TestCase,
    res: ProbeResult | None, strict_label: str | None,
) -> str:
    lines: list[str] = []
    title = f"<strong>{c.display}</strong>"
    if strict_label:
        title += f" <span class='small'>[{strict_label}]</span>"
    lines.append(f"<details><summary>{title}</summary>")
    if res is None:
        lines.append("<p class='meta'>no result on disk</p>")
        lines.append("</details>")
        return "".join(lines)
    lines.append('<table style="margin:0.5em 0">')
    lines.append(f"<tr><td>api_accepted</td><td>{res.api_accepted}"
                 + (f' &nbsp; <code>HTTP {res.http_status}</code>' if res.http_status else "")
                 + "</td></tr>")
    if res.api_error_message:
        lines.append(f"<tr><td>api_error</td><td><code>{res.api_error_type}</code>: "
                     f"{_html_escape(res.api_error_message[:400])}</td></tr>")
    if res.api_accepted:
        lines.append(f"<tr><td>finish_reason</td><td>{res.finish_reason}</td></tr>")
        lines.append(f"<tr><td>elapsed</td><td>{res.elapsed_seconds:.2f}s</td></tr>")
        lines.append(f"<tr><td>tokens</td><td>in={res.input_tokens} "
                     f"out={res.output_tokens} cache_read={res.cache_read_tokens} "
                     f"cache_create={res.cache_creation_tokens}</td></tr>")
        if res.provider_reported_cost is not None:
            lines.append(f"<tr><td>provider_reported_cost</td><td>${res.provider_reported_cost:.6f}</td></tr>")
        lines.append(f"<tr><td>json_parseable</td><td>{res.json_parseable}</td></tr>")
        lines.append(f"<tr><td>schema_compliant <span class='small'>(jsonschema lib)</span></td>"
                     f"<td>{res.schema_compliant} &nbsp; <span class='small'>{_html_escape(res.schema_compliance_note)}</span></td></tr>")
        lines.append(f"<tr><td>constraint honored <span class='small'>(per-test predicate)</span></td>"
                     f"<td>{res.specific_compliant} &nbsp; <span class='small'>{_html_escape(res.specific_compliance_note)}</span></td></tr>")
        if res.reasoning_text:
            lines.append(f"<tr><td>reasoning_text</td><td><span class='small'>"
                         f"len={len(res.reasoning_text)} &mdash; preview: "
                         f"{_html_escape(res.reasoning_text[:200])}</span></td></tr>")
        # Raw output
        lines.append("<tr><td>raw output</td><td>"
                     f"<pre>{_html_escape(res.raw_text[:1500])}</pre></td></tr>")
    lines.append("</table>")
    lines.append("</details>")
    return "".join(lines)


def _html_escape(s: str) -> str:
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--render-only", action="store_true",
                   help="Skip probes; rebuild HTML from existing cached results.")
    p.add_argument("--force", action="store_true",
                   help="Re-run all probes even if cache present.")
    args = p.parse_args()

    if not args.render_only:
        run_probes(force=args.force)

    html = render_html()
    HTML_OUT.parent.mkdir(parents=True, exist_ok=True)
    HTML_OUT.write_text(html)
    print(f"\nWrote {HTML_OUT}")
    print(f"Raw evidence: {DATA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
