"""Headless mode — the table running as a service, with no console.

This is what systemd starts (plan doc 5.5). It differs from the interactive
CLI in ways that matter:

* **Nothing reads stdin.** The CLI blocks on input(); under systemd there is
  no terminal, so that would either fail immediately or block forever.
* **Signals shut it down cleanly.** systemd stops a service with SIGTERM.
  Without handling it, Python dies wherever it stands and the PN532's GPIO
  pins stay claimed, so the next start hits "channel already in use".
* **Nothing is fatal.** Missing hardware, a broken config, an unreachable
  Pixelblaze — all degrade a subsystem and leave the table running (5.2).
  A service that exits is a table that is simply dead until someone SSHes in,
  which is the exact failure this whole design is trying to avoid.

Output goes to stdout, which systemd captures into the journal:
    journalctl -u warlocktable -f
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time

from . import runtime
from .eventlog import EventLog

# Windows consoles and some journald setups default to a legacy codepage
# that mangles the event log's bullet character and names like "Outré".
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


_shutdown = threading.Event()


def _handle_signal(signum, _frame):
    # Only set the flag here. Doing real work in a signal handler is how you
    # get deadlocks — the main loop does the actual shutdown.
    name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
    print("service: received %s, shutting down" % name, flush=True)
    _shutdown.set()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Warlock Table controller (headless service mode)")
    runtime.add_common_arguments(parser)
    parser.add_argument(
        "--status-interval", type=float, default=0.0,
        help="seconds between periodic status lines in the journal "
             "(0 = only log when something happens)",
    )
    args = parser.parse_args(argv)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    log = EventLog(path=runtime.resolve_logfile(args), echo=True)
    print("Warlock Table service starting", flush=True)

    try:
        rt = runtime.build(args, log)
    except Exception as exc:   # noqa: BLE001
        # Building the runtime should not be able to fail — every device path
        # is already guarded. If it somehow does, say so loudly and exit
        # non-zero so systemd's Restart=always retries rather than silently
        # leaving a dead table.
        print("service: FAILED to build runtime: %s: %s"
              % (type(exc).__name__, exc), file=sys.stderr, flush=True)
        return 1

    print("service: config source: %s" % rt.config_source, flush=True)
    _report_status(rt)

    # Bring the table up to its resting state. Per 5.1 the lights coming up
    # on their own are the visible signal that the controller booted.
    rt.controller.go_idle()
    print("service: ready", flush=True)

    try:
        last_report = time.monotonic()
        while not _shutdown.is_set():
            # Wake up regularly rather than blocking forever, so periodic
            # status has a chance to run and shutdown is responsive.
            _shutdown.wait(1.0)
            if args.status_interval > 0:
                now = time.monotonic()
                if now - last_report >= args.status_interval:
                    last_report = now
                    _report_status(rt)
    finally:
        _shutdown_with_deadline(rt, deadline_s=8.0)

    return 0


def _shutdown_with_deadline(rt: runtime.Runtime, deadline_s: float) -> None:
    """Release hardware, but never let shutdown outlast systemd's patience.

    Learned the hard way: with real devices attached this hung past
    TimeoutStopSec and systemd SIGKILLed the process — which is precisely
    what clean shutdown exists to avoid, since a hard kill leaves the
    PN532's GPIO pins claimed for the next start.

    Third-party teardown can block for reasons we do not control
    (pygame.mixer.quit() with a stuck SDL audio thread, a wedged SPI bus
    mid-transfer). So: attempt it on a thread, give it a bounded window,
    then exit anyway. We are terminating regardless — a mostly-clean exit
    now beats a SIGKILL later.
    """
    print("service: stopping", flush=True)
    started = time.monotonic()
    done = threading.Event()

    def _run_shutdown():
        try:
            rt.shutdown()
        except Exception as exc:   # noqa: BLE001
            print("service: shutdown error (continuing): %s: %s"
                  % (type(exc).__name__, exc), flush=True)
        finally:
            done.set()

    t = threading.Thread(target=_run_shutdown, name="shutdown", daemon=True)
    t.start()

    if done.wait(deadline_s):
        print("service: stopped cleanly in %.1fs" % (time.monotonic() - started),
              flush=True)
    else:
        print("service: shutdown exceeded %.0fs — forcing exit "
              "(a device driver is not releasing)" % deadline_s, flush=True)

    sys.stdout.flush()
    sys.stderr.flush()
    # os._exit skips interpreter cleanup, which is the point: whatever is
    # stuck would block a normal exit too.
    os._exit(0)


def _report_status(rt: runtime.Runtime) -> None:
    """One-line-per-subsystem health, for the journal."""
    st = rt.controller.status()
    parts = ["%s=%s" % (k, "ok" if v else "UNHEALTHY")
             for k, v in st["subsystems"].items()]

    nfc = getattr(rt.controller, "_nfc_status", None)
    if callable(nfc):
        info = nfc()
        parts.append("nfc=%s" % ("ok" if info.get("healthy") else "down"))
        parts.append("taps=%s" % info.get("taps", 0))

    lights_status = getattr(rt.lights, "status", None)
    if callable(lights_status):
        info = lights_status()
        if info.get("effective_pct") is not None:
            parts.append("brightness=%s%%" % info["effective_pct"])

    print("service: status %s scene=%s" % (" ".join(parts), st["scene"]),
          flush=True)


if __name__ == "__main__":
    sys.exit(main())
