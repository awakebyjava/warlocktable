#!/usr/bin/env python3
"""Build the 54 playing-card entries in a config.

    python tools/migrate_playing_cards.py --config data/config.example.json --dry-run
    python3 tools/migrate_playing_cards.py --config /var/lib/warlocktable/config.json

A standard deck used as table triggers -- not for playing card games, but
as fifty-four things a hand can reach for during one.

WHY FIFTY-FOUR ENTRIES AND ONLY EIGHT PATTERNS

The announcer says the SUIT ("spades"), so the lights are free to carry
the only other thing worth knowing: whether it was a number, an ace or a
court card. That is eight patterns covering the whole deck, which matters
because every pattern is an upload to a device whose flash has been
filled once already.

The CONFIG still names all fifty-four separately, because config is free
and information is not. Each card gets its own entry and its own label, so
the event log records that the Seven of Diamonds was tapped rather than
"a red number card" -- and so enrol_cards.py, which walks targets that
have no tag, asks for all fifty-four in turn instead of stopping at
thirteen.

WHAT IT IS CAREFUL ABOUT

Cards already enrolled keep their UIDs. This only ever writes the
interruptions and leaves cfg["cards"] alone, so re-running after tagging
half the deck cannot cost you a tap. It is idempotent: run it as often as
you like.

It also refuses to write entries pointing at patterns or audio that do not
exist, because a card that fires nothing looks like broken hardware to
everyone at the table. Pass --force to write anyway.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATTERN_DIR = os.path.join(REPO, "patterns", "generated")

# Ace first so it reads as the deck does, and so --only ace picks up four.
RANKS = ["ace", "two", "three", "four", "five", "six", "seven", "eight",
         "nine", "ten", "jack", "queen", "king"]
COURT = {"jack", "queen", "king"}

# Red and black, which for the lights means red and WHITE -- a black comet
# would be the ring switched off.
SUITS = {"hearts": "Red", "diamonds": "Red",
         "clubs": "White", "spades": "White"}

# 2.5s lap inside a 3.0s hold; see PLAY_LAP in tools/patterngen.py. These
# are triggers rather than dramatic beats, so they are deliberately quicker
# than the tarot cards' six seconds.
DURATION_S = 3.0


def entries() -> "dict[str, dict]":
    """The 54 interruptions, as {name: entry}."""
    out = {}
    for suit, colour in SUITS.items():
        for rank in RANKS:
            if rank == "ace":
                pattern = "Card-Comet-%s-Ace" % colour
            elif rank in COURT:
                pattern = "Card-Sparks-%s" % colour
            else:
                pattern = "Card-Comet-%s" % colour
            out["%s_of_%s" % (rank, suit)] = {
                "lights": pattern,
                "audio": "card-%s" % suit,
                # Speech under a music bed is the one thing that genuinely
                # becomes unintelligible; the tarot stings duck nothing
                # because they are tones, not words.
                "duck": True,
                "duration_s": DURATION_S,
            }
    # The jokers belong to no suit, so there is no suit to announce: both
    # share one clip and are told apart by the lights alone.
    for size in ("big", "small"):
        out["joker_%s" % size] = {
            "lights": "Card-Joker-%s" % size.capitalize(),
            "audio": "card-joker",
            "duck": True,
            "duration_s": DURATION_S,
        }
    return out


def audio_index(cfg: dict) -> set:
    """Every audio stem the table can resolve, by the same rule the mixer
    uses -- bare filename, any supported extension."""
    exts = (".ogg", ".wav", ".mp3", ".flac")
    found = set()
    for base in cfg.get("settings", {}).get("audio_paths", []):
        base = os.path.expanduser(base)
        if not os.path.isdir(base):
            continue
        for name in os.listdir(base):
            stem, ext = os.path.splitext(name)
            if ext.lower() in exts:
                found.add(stem)
    return found


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="write even if a pattern or sting is missing")
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args()

    cfg = json.load(io.open(args.config, encoding="utf-8"))
    cfg.setdefault("interruptions", {})
    cfg.setdefault("cards", {})

    new = entries()

    # --- referential integrity, before anything is written ---------------
    # Patterns are checked against the repo rather than the device: this
    # runs from the laptop, and the generated directory is the thing that
    # gets uploaded. Audio is checked against the config's own paths, so a
    # path that was never wired up is caught here rather than at the table.
    missing = []
    for pattern in sorted({e["lights"] for e in new.values()}):
        if not os.path.exists(os.path.join(PATTERN_DIR, pattern + ".js")):
            missing.append("pattern %s" % pattern)
    have_audio = audio_index(cfg)
    for stem in sorted({e["audio"] for e in new.values()}):
        if stem not in have_audio:
            missing.append("audio   %s" % stem)

    if missing:
        print("MISSING (%d):" % len(missing))
        for m in missing:
            print("   " + m)
        if not args.force:
            print("\nnothing written. Fix these, or pass --force.")
            return 1
        print("\n--force: writing anyway\n")

    added = updated = same = 0
    for name, entry in new.items():
        old = cfg["interruptions"].get(name)
        if old is None:
            added += 1
        elif old != entry:
            updated += 1
        else:
            same += 1
        cfg["interruptions"][name] = entry

    tagged = sum(1 for c in cfg["cards"].values()
                 if c.get("target", {}).get("name") in new)

    print("%d added, %d updated, %d already correct" % (added, updated, same))
    print("%d of %d already have a tag enrolled" % (tagged, len(new)))
    print("result: %d interruptions, %d cards"
          % (len(cfg["interruptions"]), len(cfg["cards"])))

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    if not args.no_backup:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = "%s.bak-%s" % (args.config, stamp)
        shutil.copyfile(args.config, backup)
        print("\nbacked up to %s" % backup)

    io.open(args.config, "w", encoding="utf-8", newline="\n").write(
        json.dumps(cfg, indent=2) + "\n")
    print("written to %s" % args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
