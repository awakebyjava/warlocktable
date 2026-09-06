"""Whether to speak, and which line.

Two separable jobs, kept apart because they fail differently: the gate is
about rate and timing, the choice is about not repeating yourself.

Everything here is pure decision-making -- no audio, no clock beyond
time.monotonic, no I/O. That is what makes it testable by running it ten
thousand times and counting.
"""

from __future__ import annotations

import random
import time
from collections import deque
from typing import Deque, Dict, List, Optional

from .lines import Line, LineLibrary

# Triggers that must never speak, enforced in CODE as well as config.
#
# Config can set any of these to probability 0, and the shipped config does.
# But config is edited by hand at a table, and a typo that made the Entity
# start narrating the volume slider would be both maddening and hard to
# diagnose. These are the ones where speaking is never a defensible outcome,
# so they are not left to a number in a file.
NEVER_ELIGIBLE = frozenset({
    "panel_soundscape",
    "panel_volume",
    "panel_brightness",
    "panel_mood",
    "panel_whisper",
    "panel_signal",
    "panel_seat",
    "player_signal",
    "player_whisper",
})


class Decision(object):
    """Why the Entity did or did not speak. Returned for logging and the panel."""

    __slots__ = ("spoke", "line", "reason", "trigger")

    def __init__(self, trigger, spoke=False, line=None, reason=""):
        self.trigger = trigger
        self.spoke = spoke
        self.line = line
        self.reason = reason

    def to_dict(self) -> Dict:
        return {"trigger": self.trigger, "spoke": self.spoke,
                "line": self.line.id if self.line else None,
                "reason": self.reason}

    def __repr__(self):
        return "Decision(%s, %s, %s)" % (
            self.trigger, "spoke" if self.spoke else "silent", self.reason)


class Picker(object):
    def __init__(self, library: LineLibrary, settings, clock=time.monotonic,
                 rng: Optional[random.Random] = None):
        self.library = library
        self.settings = settings          # config.EntityVoice
        self.clock = clock
        self.rng = rng or random.Random()

        self._last_finished_at: Optional[float] = None
        self._recent: Dict[str, Deque[str]] = {}
        self._gesture_open_until = 0.0
        self._gesture_spent = False

    # --- chattiness -------------------------------------------------------
    #
    # ONE SLIDER MOVES TWO GATES, and it has to.
    #
    # Probability and cooldown are in series. A slider that scaled only the
    # probability would look broken at the top end: set every trigger to 1.0
    # and a 180-second cooldown still permits one line every three minutes.
    # Whoever is tuning turns the dial to maximum, hears one line, then
    # silence, and concludes the control does nothing.
    #
    #   0.0  silent
    #   0.5  exactly the configured rates and cooldown  <- the default
    #   1.0  every eligible trigger, no cooldown

    def scaled_probability(self, configured: float) -> float:
        c = self.settings.chattiness
        if c <= 0.0:
            return 0.0
        if c <= 0.5:
            return configured * (c / 0.5)
        return configured + (1.0 - configured) * ((c - 0.5) / 0.5)

    def scaled_cooldown(self) -> float:
        c = self.settings.chattiness
        base = self.settings.global_cooldown_s
        if c <= 0.5:
            return base
        return base * (1.0 - (c - 0.5) / 0.5)

    # --- the gate ---------------------------------------------------------

    def cooldown_remaining(self) -> float:
        if self._last_finished_at is None:
            return 0.0
        elapsed = self.clock() - self._last_finished_at
        return max(0.0, self.scaled_cooldown() - elapsed)

    def begin_gesture(self) -> None:
        """A new input arrived; the previous gesture is over."""
        self._gesture_open_until = self.clock() + self.settings.gesture_settle_s
        self._gesture_spent = False

    def _gesture_is_open(self) -> bool:
        return self.clock() < self._gesture_open_until

    def consider(self, trigger: str, speaking: bool) -> Decision:
        """Should the Entity speak for this trigger? Chooses the line too."""
        if not self.settings.enabled:
            return Decision(trigger, reason="disabled")

        if trigger in NEVER_ELIGIBLE:
            return Decision(trigger, reason="never_eligible")

        # ONE GESTURE, ONE DECISION. Tapping the Wheel fires roll_table, then
        # play_interruption on the aura it landed on, then the lights, audio
        # and background that go with it. Considered per action, the Entity
        # would weigh speaking three or four times for one tap -- and would
        # occasionally speak, then speak again. The first eligible trigger in
        # a gesture is the one that counts; the rest are its consequences.
        if self._gesture_is_open() and self._gesture_spent:
            return Decision(trigger, reason="gesture_already_decided")

        if speaking:
            # A stale reaction is worse than silence, so drop rather than
            # queue. Deliberately does NOT spend the gesture: if the line in
            # flight ends before the next gesture, the next one is free.
            return Decision(trigger, reason="already_speaking")

        remaining = self.cooldown_remaining()
        if remaining > 0:
            return Decision(trigger, reason="cooldown_%.0fs" % remaining)

        probability = self.scaled_probability(self.settings.probability_for(trigger))
        if probability <= 0.0:
            return Decision(trigger, reason="probability_zero")
        if self.rng.random() >= probability:
            self._spend_gesture()
            return Decision(trigger, reason="not_this_time")

        line = self.choose(trigger)
        if line is None:
            return Decision(trigger, reason="no_line_available")

        self._spend_gesture()
        return Decision(trigger, spoke=True, line=line, reason="spoke")

    def _spend_gesture(self) -> None:
        """A decision was reached for this gesture, speaking or not.

        Not spending it on 'not_this_time' would let the cascade have a second
        and third roll off one tap, which quietly multiplies the real rate by
        however many actions a gesture happens to produce.
        """
        if not self._gesture_is_open():
            self._gesture_open_until = self.clock() + self.settings.gesture_settle_s
        self._gesture_spent = True

    # --- the choice -------------------------------------------------------

    def choose(self, trigger: str, mood: Optional[str] = None) -> Optional[Line]:
        pool = self.library.playable(self.library.pool_for(trigger))
        if not pool:
            return None

        mood = mood if mood is not None else self.settings.mood
        if mood:
            filtered = [ln for ln in pool if ln.mood == mood]
            # Mood is a preference, not a requirement. Silence is a worse
            # failure than a slightly off-mood line -- the primer is explicit.
            if filtered:
                pool = filtered

        key = self.library.category_of(trigger) or trigger
        recent = self._recent.setdefault(
            key, deque(maxlen=max(1, self.settings.no_repeat_window)))

        fresh = [ln for ln in pool if ln.id not in recent]
        if not fresh:
            # Everything in this pool has been heard lately. Better to repeat
            # than to go silent, so forget and carry on -- BUT NOT THE ONE
            # JUST PLAYED.
            #
            # The primer asks for two different things: never the same line
            # twice in a row, and ideally not within the last N. The deque
            # gives the second. Clearing it outright loses the first, and on a
            # two-line pool (dice has exactly two) that showed up immediately
            # as the same line landing back to back.
            last = recent[-1] if recent else None
            recent.clear()
            fresh = [ln for ln in pool if ln.id != last] or pool

        chosen = self.rng.choice(fresh)
        recent.append(chosen.id)
        return chosen

    # --- bookkeeping ------------------------------------------------------

    def note_finished(self) -> None:
        """Cooldown runs from when a line ENDS, not when it starts.

        With lines up to 7.9 seconds long this is a real difference: measuring
        from the start would let the next line arrive while the last was still
        audible.
        """
        self._last_finished_at = self.clock()

    def reset(self) -> None:
        self._last_finished_at = None
        self._recent.clear()
        self._gesture_open_until = 0.0
        self._gesture_spent = False
