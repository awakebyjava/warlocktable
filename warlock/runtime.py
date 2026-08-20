"""Shared startup: build the devices and controller once, use from both
the interactive CLI and the headless service.

Also implements the "never refuse to start" rule from plan doc 5.2. A
service that exits because someone typo'd a config file is worse than
useless — it fails at exactly the moment you cannot debug it, and it fails
silently because there is no console to print to.
"""

from __future__ import annotations

import argparse
import os
import shutil
from typing import Optional, Tuple

from .config import Config, ConfigError, load_config
from .controller import Controller
from .devices.fake import FakeAudioDevice, FakeDisplayDevice, FakeLightDevice
from .eventlog import EventLog

LAST_GOOD_SUFFIX = ".last-good"


def resolve_logfile(args) -> Optional[str]:
    """Where the event log goes.

    Defaults to sitting beside the config rather than to a fixed path in the
    source tree. Under the installed layout the code lives in /opt (replaced
    on every deploy) and the data in /var/lib — writing logs into /opt would
    both fail and be wrong, since they are data, not code.

    Explicit '' disables the file log entirely.
    """
    if args.logfile is not None:
        return args.logfile or None
    return os.path.join(os.path.dirname(os.path.abspath(args.config)), "events.log")


def service_is_running() -> bool:
    """True if the systemd service appears to be up.

    Used to warn before the interactive CLI fights the service for hardware:
    both cannot own the PN532's SPI bus and GPIO reset pin at once, and the
    loser reports 'Failed to detect the PN532' — which looks like broken
    hardware rather than a second copy of the program.
    """
    try:
        import subprocess
        out = subprocess.run(["systemctl", "is-active", "warlocktable"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() == "active"
    except Exception:
        return False


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Arguments shared by the interactive CLI and the service."""
    here = os.path.dirname(__file__)
    parser.add_argument(
        "--config",
        default=os.path.join(here, "..", "data", "config.example.json"),
        help="path to a config JSON file",
    )
    parser.add_argument(
        "--logfile",
        default=None,
        help="where to append the event log (JSON Lines). Defaults to "
             "events.log beside the config file. Pass '' to disable.",
    )
    parser.add_argument(
        "--real-lights", action="store_true",
        help="drive the actual Pixelblaze instead of the fake light device",
    )
    parser.add_argument(
        "--pixelblaze-ip", default=None,
        help="address hint for the Pixelblaze; discovery is used if omitted",
    )
    parser.add_argument(
        "--nfc", action="store_true",
        help="read real cards from the PN532 (Pi only — needs SPI and RPi.GPIO)",
    )
    parser.add_argument(
        "--real-audio", action="store_true",
        help="play actual sound instead of logging what would play",
    )
    parser.add_argument(
        "--web", action="store_true",
        help="serve the operator panel (iPad PWA) on the LAN",
    )
    parser.add_argument(
        "--web-port", type=int, default=8080,
        help="port for the operator panel (default 8080)",
    )


# ---------------------------------------------------------------- config

def _minimal_config() -> Config:
    """A config that lets the table boot with nothing usable on disk.

    Deliberately not empty: it has an idle scene, so the lights still come
    up. Per 5.1 a breathing table IS the signal that the controller booted,
    and that signal matters most when the config is broken.
    """
    from .config import Scene, Transition
    idle = Scene(name="idle", lights="breathing", soundscape=None,
                 transition=Transition())
    return Config(scenes={"idle": idle}, interruptions={}, random_tables={},
                  cards={}, zones=[], players=[])


def load_config_resilient(path: str, log: EventLog) -> Tuple[Config, str]:
    """Load config, falling back rather than refusing to start (5.2).

    Order: the requested file, then the last copy known to have loaded, then
    a minimal built-in. Returns (config, source) where source describes which
    was used, so the caller can surface it.

    On a successful load of the real file, a .last-good copy is written. That
    copy is what makes the fallback meaningful — without it, a bad edit has
    nothing to fall back TO.
    """
    last_good = path + LAST_GOOD_SUFFIX

    try:
        config = load_config(path)
    except (ConfigError, FileNotFoundError, KeyError, ValueError) as exc:
        log.record("config.load_failed", path=path, error=str(exc))

        if os.path.exists(last_good):
            try:
                config = load_config(last_good)
                log.record("config.using_last_good", path=last_good)
                return config, "last-known-good (%s failed to load)" % os.path.basename(path)
            except Exception as exc2:   # noqa: BLE001
                log.record("config.last_good_failed", error=str(exc2))

        log.record("config.using_minimal")
        return _minimal_config(), "built-in minimal (no usable config on disk)"

    # Loaded cleanly — remember it so a later bad edit has somewhere to land.
    try:
        shutil.copy2(path, last_good)
    except OSError as exc:
        log.record("config.last_good_save_failed", error=str(exc))

    return config, path


# ---------------------------------------------------------------- devices

class Runtime:
    """Everything built and running, with one place to shut it all down."""

    def __init__(self, controller: Controller, log: EventLog,
                 audio, lights, reader=None, config_source: str = "",
                 web=None):
        self.controller = controller
        self.log = log
        self.audio = audio
        self.lights = lights
        self.reader = reader
        self.config_source = config_source
        self.web = web

    def shutdown(self) -> None:
        """Release hardware. Safe to call more than once.

        Each step is timed and reported, so when shutdown is slow the journal
        names the culprit instead of leaving it a guess. This was added after
        shutdown hung past systemd's stop timeout with real devices attached
        and the process had to be SIGKILLed.
        """
        import time as _time

        def _timed(label, fn):
            t0 = _time.monotonic()
            try:
                fn()
                took = _time.monotonic() - t0
                # Only mention the quick ones in passing; flag slow ones.
                if took > 1.0:
                    print("  shutdown: %s took %.1fs" % (label, took), flush=True)
            except Exception as exc:   # noqa: BLE001
                print("  shutdown: %s failed: %s: %s"
                      % (label, type(exc).__name__, exc), flush=True)

        if self.web is not None:
            web = self.web
            self.web = None
            _timed("web panel", web.stop)

        if self.reader is not None:
            reader = self.reader
            self.reader = None
            _timed("nfc reader", reader.stop)

        closer = getattr(self.audio, "close", None)
        if callable(closer):
            _timed("audio", closer)

        closer = getattr(self.lights, "close", None)
        if callable(closer):
            _timed("lights", closer)


def build(args, log: EventLog, on_card=None) -> Runtime:
    """Construct devices and the controller from parsed arguments.

    Never raises for missing hardware — a device that cannot start makes its
    subsystem unhealthy, not the program dead (5.2).
    """
    config, source = load_config_resilient(args.config, log)

    if getattr(args, "real_lights", False):
        from .devices.pixelblaze_lights import PixelblazeLights
        lights = PixelblazeLights(
            log,
            address_hint=getattr(args, "pixelblaze_ip", None),
            state_path=os.path.join(os.path.dirname(args.config), "device-state.json"),
        )
        lights.try_connect()
    else:
        lights = FakeLightDevice(log)

    if getattr(args, "real_audio", False):
        from .devices.pygame_audio import PygameAudio
        audio = PygameAudio(log, search_paths=config.audio_paths,
                            device=config.audio_device,
                            duck_level=config.duck_level,
                            duck_ramp_s=config.duck_ramp_s)
        audio.start()
    else:
        audio = FakeAudioDevice(log)

    display = FakeDisplayDevice(log)
    controller = Controller(config, lights, audio, display, log)

    reader = None
    if getattr(args, "nfc", False):
        from .inputs.nfc import NFCReader

        def _default_on_card(uid: str) -> None:
            if not controller.handle_card(uid):
                log.record("card.unregistered", scanned=uid)

        reader = NFCReader(log, on_card or _default_on_card)
        reader.start()
        controller._nfc_status = reader.status

    rt = Runtime(controller, log, audio, lights, reader, source)

    if getattr(args, "web", False):
        from .web.server import WebPanel
        panel = WebPanel(controller, rt, log, port=getattr(args, "web_port", 8080))
        # A panel that fails to bind must not stop the table responding to
        # cards (5.2) - start() reports rather than raising.
        if panel.start():
            rt.web = panel

    return rt
