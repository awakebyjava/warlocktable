"""Table Check — the pre-session self-test (plan doc 5.4).

Run this ten minutes before people arrive, not at game time.

WHAT IT IS FOR

The status strip answers "is each device alive?". That is necessary and not
sufficient: every device can be perfectly healthy while the table is still
broken, because config points at things that do not exist.

That is not hypothetical. When the Pixelblaze patterns were renamed from
GreenCard/RedCard to Forest/Mountain, every device stayed green and every
mana card silently stopped working. Nothing noticed until a card was tapped.

So the centrepiece here is a **cross-device referential integrity check**:
walk everything config references — every light pattern, every audio track,
every background — and confirm the actual device actually has it. Nothing
else in the system does this.

PHYSICAL vs AUTOMATED

Some things cannot be verified in software. Whether light actually comes out
of the LEDs, or sound actually reaches the speakers, needs a human. The
`physical` mode briefly flashes a pattern and plays a sound so the operator
can confirm with their own eyes and ears — then restores whatever was
showing, so running the check never leaves the table somewhere unexpected.
"""

from __future__ import annotations

import os
import shutil
import time
from typing import Any, Dict, List

PASS, WARN, FAIL = "pass", "warn", "fail"


def _r(name: str, status: str, detail: str = "") -> Dict[str, Any]:
    return {"name": name, "status": status, "detail": detail}


def run_check(rt, physical: bool = False) -> Dict[str, Any]:
    """Run every check. Never raises — a broken check must still report."""
    started = time.monotonic()
    results: List[Dict[str, Any]] = []
    controller = rt.controller
    config = controller.config

    # ---------------------------------------------------------- build

    version = "unknown"
    try:
        with open("/opt/warlocktable/VERSION", "r", encoding="utf-8") as fh:
            version = fh.readline().strip()
    except OSError:
        version = "not an installed build (running from a checkout)"
    results.append(_r("Build", PASS, version))

    # ---------------------------------------------------------- config

    try:
        n = (len(config.scenes), len(config.interruptions),
             len(config.random_tables), len(config.cards))
        results.append(_r("Config", PASS,
                          "%d scenes, %d interruptions, %d tables, %d cards" % n))
    except Exception as exc:   # noqa: BLE001
        results.append(_r("Config", FAIL, str(exc)))
        return _finish(results, started, physical)

    if not config.cards:
        results.append(_r("Cards registered", WARN,
                          "no cards registered — nothing will respond to a tap"))

    # -------------------------------------- THE IMPORTANT ONE: assets

    results.extend(_check_light_patterns(rt, config))
    results.extend(_check_audio_tracks(rt, config))
    results.extend(_check_backgrounds(rt, config))
    results.extend(_check_zones(rt, config))

    # ---------------------------------------------------------- devices

    results.append(_check_lights_device(rt))
    results.append(_check_audio_device(rt))
    results.append(_check_nfc(rt))
    results.append(_check_display(rt))
    results.append(_check_video_output(rt))
    results.append(_check_disk())

    # ---------------------------------------------------------- physical

    if physical:
        results.extend(_physical(rt))

    return _finish(results, started, physical)


def _finish(results, started, physical):
    counts = {PASS: 0, WARN: 0, FAIL: 0}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    overall = FAIL if counts[FAIL] else (WARN if counts[WARN] else PASS)
    return {
        "overall": overall,
        "counts": counts,
        "physical": physical,
        "duration_s": round(time.monotonic() - started, 1),
        "results": results,
    }


# ------------------------------------------------------------ asset checks

def _check_light_patterns(rt, config) -> List[Dict[str, Any]]:
    wanted = set()
    for s in config.scenes.values():
        if s.lights:
            wanted.add(s.lights)
    for i in config.interruptions.values():
        if i.lights:
            wanted.add(i.lights)
    if not wanted:
        return [_r("Light patterns", WARN, "no scenes reference a pattern")]

    try:
        have = set(rt.lights.available_patterns())
    except Exception as exc:   # noqa: BLE001
        return [_r("Light patterns", FAIL,
                   "could not read the pattern list: %s" % exc)]

    missing = sorted(w for w in wanted if w not in have)
    if missing:
        return [_r("Light patterns", FAIL,
                   "%d of %d referenced patterns are NOT on the Pixelblaze: %s"
                   % (len(missing), len(wanted), ", ".join(missing)))]
    return [_r("Light patterns", PASS,
               "all %d referenced patterns exist on the device" % len(wanted))]


def _check_zones(rt, config) -> List[Dict[str, Any]]:
    """Seat zones: the maths, and whether the device can actually draw them.

    The first half is pure arithmetic and needs no hardware. It exists
    because the zone division is implemented TWICE — in warlock/zones.py
    and again inside patterns/zones.js, which derives the map on-device
    from three numbers instead of being sent all 764. That is the right
    trade for a value that changes every turn, but it means the two can
    drift, and the symptom would be a seat boundary in the wrong place,
    noticed by a confused player mid-session. Cheaper to catch here.
    """
    from . import zones as zonemap

    out: List[Dict[str, Any]] = []

    problems = zonemap.verify()
    if problems:
        out.append(_r("Zone model", FAIL, "; ".join(problems)))
    else:
        out.append(_r("Zone model", PASS,
                      "1-%d players divide cleanly, and %s agrees"
                      % (zonemap.MAX_PLAYERS, zonemap.PATTERN_PATH)))

    count = config.player_count
    if not 1 <= count <= zonemap.MAX_PLAYERS:
        out.append(_r("Seats", FAIL,
                      "player_count is %r, outside 1-%d"
                      % (count, zonemap.MAX_PLAYERS)))
        return out

    seats = [row for row in zonemap.layout(count) if row["zone"]]
    out.append(_r("Seats", PASS,
                  "%d players + GM; each seat %d-%d LEDs (%.0f in)"
                  % (count,
                     min(int(r["leds"]) for r in seats),
                     max(int(r["leds"]) for r in seats),
                     seats[0]["inches"])))

    # Anyone claiming a seat that no longer exists gets whispers sent to a
    # zone the table is not lighting.
    stranded = sorted(p.name for p in config.players
                      if p.zone_id is not None and p.zone_id > count)
    if stranded:
        out.append(_r("Seat claims", FAIL,
                      "%s claimed seats above the current count of %d"
                      % (", ".join(stranded), count)))

    # Whether per-zone lighting will do anything is a real question, not a
    # fault: the pattern has to be uploaded to the Pixelblaze by hand.
    try:
        supported = rt.lights.supports_zones()
    except Exception as exc:   # noqa: BLE001
        out.append(_r("Zone lighting", FAIL, "could not ask the device: %s" % exc))
        return out

    if supported:
        out.append(_r("Zone lighting", PASS, "the zones pattern is on the device"))
    else:
        out.append(_r("Zone lighting", WARN,
                      "no 'zones' pattern on the Pixelblaze — seat colours "
                      "will do nothing until patterns/zones.js is uploaded"))
    return out


def _check_audio_tracks(rt, config) -> List[Dict[str, Any]]:
    wanted = set()
    for s in config.scenes.values():
        if s.soundscape:
            wanted.add(s.soundscape)
    for i in config.interruptions.values():
        if i.audio:
            wanted.add(i.audio)
    if not wanted:
        return [_r("Audio tracks", WARN, "no scenes reference a track")]

    try:
        have = set(rt.controller.audio.available_tracks())
    except Exception as exc:   # noqa: BLE001
        return [_r("Audio tracks", FAIL, "could not read the library: %s" % exc)]

    missing = sorted(w for w in wanted if w not in have)
    if missing:
        return [_r("Audio tracks", FAIL,
                   "%d of %d referenced tracks are MISSING: %s"
                   % (len(missing), len(wanted), ", ".join(missing)))]
    return [_r("Audio tracks", PASS,
               "all %d referenced tracks found in the library" % len(wanted))]


def _check_backgrounds(rt, config) -> List[Dict[str, Any]]:
    wanted = set()
    for s in config.scenes.values():
        if s.background:
            wanted.add(s.background)
    for i in config.interruptions.values():
        if i.background:
            wanted.add(i.background)
    if not wanted:
        return [_r("Backgrounds", WARN, "no scenes reference a background")]

    lister = getattr(rt.controller.display, "available_backgrounds", None)
    if not callable(lister):
        return [_r("Backgrounds", WARN,
                   "display device cannot list backgrounds (fake display?)")]
    try:
        have = set(lister())
    except Exception as exc:   # noqa: BLE001
        return [_r("Backgrounds", FAIL, "could not list backgrounds: %s" % exc)]

    # Backgrounds are matched on their base name, so compare the same way.
    def base(name):
        stem = os.path.splitext(name)[0]
        splitter = getattr(rt.controller.display, "_split", None)
        return splitter(stem)[0] if callable(splitter) else stem.lower()

    missing = sorted(w for w in wanted if base(w) not in have)
    if not missing:
        return [_r("Backgrounds", PASS,
                   "all %d referenced backgrounds found" % len(wanted))]

    # A missing CUSTOM map is a warning, not a failure. Custom maps are
    # uploaded by whoever is running the table and are meant to be deletable;
    # a scene still pointing at one that has been removed is worth being told
    # about, but it is not a reason to red-flag the table before a session.
    #
    # A missing BUILT-IN background stays a failure -- that is a shipped asset,
    # and one going absent means something is actually broken.
    custom = set(_custom_slugs(config))
    gone_custom = sorted(m for m in missing if base(m) in custom)
    gone_builtin = sorted(m for m in missing if base(m) not in custom)

    results = []
    if gone_builtin:
        results.append(_r("Backgrounds", FAIL,
                          "%d of %d referenced backgrounds are MISSING: %s"
                          % (len(gone_builtin), len(wanted),
                             ", ".join(gone_builtin))))
    if gone_custom:
        results.append(_r("Backgrounds", WARN,
                          "%d uploaded map%s referenced by a scene %s been "
                          "deleted: %s"
                          % (len(gone_custom), "" if len(gone_custom) == 1 else "s",
                             "has" if len(gone_custom) == 1 else "have",
                             ", ".join(gone_custom))))
    if not gone_builtin:
        results.append(_r("Backgrounds", PASS,
                          "%d of %d referenced backgrounds found"
                          % (len(wanted) - len(missing), len(wanted))))
    return results


def _custom_slugs(config) -> List[str]:
    """Which backgrounds came from map import, per its stored recipes.

    Import is local and guarded: this check must keep working on a machine
    where map import was never set up, or where Pillow is not installed.
    """
    data_path = getattr(config, "map_data_path", None)
    if not data_path:
        return []
    try:
        from .mapimport import recipes
        return recipes.known_slugs(os.path.join(data_path, "recipes"))
    except Exception:              # noqa: BLE001
        return []


# ----------------------------------------------------------- device checks

def _check_lights_device(rt) -> Dict[str, Any]:
    probe = getattr(rt.lights, "status", None)
    if not callable(probe):
        return _r("Lights", WARN, "fake light device")
    info = probe()
    if not info.get("healthy"):
        return _r("Lights", FAIL, info.get("error") or "not connected")

    eff = info.get("effective_pct")
    detail = "connected at %s" % info.get("address")
    if eff is not None:
        detail += ", %s%% effective brightness" % eff
        # The failure this catches: everything green, table looks dead.
        if eff < 5:
            return _r("Lights", WARN, detail + " — so dim it will look broken")
    return _r("Lights", PASS, detail)


def _check_audio_device(rt) -> Dict[str, Any]:
    probe = getattr(rt.controller.audio, "status", None)
    if not callable(probe):
        return _r("Audio", WARN, "fake audio device")
    info = probe()
    if not info.get("healthy"):
        return _r("Audio", FAIL, info.get("error") or "not initialised")
    tracks = info.get("tracks", 0)
    if not tracks:
        return _r("Audio", FAIL, "mixer is up but the library is empty")
    return _r("Audio", PASS, "%d tracks, device %s" % (tracks, info.get("device")))


def _check_nfc(rt) -> Dict[str, Any]:
    probe = getattr(rt.controller, "_nfc_status", None)
    if not callable(probe):
        return _r("NFC reader", WARN, "not enabled — cards will not work")
    info = probe()
    if not info.get("healthy"):
        return _r("NFC reader", FAIL, info.get("error") or "not detected")
    return _r("NFC reader", PASS,
              "firmware %s, %s taps this session"
              % (info.get("firmware"), info.get("taps", 0)))


def _check_display(rt) -> Dict[str, Any]:
    probe = getattr(rt.controller.display, "status", None)
    if not callable(probe):
        return _r("Display", WARN, "fake display device")
    info = probe()
    if not info.get("healthy"):
        return _r("Display", FAIL, info.get("error") or "viewer not running")
    detail = ("%d backgrounds, showing %s"
              % (info.get("images", 0), info.get("background") or "nothing yet"))
    # A viewer that keeps dying and being rescued reads as PASS on every
    # individual check, which is how it would go unnoticed until it failed
    # to come back during a session. Recovered is not the same as fine.
    respawns = info.get("respawns", 0)
    if respawns:
        return _r("Display", WARN, "%s - viewer has been restarted %d time(s)"
                  % (detail, respawns))
    return _r("Display", PASS, detail)


def _check_video_output(rt) -> Dict[str, Any]:
    """Is a picture actually reaching the television?

    THE ONE CHECK THAT COVERS THE GAP.

    Everything else in this file answers "did the call succeed". This one
    answers "did anything come out", and they are not the same question.
    On 2026-08-21 the HDMI output sat *connected with no mode set*: the Pi
    drove no signal, the TV was black, and the service, the display device,
    feh and the status strip all reported green, because every one of them
    was working exactly as designed. Nothing was wrong upstream. There was
    simply nothing downstream.

    A connected output is not a working one. Only an active MODE is.
    """
    reader = getattr(rt.controller.display, "video_output", None)
    if not callable(reader):
        # The fake display has no X server to ask. Not a fault.
        return _r("Video output", PASS, "not applicable (no real display)")

    try:
        info = reader()
    except Exception as exc:   # noqa: BLE001
        return _r("Video output", FAIL, "could not read: %s" % exc)

    if info.get("error"):
        return _r("Video output", WARN,
                  "could not ask the X server: %s" % info["error"])

    outputs = info.get("outputs") or []
    connected = [o for o in outputs if o["connected"]]
    if not connected:
        return _r("Video output", FAIL,
                  "no display is connected — check the HDMI cable and that "
                  "the TV is powered on")

    live = [o for o in connected if o["mode"]]
    if not live:
        names = ", ".join(o["name"] for o in connected)
        # Name the fix. This is recoverable in one command, and a check that
        # says only "broken" at the start of a session is half a check.
        return _r("Video output", FAIL,
                  "%s is connected but NO MODE IS SET, so nothing is being "
                  "sent to the screen. Fix: xrandr --output %s --mode %s"
                  % (names, connected[0]["name"],
                     info.get("pinned") or "3840x2160"))

    pinned = info.get("pinned")
    shown = ", ".join("%s at %s" % (o["name"], o["mode"]) for o in live)
    if pinned and any(o["mode"] != pinned for o in live):
        return _r("Video output", WARN,
                  "%s, but %s was pinned at boot — artwork will be scaled"
                  % (shown, pinned))

    return _r("Video output", PASS, shown)


def _check_disk() -> Dict[str, Any]:
    """The SD card filling up is a slow, quiet way for the table to die."""
    try:
        usage = shutil.disk_usage("/")
    except Exception as exc:   # noqa: BLE001
        return _r("Disk space", WARN, str(exc))
    free_gb = usage.free / (1024 ** 3)
    pct = usage.used / usage.total * 100
    detail = "%.1f GB free (%.0f%% used)" % (free_gb, pct)
    if free_gb < 0.5:
        return _r("Disk space", FAIL, detail)
    if free_gb < 2:
        return _r("Disk space", WARN, detail)
    return _r("Disk space", PASS, detail)


# --------------------------------------------------------- physical checks

def _physical(rt) -> List[Dict[str, Any]]:
    """Prove light and sound physically happen, then put things back.

    Software cannot tell whether photons left the LEDs — that needs eyes.
    These fire something obvious and restore the previous state, so running
    the check never strands the table somewhere unexpected.
    """
    out = []
    controller = rt.controller
    previous = controller.current_scene.name if controller.current_scene else None

    # Lights: something unmistakable, briefly.
    try:
        patterns = rt.lights.available_patterns()
        flash = next((p for p in ("KITT", "blink fade", "fireflies") if p in patterns),
                     patterns[0] if patterns else None)
        if flash:
            rt.lights.set_pattern(flash)
            time.sleep(2.5)
            out.append(_r("Lights: visible?", PASS,
                          "flashed '%s' — confirm the LEDs actually lit" % flash))
        else:
            out.append(_r("Lights: visible?", WARN, "no patterns to flash"))
    except Exception as exc:   # noqa: BLE001
        out.append(_r("Lights: visible?", FAIL, str(exc)))

    # Audio: something audible, briefly.
    try:
        tracks = controller.audio.available_tracks()
        if tracks:
            controller.audio.play_effect(tracks[0], duck=False, max_duration=2.0)
            time.sleep(2.2)
            out.append(_r("Audio: audible?", PASS,
                          "played '%s' — confirm you heard it" % tracks[0]))
        else:
            out.append(_r("Audio: audible?", WARN, "no tracks to play"))
    except Exception as exc:   # noqa: BLE001
        out.append(_r("Audio: audible?", FAIL, str(exc)))

    # Put the table back where it was.
    try:
        if previous:
            controller.apply_scene(previous)
        else:
            controller.go_idle()
        out.append(_r("Restored", PASS, "back to %s" % (previous or "idle")))
    except Exception as exc:   # noqa: BLE001
        out.append(_r("Restored", FAIL, str(exc)))

    return out
