#!/usr/bin/env python3
"""Rewrite WAV files so the table's pygame can actually load them.

    tools/normalise_wavs.py voices/audio/entity            # fix in place
    tools/normalise_wavs.py voices/audio/entity --check    # report only

WHY THIS EXISTS
---------------
The Pi runs **pygame 1.9.6**, which is SDL 1.2 underneath, and SDL 1.2's WAV
loader expects the `fmt ` chunk to come first. ffmpeg writes a 52-byte `JUNK`
chunk ahead of it -- reserved space in case the output needs to become RF64 --
and SDL refuses the file outright:

    pygame.error: Unable to open file '.../system_startup_03.wav'

Nothing else notices. Python's `wave` module skips unknown chunks happily, so
the files open, report the right duration, and look perfectly healthy in every
test that does not go through pygame. All 91 Entity lines were affected, and
the only symptom was silence plus one `voice.failed` line in the journal.

This rewrites each file as canonical RIFF/`fmt `/`data`, which SDL accepts.

LOSSLESS, AND CHECKED. The PCM frames are compared before and after, and the
file is only replaced if they are byte-identical. Rewriting audio in place is
exactly the kind of operation that should refuse to proceed on any doubt.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import tempfile
import wave


def first_chunk(path: str) -> str:
    """The chunk id immediately after the RIFF/WAVE header."""
    with open(path, "rb") as fh:
        head = fh.read(16)
    if len(head) < 16 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        return "?"
    return head[12:16].decode("latin-1", "replace")


def needs_fix(path: str) -> bool:
    return first_chunk(path) != "fmt "


def normalise(path: str) -> bool:
    """Rewrite one file canonically. Returns True if it was changed."""
    with wave.open(path, "rb") as src:
        params = src.getparams()
        frames = src.readframes(src.getnframes())

    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    os.close(fd)
    try:
        with wave.open(tmp, "wb") as dst:
            dst.setnchannels(params.nchannels)
            dst.setsampwidth(params.sampwidth)
            dst.setframerate(params.framerate)
            dst.writeframes(frames)

        # Verify before replacing. The whole point of this tool is that the
        # audio is unchanged; a rewrite that quietly altered it would be far
        # worse than the bug it fixes.
        with wave.open(tmp, "rb") as check:
            if check.readframes(check.getnframes()) != frames:
                raise ValueError("frames differ after rewrite")
            if (check.getnchannels(), check.getsampwidth(),
                    check.getframerate()) != (params.nchannels,
                                              params.sampwidth,
                                              params.framerate):
                raise ValueError("format differs after rewrite")
        if first_chunk(tmp) != "fmt ":
            raise ValueError("rewritten file still does not start with fmt ")

        os.replace(tmp, path)
        return True
    except Exception:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("directory", help="directory of .wav files")
    ap.add_argument("--check", action="store_true",
                    help="report what would change, touch nothing")
    args = ap.parse_args()

    if not os.path.isdir(args.directory):
        print("no such directory: %s" % args.directory, file=sys.stderr)
        return 2

    files = sorted(f for f in os.listdir(args.directory) if f.lower().endswith(".wav"))
    if not files:
        print("no .wav files in %s" % args.directory)
        return 0

    bad = [f for f in files if needs_fix(os.path.join(args.directory, f))]
    print("%d wav files, %d need rewriting" % (len(files), len(bad)))
    if bad:
        print("  leading chunk found: %s"
              % ", ".join(sorted({first_chunk(os.path.join(args.directory, f))
                                  for f in bad})))

    if args.check or not bad:
        for f in bad[:10]:
            print("   would rewrite %s" % f)
        if len(bad) > 10:
            print("   ... and %d more" % (len(bad) - 10))
        return 0

    fixed = 0
    for f in bad:
        path = os.path.join(args.directory, f)
        try:
            if normalise(path):
                fixed += 1
        except Exception as exc:      # noqa: BLE001
            print("  FAILED %s: %s: %s" % (f, type(exc).__name__, exc),
                  file=sys.stderr)

    print("rewrote %d of %d" % (fixed, len(bad)))
    still = [f for f in files if needs_fix(os.path.join(args.directory, f))]
    print("still not canonical: %s" % (still or "none"))
    return 0 if not still else 1


if __name__ == "__main__":
    sys.exit(main())
