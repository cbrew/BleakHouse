"""Kokoro TTS voice mapping for all speaker personas.

Maps each speaker name to a Kokoro voice ID and language code.
British panels use bf_/bm_ voices; interdisciplinary panel uses af_/am_ voices.
"""

from __future__ import annotations

# Speaker -> (kokoro_voice, lang_code, description)
KOKORO_VOICES: dict[str, tuple[str, str, str]] = {
    # Host
    "Host": ("bf_emma", "b", "warm British female presenter"),
    "Narrator": ("bm_lewis", "b", "neutral British male"),

    # Panel A (default literary)
    "Eleanor Hartley": ("bf_lily", "b", "lively British female — intellectual excitement"),
    "James Blackstone": ("bm_george", "b", "measured British male — dry authority"),
    "Caroline Woodcourt": ("bf_isabella", "b", "gentle British female — reflective intimacy"),

    # Panel B (alternative literary)
    "Edmund Leigh": ("bm_lewis", "b", "stately British male — patrician gravitas"),
    "Daniel Rosen": ("bm_daniel", "b", "firm British male — passionate precision"),
    "Oliver Trevelyan": ("bm_fable", "b", "warm British male — theatrical raconteur"),

    # Interdisciplinary panel (American)
    "Sarah Chen": ("af_sarah", "a", "clear American female — analytical precision"),
    "Rebecca Martinez": ("af_bella", "a", "soft American female — contemplative warmth"),
    "Elena Volkov": ("af_nova", "a", "crisp American female — engaged analysis"),
}

# Default fallback
DEFAULT_VOICE = ("bf_emma", "b", "default")


def get_kokoro_voice(speaker: str) -> tuple[str, str]:
    """Return (voice_id, lang_code) for a speaker name."""
    voice, lang, _ = KOKORO_VOICES.get(speaker, DEFAULT_VOICE)
    return voice, lang
