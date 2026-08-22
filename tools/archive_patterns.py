#!/usr/bin/env python3
"""Pull pattern sources off the Pixelblaze before anything deletes them.

    python tools/archive_patterns.py --list        # what is on the device
    python tools/archive_patterns.py --stock       # archive the stock ones
    python tools/archive_patterns.py --all         # archive everything

Writes to patterns/legacy/device-archive/, one .js per pattern, with a
header recording the pattern id and when it was taken.

WHY

The device's flash is the constraint, and the 48 stock demo patterns are
most of what fills it. Deleting them is the fix -- but "we can always
re-download them from Pixelblaze's library" is a claim nobody checks until
they need it. Archiving first costs a few minutes and makes the deletion
reversible from this repo alone.

There is precedent and a warning here: an earlier archiving run produced
patterns/legacy/forest.js containing a KITT pattern. The filename was
wrong. So this writes the device's own name into the file header as well
as using it for the filename, and refuses to overwrite an existing file.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import socket
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO, "patterns", "legacy", "device-archive")
STATE = os.path.join(REPO, "data", "device-state.json")
TIMEOUT_S = 45.0

# Ours: the generated set, plus the two hand-written ones still in use.
OURS_EXACT = {"breathing", "zones", "Forest", "Plains", "Island",
              "Mountain", "Swamp"}
OURS_PREFIX = ("Boon-", "Person-", "Aura-")


def is_ours(name: str) -> bool:
    return (name in OURS_EXACT or name.startswith(OURS_PREFIX)
            or "+" in name)


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._+-]+", "_", name).strip("_") or "unnamed"


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
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--stock", action="store_true",
                    help="archive only patterns this project did not write")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    import websocket
    import pixelblaze

    socket.setdefaulttimeout(TIMEOUT_S)
    websocket.setdefaulttimeout(TIMEOUT_S)

    pb = None
    saved = failed = 0
    try:
        pb = pixelblaze.Pixelblaze(args.address or address())
        pats = pb.getPatternList()
        stock = {p: n for p, n in pats.items() if not is_ours(n)}
        mine = {p: n for p, n in pats.items() if is_ours(n)}

        print("%d patterns: %d ours, %d stock"
              % (len(pats), len(mine), len(stock)), flush=True)

        if args.list:
            for n in sorted(stock.values(), key=str.lower):
                print("   stock  " + n)
            return 0

        targets = pats if args.all else stock
        if not (args.all or args.stock):
            print("nothing to do: pass --stock, --all or --list")
            return 2

        os.makedirs(OUT_DIR, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d")

        for pid, name in sorted(targets.items(), key=lambda kv: kv[1].lower()):
            path = os.path.join(OUT_DIR, safe_filename(name) + ".js")
            if os.path.exists(path):
                print("  %-34s already archived" % name[:34], flush=True)
                continue
            try:
                raw = pb.getPatternSourceCode(pid) or ""
                # The device wraps sources as {"main": "..."}; unwrap so the
                # archive is real source rather than a JSON blob.
                try:
                    src = json.loads(raw).get("main", raw)
                except Exception:
                    src = raw
            except Exception as exc:   # noqa: BLE001
                print("  %-34s FAILED %s" % (name[:34], str(exc)[:40]), flush=True)
                failed += 1
                continue

            header = (
                "// Archived from the Pixelblaze %s\n"
                "// Device pattern name: %s\n"
                "// Pattern id: %s\n"
                "// Taken by tools/archive_patterns.py before pruning the\n"
                "// device's flash. This file is a copy, not the source of\n"
                "// truth -- nothing in this project builds it.\n\n"
                % (stamp, name, pid))
            io.open(path, "w", encoding="utf-8", newline="\n").write(header + src)
            saved += 1
            print("  %-34s %6d bytes" % (name[:34], len(src)), flush=True)

        print(flush=True)
        print("archived %d, failed %d, into %s"
              % (saved, failed, os.path.relpath(OUT_DIR, REPO)), flush=True)
    finally:
        if pb is not None:
            try:
                pb._close()
            except Exception:
                pass
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
