"""Build manifests for the podcast player and script reader.

Reads a run's phase3_episode.json, optionally measures cached TTS audio
durations, and writes a manifest.json with passage backlinks.

Usage:
    uv run python -m webapp.build_manifest --run ext_v01_baseline
    uv run python -m webapp.build_manifest --all          # audio runs only
    uv run python -m webapp.build_manifest --all --no-audio  # all runs
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from enrichment.podcast_types import PodcastEpisode, Turn

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

# Novel title (as it appears in episode JSON, minus ": A Literary Discussion")
# → relative path under data/ to passages_enriched.json
_NOVEL_DIRS: dict[str, str] = {
    "Bleak House": "",
    "Our Mutual Friend": "novels/our_mutual_friend",
    "The Mill on the Floss": "novels/mill_on_the_floss",
    "North and South": "novels/north_and_south",
    "A Passage to India": "novels/passage_to_india",
    "Hard Times": "novels/hard_times",
    "Middlemarch": "novels/middlemarch",
    "Daniel Deronda": "novels/daniel_deronda",
    "David Copperfield": "novels/david_copperfield",
    "Cranford": "novels/cranford",
    "No Name": "novels/no_name",
    "New Grub Street": "novels/new_grub_street",
    "The Odd Women": "novels/odd_women",
    "Miss Marjoribanks": "novels/miss_marjoribanks",
    "Hester": "novels/hester",
}


def _load_enriched_passages(novel_title: str) -> list[dict]:
    """Load all enriched passages for a novel."""
    novel_key = novel_title.replace(": A Literary Discussion", "")
    subdir = _NOVEL_DIRS.get(novel_key, "")
    if subdir:
        path = DATA_DIR / subdir / "passages_enriched.json"
    else:
        path = DATA_DIR / "passages_enriched.json"
    if not path.exists():
        return []
    with open(path) as f:
        raw = json.load(f)
    return raw


def _extract_segment_keywords(turns: list[dict]) -> set[str]:
    """Extract character names and thematic keywords from a segment's turns."""
    words: set[str] = set()
    for turn in turns:
        for utt in turn["utterances"]:
            # Extract capitalised words as potential character/place names
            for word in utt["text"].split():
                cleaned = word.strip(".,;:!?\"'—()[]")
                if cleaned and cleaned[0].isupper() and len(cleaned) > 2:
                    words.add(cleaned.lower())
    return words


def _score_passage_relevance(passage: dict, segment_keywords: set[str]) -> float:
    """Score how relevant an enriched passage is to a segment's discussion."""
    enrichment = passage.get("enrichment", {})
    if not enrichment:
        return 0.0

    score = 0.0

    # Interest score (0-5) contributes directly
    interest = enrichment.get("interest_score") or 0
    score += interest * 2

    # Character overlap
    chars = {c.lower() for c in (enrichment.get("characters_present") or [])}
    char_overlap = len(chars & segment_keywords)
    score += char_overlap * 3

    # Theme overlap
    themes = {t.lower() for t in (enrichment.get("themes") or [])}
    theme_overlap = len(themes & segment_keywords)
    score += theme_overlap * 2

    return score


def find_suggested_passages(
    manifest_segments: list[dict],
    novel_title: str,
    max_per_segment: int = 3,
) -> dict[str, dict]:
    """For no-passages runs, find closest enriched passages per segment."""
    enriched = _load_enriched_passages(novel_title)
    if not enriched:
        return {}

    suggested: dict[str, dict] = {}

    for seg in manifest_segments:
        keywords = _extract_segment_keywords(seg["turns"])
        if not keywords:
            continue

        scored = []
        for p in enriched:
            rel = _score_passage_relevance(p, keywords)
            if rel > 0:
                scored.append((rel, p))
        scored.sort(key=lambda x: -x[0])

        for rel_score, p in scored[:max_per_segment]:
            pid = p["passage_id"]
            if pid in suggested:
                continue
            e = p.get("enrichment", {})
            suggested[pid] = {
                "text": p.get("text", ""),
                "summary": e.get("summary", ""),
                "best_quote": e.get("best_quote", ""),
                "chapter_id": p.get("chapter_id", ""),
                "characters_present": e.get("characters_present", []),
                "themes": e.get("themes", []),
                "emotional_register": e.get("emotional_register", []),
                "narrator": e.get("narrator", ""),
                "suggested": True,
                "relevance_score": round(rel_score, 1),
            }

    return suggested


def measure_turn_duration_ms(turn: Turn, model_id: str) -> int:
    """Get duration of a turn's audio from the TTS cache."""
    from enrichment.render_audio import (
        SPEAKER_VOICES,
        _cache_key,
        _load_cached,
        build_turn_prompt,
    )

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


def estimate_turn_duration_ms(turn: Turn) -> int:
    """Estimate duration from character count (~15 chars/sec)."""
    char_count = sum(len(u.text) for u in turn.utterances)
    return int(char_count / 15 * 1000)


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


def build_manifest(run_id: str, model_key: str = "flash", audio: bool = True) -> dict | None:
    """Build a manifest for a run.

    When audio=True (default), measures real TTS durations and writes to
    {run_dir}/audio/manifest.json.  When audio=False, estimates durations
    from character counts and writes to {run_dir}/manifest.json.
    """
    run_dir = DATA_DIR / "runs" / run_id
    episode_path = run_dir / "phase3_episode.json"

    if not episode_path.exists():
        logger.warning("No episode file for run %s", run_id)
        return None

    if audio:
        audio_dir = run_dir / "audio"
        if not audio_dir.exists():
            logger.warning("No audio dir for run %s", run_id)
            return None
        from enrichment.render_audio import MODEL_IDS
        model_id = MODEL_IDS[model_key]

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

            if audio:
                turn_duration = measure_turn_duration_ms(turn, model_id)  # pyright: ignore[reportPossiblyUnbound]
            else:
                turn_duration = estimate_turn_duration_ms(turn)
            turn_start = cursor_ms
            cursor_ms += turn_duration
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

    # Determine passage source type
    has_refs = any(
        utt.get("passage_ref")
        for seg in manifest_segments for turn in seg["turns"] for utt in turn["utterances"]
    )
    if passages_lookup and has_refs:
        passage_source = "grounded"
    elif passages_lookup:
        passage_source = "grounded"  # has assignments but refs may be sparse
    else:
        passage_source = "ungrounded"

    # For ungrounded runs, match quotes against the novel's passages
    if passage_source == "ungrounded":
        from webapp.match_passages import load_enriched_passages, match_episode_quotes

        enriched = load_enriched_passages(episode.title)
        if enriched:
            ep_dict = {"segments": manifest_segments}
            results = match_episode_quotes(ep_dict, enriched)

            referenced_passages.update(results["matched_passages"])

            for si, ti, ui, pid, ratio, category, autopsy in results["utterance_matches"]:
                utt = manifest_segments[si]["turns"][ti]["utterances"][ui]
                if pid:
                    utt["passage_ref"] = pid
                utt["match_ratio"] = round(ratio, 3)
                utt["match_category"] = category
                if autopsy:
                    utt["autopsy"] = autopsy

            cats = {}
            for _, _, _, _, _, c, _ in results["utterance_matches"]:
                cats[c] = cats.get(c, 0) + 1
            total = len(results["utterance_matches"])
            parts = [f"{cats.get(c, 0)} {c}" for c in
                     ["verified", "paraphrase", "distant_echo", "no_clear_source", "invented"]
                     if cats.get(c, 0) > 0]
            logger.info("  Quote matching for %s: %s (of %d quotes)",
                        run_id, ", ".join(parts), total)

    # For ungrounded runs, also add suggested passages per segment
    if passage_source == "ungrounded":
        suggested = find_suggested_passages(manifest_segments, episode.title)
        referenced_passages.update(suggested)

    # Load host preparation data if available
    host_prep = None
    briefs_path = run_dir / "phase2_5_host_briefs.json"
    interviews_path = run_dir / "phase2_5_interviews.json"
    if briefs_path.exists():
        with open(briefs_path) as f:
            briefs_data = json.load(f)
        interviews_data = None
        if interviews_path.exists():
            with open(interviews_path) as f:
                interviews_data = json.load(f)
        host_prep = {
            "briefs": briefs_data,
            "interviews": interviews_data,
        }

    manifest = {
        "run_id": run_id,
        "title": episode.title,
        "experts": experts,
        "segments": manifest_segments,
        "passages": referenced_passages,
        "passage_source": passage_source,
        "has_audio": audio,
        "total_duration_ms": cursor_ms,
    }
    if host_prep:
        manifest["host_prep"] = host_prep

    if audio:
        out_path = run_dir / "audio" / "manifest.json"
    else:
        out_path = run_dir / "manifest.json"
    with open(out_path, "w") as f:
        json.dump(manifest, f, indent=2)
    logger.info("Wrote manifest for %s: %d segments, %s",
                run_id, len(manifest_segments),
                f"{cursor_ms / 60000:.1f} min" if audio else "no audio")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build manifests for podcast player / script reader")
    parser.add_argument("--run", help="Run ID to build manifest for")
    parser.add_argument("--all", action="store_true", help="Build manifests for all runs")
    parser.add_argument("--no-audio", action="store_true", help="Build without audio timing (for all runs)")
    parser.add_argument("--model", choices=["flash", "pro"], default="flash")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")

    if args.all:
        runs_dir = DATA_DIR / "runs"
        for run_dir in sorted(runs_dir.iterdir()):
            if not (run_dir / "phase3_episode.json").exists():
                continue
            if args.no_audio:
                # Skip if manifest already exists
                if (run_dir / "manifest.json").exists():
                    continue
                build_manifest(run_dir.name, args.model, audio=False)
            else:
                if (run_dir / "audio").exists():
                    build_manifest(run_dir.name, args.model, audio=True)
    elif args.run:
        build_manifest(args.run, args.model, audio=not args.no_audio)
    else:
        parser.error("Specify --run or --all")


if __name__ == "__main__":
    main()
