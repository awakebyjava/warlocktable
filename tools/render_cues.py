#!/usr/bin/env python3
"""Generate the table's music cues from soundeffects/table-cues.json.

    tools/render_cues.py --list             # what is defined, spend nothing
    tools/render_cues.py --dry-run          # what it would call
    tools/render_cues.py                    # render everything missing
    tools/render_cues.py --only ambush combat
    tools/render_cues.py --reprocess        # rebuild finals from raws, no API
    tools/render_cues.py --force            # re-render even if the final exists

A CUE is music for what is HAPPENING -- travel, ambush, arcane -- not for
where the party is. The scene bed says forest; the cue says ambush; the GM
combines them, and never the other way round.

RAWS ARE KEPT, the same rule as the Entity's voice lines. Every API response
is written to cues/_raw/ and never deleted, so re-levelling or re-looping the
whole set later costs nothing and hits no API:

    tools/render_cues.py --reprocess

PROCESSING is deliberately the same chain fix_beds.py applies to the scene
beds, because the cues come back with exactly the faults the beds had:

  * 48000 Hz, while the mixer runs at 44100. Letting SDL convert on load is
    what produced the beds' 7.6 dB level spread -- the root cause that looked
    for all the world like a level problem.
  * the first three test cues came back 11.5 dB apart, which would be a
    volume jolt on every cue change.
  * music composes a real ending and fades out, so the raw loop seam is
    enormous. travel measured 76x.

Nothing here is destructive. Finals are written beside the raws, and a cue
that already exists is skipped unless --force.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

try:
    import requests
    from pedalboard.io import AudioFile  # noqa: F401  (fix_beds needs it too)
except ImportError:
    sys.exit("needs requests and pedalboard:\n"
             "  python -m pip install numpy requests pedalboard")

# The bed repair chain, reused rather than reimplemented: same crossfade, same
# mono-sum levelling, same phase check. If one is ever improved, both improve.
import fix_beds

DB = os.path.join(ROOT, "soundeffects", "table-cues.json")
OUT_DIR = os.path.join(ROOT, "soundeffects", "cues")
RAW_DIR = os.path.join(OUT_DIR, "_raw")
PAUSE_S = 1.0            # between calls, to stay clear of rate limits
MAX_RETRIES = 3


def load_db():
    with open(DB, encoding="utf-8") as fh:
        return json.load(fh)


def generate(cue, meta, api_key, raw_path):
    """One API call -> the raw mp3, saved and never deleted."""
    el = meta["elevenlabs"]
    body = {
        "prompt": cue["prompt"] + meta.get("prompt_suffix", ""),
        "music_length_ms": cue.get("length_ms", meta.get("default_length_ms")),
        "model_id": el.get("model_id", "music_v2"),
        "force_instrumental": el.get("force_instrumental", True),
    }
    if cue.get("seed") is not None:
        body["seed"] = cue["seed"]

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.post(el["endpoint"],
                              headers={"xi-api-key": api_key,
                                       "Content-Type": "application/json"},
                              json=body, timeout=900)
        except Exception as exc:
            if attempt == MAX_RETRIES:
                return None, "request failed: %s" % exc
            time.sleep(3 * attempt)
            continue

        if r.status_code == 200:
            os.makedirs(os.path.dirname(raw_path), exist_ok=True)
            with open(raw_path, "wb") as fh:
                fh.write(r.content)
            return len(r.content), None

        # 429 is worth waiting out. A 4xx about the prompt is not.
        if r.status_code == 429 and attempt < MAX_RETRIES:
            time.sleep(10 * attempt)
            continue
        try:
            detail = json.dumps(r.json())[:200]
        except Exception:
            detail = r.text[:200]
        return None, "HTTP %s %s" % (r.status_code, detail)
    return None, "gave up after %d attempts" % MAX_RETRIES


def process(raw_path, out_path, proc):
    """Raw -> table-ready: 44100, levelled, loop closed. No API."""
    audio = fix_beds.load(raw_path)                      # resamples to 44100
    audio, dead = fix_beds.repair_dead_channel(audio)
    audio = fix_beds.close_the_loop(audio, proc.get("crossfade_s", 4.0))
    audio, _ = fix_beds.widen_check(audio)
    audio = fix_beds.level(audio, proc.get("target_rms_db", -32.0))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    size = fix_beds.write(audio, out_path, "ogg")
    return fix_beds.measure(audio), size, dead


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="+", metavar="CUE")
    ap.add_argument("--group", help="render one group (Journey, Threat, ...)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--reprocess", action="store_true",
                    help="rebuild finals from stored raws, no API calls")
    args = ap.parse_args()

    db = load_db()
    meta, cues = db["_meta"], db["cues"]
    proc = meta.get("processing", {})
    fix_beds.RATE = proc.get("rate", 44100)

    if args.only:
        want = set(args.only)
        cues = [c for c in cues if c["name"] in want]
        missing = want - {c["name"] for c in cues}
        if missing:
            sys.exit("no such cue: %s" % ", ".join(sorted(missing)))
    if args.group:
        cues = [c for c in cues if c["group"].lower() == args.group.lower()]
        if not cues:
            sys.exit("no such group: %s" % args.group)

    if args.list:
        print("%-14s %-10s %6s  %s" % ("cue", "group", "secs", "state"))
        print("-" * 60)
        for c in cues:
            final = os.path.join(OUT_DIR, c["name"] + ".ogg")
            raw = os.path.join(RAW_DIR, c["name"] + ".mp3")
            state = ("final" if os.path.isfile(final)
                     else "raw only" if os.path.isfile(raw) else "-")
            print("%-14s %-10s %6.0f  %s"
                  % (c["name"], c["group"],
                     c.get("length_ms", meta["default_length_ms"]) / 1000.0, state))
        return 0

    api_key = None
    if not args.reprocess:
        api_key = os.environ.get(
            meta["elevenlabs"].get("env_var", "ELEVENLABS_API_KEY"))
        if not api_key and not args.dry_run:
            sys.exit("ELEVENLABS_API_KEY is not set.")

    print("%-14s %8s %9s %8s  %s" % ("cue", "secs", "rms dB", "seam", "file"))
    print("-" * 66)

    failed = []
    for cue in cues:
        name = cue["name"]
        raw = os.path.join(RAW_DIR, name + ".mp3")
        final = os.path.join(OUT_DIR, name + ".ogg")

        if os.path.isfile(final) and not (args.force or args.reprocess):
            print("%-14s (already rendered)" % name)
            continue

        if not os.path.isfile(raw) or (args.force and not args.reprocess):
            if args.reprocess:
                print("%-14s no raw to reprocess" % name)
                continue
            if args.dry_run:
                print("%-14s would generate %.0fs"
                      % (name,
                         cue.get("length_ms", meta["default_length_ms"]) / 1000.0))
                continue
            _, err = generate(cue, meta, api_key, raw)
            if err:
                print("%-14s FAILED  %s" % (name, err))
                failed.append(name)
                continue
            time.sleep(PAUSE_S)

        if args.dry_run:
            print("%-14s would process the existing raw" % name)
            continue

        m, size, dead = process(raw, final, proc)
        if dead:
            print("%-14s   channel %s was silent -- filled from the live one"
                  % ("", ",".join(str(d) for d in dead)))
        print("%-14s %8.1f %9.1f %7.2fx  %s (%.1f MB)"
              % (name, m["secs"], m["rms_db"], m["seam"],
                 os.path.basename(final), size / 1048576.0))

    if failed:
        print()
        print("%d failed: %s" % (len(failed), ", ".join(failed)))
        print("re-run just those:  tools/render_cues.py --only %s"
              % " ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
