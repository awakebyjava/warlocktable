"""Sound effects -- the stings that fire when something happens.

Sibling of warlock/entity (the voice) and warlock/mapimport, and bound by the
same rule: the controller calls in, this never calls out, and nothing here can
raise into a card tap.

THE ONE THING THIS MUST NEVER DO IS INTERRUPT THE SOUNDSCAPE.

A scene card starts an ongoing bed -- forest, swamp, island, mountain, plains
-- that plays for as long as the scene lasts. The sting is what the card tap
sounds like; the bed is what the room sounds like afterwards. They are
different layers and must stay that way.

The mistake to avoid is wiring a sting in as the scene's `soundscape`, which
would REPLACE the bed. Everything here goes through `audio.play_file`, which
lands on the effect channel and layers over the bed exactly as an interruption
sting already does. Ducking (per family, off by default for the small ones)
only dips the bed's volume and restores it -- see pygame_audio._duck, which
never stops playback.

Timing is safe too: all 25 interruptions revert on their own `duration_s` and
carry no audio of their own, so a sting cannot shorten or extend a card.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Dict, List, Optional

__all__ = ["SoundEffects"]

# Families, in the order the panel shows them.
FAMILIES = ("boon", "person", "aura", "scene",
            "interface", "system", "combat", "player")

# Which families dip the bed while they play. The big card moments earn it;
# a panel tap does not -- ducking the soundscape fifty times an evening for a
# UI blip would be audible as the room breathing in and out.
DEFAULT_DUCK = {
    "boon": True, "person": True, "aura": True, "scene": True,
    "system": True, "interface": False, "combat": False, "player": False,
}

# Ready-made toggle sets for the panel. The names are what the operator picks
# between when they want less of this without configuring 54 switches.
PROFILES = {
    "everything": list(FAMILIES),
    "cards only": ["boon", "person", "aura"],
    "cards and scenes": ["boon", "person", "aura", "scene"],
    "no interface": ["boon", "person", "aura", "scene", "system"],
    "interface only": ["interface"],
    "silent": [],
}


class SoundEffects(object):
    def __init__(self, settings, audio, log):
        self.settings = settings          # config.SoundEffects
        self.audio = audio
        self.log = log

        self.sounds: Dict[str, dict] = {}      # id -> spec entry
        self.by_card: Dict[str, str] = {}      # card/scene id -> sound id
        self.healthy = False
        self.last_error: Optional[str] = None
        self.last_played: Optional[str] = None
        self._lock = threading.Lock()
        self._warned = set()

    # --- lifecycle --------------------------------------------------------

    def start(self) -> bool:
        """Load the spec. Never raises: no sounds is a quiet table, not a
        broken one."""
        try:
            spec_path = os.path.expanduser(self.settings.spec or "")
            audio_dir = os.path.expanduser(self.settings.audio_dir or "")
            if not spec_path or not os.path.isfile(spec_path):
                self.last_error = "no sound spec at %r" % spec_path
                self.log.record("sfx.unavailable", error=self.last_error)
                return False

            with open(spec_path, encoding="utf-8") as fh:
                raw = json.load(fh)

            for entry in raw.get("sounds", []):
                sid = entry.get("id")
                if not sid:
                    continue
                entry = dict(entry)
                entry["path"] = os.path.join(audio_dir, "%s.wav" % sid)
                self.sounds[sid] = entry
                # `used_by` is the mapping from a card or scene to its sound,
                # and it already lives in the spec -- no second table to keep
                # in step with the first.
                for owner in entry.get("used_by", []):
                    self.by_card[owner] = sid
        except Exception as exc:      # noqa: BLE001
            self.last_error = "%s: %s" % (type(exc).__name__, exc)
            self.log.record("sfx.unavailable", error=self.last_error)
            return False

        missing = [s for s in self.sounds if not os.path.isfile(self.sounds[s]["path"])]
        self.healthy = True
        self.last_error = None
        self.log.record("sfx.ready", sounds=len(self.sounds),
                        missing=len(missing))
        if missing:
            self.log.record("sfx.missing_files", count=len(missing),
                            examples=missing[:5])
        return True

    # --- what is switched on ----------------------------------------------

    def is_on(self, sound_id: str) -> bool:
        """Master, then family, then the individual switch."""
        if not self.settings.enabled:
            return False
        entry = self.sounds.get(sound_id)
        if entry is None:
            return False
        if not self.settings.family_on(entry.get("family", "")):
            return False
        return sound_id not in self.settings.muted

    # --- firing -----------------------------------------------------------

    def play(self, sound_id: str, force: bool = False) -> float:
        """Play one sound. Returns how long it will sound for, in seconds, or
        0.0 if nothing played.

        The duration is what lets the controller keep the Entity's voice off
        the top of a sting -- see Controller._sting.

        `force` is the panel's audition button, which ignores every toggle so
        a muted sound can still be heard.
        """
        try:
            return self._play(sound_id, force)
        except Exception as exc:      # noqa: BLE001
            self.log.record("sfx.error", sound=sound_id,
                            error="%s: %s" % (type(exc).__name__, exc))
            return 0.0

    def _play(self, sound_id: str, force: bool) -> float:
        if not self.healthy:
            return 0.0
        entry = self.sounds.get(sound_id)
        if entry is None:
            return 0.0
        if not force and not self.is_on(sound_id):
            return 0.0

        path = entry["path"]
        if not os.path.isfile(path):
            if sound_id not in self._warned:
                self._warned.add(sound_id)
                self.log.record("sfx.missing_audio", sound=sound_id, path=path)
            return 0.0

        duck = self.settings.duck_for(entry.get("family", ""))
        # play_file, NOT play_soundscape. This is the whole point: the effect
        # channel layers over the bed, so a scene's ongoing audio keeps
        # running underneath its own arrival sting.
        seconds = self.audio.play_file(path, duck)
        with self._lock:
            self.last_played = sound_id
        try:
            return float(seconds or 0.0)
        except (TypeError, ValueError):
            return 0.0

    # --- what the controller calls ----------------------------------------

    def for_card(self, card_id: str) -> Optional[str]:
        return self.by_card.get((card_id or "").lower())

    def on_card(self, card_id: str) -> float:
        """An interruption fired. Cannot affect the card's timing: every
        interruption reverts on its own duration_s and carries no audio."""
        sid = self.for_card(card_id)
        return self.play(sid) if sid else 0.0

    def on_scene(self, scene_name: str) -> float:
        """A scene was applied. THE STING ONLY -- the bed is started
        separately by the controller and is not this layer's business."""
        sid = self.for_card((scene_name or "").lower())
        return self.play(sid) if sid else 0.0

    def on_event(self, sound_id: str) -> float:
        """A named interface, system, combat or player sound."""
        return self.play(sound_id)

    # --- settings ---------------------------------------------------------

    def apply_profile(self, name: str) -> List[str]:
        on = PROFILES.get(name)
        if on is None:
            raise ValueError("no such profile: %s" % name)
        self.settings.families = {f: (f in on) for f in FAMILIES}
        return sorted(on)

    # --- reporting --------------------------------------------------------

    def status(self) -> Dict:
        families = []
        for f in FAMILIES:
            ids = [s for s in self.sounds if self.sounds[s].get("family") == f]
            families.append({
                "name": f,
                "on": self.settings.family_on(f),
                "count": len(ids),
                "muted": sum(1 for s in ids if s in self.settings.muted),
                "ducks": self.settings.duck_for(f),
            })
        return {
            "enabled": self.settings.enabled,
            "healthy": self.healthy,
            "error": self.last_error,
            "sounds": len(self.sounds),
            "missing": sum(1 for s in self.sounds
                           if not os.path.isfile(self.sounds[s]["path"])),
            "last_played": self.last_played,
            "families": families,
            "profiles": sorted(PROFILES),
        }

    def listing(self) -> List[Dict]:
        out = []
        for sid in sorted(self.sounds,
                          key=lambda s: (FAMILIES.index(self.sounds[s]["family"])
                                         if self.sounds[s].get("family") in FAMILIES
                                         else 99, s)):
            e = self.sounds[sid]
            out.append({
                "id": sid,
                "family": e.get("family", ""),
                "intent": e.get("intent", ""),
                "used_by": e.get("used_by", []),
                "on": self.is_on(sid),
                "present": os.path.isfile(e["path"]),
                "duration": e.get("duration_seconds"),
            })
        return out
