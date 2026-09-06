"""Get any sound file the operator has into one predictable shape.

WHY ffmpeg AND NOT A PYTHON LIBRARY

The Pi is armhf on Bullseye with Python 3.9. pedalboard, soundfile and scipy
have no wheel for it and building them on the table is not something to do
during a session -- the same wall the map import hit, and the same answer:
use the apt-installed command-line tool and keep Python for the arithmetic.
`heif-convert` does it for iPhone photos; ffmpeg does it here.

WHY RAW PCM ON A PIPE, AND NOT AN ffmpeg-WRITTEN FILE

Because ffmpeg is what caused the last audio outage. Asked to write a WAV it
emits a 52-byte JUNK chunk ahead of `fmt `, and the Pi's pygame 1.9.6 refuses
every file shaped that way -- all 91 voice lines failed silently until
tools/normalise_wavs.py was written to strip it. Taking the samples on a pipe
and writing the file from stdlib `wave` means the output is canonical because
of how it was made, not because something checked afterwards.

Everything comes out at 44100/stereo, which is what the mixer runs at. The
beds proved what happens otherwise: three different source rates meant SDL
resampled on load, and that conversion -- not the recordings -- is where
their 7.6 dB level spread came from.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Optional, Tuple

import numpy as np

from .errors import NoAudioStream, ToolMissing, TooLong, UnreadableAudio

RATE = 44100
CHANNELS = 2

# Decoded audio is float32 stereo at 44100: about 350 KB per second, so ten
# minutes is ~210 MB resident. The table has ~2.8 GB free and a session
# running on top, so this is the point at which an upload stops being
# somebody's sound effect and starts being a problem.
MAX_SECONDS = 600.0


def _tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise ToolMissing(
            "%s is not installed on the table, so uploaded sound cannot be "
            "converted. Install it with:  sudo apt install ffmpeg" % name)
    return path


def probe(path: str) -> dict:
    """Duration, rate, channels and codec -- BEFORE decoding anything.

    Read first so a two-hour file is refused by its header rather than after
    the table has spent a minute turning it into half a gigabyte of samples.
    """
    ffprobe = _tool("ffprobe")
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    except subprocess.TimeoutExpired:
        raise UnreadableAudio("That file took too long to read. It may be "
                              "corrupt, or not audio at all.")
    if out.returncode != 0:
        raise UnreadableAudio(
            "That file could not be read as audio. Supported: wav, mp3, ogg, "
            "flac, m4a, aac, opus.")

    try:
        meta = json.loads(out.stdout.decode("utf-8", "replace") or "{}")
    except ValueError:
        raise UnreadableAudio("That file could not be read as audio.")

    streams = [s for s in meta.get("streams", [])
               if s.get("codec_type") == "audio"]
    if not streams:
        raise NoAudioStream(
            "There is no sound in that file. If it is a video, the audio "
            "track has to be extracted first.")

    stream = streams[0]
    fmt = meta.get("format", {})
    try:
        seconds = float(fmt.get("duration") or stream.get("duration") or 0.0)
    except (TypeError, ValueError):
        seconds = 0.0

    if seconds > MAX_SECONDS:
        raise TooLong(
            "That is %.0f minutes long. The limit is %.0f minutes, because "
            "the table holds a sound in memory while it plays."
            % (seconds / 60.0, MAX_SECONDS / 60.0))

    return {
        "seconds": seconds,
        "rate": int(stream.get("sample_rate") or 0),
        "channels": int(stream.get("channels") or 0),
        "codec": stream.get("codec_name") or "?",
        "bytes": int(fmt.get("size") or os.path.getsize(path)),
    }


def decode(path: str) -> Tuple[np.ndarray, dict]:
    """-> (float32 array shaped (2, n), the probe info).

    ffmpeg writes signed 16-bit little-endian samples to stdout and nothing
    else; -v error keeps its banner off the pipe.
    """
    info = probe(path)
    ffmpeg = _tool("ffmpeg")

    cmd = [ffmpeg, "-v", "error", "-nostdin", "-i", path,
           "-map", "0:a:0",              # first audio stream, ignore video
           "-f", "s16le", "-acodec", "pcm_s16le",
           "-ar", str(RATE), "-ac", str(CHANNELS), "-"]
    try:
        out = subprocess.run(cmd, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, timeout=600)
    except subprocess.TimeoutExpired:
        raise UnreadableAudio("Converting that file took too long.")

    if out.returncode != 0 or not out.stdout:
        detail = (out.stderr or b"").decode("utf-8", "replace").strip()
        detail = detail.splitlines()[-1] if detail else "no detail given"
        raise UnreadableAudio("That file could not be converted: %s" % detail)

    pcm = np.frombuffer(out.stdout, dtype="<i2")
    usable = (pcm.size // CHANNELS) * CHANNELS
    if usable <= 0:
        raise NoAudioStream("That file decoded to no sound at all.")

    audio = (pcm[:usable].astype(np.float32) / 32768.0)
    audio = audio.reshape(-1, CHANNELS).T.copy()
    return audio, info
