"""Session recording from the room microphone (plan doc 3.10).

Deliberately just a recorder. Transcription and recaps are a later
decision; this exists so a session can be captured while that gets figured
out, because the one thing you cannot do retrospectively is record.

WHY arecord RATHER THAN A PYTHON LIBRARY

No new dependency, it is already installed, and it addresses the device BY
NAME the same way the audio output does. Every lesson in plan doc 5.3 about
`hw:1,0` breaking when cards renumber applies just as much to capture as to
playback.

WHY 16 kHz MONO

The microphone is mono hardware, so stereo would be a fabricated second
channel. 16 kHz is the standard rate for speech transcription and a
quarter the size of 48 kHz -- about 115 MB an hour, so a long session fits
comfortably where 48 kHz would not. Nothing here is music.

THE ONE THING THAT WILL BITE

arecord writes the WAV header with a placeholder length and corrects it on
exit. Killing it outright leaves a file whose header claims the wrong
duration, which some players read as empty. Stopping therefore asks
politely and only escalates if that fails.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
import time
from typing import Optional

# Refuse to start below this. A recording that fills the card takes the
# whole table down with it, and the table matters more than the recording.
MIN_FREE_BYTES = 1024 * 1024 * 1024      # 1 GB

RATE = 16000
BYTES_PER_SECOND = RATE * 2              # S16_LE mono


class MicRecorder:
    """Records the room to a WAV file. Never raises at construction."""

    def __init__(self, log, device: str, out_dir: str):
        self.log = log
        self.device = device
        self.out_dir = out_dir
        self._proc: Optional[subprocess.Popen] = None
        self._path: Optional[str] = None
        self._started: float = 0.0
        self._lock = threading.RLock()
        self.last_error: Optional[str] = None

    # ------------------------------------------------------------- helpers

    @property
    def recording(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def _free_bytes(self) -> int:
        try:
            return shutil.disk_usage(self.out_dir).free
        except OSError:
            return 0

    def available(self) -> bool:
        """Is there a capture device to record from at all?"""
        if not shutil.which("arecord"):
            return False
        try:
            listed = subprocess.run(["arecord", "-l"], capture_output=True,
                                    text=True, timeout=5).stdout
        except Exception:   # noqa: BLE001
            return False
        return "card" in listed

    # -------------------------------------------------------------- record

    def start(self) -> dict:
        with self._lock:
            if self.recording:
                return self.status()

            os.makedirs(self.out_dir, exist_ok=True)
            free = self._free_bytes()
            if free < MIN_FREE_BYTES:
                self.last_error = ("only %.1f GB free; refusing to record"
                                   % (free / 1e9))
                self.log.record("mic.refused", reason=self.last_error)
                return self.status()

            name = time.strftime("session-%Y%m%d-%H%M%S.wav")
            path = os.path.join(self.out_dir, name)
            cmd = ["arecord", "-D", self.device, "-f", "S16_LE",
                   "-r", str(RATE), "-c", "1", path]
            try:
                self._proc = subprocess.Popen(
                    cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                    start_new_session=True)
            except Exception as exc:   # noqa: BLE001
                self._proc = None
                self.last_error = "%s: %s" % (type(exc).__name__, exc)
                self.log.record("mic.start_failed", error=self.last_error)
                return self.status()

            # arecord exits immediately if the device is wrong or busy, and
            # a "recording" that died half a second ago is worse than one
            # that never started, because nobody looks again.
            time.sleep(0.4)
            if self._proc.poll() is not None:
                err = (self._proc.stderr.read() or b"").decode(errors="replace")
                self.last_error = err.strip().splitlines()[-1] if err.strip() else "arecord exited"
                self.log.record("mic.start_failed", device=self.device,
                                error=self.last_error)
                self._proc = None
                return self.status()

            self._path = path
            self._started = time.monotonic()
            self.last_error = None
            self.log.record("mic.recording_started", file=name,
                            device=self.device, free_gb=round(free / 1e9, 1))
            return self.status()

    def stop(self) -> dict:
        with self._lock:
            proc, path = self._proc, self._path
            if proc is None:
                return self.status()

            # SIGINT, not kill: arecord writes the WAV header with a
            # placeholder length and only corrects it on a clean exit.
            # Killing it leaves a file whose header lies about its duration.
            try:
                proc.send_signal(signal.SIGINT)
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.log.record("mic.stop_slow", note="escalating to terminate")
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
            except Exception:   # noqa: BLE001
                pass

            seconds = time.monotonic() - self._started
            size = 0
            try:
                size = os.path.getsize(path) if path else 0
            except OSError:
                pass
            self._proc = None
            self._path = None
            self.log.record("mic.recording_stopped",
                            file=os.path.basename(path) if path else None,
                            seconds=round(seconds, 1),
                            megabytes=round(size / 1e6, 1))
            out = self.status()
            out["last_file"] = os.path.basename(path) if path else None
            out["last_seconds"] = round(seconds, 1)
            out["last_megabytes"] = round(size / 1e6, 1)
            return out

    def close(self) -> None:
        """Called on shutdown. A recording in progress is finalised, not
        abandoned -- otherwise a service restart silently corrupts it."""
        if self.recording:
            self.log.record("mic.stopping_for_shutdown")
            self.stop()

    # -------------------------------------------------------------- status

    def status(self) -> dict:
        with self._lock:
            free = self._free_bytes()
            elapsed = time.monotonic() - self._started if self.recording else 0.0
            return {
                "recording": self.recording,
                "device": self.device,
                "seconds": round(elapsed, 1),
                "file": os.path.basename(self._path) if self._path else None,
                "free_gb": round(free / 1e9, 1),
                # What is left at the current rate, so the panel can warn
                # before a long session runs the card out rather than after.
                "hours_left": round(free / (BYTES_PER_SECOND * 3600), 1),
                "error": self.last_error,
            }


class FakeMicRecorder:
    """Records nothing, reports plausibly. Keeps the panel testable with no
    hardware, same as every other fake."""

    def __init__(self, log, device: str = "(fake)", out_dir: str = ""):
        self.log = log
        self.device = device
        self._on = False
        self._started = 0.0
        self.last_error = None

    @property
    def recording(self) -> bool:
        return self._on

    def available(self) -> bool:
        return True

    def start(self) -> dict:
        if not self._on:
            self._on = True
            self._started = time.monotonic()
            self.log.record("mic.recording_started", file="(fake)")
        return self.status()

    def stop(self) -> dict:
        if self._on:
            self._on = False
            self.log.record("mic.recording_stopped",
                            seconds=round(time.monotonic() - self._started, 1))
        return self.status()

    def close(self) -> None:
        self.stop()

    def status(self) -> dict:
        return {
            "recording": self._on,
            "device": self.device,
            "seconds": round(time.monotonic() - self._started, 1) if self._on else 0.0,
            "file": "(fake).wav" if self._on else None,
            "free_gb": 99.0,
            "hours_left": 99.0,
            "error": None,
        }
