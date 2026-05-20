"""Diagnose why open-weight models fail structured output on the
passage_enrichment schema.

Strategy:
- Tiny fixture (1 paragraph) so output should be ~300-500 tokens
  on success. Eliminates 'output truncated' as a confounder.
- Try each candidate × `strict` flag value (True / False).
- Capture finish_reason, full output text, Pydantic validation
  result, token usage.

Conclusions to draw:
- If a model produces valid JSON with strict=True but not strict=False
  → strict-flag enforcement is the cause. Update capabilities table.
- If a model fails regardless of strict → it's a capability issue.
- If a model hits finish_reason=length even on tiny input → token
  budget is the cause (revisit).

Run:
    uv run python scripts/debug_structured_output.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from enrichment.novel_prompts import build_enrichment_prompt  # noqa: E402
from enrichment.llm.schemas import ChapterEnrichmentResult  # noqa: E402

load_dotenv()

# Sample paragraphs below are pastiche-Boffin (Our Mutual Friend); use
# OMF's per-novel prompt so we're not leaking BH-specific context.
DEBUG_NOVEL_KEY = "our_mutual_friend"
DEBUG_SYSTEM_PROMPT = build_enrichment_prompt(DEBUG_NOVEL_KEY)

# Tiny fixture: 1 paragraph. Schema-valid output is ~250-400 tokens.
USER_1P = """Chapter: test - The Sample Chapter

[P0] Mr Boffin walked slowly into the parlour, his greatcoat heavy on his shoulders. The fire crackled in the grate. His wife looked up from her sewing and gave him a tired smile. "You've been gone a long while," she said."""

# 3-paragraph fixture to test scaling. Output should be ~700-1200 tokens.
USER_3P = """Chapter: test - The Sample Chapter

[P0] Mr Boffin walked slowly into the parlour, his greatcoat heavy on his shoulders. The fire crackled in the grate. His wife looked up from her sewing and gave him a tired smile. "You've been gone a long while," she said.

[P1] He set his hat down with care, as a man does who has been thinking of important matters. The shadows of the firelight made strange patterns on the wall — almost, one might have said, the shape of a man stooping over a strongbox.

[P2] "I've been considering," said Mr Boffin at length, "what is to be done about the Will." """

# Default fixture used by probes (overridden inline below).
USER = USER_1P

SCHEMA = ChapterEnrichmentResult.model_json_schema()

DEEPINFRA = "https://api.deepinfra.com/v1/openai"


def _summarise(resp, model: str, *, strict: bool | None, elapsed: float) -> dict:
    """Extract our diagnostic dimensions from an OpenAI-compat response."""
    choice = resp.choices[0]
    msg = choice.message
    content = getattr(msg, "content", None) or ""
    finish = choice.finish_reason
    reasoning = getattr(msg, "reasoning_content", None) or ""
    usage = resp.usage

    # Schema validation
    try:
        ChapterEnrichmentResult.model_validate_json(content)
        schema_valid = True
        schema_err = None
    except Exception as exc:
        schema_valid = False
        schema_err = type(exc).__name__ + ": " + str(exc)[:200]

    return {
        "model": model,
        "strict": strict,
        "finish_reason": finish,
        "elapsed_seconds": elapsed,
        "input_tokens": getattr(usage, "prompt_tokens", None),
        "output_tokens": getattr(usage, "completion_tokens", None),
        "reasoning_chars": len(reasoning),
        "content_chars": len(content),
        "content_preview": content[:300],
        "starts_with_brace": content.lstrip().startswith("{"),
        "schema_valid": schema_valid,
        "schema_err": schema_err,
    }


def probe_openai_compat(
    *, model: str, base_url: str, api_key: str, strict: bool, max_tokens: int,
    user: str = USER_1P, temperature: float = 0.0,
) -> dict:
    """temperature=0 removes output-length stochasticity. Earlier
    probe runs at default temperature produced wildly different
    outputs across calls (sometimes concise + schema-valid, sometimes
    rambling + length-truncated). That noise hid the true capability
    signal."""
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url)
    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": DEBUG_SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "ChapterEnrichmentResult",
                    "schema": SCHEMA,
                    "strict": strict,
                },
            },
        )
        elapsed = time.time() - t0
        return _summarise(resp, model, strict=strict, elapsed=elapsed)
    except Exception as exc:
        elapsed = time.time() - t0
        return {
            "model": model,
            "strict": strict,
            "elapsed_seconds": elapsed,
            "error": type(exc).__name__ + ": " + str(exc)[:300],
        }


def probe_anthropic(*, model: str, max_tokens: int, user: str = USER_1P) -> dict:
    import anthropic
    client = anthropic.Anthropic()
    t0 = time.time()
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=DEBUG_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
        output_config={
            "format": {"type": "json_schema", "schema": SCHEMA},
        },
    )
    elapsed = time.time() - t0
    block = resp.content[0]
    content = getattr(block, "text", "") if block.type == "text" else ""
    try:
        ChapterEnrichmentResult.model_validate_json(content)
        schema_valid = True
        schema_err = None
    except Exception as exc:
        schema_valid = False
        schema_err = type(exc).__name__ + ": " + str(exc)[:200]
    return {
        "model": model,
        "strict": "n/a (anthropic always strict)",
        "elapsed_seconds": elapsed,
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
        "content_chars": len(content),
        "content_preview": content[:300],
        "starts_with_brace": content.lstrip().startswith("{"),
        "schema_valid": schema_valid,
        "schema_err": schema_err,
    }


def main() -> int:
    deepinfra_key = os.environ.get("DEEPINFRA_API_KEY")
    if deepinfra_key is None:
        raise SystemExit("DEEPINFRA_API_KEY not set in .env")

    # Probe matrix: model × strict-flag.
    # Llama removed — earlier probes showed it produces markdown-wrapped
    # pseudo-JSON regardless of strict-flag on DeepInfra. Adding Qwen3
    # variants worth comparing against the 235B winner.
    deepinfra_candidates = [
        "Qwen/Qwen3-235B-A22B-Instruct-2507",
        "Qwen/Qwen3-32B",
        "Qwen/Qwen2.5-72B-Instruct",
    ]

    results: list[dict] = []

    print(f"== probing schema_valid for ChapterEnrichmentResult on a 1-paragraph input ==")
    print(f"   max_tokens=2048 (plenty for 1-paragraph output of ~300-500 tokens)")
    print()

    # Anthropic Haiku baseline first.
    print("--- Anthropic Haiku 4.5 (output_config) ---")
    try:
        r = probe_anthropic(model="claude-haiku-4-5-20251001", max_tokens=2048)
        results.append(r)
        print(json.dumps({k: v for k, v in r.items() if k != "content_preview"}, indent=2))
        print(f"  preview: {r['content_preview'][:200]!r}")
    except Exception as exc:
        print(f"  haiku probe failed: {exc}")
    print()

    # DeepInfra candidates × strict flag
    for model in deepinfra_candidates:
        for strict in (False, True):
            print(f"--- {model} (strict={strict}) ---")
            r = probe_openai_compat(
                model=model, base_url=DEEPINFRA, api_key=deepinfra_key,
                strict=strict, max_tokens=2048,
            )
            results.append(r)
            print(json.dumps(
                {k: v for k, v in r.items() if k != "content_preview"},
                indent=2,
            ))
            preview = r.get("content_preview", "")
            if preview:
                print(f"  preview: {preview[:200]!r}")
            print()

    # Scaling check: 3-paragraph input on the candidates that passed
    # the 1-paragraph probe. Output should be 3x larger; if a candidate
    # passes 1-paragraph but fails 3-paragraph it has trouble sustaining
    # the schema. Use max_tokens=8192 to remove length-truncation as a
    # confounder.
    print("=" * 80)
    print("== scaling probe: 3 paragraphs (output should be ~700-1200 tokens) ==")
    print("   max_tokens=8192; strict=False (proven cleaner)")
    print("   Qwen3-32B tested with /no_think suffix to disable thinking mode")
    print()
    for model in deepinfra_candidates:
        user = USER_3P
        # Qwen 3 family supports `/no_think` to suppress thinking tokens
        # in content (per Qwen 3 model card).
        if "Qwen3" in model:
            user = USER_3P + "\n\n/no_think"
        print(f"--- {model} on 3-paragraph input (user-suffix:"
              f" {'+/no_think' if '/no_think' in user else 'none'}) ---")
        r = probe_openai_compat(
            model=model, base_url=DEEPINFRA, api_key=deepinfra_key,
            strict=False, max_tokens=8192, user=user,
        )
        results.append({**r, "fixture": "3p-8k"})
        if "error" in r:
            print(f"  ERROR: {r['error']}")
        else:
            print(json.dumps(
                {k: v for k, v in r.items() if k != "content_preview"},
                indent=2,
            ))
            print(f"  preview: {r['content_preview'][:200]!r}")
        print()

    # Final summary table
    print("=" * 80)
    print(f"{'model':50s} {'strict':>6s} {'fixture':>8s} {'valid':>5s} {'finish':>10s}")
    for r in results:
        model = r.get("model", "?")[:50]
        strict = str(r.get("strict", "?"))[:6]
        fixture = r.get("fixture", "1p")[:8]
        if "error" in r:
            print(f"{model:50s} {strict:>6s} {fixture:>8s} {'ERR':>5s} {r['error'][:50]}")
        else:
            sv = "Yes" if r.get("schema_valid") else "No"
            finish = str(r.get("finish_reason", "?"))[:10]
            print(f"{model:50s} {strict:>6s} {fixture:>8s} {sv:>5s} {finish:>10s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
