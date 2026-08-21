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
from typing import List, Optional, Tuple


class DeviceError(Exception):
    """Raised when a device can't do what was asked.

    The controller catches this per-device (plan doc 5.2, fault isolation) —
    one broken device should never take down the others.
    """


class UnknownAssetError(DeviceError):
    """The device is fine; what was asked for doesn't exist.

    Deliberately distinct from a device fault. Asking for a pattern or track
    that isn't there is a *config* problem (plan doc 4.5, referential
    integrity) — it must not mark the subsystem unhealthy or trigger a
    reconnect. Found the hard way: a bogus pattern name was taking the whole
    lighting subsystem offline for 10 seconds.
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

    # ---- zones (plan doc 4.7) -------------------------------------------
    #
    # Optional capability, the same shape as set_overlay() on DisplayDevice
    # below: NOT abstract, defaulting to no-op. A light device that cannot
    # address regions is still a valid light device, and a Pixelblaze whose
    # zones pattern has not been uploaded must degrade quietly rather than
    # taking the lighting subsystem down.
    #
    # Colours are passed as HSV triples on the device's 0..1 scale, not as
    # names. Name-to-colour is a presentation decision and belongs above
    # this seam; the device just paints what it is told.

    def supports_zones(self) -> bool:
        """Whether per-zone colour will actually do anything here."""
        return False

    def show_zones(self, player_count: int,
                   colours: List[Tuple[float, float, float]],
                   gm_start: int, gm_len: int) -> None:
        """Switch to per-zone colour and paint every seat at once.

        gm_start/gm_len are in PATH coordinates — position around the
        physical perimeter loop, not LED index. The strip does not run in
        index order round the table, so this is the only coordinate system
        in which a seat is one contiguous run. See warlock/zones.py.

        colours is indexed by zone id: [0] is the GM, [1..player_count] are
        the seats clockwise from them.
        """
        return None

    def set_zone_colour(self, zone: int,
                        colour: Tuple[float, float, float]) -> None:
        """Repaint one zone, leaving the rest alone.

        Separate from show_zones() because per-seat initiative lighting
        moves a highlight every turn, and re-sending the whole layout to
        change one seat would be wasteful for the commonest zone operation
        the table will ever do.
        """
        return None


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
    def play_effect(self, track: str, duck: bool,
                    max_duration: Optional[float] = None) -> float:
        """One-shot, layered over the soundscape. Returns how long it will
        actually sound for, so the controller knows when to revert (plan doc
        4.3 — interruptions revert when their audio finishes).

        max_duration cuts the effect short with a fade. The V1 audio library
        is full-length music, not stings — javan4 runs 118s — so without a
        cap an "interruption" can outlast the scene it interrupts.
        """

    @abstractmethod
    def stop_effects(self, fade_ms: int = 200) -> None:
        """Silence any playing one-shots, leaving the soundscape alone.

        Called when something supersedes an interruption (plan doc 4.3, last
        input wins). Without this the lights change instantly while the sting
        plays on to its own schedule, so the table's response looks split in
        two: picture first, sound catching up afterwards.
        """

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

    def set_overlay(self, mode: str) -> None:
        """Choose the map overlay: "none", "grid", "hex", ...

        Deliberately NOT abstract: a display with no overlay artwork is
        still a valid display. The default does nothing rather than making
        every implementation carry a stub.
        """
        return None
