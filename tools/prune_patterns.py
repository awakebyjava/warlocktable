#!/usr/bin/env python3
"""Delete stock patterns from the Pixelblaze, one at a time, verifying each.

    python tools/prune_patterns.py --dry-run
    python tools/prune_patterns.py --limit 5
    python tools/prune_patterns.py

NEVER deletes anything this project wrote, anything the live config
references, or the keep-list. The referenced list must be passed in with
--used, because the config lives on the Pi and this tool runs on the
laptop -- guessing it is how you silently break seven cards.

HOW THIS DIFFERS FROM THE RUN THAT WENT WRONG

A bulk unattended upload filled the device's flash, hung mid-write, wedged
its websocket, and cost a power cycle and the entire LED configuration. So:

  - one operation at a time, in the foreground, nothing backgrounded
  - after each delete: confirm the pattern is gone, the full list is still
    readable, and the device is still rendering
  - stop on the FIRST failure rather than trying the next one
  - a deliberate pause between operations rather than hammering

Deleting frees space, so this direction is the safe one to run first.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import socket
import time

import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from archive_patterns import safe_filename          # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(REPO, "data", "device-state.json")
ARCHIVE = os.path.join(REPO, "patterns", "legacy", "device-archive")
GENERATED = os.path.join(REPO, "patterns", "generated")
TIMEOUT_S = 45.0
PAUSE_S = 1.5

OURS_EXACT = {"breathing", "zones", "Forest", "Plains", "Island",
              "Mountain", "Swamp"}
OURS_PREFIX = ("Boon-", "Person-", "Aura-")


def is_ours(name: str) -> bool:
    return name in OURS_EXACT or name.startswith(OURS_PREFIX) or "+" in name


def address() -> str:
    try:
        with io.open(STATE, encoding="utf-8") as fh:
            return json.load(fh).get("pixelblaze_address") or "10.10.0.171"
    except Exception:
        return "10.10.0.171"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--address", default=None)
    ap.add_argument("--used", default="",
                    help="comma-separated pattern names the live config "
                         "references; these are never deleted")
    ap.add_argument("--keep", default="Pac-Man Ghosts,New Pacman Ghosts",
                    help="comma-separated names to keep regardless")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--containing", default="",
                    help="delete patterns whose NAME contains this substring, "
                         "including ones this project wrote. Opt-in and "
                         "explicit, because the default refuses to touch our "
                         "own patterns and that default is worth keeping. "
                         "--used and --keep still protect absolutely. Used to "
                         "retire the 40 aura-x-scene combos ('+') when "
                         "layering was abandoned.")
    args = ap.parse_args()

    import websocket
    import pixelblaze

    socket.setdefaulttimeout(TIMEOUT_S)
    websocket.setdefaulttimeout(TIMEOUT_S)

    used = {s.strip() for s in args.used.split(",") if s.strip()}
    keep = {s.strip() for s in args.keep.split(",") if s.strip()}
    if not used:
        print("refusing to run without --used: the config's referenced")
        print("patterns must be named explicitly, not guessed.")
        return 2

    pb = None
    deleted = 0
    try:
        pb = pixelblaze.Pixelblaze(args.address or address())
        pats = pb.getPatternList()
        st = pb.getStatistics()
        print("device: %d patterns, %d bytes free, %.0f fps"
              % (len(pats), st["storageSize"] - st["storageUsed"], st["fps"]),
              flush=True)

        if args.containing:
            # Explicitly named class of our own patterns. --used and --keep
            # still win: this widens WHICH of our patterns may go, never
            # whether a referenced one may.
            targets = sorted((pid, n) for pid, n in pats.items()
                             if args.containing in n
                             and n not in used and n not in keep)
            print("--containing %r: %d to delete (%d protected by --used/--keep)"
                  % (args.containing, len(targets),
                     sum(1 for n in pats.values() if args.containing in n
                         and (n in used or n in keep))), flush=True)
        else:
            targets = sorted((pid, n) for pid, n in pats.items()
                             if not is_ours(n) and n not in used and n not in keep)
            print("%d to delete (protected: %d ours, %d in use, %d kept)"
                  % (len(targets), sum(1 for n in pats.values() if is_ours(n)),
                     len(used & set(pats.values())), len(keep & set(pats.values()))),
                  flush=True)
        print(flush=True)

        for pid, name in targets:
            # Refuse to delete anything not archived. The archive is the
            # only thing making this reversible.
            #
            # Uses archive_patterns' OWN function rather than a second
            # implementation: they disagreed at first (one collapsed runs of
            # odd characters, the other did not), so "Example: time and
            # animation" looked unarchived when it was not. Two copies of a
            # naming rule is two chances to be wrong.
            #
            # For patterns THIS project generated, patterns/generated/ in
            # git is the archive -- a better one, since it is the source
            # they were built from rather than a copy pulled back off the
            # device. Only stock patterns depend on the device-archive.
            recoverable = (
                os.path.exists(os.path.join(ARCHIVE, safe_filename(name) + ".js"))
                or os.path.exists(os.path.join(GENERATED, name + ".js")))
            if not recoverable:
                print("  %-34s NOT ARCHIVED - skipping" % name[:34], flush=True)
                continue

            if args.dry_run:
                print("  would delete %s" % name, flush=True)
                continue

            try:
                pb.deletePattern(pid)
            except Exception as exc:   # noqa: BLE001
                print("  %-34s DELETE FAILED %s" % (name[:34], str(exc)[:40]),
                      flush=True)
                print("  stopping on first failure.", flush=True)
                return 1

            time.sleep(PAUSE_S)

            # Verify on a FRESH connection. getPatternList() is cached in
            # the client, so asking the same session whether the pattern is
            # gone returns the stale list and reports a false failure --
            # which it did on the very first delete. Reconnecting per
            # verification is slow; that is the point.
            try:
                pb._close()
            except Exception:
                pass
            time.sleep(0.5)
            try:
                pb = pixelblaze.Pixelblaze(args.address or address())
                now = pb.getPatternList()
                st = pb.getStatistics()
            except Exception as exc:   # noqa: BLE001
                print("  %-34s deleted, but the device stopped responding: %s"
                      % (name[:34], str(exc)[:40]), flush=True)
                print("  STOPPING.", flush=True)
                return 1

            if name in now.values():
                print("  %-34s still present after delete - STOPPING"
                      % name[:34], flush=True)
                return 1

            deleted += 1
            print("  %-34s gone | %2d left | %7d free | %.0f fps"
                  % (name[:34], len(now), st["storageSize"] - st["storageUsed"],
                     st["fps"]), flush=True)

            if args.limit and deleted >= args.limit:
                print("reached --limit %d" % args.limit, flush=True)
                break

        print(flush=True)
        print("deleted %d" % deleted, flush=True)
    finally:
        if pb is not None:
            try:
                pb._close()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
