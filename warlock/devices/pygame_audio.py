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

        self._effect_timers: List[threading.Timer] = []
        self._bed_channels: List[object] = []
        self._bed_active = 0
        self._bed_volume = 1.0
        # Master level, applied on top of the bed/duck levels. Software
        # rather than the system mixer on purpose: ALSA's volume is shared
        # with the whole machine, and a table that quietly reconfigures the
        # OS surprises whoever touches it next.
        self._master = 1.0
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

        # Modest buffer: too small crackles on a Pi, too large adds latency
        # between a card tap and the sound starting.
        settings = dict(frequency=44100, size=-16, channels=2, buffer=1024)

        # Pin the output device BEFORE mixer init. Plan doc 5.3: the Pi has
        # 3.5mm on card 0 and HDMI on cards 2/3, and if the TV is off at boot
        # the default can silently move to a different card. SDL reads these
        # env vars at init time.
        #
        # Pinned BY NAME, not by number: `hw:0,0` would still break if HDMI
        # enumerates differently and renumbers the cards, which is the very
        # scenario being defended against.
        if self.device:
            # Remember whether WE set the driver, so the fallback can undo it.
            set_driver = "SDL_AUDIODRIVER" not in os.environ
            if set_driver:
                os.environ["SDL_AUDIODRIVER"] = "alsa"
            os.environ["AUDIODEV"] = self.device
            try:
                pygame.mixer.pre_init(**settings)
                pygame.mixer.init()
                self.log.record("audio.device_pinned", device=self.device)
                self._finish_mixer_setup(pygame)
                return
            except Exception as exc:   # noqa: BLE001
                # The configured device does not exist here — most likely the
                # config was written for the Pi and this is the laptop. Fall
                # back rather than leaving the table silent, but say so
                # loudly: a silent fallback is how you end up wondering why
                # sound is coming out of the wrong place.
                self.log.record("audio.pin_failed", device=self.device,
                                error="%s: %s" % (type(exc).__name__, exc))
                os.environ.pop("AUDIODEV", None)
                if set_driver:
                    # Must also undo SDL_AUDIODRIVER=alsa, or the retry fails
                    # for a second, unrelated reason (there is no ALSA on the
                    # laptop) and the fallback never actually gets a chance.
                    os.environ.pop("SDL_AUDIODRIVER", None)
                try:
                    pygame.mixer.quit()   # clear any half-initialised state
                except Exception:
                    pass

        pygame.mixer.pre_init(**settings)
        pygame.mixer.init()
        self._finish_mixer_setup(pygame)

    def _finish_mixer_setup(self, pygame) -> None:
        pygame.mixer.set_num_channels(self.TOTAL_CHANNELS)
        # Reserve the bed channels so effects can never steal them.
        pygame.mixer.set_reserved(self.BED_CHANNELS)

        self._mixer = pygame.mixer
        self._bed_channels = [pygame.mixer.Channel(i)
                              for i in range(self.BED_CHANNELS)]
        self.actual_device = os.environ.get("AUDIODEV") or "(sdl default)"

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
            "device": getattr(self, "actual_device", None) or self.device or "(sdl default)",
            "device_requested": self.device,
            "volume": self._master,
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
            incoming.set_volume(self._bed_volume * self._master)
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
            with self._lock:
                self._effect_timers.append(t)
        else:
            channel.play(sound)

        # Effects previously ignored the master level entirely, so turning the
        # table down quietened the bed and left the stings at full blast.
        channel.set_volume(self._master)

        if duck:
            self._duck(duration)

        self.log.record("audio.effect", track=track, duck=duck,
                        duration_s=round(duration, 2),
                        full_length_s=(round(full, 2) if duration != full else None),
                        ducking=self.soundscape if duck else None, real=True)
        return duration

    def set_volume(self, level: float) -> None:
        """Master level for everything, applied immediately."""
        level = max(0.0, min(1.0, float(level)))
        with self._lock:
            self._master = level
            if self._mixer is not None:
                for channel in self._bed_channels:
                    try:
                        # Whatever the bed is currently at -- ducked or not --
                        # rescaled to the new master, so changing the volume
                        # mid-effect does not cancel a duck.
                        current = self._bed_volume
                        if self._unduck_timer is not None:
                            current *= self.duck_level
                        channel.set_volume(current * level)
                    except Exception:   # noqa: BLE001
                        pass
        self.log.record("audio.set_volume", level=level)

    def set_output(self, device: str) -> None:
        """Move the sound to another ALSA device, e.g. HDMI.

        Tears the mixer down and rebuilds it, because SDL only reads the
        output device at init. Three things have to be dealt with, and the
        middle one is not obvious:

        1. Timers referencing the old channels are cancelled.
        2. **The Sound cache is cleared.** Every cached Sound is bound to the
           mixer that created it. Keeping them across a re-init leaves
           objects pointing at a destroyed mixer, and the next card tap
           plays silence or crashes -- with nothing in the log to say why.
        3. The soundscape is restarted, so switching output mid-session does
           not leave the table silent until the next scene change.
        """
        device = (device or "").strip()
        if not device:
            raise DeviceError("no audio device given")

        with self._lock:
            playing = self.soundscape
            for timer in self._effect_timers:
                timer.cancel()
            self._effect_timers = []
            if self._unduck_timer is not None:
                self._unduck_timer.cancel()
                self._unduck_timer = None

            previous = self.device
            try:
                if self._mixer is not None:
                    self._mixer.quit()
            except Exception:   # noqa: BLE001
                pass

            self._cache = {}          # see (2) above
            self._cache_order = []
            self._mixer = None
            self._bed_channels = []
            self._bed_active = 0
            self._bed_volume = 1.0
            self.soundscape = None

            self.device = device
            try:
                self._init_mixer()
                # _init_mixer does NOT raise when a device will not open --
                # it falls back to the SDL default so the table is never
                # silent at boot. Correct there, wrong here: a switch that
                # quietly routes sound somewhere else is worse than one that
                # refuses. actual_device is the honest answer.
                actual = getattr(self, "actual_device", None)
                if actual != device:
                    raise DeviceError(
                        "would not open; sound would have gone to %s instead"
                        % (actual or "the default output"))
            except Exception as exc:   # noqa: BLE001
                # Put the old device back rather than leaving the table mute.
                self.device = previous
                self.healthy = False
                self.last_error = "%s: %s" % (type(exc).__name__, exc)
                self.log.record("audio.output_failed", device=device,
                                error=self.last_error, reverting_to=previous)
                try:
                    self._init_mixer()
                    self.healthy = True
                except Exception:   # noqa: BLE001
                    pass
                raise DeviceError("could not open %s: %s" % (device, exc))

            self.healthy = True
            self.last_error = None
            self.log.record("audio.set_output", device=device)

        if playing:
            self.play_soundscape(playing, 1.0)

    def _duck(self, duration: float) -> None:
        """Drop the bed under an effect, and restore it afterwards."""
        with self._lock:
            if self._unduck_timer is not None:
                self._unduck_timer.cancel()
                self._unduck_timer = None

            bed = self._bed_channels[self._bed_active]
            bed.set_volume(self._bed_volume * self.duck_level * self._master)

            def restore():
                try:
                    self._bed_channels[self._bed_active].set_volume(
                        self._bed_volume * self._master)
                    self.log.record("audio.unduck")
                except Exception:
                    pass

            # Restore slightly after the effect ends so the tail isn't clipped
            # by the bed swelling back underneath it.
            self._unduck_timer = threading.Timer(duration + self.duck_ramp_s, restore)
            self._unduck_timer.daemon = True
            self._unduck_timer.start()

    def stop_effects(self, fade_ms: int = 200) -> None:
        """Silence one-shots without touching the soundscape bed."""
        if self._mixer is None:
            return
        with self._lock:
            # Cancel scheduled end-fades first, or a timer from the effect we
            # are stopping will fire later against a channel that has since
            # been reused by a different sound.
            for t in self._effect_timers:
                t.cancel()
            self._effect_timers = []

            # Also drop any pending unduck: the bed must come back up now
            # rather than at the cancelled effect's original end time.
            if self._unduck_timer is not None:
                self._unduck_timer.cancel()
                self._unduck_timer = None

            stopped = 0
            for i in range(self.BED_CHANNELS, self.TOTAL_CHANNELS):
                ch = self._mixer.Channel(i)
                if ch.get_busy():
                    ch.fadeout(fade_ms)   # brief fade, not a click
                    stopped += 1

            # Restore the bed immediately, since whatever we were ducking for
            # is now gone.
            try:
                self._bed_channels[self._bed_active].set_volume(
                    self._bed_volume * self._master)
            except Exception:
                pass

        if stopped:
            self.log.record("audio.effects_stopped", channels=stopped,
                            fade_ms=fade_ms)

    def available_tracks(self) -> List[str]:
        return sorted(self._library.keys(), key=str.lower)
