"""The fake-hardware CLI — plan doc section 4.2, step 2-3.

This is the milestone described in the plan doc: type a card name, watch
what the table *would* do, with zero hardware attached. Everything printed
here is exactly what a real Pixelblaze/audio/display driver would be told
to do — the fakes just print instead of calling a websocket.

Run it with:  python run_table.py
"""

from __future__ import annotations

import argparse
import os
import sys

# Windows consoles default to a legacy codepage (cp1252/cp437) that can't
# represent characters like the "·" this CLI prints, or names such as
# "Outré" in the audio library — they come out as "�" instead. Forcing
# UTF-8 here fixes it regardless of what codepage the terminal started in.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

from .config import ConfigError, load_config
from .controller import Controller
from .devices.fake import FakeAudioDevice, FakeDisplayDevice, FakeLightDevice
from .eventlog import EventLog
from .registry import describe_actions

# Power-budget ceiling, deliberately chosen — see the power budget section
# of warlock-table-led-reference.md. 764 SK6812 RGBW pixels draw ~46-61A at
# full white; the supply is 40A (200W) at 5V. A 50% ceiling lands at ~23-31A,
# inside the 80% continuous-load derating rule. Raising this above 50 on the
# current supply requires redoing that arithmetic first.
POWER_SAFE_LIMIT_PCT = 50

BANNER_FAKE = """\
Warlock Table v2 — fake-hardware controller
No Pi, no Pixelblaze, no NFC reader. Everything below is what the real
devices would be told to do.  Type 'help' for commands, 'quit' to exit.
"""

BANNER_REAL = """\
Warlock Table v2 — LIGHTS ARE REAL
Lights drive the actual Pixelblaze; audio and display are still fakes.
Card taps below will change the physical table. 'help' for commands.
"""

HELP = """\
  card <uid-or-label>   simulate an NFC tap (try: thedevil, forest, wheel)
  cards                 list every registered card
  scenes                list scenes
  interruptions         list interruptions
  tables                list random tables
  scene <name>          apply a scene directly (panel-style)
  interrupt <name>      play an interruption directly
  roll <table>          roll a random table directly
  idle                  go to idle
  seat <name> <colour>  claim a seat (e.g.  seat Dave red)
  actions               show the self-describing action registry
  status                subsystem health + real brightness (start here if
                        the table looks like it is doing nothing)
  bright <0.0-1.0>      set the runtime brightness slider
  log [n]               show the last n events (default 20)
  sleep <seconds>       wait — useful for watching a timed revert fire
  help                  this message
  quit                  exit
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Warlock Table fake controller")
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(__file__), "..", "data", "config.example.json"),
        help="path to a config JSON file (default: data/config.example.json)",
    )
    parser.add_argument(
        "--logfile",
        default=os.path.join(os.path.dirname(__file__), "..", "data", "events.log"),
        help="where to append the event log (JSON Lines). Pass '' to disable.",
    )
    parser.add_argument(
        "--real-lights",
        action="store_true",
        help="drive the actual Pixelblaze instead of the fake light device. "
             "Requires pixelblaze-client (pip install pixelblaze-client).",
    )
    parser.add_argument(
        "--pixelblaze-ip",
        default=None,
        help="address hint for the Pixelblaze. Optional — if it is wrong or "
             "omitted, the device is found by UDP discovery instead.",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except (ConfigError, FileNotFoundError, KeyError) as exc:
        # Section 5.2 says the controller must never refuse to start over a
        # bad config in production — it should fall back to last-known-good.
        # This CLI is a dev tool, not the production controller, so for now
        # it just reports the problem clearly and exits.
        print("Could not load config %r:\n  %s" % (args.config, exc), file=sys.stderr)
        sys.exit(1)

    log = EventLog(path=args.logfile or None, echo=True)

    if args.real_lights:
        # Note this is constructed exactly like the fake and handed to the
        # same Controller. That is the layering paying off (plan doc 4.1):
        # swapping real hardware in touches this line and nothing else.
        from .devices.pixelblaze_lights import PixelblazeLights
        lights = PixelblazeLights(
            log,
            address_hint=args.pixelblaze_ip,
            state_path=os.path.join(os.path.dirname(__file__), "..", "data", "device-state.json"),
        )
    else:
        lights = FakeLightDevice(log)

    audio = FakeAudioDevice(log)
    display = FakeDisplayDevice(log)
    controller = Controller(config, lights, audio, display, log)

    print(BANNER_REAL if args.real_lights else BANNER_FAKE)
    if args.real_lights:
        # Deliberately does not abort if the Pixelblaze is missing — section
        # 5.2: the controller must start with zero hardware present.
        lights.try_connect()
        status = lights.status()
        if status["healthy"]:
            print("REAL LIGHTS: connected to %s" % status["address"])
        else:
            print("REAL LIGHTS: not connected yet (%s)" % (status["error"] or "will retry"))
            print("             the table will keep running; lights retry in background.")

    controller.go_idle()

    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        parts = line.split(None, 1)
        cmd = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        try:
            _dispatch_command(cmd, rest, controller, config)
        except KeyError as exc:
            print("  No such name: %s" % exc)
        except Exception as exc:  # noqa: BLE001 — CLI-level catch-all is fine here
            print("  Error: %s" % exc)

        if cmd in ("quit", "exit"):
            break


def _dispatch_command(cmd: str, rest: str, controller: Controller, config) -> None:
    if cmd in ("quit", "exit"):
        return

    if cmd == "help":
        print(HELP)

    elif cmd == "card":
        if not controller.handle_card(rest):
            print("  '%s' is not a registered card. (In the real panel, this "
                  "would appear as 'unassigned — tap to name it'.)" % rest)

    elif cmd == "cards":
        for card in config.cards.values():
            print("  %-22s %-20s -> %s:%s" % (card.uid, card.label,
                                                card.target.kind, card.target.name))

    elif cmd == "scenes":
        for name in config.scenes:
            print("  " + name)

    elif cmd == "interruptions":
        for name in config.interruptions:
            print("  " + name)

    elif cmd == "tables":
        for name, t in config.random_tables.items():
            entries = ", ".join("%s:%s" % (e.kind, e.name) for e in t.entries)
            print("  %s -> [%s]" % (name, entries))

    elif cmd == "scene":
        controller.apply_scene(rest)

    elif cmd == "interrupt":
        controller.play_interruption(rest)

    elif cmd == "roll":
        controller.roll_table(rest)

    elif cmd == "idle":
        controller.go_idle()

    elif cmd == "seat":
        try:
            name, colour = rest.split()
        except ValueError:
            print("  usage: seat <name> <colour>")
            return
        ok = controller.claim_seat(name, colour)
        if not ok:
            print("  could not claim that seat (bad colour, or already taken "
                  "by someone else — see the log line above)")

    elif cmd == "actions":
        for spec in describe_actions(controller):
            print("  %s(%s)" % (
                spec["name"],
                ", ".join(p["name"] for p in spec["params"]),
            ))
            for p in spec["params"]:
                if p["choices"] is not None:
                    print("      %s: %s" % (p["name"], ", ".join(p["choices"])))

    elif cmd == "sleep":
        import time
        time.sleep(float(rest or 1))

    elif cmd == "log":
        n = int(rest) if rest.strip().isdigit() else 20
        for event in controller.log.recent(n):
            print("  " + EventLog._humanize(event))

    elif cmd == "status":
        st = controller.status()
        print("  scene:", st["scene"])
        for subsystem, ok in st["subsystems"].items():
            print("  %-9s %s" % (subsystem + ":", "ok" if ok else "UNHEALTHY"))
        device_status = getattr(controller.lights, "status", None)
        if callable(device_status):
            info = device_status()
            print("  lights device:")
            for key in ("address", "pattern", "brightness_slider",
                         "brightness_limit_pct", "effective_pct", "error"):
                if key in info and info[key] is not None:
                    print("     %-20s %s" % (key, info[key]))
            limit = info.get("brightness_limit_pct")
            if limit is not None and limit > POWER_SAFE_LIMIT_PCT:
                # Power-budget check. 40A supply; see the reference doc.
                print("     *** BRIGHTNESS LIMIT %s%% IS ABOVE THE AGREED %s%% CEILING ***"
                      % (limit, POWER_SAFE_LIMIT_PCT))
                print("         764 SK6812 RGBW draw ~46-61A at full white against")
                print("         a 40A supply. Re-check the power budget before")
                print("         leaving it here.")
            eff = info.get("effective_pct")
            if eff is not None and eff < 10:
                print("     note: effective brightness is only ~%s%%." % eff)
                print("           Ceiling is %s%%; raise the slider with"
                      % (limit if limit is not None else "?"))
                print("           'bright 1.0' to use the full budget.")

    elif cmd == "bright":
        try:
            controller.set_brightness(float(rest))
        except ValueError:
            print("  usage: bright <0.0-1.0>")

    else:
        print("  unknown command %r — try 'help'" % cmd)


if __name__ == "__main__":
    main()
