"""Profiles — the config split into what the TABLE owns and what a LIBRARY
owns (plan doc 4.8). Steps 1 and 2 of seven: the split, and a private
library composed on top of the shared one.

Today `config.json` holds everything. Section 4.8 makes scenes,
interruptions, random tables and dice triggers belong to a *library* --
the shared one now, private ones per user later -- while settings, zones,
the physical deck, seats and known dice stay with the table. This module
draws that line and nothing more: no users, no PINs, no second library.
That is deliberate (4.8, build order): the split touches how every
config is loaded and adds no feature, so it should be the only thing
that is new while it beds in.

    /var/lib/warlocktable/
        config.json                UNTOUCHED -- the previous build's file
        table.json                 table-owned half
        profiles/shared/library.json   library-owned half

**The migration is additive.** It writes the two new files BESIDE
`config.json` and never edits or removes it. Once `profiles/` exists the
new code ignores `config.json`; the old code never heard of `profiles/`.
So rolling back is deploying the previous tag, and the only thing lost is
whatever was edited through the new build since. It refuses to run twice.

**Equivalence is the contract.** `compose(split(raw)) == raw` for any
config the loader accepts, and a Config loaded through a ProfileStore is
equal to one loaded from the single file it was split from. That is the
step-1 acceptance test, in tests/test_profiles.py, against the real
config from the table.

STEP 2 -- A PRIVATE LIBRARY ON TOP OF THE SHARED ONE

    profiles/<id>/library.json     a user's own scenes, interruptions, tables

Opening a profile composes its library over the shared one into the same
single Config. **One namespace**: a name lives in exactly one of the two
files, or loading refuses and says which two files collide. The Config
remembers where each name came from (`library_owner`), so a save routes
every entry back to its own file; a NEW name goes to the write target --
the private library while one is open, else shared. Dice triggers stay
shared for now: they have no names to own by, and per-user triggers
belong with per-user cards (step 5). Until users exist (step 3), a
profile is opened with `--profile <id>`.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from .config import (Config, ConfigError, config_from_raw, load_config,
                     to_dict, write_json_atomic)

PROFILES_DIR = "profiles"
SHARED = "shared"
TABLE_FILE = "table.json"
LIBRARY_FILE = "library.json"

# Top-level keys of config.json, by owner. A key not listed here is a bug
# in this table, not something to guess about: split_raw refuses it.
TABLE_KEYS = ("settings", "zones", "cards", "players")
LIBRARY_KEYS = ("scenes", "interruptions", "random_tables")
# The kinds a private library may hold, and which half of the split holds
# the shared copy of each. Cards are the step-5 addition: the DECK stays
# in table.json and is the admin's; a GM's own registered tags live in
# their library and resolve after the deck (4.8, "a user's own cards").
# Dice triggers are deliberately not here yet (module docstring).
PRIVATE_KINDS = ("scenes", "interruptions", "random_tables", "cards")
_HALF_OF = {"scenes": "library", "interruptions": "library",
            "random_tables": "library", "cards": "table"}
SHARED, PRIVATE = "shared", "private"
# The dice section straddles: which dice exist (and whose seat) is a fact
# about the table; what a landing DOES is a binding, like a card's target,
# and lives with the library.
DICE_TABLE_KEYS = ("enabled", "known")
DICE_LIBRARY_KEYS = ("triggers",)


# ------------------------------------------------------------ pure split

def split_raw(raw: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """One config.json structure -> (table, library). Pure; copies."""
    unknown = [k for k in raw if k not in TABLE_KEYS + LIBRARY_KEYS + ("dice",)]
    if unknown:
        raise ConfigError("config has keys this build does not know how to "
                          "split: %s" % ", ".join(sorted(unknown)))
    table = {k: copy.deepcopy(raw[k]) for k in TABLE_KEYS if k in raw}
    library = {k: copy.deepcopy(raw[k]) for k in LIBRARY_KEYS if k in raw}
    dice = raw.get("dice") or {}
    if dice:
        unknown = [k for k in dice if k not in DICE_TABLE_KEYS + DICE_LIBRARY_KEYS]
        if unknown:
            raise ConfigError("dice section has unknown keys: %s"
                              % ", ".join(sorted(unknown)))
        t = {k: copy.deepcopy(dice[k]) for k in DICE_TABLE_KEYS if k in dice}
        l = {k: copy.deepcopy(dice[k]) for k in DICE_LIBRARY_KEYS if k in dice}
        if t:
            table["dice"] = t
        if l:
            library["dice"] = l
    return table, library


def compose_raw(table: Dict[str, Any], library: Dict[str, Any]) -> Dict[str, Any]:
    """(table, library) -> one config.json structure. The exact inverse."""
    raw: Dict[str, Any] = {}
    for k in TABLE_KEYS:
        if k in table:
            raw[k] = copy.deepcopy(table[k])
    for k in LIBRARY_KEYS:
        if k in library:
            raw[k] = copy.deepcopy(library[k])
    dice: Dict[str, Any] = {}
    dice.update(copy.deepcopy(table.get("dice") or {}))
    dice.update(copy.deepcopy(library.get("dice") or {}))
    if dice:
        raw["dice"] = dice
    return raw


# ------------------------------------------------------------ the store

class ProfileStore:
    """Reads and writes the split files, and hands the Controller one Config.

    Nothing below this knows the split exists: `load()` returns the same
    Config the single-file loader would, and `save()` takes the same
    Config the single-file saver would. That is the whole point -- the
    Controller and ConfigStore keep working on one Config while the files
    underneath change shape.
    """

    def __init__(self, data_dir: str, private: Optional[str] = None):
        self.data_dir = os.path.abspath(data_dir)
        self.table_path = os.path.join(self.data_dir, TABLE_FILE)
        self.shared_dir = os.path.join(self.data_dir, PROFILES_DIR, SHARED)
        self.library_path = os.path.join(self.shared_dir, LIBRARY_FILE)
        # The open private profile, if any. Its id is a directory name
        # under profiles/; "shared" is reserved.
        if private is not None:
            private = private.strip()
            if not private or private == SHARED or not _safe_id(private):
                raise ConfigError("bad profile id %r" % private)
        self.private = private
        self.private_dir = (os.path.join(self.data_dir, PROFILES_DIR, private)
                            if private else None)
        self.private_path = (os.path.join(self.private_dir, LIBRARY_FILE)
                             if private else None)
        # Where a NEW named entry is written. Opening a profile makes it
        # the target; the admin (step 3) will be able to point it back.
        self.write_target = PRIVATE if private else SHARED

    @classmethod
    def beside(cls, config_path: str, private: Optional[str] = None) -> Optional["ProfileStore"]:
        """The store for a config path, if that directory has been migrated.

        This is the ONE switch between the old layout and the new: a
        `profiles/` directory next to config.json means the split files are
        the truth and config.json is the previous build's copy.
        """
        store = cls(os.path.dirname(os.path.abspath(config_path)), private)
        return store if store.exists() else None

    def exists(self) -> bool:
        return os.path.isdir(os.path.join(self.data_dir, PROFILES_DIR))

    def _read(self, path: str) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def _read_private(self) -> Dict[str, Any]:
        if self.private_path and os.path.exists(self.private_path):
            raw = self._read(self.private_path)
            extra = [k for k in raw if k not in PRIVATE_KINDS]
            if extra:
                raise ConfigError("%s: a private library may hold only %s, not %s"
                                  % (self.private_path, ", ".join(PRIVATE_KINDS),
                                     ", ".join(sorted(extra))))
            return raw
        return {}

    def raw(self) -> Dict[str, Any]:
        """The composed single-file structure, as the loader expects it.

        Also the merge point for a private library: its named entries are
        added to the shared ones, and a name present in both is refused
        naming both files, because one namespace is the rule (4.8).
        """
        table = self._read(self.table_path) if os.path.exists(self.table_path) else {}
        library = self._read(self.library_path) if os.path.exists(self.library_path) else {}
        raw = compose_raw(table, library)
        private = self._read_private()
        for kind in PRIVATE_KINDS:
            mine = private.get(kind) or {}
            if not mine:
                continue
            theirs = raw.setdefault(kind, {})
            clash = sorted(set(mine) & set(theirs))
            if clash:
                raise ConfigError(
                    "%s %s defined in both %s and %s -- a name may live in "
                    "only one library" % (
                        kind, ", ".join(clash),
                        self.table_path if _HALF_OF[kind] == "table" else self.library_path,
                        self.private_path))
            theirs.update(copy.deepcopy(mine))
        return raw

    def owners(self) -> Dict[str, Dict[str, str]]:
        """kind -> name -> 'shared' | 'private', from the files as they are.
        For cards, 'shared' means the deck."""
        out: Dict[str, Dict[str, str]] = {}
        table = self._read(self.table_path) if os.path.exists(self.table_path) else {}
        library = self._read(self.library_path) if os.path.exists(self.library_path) else {}
        halves = {"table": table, "library": library}
        private = self._read_private()
        for kind in PRIVATE_KINDS:
            out[kind] = {}
            for name in (halves[_HALF_OF[kind]].get(kind) or {}):
                out[kind][name] = SHARED
            for name in (private.get(kind) or {}):
                out[kind][name] = PRIVATE
        return out

    def load(self) -> Config:
        config = config_from_raw(self.raw())
        config.library_owner = self.owners()
        return config

    def save(self, config: Config, backup_dir: Optional[str] = None) -> None:
        """Write every half. Validated first; each file atomic; the
        previous versions backed up. Same rules as save_config (4.4).

        Named library entries go back to the file they came from; a name
        the Config has not seen before goes to the write target. An entry
        that has gone from the Config is dropped from whichever file had
        it. Table-owned data and dice triggers always go to their files.
        """
        payload = to_dict(config)
        config_from_raw(copy.deepcopy(payload))      # refuse before touching disk
        table, library = split_raw(payload)

        private: Dict[str, Any] = {}
        if self.private:
            owners = config.library_owner or {}
            halves = {"table": table, "library": library}
            for kind in PRIVATE_KINDS:
                entries = halves[_HALF_OF[kind]].get(kind) or {}
                mine = {}
                for name in list(entries):
                    owner = owners.get(kind, {}).get(name) or self.write_target
                    if owner == PRIVATE:
                        mine[name] = entries.pop(name)
                if mine:
                    private[kind] = mine
            # The ownership map must reflect what was just written, so a
            # second save routes the same way.
            config.library_owner = {
                kind: dict(
                    {n: SHARED for n in (halves[_HALF_OF[kind]].get(kind) or {})},
                    **{n: PRIVATE for n in (private.get(kind) or {})})
                for kind in PRIVATE_KINDS}

        os.makedirs(self.shared_dir, exist_ok=True)
        write_json_atomic(self.table_path, table, backup_dir, "table")
        write_json_atomic(self.library_path, library, backup_dir, "library")
        if self.private:
            os.makedirs(self.private_dir, exist_ok=True)
            write_json_atomic(self.private_path, private, backup_dir,
                              "library-%s" % self.private)

    def describe(self) -> str:
        parts = [os.path.relpath(self.table_path, self.data_dir),
                 os.path.relpath(self.library_path, self.data_dir)]
        if self.private:
            parts.append(os.path.relpath(self.private_path, self.data_dir))
        return " + ".join(parts)


def _safe_id(profile_id: str) -> bool:
    return all(c.isalnum() or c in "-_" for c in profile_id) and len(profile_id) <= 40


# ------------------------------------------------------------ migration

def migrate(config_path: str, backup_dir: Optional[str] = None) -> ProfileStore:
    """Split config.json into table.json + profiles/shared/library.json.

    Additive: config.json is read and left exactly as it was. Refuses if
    `profiles/` already exists (idempotent by refusal, 4.8) and if the
    config does not load, because a migration that writes something the
    loader would reject is worse than none.
    """
    config_path = os.path.abspath(config_path)
    store = ProfileStore(os.path.dirname(config_path))
    if store.exists():
        raise ConfigError("%s already exists -- already migrated, nothing to do"
                          % os.path.join(store.data_dir, PROFILES_DIR))
    if not os.path.exists(config_path):
        raise ConfigError("no %s to migrate" % config_path)

    with open(config_path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    config_from_raw(copy.deepcopy(raw))          # must load as-is
    table, library = split_raw(raw)
    if compose_raw(table, library) != raw:
        raise ConfigError("split/compose does not round-trip this config; "
                          "refusing to migrate")

    if backup_dir:
        os.makedirs(backup_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(config_path, os.path.join(
            backup_dir, "config-pre-profiles-%s.json" % stamp))

    os.makedirs(store.shared_dir, exist_ok=True)
    write_json_atomic(store.table_path, table, None, "table")
    write_json_atomic(store.library_path, library, None, "library")
    return store
