"""Classic profile — preserves the rendering behaviour in place before
the 2026-04-17 tts_profiles refactor.

The dicts and helper functions below are moved verbatim from the previous
enrichment/render_audio.py so that existing outputs remain byte-identical
under --profile classic (the default).
"""
from __future__ import annotations

from enrichment import params as _params
from enrichment.podcast_types import Turn, VoicePolicy
from enrichment.tts_profiles.base import EpisodeContext

# Load DVC-tracked values from params.yaml. The module-level constants
# stay under the same names so callers don't need to change; values
# come from a single source of truth that DVC sees.
_speakers = _params.get("speakers", default={}) or {}

SPEAKER_VOICES: dict[str, str] = dict(_speakers.get("voices", {}))
SPEAKER_ACCENTS: dict[str, str] = dict(_speakers.get("accents", {}))
SPEAKER_VOICE_POLICIES: dict[str, VoicePolicy] = {
    name: VoicePolicy(**fields)
    for name, fields in (_speakers.get("voice_policies") or {}).items()
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
