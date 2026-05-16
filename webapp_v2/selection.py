"""Canonical-run picker for the v2 consumer view.

For each (novel, panel, generator) coordinate, pick exactly one run
with audio. The ranking carries forward the policy from
webapp/consumer.py:_rank_key plus a short-preferred-over-long key
(the user-invisible 'length' axis). Returns one Episode per
(novel, panel, generator) bucket; coordinates with no audio-bearing
run are dropped.

The bucket includes `generator` so each provider's take on a
(novel, panel) gets its own front-page card — Sonnet, gpt-5.4,
cerebras_qwen, etc. all surface independently if they have audio.
The audio gate is the only hard cut; everything else is preference.
"""
from __future__ import annotations

from dataclasses import dataclass

from webapp_v2.content import RunIndex, _connection

# Pipeline preference. Lower wins. Mirrors consumer.py:_PIPELINE_RANK so
# v1 and v2 surface the same canonical run for any (novel, panel) until
# we deliberately diverge.
_PIPELINE_RANK_SQL = (
    "CASE pipeline "
    "  WHEN 'transport' THEN 0 "
    "  WHEN 'embedding' THEN 1 "
    "  WHEN 'rag'       THEN 1 "
    "  WHEN 'no_passages' THEN 2 "
    "  ELSE 9 "
    "END"
)

_SELECT_BEST_PER_BUCKET = f"""
SELECT * FROM run_index
WHERE has_audio = 1
  AND panel IN ('literary', 'alternatives', 'interdisciplinary')
ORDER BY
  novel,
  panel,
  CASE length WHEN 'short' THEN 0 ELSE 1 END,
  {_PIPELINE_RANK_SQL},
  CASE hostprep WHEN 1 THEN 0 ELSE 1 END,
  CASE ref_tools WHEN 1 THEN 0 ELSE 1 END,
  run_id DESC
"""


@dataclass(frozen=True)
class Episode:
    """Canonical run surfaced on the consumer landing page."""
    novel: str
    panel: str
    run_id: str
    pipeline: str
    length: str
    hostprep: bool
    ref_tools: bool
    generator: str


def _row_to_episode(row: RunIndex) -> Episode:
    return Episode(
        novel=row.novel,
        panel=row.panel,
        run_id=row.run_id,
        pipeline=row.pipeline,
        length=row.length,
        hostprep=row.hostprep,
        ref_tools=row.ref_tools,
        generator=row.generator,
    )


def list_canonical_episodes() -> list[Episode]:
    """Return one Episode per (novel, panel, generator) triple with audio.

    Picks the best run per bucket per the ranking rule (short > long;
    transport > embedding/rag > no_passages; hostprep yes > no;
    ref_tools yes > no; tiebreak by run_id descending — stable across
    rebuilds). Coordinates with zero audio-bearing runs are absent.
    """
    seen: set[tuple[str, str, str]] = set()
    out: list[Episode] = []
    for row in _connection().execute(_SELECT_BEST_PER_BUCKET):
        key = (row["novel"], row["panel"], row["generator"])
        if key in seen:
            continue
        seen.add(key)
        out.append(Episode(
            novel=row["novel"],
            panel=row["panel"],
            run_id=row["run_id"],
            pipeline=row["pipeline"],
            length=row["length"],
            hostprep=bool(row["hostprep"]),
            ref_tools=bool(row["ref_tools"]),
            generator=row["generator"],
        ))
    return out


def canonical_run_for(
    novel: str, panel: str, generator: str | None = None,
) -> Episode | None:
    """Return the canonical Episode for (novel, panel[, generator]).

    When `generator` is given, picks the best run for that specific
    generator (e.g. 'openai_5_4'). When omitted, picks the best run
    across all generators with audio — preserving back-compat with the
    legacy /listen/{novel}/{panel} URL shape, where the default-Sonnet
    run wins under the ranking and ties go to run_id-desc."""
    for ep in list_canonical_episodes():
        if ep.novel != novel or ep.panel != panel:
            continue
        if generator is not None and ep.generator != generator:
            continue
        return ep
    return None
