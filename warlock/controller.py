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
from typing import Optional

from .config import Config, Interruption, Scene, Target
from .devices.base import (AudioDevice, DeviceError, DisplayDevice,
                            LightDevice, UnknownAssetError)
from .eventlog import EventLog
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

        # Per-subsystem health, for the panel status strip and the TV status
        # screen (plan doc 5.1). A subsystem going unhealthy must never stop
        # the others — see _try below.
        self.subsystem_ok = {"lights": True, "audio": True, "display": True}

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

    def status(self) -> dict:
        """What the panel status strip and TV status screen render (5.1)."""
        return {
            "subsystems": dict(self.subsystem_ok),
            "scene": self.current_scene.name if self.current_scene else None,
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
        # Each subsystem is attempted independently: a dead Pixelblaze must
        # not stop the soundscape from playing (plan doc 5.2).
        self._try("lights", self.lights.set_pattern, scene.lights)
        self._try("audio", self.audio.play_soundscape, scene.soundscape,
                   scene.transition.crossfade_s)
        if scene.background:
            self._try("display", self.display.set_background, scene.background)

    @action(ParamSpec("interruption_name", "str",
                       choices=lambda c: list(c.config.interruptions)))
    def play_interruption(self, interruption_name: str) -> None:
        """Layer over whatever is currently playing, then revert to it
        once the audio finishes (plan doc 4.3)."""
        self._supersede(stop_effects=True)
        interruption = self.config.interruptions[interruption_name]
        self.log.record("interruption.start", name=interruption_name,
                         reverts_to=self.current_scene.name if self.current_scene else None)

        if interruption.lights:
            self._try("lights", self.lights.set_pattern, interruption.lights)
        if interruption.background:
            self._try("display", self.display.set_background, interruption.background)

        # play_effect returns the duration we need for the revert timer, so
        # it can't go through _try (which discards return values). Guard it
        # directly, and still schedule a revert if audio failed — otherwise a
        # broken audio device would strand the table in the interruption's
        # lighting with nothing to bring it back.
        duration = 0.0
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

        self._schedule_revert(interruption_name, duration)

    def _schedule_revert(self, interruption_name: str, duration: float) -> None:
        scene_to_restore = self.current_scene

        def revert():
            self.log.record("interruption.revert", name=interruption_name,
                             to=scene_to_restore.name if scene_to_restore else "idle")
            if scene_to_restore:
                # Re-apply directly rather than calling apply_scene(), so
                # we don't clear a timer another action may have set since.
                self._try("lights", self.lights.set_pattern, scene_to_restore.lights)
                self._try("audio", self.audio.play_soundscape,
                           scene_to_restore.soundscape,
                           scene_to_restore.transition.crossfade_s)
                if scene_to_restore.background:
                    self._try("display", self.display.set_background,
                               scene_to_restore.background)
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

    @action(ParamSpec("name", "str"))
    def set_background(self, name: str) -> None:
        self._supersede()
        self._try("display", self.display.set_background, name)

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
        self._try("display", shower, build_report(rt),
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

    @action(ParamSpec("player", "str"), ParamSpec("text", "str"))
    def whisper(self, player: str, text: str) -> None:
        self._supersede()
        self.log.record("whisper", player=player, text=text)

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
        if idle.lights:
            self._try("lights", self.lights.set_pattern, idle.lights)
        self._try("audio", self.audio.play_soundscape, idle.soundscape,
                   idle.transition.crossfade_s)
        if idle.background:
            self._try("display", self.display.set_background, idle.background)

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
