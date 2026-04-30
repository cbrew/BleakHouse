"""LLM-derive a teaser line per podcast episode for the Recommended view.

A teaser is a 1-2 sentence pull or close paraphrase from the actual script
that gives a listener a taste of what's distinctive about *this* discussion
— a host's framing, an expert's pointed take, a moment of friction. It's
shown on the per-(novel, panel) card at /script-versions.

Output schema lives in `EpisodeTeaser` below; the canonical pattern for
Anthropic structured output is `output_config={"format": {"type":
"json_schema", "schema": ...}}`. See enrichment/test_single.py.

Cached on disk at data/runs/<run>/phase3_teaser.json. Re-run when missing
or stale relative to phase3_episode.json.

Usage:
    uv run python -m webapp.build_teasers --run bh_trn_literary_hostprep
    uv run python -m webapp.build_teasers --all       # rebuild every recommended cell
    uv run python -m webapp.build_teasers --all --force   # ignore cache
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

load_dotenv()

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
MODEL = "claude-sonnet-4-5"
TEASER_FILENAME = "phase3_teaser.json"


class EpisodeTeaser(BaseModel):
    """One pulled-from-script teaser line for the episode card."""

    model_config = ConfigDict(json_schema_extra={"additionalProperties": False})

    teaser: str = Field(
        description=(
            "One or two sentences (max ~40 words) drawn from the script — "
            "a quote or close paraphrase. The line should be specific to "
            "this discussion, witty or pointed, and stand alone without "
            "plot spoilers. No filler like 'this episode explores …'."
        )
    )
    speaker: str = Field(
        description=(
            "The speaker the teaser is drawn from: 'Host', or an expert "
            "name like 'Eleanor Hartley'. Use the exact speaker label "
            "from the script."
        )
    )
    source: str = Field(
        description=(
            "How the teaser relates to the script: 'verbatim' if it's a "
            "direct quote, 'paraphrase' if it's a tightening of what was "
            "said. Always anchored to a real moment."
        )
    )


SYSTEM_PROMPT = """\
You are writing the teaser line for a podcast episode card. You will
receive a transcript of a literary podcast discussion. Pick the single
most evocative moment — a host's framing, an expert's pointed take, a
beat of disagreement — and turn it into a 1-2 sentence teaser.

Rules:
- Quote verbatim where possible. If the line is too long, paraphrase
  while keeping the speaker's voice and exact stance.
- Specific to *this* episode. Avoid generic literary description
  ("Bleak House is a sprawling indictment of …"); pick something only
  this discussion would say.
- No plot spoilers. Hooks should make a listener curious without
  giving away revelations.
- No filler ("this episode explores", "join us as …"). Drop straight
  into the moment.
- Plain text. No markdown, no leading/trailing quotes.
"""


def script_to_text(episode: dict, max_chars: int = 80_000) -> str:
    """Flatten a phase3_episode.json into plain text for the LLM."""
    parts: list[str] = []
    title = episode.get("title", "")
    if title:
        parts.append(f"Episode title: {title}\n")
    for seg in episode.get("segments", []):
        parts.append(f"\n=== {seg.get('title', 'Segment')} ===\n")
        for turn in seg.get("turns", []):
            speaker = turn.get("speaker", "")
            text = " ".join(u.get("text", "") for u in turn.get("utterances", []))
            if not text.strip():
                continue
            parts.append(f"{speaker}: {text}\n")
    out = "".join(parts)
    if len(out) > max_chars:
        out = out[:max_chars] + "\n\n[truncated]"
    return out


def build_teaser(run_id: str, force: bool = False) -> EpisodeTeaser | None:
    """Derive and cache a teaser for one run. Returns the teaser or None on
    failure (no episode, API error, etc.)."""
    run_dir = DATA_DIR / "runs" / run_id
    episode_path = run_dir / "phase3_episode.json"
    teaser_path = run_dir / TEASER_FILENAME

    if not episode_path.exists():
        logger.warning("No phase3_episode.json for %s", run_id)
        return None

    if teaser_path.exists() and not force:
        ep_mtime = episode_path.stat().st_mtime
        teaser_mtime = teaser_path.stat().st_mtime
        if teaser_mtime >= ep_mtime:
            with open(teaser_path) as f:
                return EpisodeTeaser.model_validate_json(f.read())

    with open(episode_path) as f:
        episode = json.load(f)
    script_text = script_to_text(episode)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    schema = EpisodeTeaser.model_json_schema()

    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        output_config={"format": {"type": "json_schema", "schema": schema}},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": script_text}],
    )

    block = response.content[0]
    assert block.type == "text"
    teaser = EpisodeTeaser.model_validate_json(block.text)

    teaser_path.write_text(teaser.model_dump_json(indent=2))
    logger.info("teaser[%s] %s: %s", run_id, teaser.speaker, teaser.teaser[:80])
    return teaser


def all_recommended_runs() -> list[str]:
    """The set of run-ids that the curated /tracker/versions endpoint surfaces."""
    from webapp.db_views import matrix_rows  # noqa: PLC0415  pyright: ignore[reportMissingImports]
    from enrichment import axes  # noqa: PLC0415  pyright: ignore[reportMissingImports]

    out: list[str] = []
    for r in matrix_rows():
        if r["pipeline"] != "trn" or not r["hostprep"]:
            continue
        if not r.get("ref_tools"):
            continue
        if r["generator"] != axes.DEFAULT_GENERATOR:
            continue
        if (DATA_DIR / "runs" / r["run_id"]).exists():
            out.append(r["run_id"])
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", help="Single run-id to (re)build teaser for")
    g.add_argument("--all", action="store_true", help="Rebuild for every recommended-cell run")
    parser.add_argument("--force", action="store_true", help="Ignore cache and re-call the LLM")
    args = parser.parse_args()

    if args.run:
        runs = [args.run]
    else:
        runs = all_recommended_runs()
        logger.info("Building teasers for %d recommended runs", len(runs))

    ok = fail = cached = 0
    for rid in runs:
        teaser_path = DATA_DIR / "runs" / rid / TEASER_FILENAME
        was_cached = teaser_path.exists() and not args.force
        try:
            t = build_teaser(rid, force=args.force)
            if t is None:
                fail += 1
            elif was_cached:
                cached += 1
            else:
                ok += 1
        except Exception:  # noqa: BLE001
            logger.exception("teaser failed for %s", rid)
            fail += 1
        # Tiny cooldown to be polite under bursts.
        time.sleep(0.2)

    logger.info("done: %d new, %d cached, %d failed", ok, cached, fail)


if __name__ == "__main__":
    main()
