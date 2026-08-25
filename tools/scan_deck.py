#!/usr/bin/env python3
"""Scan the 54-card playing deck onto the table, one tap at a time.

RUN THIS ON THE PI, WITH THE SERVICE STOPPED:

    sudo systemctl stop warlocktable
    python3 tools/scan_deck.py
    sudo systemctl start warlocktable

It walks the deck in order, waits for you to tap each card, writes the
card entry immediately, tells you it did, and moves on.

NO PROMPTS. The label comes from the card being asked for, so there is
nothing to type. Every earlier attempt at this used input() for a label,
and input()'s prompt is not flushed when stdout is not a terminal -- over
SSH that produced a tool which looked completely dead. Removing the
question removes the whole problem.

NO WEB API AND NO SERVICE. It opens the PN532 directly and polls it. The
previous tool asked the running table what it had seen recently, which
meant a scratch buffer sat between the tap and the tool, and the two got
out of step. Here a tap is read from the hardware by the code that acts
on it.

Config is written after EVERY card, so Ctrl-C never costs you a tap.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

RANKS = ["ace", "two", "three", "four", "five", "six", "seven", "eight",
         "nine", "ten", "jack", "queen", "king"]
SUITS = ["hearts", "diamonds", "clubs", "spades"]

CONFIG = "/var/lib/warlocktable/config.json"


def deck() -> "list[str]":
    names = []
    for suit in SUITS:
        for rank in RANKS:
            names.append("%s_of_%s" % (rank, suit))
    return names + ["joker_big", "joker_small"]


def pretty(name: str) -> str:
    return name.replace("_", " ").title()


def service_is_up() -> bool:
    try:
        r = subprocess.run(["systemctl", "is-active", "warlocktable"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() == "active"
    except Exception:      # noqa: BLE001
        return False


def open_reader(cs: int, reset: int):
    """Open the PN532. Same sequence the service uses."""
    from warlock.vendor.pn532 import PN532_SPI
    try:
        import RPi.GPIO as GPIO
        GPIO.setwarnings(False)
    except Exception:      # noqa: BLE001
        pass
    pn = PN532_SPI(cs=cs, reset=reset, debug=False)
    _ic, ver, rev, _sup = pn.get_firmware_version()
    pn.SAM_configuration()
    return pn, "%s.%s" % (ver, rev)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=CONFIG)
    ap.add_argument("--only", default="",
                    help="substring filter, e.g. diamonds / ace / joker")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--redo", action="store_true",
                    help="include cards that already have a tag, replacing it")
    ap.add_argument("--cs", type=int, default=4)
    ap.add_argument("--reset", type=int, default=20)
    args = ap.parse_args()

    from warlock.config import format_uid

    cfg = json.load(io.open(args.config, encoding="utf-8"))
    cards = cfg.setdefault("cards", {})
    interruptions = cfg.get("interruptions", {})

    owner = {}          # uid -> label of whatever already claims it
    for uid, c in cards.items():
        owner[uid] = c.get("label", uid)
    tagged = {c.get("target", {}).get("name")
              for c in cards.values() if c.get("target")}

    todo = []
    missing_entry = []
    for name in deck():
        if name not in interruptions:
            missing_entry.append(name)
            continue
        if name in tagged and not args.redo:
            continue
        if args.only and args.only.lower() not in name:
            continue
        todo.append(name)

    if missing_entry:
        print("%d cards have no interruption in the config; run "
              "tools/migrate_playing_cards.py first:" % len(missing_entry))
        for n in missing_entry[:5]:
            print("   " + n)
        return 1

    print("%d of 54 already tagged. %d to scan in this run."
          % (len(tagged & set(deck())), len(todo)))
    if args.list or not todo:
        for n in todo:
            print("   " + pretty(n))
        return 0

    if service_is_up():
        print()
        print("The warlocktable service is running and owns the reader.")
        print("Stop it first:    sudo systemctl stop warlocktable")
        return 2

    print("opening the reader...")
    try:
        pn, firmware = open_reader(args.cs, args.reset)
    except Exception as exc:      # noqa: BLE001
        print("FAILED to open the PN532: %s: %s" % (type(exc).__name__, exc))
        print("Are you on the Pi, with the service stopped?")
        return 1
    print("reader ready (firmware %s)" % firmware)

    backup = "%s.bak-%s" % (args.config, time.strftime("%Y%m%d-%H%M%S"))
    shutil.copyfile(args.config, backup)
    print("backup: %s" % backup)
    print()
    print("Tap each card when asked, then LIFT IT OFF before the next one.")
    print("Ctrl-C to stop; everything scanned so far is already saved.")
    print()

    def save():
        tmp = args.config + ".tmp"
        io.open(tmp, "w", encoding="utf-8", newline="\n").write(
            json.dumps(cfg, indent=2) + "\n")
        os.replace(tmp, args.config)

    def wait_for_no_card():
        """Block until the field is empty, so one card cannot answer twice."""
        clear = 0
        while clear < 3:
            if pn.read_passive_target(timeout=0.25) is None:
                clear += 1
            else:
                clear = 0

    done = 0
    try:
        # Do not accept whatever is already sitting on the reader as the
        # answer to the first prompt.
        wait_for_no_card()

        for name in todo:
            label = pretty(name)
            print("[%2d/%2d]  TAP: %s" % (done + 1, len(todo), label),
                  flush=True)

            uid = None
            while uid is None:
                raw = pn.read_passive_target(timeout=0.25)
                if raw is None:
                    continue
                seen = format_uid(raw)
                if seen in owner and owner[seen] != label:
                    print("         that tag is already '%s' - use another "
                          "card" % owner[seen], flush=True)
                    wait_for_no_card()
                    continue
                uid = seen

            cards[uid] = {"label": label,
                          "target": {"type": "interruption", "name": name}}
            owner[uid] = label
            save()
            done += 1
            print("         UID %s" % uid, flush=True)
            print("         registered as '%s' -> %s" % (label, name),
                  flush=True)
            print("         lift the card off...", flush=True)
            wait_for_no_card()
            print(flush=True)

    except KeyboardInterrupt:
        print()
        print("stopped.")

    print("%d scanned, %d left to do." % (done, len(todo) - done))
    print()
    print("Start the table again:   sudo systemctl start warlocktable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
