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

`decode_advert()` is a pure function of the advert fields and
`parse_ad()` a pure function of the raw bytes. Both will move into
warlock/inputs/ unchanged when the real module is built, with the tests
written against them here.
"""

from __future__ import annotations

import argparse
import os
import select
import socket
import struct
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


# --- protocol constants (spec section 2) -----------------------------

# The SDK calls 6e40... "legacyDie" and a6b9... "die", but a die on
# firmware 2024-11-07 -- current, the SDK's own last release is two weeks
# later -- advertises 6e40. So a6b9 is for some newer product, and the
# UUID family is reported as information, not as a fault. The only thing
# that IS a fault is the pre-service-data advert layout, below.
SERVICE_CURRENT = "a6b90001-7a5a-43f2-a962-350c8edc9b5b"
SERVICE_LEGACY = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
SERVICE_INFO = 0x180A
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
    has_id: bool            # False until a scan response has been heard

    @property
    def state_name(self) -> str:
        return ROLL_STATES.get(self.roll_state, "state%d" % self.roll_state)

    @property
    def face(self) -> int:
        return face_value(self.die_type, self.face_index)


def decode_advert(name: Optional[str],
                  manufacturer_data: Dict[int, bytes],
                  service_data: Dict[int, bytes],
                  service_uuids: List[str]) -> Optional[DieAdvert]:
    """Turn one (merged) advertisement into a DieAdvert, or None.

    Lenient about the company id: the SDK reads "the first manufacturer
    entry" rather than insisting on 0xFFFF. Lenient about UUIDs too: if
    the packet lists none we still try, since the data layout is
    distinctive enough. Strict about lengths, because that is what
    distinguishes the layouts.
    """
    uuids = {u.lower() for u in (service_uuids or [])}
    is_current = SERVICE_CURRENT in uuids
    is_legacy = SERVICE_LEGACY in uuids
    if uuids and not (is_current or is_legacy):
        return None

    mdata = manufacturer_data.get(COMPANY_ID)
    if mdata is None and manufacturer_data:
        mdata = next(iter(manufacturer_data.values()))
    sdata = service_data.get(SERVICE_INFO)

    if mdata is not None and len(mdata) == 5:
        # The advert. The id and firmware ride in the SCAN RESPONSE, which
        # the chip requests only now and then, so they are usually absent
        # here; the caller keeps the last one seen per address.
        led_count, design, state, face, batt = struct.unpack_from("<BBBBB", mdata)
        if sdata is not None and len(sdata) >= 8:
            pixel_id, build = struct.unpack_from("<II", sdata)
            firmware = datetime.fromtimestamp(build, tz=timezone.utc)
            has_id = True
        else:
            pixel_id, firmware, has_id = 0, None, False
        old_layout = False
    elif mdata is not None and len(mdata) == 7 and sdata is None and (is_current or is_legacy):
        # Pre-service-data firmware. Not worth decoding properly: the
        # answer is "update the die".
        pixel_id = struct.unpack_from("<I", mdata)[0]
        led_count = design = state = face = batt = 0
        firmware = None
        old_layout = True
        has_id = True
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
        has_id=has_id,
    )


# --- advertising data (the bytes inside a report) ----------------------

@dataclass
class AdFields:
    name: Optional[str] = None
    manufacturer: Dict[int, bytes] = field(default_factory=dict)
    service_data: Dict[int, bytes] = field(default_factory=dict)
    uuids: List[str] = field(default_factory=list)


def _uuid128(raw: bytes) -> str:
    b = raw[::-1]   # little-endian on the air
    h = b.hex()
    return "%s-%s-%s-%s-%s" % (h[:8], h[8:12], h[12:16], h[16:20], h[20:])


def parse_ad(data: bytes, into: Optional[AdFields] = None) -> AdFields:
    """Parse AD structures ([len][type][payload]...) into fields.

    An advertisement and its scan response are separate packets that
    together describe one device, so `into` lets the caller merge them.
    """
    f = into or AdFields()
    i = 0
    while i + 1 < len(data):
        length = data[i]
        if length == 0:
            break
        t = data[i + 1]
        payload = data[i + 2:i + 1 + length]
        i += 1 + length
        if t in (0x08, 0x09):                       # shortened / complete name
            f.name = payload.decode("utf-8", "replace")
        elif t == 0xFF and len(payload) >= 2:       # manufacturer specific
            f.manufacturer[struct.unpack_from("<H", payload)[0]] = payload[2:]
        elif t == 0x16 and len(payload) >= 2:       # service data, 16-bit uuid
            f.service_data[struct.unpack_from("<H", payload)[0]] = payload[2:]
        elif t in (0x02, 0x03):                     # 16-bit uuid list
            for j in range(0, len(payload) - 1, 2):
                f.uuids.append("%08x-0000-1000-8000-00805f9b34fb"
                               % struct.unpack_from("<H", payload, j)[0])
        elif t in (0x06, 0x07):                     # 128-bit uuid list
            for j in range(0, len(payload) - 15, 16):
                f.uuids.append(_uuid128(payload[j:j + 16]))
    return f


# --- raw HCI scanning ---------------------------------------------------

HCI_COMMAND_PKT = 0x01
HCI_EVENT_PKT = 0x04
EVT_CMD_COMPLETE = 0x0E
EVT_CMD_STATUS = 0x0F
EVT_LE_META = 0x3E
LE_ADVERTISING_REPORT = 0x02
OGF_LE = 0x08
OCF_LE_SET_SCAN_PARAMETERS = 0x000B
OCF_LE_SET_SCAN_ENABLE = 0x000C


def _opcode(ogf: int, ocf: int) -> int:
    return (ogf << 10) | ocf


class HciScanner:
    """A raw HCI LE scan with duplicate filtering off. Linux, root."""

    def __init__(self, dev_id: int = 0):
        self.sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_RAW,
                                  socket.BTPROTO_HCI)
        self.sock.bind((dev_id,))
        # Only deliver HCI events, and of those only command complete /
        # status (so we can see our own commands fail) and LE meta.
        type_mask = 1 << HCI_EVENT_PKT
        ev_lo = (1 << EVT_CMD_COMPLETE) | (1 << EVT_CMD_STATUS)
        ev_hi = 1 << (EVT_LE_META - 32)
        self.sock.setsockopt(socket.SOL_HCI, socket.HCI_FILTER,
                             struct.pack("<IIIH", type_mask, ev_lo, ev_hi, 0))

    def _cmd(self, ocf: int, params: bytes) -> int:
        """Send one LE command and return its status byte (0 = ok)."""
        op = _opcode(OGF_LE, ocf)
        self.sock.send(struct.pack("<BHB", HCI_COMMAND_PKT, op, len(params)) + params)
        deadline = time.time() + 2.0
        while time.time() < deadline:
            r, _, _ = select.select([self.sock], [], [], 0.2)
            if not r:
                continue
            pkt = self.sock.recv(300)
            if len(pkt) < 3 or pkt[0] != HCI_EVENT_PKT:
                continue
            evt, plen = pkt[1], pkt[2]
            if evt == EVT_CMD_COMPLETE and plen >= 4:
                _, rop, status = struct.unpack_from("<BHB", pkt, 3)
                if rop == op:
                    return status
            elif evt == EVT_CMD_STATUS and plen >= 4:
                status, _, rop = struct.unpack_from("<BBH", pkt, 3)
                if rop == op:
                    return status
        return -1

    def start(self, active: bool = True) -> None:
        # Stop any scan a previous run left on; ignore the result, since
        # "already off" is an error we do not care about.
        self._cmd(OCF_LE_SET_SCAN_ENABLE, bytes([0x00, 0x00]))
        # type, interval, window (units of 0.625 ms), own addr type,
        # filter policy. 100% duty cycle: we would rather hear every
        # packet than save the Pi's power.
        params = struct.pack("<BHHBB", 0x01 if active else 0x00,
                             0x0010, 0x0010, 0x00, 0x00)
        st = self._cmd(OCF_LE_SET_SCAN_PARAMETERS, params)
        if st != 0:
            raise RuntimeError(
                "LE Set Scan Parameters failed (status 0x%02x). Is something "
                "else scanning? Try: sudo hcitool lescan (then Ctrl-C), or "
                "sudo systemctl restart bluetooth" % st)
        st = self._cmd(OCF_LE_SET_SCAN_ENABLE, bytes([0x01, 0x00]))  # dup filter OFF
        if st != 0:
            raise RuntimeError("LE Set Scan Enable failed (status 0x%02x)" % st)

    def stop(self) -> None:
        try:
            self._cmd(OCF_LE_SET_SCAN_ENABLE, bytes([0x00, 0x00]))
        finally:
            self.sock.close()

    def reports(self, timeout: float):
        """Yield (event_type, address, ad_bytes, rssi) for reports arriving
        within `timeout` seconds; returns when it expires."""
        end = time.time() + timeout
        while True:
            remaining = end - time.time()
            if remaining <= 0:
                return
            r, _, _ = select.select([self.sock], [], [], remaining)
            if not r:
                return
            pkt = self.sock.recv(300)
            if len(pkt) < 4 or pkt[0] != HCI_EVENT_PKT or pkt[1] != EVT_LE_META:
                continue
            if pkt[3] != LE_ADVERTISING_REPORT:
                continue
            num = pkt[4]
            i = 5
            for _ in range(num):
                if i + 8 > len(pkt):
                    break
                evt_type, addr_type = pkt[i], pkt[i + 1]
                addr = ":".join("%02X" % b for b in pkt[i + 2:i + 8][::-1])
                length = pkt[i + 8]
                data = pkt[i + 9:i + 9 + length]
                rssi = struct.unpack_from("<b", pkt, i + 9 + length)[0]
                i += 10 + length
                yield evt_type, addr, data, rssi


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
    pid = "%08x" % adv.pixel_id if adv.has_id else "--------"
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
            for evt_type, addr, data, rssi in scanner.reports(timeout=1.0):
                now = time.time()
                if args.raw and addr.startswith(args.raw):
                    t = datetime.fromtimestamp(now).strftime("%H:%M:%S.%f")[:-3]
                    print("%s  RAW %s type=%d rssi=%d  %s" % (
                        t, addr, evt_type, rssi, data.hex()))
                # Merge the advert and its scan response. Every advert
                # carries the state; only the occasional scan response
                # carries the id, so that is kept per address until the
                # next one arrives.
                fields = by_addr.get(addr)
                if fields is None:
                    fields = by_addr[addr] = AdFields()
                fields.manufacturer = {}
                parse_ad(data, fields)
                adv = decode_advert(fields.name, fields.manufacturer,
                                    fields.service_data, fields.uuids)
                if adv is None:
                    continue

                st = dice.get(addr)
                if st is None:
                    st = dice[addr] = DieStats(adv)
                    print("\n== new die at %s: %r  %s  %d LEDs  uuid %s\n" % (
                        addr, adv.name, adv.die_type, adv.led_count, adv.uuid_family))
                if adv.has_id and not st.first.has_id:
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
            a.name[:14], "%08x" % a.pixel_id if a.has_id else "--------",
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
