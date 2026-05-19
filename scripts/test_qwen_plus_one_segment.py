"""One-segment Phase-3 probe for Alibaba qwen-plus.

Re-uses the production phase3_runner helpers (_load_*, _build_client,
_call_chat_completions) but only generates segment 0 of a source run.
Validates against EpisodeSegment and prints the prose, token counts,
cost, and validation outcome.

Run:
    uv run python scripts/test_qwen_plus_one_segment.py \\
        --source data/runs/bh_trn_literary_hostprep
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from enrichment import axes
from enrichment.generate_podcast import build_messages
from enrichment.llm.schemas import EpisodeSegment
from enrichment.phase3_pricing import cost_usd
from enrichment.phase3_runner import (
    _activate_novel,
    _build_client,
    _call_chat_completions,
    _load_host_briefs,
    _load_personas,
    _load_planned_segments,
    _load_prompt_version,
    _resolve_generator,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--model", default="alibaba_qwen_plus")
    ap.add_argument("--segment-index", type=int, default=0)
    ap.add_argument("--max-completion-tokens", type=int, default=16384)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--out", type=Path, default=Path("data/runs/_qwen_plus_one_segment.json"))
    args = ap.parse_args()

    source_dir: Path = args.source
    _activate_novel(source_dir)
    generator = _resolve_generator(args.model)
    print(f"generator: {generator.id} (api_model={generator.api_model}, provider={generator.provider})")

    planned = _load_planned_segments(source_dir)
    host_briefs = _load_host_briefs(source_dir)
    prompt_version = _load_prompt_version(source_dir)
    personas = _load_personas(source_dir)

    i = args.segment_index
    if i < 0 or i >= len(planned):
        raise SystemExit(f"--segment-index {i} out of range (0..{len(planned)-1})")

    seg = planned[i]
    prev_title = planned[i - 1].template.name if i > 0 else None
    next_title = planned[i + 1].template.name if i < len(planned) - 1 else None
    brief = host_briefs[i] if host_briefs else None

    system_msg, user_msg = build_messages(
        seg, personas,
        is_first_segment=(i == 0),
        prompt_version=prompt_version,
        previous_segment_title=prev_title,
        next_segment_title=next_title,
        host_brief=brief,
    )

    schema = EpisodeSegment.model_json_schema()
    client = _build_client(generator.provider)

    print(f"\nSegment {i}: '{seg.template.name}' ({len(seg.assignments)} passages)")
    print(f"Calling {generator.api_model} via {generator.provider} ...")

    start = time.perf_counter()
    content, in_tok, out_tok, _reasoning_tok, finish_reason = _call_chat_completions(
        client=client,
        model=generator.api_model,
        system_msg=system_msg,
        user_msg=user_msg,
        schema=schema,
        max_completion_tokens=args.max_completion_tokens,
        temperature=args.temperature,
        reasoning_effort=None,
    )
    elapsed = time.perf_counter() - start

    seg_cost = cost_usd(generator.api_model, in_tok, out_tok) or 0.0
    print(
        f"\n--- metrics ---\n"
        f"elapsed_seconds: {elapsed:.1f}\n"
        f"input_tokens:    {in_tok}\n"
        f"output_tokens:   {out_tok}\n"
        f"finish_reason:   {finish_reason}\n"
        f"cost_usd:        ${seg_cost:.4f}\n"
        f"tokens_per_sec:  {out_tok/elapsed:.1f}" if elapsed > 0 else ""
    )

    validation = "ok"
    episode_seg = None
    if not content:
        validation = f"failed: empty content (finish_reason={finish_reason})"
    else:
        try:
            obj = json.loads(content)
            episode_seg = EpisodeSegment.model_validate(obj)
        except json.JSONDecodeError as e:
            validation = f"failed: JSONDecodeError {e}"
        except Exception as e:
            validation = f"failed: {e.__class__.__name__}: {e}"
    print(f"validation:      {validation}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generator_id": generator.id,
        "api_model": generator.api_model,
        "provider": generator.provider,
        "source_dir": str(source_dir),
        "segment_index": i,
        "segment_name": seg.template.name,
        "metrics": {
            "elapsed_seconds": elapsed,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "finish_reason": finish_reason,
            "cost_usd": seg_cost,
        },
        "validation": validation,
        "raw_content": content,
        "parsed_segment": episode_seg.model_dump() if episode_seg else None,
    }
    with open(args.out, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\nwrote {args.out}")

    if episode_seg:
        print("\n--- prose preview (first 6 turns) ---")
        for t, turn in enumerate(episode_seg.turns[:6]):
            speaker = getattr(turn, "speaker", "?")
            utts = getattr(turn, "utterances", None) or []
            for u in utts:
                txt = getattr(u, "text", "") or ""
                snippet = txt[:240].replace("\n", " ")
                print(f"  [{t}] {speaker}: {snippet}{'...' if len(txt) > 240 else ''}")

    return 0 if validation == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
