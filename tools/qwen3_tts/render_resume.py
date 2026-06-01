"""Render the remaining segments of phase3_episode.json and merge into the
existing audio/shards.json. Used after a partial render (e.g. segment 0
only) when re-rendering from scratch would discard validated audio.

Imports the per-shard helpers from render_episode.py so the audio path is
identical. Inserts inter-segment break shards before each newly-rendered
segment. Flushes shards.json after every segment so a crash mid-run does
not lose generated work.

Run from the qwen3_tts venv:
    uv run --directory tools/qwen3_tts python render_resume.py \\
        --run /abs/path/to/data/runs/<run_id> --from-segment 1
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import torch
from qwen_tts import Qwen3TTSModel

THIS_FILE = Path(__file__).resolve()
sys.path.insert(0, str(THIS_FILE.parent))
REPO_ROOT = THIS_FILE.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from render_episode import (  # noqa: E402
    INTER_SEGMENT_MS,
    PROFILE_NAME,
    _cas_put_bytes,
    _gen_turn_audio,
    _shard_speaker,
    _silence_mp3_bytes,
    _turn_text,
    _wav_to_mp3_bytes,
)
from enrichment.tts_profiles.qwen3_voicedesign import MODEL_ID  # noqa: E402

logger = logging.getLogger("render_resume")


def _flush(shards_path, base, shards_meta, total_audio_s, total_gen_s, experts):
    for i, s in enumerate(shards_meta):
        s["file"] = f"{i:04d}.mp3"
    manifest = {
        "schema_version": base.get("schema_version", 1),
        "profile": base.get("profile", PROFILE_NAME),
        "model_id": base.get("model_id", MODEL_ID),
        "title": base.get("title"),
        "experts": experts,
        "shards": shards_meta,
        "totals": {
            "shards": len(shards_meta),
            "total_audio_seconds": round(total_audio_s, 2),
            "total_gen_seconds": round(total_gen_s, 2),
            "realtime_factor": round(
                total_audio_s / total_gen_s if total_gen_s else 0, 3,
            ),
        },
    }
    shards_path.write_text(json.dumps(manifest, indent=2))


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )
    p = argparse.ArgumentParser()
    p.add_argument("--run", required=True, type=Path)
    p.add_argument("--from-segment", type=int, default=1)
    p.add_argument("--attn", default="sdpa",
                   choices=["sdpa", "flash_attention_2", "eager"])
    args = p.parse_args()

    if not torch.cuda.is_available():
        raise SystemExit("CUDA required; refusing to run on CPU")

    run_dir = args.run
    episode_path = run_dir / "phase3_episode.json"
    shards_path = run_dir / "audio" / "shards.json"
    if not episode_path.exists():
        raise SystemExit(f"no episode at {episode_path}")
    if not shards_path.exists():
        raise SystemExit(f"no existing shards at {shards_path}")

    episode = json.loads(episode_path.read_text())
    segments = episode.get("segments") or []
    if not segments:
        raise SystemExit("episode has no segments")

    existing = json.loads(shards_path.read_text())
    shards_meta: list[dict] = list(existing.get("shards") or [])
    total_audio_s = float(existing.get("totals", {}).get("total_audio_seconds", 0.0))
    total_gen_s = float(existing.get("totals", {}).get("total_gen_seconds", 0.0))

    seen: set[str] = set()
    experts: list[dict[str, str]] = []
    for seg in segments:
        for turn in seg.get("turns") or []:
            sp = _shard_speaker(turn)
            if sp in ("Host", "Narrator") or sp in seen:
                continue
            seen.add(sp)
            experts.append({"name": sp, "role": turn.get("role") or ""})

    present_segs = sorted({s.get("segment_index") for s in shards_meta
                           if s.get("segment_index") is not None})
    logger.info("existing shards=%d  segments_present=%s  total_audio=%.1fs",
                len(shards_meta), present_segs, total_audio_s)
    logger.info("will render segments %d..%d", args.from_segment, len(segments) - 1)

    logger.info("loading %s  attn=%s ...", MODEL_ID, args.attn)
    t0 = time.monotonic()
    model = Qwen3TTSModel.from_pretrained(
        MODEL_ID,
        device_map="cuda:0",
        dtype=torch.bfloat16,
        attn_implementation=args.attn,
    )
    logger.info("loaded in %.1fs", time.monotonic() - t0)

    for seg_idx in range(args.from_segment, len(segments)):
        silence = _silence_mp3_bytes(INTER_SEGMENT_MS)
        md5 = _cas_put_bytes(silence)
        shards_meta.append({
            "file": "",
            "md5": md5,
            "kind": "break",
            "segment_index": seg_idx - 1,
        })

        seg = segments[seg_idx]
        seg_title = seg.get("title") or f"segment_{seg_idx}"
        turns = seg.get("turns") or []
        logger.info(
            "segment %d/%d: %r (%d turns)",
            seg_idx + 1, len(segments), seg_title, len(turns),
        )
        for turn_idx, turn in enumerate(turns):
            speaker = _shard_speaker(turn)
            text = _turn_text(turn)
            if not text:
                logger.warning("seg=%d turn=%d empty text — skipping",
                               seg_idx, turn_idx)
                continue
            t_start = time.monotonic()
            wav, sr = _gen_turn_audio(model, text, speaker)
            gen_s = time.monotonic() - t_start
            audio_s = len(wav) / sr
            total_audio_s += audio_s
            total_gen_s += gen_s
            logger.info(
                "  seg=%d turn=%d/%d speaker=%s text_chars=%d "
                "audio=%.1fs gen=%.1fs (%.2fx rt)",
                seg_idx, turn_idx, len(turns), speaker, len(text),
                audio_s, gen_s, audio_s / gen_s if gen_s > 0 else 0,
            )
            mp3_bytes = _wav_to_mp3_bytes(wav, sr)
            md5 = _cas_put_bytes(mp3_bytes)
            shards_meta.append({
                "file": "",
                "md5": md5,
                "kind": "turn",
                "segment_index": seg_idx,
                "turn_index": turn_idx,
                "speaker": speaker,
                "role": turn.get("role") or "",
                "utterances": [
                    {
                        "text": u.get("text", ""),
                        "sentence_type": u.get("sentence_type"),
                        "is_quote": u.get("is_quote", False),
                        "quote_mode": u.get("quote_mode"),
                        "passage_ref": u.get("passage_ref"),
                    }
                    for u in (turn.get("utterances") or [])
                ],
                "audio_seconds": round(audio_s, 3),
                "gen_seconds": round(gen_s, 3),
            })

        _flush(shards_path, existing, shards_meta,
               total_audio_s, total_gen_s, experts)
        logger.info("flushed after seg=%d  cumulative shards=%d",
                    seg_idx, len(shards_meta))

    logger.info("done. shards=%d  audio=%.1fs  gen=%.1fs",
                len(shards_meta), total_audio_s, total_gen_s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
