#!/usr/bin/env python3
"""See what Pixels dice are saying, without connecting to any of them.

    /opt/warlocktable/venv/bin/pip install "bleak>=1.0,<2"     # once
    /opt/warlocktable/venv/bin/python -u tools/dice_probe.py
    /opt/warlocktable/venv/bin/python -u tools/dice_probe.py --all --seconds 120

RUNS ON THE PI. The service can stay running: this only listens to
Bluetooth advertisements, and nothing else on the table uses Bluetooth.
Note the `-u`, for the same reason as tag_probe.py -- without it nothing
appears until exit when stdout is not a terminal.

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

It also reports each die's firmware date and which service UUID family it
advertises, and flags the one thing that is actually a problem: the old
7-byte advert layout with no service data, which means the die needs
updating in the Pixels app before any of this works.

WHAT A LINE MEANS

    14:02:11.482  Jon's d20     1a2b3c4d  d20  rolled    20  batt 87%  rssi -61

One line per CHANGE in a die's advertised state (roll state, face or
battery), not per advert -- a die re-broadcasts the same thing several
times a second. `--all` prints every advert instead, which is how to see
the advert interval itself. `ROLL` in the margin marks a transition INTO
the `rolled` state, which is the one event the table will ever act on.

DECODER

The advert layout is the spec's section 2.1, confirmed against the
current React Native SDK. Manufacturer data (company 0xFFFF), 5 bytes:
LED count, design-and-colour (high nibble die type), roll state, face
index, battery (bit 7 charging). Service data under 0x180A, 8 bytes:
u32 pixel id, u32 firmware build timestamp. Older firmware packed 7 bytes
into manufacturer data and had no service data; that is flagged and
otherwise ignored.

`decode_advert()` is deliberately a pure function of the advert fields.
It will move into warlock/inputs/ unchanged when the real module is
built, with the tests written against it here.
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import struct
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

try:
    from bleak import BleakScanner
    from bleak.uuids import normalize_uuid_str
except ImportError:  # pragma: no cover - the message is the point
    sys.exit("bleak is not installed. On the Pi:\n"
             "  /opt/warlocktable/venv/bin/pip install \"bleak>=1.0,<2\"\n"
             "(1.x is the last line that supports the Pi's Python 3.9.)")


# --- protocol constants (spec section 2) -----------------------------

# The SDK calls 6e40... "legacyDie" and a6b9... "die", but a die on
# firmware 2024-11-07 -- current, the SDK's own last release is two weeks
# later -- advertises 6e40. So a6b9 is for some newer product, and the
# UUID family is reported as information, not as a fault. The only thing
# that IS a fault is the pre-service-data advert layout, below.
SERVICE_CURRENT = normalize_uuid_str("a6b90001-7a5a-43f2-a962-350c8edc9b5b")
SERVICE_LEGACY = normalize_uuid_str("6e400001-b5a3-f393-e0a9-e50e24dcca9e")
SERVICE_INFO = normalize_uuid_str("180a")
COMPANY_ID = 0xFFFF

ROLL_STATES = {
    0: "unknown",
    1: "rolled",     # a roll finished: THE event
    2: "handling",
    3: "rolling",
    4: "crooked",
    5: "onFace",     # set down flat; not a roll
}
ROLLED = 1

DIE_TYPES = {
    0: "unknown", 1: "d4", 2: "d6", 3: "d8", 4: "d10", 5: "d00",
    6: "d12", 7: "d20", 8: "d6pipped", 9: "d6fudge",
}


def face_value(die_type: str, face_index: int) -> int:
    """Face index -> the number printed on the die (spec 2.4)."""
    if die_type == "d10":
        return face_index
    if die_type == "d00":
        return face_index * 10
    if die_type == "unknown":
        return face_index
    return face_index + 1


@dataclass
class DieAdvert:
    pixel_id: int
    name: str
    die_type: str
    led_count: int
    colourway: int
    roll_state: int
    face_index: int
    battery: int
    charging: bool
    firmware: Optional[datetime]
    uuid_family: str        # "6e40" or "a6b9"
    old_layout: bool        # 7-byte advert, no service data: update the die

    @property
    def state_name(self) -> str:
        return ROLL_STATES.get(self.roll_state, "state%d" % self.roll_state)

    @property
    def face(self) -> int:
        return face_value(self.die_type, self.face_index)


def decode_advert(name: Optional[str],
                  manufacturer_data: Dict[int, bytes],
                  service_data: Dict[str, bytes],
                  service_uuids) -> Optional[DieAdvert]:
    """Turn one advertisement into a DieAdvert, or None if it is not a Pixel.

    Lenient about the company id: the SDK reads "the first manufacturer
    entry" rather than insisting on 0xFFFF, so if a firmware ever changes
    the id this keeps working. Strict about lengths, because that is what
    distinguishes the layouts.
    """
    uuids = {normalize_uuid_str(u) for u in (service_uuids or [])}
    is_current = SERVICE_CURRENT in uuids
    is_legacy = SERVICE_LEGACY in uuids
    if not (is_current or is_legacy):
        return None

    mdata = manufacturer_data.get(COMPANY_ID)
    if mdata is None and manufacturer_data:
        mdata = next(iter(manufacturer_data.values()))
    sdata = service_data.get(SERVICE_INFO)

    if mdata is not None and sdata is not None and len(sdata) >= 8 and len(mdata) >= 5:
        led_count, design, state, face, batt = struct.unpack_from("<BBBBB", mdata)
        pixel_id, build = struct.unpack_from("<II", sdata)
        firmware = datetime.fromtimestamp(build, tz=timezone.utc)
        old_layout = False
    elif mdata is not None and len(mdata) == 7 and sdata is None:
        # Pre-service-data firmware: id, then the five bytes, roughly.
        # Not worth decoding properly: the answer is "update the die".
        pixel_id = struct.unpack_from("<I", mdata)[0] if len(mdata) >= 4 else 0
        led_count = design = state = face = batt = 0
        firmware = None
        old_layout = True
    else:
        return None

    return DieAdvert(
        pixel_id=pixel_id,
        name=name or "",
        die_type=DIE_TYPES.get(design >> 4, "type%d" % (design >> 4)),
        led_count=led_count,
        colourway=design & 0x0F,
        roll_state=state,
        face_index=face,
        battery=batt & 0x7F,
        charging=bool(batt & 0x80),
        firmware=firmware,
        uuid_family="a6b9" if is_current else "6e40",
        old_layout=old_layout,
    )


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


def fmt_line(ts: float, adv: DieAdvert, rssi: int, mark: str = "") -> str:
    t = datetime.fromtimestamp(ts).strftime("%H:%M:%S.%f")[:-3]
    chg = " charging" if adv.charging else ""
    return "%s  %-14s %08x  %-8s %-9s %3d  batt %3d%%%s  rssi %4d  %s" % (
        t, adv.name[:14], adv.pixel_id, adv.die_type, adv.state_name,
        adv.face, adv.battery, chg, rssi, mark)


async def run(args) -> Dict[int, DieStats]:
    dice = {}  # type: Dict[int, DieStats]
    started = time.time()

    def on_advert(device, ad):
        now = time.time()
        adv = decode_advert(ad.local_name or device.name,
                            ad.manufacturer_data or {},
                            ad.service_data or {},
                            ad.service_uuids)
        if adv is None:
            return

        st = dice.get(adv.pixel_id)
        if st is None:
            st = dice[adv.pixel_id] = DieStats(adv)
            fw = adv.firmware.strftime("%Y-%m-%d") if adv.firmware else "?"
            print("\n== new die: %r  id %08x  %s  %d LEDs  firmware %s  uuid %s%s\n" % (
                adv.name, adv.pixel_id, adv.die_type, adv.led_count, fw,
                adv.uuid_family,
                "  OLD ADVERT LAYOUT - update this die in the Pixels app"
                if adv.old_layout else ""))

        st.adverts += 1
        st.rssi_min = min(st.rssi_min, ad.rssi)
        st.rssi_max = max(st.rssi_max, ad.rssi)
        gap = now - st.last_seen if st.last_seen else 0.0
        if st.last_seen:
            st.gaps.append(gap)

        mark = ""
        if adv.roll_state == ROLLED and st.last_state != ROLLED:
            st.rolls += 1
            mark = "ROLL #%d" % st.rolls
            # A long silence before a roll is a die waking from sleep;
            # that gap is the latency the GM will feel.
            if gap > 2.0:
                st.wake_gaps.append(gap)
                mark += "  (after %.1fs silence)" % gap

        key = (adv.roll_state, adv.face_index, adv.battery, adv.charging)
        if args.all or key != st.last_key or mark:
            print(fmt_line(now, adv, ad.rssi, mark))

        st.last_key = key
        st.last_state = adv.roll_state
        st.last_seen = now

    # DuplicateData=True is the whole trick on Linux. bleak's default is
    # False, which asks the controller to report each device ONCE per
    # scan and then stay silent about it; the kernel restarts the scan
    # every so often, so you get a snapshot a minute rather than a
    # stream. The first run at the table saw 2 adverts in 344 seconds
    # and none of the handling/rolling states in between. We want every
    # packet, because the state is IN the packet.
    scanner = BleakScanner(
        detection_callback=on_advert,
        service_uuids=[SERVICE_CURRENT, SERVICE_LEGACY],
        bluez={"filters": {"DuplicateData": True}},
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass

    print("Listening for Pixels dice (%s). Roll something. Ctrl-C to stop.\n"
          % ("every advert" if args.all else "changes only"))
    async with scanner:
        try:
            await asyncio.wait_for(stop.wait(), timeout=args.seconds)
        except asyncio.TimeoutError:
            pass
    print("\nRan %.0fs." % (time.time() - started))
    return dice


def summary(dice: Dict[int, DieStats]) -> None:
    if not dice:
        print("No Pixels dice heard. Checks: is Bluetooth up (`hciconfig`), "
              "is the die awake (roll it), is this user in the `bluetooth` group?")
        return
    print("\n%-14s %-8s %-8s %6s %6s %10s %12s %s" % (
        "die", "id", "type", "adverts", "rolls", "advert gap", "rssi", "wake latency"))
    for st in dice.values():
        a = st.first
        gaps = sorted(st.gaps)
        med = gaps[len(gaps) // 2] if gaps else 0.0
        wake = ("%.1fs max" % max(st.wake_gaps)) if st.wake_gaps else "-"
        print("%-14s %08x %-8s %6d %6d %8.2fs med %5d..%-5d %s" % (
            a.name[:14], a.pixel_id, a.die_type, st.adverts, st.rolls,
            med, st.rssi_min, st.rssi_max, wake))
    print("\nadvert gap = median seconds between adverts from that die while "
          "awake;\nwake latency = longest silence that preceded a roll "
          "(a die announcing itself after sleep).")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--all", action="store_true",
                   help="print every advert, not just changes")
    p.add_argument("--seconds", type=float, default=None,
                   help="stop after this long (default: until Ctrl-C)")
    args = p.parse_args()
    try:
        dice = asyncio.run(run(args))
    except KeyboardInterrupt:
        dice = {}
    summary(dice)


if __name__ == "__main__":
    main()
