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


# Offered by the panel when a config does not name its own outputs.
#
# There BECAUSE install.sh seeds config.json once and never touches it
# again: a config written before this feature existed would otherwise show
# an empty switch forever, exactly as the seat palette did. An empty dict
# means "never configured", not "deliberately none", so it falls back here.
#
# Named by CARD, never by number. hw:0,0 breaks the moment HDMI renumbers
# the cards, which is the failure 5.3 records.
#
# The TV uses the "hdmi:" PCM, NOT "plughw:". The vc4-hdmi hardware accepts
# only IEC958_SUBFRAME_LE, and the plug layer will not convert to it -- both
# aplay and speaker-test refuse with "Sample format non available". The
# "hdmi:" plugin does the IEC958 framing and takes ordinary S16 stereo at
# 44100, which is what the mixer asks for.
DEFAULT_AUDIO_OUTPUTS = {
    "Speakers": "plughw:CARD=Headphones,DEV=0",
    "Television": "hdmi:CARD=vc4hdmi0,DEV=0",
}


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
    # How many players are seated, which is what divides the table into
    # zones (plan doc 4.7). The GM is always present and is not counted
    # here; 4 players means five zones. Stored rather than computed because
    # it is a fact about the room that nothing in software can observe.
    player_count: int = 4

    # Master audio level, 0.0-1.0. Persisted because otherwise every restart
    # comes back at whatever the default is, in a room where the right level
    # is a property of the room.
    volume: float = 0.8

    # Named outputs the panel offers, name -> ALSA device. Config-driven
    # rather than hardcoded for the usual reason (plan doc 3.3): V1 baked
    # device paths into every branch. Named BY CARD, never by number --
    # hw:0,0 breaks the moment HDMI renumbers the cards, which is the exact
    # failure 5.3 records.
    audio_outputs: Dict[str, str] = field(default_factory=dict)

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
        player_count=int(raw.get("settings", {}).get("player_count", 4)),
        volume=float(raw.get("settings", {}).get("volume", 0.8)),
        audio_outputs=dict(raw.get("settings", {}).get("audio_outputs")
                            or DEFAULT_AUDIO_OUTPUTS),
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


# ---------------------------------------------------------------- writing

def to_dict(config: Config) -> Dict[str, Any]:
    """Config -> plain JSON structure. The exact inverse of load_config().

    Kept next to the loader on purpose: if one gains a field and the other
    doesn't, a save silently drops data the user entered. That is the worst
    class of bug here, because it looks like nothing happened.
    """
    out: Dict[str, Any] = {}

    out["settings"] = {
        "audio_paths": list(config.audio_paths),
        "background_paths": list(config.background_paths),
        "audio_device": config.audio_device,
        "duck_level": config.duck_level,
        "duck_ramp_s": config.duck_ramp_s,
        "idle_scene": config.idle_scene_name,
        "player_count": config.player_count,
        "volume": config.volume,
        "audio_outputs": dict(config.audio_outputs),
        "fallback_interruption_s": config.fallback_interruption_s,
    }

    out["zones"] = [{"id": z.id, "colour": z.colour} for z in config.zones]

    out["scenes"] = {}
    for name, s in config.scenes.items():
        entry: Dict[str, Any] = {"lights": s.lights}
        if s.soundscape is not None:
            entry["soundscape"] = s.soundscape
        if s.background is not None:
            entry["background"] = s.background
        entry["transition"] = {"crossfade_s": s.transition.crossfade_s,
                                "duck": s.transition.duck}
        out["scenes"][name] = entry

    out["interruptions"] = {}
    for name, i in config.interruptions.items():
        entry = {"audio": i.audio, "duck": i.duck}
        if i.duration_s is not None:
            entry["duration_s"] = i.duration_s
        if i.lights is not None:
            entry["lights"] = i.lights
        if i.background is not None:
            entry["background"] = i.background
        out["interruptions"][name] = entry

    out["random_tables"] = {
        name: {"entries": [{"type": e.kind, "name": e.name} for e in t.entries]}
        for name, t in config.random_tables.items()
    }

    out["cards"] = {
        uid: {"label": c.label,
               "target": {"type": c.target.kind, "name": c.target.name}}
        for uid, c in config.cards.items()
    }

    out["players"] = [{"name": p.name, "zone_id": p.zone_id}
                       for p in config.players]
    return out


# Mode for a config that did not exist before. Readable by anyone, writable
# by its owner: the service user needs to read it, and mkstemp's 0600 would
# lock out a panel or a maintenance script running as anyone else.
NEW_CONFIG_MODE = 0o644


def _preserve_file_identity(tmp: str, existing) -> None:
    """Give `tmp` the mode and ownership of the file it is about to replace.

    `existing` is an os.stat_result, or None for a file being created.

    Best effort by design: chown is POSIX-only and an unprivileged process
    cannot give a file away, so failures are ignored rather than blocking a
    save. The common cases both work -- root restoring the service user's
    ownership, and the service user writing its own file (a no-op).
    """
    import os as _os
    import stat as _stat

    if existing is None:
        try:
            _os.chmod(tmp, NEW_CONFIG_MODE)
        except OSError:
            pass
        return

    try:
        _os.chmod(tmp, _stat.S_IMODE(existing.st_mode))
    except OSError:
        pass
    try:
        _os.chown(tmp, existing.st_uid, existing.st_gid)
    except (AttributeError, OSError):
        pass        # Windows has no chown; unprivileged chown is refused


def save_config(config: Config, path: str, backup_dir: Optional[str] = None) -> None:
    """Write config to disk safely.

    Three things matter here, all learned from this project rather than
    theory:

    1. **Atomic.** Write to a temp file in the same directory, flush, fsync,
       then os.replace() — which is atomic on POSIX. A power cut mid-write
       must never leave a half-written config, because that file is what the
       table needs to boot.
    2. **Backed up first.** The previous version is copied aside before it
       is replaced. Config is now Pi-owned data with no git history behind
       it (plan doc 4.4), so this is the only undo that exists.
    3. **Validated before it lands.** The result is parsed back and checked
       for dangling references, so a bad edit is refused rather than written
       and discovered mid-session.
    """
    import os as _os
    import shutil as _shutil
    import tempfile
    from datetime import datetime

    payload = to_dict(config)

    # Validate by round-tripping through the loader BEFORE touching the
    # real file. Cheaper than being clever, and catches anything to_dict
    # produced that load_config would reject.
    fd, probe = tempfile.mkstemp(suffix=".probe.json",
                                  dir=_os.path.dirname(_os.path.abspath(path)))
    try:
        with _os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        load_config(probe)          # raises ConfigError on a dangling target
    finally:
        try:
            _os.unlink(probe)
        except OSError:
            pass

    if backup_dir and _os.path.exists(path):
        try:
            _os.makedirs(backup_dir, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            _shutil.copy2(path, _os.path.join(backup_dir, "config-%s.json" % stamp))
        except OSError:
            pass       # a failed backup must not block the save

    directory = _os.path.dirname(_os.path.abspath(path))

    # What the file currently looks like, so the replace can put it back.
    try:
        existing = _os.stat(path)
    except OSError:
        existing = None

    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=directory)
    try:
        with _os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
            fh.flush()
            _os.fsync(fh.fileno())

        # Carry the original's mode and ownership onto the replacement.
        #
        # os.replace() swaps the temp file in WHOLESALE, so the config ends
        # up with whatever mkstemp gave us: mode 0600, owned by whoever is
        # running. Two consequences, one cosmetic and one fatal:
        #
        #   - the panel (running as the service user) quietly turned a 0644
        #     config into 0600 on every single edit;
        #   - a maintenance script run under sudo left a root-owned 0600
        #     config that the service user could not even read, which
        #     crash-looped the table until the ownership was put back.
        #
        # Preserving the metadata is what makes "atomic write" actually a
        # drop-in replacement rather than a new file wearing the old name.
        _preserve_file_identity(tmp, existing)

        _os.replace(tmp, path)      # atomic
    except Exception:
        try:
            _os.unlink(tmp)
        except OSError:
            pass
        raise
