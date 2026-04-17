"""Classic profile — preserves the rendering behaviour in place before
the 2026-04-17 tts_profiles refactor.

The dicts and helper functions below are moved verbatim from the previous
enrichment/render_audio.py so that existing outputs remain byte-identical
under --profile classic (the default).
"""
from __future__ import annotations

from enrichment.podcast_types import Turn, VoicePolicy
from enrichment.tts_profiles.base import EpisodeContext

SPEAKER_VOICES: dict[str, str] = {
    "Host": "Sulafat",
    "Eleanor Hartley": "Zephyr",
    "James Blackstone": "Sadaltager",
    "Caroline Woodcourt": "Achernar",
    "Narrator": "Schedar",
    "Edmund Leigh": "Algenib",
    "Daniel Rosen": "Alnilam",
    "Oliver Trevelyan": "Achird",
    "Sarah Chen": "Zephyr",
    "Rebecca Martinez": "Achernar",
    "Elena Volkov": "Aoede",
}

SPEAKER_ACCENTS: dict[str, str] = {
    "Host": "speaks with a warm Home Counties accent, like a BBC Radio 4 presenter",
    "Eleanor Hartley": "speaks with a lively Cambridge accent, articulate and precise",
    "James Blackstone": "speaks with a measured Edinburgh accent, dry and authoritative",
    "Caroline Woodcourt": "speaks with a gentle Bristol accent, warm and intimate",
    "Narrator": "speaks with a clear, neutral British accent",
    "Edmund Leigh": "speaks with a patrician Oxford accent, unhurried and precise",
    "Daniel Rosen": "speaks with a clear London accent, purposeful and direct",
    "Oliver Trevelyan": "speaks with a warm, theatrical Home Counties accent, varied and lively",
    "Sarah Chen": "speaks with a clear California accent, precise and direct, like a tech professional giving a talk",
    "Rebecca Martinez": "speaks with a soft American Southwest accent, unhurried and thoughtful, with occasional pauses for emphasis",
    "Elena Volkov": "speaks with a crisp American East Coast accent, the cadence of someone trained at Juilliard and Columbia, intellectually sharp",
}

SPEAKER_VOICE_POLICIES: dict[str, VoicePolicy] = {
    "Host": VoicePolicy(rate=0.98, energy="medium", pause_bias_ms=220, style="presenter_warm"),
    "Eleanor Hartley": VoicePolicy(rate=1.01, energy="medium_high", pause_bias_ms=170, style="analytic_bright"),
    "James Blackstone": VoicePolicy(rate=0.96, energy="medium_low", pause_bias_ms=260, style="measured_dry"),
    "Caroline Woodcourt": VoicePolicy(rate=0.97, energy="medium", pause_bias_ms=240, style="reflective_intimate"),
    "Narrator": VoicePolicy(rate=1.0, energy="medium", pause_bias_ms=200, style="neutral"),
    "Edmund Leigh": VoicePolicy(rate=0.94, energy="medium_low", pause_bias_ms=280, style="patrician_measured"),
    "Daniel Rosen": VoicePolicy(rate=0.99, energy="medium_high", pause_bias_ms=200, style="passionate_precise"),
    "Oliver Trevelyan": VoicePolicy(rate=1.02, energy="medium_high", pause_bias_ms=190, style="raconteur_warm"),
    "Sarah Chen": VoicePolicy(rate=1.01, energy="medium_high", pause_bias_ms=180, style="analytical_clear"),
    "Rebecca Martinez": VoicePolicy(rate=0.96, energy="medium", pause_bias_ms=250, style="contemplative_measured"),
    "Elena Volkov": VoicePolicy(rate=0.98, energy="medium", pause_bias_ms=210, style="engaged_analytical"),
}


def _rate_direction(rate: float, speaker_base: float) -> str:
    effective = rate * speaker_base
    if effective < 0.93:
        return "Speak slowly and deliberately."
    if effective < 0.96:
        return "Speak at a measured, unhurried pace."
    if effective > 1.04:
        return "Speak with brisk energy."
    if effective > 1.01:
        return "Speak with a slightly quicker pace."
    return ""


def _quote_direction(quote_mode: str) -> str:
    if quote_mode == "setup":
        return "Build anticipation — this leads into a literary quotation."
    if quote_mode == "reading":
        return (
            "Read this as a direct literary quotation with weight and relish. "
            "Slower pace, savor the words."
        )
    if quote_mode == "commentary":
        return "Resume normal conversational pace after the quotation."
    return ""


def _emphasis_direction(words: list[str]) -> str:
    if not words:
        return ""
    return f"Give slight emphasis to: {', '.join(words)}."


class ClassicProfile:
    """Current-behaviour profile. Default when no --profile flag is passed."""

    name = "classic"
    cache_namespace = "classic"
    pause_scale = 1.0

    def __init__(self, model_id: str | None = None) -> None:
        self.model_id = model_id or "gemini-2.5-flash-preview-tts"

    def voice_name(self, speaker: str) -> str:
        return SPEAKER_VOICES.get(speaker, "Sulafat")

    def build_turn_prompt(self, turn: Turn, ctx: EpisodeContext) -> str:
        speaker = turn.speaker
        accent = SPEAKER_ACCENTS.get(speaker, "speaks with a British accent")
        policy = SPEAKER_VOICE_POLICIES.get(
            speaker,
            VoicePolicy(rate=1.0, energy="medium", pause_bias_ms=200, style="neutral"),
        )

        lines: list[str] = [
            f"[Voice direction: {speaker} {accent}. "
            f"Energy: {policy.energy}. Style: {policy.style}.]",
            "",
        ]

        for utt in turn.utterances:
            directions: list[str] = []
            rate_dir = _rate_direction(utt.rate, policy.rate)
            if rate_dir:
                directions.append(rate_dir)
            quote_dir = _quote_direction(utt.quote_mode)
            if quote_dir:
                directions.append(quote_dir)
            emph_dir = _emphasis_direction(utt.emphasis_words)
            if emph_dir:
                directions.append(emph_dir)
            if directions:
                lines.append(f"({' '.join(directions)})")
            lines.append(utt.text)
            lines.append("")

        return "\n".join(lines)
