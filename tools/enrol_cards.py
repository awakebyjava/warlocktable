#!/usr/bin/env python3
"""Enrol NFC cards by tapping them, one at a time.

    python tools/enrol_cards.py                    # everything unassigned
    python tools/enrol_cards.py --only ace         # just the four Aces
    python tools/enrol_cards.py --list             # what still needs a tag

Run it from anywhere on the network. It drives the RUNNING table over its
web API, so:

  - the controller keeps ownership of the PN532, and the table stays alive
    while you enrol. A standalone reader program would have to stop the
    service first, because the panel and a CLI cannot both own the reader.
  - a tap you make is seen by the controller exactly as it would be during
    a game, so what you enrol is what will actually fire.

HOW IT WORKS

It shows the next target that has no card, waits for you to tap an
unrecognised tag, then registers that tag to that target and moves on. An
already-known tag is reported rather than silently reassigned, because
tapping the wrong card is the likely mistake and quietly stealing it from
its current target is the worst possible response.

Nothing is written until a tag is actually seen, so it is safe to stop at
any point -- ctrl-C leaves everything enrolled so far intact.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "http://raspberrypi.local:8080"
POLL_S = 0.7


def api(base, path, payload=None):
    url = base.rstrip("/") + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=15) as fh:
            return json.loads(fh.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            return {"error": json.loads(body).get("error", body)}
        except Exception:
            return {"error": body[:200]}
    except Exception as exc:   # noqa: BLE001
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=DEFAULT_BASE,
                    help="table URL (default: %s)" % DEFAULT_BASE)
    ap.add_argument("--only", default="",
                    help="only targets whose NAME contains this, e.g. 'ace' "
                         "or 'the_'. Matches the entry name, not the card "
                         "subtype -- the Auras are named the_devil, death, "
                         "judgement and so on, so 'aura' matches nothing.")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    targets = api(args.base, "/api/config/targets")
    if "error" in targets:
        print("cannot reach the table at %s: %s" % (args.base, targets["error"]))
        print("is the controller running?")
        return 2
    cards = api(args.base, "/api/config/cards").get("cards", [])

    # What already has a card, so the same tag is never asked for twice.
    assigned = {(c.get("target_kind"), c.get("target_name")) for c in cards}

    # The idle scene is where the table returns by itself when nothing else
    # is happening. A card for it would be a card that does nothing you
    # could not do by waiting.
    skip = {("scene", "idle")}

    todo = []
    for kind in ("interruption", "random_table", "scene"):
        for name in sorted(targets.get(kind, [])):
            if (kind, name) in assigned or (kind, name) in skip:
                continue
            if args.only and args.only.lower() not in name.lower():
                continue
            todo.append((kind, name))

    print("%d targets have a card; %d still need one"
          % (len(assigned), len(todo)))
    if args.list or not todo:
        for kind, name in todo:
            print("   %-14s %s" % (kind, name))
        return 0

    print("Tap each card when prompted. Ctrl-C to stop -- everything")
    print("enrolled up to that point is already saved.")
    print()

    # Ignore anything already sitting in the buffer from before we started.
    seen_before = {u["uid"] for u in
                   api(args.base, "/api/config/unassigned").get("unassigned", [])}

    done = 0
    try:
        for kind, name in todo:
            label = name.replace("_", " ").title()
            print("  TAP the card for:  %s  (%s)" % (label, kind), flush=True)
            uid = None
            while uid is None:
                time.sleep(POLL_S)
                got = api(args.base, "/api/config/unassigned")
                if "error" in got:
                    print("     lost the table: %s" % got["error"])
                    return 1
                for row in got.get("unassigned", []):
                    if row["uid"] not in seen_before:
                        uid = row["uid"]
                        break

            res = api(args.base, "/api/config/cards",
                      {"uid": uid, "label": label,
                       "target_kind": kind, "target_name": name})
            if "error" in res:
                print("     FAILED: %s" % res["error"])
                return 1
            seen_before.add(uid)
            done += 1
            print("     registered %s" % uid, flush=True)
            print(flush=True)
    except KeyboardInterrupt:
        print()
        print("stopped.")

    print("enrolled %d card(s); %d still to do" % (done, len(todo) - done))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
