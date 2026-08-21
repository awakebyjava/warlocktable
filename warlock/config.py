"""Config loading — the data model from plan doc section 4.4, in code.

This file is deliberately boring: it reads JSON and checks it makes sense.
All the interesting behaviour lives in controller.py. Keeping the data
model and the behaviour in separate files is what makes it possible to
later swap "read from a JSON file" for "read from the management API"
without touching how a Scene or Interruption actually gets played.

IMPORTANT — where the real config lives:
Section 4.4 decided the Pi's live config lives OUTSIDE the git repo, so
editing a card from the panel never puts the Pi's clone out of sync with
GitHub (and never trips the pull.ff=only guard we set on the Pi). The
`data/config.example.json` shipped in this repo is a worked example for
development on the laptop — a starting point to copy, not the real thing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def normalise_uid(value: str) -> str:
    """Canonical form of an NFC UID for comparison: hex digits only, upper.

    "04:39:65:9A:66:70:81", "04 39 65 9a 66 70 81" and "0439659a667081" all
    reduce to the same thing. Returns "" if the input isn't plausibly a UID,
    so label lookups don't get mangled into false matches.
    """
    stripped = value.strip().replace(":", "").replace("-", "").replace(" ", "")
    if not stripped:
        return ""
    upper = stripped.upper()
    if any(c not in "0123456789ABCDEF" for c in upper):
        return ""     # contains letters like 'thedevil' — it's a label
    return upper


def format_uid(raw: bytes) -> str:
    """Bytes from the reader -> the canonical display form used in config."""
    return ":".join("%02X" % b for b in raw)


class ConfigError(Exception):
    """Raised for a config file that doesn't make sense. Section 5.2 says
    the controller must never refuse to start over a bad config — the
    caller of load_config() is responsible for falling back to a
    last-known-good file if this is raised (not yet wired up in this
    skeleton; noted as a TODO in cli.py)."""


@dataclass
class Transition:
    crossfade_s: float = 1.5   # audio crossfade duration — section 4.3
    duck: bool = True          # does the soundscape duck under effects


@dataclass
class Scene:
    name: str
    lights: str
    soundscape: Optional[str] = None
    background: Optional[str] = None
    transition: Transition = field(default_factory=Transition)


@dataclass
class Interruption:
    name: str
    audio: str
    lights: Optional[str] = None       # None = leave current lights alone
    background: Optional[str] = None
    duck: bool = True
    # How long the interruption holds, in seconds. None = as long as the
    # audio file runs.
    #
    # This exists because the V1 audio library is full-length music tracks,
    # not short stings — javan4 is 118s. Letting an arbitrary file length
    # decide the dramatic beat means a two-minute "interruption", which is
    # really a scene. Setting this fades the effect out at the given time
    # and reverts then.
    duration_s: Optional[float] = None


@dataclass
class Target:
    """A reference to something a card, table entry, etc. points at.
    kind is one of "scene" / "interruption" / "random_table"."""
    kind: str
    name: str


@dataclass
class RandomTable:
    name: str
    entries: List[Target]


@dataclass
class Card:
    uid: str            # hex string, colon-separated — see cli.py for parsing
    label: str           # what the physical object IS, not what it does
    target: Target


@dataclass
class Zone:
    id: int
    colour: str


@dataclass
class Player:
    name: str
    zone_id: Optional[int] = None


@dataclass
class Config:
    scenes: Dict[str, Scene]
    interruptions: Dict[str, Interruption]
    random_tables: Dict[str, RandomTable]
    cards: Dict[str, Card]          # keyed by uid
    zones: List[Zone]
    players: List[Player] = field(default_factory=list)
    # Which scene is the resting state (plan doc 4.3). Configurable rather
    # than hardcoded in the controller, so the management UI can change what
    # the table falls back to.
    idle_scene_name: str = "idle"
    # How long an interruption holds if the audio device can't tell us the
    # real duration (because it failed, or the file is missing). Without this
    # a broken audio device would strand the table in the interruption's
    # lighting forever, with nothing scheduled to bring it back.
    fallback_interruption_s: float = 5.0

    # Where to look for audio files. Tracks are referenced by bare name in
    # scenes/interruptions ("forest"); these directories are searched to
    # resolve a name to a file. Config-driven per plan doc 3.3 — V1 hardcoded
    # /home/pi/Documents/MagicTarot/... in every single card branch.
    audio_paths: List[str] = field(default_factory=list)

    # Where to look for display artwork. Scenes reference a background by
    # bare name ("forest.png"); these directories resolve it to a file.
    # Same split as audio (plan doc 3.3): finished renders are media, they
    # live outside the repo and arrive by rsync, not git.
    background_paths: List[str] = field(default_factory=list)

    # ALSA device for audio output, e.g. "hw:0,0" for the 3.5mm jack.
    # Pinned explicitly rather than trusting the default: plan doc 5.3 —
    # if the TV is off at boot, HDMI may not enumerate and the default
    # silently moves. None = let SDL choose (fine on the laptop).
    audio_device: Optional[str] = None

    # How far the soundscape drops under a one-shot effect or voice line
    # (0.0-1.0), and how long the dip/restore ramp takes. Tunable per 4.3.
    duck_level: float = 0.3
    duck_ramp_s: float = 0.25

    def find_card(self, uid_or_label: str) -> Optional[Card]:
        """Looks up by exact uid first, then case-insensitive label match —
        convenient for the CLI where typing a full hex UID is annoying.
        The final pass strips spaces/punctuation from both sides so e.g.
        "thedevil" matches the label "The Devil (tarot)"."""
        needle = uid_or_label.strip()
        if needle in self.cards:
            return self.cards[needle]

        # UID match ignoring format. The reader emits "04:39:65:9A:66:70:81",
        # but a UID typed into the management UI could easily arrive lowercase,
        # space-separated, or run together. Comparing canonical forms means a
        # real card tap can't silently fail to match over punctuation.
        needle_uid = normalise_uid(needle)
        if needle_uid:
            for uid, card in self.cards.items():
                if normalise_uid(uid) == needle_uid:
                    return card
        lowered = needle.lower()
        for card in self.cards.values():
            if card.label.lower() == lowered:
                return card
        for card in self.cards.values():
            if lowered in card.label.lower():
                return card
        squashed = "".join(ch for ch in lowered if ch.isalnum())
        for card in self.cards.values():
            label_squashed = "".join(ch for ch in card.label.lower() if ch.isalnum())
            if squashed and squashed in label_squashed:
                return card
        return None

    def resolve(self, target: Target):
        """Turns a Target reference into the actual Scene/Interruption/
        RandomTable object it points at. Raises ConfigError if it points
        at nothing — this is the referential-integrity check from
        section 4.5, applied at read time."""
        table = {
            "scene": self.scenes,
            "interruption": self.interruptions,
            "random_table": self.random_tables,
        }.get(target.kind)
        if table is None:
            raise ConfigError("unknown target kind %r" % target.kind)
        if target.name not in table:
            raise ConfigError(
                "%s %r not found (referenced but does not exist)"
                % (target.kind, target.name)
            )
        return table[target.name]


def _target_from_dict(d: Dict[str, Any]) -> Target:
    return Target(kind=d["type"], name=d["name"])


def load_config(path: str) -> Config:
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)

    scenes = {}
    for name, s in raw.get("scenes", {}).items():
        t = s.get("transition", {})
        scenes[name] = Scene(
            name=name,
            lights=s["lights"],
            soundscape=s.get("soundscape"),
            background=s.get("background"),
            transition=Transition(
                crossfade_s=t.get("crossfade_s", 1.5),
                duck=t.get("duck", True),
            ),
        )

    interruptions = {}
    for name, i in raw.get("interruptions", {}).items():
        interruptions[name] = Interruption(
            name=name,
            audio=i["audio"],
            lights=i.get("lights"),
            background=i.get("background"),
            duck=i.get("duck", True),
            duration_s=(float(i["duration_s"]) if i.get("duration_s") is not None
                        else None),
        )

    random_tables = {}
    for name, r in raw.get("random_tables", {}).items():
        random_tables[name] = RandomTable(
            name=name,
            entries=[_target_from_dict(e) for e in r["entries"]],
        )

    cards = {}
    for uid, c in raw.get("cards", {}).items():
        cards[uid] = Card(
            uid=uid,
            label=c["label"],
            target=_target_from_dict(c["target"]),
        )

    zones = [Zone(id=z["id"], colour=z["colour"]) for z in raw.get("zones", [])]

    players = [
        Player(name=p["name"], zone_id=p.get("zone_id"))
        for p in raw.get("players", [])
    ]

    config = Config(
        scenes=scenes, interruptions=interruptions, random_tables=random_tables,
        cards=cards, zones=zones, players=players,
        idle_scene_name=raw.get("settings", {}).get("idle_scene", "idle"),
        fallback_interruption_s=float(
            raw.get("settings", {}).get("fallback_interruption_s", 5.0)),
        audio_paths=list(raw.get("settings", {}).get("audio_paths", [])),
        background_paths=list(raw.get("settings", {}).get("background_paths", [])),
        audio_device=raw.get("settings", {}).get("audio_device"),
        duck_level=float(raw.get("settings", {}).get("duck_level", 0.3)),
        duck_ramp_s=float(raw.get("settings", {}).get("duck_ramp_s", 0.25)),
    )

    _validate(config)
    return config


def _validate(config: Config) -> None:
    """Referential integrity, checked eagerly at load time rather than
    discovered mid-session (plan doc 4.5)."""
    for card in config.cards.values():
        config.resolve(card.target)   # raises ConfigError if dangling
    for table in config.random_tables.values():
        for entry in table.entries:
            config.resolve(entry)
