"""The Entity voice -- the table occasionally says something.

FLAVOUR AUDIO, AND NOTHING ELSE. It holds no state anything else reads, makes
no decisions, and affects nothing. Delete this package and every other part of
the table behaves identically. That is not modesty about the feature; it is
the constraint that shapes the code:

  * It never blocks or delays a table action. The lights fire, and only then
    is a voice line considered, on its own.
  * It never touches table state. In particular it must NOT call the
    controller's _supersede(), which cancels scheduled reverts -- an aura
    would stop reverting because the table made a joke.
  * Nothing here raises. on_trigger returns a Decision, always.

The controller calls in; this package never calls out. Same boundary as
warlock/mapimport, for the same reason.

See entity-voice-specification.md, and voices/entity-voice-primer.md for the
intent behind it.
"""

from __future__ import annotations

import os
import threading
from typing import Dict, List, Optional

from .lines import Line, LineLibrary
from .picker import Decision, NEVER_ELIGIBLE, Picker
from .player import VoicePlayer

__all__ = ["EntityVoice", "Decision", "LineLibrary", "NEVER_ELIGIBLE"]


class EntityVoice(object):
    def __init__(self, settings, audio, log):
        """settings is config.EntityVoice. audio is the live AudioDevice."""
        self.settings = settings
        self.audio = audio
        self.log = log

        self.library: Optional[LineLibrary] = None
        self.picker: Optional[Picker] = None
        self.player: Optional[VoicePlayer] = None
        self.last: Optional[Decision] = None
        self.healthy = False
        self.last_error: Optional[str] = None
        self._lock = threading.Lock()

    # --- lifecycle --------------------------------------------------------

    def start(self) -> bool:
        """Load the database and warm the cache. Never raises (plan doc 5.2).

        A missing or broken line database leaves the Entity silent and the
        table entirely unaffected, which is the correct failure for something
        whose absence is meant to be survivable.
        """
        try:
            path = os.path.expanduser(self.settings.lines_json or "")
            audio_dir = os.path.expanduser(self.settings.audio_dir or "")
            if not path or not os.path.isfile(path):
                self.last_error = "no line database at %r" % path
                self.log.record("voice.unavailable", error=self.last_error)
                return False

            self.library = LineLibrary.load(path, audio_dir)
            self.picker = Picker(self.library, self.settings)
            self.player = VoicePlayer(self.audio, self.log,
                                      on_finished=self._on_finished)
        except Exception as exc:      # noqa: BLE001
            self.last_error = "%s: %s" % (type(exc).__name__, exc)
            self.log.record("voice.unavailable", error=self.last_error)
            return False

        missing = self.library.missing()
        loaded = self.player.preload(self.library.lines)
        self.healthy = True
        self.last_error = None
        self.log.record("voice.ready", lines=len(self.library.lines),
                        missing=len(missing), preloaded=loaded)
        if missing:
            self.log.record("voice.missing_files", count=len(missing),
                            examples=missing[:5])
        return True

    def stop_pending(self) -> None:
        """Cancel a line that is waiting on its delay, without cutting one
        already sounding. Clipping the Entity mid-word reads as a fault."""
        if self.player is not None:
            self.player.stop()

    def close(self) -> None:
        self.stop_pending()

    # --- the probabilistic path -------------------------------------------

    def begin_gesture(self) -> None:
        """A fresh input arrived -- a card tap, a panel press.

        Everything that follows until the settle time is one gesture, and gets
        one decision between it. See picker.consider.
        """
        if self.picker is not None:
            self.picker.begin_gesture()

    def on_trigger(self, trigger: str) -> Optional[str]:
        """Maybe speak. Returns the line id that played, or None.

        NEVER RAISES, and never blocks: the table action has already happened
        by the time this is called, and must not be able to un-happen.
        """
        try:
            return self._on_trigger(trigger)
        except Exception as exc:      # noqa: BLE001
            self.log.record("voice.error", trigger=trigger,
                            error="%s: %s" % (type(exc).__name__, exc))
            return None

    def _on_trigger(self, trigger: str) -> Optional[str]:
        if not self.healthy or self.picker is None or self.player is None:
            return None

        with self._lock:
            decision = self.picker.consider(trigger, self.player.is_speaking)
            self.last = decision

        if not decision.spoke or decision.line is None:
            # Logged at a low level: this fires on most actions, and the
            # answer is usually "no". Useful when tuning rates, noise
            # otherwise -- which is why the reason is carried.
            self.log.record("voice.silent", trigger=trigger,
                            reason=decision.reason)
            return None

        delay = self.settings.delay_for(trigger)
        if not self.player.play(decision.line, delay_s=delay):
            # The audio was missing or the device refused. Do not hold the
            # cooldown for a line nobody heard.
            return None
        return decision.line.id

    def _on_finished(self) -> None:
        if self.picker is not None:
            self.picker.note_finished()

    # --- the manual path --------------------------------------------------

    def say(self, line_id: str) -> bool:
        """Play one line by id, now.

        A SEPARATE PATH ON PURPOSE. It bypasses probability, cooldown and
        gesture suppression entirely -- if the panel asks for a line, the
        answer is that line, immediately. Essential for tuning, and useful
        mid-session when the operator wants a specific beat.
        """
        if not self.healthy or self.library is None or self.player is None:
            return False
        line = self.library.by_id.get(line_id)
        if line is None:
            return False
        played = self.player.play(line, delay_s=0.0)
        if played:
            self.log.record("voice.manual", line=line_id)
        return played

    # --- settings ---------------------------------------------------------

    @property
    def is_speaking(self) -> bool:
        return self.player.is_speaking if self.player else False

    @property
    def mood(self) -> Optional[str]:
        return self.settings.mood

    def set_mood(self, mood: Optional[str]) -> None:
        """Mood is just a filter value that something else sets.

        No drift logic, deliberately -- the primer defers it, and a table that
        changes its own mood on a timer is a behaviour nobody asked for yet.
        """
        self.settings.mood = mood or None

    # --- reporting --------------------------------------------------------

    def status(self) -> Dict:
        out = {
            "enabled": self.settings.enabled,
            "healthy": self.healthy,
            "error": self.last_error,
            "chattiness": self.settings.chattiness,
            "mood": self.settings.mood,
            "speaking": self.is_speaking,
            "cooldown_s": round(self.picker.scaled_cooldown(), 1) if self.picker else None,
            "cooldown_remaining_s": (round(self.picker.cooldown_remaining(), 1)
                                     if self.picker else None),
            "last": self.last.to_dict() if self.last else None,
        }
        if self.library is not None:
            out.update(self.library.summary())
        return out

    def lines(self) -> List[Dict]:
        if self.library is None:
            return []
        return [ln.to_dict() for ln in self.library.lines]
