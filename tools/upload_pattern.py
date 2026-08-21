#!/usr/bin/env python3
"""Upload a pattern from patterns/ to the Pixelblaze.

    python tools/upload_pattern.py zones
    python tools/upload_pattern.py zones --activate
    python tools/upload_pattern.py --list

RUN THIS FROM THE LAPTOP, NOT THE PI. Compiling a pattern needs V8: the
client downloads the compiler out of the Pixelblaze's own web UI and runs it
through py_mini_racer, which has no ARM wheel. deploy/py_mini_racer.py stubs
it on the Pi so the controller can still import the client, so an upload
attempted there fails loudly rather than producing nonsense.

Compilation happens against the LIVE DEVICE, which is the point: the
bytecode is built by the compiler belonging to the firmware that will run
it, and a syntax error is caught by the real compiler rather than by a
guess about what the language accepts. Worth knowing, because the language
is not JavaScript however much the .js extension suggests otherwise --
user-defined functions need the `function` keyword, which cost this project
one bug that only the device could find.

Saving does NOT activate. A session in progress keeps whatever it is
showing unless you pass --activate.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import socket
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATTERN_DIR = os.path.join(REPO, "patterns")
STATE = os.path.join(REPO, "data", "device-state.json")

# Bound every socket operation. An un-closed or hung websocket previously
# exhausted this device's connection slots badly enough to need a physical
# power cycle; see the timeout notes in warlock/devices/pixelblaze_lights.py.
TIMEOUT_S = 15.0


def last_known_address() -> str | None:
    try:
        with io.open(STATE, encoding="utf-8") as fh:
            return json.load(fh).get("pixelblaze_address")
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pattern", nargs="?",
                    help="name of a file in patterns/ or patterns/generated/, "
                         "with or without .js")
    ap.add_argument("--address", default=None,
                    help="Pixelblaze IP (default: last known, from data/device-state.json)")
    ap.add_argument("--activate", action="store_true",
                    help="make it the active pattern after saving")
    ap.add_argument("--list", action="store_true",
                    help="just list what is on the device")
    args = ap.parse_args()

    if not args.pattern and not args.list:
        ap.error("give a pattern name, or --list")

    try:
        import websocket
        import pixelblaze
    except ImportError as exc:
        print("error: %s" % exc)
        print("this needs pixelblaze-client and py_mini_racer - laptop only")
        return 2

    address = args.address or last_known_address()
    if not address:
        print("error: no address given and none recorded in %s" % STATE)
        return 2

    socket.setdefaulttimeout(TIMEOUT_S)
    websocket.setdefaulttimeout(TIMEOUT_S)

    source = None
    if args.pattern:
        name = args.pattern[:-3] if args.pattern.endswith(".js") else args.pattern
        # Hand-written patterns live in patterns/; generated ones in
        # patterns/generated/. The device name is the bare filename either
        # way, so a generated pattern can sit alongside the original for
        # comparison without the directory leaking into the name.
        candidates = [os.path.join(PATTERN_DIR, name + ".js"),
                      os.path.join(PATTERN_DIR, "generated", name + ".js")]
        path = next((c for c in candidates if os.path.exists(c)), None)
        if path is None:
            print("error: no such pattern file. Looked in:")
            for c in candidates:
                print("   " + c)
            return 2
        source = io.open(path, encoding="utf-8").read()

    pb = None
    restore_to = None
    try:
        pb = pixelblaze.Pixelblaze(address)
        print("connected to %s (firmware %s, %s pixels)"
              % (address, pb.getVersion(), pb.getPixelCount()))

        existing = pb.getPatternList()
        active = existing.get(pb.getActivePattern())
        print("active pattern: %s" % active)

        if args.list:
            print("\n%d patterns on the device:" % len(existing))
            for n in sorted(existing.values(), key=str.lower):
                print("   " + n)
            return 0

        replacing = next((pid for pid, n in existing.items() if n == name), None)
        if replacing:
            print("'%s' already exists (%s) - saving over it" % (name, replacing))
            if active == name:
                # Don't leave the table dark mid-replace.
                restore_to = name

        # savePattern compiles first, so a syntax error stops us here having
        # written nothing.
        preview = _borrow_preview(pb, existing)
        new_id = pb.savePattern(previewImage=preview, sourceCode=source,
                                name=name, id=replacing)
        print("saved '%s' as %s" % (name, new_id))

        if args.activate:
            pb.setActivePatternByName(name)
            print("activated '%s'" % name)
        elif restore_to:
            pb.setActivePatternByName(restore_to)

        return 0

    except Exception as exc:
        print("FAILED: %s: %s" % (type(exc).__name__, exc))
        return 1
    finally:
        if pb is not None:
            try:
                pb._close()
            except Exception as exc:
                print("warning: close failed: %s" % exc)


def _borrow_preview(pb, existing) -> bytes:
    """A JPEG preview is required by savePattern.

    Pillow is not a dependency of this repo, and a hand-rolled JPEG is a
    guess about what the device accepts. Copying one the device itself
    produced is neither.
    """
    for pid in existing:
        try:
            image = pb.getPreviewImage(pid)
            if image:
                return image
        except Exception:
            continue
    return b""


if __name__ == "__main__":
    raise SystemExit(main())
