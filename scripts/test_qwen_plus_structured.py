"""Schema-feature probe for Alibaba qwen-plus (DashScope Singapore intl).

Three tests, cheapest first. Stops printing per-attempt JSON for legibility
but reports finish_reason + token counts + validation outcome for each.

Run:  uv run python scripts/test_qwen_plus_structured.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
MODEL = "qwen-plus"


SMALL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "turns"],
    "properties": {
        "title": {"type": "string"},
        "turns": {
            "type": "array",
            "minItems": 2,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["speaker", "text"],
                "properties": {
                    "speaker": {"type": "string"},
                    "text": {"type": "string"},
                },
            },
        },
    },
}

SYSTEM = "You write tiny podcast segments. Output JSON only."
USER = (
    "Produce a 3-turn podcast segment titled 'Fog on the Thames' between "
    "speakers 'Host' and 'Expert' about the opening of Bleak House. "
    "Each turn ~30 words."
)


def _make_client() -> OpenAI:
    load_dotenv()
    key = os.getenv("ALIBABA_API_KEY")
    if not key:
        print("ERROR: ALIBABA_API_KEY not set in env / .env", file=sys.stderr)
        sys.exit(2)
    return OpenAI(api_key=key, base_url=BASE_URL, timeout=120.0, max_retries=0)


def _summarise(label: str, resp) -> tuple[str | None, str]:
    choice = resp.choices[0]
    content = choice.message.content
    usage = resp.usage.model_dump() if resp.usage else {}
    in_tok = int(usage.get("prompt_tokens") or 0)
    out_tok = int(usage.get("completion_tokens") or 0)
    finish = choice.finish_reason
    parse_status = "n/a"
    if content:
        try:
            obj = json.loads(content)
            parse_status = f"json OK, keys={list(obj)[:3]}"
        except Exception as e:
            parse_status = f"json FAIL: {e.__class__.__name__}: {e}"
    print(
        f"  {label}: in={in_tok} out={out_tok} finish={finish} "
        f"len(content)={len(content) if content else 0}  parse={parse_status}"
    )
    return content, parse_status


def attempt_strict_json_schema(client: OpenAI) -> None:
    print("=== Attempt 1: response_format=json_schema, strict=True ===")
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": USER},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "tiny_segment",
                    "strict": True,
                    "schema": SMALL_SCHEMA,
                },
            },
            max_completion_tokens=2048,
            temperature=0.7,
            stream=False,
        )
        _summarise("strict=True", resp)
    except Exception as e:
        print(f"  REJECTED: {e.__class__.__name__}: {e}")


def attempt_loose_json_schema(client: OpenAI) -> None:
    print("\n=== Attempt 2: response_format=json_schema, strict=False ===")
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": USER},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "tiny_segment",
                    "strict": False,
                    "schema": SMALL_SCHEMA,
                },
            },
            max_completion_tokens=2048,
            temperature=0.7,
            stream=False,
        )
        _summarise("strict=False", resp)
    except Exception as e:
        print(f"  REJECTED: {e.__class__.__name__}: {e}")


def attempt_json_object(client: OpenAI) -> None:
    print("\n=== Attempt 3: response_format=json_object (plain JSON mode) ===")
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM
                 + "\n\nReturn an object with keys: title (string), "
                 "turns (array of {speaker, text})."},
                {"role": "user", "content": USER},
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=2048,
            temperature=0.7,
            stream=False,
        )
        _summarise("json_object", resp)
    except Exception as e:
        print(f"  REJECTED: {e.__class__.__name__}: {e}")


def attempt_no_format(client: OpenAI) -> None:
    print("\n=== Attempt 4: no response_format (smoke test) ===")
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "Reply with a single word."},
                {"role": "user", "content": "Say hello."},
            ],
            max_completion_tokens=16,
            temperature=0,
            stream=False,
        )
        _summarise("no_format", resp)
    except Exception as e:
        print(f"  REJECTED: {e.__class__.__name__}: {e}")


def main() -> None:
    client = _make_client()
    print(f"Endpoint: {BASE_URL}\nModel:    {MODEL}\n")
    attempt_no_format(client)
    attempt_strict_json_schema(client)
    attempt_loose_json_schema(client)
    attempt_json_object(client)


if __name__ == "__main__":
    main()
