"""PN532 NFC reader — the real card input (plan doc 3.2, 4.3).

Replaces the CLI's simulated `card <name>` command with physical taps.

Wiring on this table: SPI, cs=4, reset=20 (carried over from V1, confirmed
working against PN532 firmware 1.6).

Design notes, all of which come from the spec rather than convenience:

**Every card is a tap, never a presence** (4.3). Physical presence detection
was considered and deliberately rejected. So this fires exactly once when a
card arrives, and will not fire again until that card has actually been taken
away and re-presented.

**A card resting on the reader must not re-trigger.** The reader returns the
same UID on every poll while a card sits there. V1's answer was
`time.sleep(1)` after each match, which is not really an answer — it just
re-fires more slowly. Here the UID is latched until the card is seen to be
gone for several consecutive polls.

**Reader failure must not take the table down** (5.2). The loop runs on its
own thread, catches its own errors, and reports health rather than raising
into the controller.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from ..config import format_uid


class NFCReader:
    # How many consecutive empty polls before we accept the card is gone.
    # 1 would be too twitchy: a card lying still occasionally fails a read,
    # and treating that as removal would let it re-fire without being moved.
    MISSES_BEFORE_CLEARED = 3

    # Backoff between attempts to bring a broken reader back.
    RECONNECT_INTERVAL_S = 15.0

    def __init__(self, log, on_card: Callable[[str], None],
                 cs: int = 4, reset: int = 20, poll_timeout: float = 0.25):
        self.log = log
        self.on_card = on_card
        self.cs = cs
        self.reset = reset
        # 0.25s, halved from 0.5 on 2026-08-22. This sits UPSTREAM of
        # everything -- nothing happens until the card is recognised, so
        # whatever the rest of the chain costs, this is added to all of it
        # (plan doc 5.7). The cost is more SPI traffic; trivially reverted
        # if the reader starts misbehaving.
        self.poll_timeout = poll_timeout

        self._pn532 = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        # Set once the thread has finished its first connect attempt, so
        # start() can report honestly without blocking on hardware.
        self._first_attempt = threading.Event()
        self._last_attempt = 0.0

        self.healthy = False
        self.firmware: Optional[str] = None
        self.last_error: Optional[str] = None
        self.last_uid: Optional[str] = None
        self.taps = 0

    # ------------------------------------------------------------- lifecycle

    # Long enough to cover the vendored driver's own ~3s of reset/wakeup
    # sleeps, so the common case reports honestly; short enough that a dead
    # reader doesn't noticeably delay a usable prompt. Measured: a healthy
    # PN532 connects in a little over 3s.
    START_WAIT_S = 4.5

    def start(self, wait_s: Optional[float] = None) -> bool:
        """Begin polling. Never raises, and never blocks startup on hardware.

        Connection happens on the polling thread; start() then waits up to
        wait_s for that first attempt to finish, purely so status() can be
        honest when the reader is present and quick.

        This is deliberately NOT a synchronous connect. An earlier version
        called _connect() inline to get an honest status line, and that froze
        startup: the vendored driver sleeps ~3s during reset/wakeup before it
        even talks to the chip, and _wait_ready retries on top. The program
        never reached its input prompt, which looks exactly like a crashed
        terminal. Hardware must never be on the critical path to a usable
        program (plan doc 5.2).

        Returns True if the reader came up within wait_s; False means "not
        yet" — which may still become True shortly, so callers should say
        "connecting" rather than "failed".
        """
        if self._thread is not None:
            return self.healthy
        self._first_attempt.clear()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="nfc-reader",
                                        daemon=True)
        self._thread.start()
        self._first_attempt.wait(self.START_WAIT_S if wait_s is None else wait_s)
        return self.healthy

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        self._cleanup_gpio()

    def status(self) -> dict:
        return {
            "healthy": self.healthy,
            "firmware": self.firmware,
            "last_uid": self.last_uid,
            "taps": self.taps,
            "error": self.last_error,
        }

    # ------------------------------------------------------------- internals

    def _connect(self) -> bool:
        """Open the reader. Returns True on success; never raises."""
        try:
            # Imported lazily: these only exist on the Pi (RPi.GPIO, spidev),
            # so importing at module scope would break the laptop's fake mode.
            from ..vendor.pn532 import PN532_SPI

            # The library calls GPIO.setup() on pins that may still be
            # configured from a previous run, which emits "channel is already
            # in use" warnings. We manage cleanup ourselves in stop(), and the
            # re-setup is harmless, so silence the noise rather than let it
            # look like a fault.
            try:
                import RPi.GPIO as GPIO
                GPIO.setwarnings(False)
            except Exception:
                pass

            pn = PN532_SPI(cs=self.cs, reset=self.reset, debug=False)
            _ic, ver, rev, _support = pn.get_firmware_version()
            pn.SAM_configuration()

            self._pn532 = pn
            self.firmware = "%s.%s" % (ver, rev)
            self.healthy = True
            self.last_error = None
            self.log.record("nfc.connected", firmware=self.firmware,
                            cs=self.cs, reset=self.reset)
            return True
        except Exception as exc:   # noqa: BLE001 - hardware init fails many ways
            self._pn532 = None
            self.healthy = False
            self.last_error = "%s: %s" % (type(exc).__name__, exc)
            self.log.record("nfc.unavailable", error=self.last_error)
            return False

    def _run(self) -> None:
        misses = 0
        latched: Optional[str] = None

        while not self._stop.is_set():
            if self._pn532 is None:
                now = time.monotonic()
                if now - self._last_attempt < self.RECONNECT_INTERVAL_S:
                    self._stop.wait(1.0)
                    continue
                self._last_attempt = now
                connected = self._connect()
                # Unblock start()'s bounded wait whether or not it worked.
                self._first_attempt.set()
                if not connected:
                    continue

            try:
                raw = self._pn532.read_passive_target(timeout=self.poll_timeout)
            except Exception as exc:  # noqa: BLE001
                # A wedged SPI bus shouldn't kill the thread — drop the handle
                # and let the reconnect path try again.
                self.healthy = False
                self.last_error = "%s: %s" % (type(exc).__name__, exc)
                self.log.record("nfc.read_failed", error=self.last_error)
                self._pn532 = None
                latched, misses = None, 0
                continue

            if raw is None:
                # No card in the field. Only clear the latch after several
                # consecutive misses, so a flaky read on a stationary card
                # isn't mistaken for the card being lifted.
                if latched is not None:
                    misses += 1
                    if misses >= self.MISSES_BEFORE_CLEARED:
                        self.log.record("nfc.card_removed", uid=latched)
                        latched, misses = None, 0
                continue

            misses = 0
            uid = format_uid(raw)
            if uid == latched:
                continue          # still the same card sitting there — ignore

            latched = uid
            self.last_uid = uid
            self.taps += 1
            self.log.record("nfc.tap", uid=uid)

            # The callback runs the whole controller dispatch. If it throws,
            # that must not kill the reader thread — log and keep polling.
            try:
                self.on_card(uid)
            except Exception as exc:   # noqa: BLE001
                self.log.record("nfc.dispatch_failed", uid=uid,
                                error="%s: %s" % (type(exc).__name__, exc))

    def _cleanup_gpio(self) -> None:
        try:
            import RPi.GPIO as GPIO
            GPIO.cleanup()
        except Exception:
            pass
