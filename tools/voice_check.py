#!/usr/bin/env python3
"""Check the Entity voice, on the table, without disturbing it.

    tools/voice_check.py                    # every static check
    tools/voice_check.py --rates            # ...plus a rate simulation
    tools/voice_check.py --play             # ...plus actually speak, out loud
    tools/voice_check.py --play --lines 6   # speak six of them

WHY THIS EXISTS AND WHAT SHAPE IT IS
------------------------------------
Every bug this subsystem has had was a Pi-only bug. The WAVs were valid by
every measure a laptop could apply -- right format, right duration, readable
by Python's `wave` -- and pygame 1.9.6 refused all 91 of them because ffmpeg
had left a JUNK chunk before `fmt `. The laptop could not have found it: the
fake audio device never opens a file.

So this runs where the problem lives, and it checks the things that actually
broke rather than the things that are easy to check.

IT DOES NOT FIGHT THE SERVICE FOR THE AUDIO DEVICE.

  * The load test opens the mixer with SDL's dummy driver, so it parses every
    file through the real pygame without touching the sound card. That is the
    check that would have caught the JUNK chunk, and it is safe to run mid
    session.
  * The audible test does not open the device at all -- it asks the RUNNING
    SERVICE to speak, through /api/voice/say. The service already owns the
    device; competing for it would be the wrong way to test whether it works.

Exit code is 0 if every check passed, 1 otherwise, so it can gate a deploy.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import struct
import sys
import time
import wave

DEFAULT_CONFIG = "/var/lib/warlocktable/config.json"
DEFAULT_PANEL = "http://localhost:8080"

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
_results = []


def check(name, status, detail=""):
    _results.append((name, status, detail))
    mark = {PASS: "  ok  ", WARN: " warn ", FAIL: " FAIL "}[status]
    print("[%s] %-34s %s" % (mark, name, detail))
    return status == PASS


# --- config ----------------------------------------------------------------

def load_settings(path):
    if not os.path.isfile(path):
        check("config file", FAIL, "not found: %s" % path)
        return None
    try:
        raw = json.load(open(path, encoding="utf-8"))
    except ValueError as exc:
        check("config file", FAIL, "not valid JSON: %s" % exc)
        return None

    voice = raw.get("settings", {}).get("entity_voice")
    if voice is None:
        check("entity_voice block", FAIL,
              "missing from settings -- the table will never speak")
        return None

    check("entity_voice block", PASS if voice.get("enabled") else WARN,
          "enabled" if voice.get("enabled") else
          "present but DISABLED (Settings > Let the table speak)")
    return voice


# --- assets ----------------------------------------------------------------

def first_chunk(path):
    with open(path, "rb") as fh:
        head = fh.read(16)
    if len(head) < 16 or head[:4] != b"RIFF":
        return "?"
    return head[12:16].decode("latin-1", "replace")


def check_assets(voice):
    lines_json = voice.get("lines_json") or ""
    audio_dir = voice.get("audio_dir") or ""

    if not os.path.isfile(lines_json):
        check("line database", FAIL, "not found: %s" % lines_json)
        return None, None
    if not os.path.isdir(audio_dir):
        check("audio directory", FAIL, "not found: %s" % audio_dir)
        return None, None

    try:
        entries = json.load(open(lines_json, encoding="utf-8")).get("lines", [])
    except ValueError as exc:
        check("line database", FAIL, "not valid JSON: %s" % exc)
        return None, None
    check("line database", PASS, "%d lines" % len(entries))

    ids = [e["id"] for e in entries if e.get("id")]
    missing = [i for i in ids if not os.path.isfile(os.path.join(audio_dir, "%s.wav" % i))]
    check("audio present", FAIL if missing else PASS,
          ("%d of %d have no wav: %s" % (len(missing), len(ids), missing[:4]))
          if missing else "all %d lines have their wav" % len(ids))

    on_disk = {f[:-4] for f in os.listdir(audio_dir) if f.endswith(".wav")}
    orphans = sorted(on_disk - set(ids))
    check("no orphan audio", PASS if not orphans else WARN,
          "none" if not orphans else "%d wav with no line: %s" % (len(orphans), orphans[:4]))

    # THE ONE THAT ACTUALLY BROKE. A JUNK chunk before `fmt ` is invisible to
    # every other tool and fatal to SDL 1.2.
    bad = []
    for i in ids:
        p = os.path.join(audio_dir, "%s.wav" % i)
        if os.path.isfile(p) and first_chunk(p) != "fmt ":
            bad.append((i, first_chunk(p)))
    check("wav chunk order", FAIL if bad else PASS,
          "canonical (fmt first)" if not bad else
          "%d files start with %r, not 'fmt ' -- run tools/normalise_wavs.py"
          % (len(bad), bad[0][1]))

    durations = []
    for i in ids:
        p = os.path.join(audio_dir, "%s.wav" % i)
        if not os.path.isfile(p):
            continue
        try:
            with wave.open(p) as w:
                durations.append(w.getnframes() / float(w.getframerate()))
        except Exception:      # noqa: BLE001
            durations.append(0.0)
    if durations:
        durations.sort()
        check("durations", PASS, "%.1f - %.1f s, median %.1f"
              % (durations[0], durations[-1], durations[len(durations) // 2]))
    return ids, audio_dir


def check_pygame_loads(ids, audio_dir):
    """Parse every file through the REAL pygame, on the dummy audio driver.

    This is the check that would have caught the JUNK chunk. The dummy driver
    means it never touches the sound card, so it is safe while the table is
    running a session.
    """
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    try:
        import pygame
    except ImportError:
        check("pygame can load them", WARN, "pygame not importable here")
        return
    try:
        pygame.mixer.init()
    except Exception as exc:   # noqa: BLE001
        check("pygame can load them", WARN, "mixer would not start: %s" % exc)
        return

    failed = []
    for i in ids:
        p = os.path.join(audio_dir, "%s.wav" % i)
        if not os.path.isfile(p):
            continue
        try:
            pygame.mixer.Sound(p)
        except Exception as exc:   # noqa: BLE001
            failed.append((i, str(exc)))
    pygame.mixer.quit()

    check("pygame can load them", FAIL if failed else PASS,
          "all %d load (pygame %s)" % (len(ids), pygame.version.ver) if not failed
          else "%d failed, first: %s -- %s" % (len(failed), failed[0][0], failed[0][1]))


# --- the trigger map -------------------------------------------------------

def check_trigger_map(lines_json):
    """Every trigger the controller can emit must reach a line."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        from warlock.entity import triggers as T
        from warlock.entity.lines import LineLibrary
    except Exception as exc:   # noqa: BLE001
        check("trigger map", WARN, "could not import: %s" % exc)
        return

    lib = LineLibrary.load(lines_json, os.path.dirname(lines_json))
    emitted = (
        [T.for_scene(s) for s in ("forest", "plains", "swamp", "island",
                                  "mountain", "idle")] +
        [T.for_interruption(c) for c in sorted(T.PERSON_TRIGGERS)] +
        [T.for_interruption(c) for c in sorted(T.BOONS)] +
        [T.for_interruption(c) for c in sorted(T.AURAS)] +
        [T.for_table(T.WHEEL_TABLE), T.for_expiry()] +
        ["system_startup", "system_shutdown", "system_idle", "dice_roll",
         "panel_map_change", "panel_appletv_handoff",
         "panel_combat_on", "panel_combat_off"]
    )
    empty = sorted({t for t in emitted if not lib.pool_for(t)})
    check("trigger map", FAIL if empty else PASS,
          "all %d triggers reach a line pool" % len(set(emitted)) if not empty
          else "no lines for: %s" % empty)


# --- rates -----------------------------------------------------------------

def simulate(voice, lines_json, gestures=2000):
    """What the CURRENT settings actually produce, before you sit through it.

    A probability and a cooldown in series are hard to reason about -- this
    answers "how often will it speak" by running it rather than by arithmetic.
    """
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if here not in sys.path:
        sys.path.insert(0, here)
    from warlock.config import _load_voice
    from warlock.entity.lines import LineLibrary
    from warlock.entity.picker import Picker

    settings = _load_voice(voice)
    lib = LineLibrary.load(lines_json, voice.get("audio_dir") or "")

    class Clock:
        def __init__(self): self.t = 0.0
        def __call__(self): return self.t

    print()
    print("  With chattiness %.2f and a %.0fs cooldown, over %d card taps"
          % (settings.chattiness, settings.global_cooldown_s, gestures))
    print("  spaced 45s apart (a brisk session):")
    print()
    print("    %-26s %8s  %s" % ("trigger", "spoke", "roughly"))
    for trig in ("tarot_boon_any", "mana_black", "tarot_wheel_of_fortune",
                 "panel_combat_on", "dice_roll", "system_idle"):
        clock = Clock()
        p = Picker(lib, settings, clock=clock, rng=random.Random(4))
        spoke = 0
        for _ in range(gestures):
            clock.t += 45.0
            p.begin_gesture()
            d = p.consider(trig, speaking=False)
            if d.spoke:
                spoke += 1
                clock.t += 4.0          # the line plays
                p.note_finished()
        pct = 100.0 * spoke / gestures
        every = ("about 1 in %d" % round(1 / (pct / 100)) if pct else "never")
        print("    %-26s %7.1f%%  %s" % (trig, pct, every))


# --- speaking --------------------------------------------------------------

def speak(panel, count):
    """Ask the RUNNING SERVICE to say some lines. Does not open the device."""
    try:
        import urllib.request as u
    except ImportError:
        check("panel reachable", FAIL, "no urllib")
        return

    def get(path):
        with u.urlopen(panel + path, timeout=10) as r:
            return json.loads(r.read())

    def post(path, body):
        req = u.Request(panel + path, data=json.dumps(body).encode(),
                        method="POST")
        req.add_header("Content-Type", "application/json")
        with u.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    try:
        status = get("/api/voice")
    except Exception as exc:   # noqa: BLE001
        check("panel reachable", FAIL,
              "%s -- is the service running? (%s)" % (exc, panel))
        return

    check("panel reachable", PASS if status.get("healthy") else FAIL,
          "voice %s, %s lines, %spreloaded"
          % ("healthy" if status.get("healthy") else "NOT healthy",
             status.get("lines"), "" if status.get("healthy") else "not "))

    lines = get("/api/voice/lines")["lines"]
    playable = [l for l in lines if l.get("present")]
    if not playable:
        check("spoke aloud", FAIL, "no playable lines")
        return

    picked = random.sample(playable, min(count, len(playable)))
    print()
    print("  Speaking %d lines through the running service. LISTEN:" % len(picked))
    print()
    ok = 0
    for line in picked:
        try:
            r = post("/api/voice/say", {"line": line["id"]})
            good = bool(r.get("ok"))
        except Exception as exc:   # noqa: BLE001
            good = False
            r = {"error": str(exc)}
        ok += good
        print("    %-28s %-13s %s"
              % (line["id"], "(%s)" % line["mood"],
                 '"%s"' % line["text"][:44] if good else "FAILED: %s" % r.get("error")))
        # Long enough for the line and its reverb tail to finish, so they do
        # not tread on each other -- the service drops a trigger that arrives
        # while it is already speaking, and that would look like a failure.
        time.sleep(6.5)

    check("spoke aloud", PASS if ok == len(picked) else FAIL,
          "%d of %d accepted -- did you HEAR them?" % (ok, len(picked)))


# --- main ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--panel", default=DEFAULT_PANEL)
    ap.add_argument("--rates", action="store_true",
                    help="simulate how often it will speak at the current settings")
    ap.add_argument("--play", action="store_true",
                    help="actually speak, through the running service")
    ap.add_argument("--lines", type=int, default=3,
                    help="how many lines to speak with --play (default 3)")
    args = ap.parse_args()

    print("Entity voice check")
    print("  config: %s" % args.config)
    print()

    voice = load_settings(args.config)
    if voice:
        ids, audio_dir = check_assets(voice)
        if ids:
            check_pygame_loads(ids, audio_dir)
            check_trigger_map(voice.get("lines_json"))
            if args.rates:
                simulate(voice, voice.get("lines_json"))
    if args.play:
        print()
        speak(args.panel, args.lines)

    print()
    failed = [r for r in _results if r[1] == FAIL]
    warned = [r for r in _results if r[1] == WARN]
    print("%d checks: %d passed, %d warnings, %d FAILED"
          % (len(_results), len(_results) - len(failed) - len(warned),
             len(warned), len(failed)))
    for name, _, detail in failed:
        print("  FAILED  %s -- %s" % (name, detail))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
