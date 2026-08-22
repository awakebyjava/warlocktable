#!/usr/bin/env python3
"""Upload generated patterns ONE AT A TIME, verifying each before the next.

    python tools/upload_watched.py --dry-run
    python tools/upload_watched.py --limit 5
    python tools/upload_watched.py

STOP THE CONTROLLER FIRST:

    ssh raspberrypi.local sudo systemctl stop warlocktable

Not optional. The controller reconnects to the Pixelblaze every 10 seconds,
and that loop exhausts the device's small pool of websocket slots. A prune
run wedged the websocket mid-way with the controller up and recovered the
moment it was stopped -- and the same contention very likely made the
original bulk upload's hang worse than it needed to be.

WHAT WENT WRONG BEFORE

An unattended bulk upload filled the flash and hung mid-write, which wedged
the websocket, cost a power cycle, and lost the entire LED configuration --
pixel count, colour order, LED type, and the brightness limit that keeps the
table inside its 40 A supply. The capacity estimate that said it would fit
counted source bytes and ignored the 8,655-byte preview image being stamped
onto every pattern.

SO, AFTER EVERY SINGLE UPLOAD, ON A FRESH CONNECTION:

  1. the pattern is listed
  2. its source reads back and matches the local file byte for byte
  3. the device is still rendering (fps > 0)
  4. pixelCount is still 764 and the brightness limit is still 50
  5. free space is still above the floor

Any one of those failing stops the run immediately and says why. A fresh
connection per check is required because the client caches the pattern list
and will happily report stale state -- that produced a false failure on the
first delete of the prune run.
"""

from __future__ import annotations

import argparse
import glob
import io
import json
import os
import socket
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN_DIR = os.path.join(REPO, "patterns", "generated")
STATE = os.path.join(REPO, "data", "device-state.json")

FLOOR_BYTES = 150 * 1024
TIMEOUT_S = 45.0
PAUSE_S = 1.5

# What the LED reference records for this table. Checked after every upload:
# these were silently lost once already, and a table that is quietly
# reconfigured to 100% brightness is a power problem, not a cosmetic one.
EXPECT_PIXELS = 764
EXPECT_LIMIT = 50


def address() -> str:
    try:
        with io.open(STATE, encoding="utf-8") as fh:
            return json.load(fh).get("pixelblaze_address") or "10.10.0.171"
    except Exception:
        return "10.10.0.171"


def connect(pixelblaze, addr):
    return pixelblaze.Pixelblaze(addr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--address", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--defer", default="",
                    help="comma-separated names to attempt LAST, after "
                         "everything else has gone up. For one that failed "
                         "before, so a repeat failure is unambiguous rather "
                         "than blocking the rest of the queue.")
    args = ap.parse_args()

    import websocket
    import pixelblaze

    socket.setdefaulttimeout(TIMEOUT_S)
    websocket.setdefaulttimeout(TIMEOUT_S)
    addr = args.address or address()

    files = sorted(glob.glob(os.path.join(GEN_DIR, "*.js")))
    pb = None
    done = 0
    try:
        pb = connect(pixelblaze, addr)
        existing = pb.getPatternList()
        st = pb.getStatistics()
        free = st["storageSize"] - st["storageUsed"]
        todo = [f for f in files
                if os.path.basename(f)[:-3] not in set(existing.values())]
        defer = {x.strip() for x in args.defer.split(",") if x.strip()}
        if defer:
            todo = ([f for f in todo if os.path.basename(f)[:-3] not in defer]
                    + [f for f in todo if os.path.basename(f)[:-3] in defer])
            print("deferring to last: %s" % ", ".join(sorted(defer)), flush=True)
        print("%d generated locally, %d already on device, %d to upload"
              % (len(files), len(files) - len(todo), len(todo)), flush=True)
        print("device: %d patterns, %d bytes free, %.0f fps"
              % (len(existing), free, st["fps"]), flush=True)
        print(flush=True)

        for path in todo:
            name = os.path.basename(path)[:-3]
            src = io.open(path, encoding="utf-8").read()

            if free < FLOOR_BYTES:
                print("STOPPING: %d bytes free, floor %d" % (free, FLOOR_BYTES),
                      flush=True)
                break
            if args.dry_run:
                print("  would upload %s" % name, flush=True)
                continue

            try:
                pb.savePattern(previewImage=b"", sourceCode=src, name=name)
            except Exception as exc:   # noqa: BLE001
                print("  %-24s UPLOAD FAILED: %s" % (name, str(exc)[:60]),
                      flush=True)
                print("  STOPPING. Nothing further attempted.", flush=True)
                return 1

            time.sleep(PAUSE_S)

            # --- verify on a fresh connection -----------------------------
            try:
                pb._close()
            except Exception:
                pass
            time.sleep(0.5)
            try:
                pb = connect(pixelblaze, addr)
                now = pb.getPatternList()
                st = pb.getStatistics()
                pixels = pb.getPixelCount()
                limit = pb.getBrightnessLimit()
            except Exception as exc:   # noqa: BLE001
                print("  %-24s uploaded, but the device stopped responding: %s"
                      % (name, str(exc)[:50]), flush=True)
                print("  STOPPING. Check the device before continuing.",
                      flush=True)
                return 1

            problems = []
            pid = next((p for p, n in now.items() if n == name), None)
            if pid is None:
                problems.append("not in the pattern list")
            else:
                # The source read comes back empty now and again on a
                # just-created pattern -- twice in one run, and both times
                # the pattern was verifiably correct a moment later. So a
                # single failed read is retried before it counts. A pattern
                # that reads wrong TWICE is a real problem; one that reads
                # wrong once is the device catching its breath.
                got = None
                for attempt in (1, 2):
                    try:
                        raw = pb.getPatternSourceCode(pid) or ""
                        got = json.loads(raw).get("main", raw)
                        break
                    except Exception as exc:   # noqa: BLE001
                        if attempt == 2:
                            problems.append("could not read source back twice "
                                            "(%s)" % str(exc)[:30])
                        else:
                            time.sleep(2.0)
                if got is not None and got.strip() != src.strip():
                    problems.append("source read back does not match")
            if st["fps"] <= 0:
                problems.append("device is not rendering (fps 0)")
            if pixels != EXPECT_PIXELS:
                problems.append("pixelCount is %s, expected %d"
                                % (pixels, EXPECT_PIXELS))
            if limit != EXPECT_LIMIT:
                problems.append("BRIGHTNESS LIMIT is %s, expected %d"
                                % (limit, EXPECT_LIMIT))

            free = st["storageSize"] - st["storageUsed"]
            if problems:
                print("  %-24s PROBLEM" % name, flush=True)
                for p in problems:
                    print("      - %s" % p, flush=True)
                print("  STOPPING.", flush=True)
                return 1

            done += 1
            print("  %-24s ok | %2d on device | %7d free | %.0f fps"
                  % (name, len(now), free, st["fps"]), flush=True)

            if args.limit and done >= args.limit:
                print("reached --limit %d" % args.limit, flush=True)
                break

        print(flush=True)
        print("uploaded %d, %d bytes free" % (done, free), flush=True)
    finally:
        if pb is not None:
            try:
                pb._close()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
