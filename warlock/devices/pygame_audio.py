"""Real audio device, backed by pygame.mixer (plan doc 3.3, 4.3).

WHY NOT pygame.mixer.music
--------------------------
V1 used `pygame.mixer.music`, which is a SINGLE stream. Every card had to
stop the previous sound to play its own:

    pygame.mixer.music.stop()
    pygame.mixer.music.load('.../javan4.ogg')
    pygame.mixer.music.play(-1)

That is why the V1 table could never speak over its own ambience, and why
"thunder over rain" was impossible. It is the concrete limitation the
two-channel design in 4.3 exists to remove.

Here the mixer is split into two groups of pygame Channels:

  * **Bed** (2 channels, reserved) - the looping soundscape. Two, not one,
    so a change can be a TRUE crossfade: the outgoing bed fades out while
    the incoming one fades in, overlapping. A single channel could only do
    fade-out-then-fade-in, which has an audible hole in the middle.
  * **Effects** (the rest) - one-shots and voice lines, layered on top,
    several able to overlap.

DUCKING
-------
When an effect plays with duck=True the bed drops to `duck_level` and is
restored when the effect finishes. That is what makes the table's voice
audible over ambience without killing it.

MEMORY NOTE
-----------
pygame.mixer.Sound decodes the whole file into RAM - a 4-minute stereo track
is ~40MB regardless of whether the source is a small .ogg. The loaded-sound
cache is therefore bounded (see CACHE_LIMIT). Streaming would use less
memory but cannot overlap two beds, so it cannot crossfade. That trade is
deliberate.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Dict, List, Optional

from .base import AudioDevice, DeviceError, UnknownAssetError

AUDIO_EXTENSIONS = (".ogg", ".wav", ".mp3", ".flac")


class PygameAudio(AudioDevice):
    BED_CHANNELS = 2
    TOTAL_CHANNELS = 8
    # Bounded so a long session can't slowly consume all RAM. Small because
    # each entry may be tens of megabytes decoded.
    CACHE_LIMIT = 6

    def __init__(self, log, search_paths: List[str],
                 device: Optional[str] = None,
                 duck_level: float = 0.3, duck_ramp_s: float = 0.25):
        self.log = log
        self.search_paths = [os.path.expanduser(p) for p in search_paths]
        self.device = device
        self.duck_level = max(0.0, min(1.0, duck_level))
        self.duck_ramp_s = duck_ramp_s

        self._mixer = None
        self._library: Dict[str, str] = {}      # track name -> file path
        self._cache: Dict[str, object] = {}     # path -> Sound
        self._cache_order: List[str] = []

        self._bed_channels: List[object] = []
        self._bed_active = 0
        self._bed_volume = 1.0
        self._unduck_timer: Optional[threading.Timer] = None
        self._lock = threading.RLock()

        self.healthy = False
        self.last_error: Optional[str] = None
        self.soundscape: Optional[str] = None

    # ------------------------------------------------------------- lifecycle

    def start(self) -> bool:
        """Initialise the mixer and scan the library. Never raises (5.2)."""
        try:
            self._init_mixer()
        except Exception as exc:   # noqa: BLE001
            self.healthy = False
            self.last_error = "%s: %s" % (type(exc).__name__, exc)
            self.log.record("audio.unavailable", error=self.last_error)
            return False

        self._scan_library()
        self.healthy = True
        self.last_error = None
        self.log.record("audio.ready", device=self.device or "(sdl default)",
                        tracks=len(self._library))
        return True

    def _init_mixer(self) -> None:
        import pygame

        # Pin the output device BEFORE mixer init. Plan doc 5.3: the Pi has
        # 3.5mm on card 0 and HDMI on cards 2/3, and if the TV is off at boot
        # the default can silently move. SDL reads these at init time.
        if self.device:
            os.environ.setdefault("SDL_AUDIODRIVER", "alsa")
            os.environ["AUDIODEV"] = self.device

        # Modest buffer: too small crackles on a Pi, too large adds latency
        # between a card tap and the sound starting.
        pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=1024)
        pygame.mixer.init()
        pygame.mixer.set_num_channels(self.TOTAL_CHANNELS)
        # Reserve the bed channels so effects can never steal them.
        pygame.mixer.set_reserved(self.BED_CHANNELS)

        self._mixer = pygame.mixer
        self._bed_channels = [pygame.mixer.Channel(i)
                              for i in range(self.BED_CHANNELS)]

    def _scan_library(self) -> None:
        """Build track-name -> path. Name is the filename without extension,
        so config refers to "forest" and gets forest.ogg."""
        found: Dict[str, str] = {}
        for base in self.search_paths:
            if not os.path.isdir(base):
                self.log.record("audio.path_missing", path=base)
                continue
            for root, _dirs, files in os.walk(base):
                for fn in files:
                    stem, ext = os.path.splitext(fn)
                    if ext.lower() not in AUDIO_EXTENSIONS:
                        continue
                    # First match wins, so earlier search paths take priority.
                    # Prefer compressed over .wav when both exist: same audio,
                    # far less disk read, and V1 had both of most tracks.
                    if stem in found:
                        if ext.lower() == ".ogg" and not found[stem].endswith(".ogg"):
                            found[stem] = os.path.join(root, fn)
                        continue
                    found[stem] = os.path.join(root, fn)
        self._library = found

    def close(self) -> None:
        with self._lock:
            if self._unduck_timer is not None:
                self._unduck_timer.cancel()
                self._unduck_timer = None
        try:
            if self._mixer is not None:
                self._mixer.quit()
        except Exception:
            pass
        self._mixer = None
        self.healthy = False

    # ---------------------------------------------------------------- health

    def status(self) -> dict:
        return {
            "healthy": self.healthy,
            "device": self.device or "(sdl default)",
            "tracks": len(self._library),
            "soundscape": self.soundscape,
            "error": self.last_error,
        }

    # --------------------------------------------------------------- helpers

    def _require(self):
        if self._mixer is None or not self.healthy:
            raise DeviceError("audio unavailable: %s"
                              % (self.last_error or "not initialised"))
        return self._mixer

    def _resolve(self, track: str) -> str:
        path = self._library.get(track)
        if path is None:
            raise UnknownAssetError(
                "no audio track named %r (%d in library; searched %s)"
                % (track, len(self._library), ", ".join(self.search_paths) or "nothing"))
        return path

    def _sound(self, path: str):
        """Load a Sound, with a bounded cache (see MEMORY NOTE)."""
        if path in self._cache:
            return self._cache[path]
        snd = self._mixer.Sound(path)
        self._cache[path] = snd
        self._cache_order.append(path)
        while len(self._cache_order) > self.CACHE_LIMIT:
            evict = self._cache_order.pop(0)
            self._cache.pop(evict, None)
        return snd

    # ------------------------------------------------------------- interface

    def play_soundscape(self, track: Optional[str], crossfade_s: float) -> None:
        mixer = self._require()
        ms = max(0, int(crossfade_s * 1000))

        with self._lock:
            current = self._bed_channels[self._bed_active]

            if track is None:
                current.fadeout(ms)
                self.soundscape = None
                self.log.record("audio.soundscape_stop", fade_s=crossfade_s, real=True)
                return

            path = self._resolve(track)
            try:
                sound = self._sound(path)
            except Exception as exc:   # noqa: BLE001
                raise DeviceError("could not load %s: %s" % (path, exc))

            # True crossfade: start the new bed on the OTHER channel and fade
            # it up while the old one fades down. They overlap, so there is no
            # silent hole between soundscapes.
            nxt = 1 - self._bed_active
            incoming = self._bed_channels[nxt]
            incoming.set_volume(self._bed_volume)
            incoming.play(sound, loops=-1, fade_ms=ms)
            current.fadeout(ms)

            self._bed_active = nxt
            was, self.soundscape = self.soundscape, track
            self.log.record("audio.soundscape", track=track,
                            crossfade_s=crossfade_s, from_=was, real=True)

    def play_effect(self, track: str, duck: bool,
                    max_duration: Optional[float] = None) -> float:
        mixer = self._require()
        path = self._resolve(track)
        try:
            sound = self._sound(path)
        except Exception as exc:   # noqa: BLE001
            raise DeviceError("could not load %s: %s" % (path, exc))

        channel = mixer.find_channel()   # honours the reserved bed channels
        if channel is None:
            # Everything busy. Better to interrupt the oldest effect than to
            # silently drop a voice line the table was supposed to say.
            channel = mixer.Channel(self.BED_CHANNELS)

        full = float(sound.get_length())
        duration = full

        if max_duration is not None and max_duration < full:
            # Cut a long track short so it can serve as a dramatic beat.
            #
            # NOTE: pygame's fadeout(t) starts fading IMMEDIATELY over t ms.
            # Calling fadeout(12000) here made the audio quieter for its whole
            # 12 seconds rather than ending cleanly - a real bug, and audible
            # as the sting seeming to evaporate. Instead: play at full volume
            # with maxtime as a hard backstop, and schedule a SHORT fade near
            # the end.
            duration = max_duration
            fade_s = min(1.5, max_duration * 0.2)
            channel.play(sound, maxtime=int(max_duration * 1000))

            def _fade(ch=channel, ms=int(fade_s * 1000)):
                try:
                    ch.fadeout(ms)
                except Exception:
                    pass

            t = threading.Timer(max(0.0, max_duration - fade_s), _fade)
            t.daemon = True
            t.start()
        else:
            channel.play(sound)

        if duck:
            self._duck(duration)

        self.log.record("audio.effect", track=track, duck=duck,
                        duration_s=round(duration, 2),
                        full_length_s=(round(full, 2) if duration != full else None),
                        ducking=self.soundscape if duck else None, real=True)
        return duration

    def _duck(self, duration: float) -> None:
        """Drop the bed under an effect, and restore it afterwards."""
        with self._lock:
            if self._unduck_timer is not None:
                self._unduck_timer.cancel()
                self._unduck_timer = None

            bed = self._bed_channels[self._bed_active]
            bed.set_volume(self._bed_volume * self.duck_level)

            def restore():
                try:
                    self._bed_channels[self._bed_active].set_volume(self._bed_volume)
                    self.log.record("audio.unduck")
                except Exception:
                    pass

            # Restore slightly after the effect ends so the tail isn't clipped
            # by the bed swelling back underneath it.
            self._unduck_timer = threading.Timer(duration + self.duck_ramp_s, restore)
            self._unduck_timer.daemon = True
            self._unduck_timer.start()

    def available_tracks(self) -> List[str]:
        return sorted(self._library.keys(), key=str.lower)
