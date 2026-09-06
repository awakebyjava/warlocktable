#!/usr/bin/env python3
"""Repair the scene soundscapes without replacing them.

    tools/fix_beds.py --check          # measure, change nothing
    tools/fix_beds.py                  # write repaired copies
    tools/fix_beds.py --format wav     # if the mixer ever stops reading ogg

The originals are good recordings with three engineering faults. This fixes
the engineering and leaves the content entirely alone.

WHAT WAS ACTUALLY WRONG (measured on the table, 2026-09-06)
-----------------------------------------------------------
1. FORMAT. pygame's mixer runs at 44100/16/stereo. The beds were 44100, 48000
   and 96000; 16-bit, 24-bit and one float32. Only island matched. Everything
   else was being converted by SDL on load, and that conversion is where the
   level differences came from -- so this is the root cause of fault 2, not a
   separate tidy-up.

2. LEVEL. 7.6 dB between the quietest and loudest, which is roughly double the
   loudness. Levelled here on the MONO SUM rather than per channel: people sit
   around this table, close, so what they hear is near enough mono, and two
   files at identical per-channel level can be far apart once summed.

3. LOOP SEAM. island's last 50ms measured 4.15x the level of its first 50ms,
   plains 1.87x. That step is what is audible every time round. An equal-power
   crossfade of the tail back over the head makes the file end exactly where
   it begins.

NOTHING IS OVERWRITTEN. Repaired files are written to a separate directory so
the originals stay put and the two can be compared on the table.
"""

from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
import tempfile

try:
    import numpy as np
    from pedalboard.io import AudioFile
except ImportError:
    sys.exit("needs numpy and pedalboard:  python -m pip install numpy pedalboard")

# What the mixer asks for. See pygame_audio: frequency=44100, size=-16,
# channels=2. Matching it exactly means SDL never resamples or requantises.
RATE = 44100
CHANNELS = 2

# Target loudness, measured on the mono sum. -30 dBFS RMS sits comfortably
# under the stings without disappearing beneath them.
TARGET_RMS_DB = -30.0

# How much of the tail is folded back over the head to close the loop.
CROSSFADE_S = 4.0

# Below this the channels are too decorrelated to survive being summed, and
# get narrowed until they are not.
MIN_CORRELATION = 0.35

SCENES = ("forest", "plains", "swamp", "island", "mountain")


def load(path):
    """Read anything ffmpeg understands, at the mixer's rate."""
    with AudioFile(path).resampled_to(RATE) as f:
        return f.read(f.frames)


def measure(audio):
    if audio.shape[0] >= 2:
        mono = audio[:2].mean(axis=0)
        corr = float(np.corrcoef(audio[0], audio[1])[0, 1]) if audio.shape[-1] > 1 else 1.0
    else:
        mono = audio[0]
        corr = 1.0
    rms = float(np.sqrt(np.mean(mono.astype(np.float64) ** 2)))
    k = int(RATE * 0.05)
    head = float(np.sqrt(np.mean(mono[:k].astype(np.float64) ** 2)))
    tail = float(np.sqrt(np.mean(mono[-k:].astype(np.float64) ** 2)))
    seam = max(head, tail) / max(1e-9, min(head, tail))
    return {
        "secs": audio.shape[-1] / float(RATE),
        "rms_db": 20 * math.log10(rms) if rms > 0 else -99.0,
        "peak": float(np.max(np.abs(audio))),
        "corr": corr,
        "seam": seam,
    }


def close_the_loop(audio, seconds):
    """Fold the tail back over the head so the file ends where it begins.

    Equal-power (sine/cosine) rather than linear, so the level holds steady
    through the blend instead of dipping in the middle.
    """
    n = audio.shape[-1]
    k = int(RATE * seconds)
    if k <= 0 or n <= 2 * k:
        return audio
    head, tail = audio[:, :k].copy(), audio[:, -k:]
    t = np.linspace(0.0, 1.0, k, dtype=np.float32)
    out = audio[:, :n - k].copy()
    out[:, :k] = head * np.sin(t * np.pi / 2) + tail * np.cos(t * np.pi / 2)
    return out


def repair_dead_channel(audio):
    """A silent channel gets the live one copied across.

    plains.wav was found with a completely dead right channel -- zero
    throughout, so on stereo speakers it only ever came out of one side. That
    is a fault in the file, not a stylistic choice, and mono-summing it also
    halves its level relative to everything else.
    """
    if audio.shape[0] < 2:
        return audio, None
    live = [i for i in range(audio.shape[0]) if float(audio[i].std()) > 1e-9]
    if not live or len(live) == audio.shape[0]:
        return audio, None
    src = live[0]
    fixed = np.vstack([audio[src] for _ in range(audio.shape[0])]).astype(np.float32)
    dead = [i for i in range(audio.shape[0]) if i not in live]
    return fixed, dead


def widen_check(audio):
    """Narrow anything too out-of-phase to survive a mono sum."""
    if audio.shape[0] < 2:
        return audio, 1.0
    for _ in range(12):
        if audio[0].std() < 1e-9 or audio[1].std() < 1e-9:
            break
        corr = float(np.corrcoef(audio[0], audio[1])[0, 1])
        if corr >= MIN_CORRELATION:
            return audio, corr
        mid = (audio[0] + audio[1]) / 2.0
        side = (audio[0] - audio[1]) / 2.0 * 0.7
        audio = np.vstack([mid + side, mid - side]).astype(np.float32)
    return audio, float(np.corrcoef(audio[0], audio[1])[0, 1])


def level(audio, target_db):
    mono = audio[:2].mean(axis=0) if audio.shape[0] >= 2 else audio[0]
    rms = float(np.sqrt(np.mean(mono.astype(np.float64) ** 2)))
    if rms > 1e-9:
        audio = audio * ((10.0 ** (target_db / 20.0)) / rms)
    peak = float(np.max(np.abs(audio)))
    if peak > 0.99:
        audio = audio * (0.99 / peak)
    return audio


def write(audio, path, fmt):
    """Write the repaired bed.

    ogg goes through pedalboard, which writes it directly -- no ffmpeg, which
    is not installed on the laptop where this runs. wav is written with the
    stdlib so it comes out canonical RIFF/fmt/data, for the same reason the
    voice lines have to: the Pi's pygame 1.9.6 refuses a leading JUNK chunk.
    """
    if audio.shape[0] == 1:
        audio = np.vstack([audio[0], audio[0]])
    audio = np.clip(audio[:CHANNELS], -1.0, 1.0).astype(np.float32)

    if fmt == "ogg":
        with AudioFile(path, "w", RATE, CHANNELS, quality="192 kbps") as f:
            f.write(audio)
        return os.path.getsize(path)

    import wave
    pcm = (audio.T.reshape(-1) * 32767.0).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    return os.path.getsize(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=os.path.expanduser(
        "~/Documents/MagicTarot/MagicCards"))
    ap.add_argument("--out", default=os.path.expanduser(
        "~/Documents/MagicTarot/MagicCards-fixed"))
    ap.add_argument("--format", choices=("ogg", "wav"), default="ogg")
    ap.add_argument("--check", action="store_true", help="measure only")
    ap.add_argument("--crossfade", type=float, default=CROSSFADE_S)
    args = ap.parse_args()

    if not os.path.isdir(args.source):
        sys.exit("no such directory: %s" % args.source)
    if not args.check:
        os.makedirs(args.out, exist_ok=True)

    print("%-10s %7s %9s %8s %7s %8s" % ("scene", "secs", "rms dB", "seam", "corr", "peak"))
    print("-" * 56)

    before, after = {}, {}
    for scene in SCENES:
        src = None
        for ext in (".wav", ".ogg", ".flac", ".mp3"):
            p = os.path.join(args.source, scene + ext)
            if os.path.isfile(p):
                src = p
                break
        if src is None:
            print("%-10s (not found)" % scene)
            continue

        audio = load(src)
        m = measure(audio)
        before[scene] = m
        print("%-10s %7.1f %9.1f %7.2fx %7.2f %8.3f  <- before"
              % (scene, m["secs"], m["rms_db"], m["seam"], m["corr"], m["peak"]))

        if args.check:
            continue

        audio, dead = repair_dead_channel(audio)
        if dead:
            print("%-10s   channel %s was SILENT -- filled from the live one"
                  % ("", ",".join(str(d) for d in dead)))
        audio = close_the_loop(audio, args.crossfade)
        audio, _ = widen_check(audio)
        audio = level(audio, TARGET_RMS_DB)

        m2 = measure(audio)
        after[scene] = m2
        dest = os.path.join(args.out, "%s.%s" % (scene, args.format))
        size = write(audio, dest, args.format)
        print("%-10s %7.1f %9.1f %7.2fx %7.2f %8.3f  -> %s (%.1f MB)"
              % (scene, m2["secs"], m2["rms_db"], m2["seam"], m2["corr"],
                 m2["peak"], os.path.basename(dest), size / 1048576.0))

    if after:
        b = [v["rms_db"] for v in before.values()]
        a = [v["rms_db"] for v in after.values()]
        print()
        print("  level spread : %.1f dB  ->  %.1f dB" % (max(b) - min(b), max(a) - min(a)))
        print("  worst seam   : %.2fx    ->  %.2fx"
              % (max(v["seam"] for v in before.values()),
                 max(v["seam"] for v in after.values())))
        print("  originals untouched in %s" % args.source)
    return 0


if __name__ == "__main__":
    sys.exit(main())
