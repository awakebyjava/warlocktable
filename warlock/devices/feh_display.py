"""Real display device — fullscreen artwork on the embedded TV.

HOW IT WORKS

feh runs fullscreen showing one file, `.current.png`, with `--reload 0.2`.
Changing the background copies the wanted image over that file and feh picks
it up within about a fifth of a second. It was 1s, which measured as the
dominant term in how far the picture trailed the lights and sound.

That indirection is the point: feh owns the X window for the whole session,
so switching images never creates or destroys a window. Killing and
relaunching a viewer per change would flash the desktop between every scene,
which at a game table looks like a fault.

WHY feh RATHER THAN pygame

pygame is already a dependency and could draw this. But the controller
already uses pygame.mixer in-process, and adding pygame.display to the same
process means one library owning both the audio device and an X window
inside a systemd service with no session. feh is a 500KB distro package that
does exactly one job.

REACHING THE SCREEN

The service runs under systemd, outside the desktop session, so it has no
DISPLAY of its own. feh is launched with DISPLAY/XAUTHORITY pointing at the
running X session. Xorg runs as root here but the `pi` user's Xauthority
grants access.

NAMING

Config refers to a background as "forest.png" while the files on disk are
"forest_3840x2160.png" and "forest_3840x2160_grid.png". Rather than force
config to carry render-specific filenames, names are matched on their base:
everything up to the resolution/grid suffix. That also gives the gridded
variants for free as a toggle rather than as separate scenes.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Dict, List, Optional

from .base import (DeviceError, DisplayDevice, STATUS_SCREEN,
                   UnknownAssetError)

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
CURRENT = ".current.png"

# --- viewer supervision ---------------------------------------------------
#
# feh is launched once and, before this existed, was never launched again.
# When it died the TV went black and stayed black: status() flipped healthy
# to False and every set_background() after that raised, so the only way
# back was restarting the service. Mid-session that is the entire visual
# half of the table gone, with nobody at a keyboard.
#
# It happened for real on 2026-08-22 -- no OOM, no segfault, plenty of free
# memory, and nothing in any log saying why. That is the case this guards:
# we cannot prevent an exit we cannot explain, so recover from it instead.
WATCH_INTERVAL_S = 2.0      # how often to notice feh is gone
RESPAWN_BACKOFF_S = 3.0     # wait between attempts, so a hard failure
                            # does not become a spawn loop
RESPAWN_MAX_TRIES = 5       # then stop and stay unhealthy, because a
                            # sixth attempt would not be different

# "HDMI-1 connected primary 3840x2160+0+0 (normal ...)" -- the geometry is
# optional, and its ABSENCE is the interesting case.
_OUTPUT_LINE = re.compile(
    r"^(?P<name>\S+) (?P<state>connected|disconnected)"
    r"(?: primary)?(?: (?P<mode>\d+x\d+)\+\d+\+\d+)?")

# Where the boot-time mode pin lives, per the HDMI notes in plan doc 3.6.
CMDLINE = "/boot/cmdline.txt"


def _pinned_mode():
    """The resolution pinned at boot, e.g. "3840x2160", or None.

    Read rather than assumed: comparing what X is doing against what the
    boot config asked for is what turns "there is a picture" into "there is
    the RIGHT picture".
    """
    try:
        with open(CMDLINE, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    match = re.search(r"video=\S*?:(\d+x\d+)", text)
    return match.group(1) if match else None

# Overlays a background can carry. "" is the plain artwork.
#   forest_3840x2160.png       -> base "forest", overlay ""
#   forest_3840x2160_grid.png  -> base "forest", overlay "grid"
#   forest_3840x2160_hex.png   -> base "forest", overlay "hex"
OVERLAYS = ("grid", "hex")

# STATUS_SCREEN comes from .base: it is a background like any other as far
# as this device is concerned -- just an image swapped into CURRENT -- but
# the controller has to recognise the name as well, so it is defined once
# on the interface rather than here.

# Deliberately data-driven off OVERLAYS rather than hardcoding the two
# names: adding a third overlay later should be a filename convention, not
# a code change.
_SUFFIX = re.compile(
    r"^(?P<base>.+?)(?:[_-]\d{3,5}x\d{3,5})?(?:[_-](?P<overlay>%s))?$"
    % "|".join(OVERLAYS), re.IGNORECASE)


class FehDisplay(DisplayDevice):
    def __init__(self, log, search_paths: List[str],
                 display: str = ":0",
                 xauthority: str = "/home/pi/.Xauthority"):
        self.log = log
        self.search_paths = [os.path.expanduser(p) for p in search_paths]
        self.display = display
        self.xauthority = xauthority

        # base name -> {"plain": path, "grid": path}
        self._library: Dict[str, Dict[str, str]] = {}
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.RLock()
        self._current_dir: Optional[str] = None

        # Viewer supervision. _stop is how close() gets the watcher to
        # leave promptly instead of sleeping out its interval.
        self._stop = threading.Event()
        self._watcher: Optional[threading.Thread] = None
        self._respawns = 0          # successful relaunches, for status()
        self._stderr_file: Optional[str] = None

        # "" = plain artwork, otherwise one of OVERLAYS.
        self.overlay = ""
        self.background: Optional[str] = None
        self.healthy = False
        self.last_error: Optional[str] = None

    # ------------------------------------------------------------- lifecycle

    def start(self) -> bool:
        """Scan the library and launch the viewer. Never raises (5.2)."""
        self._scan()
        if not self._library:
            self.last_error = "no images found in %s" % (
                ", ".join(self.search_paths) or "any configured path")
            self.log.record("display.unavailable", error=self.last_error)
            return False

        # feh needs a file to exist before it will start.
        self._current_dir = os.path.dirname(
            next(iter(self._library.values()))["plain"])
        target = os.path.join(self._current_dir, CURRENT)
        if not os.path.exists(target):
            first = next(iter(self._library.values()))["plain"]
            try:
                shutil.copyfile(first, target)
            except OSError as exc:
                self.last_error = str(exc)
                self.log.record("display.unavailable", error=self.last_error)
                return False

        if not self._launch(target):
            return False

        # Only supervise something that started. Watching a viewer that
        # never came up would just retry a failure five times at boot.
        self._watcher = threading.Thread(target=self._watch,
                                         name="feh-watch", daemon=True)
        self._watcher.start()
        return True

    def video_output(self) -> dict:
        """What the X server is actually driving on each output.

        WHY THIS EXISTS, and it is not theoretical.

        `healthy` on this device means "feh is running and the file swap
        worked". It does NOT mean a picture is reaching the television. An
        output can be *connected*, list every mode it supports, and have
        **none of them active** -- in which case the Pi drives no signal at
        all, the screen is black, and every check in this system still
        reports green. That is exactly what happened on 2026-08-21: the
        table looked perfectly healthy while the TV showed nothing.

        So this asks the X server the one question the rest of the stack
        cannot: is a mode actually set?

        Returns {"outputs": [...], "pinned": str|None, "error": str|None}.
        Never raises -- a check that cannot run must report that, not crash
        the thing it was checking.
        """
        env = dict(os.environ)
        env["DISPLAY"] = self.display
        env["XAUTHORITY"] = self.xauthority

        try:
            proc = subprocess.run(["xrandr", "--query"], env=env,
                                  capture_output=True, text=True, timeout=10)
        except FileNotFoundError:
            return {"outputs": [], "pinned": None,
                    "error": "xrandr is not installed"}
        except Exception as exc:   # noqa: BLE001
            return {"outputs": [], "pinned": None, "error": str(exc)}

        if proc.returncode != 0:
            return {"outputs": [], "pinned": None,
                    "error": (proc.stderr or "xrandr failed").strip()}

        outputs = []
        for line in proc.stdout.splitlines():
            match = _OUTPUT_LINE.match(line)
            if not match:
                continue
            # A geometry (WxH+X+Y) on the output's own line is the only
            # reliable sign a mode is set. "connected" alone says a cable
            # and a sink are there, which is not the same thing at all.
            outputs.append({
                "name": match.group("name"),
                "connected": match.group("state") == "connected",
                "mode": match.group("mode"),          # None when unset
            })

        return {"outputs": outputs, "pinned": _pinned_mode(), "error": None}

    def _launch(self, target: str) -> bool:
        env = dict(os.environ)
        env["DISPLAY"] = self.display
        env["XAUTHORITY"] = self.xauthority
        cmd = [
            "feh",
            "--fullscreen",
            "--hide-pointer",
            "--auto-zoom",          # fill the screen, preserving aspect
            "--image-bg", "black",  # letterbox in black, not desktop grey
            # 0.2, not 1: feh POLLS, so this is the dominant term in how
            # long the picture trails the lights and sound -- 0-1000ms of
            # pure waiting, measured 2026-08-22 (plan doc 5.7). feh 3.6.3
            # on the Pi accepts a fractional value; verified by parsing it
            # with the display unset, where it complains only about X.
            "--reload", "0.2",      # notice the file being swapped
            "--no-menus",
            target,
        ]
        # stderr goes to a FILE, not a pipe. A pipe here is a trap: nothing
        # reads it after the startup check below, so once feh writes enough
        # to fill the ~64KB buffer it blocks forever on write and the
        # picture freezes with the process still "alive". A file cannot
        # fill, and we can still read the text back when it dies.
        self._discard_stderr()
        try:
            handle, self._stderr_file = tempfile.mkstemp(prefix="feh-", suffix=".err")
        except OSError:
            handle, self._stderr_file = None, None

        try:
            self._proc = subprocess.Popen(
                cmd, env=env, stdout=subprocess.DEVNULL,
                stderr=(handle if handle is not None else subprocess.DEVNULL),
                start_new_session=True)
        except (OSError, FileNotFoundError) as exc:
            self.last_error = "could not start feh: %s" % exc
            self.log.record("display.unavailable", error=self.last_error)
            return False
        finally:
            if handle is not None:
                os.close(handle)     # the child holds its own copy

        # feh exits immediately if it cannot open the display; give it a
        # moment and check, so status() is honest rather than optimistic.
        time.sleep(0.6)
        if self._proc.poll() is not None:
            err = self._read_stderr()
            self.last_error = "feh exited immediately: %s" % (err or "no output")
            self.log.record("display.unavailable", error=self.last_error)
            self._proc = None
            return False

        self.healthy = True
        self.last_error = None
        self.log.record("display.ready", images=len(self._library),
                        display=self.display)
        return True

    # -------------------------------------------------- viewer supervision

    def _read_stderr(self) -> str:
        """Whatever feh complained about before it died. Never raises."""
        if not self._stderr_file:
            return ""
        try:
            with open(self._stderr_file, "r", errors="replace") as fh:
                # Only the tail is useful and the file is untrusted in
                # size -- a chatty feh should not pull megabytes into a
                # log line.
                return fh.read()[-2000:].strip()
        except OSError:
            return ""

    def _discard_stderr(self) -> None:
        if not self._stderr_file:
            return
        try:
            os.unlink(self._stderr_file)
        except OSError:
            pass
        self._stderr_file = None

    def _watch(self) -> None:
        """Relaunch feh if it dies. Runs until close().

        Nothing needs restoring after a relaunch: the image on screen is
        whatever is in CURRENT on disk, that file is untouched by feh
        exiting, and --reload makes the new instance pick it up. So a
        respawn is just _launch() again with the same target.
        """
        tries = 0
        while not self._stop.wait(WATCH_INTERVAL_S):
            with self._lock:
                if self._current_dir is None:
                    continue
                if self._proc is not None and self._proc.poll() is None:
                    tries = 0           # alive; forget earlier failures
                    continue
                if tries >= RESPAWN_MAX_TRIES:
                    continue            # gave up; status() says why

                err = self._read_stderr()
                self.healthy = False
                tries += 1
                self.log.record("display.viewer_died", attempt=tries,
                                stderr=err[-200:] or "(silent)")

                target = os.path.join(self._current_dir, CURRENT)
                if self._launch(target):
                    self._respawns += 1
                    self.log.record("display.respawned", attempt=tries,
                                     total=self._respawns)
                    tries = 0
                    continue

                if tries >= RESPAWN_MAX_TRIES:
                    self.last_error = ("feh died and would not restart after "
                                       "%d attempts: %s"
                                       % (tries, self.last_error or "no output"))
                    self.log.record("display.unavailable",
                                    error=self.last_error)

            # Outside the lock: a failing respawn must not hold up a scene
            # change that is only going to fail fast anyway.
            self._stop.wait(RESPAWN_BACKOFF_S)

    def close(self) -> None:
        # Signal BEFORE taking the lock, so the watcher cannot win a race
        # and relaunch feh while we are shutting it down.
        self._stop.set()
        watcher, self._watcher = self._watcher, None
        if watcher is not None and watcher is not threading.current_thread():
            watcher.join(timeout=WATCH_INTERVAL_S + RESPAWN_BACKOFF_S + 2)

        with self._lock:
            if self._proc is not None:
                try:
                    self._proc.terminate()
                    self._proc.wait(timeout=3)
                except Exception:
                    try:
                        self._proc.kill()
                    except Exception:
                        pass
                self._proc = None
            self._discard_stderr()
            self.healthy = False

    # ---------------------------------------------------------------- library

    @staticmethod
    def _split(stem: str):
        """-> (base, overlay). overlay is "" for the plain artwork."""
        m = _SUFFIX.match(stem)
        if not m:
            return stem.lower(), ""
        return m.group("base").lower(), (m.group("overlay") or "").lower()

    def _scan(self) -> None:
        found: Dict[str, Dict[str, str]] = {}
        for base_dir in self.search_paths:
            if not os.path.isdir(base_dir):
                self.log.record("display.path_missing", path=base_dir)
                continue
            for fn in sorted(os.listdir(base_dir)):
                if fn.startswith("."):
                    continue          # skip .current.png
                stem, ext = os.path.splitext(fn)
                if ext.lower() not in IMAGE_EXTENSIONS:
                    continue
                base, overlay = self._split(stem)
                entry = found.setdefault(base, {})
                entry[overlay or "plain"] = os.path.join(base_dir, fn)
        # Any missing variant falls back to the plain artwork (or to
        # whatever exists), so a background with only one render is still
        # usable and asking for an overlay it lacks degrades quietly.
        for base, variants in found.items():
            fallback = variants.get("plain") or next(iter(variants.values()))
            variants.setdefault("plain", fallback)
            for ov in OVERLAYS:
                variants.setdefault(ov, fallback)
        self._library = found

    def available_backgrounds(self) -> List[str]:
        # Status screen first: it is the one entry that is not artwork, and
        # burying it alphabetically among the scenes hides the thing you
        # reach for when you are trying to see what is wrong.
        return [STATUS_SCREEN] + sorted(self._library.keys())

    def _resolve(self, name: str) -> str:
        base, wanted = self._split(os.path.splitext(name)[0])
        variants = self._library.get(base)
        if variants is None:
            raise UnknownAssetError(
                "no background named %r (%d available: %s)"
                % (name, len(self._library),
                   ", ".join(sorted(self._library)[:6])))
        # An overlay named explicitly in the request wins; otherwise follow
        # the current mode.
        overlay = wanted or self.overlay
        return variants.get(overlay or "plain", variants["plain"])

    # -------------------------------------------------------------- interface

    def set_background(self, name: str) -> None:
        with self._lock:
            path = self._resolve(name)
            # Being mid-respawn is NOT a reason to refuse. The file is the
            # source of truth -- feh only reads it -- so writing it while
            # the watcher is bringing a new viewer up is both safe and
            # exactly right: the new instance opens the scene we wanted.
            # Refusing here would drop a card tap on the floor for the two
            # seconds that recovery takes, which is the failure this whole
            # change exists to remove.
            supervised = self._watcher is not None and self._watcher.is_alive()
            if self._current_dir is None or (not self.healthy and not supervised):
                raise DeviceError("display unavailable: %s"
                                  % (self.last_error or "not started"))

            # Copy rather than symlink: feh's --reload re-stats the same
            # filename, and a copy is unambiguous about having changed.
            target = os.path.join(self._current_dir, CURRENT)
            t0 = time.monotonic()
            try:
                tmp = target + ".tmp"
                shutil.copyfile(path, tmp)
                os.replace(tmp, target)     # atomic: feh never sees a partial file
            except OSError as exc:
                self.healthy = False
                self.last_error = str(exc)
                raise DeviceError("could not swap background: %s" % exc)

            self.background = name
            self.log.record("display.background", name=name,
                            file=os.path.basename(path),
                            overlay=self.overlay or "none",
                            swap_ms=round((time.monotonic() - t0) * 1000),
                            real=True)

    def show_status(self, report, branding: str = None) -> None:
        """Render the status screen and put it on the TV (plan doc 5.1).

        Goes through the SAME feh instance as the artwork, so there is only
        ever one thing drawing on the screen. The status screen is, as far as
        the display is concerned, just another image.
        """
        from ..statusscreen import render
        with self._lock:
            if self._current_dir is None:
                raise DeviceError("display not started")
            out = os.path.join(self._current_dir, ".status.png")
            render(out, report, branding=branding)
            target = os.path.join(self._current_dir, CURRENT)
            tmp = target + ".tmp"
            shutil.copyfile(out, tmp)
            os.replace(tmp, target)
            self.background = STATUS_SCREEN
            self.log.record("display.status_screen", overall=report.get("overall"))

    def set_overlay(self, mode: str) -> None:
        """Choose the map overlay and re-show the current background.

        A mode rather than a boolean, because there are now three states
        (none / square grid / hex) and there may be more. Kept out of scene
        names deliberately: an overlay under an ambient forest looks wrong
        when nobody is running a combat, and duplicating every scene per
        overlay would multiply the config for what is one setting.
        """
        mode = (mode or "").lower()
        if mode in ("none", "off", "plain"):
            mode = ""
        if mode and mode not in OVERLAYS:
            raise UnknownAssetError(
                "unknown overlay %r (have: none, %s)" % (mode, ", ".join(OVERLAYS)))
        with self._lock:
            self.overlay = mode
            self.log.record("display.overlay", mode=mode or "none")
            if self.background and self.background != STATUS_SCREEN:
                self.set_background(self.background)

    def available_overlays(self) -> List[str]:
        return ["none"] + list(OVERLAYS)

    def handoff(self, target: str) -> None:
        # HDMI-CEC (plan doc 3.7) is not built yet. Log the intent so the
        # panel button can exist without silently doing nothing.
        self.log.record("display.handoff", target=target, implemented=False)

    def status(self) -> dict:
        alive = self._proc is not None and self._proc.poll() is None
        if self.healthy and not alive:
            # feh died at some point - say so rather than keep claiming ok.
            # The watcher will normally have this back within a couple of
            # seconds, so seeing it here means either bad luck on timing or
            # a relaunch that is failing; don't clobber the watcher's more
            # specific message if it already set one.
            self.healthy = False
            if not self.last_error:
                self.last_error = "feh is no longer running"
        return {
            "healthy": self.healthy,
            "background": self.background,
            "overlay": self.overlay or "none",
            "overlays": ["none"] + list(OVERLAYS),
            "images": len(self._library),
            # A display that keeps needing rescue is still a fault, even
            # though every individual recovery worked. Without this the
            # only trace is log lines nobody is reading.
            "respawns": self._respawns,
            "error": self.last_error,
        }
