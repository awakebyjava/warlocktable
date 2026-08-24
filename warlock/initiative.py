"""Player initiative order (plan doc 3.9).

DELIBERATELY SMALL

This tracks whose turn it is among the PLAYERS, and nothing else. It does
not know about monsters, it does not roll or sort anything, and it does not
try to guess an order from what anyone typed. The GM taps the players in
the order they want and that is the order.

That is a narrowing of an earlier version which parsed free text, sorted by
score, and carried seatless combatants for monsters. All of it was
unrequested and it buried the one thing this has to do: light the seat whose
turn it is. Monsters do not have seats, so the table has nothing to say
about them; that belongs on the GM's own sheet.

An entry is just a zone id. The player's NAME is looked up from their seat
claim when it is time to show something, rather than copied in here, so a
player who re-claims under a different name does not leave a stale one
sitting in the order.

DELIBERATELY NOT PERSISTED

It changes every turn, and the SD card is the one component here with a
wear limit. It is also a fact about the next twenty minutes rather than
about the table: a controller that restarts mid-combat should come back
showing seats, not silently reasserting a fight that may already be over.
"""

from __future__ import annotations

import threading
from typing import List, Optional

NOBODY = -1


class Initiative:
    """An order of seats, and a cursor into it.

    Locked because the panel is threaded: the GM tapping an arrow while a
    poll reads the order is the same overlap that desynced the Pixelblaze
    socket earlier in this project.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._order: List[int] = []
        self._index = 0
        self._running = False
        # Rounds are counted, turns are derived. A "turn" is just the
        # cursor's position in the order, so storing it separately would be
        # two facts that can disagree; the round is the only thing the
        # order itself does not already say.
        self._round = 0

    # ---------------------------------------------------------- the order

    def set_order(self, zones: List[int]) -> List[int]:
        """Replace the order with these seats, in exactly this sequence.

        Duplicates are dropped rather than rejected: tapping a player twice
        while building the order is a slip, and silently taking the first
        tap is friendlier than refusing the whole list.
        """
        with self._lock:
            seen = []
            for zone in zones:
                zone = int(zone)
                if zone not in seen:
                    seen.append(zone)
            self._order = seen
            self._index = 0
            self._running = False
            self._round = 0
            return list(self._order)

    def clear(self) -> None:
        with self._lock:
            self._order = []
            self._index = 0
            self._running = False
            self._round = 0

    def remove(self, zone: int) -> bool:
        """Take one seat out of the order. Returns True if it was there.

        Called when somebody leaves or is removed from a seat. Without it
        the order keeps a turn for an empty chair, and the table waits on a
        player who has gone -- which looks like the initiative system being
        stuck rather than a seat being vacated.

        The cursor is kept pointing at the SAME PLAYER wherever possible,
        rather than at the same index: removing somebody earlier in the
        order would otherwise skip whoever is currently up.
        """
        with self._lock:
            zone = int(zone)
            if zone not in self._order:
                return False
            at = self._order.index(zone)
            self._order.remove(zone)
            if not self._order:
                self._index = 0
                self._running = False
                return True
            if at < self._index:
                self._index -= 1
            self._index = min(self._index, len(self._order) - 1)
            return True

    def drop_missing(self, player_count: int) -> None:
        """Forget seats that no longer exist.

        Called when the player count drops. Leaving a vanished seat in the
        order would light nothing on its turn and look like a fault.
        """
        with self._lock:
            kept = [z for z in self._order if 1 <= z <= player_count]
            if kept != self._order:
                self._order = kept
                self._index = min(self._index, max(0, len(kept) - 1))
                if not kept:
                    self._running = False

    # ------------------------------------------------------------ running

    def run(self) -> Optional[int]:
        """Start from the top. This is the "Run Initiative" button."""
        with self._lock:
            if not self._order:
                return None
            self._index = 0
            self._running = True
            self._round = 1
            return self._order[0]

    def stop(self) -> None:
        """Stop pointing at anyone. The order is kept for the next round."""
        with self._lock:
            self._running = False

    def advance(self, step: int = 1) -> Optional[int]:
        """Move the cursor, wrapping at both ends.

        Wrapping rather than stopping at the last player: an order that
        refuses to go past the end would need a separate "new round"
        button, and going round again IS the new round.
        """
        with self._lock:
            if not self._order or not self._running:
                return None
            step = int(step)
            moved = self._index + step
            # Going round again IS the new round -- see the docstring. The
            # same arithmetic run backwards takes the count down, so
            # stepping back past the top of the order returns to the
            # previous round rather than stranding the count one high.
            n = len(self._order)
            self._round = max(1, self._round + (moved // n if n else 0))
            self._index = moved % n
            return self._order[self._index]

    # ------------------------------------------------------------ reading

    def active_zone(self) -> int:
        with self._lock:
            if not self._running or not self._order:
                return NOBODY
            return self._order[self._index]

    def report(self) -> dict:
        with self._lock:
            return {
                "order": list(self._order),
                "index": self._index if self._order else None,
                "running": self._running,
                "active_zone": self.active_zone(),
                # Both are 1-based for display: a GM says "round one, first
                # turn", never "round zero".
                "round": self._round if self._running else 0,
                "turn": (self._index + 1) if (self._running and self._order) else 0,
                "of": len(self._order),
            }
