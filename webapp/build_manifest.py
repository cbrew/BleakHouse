"""Build timing manifests for the podcast player.

Reads a run's phase3_episode.json, measures cached TTS audio durations,
and writes a manifest.json with per-turn timestamps into the run's audio dir.

Usage:
    uv run python -m webapp.build_manifest --run ext_v01_baseline
    uv run python -m webapp.build_manifest --all
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from enrichment.podcast_types import PodcastEpisode, Turn
from enrichment.render_audio import (
    SPEAKER_VOICES,
    _cache_key,
    _load_cached,
    build_turn_prompt,
)

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def measure_turn_duration_ms(turn: Turn, model_id: str) -> int:
    """Get duration of a turn's audio from the TTS cache."""
    speaker = turn.speaker
    voice_name = SPEAKER_VOICES.get(speaker, "Sulafat")
    prompt = build_turn_prompt(turn)
    cache_key = _cache_key(prompt, voice_name, model_id)
    cached = _load_cached(cache_key)
    if cached is None:
        # Estimate from character count (~15 chars/sec)
        char_count = sum(len(u.text) for u in turn.utterances)
        estimated_ms = int(char_count / 15 * 1000)
        logger.warning(
            "Cache miss for %s turn (%d chars), estimating %dms",
            speaker,
            char_count,
            estimated_ms,
        )
        return estimated_ms
    return len(cached)


def compute_turn_pauses(turn: Turn) -> tuple[int, int]:
    """Compute leading and trailing pause durations matching render_audio logic."""
    leading_ms = 0
    trailing_ms = 0
    first = turn.utterances[0] if turn.utterances else None
    if first and first.pause_before_ms > 0:
        leading_ms = first.pause_before_ms
    last = turn.utterances[-1] if turn.utterances else None
    if last and last.pause_after_ms > 300:
        trailing_ms = last.pause_after_ms - 300
    return leading_ms, trailing_ms


def build_manifest(run_id: str, model_key: str = "flash") -> dict | None:
    """Build a timing manifest for a run."""
    from enrichment.render_audio import MODEL_IDS

    model_id = MODEL_IDS[model_key]
    run_dir = DATA_DIR / "runs" / run_id
    episode_path = run_dir / "phase3_episode.json"
    audio_dir = run_dir / "audio"

    if not episode_path.exists():
        logger.warning("No episode file for run %s", run_id)
        return None
    if not audio_dir.exists():
        logger.warning("No audio dir for run %s", run_id)
        return None

    with open(episode_path) as f:
        episode = PodcastEpisode.model_validate(json.load(f))

    # Load passage data from phase1_assignments
    passages_lookup: dict[str, dict] = {}
    assignments_path = run_dir / "phase1_assignments.json"
    if assignments_path.exists():
        with open(assignments_path) as f:
            raw = json.load(f)
        assignments = raw.get("assignments", raw) if isinstance(raw, dict) else raw
        for p in assignments:
            pid = p.get("passage_id", "")
            if pid:
                passages_lookup[pid] = {
                    "text": p.get("text", ""),
                    "summary": p.get("summary", ""),
                    "best_quote": p.get("best_quote", ""),
                    "chapter_id": p.get("chapter_id", ""),
                    "characters_present": p.get("characters_present", []),
                    "themes": p.get("themes", []),
                    "emotional_register": p.get("emotional_register", []),
                    "narrator": p.get("narrator", ""),
                }

    # Collect unique experts (excluding Host and Narrator)
    experts: list[dict[str, str]] = []
    seen_experts: set[str] = set()
    for seg in episode.segments:
        for turn in seg.turns:
            if turn.speaker not in ("Host", "Narrator") and turn.speaker not in seen_experts:
                seen_experts.add(turn.speaker)
                experts.append({"name": turn.speaker, "role": turn.role})

    cursor_ms = 0
    manifest_segments = []

    for seg_idx, seg in enumerate(episode.segments):
        seg_start_ms = cursor_ms
        manifest_turns = []

        for turn in seg.turns:
            leading_pause, trailing_pause = compute_turn_pauses(turn)
            cursor_ms += leading_pause

            audio_duration = measure_turn_duration_ms(turn, model_id)
            turn_start = cursor_ms
            cursor_ms += audio_duration
            cursor_ms += trailing_pause
            turn_end = cursor_ms

            manifest_turns.append({
                "speaker": turn.speaker,
                "role": turn.role,
                "start_ms": turn_start,
                "end_ms": turn_end,
                "utterances": [
                    {
                        "text": u.text,
                        "sentence_type": u.sentence_type.value,
                        "is_quote": u.is_quote,
                        "quote_mode": u.quote_mode,
                        "passage_ref": u.passage_ref,
                    }
                    for u in turn.utterances
                ],
            })

        manifest_segments.append({
            "title": seg.title,
            "segment_type": seg.segment_type,
            "start_ms": seg_start_ms,
            "turns": manifest_turns,
        })

        # Segment break: 2000ms silence between segments
        if seg_idx < len(episode.segments) - 1:
            cursor_ms += 2000

    # Filter passages to only those actually referenced in the episode
    referenced_passages: dict[str, dict] = {}
    for seg in manifest_segments:
        for turn in seg["turns"]:
            for utt in turn["utterances"]:
                ref = utt.get("passage_ref", "")
                if ref and ref in passages_lookup and ref not in referenced_passages:
                    referenced_passages[ref] = passages_lookup[ref]

    manifest = {
        "run_id": run_id,
        "title": episode.title,
        "experts": experts,
        "segments": manifest_segments,
        "passages": referenced_passages,
        "total_duration_ms": cursor_ms,
    }

    out_path = audio_dir / "manifest.json"
    with open(out_path, "w") as f:
        json.dump(manifest, f, indent=2)
    logger.info("Wrote manifest for %s: %d segments, %.1f min total",
                run_id, len(manifest_segments), cursor_ms / 60000)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build timing manifests for podcast player")
    parser.add_argument("--run", help="Run ID to build manifest for")
    parser.add_argument("--all", action="store_true", help="Build manifests for all runs with audio")
    parser.add_argument("--model", choices=["flash", "pro"], default="flash")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")

    if args.all:
        runs_dir = DATA_DIR / "runs"
        for run_dir in sorted(runs_dir.iterdir()):
            if (run_dir / "audio").exists() and (run_dir / "phase3_episode.json").exists():
                build_manifest(run_dir.name, args.model)
    elif args.run:
        build_manifest(args.run, args.model)
    else:
        parser.error("Specify --run or --all")


if __name__ == "__main__":
    main()
