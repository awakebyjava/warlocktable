#!/usr/bin/env python3
"""Catalogue a sound-effects library into one CSV, so a shortlist can be made
without listening to thousands of files.

    tools/catalog_sfx.py                     # walk soundeffects/, write the CSV
    tools/catalog_sfx.py --limit 200         # try it on a subset first
    tools/catalog_sfx.py --force             # re-analyse everything
    tools/catalog_sfx.py --root some/dir     # somewhere else

LAPTOP-SIDE, ONE-TIME. Nothing here runs on the Pi, and nothing is copied,
renamed or moved -- the library is left exactly as it is. The CSV is the
deliverable.

WHAT THE COLUMNS ARE FOR
------------------------
The job is finding ~30-40 short one-shot stingers for card taps in a library
of thousands. Filenames in these bundles are genuinely descriptive, so most of
the work is text filtering -- but text alone cannot tell a two-second metal
impact from a ninety-second drone called "Metal Impact Designed". The acoustic
columns are there to answer the questions text cannot:

  duration_sec, is_oneshot   is it a stinger at all, or a bed
  spectral_centroid_hz       dark and rumbly, or bright and hissy
  attack_ms                  percussive, or a slow swell
  crest_factor               punchy transient, or sustained/compressed
  low/high_energy_ratio      impact, or shimmer
  rms_db, peak               how loud it will actually be against a soundscape

DEPENDENCIES: numpy and pedalboard, both already present from the voice work.
Deliberately not librosa -- every feature here is a few lines of FFT, and a
heavyweight dependency for that would be a poor trade.
"""

from __future__ import annotations

import argparse
import csv
import os
import struct
import sys
import time
import traceback

import numpy as np

try:
    from pedalboard.io import AudioFile
except ImportError:                                  # pragma: no cover
    print("needs pedalboard:  python -m pip install pedalboard", file=sys.stderr)
    raise SystemExit(2)

AUDIO_EXTS = (".wav", ".wave", ".flac", ".mp3", ".aif", ".aiff", ".ogg", ".m4a")

# Analyse at most this much of any one file. A ninety-second drone's character
# is entirely established in the first half minute, and reading all of it for
# thousands of files would dominate the runtime for nothing. The TRUE duration
# is still recorded from the header.
MAX_ANALYSIS_S = 30.0

# Frame size for the spectral work. 2048 at 48k is ~43ms -- long enough to
# resolve low frequencies, short enough to see an attack.
FRAME = 2048
HOP = 1024

FIELDS = [
    "path", "filename", "folder", "format", "size_mb",
    "duration_sec", "samplerate", "channels",
    "peak", "rms_db", "spectral_centroid_hz", "attack_ms", "decay_sec",
    "is_oneshot", "crest_factor", "low_energy_ratio", "high_energy_ratio",
    "bwf_description", "bwf_originator", "ixml_description",
]


# --- embedded metadata -----------------------------------------------------

def read_wav_metadata(path):
    """Pull BWF `bext` and iXML text straight out of the RIFF header.

    Parsed by hand rather than with another dependency: it is a walk over
    chunk headers, and these bundles carry real descriptions in here that the
    filename sometimes lacks.

    Reads only the header region, never the audio.
    """
    out = {"bwf_description": "", "bwf_originator": "", "ixml_description": ""}
    try:
        with open(path, "rb") as fh:
            head = fh.read(12)
            if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
                return out
            while True:
                hdr = fh.read(8)
                if len(hdr) < 8:
                    break
                cid = hdr[:4]
                size = struct.unpack("<I", hdr[4:8])[0]

                if cid == b"bext":
                    # Description is the first 256 bytes, originator the next
                    # 32. Both are null-padded ASCII.
                    body = fh.read(min(size, 604))
                    out["bwf_description"] = _clean(body[0:256])
                    out["bwf_originator"] = _clean(body[256:288])
                    remaining = size - len(body)
                    if remaining > 0:
                        fh.seek(remaining + (size & 1), os.SEEK_CUR)
                    elif size & 1:
                        fh.seek(1, os.SEEK_CUR)
                elif cid in (b"iXML", b"IXML"):
                    body = fh.read(size + (size & 1))
                    out["ixml_description"] = _ixml_text(body[:size])
                elif cid == b"data":
                    # Everything interesting precedes the audio; stop rather
                    # than seeking through hundreds of megabytes.
                    break
                else:
                    fh.seek(size + (size & 1), os.SEEK_CUR)
    except OSError:
        pass
    return out


def _clean(raw: bytes) -> str:
    text = raw.split(b"\x00", 1)[0].decode("utf-8", "replace")
    return " ".join(text.split())


def _ixml_text(raw: bytes) -> str:
    """The useful free text out of an iXML blob, without an XML parser.

    Soundminer and friends put the description in one of a handful of tags;
    take the first that has content.
    """
    try:
        text = raw.decode("utf-8", "replace")
    except Exception:                                # noqa: BLE001
        return ""
    for tag in ("DESCRIPTION", "NOTE", "PROJECT", "SCENE"):
        opening, closing = "<%s>" % tag, "</%s>" % tag
        i = text.find(opening)
        if i < 0:
            continue
        j = text.find(closing, i)
        if j < 0:
            continue
        value = " ".join(text[i + len(opening):j].split())
        if value:
            return value
    return ""


# --- features --------------------------------------------------------------

def analyse(path):
    """Read (a bounded amount of) the audio and describe it."""
    with AudioFile(str(path)) as f:
        samplerate = float(f.samplerate)
        channels = int(f.num_channels)
        total_frames = int(f.frames)
        duration = total_frames / samplerate if samplerate else 0.0

        want = int(min(total_frames, MAX_ANALYSIS_S * samplerate))
        # Read in blocks so a long file never lands in memory whole.
        blocks = []
        remaining = want
        while remaining > 0:
            block = f.read(min(remaining, 1 << 20))
            if block.shape[-1] == 0:
                break
            blocks.append(block)
            remaining -= block.shape[-1]

    if not blocks:
        raise ValueError("no audio frames could be read")

    audio = np.concatenate(blocks, axis=1) if len(blocks) > 1 else blocks[0]
    # Mono for analysis. Every feature here is about character, not imaging.
    mono = audio.mean(axis=0).astype(np.float64, copy=False)
    if mono.size == 0:
        raise ValueError("empty after downmix")

    peak = float(np.max(np.abs(mono)))
    rms = float(np.sqrt(np.mean(mono * mono)))
    rms_db = 20.0 * np.log10(rms) if rms > 1e-12 else -120.0
    crest = (peak / rms) if rms > 1e-12 else 0.0

    # --- envelope, for attack and decay ---
    # A short-window RMS envelope, which is far steadier than the raw samples
    # for finding where the sound actually peaks and how it falls away.
    win = max(1, int(0.005 * samplerate))            # 5 ms
    usable = (mono.size // win) * win
    env = np.sqrt((mono[:usable].reshape(-1, win) ** 2).mean(axis=1)) if usable else np.array([rms])
    env_peak_i = int(np.argmax(env)) if env.size else 0
    env_peak = float(env[env_peak_i]) if env.size else 0.0

    attack_ms = env_peak_i * win / samplerate * 1000.0

    # Decay: from the peak, how long until the envelope is 1/1000 of it
    # (-60 dB). Falls back to the remaining length when it never gets there,
    # which is itself the signal that this is a sustained sound.
    decay_sec = 0.0
    if env_peak > 0 and env.size > env_peak_i + 1:
        tail = env[env_peak_i:]
        below = np.nonzero(tail < env_peak * 0.001)[0]
        decay_frames = int(below[0]) if below.size else int(tail.size)
        decay_sec = decay_frames * win / samplerate

    # --- spectrum ---
    centroid, low_ratio, high_ratio = _spectrum(mono, samplerate)

    # --- the one-shot heuristic ---
    #
    # Deliberately conservative and explainable, not clever: short, with the
    # energy arriving early and the tail dying away. It is a filter for a
    # shortlist, and a false negative just means one more file to skim past.
    is_oneshot = bool(
        duration <= 6.0
        and attack_ms <= 400.0
        and crest >= 3.0
        and (decay_sec <= 5.0)
        and peak > 0.01
    )

    return {
        "duration_sec": round(duration, 3),
        "samplerate": int(samplerate),
        "channels": channels,
        "peak": round(peak, 4),
        "rms_db": round(rms_db, 2),
        "spectral_centroid_hz": round(centroid, 1),
        "attack_ms": round(attack_ms, 1),
        "decay_sec": round(decay_sec, 3),
        "is_oneshot": is_oneshot,
        "crest_factor": round(crest, 2),
        "low_energy_ratio": round(low_ratio, 4),
        "high_energy_ratio": round(high_ratio, 4),
    }


def _spectrum(mono, samplerate):
    """Average spectral centroid, and the share of energy low and high.

    Framed and averaged rather than one FFT over the whole file: a single
    transform of a long file smears a bright transient into a dull average and
    reports something true of no moment in it.
    """
    if mono.size < FRAME:
        padded = np.zeros(FRAME, dtype=np.float64)
        padded[:mono.size] = mono
        frames = padded[None, :]
    else:
        count = 1 + (mono.size - FRAME) // HOP
        # Cap the number of frames analysed; a 30s file at hop 1024 is ~1400
        # frames, which is plenty, and this keeps the cost flat.
        count = min(count, 2000)
        idx = np.arange(FRAME)[None, :] + HOP * np.arange(count)[:, None]
        frames = mono[idx]

    window = np.hanning(FRAME)
    spec = np.abs(np.fft.rfft(frames * window, axis=1))
    freqs = np.fft.rfftfreq(FRAME, d=1.0 / samplerate)

    power = spec ** 2
    total = power.sum(axis=1)
    live = total > 1e-20
    if not np.any(live):
        return 0.0, 0.0, 0.0

    power = power[live]
    total = total[live]
    centroid = float(np.mean((power * freqs[None, :]).sum(axis=1) / total))

    low = float(np.mean(power[:, freqs < 250.0].sum(axis=1) / total))
    high = float(np.mean(power[:, freqs > 4000.0].sum(axis=1) / total))
    return centroid, low, high


# --- walking ---------------------------------------------------------------

def find_audio(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            if name.lower().endswith(AUDIO_EXTS) and not name.startswith("._"):
                yield os.path.join(dirpath, name)


def human(seconds):
    seconds = int(seconds)
    if seconds < 90:
        return "%ds" % seconds
    if seconds < 5400:
        return "%dm %02ds" % (seconds // 60, seconds % 60)
    return "%dh %02dm" % (seconds // 3600, (seconds % 3600) // 60)


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=os.path.join(here, "soundeffects"))
    ap.add_argument("--out", default=None, help="default: <root>/sfx_catalog.csv")
    ap.add_argument("--limit", type=int, default=0, help="stop after N new files")
    ap.add_argument("--force", action="store_true",
                    help="re-analyse files already in the CSV")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print("no such directory: %s" % root, file=sys.stderr)
        return 2

    out_path = args.out or os.path.join(root, "sfx_catalog.csv")
    err_path = os.path.join(root, "catalog_errors.log")

    # Resume: anything already catalogued is skipped unless --force. These
    # runs take a long time and should survive being interrupted.
    done = set()
    if os.path.isfile(out_path) and not args.force:
        try:
            with open(out_path, newline="", encoding="utf-8") as fh:
                done = {row["path"] for row in csv.DictReader(fh) if row.get("path")}
        except Exception:                            # noqa: BLE001
            done = set()
    if done:
        print("resuming: %d files already catalogued" % len(done))

    print("scanning %s ..." % root)
    all_files = list(find_audio(root))
    todo = [p for p in all_files
            if os.path.relpath(p, root).replace("\\", "/") not in done]
    if args.limit:
        todo = todo[:args.limit]

    print("%d audio files found, %d to analyse" % (len(all_files), len(todo)))
    if not todo:
        print("nothing to do")
        return 0

    exists = os.path.isfile(out_path) and done and not args.force
    fh_out = open(out_path, "a" if exists else "w", newline="", encoding="utf-8")
    writer = csv.DictWriter(fh_out, fieldnames=FIELDS)
    if not exists:
        writer.writeheader()
    fh_err = open(err_path, "a", encoding="utf-8")

    started = time.time()
    ok = failed = 0
    total_duration = 0.0
    per_folder = {}
    oneshots = 0

    for n, path in enumerate(todo, 1):
        rel = os.path.relpath(path, root).replace("\\", "/")
        try:
            row = analyse(path)
            meta = (read_wav_metadata(path)
                    if path.lower().endswith((".wav", ".wave"))
                    else {"bwf_description": "", "bwf_originator": "",
                          "ixml_description": ""})
            row.update(meta)
            row["path"] = rel
            row["filename"] = os.path.splitext(os.path.basename(path))[0]
            row["folder"] = os.path.basename(os.path.dirname(path))
            row["format"] = os.path.splitext(path)[1].lstrip(".").lower()
            row["size_mb"] = round(os.path.getsize(path) / 1048576.0, 3)
            writer.writerow(row)
            ok += 1
            total_duration += row["duration_sec"]
            per_folder[row["folder"]] = per_folder.get(row["folder"], 0) + 1
            oneshots += bool(row["is_oneshot"])
        except Exception as exc:                     # noqa: BLE001
            failed += 1
            fh_err.write("%s\n    %s: %s\n" % (rel, type(exc).__name__, exc))
            fh_err.write("".join("    " + l for l in
                                 traceback.format_exc(limit=2).splitlines(True)))
            fh_err.write("\n")

        if n % 25 == 0 or n == len(todo):
            elapsed = time.time() - started
            rate = n / elapsed if elapsed else 0.0
            left = (len(todo) - n) / rate if rate else 0.0
            fh_out.flush()
            print("  %6d/%d  %5.1f files/s  elapsed %s  eta %s"
                  % (n, len(todo), rate, human(elapsed), human(left)),
                  end="\r", flush=True)

    print()
    fh_out.close()
    fh_err.close()

    print()
    print("catalogued %d files, %d failed" % (ok, failed))
    print("total audio: %s" % human(total_duration))
    print("flagged one-shot: %d (%.0f%%)"
          % (oneshots, 100.0 * oneshots / ok if ok else 0))
    print("csv: %s" % out_path)
    if failed:
        print("errors: %s" % err_path)

    if per_folder:
        print()
        print("by folder (top 15 of %d):" % len(per_folder))
        for folder, count in sorted(per_folder.items(),
                                    key=lambda kv: -kv[1])[:15]:
            print("  %6d  %s" % (count, folder))
    return 0


if __name__ == "__main__":
    sys.exit(main())
