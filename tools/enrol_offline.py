#!/usr/bin/env python3
"""Enrol playing cards by tapping them, with the service STOPPED.

    sudo systemctl stop warlocktable
    python3 tools/enrol_offline.py --only diamonds
    sudo systemctl start warlocktable

Run it over SSH from wherever you like; it has to run ON THE PI, because
it talks to the PN532 on the SPI bus directly.

WHY THIS EXISTS ALONGSIDE enrol_cards.py

enrol_cards.py drives the RUNNING table over its web API, so the
controller keeps the reader and the table stays alive while you enrol.
That is the right shape for adding one card mid-session.

It is the wrong shape for tagging a 54-card deck. Every tap goes through
the live controller, competes with whatever the table is doing, and
depends on a scratch buffer of recently-seen tags being in exactly the
state the tool expects. This one owns the reader outright: nothing else is
running, a tap is a tap, and there is no buffer to get out of step.

WHAT IT WRITES

config.json, after EVERY successful card, with one backup taken at the
start. Ctrl-C at any point keeps everything enrolled so far -- there is no
"save at the end" to lose.

It never reassigns a tag that already belongs to something else. Tapping
the wrong card is the likely mistake, and quietly stealing the tag from
its current owner is the worst possible response.
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
import queue

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)


class QuietLog:
    """NFCReader wants somewhere to record; nothing here needs a log file."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def record(self, kind: str, **kw) -> None:
        if self.verbose:
            print("     [%s %s]" % (kind, kw), flush=True)


def service_running() -> bool:
    try:
        out = subprocess.run(["systemctl", "is-active", "warlocktable"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() == "active"
    except Exception:      # noqa: BLE001 -- not systemd, or not permitted
        return False


def playing_card_names() -> "list[str]":
    """The 54, in deck order, from the migration's own definition so the
    two cannot drift."""
    sys.path.insert(0, os.path.join(REPO, "tools"))
    from migrate_playing_cards import RANKS, SUITS
    names = []
    for suit in SUITS:
        for rank in RANKS:
            names.append("%s_of_%s" % (rank, suit))
    names += ["joker_big", "joker_small"]
    return names


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="/var/lib/warlocktable/config.json")
    ap.add_argument("--only", default="",
                    help="substring filter, e.g. diamonds / ace / joker")
    ap.add_argument("--list", action="store_true",
                    help="show what still needs a tag, read nothing")
    ap.add_argument("--force", action="store_true",
                    help="run even if the service is up (it will fight you "
                         "for the reader)")
    ap.add_argument("--verbose", action="store_true",
                    help="print raw reader events")
    ap.add_argument("--cs", type=int, default=4)
    ap.add_argument("--reset", type=int, default=20)
    args = ap.parse_args()

    cfg = json.load(io.open(args.config, encoding="utf-8"))
    cards = cfg.setdefault("cards", {})
    interruptions = cfg.get("interruptions", {})

    # uid -> what already owns it, so a mis-tap can be named rather than
    # silently overwritten.
    owner = {uid: c.get("label", uid) for uid, c in cards.items()}
    taken = {c.get("target", {}).get("name")
             for c in cards.values() if c.get("target")}

    todo = []
    for name in playing_card_names():
        if name not in interruptions:
            continue                      # migration has not been run
        if name in taken:
            continue                      # already has a tag
        if args.only and args.only.lower() not in name:
            continue
        todo.append(name)

    if args.list or not todo:
        done = sum(1 for n in playing_card_names() if n in taken)
        print("%d of 54 playing cards have a tag; %d match this run"
              % (done, len(todo)))
        for n in todo:
            print("   " + n)
        return 0

    if service_running() and not args.force:
        print("The warlocktable service is running. Stop it first:")
        print()
        print("    sudo systemctl stop warlocktable")
        print()
        print("It owns the SPI reader; two readers on one bus is how you get")
        print("taps that land nowhere. Pass --force to override.")
        return 2

    from warlock.inputs.nfc import NFCReader

    taps: "queue.Queue[str]" = queue.Queue()
    reader = NFCReader(QuietLog(args.verbose), taps.put,
                       cs=args.cs, reset=args.reset)

    print("connecting to the reader...", flush=True)
    if not reader.start(wait_s=15.0):
        print("FAILED: %s" % (getattr(reader, "last_error", None)
                              or "no PN532 on SPI cs=%d reset=%d"
                              % (args.cs, args.reset)))
        print("Is the service really stopped? Are you running this on the Pi?")
        return 1

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = "%s.bak-%s" % (args.config, stamp)
    shutil.copyfile(args.config, backup)

    print("reader ready. %d cards to tag." % len(todo))
    print("backup: %s" % backup)
    print("Ctrl-C to stop; everything tagged so far is already saved.")
    print()

    def save() -> None:
        tmp = args.config + ".tmp"
        io.open(tmp, "w", encoding="utf-8", newline="\n").write(
            json.dumps(cfg, indent=2) + "\n")
        os.replace(tmp, args.config)

    done = 0
    try:
        for name in todo:
            label = name.replace("_", " ").title()
            print("  TAP:  %s" % label, flush=True)

            uid = None
            while uid is None:
                try:
                    got = taps.get(timeout=1.0)
                except queue.Empty:
                    continue
                if got in owner:
                    print("     that tag is already %s -- try another"
                          % owner[got], flush=True)
                    continue
                uid = got

            try:
                typed = input("     label [%s]: " % label).strip()
            except EOFError:
                typed = ""
            if typed:
                label = typed

            # Shape copied from what is already in the file: the uid is
            # the KEY, not a field, and the target discriminator is "type".
            cards[uid] = {"label": label,
                          "target": {"type": "interruption", "name": name}}
            owner[uid] = label
            save()
            done += 1
            print("     registered %s  (%d/%d)" % (uid, done, len(todo)),
                  flush=True)
            print("     lift the card off the reader", flush=True)
            print(flush=True)
    except KeyboardInterrupt:
        print()
        print("stopped.")
    finally:
        reader.stop()

    print("%d enrolled. %d still need a tag."
          % (done, len(todo) - done))
    print()
    print("Start the table again:  sudo systemctl start warlocktable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
