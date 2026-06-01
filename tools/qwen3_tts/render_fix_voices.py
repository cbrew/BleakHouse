"""Re-render turn shards that previously rendered with FALLBACK_VOICE because
voice_for() lookup failed on a non-canonical speaker form (e.g.
"caroline_woodcourt" instead of "Caroline Woodcourt", or "host" instead
of "Host"). After the voice_for() normalisation patch on
enrichment/tts_profiles/qwen3_voicedesign.py, those speakers now resolve
to a real VOICES entry — this script regenerates the affected shards
so the on-disk episode reflects the corrected voice mapping.

Reads audio/shards.json in place. For each turn shard whose speaker
maps to FALLBACK_VOICE under the *old* literal lookup but maps to a
real VOICES entry under the *normalised* lookup, regenerates the wav,
encodes mp3, puts into CAS, replaces the md5 (and audio_seconds /
gen_seconds) in the shard, and flushes shards.json after every
segment. Inter-segment break shards and shards whose speaker already
hit a real VOICES entry are left untouched. Orphaned old CAS bytes
remain on disk; they're addressed by content and harmless.

Run from the qwen3_tts venv:
    uv run --directory tools/qwen3_tts python render_fix_voices.py \\
        --run /abs/path/to/data/runs/<run_id>
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
    _cas_put_bytes,
    _gen_turn_audio,
    _wav_to_mp3_bytes,
)
from enrichment.tts_profiles.qwen3_voicedesign import (  # noqa: E402
    MODEL_ID,
    VOICES,
    voice_for,
)

logger = logging.getLogger("render_fix_voices")


def _shard_text(shard: dict) -> str:
    parts: list[str] = []
    for utt in shard.get("utterances", []) or []:
        text = (utt.get("text") or "").strip()
        if text:
            parts.append(text)
    return " ".join(parts)


def _needs_refix(speaker: str) -> bool:
    """True if the *old* lookup (literal) would have hit FALLBACK_VOICE but
    the *new* lookup (normalised) hits a real entry."""
    if not speaker:
        return False
    if speaker in VOICES:
        return False
    norm = speaker.strip().lower().replace("_", " ")
    return any(k.lower().replace("_", " ") == norm for k in VOICES)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )
    p = argparse.ArgumentParser()
    p.add_argument("--run", required=True, type=Path)
    p.add_argument("--attn", default="sdpa",
                   choices=["sdpa", "flash_attention_2", "eager"])
    p.add_argument("--segment", type=int, default=None,
                   help="If set, re-render every turn shard in this segment "
                        "regardless of voice_for() outcome. Overrides the "
                        "default FALLBACK_VOICE refix criterion. Useful after "
                        "editing a voice instruct in qwen3_voicedesign.py.")
    args = p.parse_args()

    if not torch.cuda.is_available():
        raise SystemExit("CUDA required; refusing to run on CPU")

    shards_path = args.run / "audio" / "shards.json"
    if not shards_path.exists():
        raise SystemExit(f"no shards at {shards_path}")
    manifest = json.loads(shards_path.read_text())
    shards: list[dict] = manifest.get("shards") or []

    targets: list[int] = []
    for i, s in enumerate(shards):
        if s.get("kind") != "turn":
            continue
        if args.segment is not None:
            if s.get("segment_index") == args.segment:
                targets.append(i)
        elif _needs_refix(s.get("speaker") or ""):
            targets.append(i)

    if not targets:
        logger.info("no shards selected")
        return 0

    by_seg: dict[int, int] = {}
    for i in targets:
        si = shards[i].get("segment_index")
        by_seg[si] = by_seg.get(si, 0) + 1
    logger.info("will refix %d turn shards across %d segments: %s",
                len(targets), len(by_seg), sorted(by_seg.items()))

    logger.info("loading %s attn=%s ...", MODEL_ID, args.attn)
    t0 = time.monotonic()
    model = Qwen3TTSModel.from_pretrained(
        MODEL_ID,
        device_map="cuda:0",
        dtype=torch.bfloat16,
        attn_implementation=args.attn,
    )
    logger.info("loaded in %.1fs", time.monotonic() - t0)

    total_new_audio = 0.0
    total_new_gen = 0.0
    current_seg: int | None = None
    for n, i in enumerate(targets, 1):
        shard = shards[i]
        speaker = shard["speaker"]
        text = _shard_text(shard)
        if not text:
            logger.warning("shard idx=%d (seg=%d, turn=%d) empty — skipping",
                           i, shard.get("segment_index"),
                           shard.get("turn_index"))
            continue
        seg_idx = shard.get("segment_index")
        if seg_idx != current_seg:
            if current_seg is not None:
                _flush(shards_path, manifest, shards,
                       total_new_audio, total_new_gen)
                logger.info("flushed after seg=%d", current_seg)
            current_seg = seg_idx

        instruct_preview = voice_for(speaker)[:60].replace("\n", " ")
        t_start = time.monotonic()
        wav, sr = _gen_turn_audio(model, text, speaker)
        gen_s = time.monotonic() - t_start
        audio_s = len(wav) / sr
        total_new_audio += audio_s
        total_new_gen += gen_s

        old_audio = shard.get("audio_seconds", 0.0)
        old_gen = shard.get("gen_seconds", 0.0)
        mp3_bytes = _wav_to_mp3_bytes(wav, sr)
        new_md5 = _cas_put_bytes(mp3_bytes)
        shard["md5"] = new_md5
        shard["audio_seconds"] = round(audio_s, 3)
        shard["gen_seconds"] = round(gen_s, 3)
        logger.info(
            "  [%d/%d] seg=%d turn=%d speaker=%r voice=%r "
            "audio %.1f→%.1fs gen=%.1fs (%.2fx rt)",
            n, len(targets), seg_idx, shard.get("turn_index"),
            speaker, instruct_preview,
            old_audio, audio_s, gen_s,
            audio_s / gen_s if gen_s > 0 else 0,
        )

    _flush(shards_path, manifest, shards, total_new_audio, total_new_gen)
    logger.info("done. refixed=%d  new_audio=%.1fs  new_gen=%.1fs",
                len(targets), total_new_audio, total_new_gen)
    return 0


def _flush(shards_path, manifest, shards, _new_audio, _new_gen):
    audio = sum(s.get("audio_seconds", 0.0) for s in shards
                if s.get("kind") == "turn")
    gen = sum(s.get("gen_seconds", 0.0) for s in shards
              if s.get("kind") == "turn")
    manifest["shards"] = shards
    manifest["totals"] = {
        "shards": len(shards),
        "total_audio_seconds": round(audio, 2),
        "total_gen_seconds": round(gen, 2),
        "realtime_factor": round(audio / gen if gen else 0, 3),
    }
    shards_path.write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    sys.exit(main())
