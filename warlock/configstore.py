"""Mutating the live config safely (plan doc 4.5).

This is the Management API's engine: the panel edits cards through here,
never by touching Controller.config directly.

Two problems it exists to solve.

**Concurrency.** The web server runs a thread per request while the NFC
thread reads config on every tap. Mutating a dict from one thread while
another iterates it is exactly the class of bug that took the lights down
when the panel first shipped. Every change here happens under a lock.

**Durability.** Config is Pi-owned data with no git history behind it
(4.4), so a corrupt or lost file is not recoverable from anywhere. Writes
are atomic, validated before they land, and the previous version is kept.

The in-memory object and the file are updated together: if the write is
refused, the in-memory change is rolled back, so what the table is doing
always matches what is on disk.
"""

from __future__ import annotations

import copy
import threading
from typing import Dict, List, Optional, Tuple

from .config import Card, Config, ConfigError, Target, save_config
from .zones import MAX_PLAYERS


class ConfigStore:
    def __init__(self, config: Config, path: str, log,
                 backup_dir: Optional[str] = None):
        self.config = config
        self.path = path
        self.log = log
        self.backup_dir = backup_dir
        self._lock = threading.RLock()

    # ------------------------------------------------------------ internals

    def _commit(self, what: str, **details) -> None:
        """Persist the current in-memory config, or raise without changing it."""
        save_config(self.config, self.path, self.backup_dir)
        self.log.record("config.saved", change=what, **details)

    def _with_rollback(self, what: str, mutate, **details):
        """Apply a mutation, persist it, and undo it if the write is refused.

        Without the rollback the table would keep running a change that was
        rejected on disk — so a restart would silently revert behaviour the
        operator believes they saved. Worse than refusing outright.
        """
        with self._lock:
            snapshot = copy.deepcopy(self.config.cards)
            try:
                result = mutate()
                self._commit(what, **details)
                return result
            except Exception as exc:
                self.config.cards = snapshot
                self.log.record("config.save_failed", change=what, error=str(exc))
                raise

    # ----------------------------------------------------------------- seats

    def set_player_count(self, count: int) -> int:
        """Change how many players are seated, and persist it.

        Has its own rollback rather than going through _with_rollback,
        which snapshots config.cards specifically. Restoring cards would
        not restore this, and quietly leaving the count changed in memory
        after a refused write is the exact failure _with_rollback exists
        to prevent.
        """
        count = int(count)
        if not 1 <= count <= MAX_PLAYERS:
            raise ValueError("player count must be between 1 and %d"
                             % MAX_PLAYERS)
        with self._lock:
            previous = self.config.player_count
            if count == previous:
                return count
            self.config.player_count = count

            # Anyone sitting in a seat that no longer exists is unseated
            # rather than left pointing at nothing: a stale zone_id would
            # send whispers to a zone the table is not lighting.
            displaced = [p.name for p in self.config.players
                         if p.zone_id is not None and p.zone_id > count]
            # Snapshot the seat assignments themselves, not just the list.
            # list() is shallow: it would hand back the very Player objects
            # whose zone_id had already been cleared, so a failed write
            # would roll back the count and silently keep everyone unseated.
            seated = {id(p): p.zone_id for p in self.config.players}
            for player in self.config.players:
                if player.zone_id is not None and player.zone_id > count:
                    player.zone_id = None
            try:
                self._commit("player_count", count=count,
                             displaced=len(displaced))
            except Exception as exc:
                self.config.player_count = previous
                for player in self.config.players:
                    player.zone_id = seated.get(id(player), player.zone_id)
                self.log.record("config.save_failed", change="player_count",
                                error=str(exc))
                raise
            if displaced:
                self.log.record("seat.displaced", players=displaced,
                                new_count=count)
            return count

    # ---------------------------------------------------------------- cards

    def list_cards(self) -> List[dict]:
        with self._lock:
            cards = [{
                "uid": uid,
                "label": c.label,
                "target_kind": c.target.kind,
                "target_name": c.target.name,
            } for uid, c in self.config.cards.items()]
        cards.sort(key=lambda c: c["label"].lower())
        return cards

    def valid_targets(self) -> Dict[str, List[str]]:
        """What a card may point at, read live from config.

        4.5: the UI builds its dropdowns from this, so it is impossible to
        assign something that does not exist.
        """
        with self._lock:
            return {
                "scene": sorted(self.config.scenes),
                "interruption": sorted(self.config.interruptions),
                "random_table": sorted(self.config.random_tables),
            }

    def set_card(self, uid: str, label: str, kind: str, name: str) -> dict:
        """Create or update a card. Raises ConfigError if the target is bogus."""
        uid = uid.strip()
        label = (label or "").strip()
        if not uid:
            raise ConfigError("uid is required")
        if not label:
            raise ConfigError("label is required")

        valid = self.valid_targets()
        if kind not in valid:
            raise ConfigError("unknown target kind %r" % kind)
        if name not in valid[kind]:
            raise ConfigError("no %s named %r" % (kind, name))

        def mutate():
            existing = self.config.cards.get(uid)
            self.config.cards[uid] = Card(uid=uid, label=label,
                                          target=Target(kind=kind, name=name))
            return "updated" if existing else "created"

        action = self._with_rollback("card", mutate, uid=uid, label=label,
                                      target="%s:%s" % (kind, name))
        return {"uid": uid, "label": label, "target_kind": kind,
                "target_name": name, "action": action}

    def delete_card(self, uid: str) -> None:
        with self._lock:
            if uid not in self.config.cards:
                raise ConfigError("no card with uid %s" % uid)

        def mutate():
            del self.config.cards[uid]

        self._with_rollback("card_deleted", mutate, uid=uid)

    # ------------------------------------------- referential integrity (4.5)

    def usage_of(self, kind: str, name: str) -> List[str]:
        """Everything that would break if this target disappeared.

        4.5 chose "block with a list" over silent deletion, because the
        failure it prevents is a card going quiet mid-session with no clue
        why.
        """
        users = []
        with self._lock:
            for uid, c in self.config.cards.items():
                if c.target.kind == kind and c.target.name == name:
                    users.append("card %s (%s)" % (c.label, uid))
            for tname, table in self.config.random_tables.items():
                for e in table.entries:
                    if e.kind == kind and e.name == name:
                        users.append("random table %s" % tname)
                        break
        return users


class UnassignedCards:
    """Unknown tags seen recently, so they can be registered (4.5).

    V1's answer to an unrecognised card was `print('not a registered card!')`
    into a terminal nobody was reading. Here the tap is remembered, the panel
    surfaces it, and naming it is a two-field form — which turns "register a
    new card" from a config-editing job into tapping it on the reader.

    Bounded and in-memory on purpose: this is a scratch list, not data worth
    persisting.
    """

    LIMIT = 12

    def __init__(self):
        self._seen: List[Tuple[str, float]] = []
        self._lock = threading.Lock()

    def note(self, uid: str) -> None:
        import time
        with self._lock:
            self._seen = [(u, t) for u, t in self._seen if u != uid]
            self._seen.insert(0, (uid, time.time()))
            del self._seen[self.LIMIT:]

    def forget(self, uid: str) -> None:
        with self._lock:
            self._seen = [(u, t) for u, t in self._seen if u != uid]

    def list(self) -> List[dict]:
        import time
        now = time.time()
        with self._lock:
            return [{"uid": u, "seconds_ago": round(now - t, 1)}
                    for u, t in self._seen]
