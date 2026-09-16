#!/usr/bin/env python3
"""See what Pixels dice are saying, without connecting to any of them.

    sudo python3 -u tools/dice_probe.py
    sudo python3 -u tools/dice_probe.py --all --seconds 120

RUNS ON THE PI, AS ROOT. Standard library only -- nothing to install.
The service can stay running: this only listens to Bluetooth
advertisements, and nothing else on the table uses Bluetooth. Note the
`-u`, for the same reason as tag_probe.py -- without it nothing appears
until exit when stdout is not a terminal.

WHY THIS TALKS TO THE CHIP DIRECTLY

The first version used bleak, which goes through bluetoothd's discovery
API. On Bullseye (BlueZ 5.55) that API hands you ONE update per device
per minute -- verified at the table: 10 adverts in 406 seconds from a die
being rolled continuously, arriving on a 57-64s clock, with none of the
handling/rolling states in between. The DuplicateData filter made no
difference. `hcitool lescan --duplicates`, which bypasses bluetoothd and
drives the controller over a raw HCI socket, streamed the same die many
times a second. So this does what hcitool does, from Python's standard
library: open the raw socket, tell the controller to scan with duplicate
filtering OFF, and read LE Advertising Report events as they come.

That needs CAP_NET_RAW, hence sudo here and `AmbientCapabilities=` in the
systemd unit when this becomes part of the service. It also means we do
not depend on bleak at all, which on this Pi is a feature.

WHY THIS EXISTS

The plan is to read dice rolls from BLE advertisement packets and never
connect (pixels-dice-specification.md, section 3). Whether that is good
enough is a question with numbers in it -- how quickly a roll shows up,
whether a die that has been asleep announces its first roll promptly,
whether the Pi hears dice from every seat through the table housing, and
whether a permanent scan makes the iPad panel sluggish over the shared
Wi-Fi/Bluetooth radio. This prints those numbers. Run it at the table,
with every die, from every seat, with the Pixels app open on a phone at
the same time, and with the panel open on the iPad.

WHAT A LINE MEANS

    14:02:11.482  Jon's d20     1a2b3c4d  d20  rolled    20  batt 87%  rssi -61

One line per CHANGE in a die's advertised state (roll state, face or
battery), not per advert -- a die re-broadcasts the same thing many times
a second. `--all` prints every advert instead, which is how to see the
advert interval itself. `ROLL` in the margin marks a transition INTO the
`rolled` state, which is the one event the table will ever act on.

Every advert carries the state, name and battery; the pixel id and
firmware date ride only in the SCAN RESPONSE, which the chip requests
now and then. So the probe tracks by Bluetooth address and fills in the
id when it hears it (`--------` until then). A die has been seen using
two addresses ("Pixel..." and "PXL..."); the real module will fold them
together by id.

DECODER

The advert layout is the spec's section 2.1, confirmed against the
current React Native SDK. Manufacturer data (company 0xFFFF), 5 bytes:
LED count, design-and-colour (high nibble die type), roll state, face
index, battery (bit 7 charging). Service data under 0x180A, 8 bytes:
u32 pixel id, u32 firmware build timestamp. Older firmware packed 7 bytes
into manufacturer data and had no service data; that is flagged and
otherwise ignored.

The decoder and the raw HCI scanner live in warlock/inputs/dice.py --
this is a thin diagnostic over them, so a die that decodes here decodes
in the service. tests/test_dice.py covers the decoder with these bytes.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from typing import Dict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from warlock.inputs.dice import (   # noqa: E402  (the protocol lives there now)
    ROLLED, AdFields, DieAdvert, HciScanner, decode_advert, parse_ad)


# --- the probe --------------------------------------------------------

class DieStats:
    """What we learn about one die over the run."""

    def __init__(self, first: DieAdvert):
        self.first = first
        self.adverts = 0
        self.rolls = 0
        self.last_state = None      # type: Optional[int]
        self.last_key = None        # type: Optional[tuple]
        self.last_seen = 0.0
        self.gaps = []              # seconds between consecutive adverts
        self.rssi_min = 0
        self.rssi_max = -999
        self.wake_gaps = []         # gap preceding a roll after silence
        self.addresses = set()


def fmt_line(ts: float, adv: DieAdvert, rssi: int, mark: str = "") -> str:
    t = datetime.fromtimestamp(ts).strftime("%H:%M:%S.%f")[:-3]
    chg = " charging" if adv.charging else ""
    pid = "%08x" % adv.pixel_id if adv.pixel_id is not None else "--------"
    return "%s  %-14s %s  %-8s %-9s %3d  batt %3d%%%s  rssi %4d  %s" % (
        t, adv.name[:14], pid, adv.die_type, adv.state_name,
        adv.face, adv.battery, chg, rssi, mark)


def run(args) -> Dict[int, DieStats]:
    dice = {}                       # type: Dict[int, DieStats]
    by_addr = {}                    # type: Dict[str, AdFields]
    started = time.time()

    scanner = HciScanner()
    scanner.start()
    print("Listening for Pixels dice (%s). Roll something. Ctrl-C to stop.\n"
          % ("every advert" if args.all else "changes only"))

    try:
        while args.seconds is None or time.time() - started < args.seconds:
            for addr, data, rssi in scanner.reports(timeout=1.0):
                now = time.time()
                if args.raw and addr.startswith(args.raw):
                    t = datetime.fromtimestamp(now).strftime("%H:%M:%S.%f")[:-3]
                    print("%s  RAW %s rssi=%d  %s" % (t, addr, rssi, data.hex()))
                # Merge the advert and its scan response. Every advert
                # carries the state; only the occasional scan response
                # carries the id, so that is kept per address until the
                # next one arrives.
                fields = by_addr.get(addr)
                if fields is None:
                    fields = by_addr[addr] = AdFields()
                fresh = parse_ad(data)
                if fresh.manufacturer:
                    fields.manufacturer = fresh.manufacturer
                if fresh.service_data:
                    fields.service_data.update(fresh.service_data)
                if fresh.name:
                    fields.name = fresh.name
                for u in fresh.uuids:
                    if u not in fields.uuids:
                        fields.uuids.append(u)
                adv = decode_advert(fields)
                if adv is None:
                    continue

                st = dice.get(addr)
                if st is None:
                    st = dice[addr] = DieStats(adv)
                    print("\n== new die at %s: %r  %s  %d LEDs\n" % (
                        addr, adv.name, adv.die_type, adv.led_count))
                if adv.pixel_id is not None and st.first.pixel_id is None:
                    st.first = adv
                    fw = adv.firmware.strftime("%Y-%m-%d") if adv.firmware else "?"
                    print("\n== %s is pixel id %08x, firmware %s%s\n" % (
                        addr, adv.pixel_id, fw,
                        "  OLD ADVERT LAYOUT - update this die in the Pixels app"
                        if adv.old_layout else ""))
                st.addresses.add(addr)

                st.adverts += 1
                st.rssi_min = min(st.rssi_min, rssi)
                st.rssi_max = max(st.rssi_max, rssi)
                gap = now - st.last_seen if st.last_seen else 0.0
                if st.last_seen:
                    st.gaps.append(gap)

                mark = ""
                if adv.roll_state == ROLLED and st.last_state != ROLLED:
                    st.rolls += 1
                    mark = "ROLL #%d" % st.rolls
                    # A long silence before a roll is a die waking from
                    # sleep; that gap is the latency the GM will feel.
                    if gap > 2.0:
                        st.wake_gaps.append(gap)
                        mark += "  (after %.1fs silence)" % gap

                key = (adv.roll_state, adv.face_index, adv.battery, adv.charging)
                if args.all or key != st.last_key or mark:
                    print(fmt_line(now, adv, rssi, mark))

                st.last_key = key
                st.last_state = adv.roll_state
                st.last_seen = now
    except KeyboardInterrupt:
        pass
    finally:
        scanner.stop()
    print("\nRan %.0fs." % (time.time() - started))
    return dice


def summary(dice: Dict[int, DieStats]) -> None:
    if not dice:
        print("No Pixels dice heard. Checks: is Bluetooth up (`hciconfig`), "
              "is the die awake (roll it)?")
        return
    print("\n%-14s %-8s %-8s %7s %6s %11s %12s  %s" % (
        "die", "id", "type", "adverts", "rolls", "advert gap", "rssi", "wake latency"))
    for st in dice.values():
        a = st.first
        gaps = sorted(st.gaps)
        med = gaps[len(gaps) // 2] if gaps else 0.0
        wake = ("%.1fs max" % max(st.wake_gaps)) if st.wake_gaps else "-"
        print("%-14s %s %-8s %7d %6d %8.3fs med %5d..%-5d  %s" % (
            a.name[:14], "%08x" % a.pixel_id if a.pixel_id is not None else "--------",
            a.die_type, st.adverts, st.rolls,
            med, st.rssi_min, st.rssi_max, wake))
        print("%-14s addresses: %s" % ("", ", ".join(sorted(st.addresses))))
    print("\nadvert gap = median seconds between adverts from that die;\n"
          "wake latency = longest silence that preceded a roll "
          "(a die announcing itself after sleep).")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--all", action="store_true",
                   help="print every advert, not just changes")
    p.add_argument("--seconds", type=float, default=None,
                   help="stop after this long (default: until Ctrl-C)")
    p.add_argument("--raw", metavar="ADDR_PREFIX", default=None,
                   help="also hex-dump every report from addresses starting "
                        "with this, e.g. --raw CA:D8:66")
    args = p.parse_args()
    if not hasattr(socket, "AF_BLUETOOTH"):
        sys.exit("This needs Linux with Bluetooth sockets -- run it on the Pi.")
    if os.geteuid() != 0:
        sys.exit("Raw HCI scanning needs root: sudo python3 -u tools/dice_probe.py")
    dice = run(args)
    summary(dice)


if __name__ == "__main__":
    main()
