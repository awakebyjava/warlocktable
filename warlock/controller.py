"""The Controller — owns every action, per plan doc section 4 (Central
Controller pattern) and 4.3 (Interaction Model).

Every input (a card tap, a panel button, later voice/VTT/dice) ends up
calling a method on this one class. That is deliberate: a card and a
panel button firing the identical action with zero duplicated logic is
the whole point of the architecture (plan doc section 4, "why this
matters").

Precedence rule (4.3): last input wins, flat. Concretely, that means every
action here starts by cancelling any pending revert-after-interruption
timer — whatever just happened supersedes whatever was about to happen.
"""

from __future__ import annotations

import random
import threading
import time
from typing import List, Optional

from .config import Config, Interruption, Scene, Target
from .devices.base import (AudioDevice, DeviceError, DisplayDevice,
                           LightDevice, STATUS_SCREEN, UnknownAssetError)
from .eventlog import EventLog
from . import zones as zonemap
from .initiative import Initiative
from .registry import ParamSpec, action


class Controller:
    def __init__(self, config: Config, lights: LightDevice, audio: AudioDevice,
                 display: DisplayDevice, log: EventLog):
        self.config = config
        self.lights = lights
        self.audio = audio
        self.display = display
        self.log = log

        self.current_scene: Optional[Scene] = None
        self._revert_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

        # Combat order. In memory only, and deliberately so — see the note
        # at the top of warlock/initiative.py.
        self.initiative = Initiative()
        # Restores the scene after flash_player(). Separate from the
        # interruption revert timer so the two cannot cancel each other.
        self._flash_timer = None

        # Player signals -- the `?` and `!` from a phone (plan doc 3.7).
        # In memory only: a signal is meaningless sixty seconds after it is
        # raised, by its own definition, so there is nothing to persist and
        # writing it would be SD wear for nothing.
        #
        # Its own lock. _lock guards the revert timer, and taking two locks
        # in inconsistent orders is how you get a deadlock nobody can
        # reproduce.
        self._signals = {}                    # colour -> {kind, name, at}
        self._signals_lock = threading.Lock()

        # Whispers: one private thread per player, keyed by seat colour
        # (plan doc 3.7). There is no public channel and there will not be
        # one -- a player's thread is between them and the GM.
        #
        # In memory, but ALSO written to the session log while recording,
        # which is a decision with a consequence: private messages end up
        # on the SD card. Recorded in the spec so it is a choice rather
        # than something discovered later.
        self._whispers = {}                   # colour -> [ {from, text, at} ]
        self._whispers_lock = threading.Lock()

        # Dice rolls, per player (plan doc 3.7). Both the player and the GM
        # keep a record; while recording, each roll also reaches the
        # session log with an offset so a transcript can line it up.
        self._rolls = {}                      # colour -> [ {n, sides, total} ]
        self._rolls_lock = threading.Lock()

        # Per-subsystem health, for the panel status strip and the TV status
        # screen (plan doc 5.1). A subsystem going unhealthy must never stop
        # the others — see _try below.
        self.subsystem_ok = {"lights": True, "audio": True, "display": True,
                             "govee": True}

        # Govee accent strips (plan doc 3.13). Assigned by runtime.py after
        # construction; a fake stands in when they are not configured, so
        # nothing here has to check whether they exist.
        self.govee = None

    # ---- internal: fault isolation (plan doc 5.2) ------------------------

    def _try(self, subsystem: str, fn, *args, **kwargs) -> bool:
        """Call a device method, absorbing device failures.

        Plan doc 5.2: "lights down != sound down != panel down". Every device
        call goes through here so one failing device degrades that subsystem
        only, and the table keeps running.

        Two distinct failure kinds, deliberately handled differently:
          - UnknownAssetError: the device is fine, the *config* asked for
            something that doesn't exist. Health is untouched; this is a
            content bug to fix in the management UI.
          - DeviceError: the device itself is unreachable or broken. Mark the
            subsystem unhealthy so the status strip can show it.

        Returns True if the call succeeded.
        """
        try:
            fn(*args, **kwargs)
        except UnknownAssetError as exc:
            self.log.record("action.missing_asset", subsystem=subsystem, error=str(exc))
            return False
        except DeviceError as exc:
            if self.subsystem_ok.get(subsystem, True):
                self.log.record("subsystem.unhealthy", subsystem=subsystem, error=str(exc))
            self.subsystem_ok[subsystem] = False
            return False
        except Exception as exc:  # noqa: BLE001 - a driver bug must not kill the table
            self.log.record("subsystem.error", subsystem=subsystem,
                             error="%s: %s" % (type(exc).__name__, exc))
            self.subsystem_ok[subsystem] = False
            return False

        if not self.subsystem_ok.get(subsystem, True):
            self.log.record("subsystem.recovered", subsystem=subsystem)
        self.subsystem_ok[subsystem] = True
        return True

    # How long to wait for the slowest subsystem before returning. Generous:
    # every device already bounds its own sockets, so this only catches a
    # driver that hangs outright, and a card tap must never wedge the panel.
    FANOUT_JOIN_S = 5.0

    def _fanout(self, *jobs) -> None:
        """Run device calls CONCURRENTLY. Each job is (subsystem, fn, *args).

        Serial dispatch was the largest software cost in the whole chain,
        measured 2026-08-22 (plan doc 5.7): set_pattern blocks for ~480ms --
        270-320ms of it the Pixelblaze loading bytecode -- and audio and
        the picture were queued behind it. So a card tap answered in three
        instalments spread over about two seconds, which is the stagger
        that was reported from the table.

        Nothing is delayed to make them land together. Deliberately: the
        goal is fast and close, not synchronised, and padding the quick
        subsystems to meet the slow one would trade the thing you notice
        (lag) for the thing you mostly do not (a quarter-second skew).

        Fault isolation is unchanged -- each job goes through _try, which
        absorbs its own failures, so one dead device still cannot take the
        others down.
        """
        threads = []
        for job in jobs:
            subsystem, fn = job[0], job[1]
            t = threading.Thread(target=self._try, args=(subsystem, fn) + tuple(job[2:]),
                                 name="fanout-" + subsystem, daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout=self.FANOUT_JOIN_S)

    # ---- session log: what happened, beside the recording ----------------

    def _session_log(self, kind: str, **fields) -> None:
        """Write one event to the recording's companion log, if recording.

        Never raises and never reports: play carries on whether or not the
        microphone is running, and an event that cannot be written is not a
        reason to fail the thing that produced it.
        """
        mic = self._mic()
        logger = getattr(mic, "log_event", None)
        if not callable(logger):
            return
        try:
            logger(kind, **fields)
        except Exception:      # noqa: BLE001
            pass

    # ---- whispers (plan doc 3.7) -----------------------------------------

    WHISPER_MAX = 200          # per thread; an evening, not a lifetime

    def whisper(self, colour: str, text: str, sender: str = "player",
                name: str = "") -> dict:
        """Add a message to one player's thread. Both directions.

        Keyed by seat colour because that is the identity the phone
        already holds and the one the player can see lit in front of them.
        Worth being plain about the limit: anyone who knows a colour could
        read that thread. On a LAN table with six people in the room that
        is not a threat model, but it is not privacy either, and it should
        not be described as such.
        """
        colour = (colour or "").strip().lower()
        text = (text or "").strip()
        if not colour:
            raise ValueError("a seat colour is needed")
        if not text:
            raise ValueError("an empty whisper is not a whisper")
        if sender not in ("player", "gm"):
            raise ValueError("sender must be player or gm")
        text = text[:500]
        msg = {"from": sender, "text": text, "at": time.time()}
        with self._whispers_lock:
            thread = self._whispers.setdefault(colour, [])
            thread.append(msg)
            # Trim from the front: a long evening should cost memory that
            # stops growing, and the oldest line is the one nobody rereads.
            if len(thread) > self.WHISPER_MAX:
                del thread[:len(thread) - self.WHISPER_MAX]
            out = {"colour": colour, "messages": list(thread)}
        self.log.record("whisper", colour=colour, sender=sender,
                        chars=len(text))
        self._session_log("whisper", colour=colour, sender=sender,
                          name=name, text=text)
        return out

    def whisper_thread(self, colour: str) -> dict:
        colour = (colour or "").strip().lower()
        if colour == self.GM_KEY:
            # Same reasoning as roll_history: no thread is addressed to
            # this key, but refusing it explicitly beats relying on that.
            return {"colour": colour, "messages": []}
        with self._whispers_lock:
            return {"colour": colour,
                    "messages": list(self._whispers.get(colour, []))}

    def whisper_threads(self) -> dict:
        """Every thread, for the GM. Players never call this."""
        seated = {z.colour: p.name
                  for z in self.config.zones
                  for p in self.config.players
                  if p.zone_id == z.id}
        with self._whispers_lock:
            return {"threads": [
                {"colour": c,
                 "name": seated.get(c, ""),
                 "messages": list(msgs),
                 "last_from": msgs[-1]["from"] if msgs else None,
                 "last_at": msgs[-1]["at"] if msgs else 0}
                for c, msgs in sorted(self._whispers.items())]}

    @action()
    def clear_whispers(self) -> None:
        """Wipe every thread. For the end of a session, or a fresh table."""
        with self._whispers_lock:
            n = len(self._whispers)
            self._whispers = {}
        self.log.record("whispers_cleared", threads=n)

    # ---- dice (plan doc 3.7) ---------------------------------------------

    # WHAT MAY BE ROLLED, which is NOT the same list as what the interface
    # SHOWS. That distinction is new as of 2026-08-24 and is the thing to
    # understand before adding another die.
    #
    # The six shapes on the pad are a system-agnostic default: a number and
    # a die, no modifiers, nothing that assumes a ruleset. d100 is not on
    # that pad and should not be. But BRP -- Call of Cthulhu, RuneQuest --
    # resolves everything by rolling under a skill on 1d100, so its preset
    # panel was shipping without the roll its players make most.
    #
    # A d100 is one die reporting one number in 1..100. It is not the
    # percentile PAIR (two d10s read as tens and units), which was rejected
    # along with modifiers and stays rejected: a pair with a reading
    # convention is where encoding somebody's rules starts.
    #
    # So: allowed here, absent from the pad, present in the BRP preset
    # panel. To add another die, put it in this tuple and then decide
    # separately whether it earns a place on the pad -- the frontends keep
    # their own lists (`GM_DICE` in app.js, `DICE` in player.html) and do
    # not read this one, precisely so the two can differ.
    DICE = (4, 6, 8, 10, 12, 20, 100)
    # The GM rolls too, and has no seat. Their rolls land in the GM's own
    # log and nowhere else -- players read only their own thread of rolls,
    # so this is behind the screen by construction rather than by a rule
    # somebody has to remember to enforce.
    GM_KEY = "gm"
    MAX_DICE = 100             # see roll(); a rail, not a rule
    ROLL_HISTORY = 500         # per player
    ROLL_SHOW_DICE = 12        # individual dice printed in a roll label

    def roll(self, colour: str, count: int, sides: int, name: str = "") -> dict:
        """Roll `count` dice of `sides`, record it, return the whole roll.

        Deliberately system-agnostic: a number and a die, no modifiers and
        no d100. The moment there are modifiers this starts encoding
        somebody's rules, and the table does not know what game you are
        playing.

        MAX_DICE exists because nothing stops a thumb entering 9999 on a
        phone. It is a guard against a fat finger, not a judgement about
        how many dice a game may need -- raise it freely.
        """
        colour = (colour or "").strip().lower()
        if not colour:
            raise ValueError("a seat colour is needed")
        try:
            count, sides = int(count), int(sides)
        except (TypeError, ValueError):
            raise ValueError("count and sides must be numbers")
        if sides not in self.DICE:
            raise ValueError("no d%s at this table (have: %s)"
                             % (sides, ", ".join("d%d" % d for d in self.DICE)))
        if count < 1 or count > self.MAX_DICE:
            raise ValueError("roll between 1 and %d dice" % self.MAX_DICE)

        dice = [random.randint(1, sides) for _ in range(count)]
        total = sum(dice)

        # The individual dice, in parentheses after the total. They were
        # always recorded and never shown, which made a pool roll
        # unauditable at exactly the table where somebody wants to see the
        # two sixes -- "4d6=14" is a number to take on trust, and
        # "4d6=14 (6, 6, 1, 1)" is a roll you watched.
        #
        # Not shown for a single die, where the parenthetical would only
        # repeat the total. Truncated past a dozen, because the label lands
        # in a narrow log column and nobody reads the 40th d6 individually
        # -- the full list stays in `dice` for anything that wants it.
        shown = ""
        if count > 1:
            if count <= self.ROLL_SHOW_DICE:
                shown = " (%s)" % ", ".join(str(d) for d in dice)
            else:
                shown = " (%s, +%d more)" % (
                    ", ".join(str(d) for d in dice[:self.ROLL_SHOW_DICE]),
                    count - self.ROLL_SHOW_DICE)

        entry = {"n": count, "sides": sides, "dice": dice,
                 "total": total, "at": time.time(),
                 # The spec's format, built once here rather than in each
                 # of the three places that display it.
                 "label": "%dd%d=%d%s" % (count, sides, total, shown)}
        with self._rolls_lock:
            log = self._rolls.setdefault(colour, [])
            log.append(entry)
            if len(log) > self.ROLL_HISTORY:
                del log[:len(log) - self.ROLL_HISTORY]
        self.log.record("dice.roll", colour=colour, roll=entry["label"])
        self._session_log("roll", colour=colour, name=name,
                          roll=entry["label"], dice=dice)
        return entry

    def roll_history(self, colour: str) -> dict:
        """One player's own rolls. Never the GM's.

        The phone only ever asks for its own colour, so in practice a GM
        roll never reached a player anyway -- but "the client does not ask"
        is not the same as "cannot be had", and anyone who typed
        ?colour=gm into a browser would have had the lot. The guard makes
        the claim true instead of merely usually-true.
        """
        colour = (colour or "").strip().lower()
        if colour == self.GM_KEY:
            return {"colour": colour, "rolls": []}
        with self._rolls_lock:
            return {"colour": colour, "rolls": list(self._rolls.get(colour, []))}

    def roll_log(self, limit: int = 60) -> dict:
        """Every player's rolls, newest first. The GM's record."""
        seated = {z.colour: p.name
                  for z in self.config.zones
                  for p in self.config.players
                  if p.zone_id == z.id}
        seated[self.GM_KEY] = "GM"
        rows = []
        with self._rolls_lock:
            for colour, entries in self._rolls.items():
                for e in entries:
                    rows.append({"colour": colour,
                                 "name": seated.get(colour, ""),
                                 "label": e["label"], "at": e["at"]})
        rows.sort(key=lambda r: r["at"], reverse=True)
        return {"rolls": rows[:max(1, int(limit))]}

    @action()
    def clear_rolls(self) -> None:
        """Wipe every roll log. End of session, or a fresh table."""
        with self._rolls_lock:
            n = sum(len(v) for v in self._rolls.values())
            self._rolls = {}
        self.log.record("dice.cleared", rolls=n)

    # ---- player signals (plan doc 3.7) -----------------------------------

    SIGNAL_TTL_S = 60.0
    SIGNAL_KINDS = ("question", "need")

    def _live_signals(self):
        """Drop anything past its life. Caller holds the lock.

        Expiry is computed on READ rather than run off a timer. Sixty
        one-shot timers competing with the revert timer is a lot of moving
        parts for something a comparison against a clock settles, and a
        timer that fires after a service restart does not exist to fire.
        """
        cutoff = time.time() - self.SIGNAL_TTL_S
        for colour in [c for c, r in self._signals.items() if r["at"] < cutoff]:
            del self._signals[colour]
        return self._signals

    def raise_signal(self, colour: str, kind: str, name: str = "") -> dict:
        """A player pressing `?` or `!`.

        NOT an @action. The registry is the GM's vocabulary and the panel
        builds its buttons from it; a player-initiated signal has no
        business putting a button on the GM's screen.

        Pressing the SAME one again takes it back -- a player who sorts it
        out themselves should not have to wait for the GM to notice. A
        different one replaces it, because a player wanting both at once is
        not a thing that needs modelling.
        """
        colour = (colour or "").strip().lower()
        kind = (kind or "").strip().lower()
        if not colour:
            raise ValueError("a seat colour is needed")
        if kind not in self.SIGNAL_KINDS:
            raise ValueError("kind must be one of %s" % (self.SIGNAL_KINDS,))
        with self._signals_lock:
            live = self._live_signals()
            existing = live.get(colour)
            if existing and existing["kind"] == kind:
                del live[colour]
                out = self._snapshot(live)
                action = "lowered"
            else:
                live[colour] = {"kind": kind, "name": (name or "").strip()[:24],
                                "at": time.time()}
                out = self._snapshot(live)
                action = "raised"
        # `mark`, not `kind`: EventLog.record()'s own first parameter is
        # named kind, so a field by that name is a TypeError at the call.
        self.log.record("player.signal", colour=colour, mark=kind, action=action)
        return out

    def clear_signal(self, colour: str = "") -> dict:
        """The GM acknowledging one, or all of them."""
        colour = (colour or "").strip().lower()
        with self._signals_lock:
            live = self._live_signals()
            if colour:
                live.pop(colour, None)
            else:
                live.clear()
            out = self._snapshot(live)
        self.log.record("player.signal_cleared", colour=colour or "all")
        return out

    def signal_report(self) -> dict:
        with self._signals_lock:
            return self._snapshot(self._live_signals())

    def _snapshot(self, live):
        now = time.time()
        return {"signals": [
            {"colour": c, "kind": r["kind"], "name": r["name"],
             # What the panel needs to fade one out as it ages, without
             # every client having to agree about the wall clock.
             "age_s": round(now - r["at"], 1)}
            for c, r in sorted(live.items())]}

    def status(self) -> dict:
        """What the panel status strip and TV status screen render (5.1)."""
        return {
            "subsystems": dict(self.subsystem_ok),
            "scene": self.current_scene.name if self.current_scene else None,
            # Rides on the poll the panel already does, rather than adding a
            # second one just for this.
            "signals": self.signal_report()["signals"],
        }

    # ---- internal: precedence ------------------------------------------

    def _supersede(self, stop_effects: bool = False) -> None:
        """Cancel anything that was scheduled to happen later. Called at
        the top of every public action — see the module docstring.

        stop_effects also silences any playing one-shot. That is deliberately
        opt-in rather than automatic: changing the scene should cut a sting
        short, but nudging the brightness should not. Without it the lights
        change instantly while the sting plays on to its own schedule, so the
        table answers in two halves — picture, then sound.
        """
        with self._lock:
            if self._revert_timer is not None:
                self._revert_timer.cancel()
                self._revert_timer = None
        if stop_effects:
            self._try("audio", self.audio.stop_effects)

    # ---- targets: the three things a card/table entry can point at -----

    @action(ParamSpec("scene_name", "str", choices=lambda c: list(c.config.scenes)))
    def apply_scene(self, scene_name: str) -> None:
        """Enter a persisting state. Stays until something replaces it."""
        # stop_effects: a new scene cuts a playing sting short, so lights and
        # sound change together rather than the audio trailing behind.
        self._supersede(stop_effects=True)
        scene = self.config.scenes[scene_name]
        self.current_scene = scene
        self.log.record("scene.apply", name=scene_name)
        self._session_log("scene", name=scene_name)
        # Each subsystem is attempted independently and CONCURRENTLY: a dead
        # Pixelblaze must not stop the soundscape (plan doc 5.2), and the
        # soundscape must not wait half a second for the lights (5.7).
        jobs = [("lights", self.lights.set_pattern, scene.lights),
                ("audio", self.audio.play_soundscape, scene.soundscape,
                 scene.transition.crossfade_s)]
        if scene.background:
            jobs.append(("display", self.display.set_background, scene.background))
        if self.govee is not None:
            # Scenes only, never cards: an Aura is 4-9s and a UDP command
            # with no acknowledgement is not something to hang a sting on
            # (plan doc 3.13).
            jobs.append(("govee", self.govee.set_scene, scene_name))
        self._fanout(*jobs)

    @action(ParamSpec("interruption_name", "str",
                       choices=lambda c: list(c.config.interruptions)))
    def play_interruption(self, interruption_name: str) -> None:
        """Layer over whatever is currently playing, then revert to it
        once the audio finishes (plan doc 4.3)."""
        self._supersede(stop_effects=True)
        interruption = self.config.interruptions[interruption_name]
        self.log.record("interruption.start", name=interruption_name,
                         reverts_to=self.current_scene.name if self.current_scene else None)
        self._session_log("card", name=interruption_name,
                          over=self.current_scene.name if self.current_scene else None)

        jobs = []
        if interruption.lights:
            jobs.append(("lights", self.lights.set_pattern, interruption.lights))
        if interruption.background:
            jobs.append(("display", self.display.set_background,
                         interruption.background))
        if jobs:
            self._fanout(*jobs)

        # play_effect returns the duration we need for the revert timer, so
        # it can't go through _try (which discards return values). Guard it
        # directly, and still schedule a revert if audio failed — otherwise a
        # broken audio device would strand the table in the interruption's
        # lighting with nothing to bring it back.
        duration = 0.0
        if not interruption.audio:
            # Lights-only. duration_s is the whole timing story, so an
            # interruption without it would never revert.
            duration = interruption.duration_s or self.config.fallback_interruption_s
            self._schedule_revert(interruption_name, duration)
            return
        try:
            duration = self.audio.play_effect(interruption.audio,
                                               duck=interruption.duck,
                                               max_duration=interruption.duration_s)
            self.subsystem_ok["audio"] = True
        except UnknownAssetError as exc:
            self.log.record("action.missing_asset", subsystem="audio", error=str(exc))
        except DeviceError as exc:
            self.log.record("subsystem.unhealthy", subsystem="audio", error=str(exc))
            self.subsystem_ok["audio"] = False

        if not duration:
            duration = self.config.fallback_interruption_s

        # THE LIGHTS DECIDE THE LENGTH, NOT THE CLIP. play_effect returns the
        # audio's own duration, and letting that drive the revert means a
        # short clip cuts the visual off mid-gesture: the Auras are built
        # with a release that fades them out over their last second or so,
        # and a 3s howl on a 9s aura would kill the light before it got
        # there. Whoever sources a sound would be silently deciding how long
        # the pattern runs.
        #
        # A LONG clip is already handled -- play_effect was passed
        # duration_s as max_duration, so it returns no more than that.
        if interruption.duration_s:
            duration = max(duration, interruption.duration_s)

        self._schedule_revert(interruption_name, duration)

    def _schedule_revert(self, interruption_name: str, duration: float) -> None:
        scene_to_restore = self.current_scene

        def revert():
            self.log.record("interruption.revert", name=interruption_name,
                             to=scene_to_restore.name if scene_to_restore else "idle")
            if scene_to_restore:
                # Re-apply directly rather than calling apply_scene(), so
                # we don't clear a timer another action may have set since.
                jobs = [("lights", self.lights.set_pattern, scene_to_restore.lights),
                        ("audio", self.audio.play_soundscape,
                         scene_to_restore.soundscape,
                         scene_to_restore.transition.crossfade_s)]
                if scene_to_restore.background:
                    jobs.append(("display", self.display.set_background,
                                 scene_to_restore.background))
                if self.govee is not None:
                    jobs.append(("govee", self.govee.set_scene,
                                 scene_to_restore.name))
                self._fanout(*jobs)
            else:
                self.go_idle()

        with self._lock:
            self._revert_timer = threading.Timer(duration, revert)
            self._revert_timer.daemon = True
            self._revert_timer.start()

    @action(ParamSpec("table_name", "str",
                       choices=lambda c: list(c.config.random_tables)))
    def roll_table(self, table_name: str) -> None:
        """Pick one of the table's entries at random and dispatch to it.
        Stateless — no memory of past rolls (plan doc 4.3)."""
        table = self.config.random_tables[table_name]
        choice: Target = random.choice(table.entries)
        self.log.record("table.roll", table=table_name,
                         result_kind=choice.kind, result_name=choice.name)
        self._dispatch(choice)

    def _dispatch(self, target: Target) -> None:
        if target.kind == "scene":
            self.apply_scene(target.name)
        elif target.kind == "interruption":
            self.play_interruption(target.name)
        elif target.kind == "random_table":
            self.roll_table(target.name)
        else:
            raise ValueError("unknown target kind %r" % target.kind)

    # ---- cards -----------------------------------------------------------

    def handle_card(self, uid_or_label: str) -> bool:
        """Simulates an NFC tap. Returns False for an unregistered card —
        the real input layer would surface that in the panel as
        'unassigned, ready to register' (plan doc 4.5) rather than just
        printing into a terminal nobody reads, as V1 did."""
        card = self.config.find_card(uid_or_label)
        if card is None:
            self.log.record("card.unregistered", scanned=uid_or_label)
            return False
        self.log.record("card.tap", uid=card.uid, label=card.label)
        self._dispatch(card.target)
        return True

    # ---- primitives: what the panel drives directly (plan doc 4.5) ------

    @action(ParamSpec("pattern", "str", choices=lambda c: c.lights.available_patterns()))
    def set_lights(self, pattern: str) -> None:
        self._supersede()
        self._try("lights", self.lights.set_pattern, pattern)

    @action(ParamSpec("track", "str", choices=lambda c: c.audio.available_tracks()))
    def set_soundscape(self, track: Optional[str]) -> None:
        self._supersede()
        crossfade = (self.current_scene.transition.crossfade_s
                     if self.current_scene else 1.5)
        self._try("audio", self.audio.play_soundscape, track, crossfade)

    @action(ParamSpec("name", "str", choices=lambda c: c.background_choices()))
    def set_background(self, name: str) -> None:
        self._supersede()
        # The status screen is offered in the same list as the artwork,
        # because from the panel it is the same decision: what is on the
        # television. It cannot go through the display's own
        # set_background, though -- it has to be RENDERED first, from live
        # status the device knows nothing about.
        if name == STATUS_SCREEN:
            self.show_status_screen()
            return
        self._try("display", self.display.set_background, name)

    def background_choices(self) -> List[str]:
        """What the panel may pick. Never raises: an empty picker is a
        nuisance, an action registry that blows up is a dead panel."""
        lister = getattr(self.display, "available_backgrounds", None)
        if not callable(lister):
            return [STATUS_SCREEN]
        try:
            return list(lister())
        except Exception:      # noqa: BLE001
            return [STATUS_SCREEN]

    @action(ParamSpec("track", "str", choices=lambda c: c.audio.available_tracks()))
    def play_effect(self, track: str) -> None:
        self._supersede()
        self._try("audio", self.audio.play_effect, track, True)

    @action(ParamSpec("line", "str"))
    def speak_line(self, line: str) -> None:
        """Table voice — plan doc 3.5. Routed through the effect channel
        with ducking, same as any other one-shot layered over ambience."""
        self._supersede()
        self.log.record("voice.speak", line=line)
        self._try("audio", self.audio.play_effect, line, True)

    @action(ParamSpec("level", "float"))
    def set_brightness(self, level: float) -> None:
        self._supersede()
        self._try("lights", self.lights.set_brightness, level)

    @action(ParamSpec("level", "float"))
    def set_volume(self, level: float) -> None:
        """Master audio level, 0.0-1.0.

        Deliberately NOT a _supersede action, same reasoning as set_overlay:
        nudging the volume mid-scene is a preference, not a scene change,
        and must not cancel a pending interruption revert.
        """
        level = max(0.0, min(1.0, float(level)))
        self._try("audio", self.audio.set_volume, level)
        self._persist_audio(volume=level)

    @action(ParamSpec("name", "str",
                      choices=lambda c: sorted(c.config.audio_outputs)))
    def set_audio_output(self, name: str) -> None:
        """Send sound to a named output, e.g. the speakers or the TV.

        Takes a NAME from config rather than a raw ALSA string, so the panel
        offers "Television" and the device string stays a config detail. It
        also means an unknown name is refused here rather than becoming a
        failed mixer init on the far side.
        """
        device = self.config.audio_outputs.get(name)
        if device is None:
            raise ValueError(
                "no audio output named %r (have: %s)"
                % (name, ", ".join(sorted(self.config.audio_outputs)) or "none"))
        if not self._try("audio", self.audio.set_output, device):
            # _try has already marked audio unhealthy and logged why. Do not
            # persist a device that would not open, or the next restart
            # comes up silent.
            return
        self._persist_audio(device=device)
        self.log.record("audio.output_changed", name=name, device=device)

    def _persist_audio(self, volume=None, device=None) -> None:
        store = getattr(getattr(self, "_runtime", None), "store", None)
        if store is None:
            # Interactive CLI with nothing to save to: honour it in memory.
            if volume is not None:
                self.config.volume = volume
            if device is not None:
                self.config.audio_device = device
            return
        try:
            store.set_audio(volume=volume, device=device)
        except Exception as exc:   # noqa: BLE001
            # A failed write must not undo a change the operator can hear.
            self.log.record("audio.persist_failed", error=str(exc))

    def audio_report(self) -> dict:
        """What the panel's volume slider and output switch render from."""
        status = {}
        probe = getattr(self.audio, "status", None)
        if callable(probe):
            try:
                status = probe()
            except Exception:   # noqa: BLE001
                status = {}
        current = status.get("device_requested") or self.config.audio_device
        outputs = dict(self.config.audio_outputs)
        return {
            "volume": self.config.volume,
            "outputs": sorted(outputs),
            "current": next((n for n, d in outputs.items() if d == current),
                            None),
            "device": current,
        }

    @action(ParamSpec("target", "str"))
    def handoff_display(self, target: str) -> None:
        self._supersede()
        self._try("display", self.display.handoff, target)

    @action()
    def show_status_screen(self) -> None:
        """Put the system status on the table's own screen.

        Deliberately available as an action so it can be summoned from the
        panel — but its real value is at boot, when there may be no panel
        and a blank screen is indistinguishable from a crash.
        """
        shower = getattr(self.display, "show_status", None)
        if not callable(shower):
            self.log.record("display.status_unsupported")
            return
        from .statusscreen import build_report
        rt = getattr(self, "_runtime", None)
        if rt is None:
            self.log.record("display.status_unsupported", reason="no runtime")
            return

        # Table Check (plan doc 5.4) is sub-second without --physical, so
        # there is no reason the boot screen should settle for a plain
        # device-alive rollup when the real thing is this cheap to run.
        # Device probes alone stay green while a scene points at a pattern
        # that no longer exists on the Pixelblaze -- exactly the failure
        # tablecheck exists to catch -- so a table in that state used to
        # look perfectly healthy on its own screen.
        #
        # Best-effort: a check that errors or hangs must not be the reason
        # the status screen fails to show at all.
        check = None
        try:
            from .tablecheck import run_check
            check = run_check(rt, physical=False)
        except Exception as exc:   # noqa: BLE001
            self.log.record("display.status_check_failed", error=str(exc))

        self._try("display", shower, build_report(rt, check),
                   getattr(self, "_branding_path", None))

    @action(ParamSpec("mode", "str",
                       choices=lambda c: (c.display.available_overlays()
                                          if hasattr(c.display, "available_overlays")
                                          else ["none", "grid", "hex"])))
    def set_overlay(self, mode: str) -> None:
        """Choose the map overlay on the table screen: none, grid, or hex.

        A mode rather than a boolean because there are three states now and
        may be more. Deliberately NOT a _supersede action: this is a display
        preference, not a scene change, so changing it mid-combat must not
        cancel a pending interruption revert.
        """
        self._try("display", self.display.set_overlay, mode)

    # `whisper` used to be a stub @action here that logged a line and
    # delivered nothing. The real implementation is further up, is not an
    # action, and is reached through /api/whispers/reply -- a private
    # message to one player has no business being a generic button in the
    # GM's action vocabulary, next to "set brightness".
    #
    # It also silently SHADOWED the real one: defined later in the class,
    # it simply won, and every whisper call hit the stub. Caught by tests
    # before it shipped, and worth the note so nobody re-adds it.

    # ---- system ------------------------------------------------------

    @action()
    def go_idle(self) -> None:
        """The resting state: breathing lights, no audio (plan doc 4.3).
        Also what runs at boot, per the startup sequence in 5.1.

        Reads the idle scene from config rather than hardcoding a pattern
        name — the pattern was previously baked in here, which is exactly
        the anti-pattern the config-driven design exists to prevent.
        """
        self._supersede(stop_effects=True)
        self.log.record("go_idle")

        idle = self.config.scenes.get(self.config.idle_scene_name)
        if idle is None:
            # Never leave the table in an undefined state: fall back to
            # dark and silent rather than refusing to idle at all.
            self.log.record("go_idle.no_scene", wanted=self.config.idle_scene_name)
            self.current_scene = None
            self._try("audio", self.audio.play_soundscape, None, 1.5)
            return

        self.current_scene = idle
        jobs = [("audio", self.audio.play_soundscape, idle.soundscape,
                 idle.transition.crossfade_s)]
        if idle.lights:
            jobs.append(("lights", self.lights.set_pattern, idle.lights))
        if idle.background:
            jobs.append(("display", self.display.set_background, idle.background))
        if self.govee is not None:
            jobs.append(("govee", self.govee.set_scene,
                         self.config.idle_scene_name))
        self._fanout(*jobs)

    # ---- zones (plan doc 4.7) --------------------------------------------

    def zone_colours(self) -> List[tuple]:
        """HSV per zone id, [0] the GM then each seat, ready for the device.

        Colour NAMES live in config so the panel can offer them and a player
        can claim one; the device only ever sees HSV. Translating here keeps
        that split at the controller, where every other config-to-device
        decision already happens.
        """
        out = [zonemap.hsv_for(zonemap.GM_COLOUR)]
        by_id = {z.id: z.colour for z in self.config.zones}
        for zone_id in range(1, self.config.player_count + 1):
            out.append(zonemap.hsv_for(
                by_id.get(zone_id, zonemap.seat_colour(zone_id))))
        return out

    @action()
    def show_seat_colours(self) -> None:
        """Light every seat in its own colour, for claiming.

        A mode, not a flash: it stays up while people pick their seats, and
        is left by applying any scene or going idle. Deliberately does NOT
        restore the previous pattern on its own — Table Check flashes and
        restores because it interrupts a running session, whereas this is
        the thing the operator wants to look at until they are done with it.
        """
        if not self.lights.supports_zones():
            self.log.record("lights.zones_unsupported")
            return
        gm_start, gm_len = zonemap.gm_span()
        self._supersede()
        self._try("lights", self.lights.show_zones,
                  self.config.player_count, self.zone_colours(),
                  gm_start, gm_len)

    @action(ParamSpec("count", "float"))
    def set_player_count(self, count: int) -> None:
        """How many players are seated, 1-7. The GM is not counted.

        Changing this re-divides the whole table, so it re-lights the seats
        immediately: the only way to confirm the division is right is to
        look at the table, and a setting that changes nothing visible is
        one nobody can check.
        """
        count = int(count)
        if not 1 <= count <= zonemap.MAX_PLAYERS:
            raise ValueError("player count must be between 1 and %d"
                             % zonemap.MAX_PLAYERS)

        store = getattr(getattr(self, "_runtime", None), "store", None)
        if store is not None:
            store.set_player_count(count)      # persists, or raises
        else:
            # No store: an interactive CLI session with nothing to save to.
            # Still honour the change in memory rather than refusing it.
            self.config.player_count = count
        self.log.record("zones.player_count", count=count)

        if self.lights.supports_zones():
            self.show_seat_colours()

    @action(ParamSpec("zone", "float"),
            ParamSpec("colour", "str",
                      choices=lambda c: sorted(zonemap.COLOUR_HSV)))
    def set_zone(self, zone: int, colour: str) -> None:
        """Recolour one seat, leaving the others alone.

        The per-turn operation: initiative lighting moves a highlight round
        the table every turn, so this must not resend the whole layout.
        """
        zone = int(zone)
        if not 0 <= zone <= self.config.player_count:
            raise ValueError("zone %d does not exist with %d players"
                             % (zone, self.config.player_count))
        if not self.lights.supports_zones():
            self.log.record("lights.zones_unsupported")
            return
        self._try("lights", self.lights.set_zone_colour,
                  zone, zonemap.hsv_for(colour))

    def zone_report(self) -> dict:
        """What the panel renders: every zone, its colour, size and occupant."""
        by_id = {z.id: z.colour for z in self.config.zones}
        seated = {p.zone_id: p.name for p in self.config.players
                  if p.zone_id is not None}
        rows = zonemap.layout(self.config.player_count, colours=by_id)
        for row in rows:
            row["player"] = seated.get(int(row["zone"]))
        return {
            "player_count": self.config.player_count,
            "max_players": zonemap.MAX_PLAYERS,
            "supported": self.lights.supports_zones(),
            "zones": rows,
        }

    # ---- recording (plan doc 3.10) ---------------------------------------

    def _mic(self):
        return getattr(getattr(self, "_runtime", None), "mic", None)

    @action()
    def start_recording(self) -> None:
        """Begin recording the room. Transcription is a later problem.

        NOT a _supersede action: recording is orthogonal to what the table
        is showing, and starting it must not cancel a pending interruption
        revert.
        """
        mic = self._mic()
        if mic is None:
            self.log.record("mic.unavailable")
            return
        mic.start()

    @action()
    def stop_recording(self) -> None:
        mic = self._mic()
        if mic is None:
            return
        mic.stop()

    def recording_report(self) -> dict:
        mic = self._mic()
        if mic is None:
            return {"recording": False, "available": False,
                    "error": "no recorder"}
        out = dict(mic.status())
        out["available"] = True
        return out

    # ---- initiative (plan doc 3.9) ---------------------------------------
    #
    # Player turns only. No monsters, no scores, no sorting: the GM taps the
    # players in the order they want and that is the order. See the note at
    # the top of warlock/initiative.py for why this is deliberately small.

    # A flash is ~0.7s in patterns/zones.js. Three of them is long enough to
    # catch someone looking away and short enough not to interrupt play.
    PING_FLASHES = 3
    PING_SECONDS = 3 * 0.7 + 0.3

    def _push_active_zone(self) -> None:
        """Tell the lights which seat is up, if they can show it."""
        if not self.lights.supports_zones():
            return
        self.initiative.drop_missing(self.config.player_count)
        self._try("lights", self.lights.set_active_zone,
                  self.initiative.active_zone())

    def set_initiative_order(self, zones) -> dict:
        """The order, as seat numbers, exactly as tapped."""
        cleaned = []
        for zone in zones or []:
            zone = int(zone)
            if not 1 <= zone <= self.config.player_count:
                raise ValueError("seat %d does not exist with %d players"
                                 % (zone, self.config.player_count))
            cleaned.append(zone)
        self.initiative.set_order(cleaned)
        self.log.record("initiative.order_set", seats=cleaned)
        # Configure before highlighting: pushing the highlight first is what
        # loaded the pattern in an unconfigured state.
        if self.lights.supports_zones():
            self._ensure_zones_pattern()
        self._push_active_zone()
        return self.initiative_report()

    @action()
    def run_initiative(self) -> None:
        """Start the order from the top and light the first player."""
        if self.initiative.run() is None:
            self.log.record("initiative.no_order")
            return
        self._ensure_zones_pattern()
        self.log.record("initiative.run",
                        seat=self.initiative.active_zone())
        self._push_active_zone()

    @action(ParamSpec("step", "float"))
    def advance_turn(self, step: float = 1) -> None:
        """Next player, or the previous one with step = -1.

        An action as well as an API call so it can be put on a card: passing
        a physical token round the table beats everyone waiting on the GM's
        tablet.
        """
        if self.initiative.advance(int(step)) is None:
            self.log.record("initiative.not_running")
            return
        self.log.record("initiative.turn", seat=self.initiative.active_zone())
        self._push_active_zone()

    @action()
    def stop_initiative(self) -> None:
        """Stop pointing at anyone. The order is kept for next time."""
        self.initiative.stop()
        self.log.record("initiative.stopped")
        self._push_active_zone()

    def clear_initiative(self) -> dict:
        self.initiative.clear()
        self.log.record("initiative.cleared")
        self._push_active_zone()
        return self.initiative_report()

    @action(ParamSpec("zone", "float"))
    def flash_player(self, zone: float) -> None:
        """Flash one seat a few times, then put the scene back.

        The "oi, you" button. Deliberately NOT a mode: it interrupts
        whatever the table is showing for about two seconds and then
        restores it, so the GM can get a player's attention without
        abandoning the scene they set up.
        """
        zone = int(zone)
        if not 1 <= zone <= self.config.player_count:
            raise ValueError("seat %d does not exist with %d players"
                             % (zone, self.config.player_count))
        if not self.lights.supports_zones():
            self.log.record("lights.zones_unsupported")
            return

        # What to go back to. Grab it BEFORE switching, and prefer the
        # scene's pattern over whatever is currently loaded: if two flashes
        # overlap, the second would otherwise "restore" to the zones
        # pattern and strand the table there.
        scene = self.current_scene
        restore_to = scene.lights if scene and scene.lights else None

        with self._lock:
            if self._flash_timer is not None:
                self._flash_timer.cancel()
                self._flash_timer = None

        self._ensure_zones_pattern()
        self._try("lights", self.lights.set_active_zone, zone)
        self.log.record("initiative.flash_player", seat=zone,
                        flashes=self.PING_FLASHES, restore_to=restore_to)

        def restore():
            with self._lock:
                self._flash_timer = None
            # If combat started while the flash was in the air, the order
            # wins: putting the scene back would drop the turn indicator.
            if self.initiative.report()["running"]:
                self._push_active_zone()
                return
            self._try("lights", self.lights.set_active_zone, -1)
            if restore_to:
                self._try("lights", self.lights.set_pattern, restore_to)

        timer = threading.Timer(self.PING_SECONDS, restore)
        timer.daemon = True
        with self._lock:
            self._flash_timer = timer
        timer.start()

    def initiative_report(self) -> dict:
        """The order, with each seat's colour and whoever claimed it."""
        report = self.initiative.report()
        by_id = {z.id: z.colour for z in self.config.zones}
        claimed = {p.zone_id: p.name for p in self.config.players
                   if p.zone_id is not None}
        report["order"] = [
            {"zone": z,
             "colour": by_id.get(z, zonemap.seat_colour(z)),
             "player": claimed.get(z)}
            for z in report["order"]
        ]
        return report

    def _ensure_zones_pattern(self) -> None:
        """Load the zones pattern AND push its layout. Always both.

        This used to skip the push when the pattern was already loaded,
        treating "loaded" as a proxy for "configured". They are not the
        same, because set_active_zone() switches to the zones pattern by
        itself in order to write activeZone -- so setting an order loaded
        the pattern with no playerCount, and running initiative then saw it
        already loaded and skipped the setup. The pattern sat at
        playerCount = 0 and rendered its unconfigured fallback: a dim
        purple table, and initiative that appeared to do nothing.

        Pushing every time costs one websocket message on a path that runs
        when combat starts, not per turn.
        """
        self._try("lights", self.lights.show_zones,
                  self.config.player_count, self.zone_colours(),
                  *zonemap.gm_span())


    # ---- seats (plan doc 4.5) --------------------------------------------

    def claim_seat(self, player_name: str, colour: str) -> bool:
        zone = next((z for z in self.config.zones if z.colour == colour), None)
        if zone is None:
            self.log.record("seat.claim_failed", player=player_name, colour=colour)
            return False
        taken_by = next((p for p in self.config.players if p.zone_id == zone.id), None)
        if taken_by and taken_by.name != player_name:
            self.log.record("seat.collision", player=player_name,
                             colour=colour, already_claimed_by=taken_by.name)
            return False
        from .config import Player
        self.config.players = [p for p in self.config.players if p.name != player_name]
        self.config.players.append(Player(name=player_name, zone_id=zone.id))
        self.log.record("seat.claimed", player=player_name, colour=colour, zone_id=zone.id)
        return True

    def release_seat(self, colour: str = "", player_name: str = "") -> bool:
        """Empty a seat. Addressed by colour (the GM removing whoever is
        there) or by name (a player standing up).

        BOTH DOORS ARE NEEDED and they are not the same door. A player
        leaving knows their own name and not necessarily which colour they
        ended up with; a GM fixing someone who sat in the wrong place is
        looking at a seat, and may not know or care what the occupant
        called themselves. Taking either identifier means neither side has
        to look the other up first.

        Returns False when the seat was already empty, so a caller can tell
        "there was nobody there" from "somebody left" -- the panel needs
        that to avoid reporting a removal that did not happen.
        """
        before = len(self.config.players)
        if colour:
            zone = next((z for z in self.config.zones if z.colour == colour), None)
            if zone is None:
                self.log.record("seat.release_failed", colour=colour,
                                 reason="no such seat")
                return False
            sitting = [p for p in self.config.players if p.zone_id == zone.id]

            # BOTH IDENTIFIERS MEANS "MUST MATCH", not "colour wins". The
            # player app sends its own name AND colour, and a phone that
            # has been closed in a pocket may be describing a seat somebody
            # else has since taken -- releasing on colour alone would let a
            # stale device evict whoever is sitting there now. The GM's
            # remove button sends colour only and is unaffected: they are
            # looking at the chair, and removing whoever is in it is
            # exactly what they asked for.
            if player_name and sitting and sitting[0].name != player_name:
                self.log.record("seat.release_refused", colour=colour,
                                 asked_by=player_name,
                                 actually=sitting[0].name)
                return False

            leaving = sitting
            self.config.players = [p for p in self.config.players
                                   if p.zone_id != zone.id]
        elif player_name:
            leaving = [p for p in self.config.players if p.name == player_name]
            self.config.players = [p for p in self.config.players
                                   if p.name != player_name]
        else:
            return False

        if len(self.config.players) == before:
            return False

        for p in leaving:
            self.log.record("seat.released", player=p.name, zone_id=p.zone_id)

        # An empty seat must not keep a turn in the running order, or
        # initiative advances to a chair nobody is sitting in and the table
        # waits on a player who left.
        for p in leaving:
            if p.zone_id is not None:
                try:
                    self.initiative.remove(p.zone_id)
                except (AttributeError, ValueError, KeyError):
                    pass

        # A signal from someone who is no longer at the table would sit in
        # the GM's bar with nobody to answer it.
        for p in leaving:
            zone = next((z for z in self.config.zones if z.id == p.zone_id), None)
            if zone is not None:
                try:
                    self.clear_signal(zone.colour)
                except Exception:      # noqa: BLE001 -- never block a release
                    pass
        return True
