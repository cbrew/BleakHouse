"""Voice descriptions for Qwen3-TTS-12Hz-1.7B-VoiceDesign.

Plain-data module: no imports from elsewhere in the project, so the
qwen3_tts venv (tools/qwen3_tts/) can read this dict without needing
the main project's Pydantic / Anthropic / etc. dependencies.

Each entry is the natural-language `instruct` argument passed to
`model.generate_voice_design()`. Gender + accent + register mirror
the speakers/voices block in params.yaml (the previous Gemini-TTS
setup); the actual timbre is up to Qwen3-TTS to interpret from the
prose.

VoiceDesign instructs are inherently fuzzy — small wording changes
can shift the output. The phrasings here were drafted under
BleakHouse-el1j.4; rewrite freely if the rendered voices need
adjustment, but expect the perceived voice to drift.
"""
from __future__ import annotations


MODEL_ID = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
LANGUAGE = "English"


# Fallback used for unknown speakers. Deliberately neutral.
FALLBACK_VOICE = (
    "Clear, neutral British voice. Even-paced, professional, "
    "without distinctive regional inflection."
)


VOICES: dict[str, str] = {
    "Host": (
        "British English voice. Warm female presenter in her early "
        "forties with a polished Home Counties accent — a BBC Radio 4 "
        "cadence. Calm, conversational, with the unhurried authority of "
        "someone who has hosted many literary panels."
    ),
    "Narrator": (
        "Clear, neutral female voice with a precise British accent — "
        "the voice of a professional narrator: neither warm nor cold, "
        "even-paced, neutral in register."
    ),

    # Literary panel
    "Eleanor Hartley": (
        "British English voice. Bright, articulate female academic in "
        "her late thirties with a precise Cambridge accent. Lively and "
        "analytical — the cadence of an English-faculty academic who "
        "loves dissecting a sentence in front of an audience."
    ),
    "James Blackstone": (
        "Scottish English voice. Measured male legal historian in his "
        "mid-fifties with a dry Edinburgh accent. Authoritative and "
        "slightly austere, like a legal historian who has lectured for "
        "thirty years and chooses every clause with care."
    ),
    "Caroline Woodcourt": (
        "British English voice. Gentle female reader in her late forties "
        "with a soft Bristol accent. Warm and intimate, slightly "
        "contemplative — the unhurried tone of someone who has read the "
        "same novels across decades."
    ),

    # Other panels in the rotation
    "Edmund Leigh": (
        "Patrician male voice in his sixties with an Oxford accent. "
        "Unhurried and slightly grand, the deliberate cadence of an "
        "emeritus don who is comfortable with long pauses."
    ),
    "Daniel Rosen": (
        "Energetic male voice in his late thirties with a clear London "
        "accent. Purposeful and direct — the cadence of a public "
        "intellectual giving a lecture he genuinely cares about."
    ),
    "Oliver Trevelyan": (
        "Warm theatrical male voice in his fifties with a Home Counties "
        "accent. Varied, expressive, slightly raconteurish — the kind "
        "of voice that holds attention at a dinner party."
    ),
    "Sarah Chen": (
        "Clear female voice in her thirties with a Northern California "
        "accent. Precise and direct, slightly brisk — the cadence of a "
        "tech professional giving a polished conference talk."
    ),
    "Rebecca Martinez": (
        "Soft female voice in her forties with a gentle American "
        "Southwest accent. Unhurried and thoughtful, with occasional "
        "reflective pauses — a careful, measured speaker."
    ),
    "Elena Volkov": (
        "Crisp female voice in her forties with an American East Coast "
        "accent — the cadence of a New York intellectual trained at "
        "elite institutions, intellectually sharp and engaged."
    ),
}


# Normalised lookup so "caroline_woodcourt" and "Caroline Woodcourt" both
# resolve to the same VOICES entry. phase3_episode.json has historically
# emitted both forms — and also "host" alongside "Host" — for the same
# speaker, which would otherwise drop the affected turns through to
# FALLBACK_VOICE and lose the per-character voice description.
_VOICE_KEYS_NORM: dict[str, str] = {
    k.lower().replace("_", " "): k for k in VOICES
}


def voice_for(speaker: str) -> str:
    """Return the instruct description for a speaker, or the fallback."""
    if not speaker:
        return FALLBACK_VOICE
    if speaker in VOICES:
        return VOICES[speaker]
    canonical = _VOICE_KEYS_NORM.get(speaker.strip().lower().replace("_", " "))
    if canonical is not None:
        return VOICES[canonical]
    return FALLBACK_VOICE
