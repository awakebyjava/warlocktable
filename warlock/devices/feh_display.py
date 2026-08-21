"""Real display device — fullscreen artwork on the embedded TV.

HOW IT WORKS

feh runs fullscreen showing one file, `.current.png`, with `--reload 1`.
Changing the background copies the wanted image over that file and feh picks
it up within a second.

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
import threading
import time
from typing import Dict, List, Optional

from .base import DeviceError, DisplayDevice, UnknownAssetError

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
CURRENT = ".current.png"

# Overlays a background can carry. "" is the plain artwork.
#   forest_3840x2160.png       -> base "forest", overlay ""
#   forest_3840x2160_grid.png  -> base "forest", overlay "grid"
#   forest_3840x2160_hex.png   -> base "forest", overlay "hex"
OVERLAYS = ("grid", "hex")

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

        return self._launch(target)

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
            "--reload", "1",        # notice the file being swapped
            "--no-menus",
            target,
        ]
        try:
            self._proc = subprocess.Popen(
                cmd, env=env, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, start_new_session=True)
        except (OSError, FileNotFoundError) as exc:
            self.last_error = "could not start feh: %s" % exc
            self.log.record("display.unavailable", error=self.last_error)
            return False

        # feh exits immediately if it cannot open the display; give it a
        # moment and check, so status() is honest rather than optimistic.
        time.sleep(0.6)
        if self._proc.poll() is not None:
            err = ""
            try:
                err = (self._proc.stderr.read() or b"").decode("utf-8", "replace").strip()
            except Exception:
                pass
            self.last_error = "feh exited immediately: %s" % (err or "no output")
            self.log.record("display.unavailable", error=self.last_error)
            self._proc = None
            return False

        self.healthy = True
        self.last_error = None
        self.log.record("display.ready", images=len(self._library),
                        display=self.display)
        return True

    def close(self) -> None:
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
        return sorted(self._library.keys())

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
            if not self.healthy or self._current_dir is None:
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
            self.background = "(status screen)"
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
            if self.background and self.background != "(status screen)":
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
            self.healthy = False
            self.last_error = "feh is no longer running"
        return {
            "healthy": self.healthy,
            "background": self.background,
            "overlay": self.overlay or "none",
            "overlays": ["none"] + list(OVERLAYS),
            "images": len(self._library),
            "error": self.last_error,
        }
