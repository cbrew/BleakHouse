"""Experimental TTS profile using gemini-3.1-flash-tts-preview and the
six-strategy prompting scheme documented at
https://ai.google.dev/gemini-api/docs/speech-generation#prompting-strategies.

Spec: docs/superpowers/specs/2026-04-17-tts-trevelyan-v2-experiment-design.md
"""
from __future__ import annotations

from collections.abc import Iterable

from enrichment.podcast_types import Turn, Utterance, VoicePolicy
from enrichment.tts_profiles.base import EpisodeContext
from enrichment.tts_profiles.classic import (
    SPEAKER_ACCENTS,
    SPEAKER_VOICE_POLICIES,
    SPEAKER_VOICES,
)

MODEL_ID = "gemini-3.1-flash-tts-preview"

SCENE = """\
## THE SCENE
A BBC Radio 4 studio, early evening. Four participants seated at a round oak
table, each with a boom-mounted microphone. Soft foam acoustic panels; the
faint hum of studio gear. The tone is In Our Time — measured, literary,
unhurried, but the conversation flows: participants pick up each other's
threads with minimal dead air and the host treats silence as a tool, not a
default. The red RECORD light is on; the host has just wrapped the
introduction."""

AUDIO_PROFILES: dict[str, str] = {
    "Host": """\
# AUDIO PROFILE: Host / "The chair"
A veteran BBC Radio 4 presenter, around 80 years old. Educated RP with
northern English colouring — grammar-school in the West Riding, then
Cambridge. Low, generous timbre; the voice of someone who has interviewed
everyone and is still curious. Treats questions as invitations. Never hurries
a guest, but never leaves dead air either.""",
    "Oliver Trevelyan": """\
# AUDIO PROFILE: Oliver Trevelyan / "The reader-performer"
An English actor and audiobook artist, male, born in the late 1950s.
Educated at Uppingham School and Cambridge. Received Pronunciation of that
generation: resonant lower register, theatrical timing, a touch of avuncular
warmth. A man who has read Dickens aloud for a living and relishes a good
anecdote. Never hurried; always moving forward.""",
    "Edmund Leigh": """\
# AUDIO PROFILE: Edmund Leigh / "The don"
Emeritus Oxford don, late 60s, Victorianist. Patrician RP with faint
pre-war inflections. Dry, aphoristic, allergic to cliché. His pauses do as
much work as his sentences — but those pauses are chosen, not habitual.""",
    "Daniel Rosen": """\
# AUDIO PROFILE: Daniel Rosen / "The critic"
London-based critic, early 40s, trained between New York and UCL. Clear
London cadence with American emphasis patterns. Direct, argumentative,
intellectually quick; tends to press a point hard, then soften it with a
joke. Forward momentum is his default.""",
}

FALLBACK_AUDIO_PROFILE_TEMPLATE = """\
# AUDIO PROFILE: {speaker}
A thoughtful, well-spoken guest on a literary radio programme. Educated RP,
conversational, forward-flowing."""

STYLE_PHRASES: dict[str, str] = {
    "presenter_warm": "warm, generous presenter — draws guests out",
    "analytic_bright": "bright, analytic, excited by craft",
    "measured_dry": "measured, dry authority grounded in evidence",
    "reflective_intimate": "reflective, intimate, emotionally engaged",
    "neutral": "neutral narration",
    "patrician_measured": "patrician, unhurried, aphoristic",
    "passionate_precise": "passionate but precise; argument-driven",
    "raconteur_warm": "warm raconteur with theatrical relish",
    "analytical_clear": "analytical, precise, direct",
    "contemplative_measured": "contemplative, unhurried, hypothesis-driven",
    "engaged_analytical": "engaged, analytical, historically informed",
}

DEFAULT_POLICY = VoicePolicy(
    rate=1.0, energy="medium", pause_bias_ms=200, style="neutral"
)


def _audio_profile(speaker: str) -> str:
    return AUDIO_PROFILES.get(
        speaker, FALLBACK_AUDIO_PROFILE_TEMPLATE.format(speaker=speaker)
    )


def _pacing_line(avg_rate: float, speaker_base: float) -> str:
    effective = avg_rate * speaker_base
    base = (
        "Prefer forward momentum; let sentences connect without settling. "
        "Pauses only where a thought genuinely demands one."
    )
    if effective < 0.92:
        return f"Noticeably slower than default. {base}"
    if effective > 1.06:
        return f"Noticeably brisker than default. {base}"
    return base


def _articulation_line(energy: str, emphasis_present: bool) -> str:
    base = {
        "medium_low": "clean articulation, unhurried",
        "medium": "clean articulation, natural energy",
        "medium_high": "clean articulation, slightly forward energy",
    }.get(energy, "clean articulation")
    if emphasis_present:
        base += "; lift the marked words slightly"
    return base


def _breathing_line(utterances: Iterable[Utterance]) -> str | None:
    if any(u.pause_before_ms > 600 for u in utterances):
        return (
            "Take a clear breath before the turn's longer pauses; otherwise "
            "breathe between clauses, not at commas."
        )
    return None


def _accent_for(speaker: str) -> str:
    return SPEAKER_ACCENTS.get(speaker, "neutral British")


def _director_notes(turn: Turn) -> str:
    policy = SPEAKER_VOICE_POLICIES.get(turn.speaker, DEFAULT_POLICY)
    lines = ["### DIRECTOR'S NOTES"]
    style_phrase = STYLE_PHRASES.get(policy.style, policy.style)
    lines.append(f"Style: {policy.style} — {style_phrase}.")

    rates = [u.rate for u in turn.utterances] or [1.0]
    avg_rate = sum(rates) / len(rates)
    lines.append(f"Pacing: {_pacing_line(avg_rate, policy.rate)}")

    emphasis_present = any(u.emphasis_words for u in turn.utterances)
    lines.append(
        f"Articulation: {_articulation_line(policy.energy, emphasis_present)}."
    )

    if turn.speaker == "Oliver Trevelyan":
        lines.append("Accent: as described in the Audio Profile.")
    else:
        lines.append(f"Accent: {_accent_for(turn.speaker)}.")

    breathing = _breathing_line(turn.utterances)
    if breathing:
        lines.append(f"Breathing: {breathing}")

    if any(u.quote_mode == "reading" for u in turn.utterances):
        lines.append(
            "Quotation: read any marked quotation as a direct literary "
            "quotation; slower, savoured."
        )

    emphasis_words = sorted(
        {w for u in turn.utterances for w in u.emphasis_words}
    )
    if emphasis_words:
        lines.append(
            f"Emphasis: give light emphasis to: {', '.join(emphasis_words)}."
        )

    return "\n".join(lines)


def _audio_tag(quote_mode: str) -> str:
    if quote_mode == "setup":
        return "[curious] "
    if quote_mode == "reading":
        return "[serious] "
    return ""


def _transcript(turn: Turn) -> str:
    lines = ["#### TRANSCRIPT"]
    for utt in turn.utterances:
        lines.append(f"{_audio_tag(utt.quote_mode)}{utt.text}")
    return "\n".join(lines)


def _sample_context(ctx: EpisodeContext) -> str | None:
    prev = ctx.previous_turn
    if prev is None or not prev.utterances:
        return None
    last_text = prev.utterances[-1].text.strip()
    return (
        "### SAMPLE CONTEXT\n"
        f"You are responding to {prev.speaker}. They have just said:\n"
        f"\"{last_text}\"\n"
        f"The segment is \"{ctx.segment_title}\"."
    )


class TrevelyanV2Profile:
    """Experimental 3.1 profile — see module docstring."""

    name = "trevelyan_v2"
    model_id = MODEL_ID
    cache_namespace = "trevelyan_v2"
    pause_scale = 0.5

    def voice_name(self, speaker: str) -> str:
        return SPEAKER_VOICES.get(speaker, "Sulafat")

    def build_turn_prompt(self, turn: Turn, ctx: EpisodeContext) -> str:
        sections: list[str] = [
            _audio_profile(turn.speaker),
            SCENE,
            _director_notes(turn),
        ]
        sample = _sample_context(ctx)
        if sample is not None:
            sections.append(sample)
        sections.append(_transcript(turn))
        return "\n\n".join(sections)
