"""Run an LLM-judge over the 100 Tier L pairwise presentations.

CAVEATS (read first):

- docs/tier_l_judge_methodology.md (Tier L decision, 2026-05-16) says
  human inspection is primary at this stage. This script is the
  fallback / unblocker: it produces a Potato-shaped TSV by running
  each pair through an out-of-panel LLM judge so the dll8 epic can
  proceed when the human listener isn't available. Human re-run is
  always welcome and will overwrite cleanly.
- Judge model: claude-haiku-4-5. Deliberately OUT of the candidate
  panel (sonnet, gemma-4-31b, deepseek-v3-2, qwen3-235b-a22b,
  gpt-5-4), so within-family bias toward any single candidate is at
  least minimised. Cross-family (Anthropic-vs-non-Anthropic) bias is
  still real and documented — Haiku may systematically lean toward
  Sonnet's prose conventions because it shares training lineage.
- The judge is asked to choose A, B, or tie based purely on prose
  quality (vocabulary, sentence rhythm, intellectual substance,
  character voicing, avoidance of clichés). It does NOT know which
  model produced which side; the blinding manifest is the audit
  key, not visible to the judge.

OUTPUT (Potato TSV shape, matches scripts/score_eval_pairings_potato.py):
  data/eval/stage2_tier_l_prose/potato/annotation_output/annotations.tsv
  columns: instance_id, user_id, preference.selection
  user_id: "claude-haiku-4-5-llm-judge"
  preference.selection: "A" | "B" | "tie / no preference"

Per-pair judge rationale persisted alongside (NOT in the TSV) at
  data/eval/stage2_tier_l_prose/potato/annotation_output/judge_rationales.jsonl
  one line per pair: {pair_id, choice, rationale, ...}
"""
from __future__ import annotations

import csv
import json
import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from enrichment.llm import generate as llm_generate  # noqa: E402
from enrichment.llm import settings  # noqa: E402
from enrichment.llm.types import GenerationRequest, ModelSpec  # noqa: E402

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("judge-eval-pairings-llm")

ROOT = REPO_ROOT / "data" / "eval" / "stage2_tier_l_prose"
PAIRS_JSONL = ROOT / "potato" / "pairs.jsonl"
OUT_DIR = ROOT / "potato" / "annotation_output"
TSV_PATH = OUT_DIR / "annotations.tsv"
RATIONALES_PATH = OUT_DIR / "judge_rationales.jsonl"

JUDGE_TASK = "tier_l_pairwise_judge"
JUDGE_USER_ID = "claude-haiku-4-5-llm-judge"
TIE_LABEL = "tie / no preference"

# Schema for the judge's structured output. JSON schema kept inline so
# this script can run standalone (no Pydantic dance).
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "choice": {
            "type": "string",
            "enum": ["A", "B", "tie"],
            "description": "Which prose sample reads as better, or 'tie' if no preference.",
        },
        "rationale": {
            "type": "string",
            "description": (
                "One- or two-sentence justification: what specifically "
                "made A or B (or neither) better — sentence rhythm, "
                "intellectual substance, character voicing, avoidance "
                "of clichés."
            ),
        },
    },
    "required": ["choice", "rationale"],
    "additionalProperties": False,
}

SYSTEM = """\
You are an experienced literary editor reviewing two AI-generated podcast \
segments from a literary criticism show about Victorian novels. The two \
segments were generated for the same input (same fixture entry, same arc) \
by two different language models. Identifying surface cues (titles, model \
fingerprints) have been stripped — judge only the prose itself.

Criteria, in priority order:
1. Intellectual substance: do the experts make a real argument, or is it \
filler? Are quotes from the novel used to support specific claims rather \
than as decoration?
2. Character voicing: do the experts sound distinct from each other and \
from the host? Is the dialogue believable as a back-and-forth between \
intelligent people who disagree?
3. Prose craft: sentence rhythm, vocabulary range, avoidance of clichés \
("masterpiece", "fog-bound", "labyrinth", "tapestry", "ruthless"), \
avoidance of formulaic transitions.
4. Use of quoted material: are quotes integrated meaningfully or just \
dropped in?

Pick A or B if one is clearly better. Pick 'tie' only if they're \
genuinely close — don't tie just to avoid choosing. Output the choice \
and a one-sentence rationale.
"""

USER_TEMPLATE = """\
## A

{a_text}

---

## B

{b_text}

---

Which is the better podcast segment, A or B? Or tie if they're \
genuinely close. Return your choice and a one-sentence rationale."""


def main() -> None:
    if not PAIRS_JSONL.exists():
        raise SystemExit(
            f"missing {PAIRS_JSONL}. Run scripts/render_eval_pairings_potato.py first."
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Register the judge model with the seam. Haiku is OUT of the
    # candidate panel — chosen deliberately for that reason.
    judge_spec = ModelSpec(
        provider="anthropic",
        model="claude-haiku-4-5-20251001",
        hosting="anthropic",
    )
    settings.register_task(JUDGE_TASK, judge_spec)

    pairs = [json.loads(ln) for ln in PAIRS_JSONL.open() if ln.strip()]
    log.info("Loaded %d pairs from %s", len(pairs), PAIRS_JSONL)

    rationales_fh = RATIONALES_PATH.open("w", encoding="utf-8")
    tsv_fh = TSV_PATH.open("w", newline="", encoding="utf-8")
    writer = csv.DictWriter(
        tsv_fh,
        fieldnames=["instance_id", "user_id", "preference.selection"],
        delimiter="\t",
    )
    writer.writeheader()

    t_start = time.monotonic()
    n_a = n_b = n_tie = n_err = 0
    for i, pair in enumerate(pairs, 1):
        pair_id = pair["id"]
        a_text, b_text = pair["text"]
        user_msg = USER_TEMPLATE.format(a_text=a_text, b_text=b_text)
        try:
            t0 = time.monotonic()
            r = llm_generate(GenerationRequest(
                task=JUDGE_TASK,
                system=SYSTEM,
                user=user_msg,
                max_tokens=400,
                json_schema=JUDGE_SCHEMA,
                temperature=0.0,
            ))
            wall = time.monotonic() - t0
            parsed = json.loads(r.text)
            choice = parsed["choice"]
            rationale = parsed["rationale"]
            if choice == "A":
                tsv_choice = "A"
                n_a += 1
            elif choice == "B":
                tsv_choice = "B"
                n_b += 1
            else:
                tsv_choice = TIE_LABEL
                n_tie += 1
            writer.writerow({
                "instance_id": pair_id,
                "user_id": JUDGE_USER_ID,
                "preference.selection": tsv_choice,
            })
            tsv_fh.flush()
            rationales_fh.write(json.dumps({
                "pair_id": pair_id,
                "choice": choice,
                "rationale": rationale,
                "wall_seconds": wall,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
            }, ensure_ascii=False) + "\n")
            rationales_fh.flush()
            log.info(
                "[%3d/%d] %s -> %s (%.1fs, %s tok)",
                i, len(pairs), pair_id, choice, wall,
                r.output_tokens,
            )
        except Exception as e:  # noqa: BLE001
            n_err += 1
            log.error("[%3d/%d] %s FAILED: %s", i, len(pairs), pair_id, e)
            rationales_fh.write(json.dumps({
                "pair_id": pair_id,
                "error": str(e),
            }) + "\n")
            rationales_fh.flush()

    tsv_fh.close()
    rationales_fh.close()
    elapsed = time.monotonic() - t_start
    log.info(
        "Done in %.1fs. Choices: A=%d B=%d tie=%d errors=%d",
        elapsed, n_a, n_b, n_tie, n_err,
    )
    log.info("TSV         -> %s", TSV_PATH)
    log.info("Rationales  -> %s", RATIONALES_PATH)
    log.info("Now run: uv run python scripts/score_eval_pairings_potato.py")


if __name__ == "__main__":
    main()
