"""Fake devices — stand-ins that satisfy the real interfaces but only print.

This is the whole trick that lets the table's logic be built and tested on
a laptop with zero hardware (plan doc section 4.2). A fake's job is to be
honest about what it *would* have done, not to simulate hardware precisely.

Swapping one of these for a real driver later means writing a class that
implements the same base.LightDevice/AudioDevice/DisplayDevice interface —
nothing in warlock/controller.py changes.
"""

from __future__ import annotations

from typing import List, Optional

from .base import AudioDevice, DisplayDevice, LightDevice

# A plausible library, standing in for "ask the real Pixelblaze what
# patterns it has" / "ask the audio library what files exist". Matches the
# real names in use on the table today so this stays grounded.
FAKE_PATTERNS = [
    "breathing", "KITT", "blink fade", "fireflies",
    "green ripple reflections", "glitch bands", "sparkfire",
    "spin cycle", "opposites",
    "GreenCard", "WhiteCard", "BlackCard", "BlueCard", "RedCard",
]

# name -> fake duration in seconds. Real files will report real duration;
# for now these are just plausible numbers so reverts have something to
# time against.
FAKE_TRACKS = {
    "forest": 0, "plains": 0, "swamp": 0, "island": 0, "mountain": 0,  # loops
    "outre": 3.0, "cigarette": 3.0, "crowley2": 4.0, "peromyscus": 4.0,
    "javan4": 4.0, "audley": 4.0, "september4": 4.0,
}


class FakeLightDevice(LightDevice):
    def __init__(self, log):
        self.log = log
        self.current_pattern: Optional[str] = None
        self.brightness = 1.0

    def set_pattern(self, name: str) -> None:
        self.current_pattern = name
        self.log.record("lights.set_pattern", pattern=name)

    def set_brightness(self, level: float) -> None:
        self.brightness = level
        self.log.record("lights.set_brightness", level=level)

    def available_patterns(self) -> List[str]:
        return list(FAKE_PATTERNS)


class FakeAudioDevice(AudioDevice):
    def __init__(self, log):
        self.log = log
        self.soundscape: Optional[str] = None

    def play_soundscape(self, track: Optional[str], crossfade_s: float) -> None:
        if track is None:
            self.log.record("audio.soundscape_stop", fade_s=crossfade_s,
                             was=self.soundscape)
        else:
            self.log.record("audio.soundscape", track=track,
                             crossfade_s=crossfade_s, from_=self.soundscape)
        self.soundscape = track

    def play_effect(self, track: str, duck: bool,
                     max_duration: Optional[float] = None) -> float:
        duration = FAKE_TRACKS.get(track, 3.0)
        if max_duration is not None and max_duration < duration:
            duration = max_duration
        self.log.record("audio.effect", track=track, duck=duck,
                         duration_s=duration,
                         ducking=self.soundscape if duck else None)
        return duration

    def stop_effects(self, fade_ms: int = 200) -> None:
        self.log.record("audio.effects_stopped", fade_ms=fade_ms)

    def available_tracks(self) -> List[str]:
        return list(FAKE_TRACKS.keys())


class FakeDisplayDevice(DisplayDevice):
    def __init__(self, log):
        self.log = log
        self.background: Optional[str] = None

    def set_background(self, name: str) -> None:
        self.background = name
        self.log.record("display.background", name=name)

    def handoff(self, target: str) -> None:
        self.log.record("display.handoff", target=target)
