"""Abstract device interfaces.

These are contracts, not implementations. A "real" Pixelblaze-backed
LightDevice and a "fake" print-only one both satisfy LightDevice — so the
controller can be handed either and never know the difference. That is
the entire reason this file exists: it is the seam where a real device
gets swapped in later (plan doc section 4.2, step 4) without touching
anything above it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional


class DeviceError(Exception):
    """Raised when a device can't do what was asked.

    The controller catches this per-device (plan doc 5.2, fault isolation) —
    one broken device should never take down the others.
    """


class LightDevice(ABC):
    @abstractmethod
    def set_pattern(self, name: str) -> None:
        """Hard cut to a named pattern. See plan doc 4.3 — no crossfade
        assumed at this layer."""

    @abstractmethod
    def set_brightness(self, level: float) -> None:
        """level is 0.0-1.0."""

    @abstractmethod
    def available_patterns(self) -> List[str]:
        """What patterns actually exist right now. This is what makes the
        action registry self-describing (plan doc 4.5) — the management UI
        asks the device, not a hardcoded list, so you can never assign a
        pattern that doesn't exist."""


class AudioDevice(ABC):
    """Two independent channels, deliberately — see plan doc 4.3.

    V1's bug was having exactly one pygame.mixer.music channel, so a voice
    line or effect had to stop the soundscape to play. Splitting these two
    channels is what makes 'play a sting over the ambience' possible at all.
    """

    @abstractmethod
    def play_soundscape(self, track: Optional[str], crossfade_s: float) -> None:
        """track=None means stop with a fade-out. Looping bed, channel 1."""

    @abstractmethod
    def play_effect(self, track: str, duck: bool) -> float:
        """One-shot, channel 2, layered over the soundscape. Returns the
        track's duration in seconds so the controller knows when to revert
        (plan doc 4.3 — interruptions revert when their audio finishes)."""

    @abstractmethod
    def available_tracks(self) -> List[str]:
        ...


class DisplayDevice(ABC):
    @abstractmethod
    def set_background(self, name: str) -> None:
        ...

    @abstractmethod
    def handoff(self, target: str) -> None:
        """target is 'pi' or 'appletv' (plan doc 3.7, HDMI-CEC)."""
