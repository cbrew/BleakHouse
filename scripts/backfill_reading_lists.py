"""Generate reading lists for runs that have a script but no host-prep stage.

Background: only ~33 of our ~220 runs went through the Phase 2.5 host-prep
flow that builds `phase2_5_reading_list.json`. The rest (mostly embedding
and no-passages runs) ship with no reading list, so /report shows nothing
to follow up on. This script generates a reading list per (novel, panel)
group and writes it into every sibling run dir, so all 187 missing runs
get a reasonable list of references without re-running host-prep.

Approach (per group):
  1. Read the representative run's phase3_episode.json (segment titles).
  2. Run a single Sonnet tool-loop with search_openalex / search_wikipedia
     / read_wikipedia_article. Prompt the model to assemble ~15-20 listener-
     accessible references that engage the topics raised in the episode.
  3. Run the same Haiku-based listener-pick winnower used in host-prep so
     the report's "Recommended for listeners" subset is meaningful.
  4. Build a phase2_5_reading_list.json payload with the canonical schema
     (`entries`, `recommended`, `proposed_by_segment`, `stats`, ...).
  5. Write that file into every run dir in the group (representative + 5
     siblings).

Idempotent: skips groups where every member already has a reading list.

Usage:
    uv run python scripts/backfill_reading_lists.py            # all groups
    uv run python scripts/backfill_reading_lists.py --dry-run  # report only
    uv run python scripts/backfill_reading_lists.py --novel mdal --panel literary
    uv run python scripts/backfill_reading_lists.py --limit 1
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from collections import defaultdict
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from enrichment import axes
from enrichment.host_prep import _select_listener_recommendations
from enrichment.reference_tools import (
    ALL_TOOLS,
    CitationRecord,
    CitationRegistry,
    dispatch_tool,
)
from enrichment.timing import Recorder, time_model

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
RUNS_DIR = DATA_DIR / "runs"

GENERATOR_MODEL = "claude-sonnet-4-6"
WINNOWER_MODEL = "claude-haiku-4-5-20251001"
MAX_TOOL_CALLS = 12  # per group; the host-prep loop uses 6 per segment, but
                    # we're covering a whole episode in one loop here.

PANEL_LABELS = {
    "literary": "literary critics",
    "interdisciplinary": "interdisciplinary scholars (NLP, astrophysics, music)",
    "alternatives": "alternative-canon readers",
}


_SYSTEM = """\
You are preparing a listener-focused reading list for a podcast episode \
about "{novel_title}" by {novel_author}. The discussion was led by {panel_label}.

You have three search tools.
- `search_openalex` for scholarly works (articles, books, theses).
- `search_wikipedia` for canonical works, named events, biographies, \
historical context.
- `read_wikipedia_article` to dig deeper into a specific Wikipedia result.

Build a reading list of 12-20 references that listeners — interested but \
non-specialist — could read next. Aim for a mix of scholarly anchors \
and accessible introductions; balance literary criticism with social, \
historical, or biographical context where relevant. Prefer well-cited or \
canonical pieces over obscure single-citation papers.

When you are done searching, stop. The references you've registered via \
search tools become the candidate set; you don't need to repeat them.
"""


_USER = """\
The episode covered these segments:

{segment_block}

Search for references that engage the topics raised. End with a brief \
sentence noting which themes you tried to cover (no JSON, just prose).
"""


def _segments_block(episode: dict) -> str:
    out: list[str] = []
    for s in episode.get("segments", []) or []:
        title = s.get("title", "")
        st = s.get("segment_type", "")
        out.append(f"- [{st}] {title}" if st else f"- {title}")
    return "\n".join(out) or "- (no segments listed)"


def _run_tool_loop(
    client: anthropic.Anthropic,
    novel_title: str,
    novel_author: str,
    panel_label: str,
    segment_block: str,
    recorder: Recorder,
) -> CitationRegistry:
    registry = CitationRegistry()
    system = _SYSTEM.format(
        novel_title=novel_title,
        novel_author=novel_author,
        panel_label=panel_label,
    )
    messages: list = [
        {"role": "user", "content": _USER.format(segment_block=segment_block)}
    ]

    for _ in range(MAX_TOOL_CALLS + 1):
        response = time_model(
            recorder, "backfill_loop_turn",
            lambda: client.messages.create(
                model=GENERATOR_MODEL,
                max_tokens=4096,
                system=system,
                messages=messages,
                tools=ALL_TOOLS,
            ),
        )
        if response.stop_reason != "tool_use":
            break
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result_text = dispatch_tool(
                    block.name, block.input, registry, client, recorder,
                )
                arg = block.input.get("query") or block.input.get("ref_tag") or ""
                logger.info(
                    "    Tool %s(%s): %d chars",
                    block.name, str(arg)[:50], len(result_text),
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                })
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})
    return registry


def _build_payload(
    novel_title: str,
    novel_author: str,
    segment_block: str,
    registry: CitationRegistry,
    recommended_tags: list[str],
) -> dict:
    entries: list[dict] = registry.to_dicts()
    rec_set = set(recommended_tags)
    recommended = [e for e in entries if e.get("tag") in rec_set]
    by_source: dict[str, int] = defaultdict(int)
    for e in entries:
        by_source[e.get("source", "?")] += 1

    return {
        "schema_version": 2,
        "novel_title": novel_title,
        "novel_author": novel_author,
        "models": {"interview": GENERATOR_MODEL, "enrich": WINNOWER_MODEL},
        "entries": entries,
        # No per-segment provenance for the backfill — one shared list
        # per (novel, panel) group, not per-segment expert pre-interviews.
        "proposed_by_segment": {},
        "recommended": recommended,
        "stats": {
            "total_entries": len(entries),
            "by_source": dict(by_source),
            "total_proposed_tags": len(entries),
        },
        "total_proposed": len(entries),
        "total_verified": len(entries),
        "verification_rate": 1.0 if entries else 0.0,
        "_backfill": {
            "source": "scripts/backfill_reading_lists.py",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "generator_model": GENERATOR_MODEL,
            "winnower_model": WINNOWER_MODEL,
            "segment_block": segment_block,
        },
    }


def _representative(group_runs: list[Path]) -> Path:
    """Pick a representative run for a group: prefer transport+hostprep,
    then any transport, then any with hostprep, then anything."""
    def key(p: Path) -> tuple[int, str]:
        cfg = p / "config.json"
        try:
            ax = (json.loads(cfg.read_text()).get("axes") or {}) if cfg.exists() else {}
        except Exception:
            ax = {}
        score = 0
        if ax.get("pipeline") == "trn":
            score += 2
        if ax.get("hostprep"):
            score += 1
        return (-score, p.name)
    return sorted(group_runs, key=key)[0]


def _group_runs() -> dict[tuple[str, str], list[Path]]:
    """Discover runs missing a reading list, grouped by (novel, panel)."""
    groups: dict[tuple[str, str], list[Path]] = defaultdict(list)
    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir():
            continue
        if not (run_dir / "phase3_episode.json").exists():
            continue
        if (run_dir / "phase2_5_reading_list.json").exists():
            continue
        cfg = run_dir / "config.json"
        if not cfg.exists():
            continue
        try:
            ax = (json.loads(cfg.read_text()).get("axes") or {})
        except Exception:
            continue
        novel = ax.get("novel")
        panel = ax.get("panel")
        if not novel or not panel:
            continue
        groups[(novel, panel)].append(run_dir)
    return groups


def backfill_group(
    client: anthropic.Anthropic | None,
    novel_key: str,
    panel: str,
    runs: list[Path],
    *,
    dry_run: bool,
) -> None:
    novel = axes.NOVEL_BY_KEY.get(novel_key)
    if novel is None:
        logger.warning("Skip group (%s, %s): novel %r not in NOVEL_BY_KEY",
                       novel_key, panel, novel_key)
        return
    panel_label = PANEL_LABELS.get(panel, panel)

    rep = _representative(runs)
    episode_path = rep / "phase3_episode.json"
    try:
        episode = json.loads(episode_path.read_text())
    except Exception as exc:
        logger.warning("Skip group (%s, %s): cannot read %s: %s",
                       novel_key, panel, episode_path, exc)
        return
    segment_block = _segments_block(episode)

    logger.info(
        "Group (%s, %s): %d runs, representative=%s",
        novel_key, panel, len(runs), rep.name,
    )

    if dry_run or client is None:
        logger.info("  DRY RUN — would generate from %s and write to %d runs",
                    rep.name, len(runs))
        return

    recorder = Recorder()
    registry = _run_tool_loop(
        client,
        novel_title=novel.title,
        novel_author=novel.author,
        panel_label=panel_label,
        segment_block=segment_block,
        recorder=recorder,
    )

    candidates: list[CitationRecord] = registry.all()
    if not candidates:
        logger.warning("  No references collected; skipping group")
        return

    recommended_tags = _select_listener_recommendations(
        candidates, novel.title, novel.author, recorder=recorder,
    )

    payload = _build_payload(
        novel.title, novel.author, segment_block, registry, recommended_tags,
    )

    for run_dir in runs:
        out = run_dir / "phase2_5_reading_list.json"
        if out.exists():
            logger.info("  %s: already has reading list — skip", run_dir.name)
            continue
        out.write_text(json.dumps(payload, indent=2))
        logger.info(
            "  %s: wrote %d entries (%d recommended)",
            run_dir.name, len(payload["entries"]), len(payload["recommended"]),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be generated; no API calls.")
    parser.add_argument("--novel", help="Restrict to a single novel key.")
    parser.add_argument("--panel", help="Restrict to a single panel id.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only process the first N groups (after filters).")
    args = parser.parse_args()

    load_dotenv()

    groups = _group_runs()
    if args.novel or args.panel:
        groups = {
            k: v for k, v in groups.items()
            if (args.novel is None or k[0] == args.novel)
            and (args.panel is None or k[1] == args.panel)
        }
    items = sorted(groups.items())
    if args.limit:
        items = items[: args.limit]

    n_runs_covered = sum(len(v) for _, v in items)
    logger.info(
        "Plan: %d groups, %d runs without reading lists (avg %.1f runs/group)",
        len(items), n_runs_covered,
        n_runs_covered / len(items) if items else 0,
    )
    if not items:
        return

    if args.dry_run:
        client = None
    else:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    for (novel_key, panel), runs in items:
        backfill_group(client, novel_key, panel, runs, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
