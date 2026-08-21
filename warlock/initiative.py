"""Initiative order, and whose turn it is (plan doc 3.9).

DELIBERATELY NOT PERSISTED

Everything else the table knows lives in config.json. This does not, for two
reasons:

1. It changes every single turn. Persisting it would mean an SD-card write
   per turn, for hours, and the card is the one component here with a wear
   limit.
2. It is not a fact about the table, it is a fact about the next twenty
   minutes. A controller that restarts mid-combat should come back showing
   seats, not silently reasserting a combat that may already have ended.

The cost is that a restart loses the order and the GM retypes it. That is a
worse outcome than not restarting, and a better one than grinding the card.

WHY THE ORDER IS NOT JUST A LIST OF SEATS

Monsters take turns too, and they have no seat. So an entry carries an
optional zone: entries with one light up when their turn comes, entries
without simply do not. That keeps "the goblins go now" in the same list as
the players rather than in the GM's head.
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional

NOBODY = -1


class Entry:
    """One combatant. `zone` is None for anything without a seat."""

    __slots__ = ("name", "zone", "score")

    def __init__(self, name: str, zone: Optional[int] = None,
                 score: Optional[float] = None):
        self.name = name
        self.zone = zone
        self.score = score

    def to_dict(self) -> Dict[str, object]:
        return {"name": self.name, "zone": self.zone, "score": self.score}


class Initiative:
    """The order, and a cursor into it.

    Locked because the panel is threaded and the GM tapping "next" while a
    card advances the turn is exactly the overlap that corrupted the
    Pixelblaze socket earlier in this project.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._order: List[Entry] = []
        self._index = 0
        self._round = 0

    # ------------------------------------------------------------ building

    def set_order(self, entries: List[Entry], sort: bool = True) -> None:
        """Replace the order. Highest score first when scores are given.

        Sorting is opt-out because a GM who has typed the order by hand
        should not have it rearranged underneath them.
        """
        with self._lock:
            rows = list(entries)
            if sort and any(e.score is not None for e in rows):
                # Unscored entries sink rather than being dropped: a
                # half-filled order is still usable, and silently losing a
                # combatant mid-combat is much worse than an odd position.
                rows.sort(key=lambda e: (e.score is None,
                                         -(e.score or 0.0)))
            self._order = rows
            self._index = 0
            self._round = 1 if rows else 0

    def clear(self) -> None:
        with self._lock:
            self._order = []
            self._index = 0
            self._round = 0

    # ------------------------------------------------------------- moving

    def advance(self, step: int = 1) -> Optional[Entry]:
        """Move the cursor. Wraps, counting rounds as it passes the top."""
        with self._lock:
            if not self._order:
                return None
            position = self._index + step
            count = len(self._order)
            # Round changes on every wrap, in either direction, so stepping
            # back over the top does not leave the round count wrong.
            self._round += position // count if position >= 0 else -1
            self._index = position % count
            self._round = max(1, self._round)
            return self._order[self._index]

    def current(self) -> Optional[Entry]:
        with self._lock:
            if not self._order:
                return None
            return self._order[self._index]

    def active_zone(self) -> int:
        """The zone to light, or NOBODY.

        NOBODY covers both "no combat" and "it is the dragon's turn" — in
        neither case should a player's seat be lit, and lighting the
        previous player's seat because the current one has no zone would
        actively mislead.
        """
        entry = self.current()
        if entry is None or entry.zone is None:
            return NOBODY
        return entry.zone

    def go_to(self, index: int) -> Optional[Entry]:
        """Jump straight to a position. For fixing a mis-click mid-combat."""
        with self._lock:
            if not self._order:
                return None
            self._index = max(0, min(int(index), len(self._order) - 1))
            return self._order[self._index]

    # ------------------------------------------------------------ reading

    def report(self) -> Dict[str, object]:
        with self._lock:
            return {
                "round": self._round,
                "index": self._index if self._order else None,
                "active_zone": self.active_zone(),
                "running": bool(self._order),
                "order": [e.to_dict() for e in self._order],
            }
