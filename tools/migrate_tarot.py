#!/usr/bin/env python3
"""Build the tarot card entries in a config, from the design doc.

    python tools/migrate_tarot.py --config data/config.example.json --dry-run
    python3 tools/migrate_tarot.py --config /var/lib/warlocktable/config.json

Source of truth is warlock-table-interruption-cards.json, which defines all
26 cards. This turns them into config entries pointing at the generated
Pixelblaze patterns.

WHAT IT DOES

  - 25 interruptions: 4 Boon, 9 Person, 12 Aura. Lights only for now; the
    spec's placeholder audio does not exist and Interruption.audio is
    optional precisely so these can work silently until it does.
  - Wheel of Fortune becomes a random table over the 12 Auras, replacing
    the old scene-picking behaviour. That is the redefinition in the design
    doc, and it retires the three fortune_* interruptions with it.
  - Removes the test1/test2 scenes and their cards.

WHAT IT IS CAREFUL ABOUT

Five tarot cards are ALREADY enrolled with real NFC UIDs. Those are
re-pointed at the new entries, never deleted and recreated -- losing a UID
means physically re-tapping a card that already worked.

Durations come from the design doc: Auras are a 60s flourish, Boon and
Person are one-shot announcements that hand the table straight back.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(REPO, "warlock-table-interruption-cards.json")
GEN = os.path.join(REPO, "patterns", "generated")

# Card id -> the generated Pixelblaze pattern that renders it. Explicit
# rather than derived: a mechanical name transform would silently produce a
# pattern that does not exist, and every one of these is checked below.
PATTERN = {
    "ace_of_swords": "Boon-Swords", "ace_of_cups": "Boon-Cups",
    "ace_of_wands": "Boon-Wands", "ace_of_pentacles": "Boon-Pentacles",
    "the_magician": "Person-Magician", "the_emperor": "Person-Emperor",
    "the_fool": "Person-Fool", "the_empress": "Person-Empress",
    "the_high_priestess": "Person-HighPriestess", "the_lovers": "Person-Lovers",
    "the_hermit": "Person-Hermit", "the_hanged_man": "Person-HangedMan",
    "the_hierophant": "Person-Hierophant",
    "the_sun": "Aura-Sun", "the_moon": "Aura-Moon", "the_star": "Aura-Star",
    "temperance": "Aura-Temperance", "strength": "Aura-Strength",
    "justice": "Aura-Justice", "judgement": "Aura-Judgement",
    "the_devil": "Aura-Devil", "the_tower": "Aura-Tower",
    "death": "Aura-Death", "the_world": "Aura-World",
    "the_chariot": "Aura-Chariot",
}

# One-shot announcements hand the table back quickly; an Aura is a flourish
# that sits over the scene for a while. Both from the design doc.
DURATION = {"boon": 6.0, "person": 5.0, "aura": 60.0}

# Old entry -> new entry, for cards that already carry an NFC UID.
REPOINT = {
    "ace_of_pentacles_reveal": "ace_of_pentacles",
    "death_reveal": "death",
    "the_devil_reveal": "the_devil",
    "magician_reveal": "the_magician",
}

RETIRE_INTERRUPTIONS = set(REPOINT) | {
    "fortune_mystery", "fortune_reversal", "fortune_windfall"}
RETIRE_SCENES = {"test1", "test2"}
WHEEL = "wheel_outcomes"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    spec = json.load(io.open(SPEC, encoding="utf-8"))
    cards = {c["id"]: c for c in spec["cards"]}

    # Every pattern named must actually have been generated.
    have = {os.path.basename(f)[:-3] for f in os.listdir(GEN) if f.endswith(".js")}
    missing = sorted(p for p in PATTERN.values() if p not in have)
    if missing:
        print("refusing to run: these patterns do not exist: %s" % missing)
        return 2
    unmapped = sorted(i for i in cards if i not in PATTERN and i != "wheel_of_fortune")
    if unmapped:
        print("refusing to run: cards with no pattern mapping: %s" % unmapped)
        return 2

    cfg = json.load(io.open(args.config, encoding="utf-8"))
    changes = []

    # --- interruptions ---------------------------------------------------
    for cid, card in sorted(cards.items()):
        if card["subtype"] == "random_table":
            continue
        entry = {
            "lights": PATTERN[cid],
            "duck": False,          # nothing to duck: no audio yet
            "duration_s": DURATION[card["subtype"]],
        }
        if cid not in cfg["interruptions"]:
            changes.append("add interruption  %-22s -> %s"
                           % (cid, PATTERN[cid]))
        cfg["interruptions"][cid] = entry

    # --- Wheel of Fortune ------------------------------------------------
    auras = sorted(i for i, c in cards.items() if c["subtype"] == "aura")
    cfg.setdefault("random_tables", {})[WHEEL] = {
        "entries": [{"type": "interruption", "name": a} for a in auras]
    }
    changes.append("wheel_outcomes    -> random Aura, %d entries (was scenes)"
                   % len(auras))

    # --- re-point already-enrolled cards ---------------------------------
    for uid, card in cfg["cards"].items():
        t = card.get("target", {})
        if t.get("type") == "interruption" and t.get("name") in REPOINT:
            new = REPOINT[t["name"]]
            changes.append("repoint card      %-22s %s -> %s"
                           % (card["label"], t["name"], new))
            t["name"] = new

    # --- retire the old ---------------------------------------------------
    for name in sorted(RETIRE_INTERRUPTIONS):
        if cfg["interruptions"].pop(name, None) is not None:
            changes.append("remove interruption %s" % name)
    for name in sorted(RETIRE_SCENES):
        if cfg["scenes"].pop(name, None) is not None:
            changes.append("remove scene      %s" % name)
    for uid in [u for u, c in cfg["cards"].items()
                if c.get("target", {}).get("name") in RETIRE_SCENES]:
        changes.append("remove card       %s" % cfg["cards"][uid]["label"])
        del cfg["cards"][uid]

    print("%d changes:" % len(changes))
    for c in changes:
        print("   " + c)
    print()
    print("result: %d scenes, %d interruptions, %d tables, %d cards"
          % (len(cfg["scenes"]), len(cfg["interruptions"]),
             len(cfg.get("random_tables", {})), len(cfg["cards"])))

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    io.open(args.config, "w", encoding="utf-8", newline="\n").write(
        json.dumps(cfg, indent=2) + "\n")
    print("\nwritten to %s" % args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
