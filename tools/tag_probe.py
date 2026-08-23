#!/usr/bin/env python3
"""Identify NFC tags: what the reader sees, and what kind of chip it is.

    sudo systemctl stop warlocktable
    /opt/warlocktable/venv/bin/python tools/tag_probe.py
    sudo systemctl start warlocktable

RUNS ON THE PI, and the service must be stopped first: the controller
holds the PN532's SPI bus and GPIO reset pin, and the two cannot share it.

WHY THIS EXISTS

`enrol_cards.py` answers "which card is this" for tags the table already
knows how to use. This answers the earlier question: **can the reader see
this thing at all, and what is it?** For a drawer of unknown stock -- blank
tags, ID cards, key fobs -- that is the question, and the enrolment tool
cannot tell you because it only reports a UID.

WHAT IT READS THAT THE NORMAL PATH THROWS AWAY

The vendored driver's read_passive_target() returns the UID and nothing
else, which is all the table needs in play. The InListPassiveTarget
response also carries ATQA and SAK, and those are what identify the chip
family. So this issues the raw command and parses the whole reply:

    byte 0     number of targets
    byte 1     target number
    bytes 2-3  SENS_RES (ATQA)
    byte 4     SEL_RES  (SAK)   <- the interesting one
    byte 5     UID length
    bytes 6..  UID

For NTAG21x it then asks the chip directly with GET_VERSION (0x60), which
distinguishes 213 from 215 from 216 by storage size -- they are otherwise
identical on the wire and hold very different amounts.
"""

from __future__ import annotations

import argparse
import sys
import time

CS, RESET = 4, 20
INLISTPASSIVETARGET = 0x4A
INDATAEXCHANGE = 0x40
ISO14443A = 0x00

# SAK (SEL_RES) is the chip family. Values from NXP AN10833.
SAK = {
    0x00: "MIFARE Ultralight / NTAG",
    0x08: "MIFARE Classic 1K",
    0x09: "MIFARE Mini",
    0x10: "MIFARE Plus 2K (SL2)",
    0x11: "MIFARE Plus 4K (SL2)",
    0x18: "MIFARE Classic 4K",
    0x20: "ISO14443-4 (DESFire, JCOP, or a phone)",
    0x28: "MIFARE Classic + ISO14443-4 (SmartMX)",
    0x38: "MIFARE Classic 4K + ISO14443-4",
}

# GET_VERSION byte 6 is the storage size code.
NTAG_STORAGE = {
    0x0B: "NTAG210 / Ultralight (48 bytes user)",
    0x0E: "NTAG212 (128 bytes user)",
    0x0F: "NTAG213 (144 bytes user)",
    0x11: "NTAG215 (504 bytes user)",
    0x13: "NTAG216 (888 bytes user)",
}


def fmt(b) -> str:
    return ":".join("%02X" % x for x in b)


def classify(sak: int, uid_len: int) -> str:
    name = SAK.get(sak)
    if name:
        return name
    # Unknown SAKs are worth reporting rather than swallowing: an
    # unrecognised value is exactly the interesting case for a drawer of
    # mystery stock.
    return "unknown chip (SAK 0x%02X, %d-byte UID)" % (sak, uid_len)


def ntag_version(pn):
    """Ask an NTAG21x what it is. None if it does not answer.

    A chip that is not an NTAG will simply NAK this, which the driver
    surfaces as an exception -- so a failure here means 'not an NTAG',
    not 'something went wrong'.
    """
    try:
        resp = pn.call_function(INDATAEXCHANGE, params=[0x01, 0x60],
                                response_length=10, timeout=0.5)
    except Exception:      # noqa: BLE001
        return None
    if not resp or resp[0] != 0x00 or len(resp) < 8:
        return None
    body = resp[1:]
    if len(body) < 7:
        return None
    return NTAG_STORAGE.get(body[6], "NTAG-family, storage code 0x%02X" % body[6])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=300.0,
                    help="how long to keep listening (default 300)")
    args = ap.parse_args()

    try:
        sys.path.insert(0, "/opt/warlocktable")
        from warlock.vendor.pn532 import PN532_SPI
    except Exception as exc:      # noqa: BLE001
        print("cannot import the driver: %s" % exc)
        print("run this on the Pi, with the venv python")
        return 2

    try:
        pn = PN532_SPI(cs=CS, reset=RESET, debug=False)
        ver = pn.get_firmware_version()
        pn.SAM_configuration()
    except Exception as exc:      # noqa: BLE001
        print("could not open the reader: %s" % exc)
        print("is the service stopped?  sudo systemctl stop warlocktable")
        return 1

    print("PN532 firmware %d.%d ready. Tap tags one at a time." % (ver[1], ver[2]))
    print("Listening for %.0f seconds.\n" % args.seconds)
    print("%-3s %-26s %-6s %-5s %s" % ("#", "UID", "ATQA", "SAK", "WHAT IT IS"))

    seen = {}
    n = 0
    last_uid = None
    end = time.time() + args.seconds
    while time.time() < end:
        try:
            resp = pn.call_function(INLISTPASSIVETARGET,
                                    params=[0x01, ISO14443A],
                                    response_length=19, timeout=0.4)
        except Exception:      # noqa: BLE001 -- BusyError just means no tag
            resp = None
        if not resp or resp[0] != 0x01:
            last_uid = None       # tag removed; the next one counts as new
            continue

        atqa = (resp[2] << 8) | resp[3]
        sak = resp[4]
        uid = bytes(resp[6:6 + resp[5]])
        if uid == last_uid:
            continue              # still the same tag on the reader
        last_uid = uid

        what = classify(sak, len(uid))
        if sak == 0x00:
            detail = ntag_version(pn)
            if detail:
                what = detail

        n += 1
        key = fmt(uid)
        dupe = "  (already seen as #%d)" % seen[key] if key in seen else ""
        seen.setdefault(key, n)
        print("%-3d %-26s %04X   0x%02X  %s%s" % (n, key, atqa, sak, what, dupe),
              flush=True)

    print("\n%d taps, %d distinct tags." % (n, len(seen)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
