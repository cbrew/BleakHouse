"""CLI entry point for the forced-alignment migration."""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

from forced_align.align import align_transcript
from forced_align.boundaries import compute_boundaries
from forced_align.manifest import write_manifests
from forced_align.slicer import slice_mp3
from forced_align.transcript import parse_episode

logger = logging.getLogger(__name__)


def _ffprobe_duration(path: Path) -> float:
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(path),
    ]).decode().strip()
    return float(out)


def process_run(data_dir: Path, run_id: str, *, force: bool = False) -> int:
    run_dir = data_dir / "runs" / run_id
    audio_dir = run_dir / "audio"
    podcast = audio_dir / "podcast.mp3"
    episode_path = run_dir / "phase3_episode.json"
    shards_json = audio_dir / "shards.json"

    if not podcast.exists():
        logger.error("%s: no podcast.mp3", run_id)
        return 1
    if not episode_path.exists():
        logger.error("%s: no phase3_episode.json", run_id)
        return 1
    if shards_json.exists() and not force:
        logger.warning("%s: shards.json already exists (use --force)", run_id)
        return 0

    episode = json.loads(episode_path.read_text())
    words, turn_ranges = parse_episode(episode)
    logger.info("%s: %d words across %d turns", run_id, len(words), len(turn_ranges))

    try:
        aligned = align_transcript(podcast, words)
    except Exception as exc:  # noqa: BLE001
        logger.exception("%s: alignment failed", run_id)
        (audio_dir / "align_error.txt").write_text(repr(exc))
        return 1

    duration_s = _ffprobe_duration(podcast)
    try:
        boundaries = compute_boundaries(aligned, turn_ranges, duration_s)
    except ValueError as exc:
        logger.error("%s: boundary computation failed: %s", run_id, exc)
        (audio_dir / "align_error.txt").write_text(str(exc))
        return 1

    shards_dir = audio_dir / "shards" / "classic"
    if shards_dir.exists() and force:
        for old in shards_dir.glob("*.mp3"):
            old.unlink()
    shards_dir.mkdir(parents=True, exist_ok=True)
    for i, b in enumerate(boundaries):
        if b.end_s <= b.start_s:
            # Empty turn — emit a tiny ~26ms slice so shards.json md5 has a file.
            slice_mp3(podcast, shards_dir / f"{i:04d}.mp3",
                      start_s=max(0.0, b.start_s - 0.013),
                      end_s=min(duration_s, b.start_s + 0.013))
        else:
            slice_mp3(podcast, shards_dir / f"{i:04d}.mp3",
                      start_s=b.start_s, end_s=b.end_s)

    write_manifests(audio_dir=audio_dir, episode=episode,
                    boundaries=boundaries, profile="classic")
    logger.info("%s: wrote %d shards", run_id, len(boundaries))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="forced_align")
    parser.add_argument("--run", help="single run id")
    parser.add_argument("--all", action="store_true",
                        help="process every run with podcast.mp3 and no shards.json")
    parser.add_argument("--force", action="store_true",
                        help="overwrite existing shards.json")
    parser.add_argument("--data-dir", type=Path, default=Path("data"),
                        help="root data directory")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
    )

    if not args.run and not args.all:
        parser.error("specify --run <id> or --all")

    if args.run:
        return process_run(args.data_dir, args.run, force=args.force)

    runs_root = args.data_dir / "runs"
    targets = []
    for run_dir in sorted(runs_root.iterdir()):
        if not run_dir.is_dir():
            continue
        if not (run_dir / "audio" / "podcast.mp3").exists():
            continue
        if (run_dir / "audio" / "shards.json").exists() and not args.force:
            continue
        targets.append(run_dir.name)
    logger.info("processing %d runs", len(targets))
    failures = []
    for run_id in targets:
        rc = process_run(args.data_dir, run_id, force=args.force)
        if rc != 0:
            failures.append(run_id)
    if failures:
        logger.error("failed runs: %s", failures)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
