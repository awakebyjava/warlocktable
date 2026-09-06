#!/usr/bin/env python3
"""Render the table's sound effects from soundeffects/table-sfx.json.

    set ELEVENLABS_API_KEY in your environment, then:

    tools/render_sfx.py --list                # what would be generated
    tools/render_sfx.py --only combat_turn    # one sound
    tools/render_sfx.py --family interface    # one family
    tools/render_sfx.py                       # everything not yet rendered
    tools/render_sfx.py --audition combat_turn --takes 3
    tools/render_sfx.py --reprocess           # rebuild finals from raws, no API

SIBLING OF voices/entity_render.py, and deliberately shaped like it: generate
once, keep the raw, and let --reprocess rebuild every final for free when the
recipe changes. Nothing here calls the API twice for the same sound unless you
ask it to.

WHAT IT DOES *NOT* DO
---------------------
It does not run LEGION. That recipe is a voice: formant shift, sub-harmonic,
detune, a fifth below. Applied to a wooden knock it would be nonsense.

What the stingers DO share with the voice is the room and the finish -- the
same reverb, the same darkness on the tail, the same 0.86 peak and the same
12ms fades. That is what makes a card sting and a spoken line sound like they
are happening in the same place, which is the entire reason for generating
these rather than buying a library.

FAMILY COHERENCE comes from the shared prompt skeleton in the JSON's
`_meta.aesthetic`, prepended and appended to every prompt here. Four aces
written as four freehand prompts drift apart; four aces sharing a skeleton and
one processing chain do not.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import wave
from pathlib import Path

try:
    import numpy as np
    from pedalboard import LowpassFilter, Pedalboard, Reverb
    from pedalboard.io import AudioFile
except ImportError:
    sys.exit("needs numpy and pedalboard:  python -m pip install numpy pedalboard")

try:
    import requests
except ImportError:
    requests = None

HERE = Path(__file__).resolve().parent.parent
SPEC = HERE / "soundeffects" / "table-sfx.json"

# --- the finish, shared with the voice --------------------------------------
# These four are copied deliberately from voices/entity_render.py. If that
# recipe is retuned, retune these to match and --reprocess both, or the voice
# and the stingers will drift into different rooms.
SPACE = 0.12                 # how much reverb is blended in
SPACE_DARK = 1800            # the tail is rolled off here, as the voice is
PEAK = 0.86                  # headroom; a normalised peak can overshoot on
                             # reconstruction
FADE_MS = 12                 # guarantees no click at either end
TAIL_SECONDS = 1.0           # padding so the reverb tail decays rather than
                             # being cut off mid-decay, which clicks


def load_spec():
    if not SPEC.exists():
        sys.exit("can't find %s" % SPEC)
    with open(SPEC, encoding="utf-8") as fh:
        return json.load(fh)


def build_prompt(meta, sound):
    """The skeleton plus the specific. See the JSON's `why_shared`."""
    aesthetic = meta.get("aesthetic", {})
    parts = [aesthetic.get("prefix", ""), sound["prompt"], aesthetic.get("suffix", "")]
    return " ".join(p.strip() for p in parts if p and p.strip())


# --- generation -------------------------------------------------------------

def generate(prompt, seconds, influence, api_key, out_path, fmt):
    """One API call. Writes the raw exactly as returned, and keeps it."""
    if requests is None:
        sys.exit("needs requests:  python -m pip install requests")

    body = {
        "text": prompt,
        "duration_seconds": round(float(seconds), 2),
        "prompt_influence": float(influence),
    }
    r = requests.post(
        "https://api.elevenlabs.io/v1/sound-generation",
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
        params={"output_format": fmt},
        json=body,
        timeout=180,
    )
    if r.status_code != 200:
        detail = r.text[:300].replace("\n", " ")
        raise RuntimeError("API %s: %s" % (r.status_code, detail))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(r.content)
    return len(r.content)


# --- processing -------------------------------------------------------------

def process(raw_path, out_path):
    """Raw -> the finished WAV the table plays.

    Deliberately light. The generated sound is already the sound; this only
    puts it in the same room as the voice and finishes it safely.
    """
    with AudioFile(str(raw_path)) as f:
        rate = f.samplerate
        audio = f.read(f.frames)

    if audio.shape[-1] == 0:
        raise ValueError("raw file is empty")

    # Pad so the reverb has somewhere to decay to.
    pad = int(rate * TAIL_SECONDS)
    out = np.concatenate(
        [audio, np.zeros((audio.shape[0], pad), dtype=audio.dtype)], axis=1)

    if SPACE > 0:
        wet = Pedalboard([
            Reverb(room_size=0.5, damping=0.7, wet_level=1.0,
                   dry_level=0.0, width=0.8),
            LowpassFilter(cutoff_frequency_hz=SPACE_DARK),
        ])(out.astype(np.float32), rate)
        out = out * (1 - SPACE) + wet * SPACE

    # Trim the padding back to where it actually went quiet, keeping the tail.
    mag = np.max(np.abs(out), axis=0)
    thresh = float(np.max(mag)) * 0.0015
    nz = np.nonzero(mag > thresh)[0]
    if len(nz):
        end = min(out.shape[-1], nz[-1] + int(rate * 0.08))
        out = out[:, :end]

    # FADE FIRST, THEN NORMALISE -- the opposite order to entity_render.py,
    # and deliberately so.
    #
    # The voice chain normalises then fades, which is fine for speech: its
    # loudest moment is somewhere in the middle of a word, nowhere near the
    # 12ms ramp at the start. A percussive sound is the other way round. A
    # struck knock peaks at sample zero, squarely inside the fade, so fading
    # afterwards drags the true peak down -- measured at 0.799 against a
    # target of 0.86 on the first test, which would have left every stinger
    # quietly under-levelled against the voice.
    f_len = max(1, int(rate * FADE_MS / 1000.0))
    if out.shape[-1] > 2 * f_len:
        ramp = np.linspace(0.0, 1.0, f_len, dtype=np.float32)
        out[:, :f_len] *= ramp
        out[:, -f_len:] *= ramp[::-1]

    peak = float(np.max(np.abs(out)))
    if peak > 0:
        out = out / peak * PEAK

    write_canonical_wav(out.astype(np.float32), rate, out_path)
    return out.shape[-1] / float(rate)


def write_canonical_wav(audio, rate, out_path):
    """Write with Python's `wave`, NOT via a library that may add chunks.

    THIS IS NOT FUSSINESS. The Pi runs pygame 1.9.6 on SDL 1.2, whose WAV
    loader requires `fmt ` to be the first chunk. ffmpeg-based writers insert a
    52-byte JUNK chunk ahead of it for possible RF64 promotion, and SDL then
    refuses the file with a bare "Unable to open file". All 91 Entity voice
    lines were unplayable for exactly this reason, and nothing else noticed --
    the files were valid by every other measure.

    Writing the frames ourselves produces RIFF/fmt/data and nothing else.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    mono = audio.mean(axis=0) if audio.shape[0] > 1 else audio[0]
    clipped = np.clip(mono, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")

    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(pcm.tobytes())


# --- main -------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="show what would be done")
    ap.add_argument("--only", help="one sound id")
    ap.add_argument("--family", help="one family: boon person aura scene interface system combat player")
    ap.add_argument("--force", action="store_true", help="regenerate even if it exists")
    ap.add_argument("--reprocess", action="store_true",
                    help="rebuild finals from stored raws, no API calls")
    ap.add_argument("--audition", help="generate several takes of one id to choose from")
    ap.add_argument("--takes", type=int, default=3)
    args = ap.parse_args()

    spec = load_spec()
    meta = spec["_meta"]
    eleven = meta["elevenlabs"]
    sounds = spec["sounds"]

    out_dir = HERE / "soundeffects" / eleven.get("output_dir", "audio/sfx/")
    raw_dir = HERE / "soundeffects" / eleven.get("raw_dir", "audio/sfx/_raw/")
    fmt = eleven.get("output_format", "mp3_44100_128")
    default_influence = float(eleven.get("default_prompt_influence", 0.45))

    selected = sounds
    if args.family:
        selected = [s for s in selected if s["family"] == args.family]
    if args.only:
        selected = [s for s in selected if s["id"] == args.only]
    if args.audition:
        selected = [s for s in sounds if s["id"] == args.audition]
    if not selected:
        sys.exit("nothing matched")

    if args.list:
        print("%-26s %-10s %5s  %s" % ("id", "family", "secs", "prompt"))
        for s in selected:
            done = (out_dir / ("%s.wav" % s["id"])).exists()
            print("%-26s %-10s %5.1f  %s%s"
                  % (s["id"], s["family"], s["duration_seconds"],
                     "[done] " if done else "", build_prompt(meta, s)[:96]))
        print("\n%d sounds, %.0f seconds of audio"
              % (len(selected), sum(s["duration_seconds"] for s in selected)))
        return 0

    # --reprocess never touches the network. Retuning the finish costs nothing.
    if args.reprocess:
        n = 0
        for s in selected:
            raws = sorted(raw_dir.glob("%s.*" % s["id"]))
            if not raws:
                continue
            try:
                secs = process(raws[0], out_dir / ("%s.wav" % s["id"]))
                n += 1
                print("  %-26s %.2fs" % (s["id"], secs))
            except Exception as exc:            # noqa: BLE001
                print("  %-26s FAILED: %s" % (s["id"], exc), file=sys.stderr)
        print("\nreprocessed %d (no API calls)" % n)
        return 0

    api_key = os.environ.get(eleven.get("env_var", "ELEVENLABS_API_KEY"))
    if not api_key:
        sys.exit("%s is not set." % eleven.get("env_var", "ELEVENLABS_API_KEY"))

    if args.audition:
        s = selected[0]
        prompt = build_prompt(meta, s)
        print("auditioning %s, %d takes" % (s["id"], args.takes))
        print("  %s\n" % prompt)
        for i in range(1, args.takes + 1):
            raw = raw_dir / "_audition" / ("%s_take%d.mp3" % (s["id"], i))
            try:
                generate(prompt, s["duration_seconds"],
                         s.get("prompt_influence", default_influence),
                         api_key, raw, fmt)
                final = out_dir / "_audition" / ("%s_take%d.wav" % (s["id"], i))
                secs = process(raw, final)
                print("  take %d  %.2fs  %s" % (i, secs, final))
            except Exception as exc:            # noqa: BLE001
                print("  take %d  FAILED: %s" % (i, exc), file=sys.stderr)
            time.sleep(1.0)
        print("\nListen, then copy the one you want to %s/<id>.wav" % out_dir)
        return 0

    todo = [s for s in selected
            if args.force or not (out_dir / ("%s.wav" % s["id"])).exists()]
    print("%d selected, %d to generate" % (len(selected), len(todo)))
    if not todo:
        print("nothing to do (use --force to regenerate)")
        return 0

    ok = failed = 0
    for n, s in enumerate(todo, 1):
        prompt = build_prompt(meta, s)
        influence = s.get("prompt_influence", default_influence)
        raw = raw_dir / ("%s.mp3" % s["id"])
        try:
            generate(prompt, s["duration_seconds"], influence, api_key, raw, fmt)
            secs = process(raw, out_dir / ("%s.wav" % s["id"]))
            ok += 1
            print("  %3d/%d  %-26s %.2fs" % (n, len(todo), s["id"], secs))
        except Exception as exc:                # noqa: BLE001
            failed += 1
            print("  %3d/%d  %-26s FAILED: %s"
                  % (n, len(todo), s["id"], exc), file=sys.stderr)
        # Gentle on the API; these are not urgent.
        time.sleep(1.0)

    print("\nrendered %d, failed %d" % (ok, failed))
    print("finals : %s" % out_dir)
    print("raws   : %s   (--reprocess rebuilds finals free)" % raw_dir)
    if ok:
        print("\nThese are canonical RIFF/fmt/data, so the Pi's pygame 1.9.6")
        print("will load them. Verify before shipping:")
        print("  tools/catalog_sfx.py --root soundeffects/audio/sfx")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
