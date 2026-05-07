"""Write shards.json (matches rwv schema) and audio/manifest.json
(audio-measured per-turn timing). Both files live alongside the
shards/<profile>/*.mp3 files in <run>/audio/."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from forced_align.boundaries import ShardBoundary

# forced_align is a separate uv subproject and cannot import the
# bleak-house top-level `cas` package without dragging in its full
# transitive dep set (anthropic, lancedb, pydub, etc). The CAS layout
# is just 3 lines, so we mirror cas.store.put inline here. Keep this
# in lockstep with cas/store.py (FIPS-safe md5, same path shape).


def _cas_root(repo_root: Path) -> Path:
    override = os.environ.get("BLEAKHOUSE_CAS_ROOT")
    return Path(override) if override else repo_root / "data" / "cas"


def _md5(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _cas_put(path: Path, *, repo_root: Path) -> str:
    """Hash `path`, copy bytes into the local CAS, return md5.

    Mirrors cas.store.put (kept in lockstep). Idempotent: re-puts of the
    same md5 are no-ops. Atomic via NamedTemporaryFile + os.rename in
    the destination directory.
    """
    md5 = _md5(path)
    dest = _cas_root(repo_root) / "files" / "md5" / md5[:2] / md5[2:]
    if dest.is_file():
        return md5
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=dest.parent, prefix=".put-", suffix=".tmp", delete=False
    ) as tmp_f:
        tmp = Path(tmp_f.name)
    try:
        shutil.copyfile(path, tmp)
        tmp.rename(dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return md5


def write_manifests(
    *,
    audio_dir: Path,
    episode: dict,
    boundaries: list[ShardBoundary],
    profile: str,
    repo_root: Path | None = None,
) -> None:
    """Write shards.json + manifest.json into audio_dir.

    Assumes the per-shard mp3 files already exist at
    audio_dir/shards/<profile>/{0000,0001,...}.mp3. Each shard is also
    copied into the local CAS via _cas_put — backup-mode parity with
    enrichment/render_audio.py.

    repo_root anchors the default CAS path (<repo>/data/cas); pass
    explicitly in tests, otherwise defaults to BLEAKHOUSE_CAS_ROOT or
    the canonical bleak-house repo three levels up.
    """
    if repo_root is None:
        # tools/forced_align/forced_align/manifest.py → repo root
        repo_root = Path(__file__).resolve().parents[3]
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
            "md5": _cas_put(mp3_path, repo_root=repo_root),
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
