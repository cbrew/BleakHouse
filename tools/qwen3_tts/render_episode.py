"""Render a phase3_episode.json to audio shards via local Qwen3-TTS-VoiceDesign.

Runs in the tools/qwen3_tts/ venv (qwen-tts + torch + cuda). Reads the
phase3_episode.json + the static voice-description dict at
enrichment/tts_profiles/qwen3_voicedesign.py, generates one wav per
turn via `model.generate_voice_design()`, encodes to mp3, and stores
shards via the CAS module (same as enrichment/render_audio.py).

The output shards.json shape matches what render_audio.py produces,
so downstream tools (the webapp's audio serving, build_content_db,
etc.) don't need to know whether the audio came from Gemini or
Qwen3-TTS.

No voice matching, no per-utterance speech directions — VoiceDesign
takes a single natural-language `instruct` per speaker. Per
BleakHouse-el1j.4.

Run from the qwen3_tts venv:
    uv run --directory tools/qwen3_tts python render_episode.py \\
        --run data/runs/bh_trn_literary_hostprep_alibaba_qwen_plus
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import soundfile as sf
import torch
from pydub import AudioSegment
from qwen_tts import Qwen3TTSModel


# Resolve repo root and import the voice-description dict + cas module.
# Both are written as self-contained Python with no heavy deps (Pydantic
# / Anthropic / etc.), so this works from the qwen3_tts venv.
THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from enrichment.tts_profiles.qwen3_voicedesign import (  # noqa: E402
    LANGUAGE,
    MODEL_ID,
    VOICES,
    voice_for,
)
from cas import store as cas_store  # noqa: E402


PROFILE_NAME = "qwen3_voicedesign"
INTER_SEGMENT_MS = 2000   # 2-second pause between segments
MP3_BITRATE = "192k"

logger = logging.getLogger("render_qwen3_tts")


# ---------------------------------------------------------------------------
# Episode parsing — work directly from JSON (no Pydantic in this venv).
# ---------------------------------------------------------------------------

def _turn_text(turn: dict[str, Any]) -> str:
    """Concatenate the turn's utterances into a single string for synthesis."""
    parts: list[str] = []
    for utt in turn.get("utterances", []) or []:
        text = (utt.get("text") or "").strip()
        if text:
            parts.append(text)
    return " ".join(parts)


def _shard_speaker(turn: dict[str, Any]) -> str:
    return turn.get("speaker") or "Host"


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

def _wav_to_mp3_bytes(wav, sample_rate: int) -> bytes:
    """Convert a numpy float32 wav array into mp3 bytes via pydub."""
    # Write the wav to an in-memory buffer first; pydub reads via ffmpeg.
    wav_buf = io.BytesIO()
    sf.write(wav_buf, wav, sample_rate, format="WAV", subtype="PCM_16")
    wav_buf.seek(0)
    seg = AudioSegment.from_file(wav_buf, format="wav")
    mp3_buf = io.BytesIO()
    seg.export(mp3_buf, format="mp3", bitrate=MP3_BITRATE)
    return mp3_buf.getvalue()


def _silence_mp3_bytes(duration_ms: int) -> bytes:
    seg = AudioSegment.silent(duration=duration_ms)
    mp3_buf = io.BytesIO()
    seg.export(mp3_buf, format="mp3", bitrate=MP3_BITRATE)
    return mp3_buf.getvalue()


def _cas_put_bytes(b: bytes) -> str:
    """Drop bytes into the CAS and return the md5. Uses a tempfile because
    cas_store.put takes a path."""
    with tempfile.NamedTemporaryFile(
        prefix=".qwen3tts-", suffix=".mp3", delete=False
    ) as tmp_f:
        tmp = Path(tmp_f.name)
    try:
        tmp.write_bytes(b)
        return cas_store.put(tmp)
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

def _gen_turn_audio(
    model,
    text: str,
    speaker: str,
) -> tuple[Any, int]:
    instruct = voice_for(speaker)
    wavs, sr = model.generate_voice_design(
        text=text, language=LANGUAGE, instruct=instruct,
    )
    if wavs is None or len(wavs) == 0:
        raise RuntimeError(f"qwen3_tts returned no wav for speaker={speaker!r}")
    return wavs[0], int(sr)


def render_episode(
    run_dir: Path,
    only_segment: int | None = None,
    attn_implementation: str = "sdpa",
) -> dict:
    episode_path = run_dir / "phase3_episode.json"
    if not episode_path.exists():
        raise SystemExit(f"no episode at {episode_path}")
    episode = json.loads(episode_path.read_text())
    title = episode.get("title") or episode.get("episode_title") or "episode"
    segments = episode.get("segments") or []
    if not segments:
        raise SystemExit("episode has no segments")

    logger.info("loading %s  attn=%s ...", MODEL_ID, attn_implementation)
    t0 = time.monotonic()
    model = Qwen3TTSModel.from_pretrained(
        MODEL_ID,
        device_map="cuda:0",
        dtype=torch.bfloat16,
        attn_implementation=attn_implementation,
    )
    logger.info("loaded in %.1fs", time.monotonic() - t0)

    shards_meta: list[dict] = []
    total_audio_s = 0.0
    total_gen_s = 0.0
    turn_idx_global = 0

    for seg_idx, seg in enumerate(segments):
        if only_segment is not None and seg_idx != only_segment:
            continue
        seg_title = seg.get("title") or seg.get("segment_title") or f"segment_{seg_idx}"
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
                "  seg=%d turn=%d/%d speaker=%s text_chars=%d audio=%.1fs gen=%.1fs (%.2fx rt)",
                seg_idx, turn_idx, len(turns), speaker, len(text),
                audio_s, gen_s, audio_s / gen_s if gen_s > 0 else 0,
            )

            mp3_bytes = _wav_to_mp3_bytes(wav, sr)
            md5 = _cas_put_bytes(mp3_bytes)
            shards_meta.append({
                "file": f"{turn_idx_global:04d}.mp3",
                "md5": md5,
                "kind": "turn",
                "segment_index": seg_idx,
                "turn_index": turn_idx,
                "speaker": speaker,
                "role": turn.get("role") or "",
                "utterances": [
                    {
                        "text": u.get("text", ""),
                        "sentence_type": (u.get("sentence_type")
                                          if isinstance(u.get("sentence_type"), str)
                                          else getattr(u.get("sentence_type"), "value", None)),
                        "is_quote": u.get("is_quote", False),
                        "quote_mode": u.get("quote_mode"),
                        "passage_ref": u.get("passage_ref"),
                    }
                    for u in (turn.get("utterances") or [])
                ],
                "audio_seconds": round(audio_s, 3),
                "gen_seconds": round(gen_s, 3),
            })
            turn_idx_global += 1

        # Inter-segment break shard
        if seg_idx < len(segments) - 1 and only_segment is None:
            silence = _silence_mp3_bytes(INTER_SEGMENT_MS)
            md5 = _cas_put_bytes(silence)
            shards_meta.append({
                "file": f"{turn_idx_global:04d}.mp3",
                "md5": md5,
                "kind": "break",
                "segment_index": seg_idx,
            })
            turn_idx_global += 1

    # experts list — Host/Narrator excluded
    seen: set[str] = set()
    experts: list[dict[str, str]] = []
    for seg in segments:
        for turn in seg.get("turns") or []:
            sp = _shard_speaker(turn)
            if sp in ("Host", "Narrator") or sp in seen:
                continue
            seen.add(sp)
            experts.append({"name": sp, "role": turn.get("role") or ""})

    manifest = {
        "schema_version": 1,
        "profile": PROFILE_NAME,
        "model_id": MODEL_ID,
        "title": title,
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

    audio_dir = run_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    shards_path = audio_dir / "shards.json"
    shards_path.write_text(json.dumps(manifest, indent=2))
    logger.info(
        "wrote %s  shards=%d  audio=%.1fs  gen=%.1fs  rt=%.2fx",
        shards_path, len(shards_meta), total_audio_s, total_gen_s,
        manifest["totals"]["realtime_factor"],
    )
    return manifest


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )
    p = argparse.ArgumentParser()
    p.add_argument("--run", required=True, type=Path,
                   help="Path to a run directory containing phase3_episode.json")
    p.add_argument("--only-segment", type=int, default=None,
                   help="Render just this segment index (0-based) for quick A/B")
    p.add_argument("--attn", default="sdpa",
                   choices=["sdpa", "flash_attention_2", "eager"])
    args = p.parse_args()

    if not torch.cuda.is_available():
        raise SystemExit("CUDA required; refusing to run on CPU")
    render_episode(args.run, only_segment=args.only_segment,
                   attn_implementation=args.attn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
