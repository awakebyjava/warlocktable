"""Real Pixelblaze-backed LightDevice — the first fake swapped for hardware.

This is plan doc section 4.2 step 4. Nothing in warlock/controller.py changes
to use this; it satisfies the same base.LightDevice contract as the fake.

Three behaviours here come straight out of the reliability spec (section 5):

1. **Constructing this must never raise.** The controller has to boot with
   zero hardware present (5.2), so connection is lazy and retried in the
   background. A missing Pixelblaze makes lights unhealthy, not fatal.

2. **Address is discovered, not trusted.** Section 5.3 records that the
   Pixelblaze's IP has already drifted once (V0 had 10.1.10.165, V1 had
   10.10.0.171). Strategy: try the last-known-good address first because it
   is fast, fall back to UDP discovery, then persist whatever worked. That
   survives a DHCP change without paying discovery's latency every boot.

3. **Pattern names are read from the device**, never hardcoded, so the
   management UI can't offer a pattern that doesn't exist (4.5).
"""

from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional

from .base import DeviceError, LightDevice, UnknownAssetError

try:  # keep the import soft so the fake CLI runs on a machine without it
    import pixelblaze as _pixelblaze
except ImportError:  # pragma: no cover
    _pixelblaze = None


class PixelblazeLights(LightDevice):
    # Don't hammer a dead device on every action; back off between attempts.
    RECONNECT_INTERVAL_S = 10.0
    # Pattern lists change rarely (only when you author one), so cache them.
    PATTERN_CACHE_TTL_S = 60.0

    def __init__(self, log, address_hint: Optional[str] = None,
                 state_path: Optional[str] = None,
                 discovery_timeout_ms: int = 5000):
        self.log = log
        self.state_path = state_path
        self.discovery_timeout_ms = discovery_timeout_ms

        # Prefer an explicitly configured address, else the last one that worked.
        self.address = address_hint or self._load_last_known_address()

        self._pb = None
        self._last_attempt = 0.0
        self._patterns: Dict[str, str] = {}   # name -> pattern id
        self._patterns_fetched_at = 0.0

        self.current_pattern: Optional[str] = None
        self.healthy = False
        self.last_error: Optional[str] = None

    # ---------------------------------------------------------------- health

    def try_connect(self) -> bool:
        """Attempt one connection now, without raising.

        Connection is otherwise lazy, which keeps startup non-blocking (5.2)
        but means status() reads "not connected" until the first action fires.
        Startup calls this so it can report honestly, while a failure here
        still isn't fatal — the background retry takes over.
        """
        try:
            self._ensure()
            return True
        except DeviceError:
            return False

    def status(self) -> dict:
        """Feeds the panel's status strip and the TV status screen (5.1)."""
        return {
            "healthy": self.healthy,
            "address": self.address,
            "pattern": self.current_pattern,
            "error": self.last_error,
        }

    # ------------------------------------------------------------ connection

    def _load_last_known_address(self) -> Optional[str]:
        if not self.state_path or not os.path.exists(self.state_path):
            return None
        try:
            with open(self.state_path, "r", encoding="utf-8") as fh:
                return json.load(fh).get("pixelblaze_address")
        except (OSError, ValueError):
            return None

    def _save_last_known_address(self, address: str) -> None:
        if not self.state_path:
            return
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            data = {}
            if os.path.exists(self.state_path):
                with open(self.state_path, "r", encoding="utf-8") as fh:
                    try:
                        data = json.load(fh)
                    except ValueError:
                        data = {}
            data["pixelblaze_address"] = address
            with open(self.state_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except OSError as exc:
            # Not being able to remember the address is a nuisance, not a fault.
            self.log.record("lights.state_save_failed", error=str(exc))

    def _discover(self) -> Optional[str]:
        """UDP-beacon discovery. Returns an address or None.

        Verified working: with a deliberately wrong address hint, this found
        the real table and reconnected to it. That is the DHCP-drift recovery
        from section 5.3 actually working, not just theorised.
        """
        if _pixelblaze is None:
            return None
        try:
            found = list(_pixelblaze.Pixelblaze.EnumerateAddresses(
                timeout=self.discovery_timeout_ms))
        except Exception as exc:
            self.log.record("lights.discovery_failed", error=str(exc))
            return None
        if not found:
            return None
        if len(found) > 1:
            self.log.record("lights.discovery_multiple", found=list(found))
        return found[0]

    def _connect(self) -> None:
        """Try to establish a connection. Raises DeviceError on failure."""
        if _pixelblaze is None:
            raise DeviceError("pixelblaze-client is not installed")

        candidates = [a for a in (self.address,) if a]

        # Only pay for discovery if the known address didn't pan out.
        for address in candidates:
            try:
                pb = _pixelblaze.Pixelblaze(address)
                pb.getPatternList()          # prove it actually answers
                self._adopt(pb, address)
                return
            except Exception as exc:
                self.last_error = "%s: %s" % (address, exc)

        discovered = self._discover()
        if discovered and discovered not in candidates:
            try:
                pb = _pixelblaze.Pixelblaze(discovered)
                pb.getPatternList()
                self.log.record("lights.address_changed",
                                old=self.address, new=discovered)
                self._adopt(pb, discovered)
                return
            except Exception as exc:
                self.last_error = "%s: %s" % (discovered, exc)

        raise DeviceError("no Pixelblaze reachable (%s)" % (self.last_error or "no address"))

    def _adopt(self, pb, address: str) -> None:
        self._pb = pb
        if address != self.address:
            self._save_last_known_address(address)
        self.address = address
        self.healthy = True
        self.last_error = None
        self.log.record("lights.connected", address=address,
                        name=self._safe(pb.getDeviceName),
                        pixels=self._safe(pb.getPixelCount))

    @staticmethod
    def _safe(fn):
        try:
            return fn()
        except Exception:
            return None

    def _ensure(self):
        """Return a live connection, or raise DeviceError.

        Rate-limited so a dead device doesn't stall every single action with
        a fresh connection attempt.
        """
        if self._pb is not None and self.healthy:
            return self._pb

        now = time.monotonic()
        if now - self._last_attempt < self.RECONNECT_INTERVAL_S:
            raise DeviceError("pixelblaze unavailable (retry pending): %s"
                              % (self.last_error or "unknown"))
        self._last_attempt = now
        self._connect()
        return self._pb

    def _drop(self, exc: Exception) -> None:
        self._pb = None
        self.healthy = False
        self.last_error = str(exc)
        self.log.record("lights.disconnected", error=str(exc))

    # -------------------------------------------------------------- interface

    def set_pattern(self, name: str) -> None:
        pb = self._ensure()

        # Check the name against the device's own list BEFORE calling it.
        # setActivePatternByName() on an unknown name raises a confusing
        # "NoneType has no len()" from inside the library, which is
        # indistinguishable from a transport failure — and treating it as one
        # dropped the connection and blacked out lighting for the reconnect
        # interval. A bad name is a config error; the device is healthy.
        try:
            known = self.available_patterns()
        except DeviceError:
            known = []
        if known and name not in known:
            raise UnknownAssetError(
                "no pattern named %r on %s (%d patterns available)"
                % (name, self.address, len(known)))

        try:
            pb.setActivePatternByName(name)
        except Exception as exc:
            self._drop(exc)
            raise DeviceError("set_pattern(%r) failed: %s" % (name, exc))
        self.current_pattern = name
        self.log.record("lights.set_pattern", pattern=name, real=True)

    def set_brightness(self, level: float) -> None:
        level = max(0.0, min(1.0, float(level)))
        pb = self._ensure()
        try:
            # setBrightnessSlider is the runtime dimmer (0.0-1.0). Deliberately
            # NOT setBrightnessLimit, which is the persisted hardware ceiling
            # (currently 40) and is a power/thermal setting, not a scene control.
            pb.setBrightnessSlider(level)
        except Exception as exc:
            self._drop(exc)
            raise DeviceError("set_brightness(%s) failed: %s" % (level, exc))
        self.log.record("lights.set_brightness", level=level, real=True)

    def available_patterns(self) -> List[str]:
        now = time.monotonic()
        fresh = (now - self._patterns_fetched_at) < self.PATTERN_CACHE_TTL_S
        if self._patterns and fresh:
            return sorted(self._patterns.keys(), key=str.lower)

        pb = self._ensure()
        try:
            listing = pb.getPatternList()      # {id: name}
        except Exception as exc:
            self._drop(exc)
            raise DeviceError("available_patterns failed: %s" % exc)

        self._patterns = {name: pid for pid, name in listing.items()}
        self._patterns_fetched_at = now
        return sorted(self._patterns.keys(), key=str.lower)

    def close(self) -> None:
        """1.1.8 exposes only _close(); wrap it so callers have a public name."""
        if self._pb is not None:
            try:
                closer = getattr(self._pb, "close", None) or getattr(self._pb, "_close", None)
                if closer:
                    closer()
            except Exception:
                pass
        self._pb = None
        self.healthy = False
