"""Pixels dice — Bluetooth dice as an input (pixels-dice-specification.md).

    python -m warlock.inputs.dice          # standalone: print roll events (Pi, root)

The shape is `nfc.py`'s: a thread owns the hardware, catches its own
errors, reports health, and calls back into whatever wants roll events.
It knows nothing about the controller, config, scenes or seats. It says
"die 03ef405d, a d20, landed on 14" and stops there — the value is
carried, never interpreted (the handover's non-negotiable).

HOW IT LISTENS

It never connects to a die. Every Pixel broadcasts its state in its BLE
advertisement about five times a second while awake, so the Pi just
scans. That is why any number of dice works, why the Pixels phone app can
stay open, and why a die that has slept needs no reconnect. Verified at
the table 2026-09-16 (spec section 8).

The scan is a raw HCI socket, not bleak: BlueZ 5.55's discovery API
delivers one update per device per minute on this Pi, which is useless
for reading state out of adverts, and `hcitool` -- which drives the chip
directly -- streams it. So we do what hcitool does, from the standard
library. Needs CAP_NET_RAW (root, or AmbientCapabilities= in the unit).

WHAT IS IN A PACKET (spec 2.1, corrected by what the die actually sends)

Every ADVERT carries: the `180a` service UUID, 5 bytes of manufacturer
data (LED count, die type + colourway, roll state, face index, battery),
and the name. Only the occasional SCAN RESPONSE carries the pixel id,
firmware date and the Pixels service UUID. So state is tracked per
Bluetooth address from the first packet, and the id is filled in when
heard; a die has been seen using two addresses, which are folded together
once both have reported an id.

WHAT IS A ROLL

The transition INTO roll state 1, `rolled`. Nothing else. `onFace` (5) is
a die set down or picked up and replaced -- not a roll, and a table that
reacted to it would react to every fidget. Two rolls of the same face in
a row are two rolls, because the `rolling` packets in between are heard
(measured, spec 8). The same die reporting the same landing on both of
its addresses within a second is one roll.

The pure parts -- `parse_ad`, `decode_advert`, `RollTracker` -- have no
socket in them and are what tests/test_dice.py exercises.
"""

from __future__ import annotations

import os
import select
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, Iterator, List, Optional, Tuple


# --- protocol constants (spec section 2) ----------------------------------

# 6e40 is what a die on 2024-11-07 firmware advertises, though the SDK
# calls it "legacy"; a6b9 is the SDK's "current" and presumably a newer
# product. Both are accepted, neither is required (see decode_advert).
SERVICE_CURRENT = "a6b90001-7a5a-43f2-a962-350c8edc9b5b"
SERVICE_LEGACY = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
UUID_180A = "0000180a-0000-1000-8000-00805f9b34fb"
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


# --- advertising data -------------------------------------------------------

@dataclass
class AdFields:
    """The fields of one device's advertising, merged across packets."""
    name: Optional[str] = None
    manufacturer: Dict[int, bytes] = field(default_factory=dict)
    service_data: Dict[int, bytes] = field(default_factory=dict)
    uuids: List[str] = field(default_factory=list)


def _uuid128(raw: bytes) -> str:
    h = raw[::-1].hex()   # little-endian on the air
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
                u = struct.unpack_from("<H", payload, j)[0]
                f.uuids.append("%08x-0000-1000-8000-00805f9b34fb" % u)
        elif t in (0x06, 0x07):                     # 128-bit uuid list
            for j in range(0, len(payload) - 15, 16):
                f.uuids.append(_uuid128(payload[j:j + 16]))
    return f


@dataclass
class DieAdvert:
    """One decoded advertisement from one die."""
    name: str
    die_type: str
    led_count: int
    colourway: int
    roll_state: int
    face_index: int
    battery: int
    charging: bool
    pixel_id: Optional[int]           # None until a scan response is heard
    firmware: Optional[datetime]
    old_layout: bool                  # pre-2023 advert: update the die

    @property
    def state_name(self) -> str:
        return ROLL_STATES.get(self.roll_state, "state%d" % self.roll_state)

    @property
    def face(self) -> int:
        return face_value(self.die_type, self.face_index)


def decode_advert(fields: AdFields) -> Optional[DieAdvert]:
    """Merged advertising fields -> DieAdvert, or None if not a Pixel.

    Recognition: the Pixels service UUID if present (it usually is not --
    it rides in the scan response), else the 180a listing or a Pixel/PXL
    name, AND the 5-byte manufacturer layout. Company id 0xFFFF is the
    Bluetooth "test" id that hobby firmware uses, so it is not proof of
    anything on its own.
    """
    uuids = {u.lower() for u in fields.uuids}
    pixel_uuid = SERVICE_CURRENT in uuids or SERVICE_LEGACY in uuids
    name = fields.name or ""
    if not (pixel_uuid or UUID_180A in uuids
            or name.lower().startswith(("pixel", "pxl"))):
        return None

    mdata = fields.manufacturer.get(COMPANY_ID)
    if mdata is None and fields.manufacturer and pixel_uuid:
        mdata = next(iter(fields.manufacturer.values()))
    sdata = fields.service_data.get(SERVICE_INFO)

    if mdata is not None and len(mdata) == 5:
        led_count, design, state, face, batt = struct.unpack_from("<BBBBB", mdata)
        pixel_id = firmware = None
        if sdata is not None and len(sdata) >= 8:
            pixel_id, build = struct.unpack_from("<II", sdata)
            firmware = datetime.fromtimestamp(build, tz=timezone.utc)
        old_layout = False
    elif mdata is not None and len(mdata) == 7 and sdata is None and pixel_uuid:
        pixel_id = struct.unpack_from("<I", mdata)[0]
        led_count = design = state = face = batt = 0
        firmware = None
        old_layout = True
    else:
        return None

    return DieAdvert(
        name=name,
        die_type=DIE_TYPES.get(design >> 4, "type%d" % (design >> 4)),
        led_count=led_count,
        colourway=design & 0x0F,
        roll_state=state,
        face_index=face,
        battery=batt & 0x7F,
        charging=bool(batt & 0x80),
        pixel_id=pixel_id,
        firmware=firmware,
        old_layout=old_layout,
    )


# --- from packets to roll events ----------------------------------------------

@dataclass
class RollEvent:
    """A die landed. This is the whole of what the table learns."""
    address: str
    pixel_id: Optional[int]
    name: str
    die_type: str
    face: int
    face_index: int
    battery: int
    rssi: int
    timestamp: float

    @property
    def die_key(self) -> str:
        """Stable identity for config: the pixel id if known, else the address."""
        return "%08x" % self.pixel_id if self.pixel_id is not None else self.address


@dataclass
class KnownDie:
    """What the scanner currently knows about one Bluetooth address."""
    address: str
    fields: AdFields = field(default_factory=AdFields)
    name: str = ""
    die_type: str = "unknown"
    pixel_id: Optional[int] = None
    firmware: Optional[datetime] = None
    battery: int = 0
    charging: bool = False
    old_layout: bool = False
    last_state: Optional[int] = None
    last_seen: float = 0.0
    rssi: int = 0
    rolls: int = 0


class RollTracker:
    """Turns a stream of advertising reports into roll events. No I/O.

    feed() takes exactly what the HCI layer hands over and returns a
    RollEvent when a die has just landed, else None.
    """

    # Two addresses of one die can both announce the same landing; treat
    # a repeat of (id, face) inside this window as the same roll.
    SAME_ROLL_WINDOW_S = 1.5

    def __init__(self):
        self.dice: Dict[str, KnownDie] = {}
        self._last_roll: Dict[int, Tuple[float, int]] = {}   # pixel_id -> (t, face)

    def feed(self, address: str, data: bytes, rssi: int,
             now: Optional[float] = None) -> Optional[RollEvent]:
        now = time.time() if now is None else now
        die = self.dice.get(address)
        fields = die.fields if die else AdFields()
        # Each packet contributes what it carries. An advert brings fresh
        # manufacturer data (the state) and the name; a scan response
        # brings the service data (id, firmware) and the Pixels UUID, and
        # those are kept until the next one replaces them.
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
            return None

        if die is None:
            die = self.dice[address] = KnownDie(address=address, fields=fields)
        die.name = adv.name or die.name
        die.die_type = adv.die_type
        die.battery, die.charging = adv.battery, adv.charging
        die.old_layout = adv.old_layout
        die.last_seen, die.rssi = now, rssi
        if adv.pixel_id is not None:
            die.pixel_id, die.firmware = adv.pixel_id, adv.firmware

        event = None
        if adv.roll_state == ROLLED and die.last_state != ROLLED and not adv.old_layout:
            dup = False
            if die.pixel_id is not None:
                prev = self._last_roll.get(die.pixel_id)
                dup = (prev is not None and prev[1] == adv.face_index
                       and now - prev[0] < self.SAME_ROLL_WINDOW_S)
                self._last_roll[die.pixel_id] = (now, adv.face_index)
            if not dup:
                die.rolls += 1
                event = RollEvent(
                    address=address, pixel_id=die.pixel_id, name=die.name,
                    die_type=adv.die_type, face=adv.face,
                    face_index=adv.face_index, battery=adv.battery,
                    rssi=rssi, timestamp=now)
        die.last_state = adv.roll_state
        return event

    def snapshot(self, now: Optional[float] = None, stale_s: float = 300.0) -> List[dict]:
        """Dice heard recently, one entry per die (addresses folded by id)."""
        now = time.time() if now is None else now
        by_key: Dict[str, dict] = {}
        for d in self.dice.values():
            if now - d.last_seen > stale_s:
                continue
            key = "%08x" % d.pixel_id if d.pixel_id is not None else d.address
            cur = by_key.get(key)
            if cur is None or d.last_seen > cur["_seen"]:
                by_key[key] = {
                    "die": key, "name": d.name, "type": d.die_type,
                    "battery": d.battery, "charging": d.charging,
                    "rssi": d.rssi, "age_s": round(now - d.last_seen, 1),
                    "rolls": d.rolls + (cur["rolls"] if cur else 0),
                    "firmware": d.firmware.strftime("%Y-%m-%d") if d.firmware else None,
                    "old_layout": d.old_layout,
                    "_seen": d.last_seen,
                }
            else:
                cur["rolls"] += d.rolls
        out = sorted(by_key.values(), key=lambda e: e["die"])
        for e in out:
            e.pop("_seen", None)
        return out


# --- raw HCI ---------------------------------------------------------------------

HCI_COMMAND_PKT = 0x01
HCI_EVENT_PKT = 0x04
EVT_CMD_COMPLETE = 0x0E
EVT_CMD_STATUS = 0x0F
EVT_LE_META = 0x3E
LE_ADVERTISING_REPORT = 0x02
OGF_LE = 0x08
OCF_LE_SET_SCAN_PARAMETERS = 0x000B
OCF_LE_SET_SCAN_ENABLE = 0x000C


class HciScanner:
    """A raw HCI LE scan with duplicate filtering OFF. Linux, CAP_NET_RAW."""

    def __init__(self, dev_id: int = 0):
        self.sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_RAW,  # type: ignore[attr-defined]
                                  socket.BTPROTO_HCI)                   # type: ignore[attr-defined]
        self.sock.bind((dev_id,))
        type_mask = 1 << HCI_EVENT_PKT
        ev_lo = (1 << EVT_CMD_COMPLETE) | (1 << EVT_CMD_STATUS)
        ev_hi = 1 << (EVT_LE_META - 32)
        self.sock.setsockopt(socket.SOL_HCI, socket.HCI_FILTER,        # type: ignore[attr-defined]
                             struct.pack("<IIIH", type_mask, ev_lo, ev_hi, 0))

    def _cmd(self, ocf: int, params: bytes) -> int:
        op = (OGF_LE << 10) | ocf
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

    def start(self) -> None:
        self._cmd(OCF_LE_SET_SCAN_ENABLE, bytes([0x00, 0x00]))   # clear any leftover scan
        # active scan, interval = window = 10 ms (units of 0.625 ms): 100%
        # duty, so we would rather hear every packet than save power.
        params = struct.pack("<BHHBB", 0x01, 0x0010, 0x0010, 0x00, 0x00)
        st = self._cmd(OCF_LE_SET_SCAN_PARAMETERS, params)
        if st != 0:
            raise RuntimeError("LE Set Scan Parameters failed, status 0x%02x "
                               "(something else scanning?)" % st)
        st = self._cmd(OCF_LE_SET_SCAN_ENABLE, bytes([0x01, 0x00]))   # dup filter OFF
        if st != 0:
            raise RuntimeError("LE Set Scan Enable failed, status 0x%02x" % st)

    def stop(self) -> None:
        try:
            self._cmd(OCF_LE_SET_SCAN_ENABLE, bytes([0x00, 0x00]))
        finally:
            self.sock.close()

    def reports(self, timeout: float) -> Iterator[Tuple[str, bytes, int]]:
        """Yield (address, ad_bytes, rssi) until `timeout` seconds elapse."""
        end = time.time() + timeout
        while True:
            remaining = end - time.time()
            if remaining <= 0:
                return
            r, _, _ = select.select([self.sock], [], [], remaining)
            if not r:
                return
            pkt = self.sock.recv(300)
            if (len(pkt) < 5 or pkt[0] != HCI_EVENT_PKT or pkt[1] != EVT_LE_META
                    or pkt[3] != LE_ADVERTISING_REPORT):
                continue
            i = 5
            for _ in range(pkt[4]):
                if i + 9 > len(pkt):
                    break
                addr = ":".join("%02X" % b for b in pkt[i + 2:i + 8][::-1])
                length = pkt[i + 8]
                data = pkt[i + 9:i + 9 + length]
                if i + 9 + length >= len(pkt):
                    break
                rssi = struct.unpack_from("<b", pkt, i + 9 + length)[0]
                i += 10 + length
                yield addr, data, rssi


# --- the input --------------------------------------------------------------------

class DiceScanner:
    """The dice input. Owns the radio on its own thread; calls on_roll."""

    RECONNECT_INTERVAL_S = 15.0
    START_WAIT_S = 2.0

    def __init__(self, log, on_roll: Callable[[RollEvent], None], dev_id: int = 0):
        self.log = log
        self.on_roll = on_roll
        self.dev_id = dev_id
        self.tracker = RollTracker()

        self._hci: Optional[HciScanner] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._first_attempt = threading.Event()
        self._last_attempt = 0.0

        self.healthy = False
        self.last_error: Optional[str] = None
        self.rolls = 0
        self.last_roll: Optional[RollEvent] = None

    def start(self, wait_s: Optional[float] = None) -> bool:
        """Begin scanning on a thread. Never raises, never blocks on hardware."""
        if self._thread is not None:
            return self.healthy
        self._first_attempt.clear()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="dice-scanner",
                                        daemon=True)
        self._thread.start()
        self._first_attempt.wait(self.START_WAIT_S if wait_s is None else wait_s)
        return self.healthy

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def status(self) -> dict:
        return {
            "healthy": self.healthy,
            "error": self.last_error,
            "rolls": self.rolls,
            "last_roll": (
                {"die": self.last_roll.die_key, "name": self.last_roll.name,
                 "type": self.last_roll.die_type, "face": self.last_roll.face}
                if self.last_roll else None),
            "dice": self.tracker.snapshot(),
        }

    # ------------------------------------------------------------- internals

    def _open(self) -> bool:
        try:
            if not hasattr(socket, "BTPROTO_HCI"):
                raise RuntimeError("no Bluetooth HCI sockets on this platform (Linux only)")
            if os.geteuid() != 0 and not _has_net_raw():
                raise PermissionError("raw HCI needs CAP_NET_RAW (root, or "
                                      "AmbientCapabilities= in the service unit)")
            hci = HciScanner(self.dev_id)
            hci.start()
            self._hci = hci
            self.healthy = True
            self.last_error = None
            self.log.record("dice.scanning", hci=self.dev_id)
            return True
        except Exception as exc:   # noqa: BLE001 - many ways for a radio to fail
            self._hci = None
            self.healthy = False
            self.last_error = "%s: %s" % (type(exc).__name__, exc)
            self.log.record("dice.unavailable", error=self.last_error)
            return False

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                if self._hci is None:
                    now = time.monotonic()
                    if now - self._last_attempt < self.RECONNECT_INTERVAL_S:
                        self._stop.wait(1.0)
                        continue
                    self._last_attempt = now
                    opened = self._open()
                    self._first_attempt.set()
                    if not opened:
                        continue

                try:
                    for addr, data, rssi in self._hci.reports(timeout=1.0):
                        event = self.tracker.feed(addr, data, rssi)
                        if event is not None:
                            self._dispatch(event)
                        if self._stop.is_set():
                            break
                except Exception as exc:   # noqa: BLE001
                    self.healthy = False
                    self.last_error = "%s: %s" % (type(exc).__name__, exc)
                    self.log.record("dice.read_failed", error=self.last_error)
                    try:
                        self._hci.stop()
                    except Exception:
                        pass
                    self._hci = None
        finally:
            if self._hci is not None:
                try:
                    self._hci.stop()
                except Exception:
                    pass
                self._hci = None

    def _dispatch(self, event: RollEvent) -> None:
        self.rolls += 1
        self.last_roll = event
        self.log.record("dice.roll", die=event.die_key, name=event.name,
                        type=event.die_type, face=event.face, battery=event.battery)
        # The callback runs the controller. If it throws, the scanner must
        # not die with it.
        try:
            self.on_roll(event)
        except Exception as exc:   # noqa: BLE001
            self.log.record("dice.dispatch_failed", die=event.die_key,
                            error="%s: %s" % (type(exc).__name__, exc))


def _has_net_raw() -> bool:
    """True if this process holds CAP_NET_RAW (Linux only; best effort)."""
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("CapEff:"):
                    return bool(int(line.split()[1], 16) & (1 << 13))
    except OSError:
        pass
    return False


class FakeDiceScanner:
    """No radio: rolls are injected by the CLI (`dice d20 20`)."""

    def __init__(self, log, on_roll: Callable[[RollEvent], None]):
        self.log = log
        self.on_roll = on_roll
        self.healthy = True
        self.last_error = None
        self.rolls = 0
        self.last_roll: Optional[RollEvent] = None
        self.tracker = RollTracker()

    def start(self, wait_s: Optional[float] = None) -> bool:
        return True

    def stop(self, timeout: float = 0.0) -> None:
        pass

    def roll(self, die_type: str, face: int, name: str = "fake",
             die_key: str = "fake0001") -> RollEvent:
        idx = {"d10": face, "d00": face // 10}.get(die_type, face - 1)
        try:
            pixel_id: Optional[int] = int(die_key, 16)
        except ValueError:
            pixel_id = None
        event = RollEvent(address="00:00:00:00:00:00", pixel_id=pixel_id,
                          name=name, die_type=die_type, face=face,
                          face_index=idx, battery=100, rssi=-40,
                          timestamp=time.time())
        self.rolls += 1
        self.last_roll = event
        self.log.record("dice.roll", die=event.die_key, name=name,
                        type=die_type, face=face, fake=True)
        self.on_roll(event)
        return event

    def status(self) -> dict:
        return DiceScanner.status(self)  # type: ignore[arg-type]


# --- standalone ---------------------------------------------------------------------

def _main() -> None:
    import sys

    class _Log:
        def record(self, kind, **fields):
            print("  [%s] %s" % (kind, " ".join("%s=%s" % kv for kv in fields.items())))

    def on_roll(e: RollEvent) -> None:
        print("%s  ROLL  %-14s %s  %-4s -> %d   batt %d%%  rssi %d" % (
            datetime.fromtimestamp(e.timestamp).strftime("%H:%M:%S.%f")[:-3],
            e.name, e.die_key, e.die_type, e.face, e.battery, e.rssi))

    scanner = DiceScanner(_Log(), on_roll)
    if not scanner.start():
        err = scanner.last_error or ""
        if "HCI sockets" in err or "CAP_NET_RAW" in err:
            # Not going to fix itself by waiting.
            scanner.stop()
            sys.exit("cannot scan: %s" % err)
        print("scanner not up yet (%s); retrying in the background" % err)
    print("Roll something. Ctrl-C to stop.")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        scanner.stop()
    st = scanner.status()
    print("\n%d roll(s). Dice seen:" % st["rolls"])
    for d in st["dice"]:
        print("  %(die)s  %(name)-14s %(type)-5s batt %(battery)d%%  rolls %(rolls)d  "
              "rssi %(rssi)d  fw %(firmware)s" % d)
    sys.exit(0)


if __name__ == "__main__":
    _main()
