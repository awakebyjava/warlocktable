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
import re
import threading
from typing import Dict, List, Optional, Tuple

from .config import (Scene, Transition, Card, Config, ConfigError,
                     Interruption, Target, save_config)
from .zones import MAX_PLAYERS


# Scene names end up as config keys and in URLs, so keep them plain.
NAME_OK = re.compile(r"^[a-z0-9_-]+$")


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

    def set_audio(self, volume=None, device=None):
        """Persist the master volume and/or the chosen output.

        Own rollback for the same reason set_player_count has one:
        _with_rollback snapshots config.cards, which would not restore
        either of these, and quietly keeping a change in memory after a
        refused write is what that machinery exists to prevent.
        """
        with self._lock:
            before = (self.config.volume, self.config.audio_device)
            if volume is not None:
                self.config.volume = max(0.0, min(1.0, float(volume)))
            if device is not None:
                self.config.audio_device = device
            try:
                self._commit("audio", volume=self.config.volume,
                             device=self.config.audio_device)
            except Exception as exc:
                self.config.volume, self.config.audio_device = before
                self.log.record("config.save_failed", change="audio",
                                error=str(exc))
                raise
            return {"volume": self.config.volume,
                    "device": self.config.audio_device}

    def set_voice(self, enabled=None, chattiness=None, mood=None,
                  announce_cards=None):
        """Persist the Entity voice controls.

        Same shape and the same rollback reasoning as set_audio: these are
        fields _with_rollback would not restore, and silently keeping a
        change in memory after a refused write is exactly what that
        machinery exists to prevent.
        """
        with self._lock:
            voice = self.config.entity_voice
            before = (voice.enabled, voice.chattiness, voice.mood,
                      voice.announce_cards)

            if announce_cards is not None:
                voice.announce_cards = bool(announce_cards)
            if enabled is not None:
                voice.enabled = bool(enabled)
            if chattiness is not None:
                voice.chattiness = max(0.0, min(1.0, float(chattiness)))
            if mood is not None:
                # "" clears the filter rather than setting a mood named "".
                voice.mood = str(mood) or None

            try:
                self._commit("voice", enabled=voice.enabled,
                             chattiness=voice.chattiness, mood=voice.mood,
                             announce_cards=voice.announce_cards)
            except Exception as exc:
                (voice.enabled, voice.chattiness, voice.mood,
                 voice.announce_cards) = before
                self.log.record("config.save_failed", change="voice",
                                error=str(exc))
                raise
            return {"enabled": voice.enabled,
                    "chattiness": voice.chattiness,
                    "mood": voice.mood,
                    "announce_cards": voice.announce_cards}

    def set_sfx(self, enabled=None, family=None, on=None,
                muted=None, profile=None):
        """Persist the sound-effect switches. Same shape as set_audio."""
        with self._lock:
            sfx = self.config.sound_effects
            before = (sfx.enabled, dict(sfx.families), list(sfx.muted))

            if enabled is not None:
                sfx.enabled = bool(enabled)
            if family is not None and on is not None:
                sfx.families[str(family)] = bool(on)
            if muted is not None:
                sfx.muted = [str(x) for x in muted]
            if profile is not None:
                from .sfx import FAMILIES, PROFILES
                wanted = PROFILES.get(profile)
                if wanted is not None:
                    sfx.families = {f: (f in wanted) for f in FAMILIES}

            try:
                self._commit("sfx", enabled=sfx.enabled,
                             families=sum(1 for v in sfx.families.values() if v),
                             muted=len(sfx.muted))
            except Exception as exc:
                sfx.enabled, sfx.families, sfx.muted = before
                self.log.record("config.save_failed", change="sfx",
                                error=str(exc))
                raise
            return {"enabled": sfx.enabled,
                    "families": dict(sfx.families),
                    "muted": list(sfx.muted)}

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

    # ------------------------------------------------------------- scenes

    def list_scenes(self) -> List[dict]:
        out = []
        for name, sc in sorted(self.config.scenes.items()):
            out.append({
                "name": name,
                "lights": sc.lights,
                "soundscape": sc.soundscape,
                "background": sc.background,
                "crossfade_s": sc.transition.crossfade_s,
                "duck": sc.transition.duck,
                "is_idle": name == self.config.idle_scene_name,
                "used_by": self.usage_of("scene", name),
            })
        return out

    def scene_options(self, controller) -> dict:
        """Everything a scene may point at, asked of the live devices.

        Same principle as valid_targets and the action registry (plan doc
        4.5): the editor offers what actually exists, so a scene cannot be
        saved naming a pattern or a track that is not there.
        """
        def safe(fn, fallback=None):
            try:
                return list(fn())
            except Exception:              # noqa: BLE001
                return list(fallback or [])

        return {
            "lights": safe(controller.lights.available_patterns),
            "soundscapes": safe(controller.audio.available_tracks),
            "backgrounds": safe(controller.background_choices),
        }

    def set_scene(self, name, lights, soundscape=None, background=None,
                  crossfade_s=None, duck=None, options=None) -> dict:
        """Create or update a scene.

        `options` is scene_options() when the caller has a controller to ask.
        Given it, a scene cannot be saved referring to a pattern, track or
        background that does not exist -- the referential integrity rule from
        4.5, applied at the point of writing rather than discovered at the
        table when the card is tapped.
        """
        name = (name or "").strip().lower().replace(" ", "_")
        lights = (lights or "").strip()
        if not name:
            raise ConfigError("scene name is required")
        if not NAME_OK.match(name):
            raise ConfigError("scene name may only use letters, numbers, "
                              "dash and underscore")
        if not lights:
            raise ConfigError("a lighting pattern is required")

        soundscape = (soundscape or "").strip() or None
        background = (background or "").strip() or None

        if options:
            if options.get("lights") and lights not in options["lights"]:
                raise ConfigError("no lighting pattern named %r" % lights)
            if soundscape and options.get("soundscapes")                     and soundscape not in options["soundscapes"]:
                raise ConfigError("no soundscape named %r" % soundscape)
            if background and options.get("backgrounds")                     and background not in options["backgrounds"]:
                raise ConfigError("no background named %r" % background)

        existing = self.config.scenes.get(name)
        transition = Transition(
            crossfade_s=(float(crossfade_s) if crossfade_s is not None
                         else (existing.transition.crossfade_s if existing else 1.5)),
            duck=(bool(duck) if duck is not None
                  else (existing.transition.duck if existing else True)),
        )

        def mutate():
            self.config.scenes[name] = Scene(
                name=name, lights=lights, soundscape=soundscape,
                background=background, transition=transition)
            return "updated" if existing else "created"

        action = self._with_rollback("scene", mutate, name=name, lights=lights)
        return {"name": name, "action": action}

    def delete_scene(self, name: str) -> None:
        """Remove a scene. Refuses if anything still points at it."""
        name = (name or "").strip()
        if name not in self.config.scenes:
            raise ConfigError("no scene named %r" % name)
        if name == self.config.idle_scene_name:
            raise ConfigError(
                "%r is the idle scene -- the table falls back to it, so "
                "removing it would leave no resting state." % name)

        users = self.usage_of("scene", name)
        if users:
            # Deleting out from under a card would leave a tap that does
            # nothing and says nothing, which is the failure this whole
            # referential-integrity idea exists to prevent.
            raise ConfigError(
                "%r is still used by %d card(s): %s"
                % (name, len(users), ", ".join(users[:4])))

        def mutate():
            del self.config.scenes[name]
            return "deleted"

        self._with_rollback("scene", mutate, name=name)

    # ------------------------------------------------------- interruptions

    def interruption_options(self, controller) -> dict:
        """Everything an interruption may point at, asked of the live devices.

        Same principle as scene_options: the editor offers what actually
        exists, so a card cannot be saved naming a clip that is not there.
        """
        def safe(fn, fallback=None):
            try:
                return list(fn())
            except Exception:              # noqa: BLE001
                return list(fallback or [])

        return {
            "audio": safe(controller.audio.available_tracks),
            "lights": safe(controller.lights.available_patterns),
            "backgrounds": safe(controller.background_choices),
            "fallback_s": self.config.fallback_interruption_s,
        }

    def list_interruptions(self) -> List[dict]:
        """Every interruption, with what points at it."""
        out = []
        with self._lock:
            for name in sorted(self.config.interruptions):
                i = self.config.interruptions[name]
                out.append({
                    "name": name,
                    "audio": i.audio,
                    "lights": i.lights,
                    "background": i.background,
                    "duck": i.duck,
                    "duration_s": i.duration_s,
                    "used_by": self.usage_of("interruption", name),
                })
        return out

    def set_interruption(self, name, audio=None, lights=None, background=None,
                         duck=None, duration_s=None, options=None) -> dict:
        """Create or update an interruption.

        UNLIKE A SCENE, lights are optional -- `None` means "leave the
        current lighting alone", which is a real and useful card: a sound
        over whatever is already showing. So the requirement cannot be "must
        have lights"; it is that the card must do SOMETHING. An interruption
        with no audio, no lights and no background is a tap that produces
        nothing and explains nothing, which is exactly the failure the
        referential-integrity rule exists to prevent.
        """
        name = (name or "").strip().lower().replace(" ", "_")
        if not name:
            raise ConfigError("interruption name is required")
        if not NAME_OK.match(name):
            raise ConfigError("interruption name may only use letters, "
                              "numbers, dash and underscore")

        audio = (audio or "").strip() or None
        lights = (lights or "").strip() or None
        background = (background or "").strip() or None

        if not (audio or lights or background):
            raise ConfigError(
                "an interruption needs at least one of a sound, a lighting "
                "pattern or a map -- otherwise tapping the card does nothing")

        if duration_s in ("", None):
            duration_s = None
        else:
            try:
                duration_s = float(duration_s)
            except (TypeError, ValueError):
                raise ConfigError("duration must be a number of seconds")
            if duration_s <= 0:
                raise ConfigError("duration must be greater than zero")

        if options:
            if audio and options.get("audio") and audio not in options["audio"]:
                raise ConfigError("no sound named %r" % audio)
            if lights and options.get("lights")                     and lights not in options["lights"]:
                raise ConfigError("no lighting pattern named %r" % lights)
            if background and options.get("backgrounds")                     and background not in options["backgrounds"]:
                raise ConfigError("no map named %r" % background)

        existing = self.config.interruptions.get(name)
        if duck is None:
            duck = existing.duck if existing else True

        def mutate():
            self.config.interruptions[name] = Interruption(
                name=name, audio=audio, lights=lights, background=background,
                duck=bool(duck), duration_s=duration_s)
            return "updated" if existing else "created"

        action = self._with_rollback("interruption", mutate, name=name)
        return {"name": name, "action": action}

    def delete_interruption(self, name: str) -> None:
        """Remove an interruption. Refuses if a card still points at it."""
        name = (name or "").strip()
        if name not in self.config.interruptions:
            raise ConfigError("no interruption named %r" % name)

        users = self.usage_of("interruption", name)
        if users:
            raise ConfigError(
                "%r is still used by %d card(s): %s"
                % (name, len(users), ", ".join(users[:4])))

        def mutate():
            del self.config.interruptions[name]
            return "deleted"

        self._with_rollback("interruption", mutate, name=name)

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
