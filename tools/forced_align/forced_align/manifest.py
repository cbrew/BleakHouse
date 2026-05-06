"""Write shards.json (matches rwv schema) and audio/manifest.json
(audio-measured per-turn timing). Both files live alongside the
shards/<profile>/*.mp3 files in <run>/audio/."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from forced_align.boundaries import ShardBoundary


def _md5(path: Path) -> str:
    h = hashlib.md5()
    h.update(path.read_bytes())
    return h.hexdigest()


def write_manifests(
    *,
    audio_dir: Path,
    episode: dict,
    boundaries: list[ShardBoundary],
    profile: str,
) -> None:
    """Write shards.json + manifest.json into audio_dir.

    Assumes the per-shard mp3 files already exist at
    audio_dir/shards/<profile>/{0000,0001,...}.mp3.
    """
    shards_dir = audio_dir / "shards" / profile
    shards_entries: list[dict] = []
    audio_manifest_segments: list[dict] = []
    current_seg_idx: int | None = None
    seg_dict: dict | None = None

    flat_turns: list[tuple[int, int, dict]] = []
    for seg_idx, segment in enumerate(episode.get("segments", [])):
        for turn_idx, turn in enumerate(segment.get("turns", [])):
            flat_turns.append((seg_idx, turn_idx, turn))

    assert len(flat_turns) == len(boundaries), (
        f"boundary count {len(boundaries)} != turn count {len(flat_turns)}"
    )

    for shard_idx, ((seg_idx, turn_idx, turn), boundary) in enumerate(
        zip(flat_turns, boundaries, strict=True)
    ):
        mp3_path = shards_dir / f"{shard_idx:04d}.mp3"
        shards_entries.append({
            "file": f"{shard_idx:04d}.mp3",
            "md5": _md5(mp3_path),
            "kind": "turn",
            "segment_index": seg_idx,
            "turn_index": turn_idx,
            "speaker": turn.get("speaker", ""),
            "role": turn.get("role", ""),
            "utterances": turn.get("utterances", []),
        })

        if seg_idx != current_seg_idx:
            seg_dict = {
                "title": episode["segments"][seg_idx].get("title", ""),
                "segment_type": episode["segments"][seg_idx].get("segment_type", ""),
                "start_ms": int(boundary.start_s * 1000),
                "turns": [],
            }
            audio_manifest_segments.append(seg_dict)
            current_seg_idx = seg_idx
        assert seg_dict is not None
        seg_dict["turns"].append({
            "speaker": turn.get("speaker", ""),
            "role": turn.get("role", ""),
            "start_ms": int(boundary.start_s * 1000),
            "end_ms": int(boundary.end_s * 1000),
            "utterances": turn.get("utterances", []),
        })

    total_duration_ms = (
        int(boundaries[-1].end_s * 1000) if boundaries else 0
    )
    shards_doc = {
        "schema_version": 1,
        "profile": profile,
        "episode_title": episode.get("title", ""),
        "experts": episode.get("experts", []),
        "shards": shards_entries,
    }
    audio_manifest_doc = {
        "title": episode.get("title", ""),
        "experts": episode.get("experts", []),
        "segments": audio_manifest_segments,
        "total_duration_ms": total_duration_ms,
    }

    (audio_dir / "shards.json").write_text(json.dumps(shards_doc, indent=2))
    (audio_dir / "manifest.json").write_text(
        json.dumps(audio_manifest_doc, indent=2)
    )
