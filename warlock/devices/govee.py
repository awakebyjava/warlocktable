"""Govee accent strips over the LAN API (plan doc 3.13).

Accent lighting in the room around the table, following the scene. Solid
colour and brightness — nothing else, deliberately.

LOCAL ONLY. Govee's official developer API is a CLOUD api: every command
would travel to their servers and back to a device in the same room, so
the table would need outbound internet to change the colour of a light
three feet away, and would go dark whenever the internet did. The LAN API
is plain UDP on this network and does everything this needs.

THE PROTOCOL

  discovery   multicast 239.255.255.250:4001, devices reply to UDP 4002
  commands    UDP to the device's own address, port 4003
  turn        {"msg":{"cmd":"turn","data":{"value":0|1}}}
  brightness  {"msg":{"cmd":"brightness","data":{"value":1..100}}}
  colour      {"msg":{"cmd":"colorwc","data":{"color":{"r":,"g":,"b":}}}}
  state       {"msg":{"cmd":"devStatus","data":{}}}

FOUR THINGS THAT ARE NOT OURS TO CHANGE

  1. LAN control is OFF by default and must be enabled per device in the
     Govee Home app. An un-enabled device is invisible to discovery and
     there is nothing to be done about it from here.
  2. Not every model supports it.
  3. Multicast is unreliable on consumer routers, so this broadcasts as
     well — belt and braces, and it costs one extra datagram.
  4. UDP has no acknowledgement. A command that vanishes leaves the room
     out of step until the next one, which is why set_scene re-sends the
     current colour periodically rather than trusting a single packet.

ADDRESSED BY DEVICE ID, NEVER BY IP. Those addresses are DHCP, on a
network where the Pi moved three times in one day. Discovery maps a
stable id to whatever address it has now.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from typing import Dict, List, Optional

MCAST_GROUP = "239.255.255.250"
SCAN_PORT = 4001            # where discovery requests go
LISTEN_PORT = 4002          # where every reply comes back
CMD_PORT = 4003             # where commands go, per device

SCAN_REQUEST = {"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}}

# How long to wait for devices to answer a scan. Generous: a strip on wifi
# at the far end of a garage is not quick, and discovery happens at startup
# where a second costs nothing.
DISCOVER_WAIT_S = 3.0

# Re-send the current colour this often. UDP gives no acknowledgement, so
# a dropped packet would otherwise leave the room on the previous scene
# until somebody changed it again. Cheap: one datagram per device.
REFRESH_S = 30.0


class GoveeAccent:
    """Accent strips that follow the scene. Never raises (plan doc 5.2)."""

    def __init__(self, log, device_ids: List[str], colours_path: str,
                 brightness: int = 100, static_ips: Optional[List[str]] = None):
        self.log = log
        # Normalised once: ids come from config and from the wire in
        # different cases, and comparing them raw is a bug waiting to be
        # written.
        self.wanted = {d.strip().upper() for d in device_ids if d.strip()}
        self.colours_path = colours_path
        self.brightness = max(1, min(100, int(brightness)))
        self.static_ips = list(static_ips or [])

        self._colours: Dict[str, List[int]] = {}
        self._addr: Dict[str, str] = {}        # device id -> current ip
        self._lock = threading.RLock()
        self._sock: Optional[socket.socket] = None
        self._scene: Optional[str] = None
        self._last_sent = 0.0
        self.healthy = False
        self.last_error: Optional[str] = None

    # ------------------------------------------------------------ lifecycle

    def start(self) -> bool:
        """Load the colours, find the devices. Never raises."""
        self._load_colours()
        if not self.wanted:
            self.last_error = "no govee devices configured"
            self.log.record("govee.disabled", reason=self.last_error)
            return False
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
        except OSError as exc:
            self.last_error = "could not open a socket: %s" % exc
            self.log.record("govee.unavailable", error=self.last_error)
            return False

        found = self.discover()
        self.healthy = bool(found)
        if not self.healthy:
            self.last_error = ("none of the configured devices answered; "
                               "check LAN Control is enabled in the Govee app")
            self.log.record("govee.no_devices", error=self.last_error)
        return self.healthy

    def close(self) -> None:
        with self._lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
            self.healthy = False

    # ------------------------------------------------------------ discovery

    def discover(self) -> Dict[str, str]:
        """Scan for the configured devices. Returns {device id: ip}."""
        if self._sock is None:
            return {}

        rx = None
        try:
            rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            rx.bind(("0.0.0.0", LISTEN_PORT))
            rx.settimeout(0.5)
        except OSError as exc:
            # Almost always something else already holding 4002.
            self.last_error = "cannot listen on %d: %s" % (LISTEN_PORT, exc)
            self.log.record("govee.discover_failed", error=self.last_error)
            if rx is not None:
                rx.close()
            return {}

        payload = json.dumps(SCAN_REQUEST).encode()
        targets = [(MCAST_GROUP, SCAN_PORT)]
        targets += [(ip, SCAN_PORT) for ip in self.static_ips]
        # Broadcast as well: multicast is what the protocol says and what
        # plenty of consumer routers quietly drop.
        targets.append(("255.255.255.255", SCAN_PORT))

        found: Dict[str, str] = {}
        try:
            for target in targets:
                try:
                    self._sock.sendto(payload, target)
                except OSError:
                    pass          # a bad static ip must not stop the scan
            end = time.time() + DISCOVER_WAIT_S
            while time.time() < end:
                try:
                    data, addr = rx.recvfrom(2048)
                except socket.timeout:
                    continue
                except OSError:
                    break
                try:
                    body = json.loads(data.decode()).get("msg", {}).get("data", {})
                except Exception:      # noqa: BLE001 -- other things use 4002
                    continue
                dev = str(body.get("device", "")).upper()
                if dev and dev in self.wanted:
                    found[dev] = addr[0]
        finally:
            rx.close()

        with self._lock:
            self._addr.update(found)
        missing = self.wanted - set(self._addr)
        self.log.record("govee.discovered", found=len(self._addr),
                        wanted=len(self.wanted),
                        missing=",".join(sorted(missing)) or None)
        return dict(found)

    # ------------------------------------------------------------ commands

    def _send(self, cmd: str, data: dict) -> int:
        """Fire one command at every known device. Returns how many were sent."""
        if self._sock is None:
            return 0
        payload = json.dumps({"msg": {"cmd": cmd, "data": data}}).encode()
        sent = 0
        with self._lock:
            addrs = list(self._addr.values())
        for ip in addrs:
            try:
                self._sock.sendto(payload, (ip, CMD_PORT))
                sent += 1
            except OSError as exc:
                self.last_error = "send to %s failed: %s" % (ip, exc)
        return sent

    def set_scene(self, scene_name: str) -> None:
        """Follow a scene. Unknown scene names are ignored, not an error.

        A scene with no colour is normal -- somebody may add one to config
        without regenerating the palette file -- and the room simply holds
        what it had rather than guessing.
        """
        name = (scene_name or "").strip().lower()
        colour = self._colours.get(name)
        if colour is None:
            self.log.record("govee.no_colour", scene=name)
            return
        with self._lock:
            self._scene = name
        self._apply(colour)

    def _apply(self, colour) -> None:
        r, g, b = (int(max(0, min(255, c))) for c in colour[:3])
        n = self._send("colorwc", {"color": {"r": r, "g": g, "b": b},
                                   "colorTemInKelvin": 0})
        self._send("brightness", {"value": self.brightness})
        self._last_sent = time.time()
        self.healthy = n > 0
        if n:
            self.last_error = None
        self.log.record("govee.colour", rgb="%d,%d,%d" % (r, g, b),
                        devices=n, real=True)

    def refresh(self) -> None:
        """Re-send the current colour if it has been a while.

        Called from the controller's periodic status tick. UDP drops are
        silent, so without this a lost packet leaves the room showing the
        previous scene indefinitely -- and the failure looks like the
        integration not working rather than one missing datagram.
        """
        with self._lock:
            scene = self._scene
        if not scene or (time.time() - self._last_sent) < REFRESH_S:
            return
        colour = self._colours.get(scene)
        if colour:
            self._apply(colour)

    # ------------------------------------------------------------ reporting

    def status(self) -> dict:
        with self._lock:
            addrs = dict(self._addr)
            scene = self._scene
        return {
            "healthy": self.healthy,
            "devices": len(addrs),
            "configured": len(self.wanted),
            "missing": sorted(self.wanted - set(addrs)),
            "scene": scene,
            "brightness": self.brightness,
            "error": self.last_error,
        }

    # ------------------------------------------------------------ internals

    def _load_colours(self) -> None:
        """Scene colours, DERIVED by tools/patterngen.py from the patterns.

        Not configured anywhere. The room and the table read the same
        source, so retuning a scene's palette moves both and they cannot
        drift apart.
        """
        try:
            with open(self.colours_path, encoding="utf-8") as fh:
                raw = json.load(fh)
            self._colours = {str(k).lower(): list(v) for k, v in raw.items()}
        except (OSError, ValueError) as exc:
            self._colours = {}
            self.last_error = "no scene colours: %s" % exc
            self.log.record("govee.no_colours", path=self.colours_path,
                            error=str(exc))


class FakeGoveeAccent:
    """Logs what it would have sent. Same shape as the real one."""

    def __init__(self, log, **_):
        self.log = log
        self.scene = None
        self.healthy = True

    def start(self) -> bool:
        self.log.record("govee.fake_ready")
        return True

    def discover(self) -> dict:
        return {}

    def set_scene(self, scene_name: str) -> None:
        self.scene = scene_name
        self.log.record("govee.colour", scene=scene_name, real=False)

    def refresh(self) -> None:
        pass

    def close(self) -> None:
        pass

    def status(self) -> dict:
        return {"healthy": True, "devices": 0, "configured": 0,
                "missing": [], "scene": self.scene, "brightness": 100,
                "error": None}
