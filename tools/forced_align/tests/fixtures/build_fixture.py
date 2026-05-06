"""One-shot: build a 3-turn synthetic mp3 fixture for slicer tests.

Generates 3 short tones at distinct frequencies + silence between
them, encoded as mp3. Run once; commit the output mp3.
"""
from pathlib import Path

from pydub import AudioSegment
from pydub.generators import Sine


def build() -> Path:
    silence = AudioSegment.silent(duration=500)  # 0.5s
    tone_a = Sine(440).to_audio_segment(duration=1500)   # 1.5s @ 440Hz
    tone_b = Sine(660).to_audio_segment(duration=1500)   # 1.5s @ 660Hz
    tone_c = Sine(880).to_audio_segment(duration=1500)   # 1.5s @ 880Hz
    audio = (
        silence + tone_a + silence
        + tone_b + silence
        + tone_c + silence
    )
    out = Path(__file__).parent / "synthetic_3turn.mp3"
    audio.export(str(out), format="mp3", bitrate="128k")
    return out


if __name__ == "__main__":
    p = build()
    print(f"wrote {p} ({p.stat().st_size} bytes)")
