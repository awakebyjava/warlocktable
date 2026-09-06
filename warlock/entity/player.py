"""Getting a line out of the speakers, without disturbing the table.

One chokepoint, deliberately. Every route to audible sound goes through
`play()` -- the probabilistic path, the panel's manual path, and anything
added later. That is what keeps the room-mic idea from being a redesign: "hold
until the room is quiet" becomes a wait in one function, not a change
everywhere.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Callable, Optional

from .lines import Line


class VoicePlayer(object):
    def __init__(self, audio, log, on_finished: Optional[Callable] = None):
        self.audio = audio
        self.log = log
        self.on_finished = on_finished

        self._lock = threading.Lock()
        self._speaking_until = 0.0
        self._current: Optional[str] = None
        self._timer: Optional[threading.Timer] = None
        self._warned = set()          # files already complained about

    # --- state ------------------------------------------------------------

    @property
    def is_speaking(self) -> bool:
        with self._lock:
            return time.monotonic() < self._speaking_until

    @property
    def current_line(self) -> Optional[str]:
        with self._lock:
            return self._current if time.monotonic() < self._speaking_until else None

    # --- playback ---------------------------------------------------------

    def play(self, line: Line, delay_s: float = 0.0) -> bool:
        """Speak a line. Returns whether it was handed to the audio device.

        NEVER RAISES. A voice line is decoration; a failure here must not
        reach the controller, and certainly must not reach a card tap.
        """
        if not line.exists:
            # Not every line is rendered at any given moment. Say so once per
            # file rather than on every attempt.
            if line.id not in self._warned:
                self._warned.add(line.id)
                self.log.record("voice.missing_audio", line=line.id,
                                path=line.path)
            return False

        if delay_s > 0:
            # A line landing at the same instant as a comet sweep competes
            # with it. A beat afterwards reads as a reaction rather than a
            # collision, so the delay is per-trigger and configurable.
            timer = threading.Timer(delay_s, self._speak, args=(line,))
            timer.daemon = True
            timer.start()
            with self._lock:
                self._timer = timer
            return True

        return self._speak(line)

    def _speak(self, line: Line) -> bool:
        try:
            # duck=True: the Entity talks OVER the soundscape, which dips
            # under it. Exactly what the effect channel already does for a
            # sting -- see AudioDevice, two channels on purpose.
            #
            # play_file rather than play_effect, so these 91 WAVs never enter
            # available_tracks() and bury the panel's effect picker.
            duration = self.audio.play_file(line.path, True)
            # Coerce INSIDE the try. A device that returns something odd --
            # None, or a dict from a logging call that was meant to return a
            # number -- must not throw from out here, where the failure would
            # escape into the caller. Found exactly that way.
            duration = float(duration or 0.0)
        except Exception as exc:      # noqa: BLE001
            self.log.record("voice.failed", line=line.id,
                            error="%s: %s" % (type(exc).__name__, exc))
            return False

        with self._lock:
            self._speaking_until = time.monotonic() + duration
            self._current = line.id

        self.log.record("voice.spoke", line=line.id, mood=line.mood,
                        duration_s=round(duration, 2), said=line.text)

        # Cooldown must start when the line ENDS. Lines run to 7.9 s, so
        # measuring from the start would let the next one arrive over the top
        # of this one.
        if self.on_finished is not None:
            timer = threading.Timer(max(0.05, duration), self._finished)
            timer.daemon = True
            timer.start()
        return True

    def _finished(self) -> None:
        with self._lock:
            self._current = None
        try:
            self.on_finished()
        except Exception:             # noqa: BLE001
            pass

    def stop(self) -> None:
        """Cancel a pending delayed line. Does not cut one already sounding --
        clipping the Entity mid-word sounds like a fault, not a silence."""
        with self._lock:
            timer, self._timer = self._timer, None
        if timer is not None:
            timer.cancel()

    # --- warm-up ----------------------------------------------------------

    def preload(self, lines, limit: Optional[int] = None) -> int:
        """Pull the WAVs into the audio device's cache before they are needed.

        Decoding on first play adds a delay that reads as the table
        hesitating, which is precisely the wrong impression for a thing whose
        only job is to seem present. 91 short WAVs is ~35 MB, which is nothing
        on a 4 GB Pi.

        Best-effort: a device with no cache simply does not implement this,
        and nothing here treats that as a problem.
        """
        loader = getattr(self.audio, "_sound", None)
        if not callable(loader):
            return 0

        loaded = 0
        for line in lines:
            if limit is not None and loaded >= limit:
                break
            if not line.exists:
                continue
            try:
                loader(line.path)
                loaded += 1
            except Exception:         # noqa: BLE001
                continue
        return loaded
