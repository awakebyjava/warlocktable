#!/usr/bin/env python3
"""
Entity TTS — TEST SCRIPT

Renders ONE line from entity-lines.json through ElevenLabs, then runs the
post-processing chain (sub-octave weight + grit). Saves both the raw and the
processed version side by side so you can A/B them.

Purpose: dial in the voice and the effect amounts on a single file before
committing API credits to all 91 lines.

SETUP
-----
    pip install requests pedalboard numpy

    Set your API key as an environment variable:
        Windows (PowerShell):  $env:ELEVENLABS_API_KEY="sk_..."
        Mac/Linux:             export ELEVENLABS_API_KEY="sk_..."

    Then paste your voice ID into VOICE_ID below.

USAGE
-----
    python entity_tts_test.py                      # renders the default test line
    python entity_tts_test.py tarot_boon_04        # renders a specific line id
    python entity_tts_test.py --list               # show all available line ids
    python entity_tts_test.py --no-tts             # re-process existing raw file only

The --no-tts flag is the important one: once you have a raw file, you can tune
SUB_OCTAVE and GRIT and re-run repeatedly without spending a single credit.
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import requests
from pedalboard import (Compressor, Distortion, HighpassFilter, LowpassFilter,
                        Pedalboard, PitchShift)
from pedalboard.io import AudioFile

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG — edit these
# ─────────────────────────────────────────────────────────────────────────────

# "The Table"
VOICE_ID = "GggBPbdwC99XwxWA2Ca8"

LINES_JSON = Path("entity-lines.json")
OUT_DIR = Path("audio/entity/_test")

# Which line to render if none is given on the command line.
# "Finally." — the hardest line in the set. If this works, everything works.
DEFAULT_TEST_ID = "system_shutdown_01"

# A longer audition phrase for judging texture. Deliberately covers the
# hardest cases: a one-word line, a flat declarative, a compulsion line,
# an abandoned sentence, and a sustained line to hear the texture ride.
AUDITION_TEXT = (
    "Finally. "
    "Back so soon. I'd only just stopped listening. "
    "There. Your Warlock is pleased. I am not consulted. "
    "Oh, that's — hm. Fine. It's fine. "
    "I counted you. There is one more than last time."
)

# ── ElevenLabs voice settings ──
# eleven_v3 is the expressive flagship — dramatic delivery, supports inline
# audio tags. eleven_multilingual_v2 is the older stable-narration model and
# sounds noticeably flatter on this kind of character work.
MODEL_ID = "eleven_v3"

# v3 accepts stability of 0.0 (Creative), 0.5 (Natural), or 1.0 (Robust) only.
# Robust flattens inflection badly. Natural is the right default here —
# containment should come from the voice and the writing, not from strangling
# the model's expressiveness.
STABILITY = 0.5
SIMILARITY_BOOST = 0.75
STYLE = 0.0
SPEAKER_BOOST = False   # can smear transitions; leave off unless it helps

# Audio tags (v3 only) prepended to every line. Try "[bored]", "[flat]",
# "[weary]", "[deadpan]". Set to "" to disable.
GLOBAL_TAG = "[bored]"

# Lossless intermediate. Requesting raw PCM and writing WAV avoids decoding
# and re-encoding mp3 twice, which was chewing up the word-to-word transitions.
# pcm_44100 needs a Pro plan; mp3_44100_128 is what Starter allows.
REQUEST_FORMAT = "mp3_44100_128"

# ── Post-processing ──
# SUB_OCTAVE = inhuman WEIGHT. An octave-down layer mixed underneath.
#   0.00 = off, 0.15-0.20 = noticeable presence, 0.35+ = obviously monstrous.
SUB_OCTAVE = 0.18

# GRIT = ROUGHNESS. Harmonic saturation on the edges of the voice.
#   Go easy. Past ~0.10 it starts eating consonants, and this character's
#   whole delivery depends on precise diction. Short lines suffer first.
GRIT = 0.06

# Gentle compression to even out the very short lines against the long ones.
COMPRESS = True

# ─────────────────────────────────────────────────────────────────────────────


def load_lines():
    if not LINES_JSON.exists():
        sys.exit(f"Can't find {LINES_JSON}. Run this from the folder containing it.")
    with open(LINES_JSON, encoding="utf-8") as f:
        return json.load(f)


def find_line(data, line_id):
    for entry in data["lines"]:
        if entry["id"] == line_id:
            return entry
    sys.exit(f"No line with id '{line_id}'. Use --list to see available ids.")


def synthesize(text, out_path):
    """Call ElevenLabs and write a lossless WAV.

    Requests raw PCM rather than mp3 so the file we process is a first
    generation. Encoding to mp3 happens once, at the very end.
    """
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        sys.exit("ELEVENLABS_API_KEY is not set. See the SETUP notes at the top.")

    send_text = f"{GLOBAL_TAG} {text}".strip() if GLOBAL_TAG else text

    settings = {"stability": STABILITY, "similarity_boost": SIMILARITY_BOOST}
    if not MODEL_ID.startswith("eleven_v3"):
        settings["style"] = STYLE
    settings["use_speaker_boost"] = SPEAKER_BOOST

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
    resp = requests.post(
        url,
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
        json={"text": send_text, "model_id": MODEL_ID, "voice_settings": settings},
        params={"output_format": REQUEST_FORMAT},
        timeout=120,
    )
    if resp.status_code != 200:
        sys.exit(f"ElevenLabs returned {resp.status_code}:\n{resp.text[:600]}")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    if REQUEST_FORMAT.startswith("pcm_"):
        rate = int(REQUEST_FORMAT.split("_")[1])
        pcm = np.frombuffer(resp.content, dtype="<i2").astype(np.float32) / 32768.0
        with AudioFile(str(out_path), "w", rate, 1) as f:
            f.write(pcm[None, :])
        dur = len(pcm) / rate
        print(f"  raw       -> {out_path}  ({dur:.1f}s, lossless)")
    else:
        out_path.write_bytes(resp.content)
        print(f"  raw       -> {out_path}  ({len(resp.content):,} bytes)")


def process(in_path, out_path):
    """Sub-octave weight + grit + compression + normalize."""
    with AudioFile(str(in_path)) as f:
        audio = f.read(f.frames)
        rate = f.samplerate

    out = audio.copy()

    # Grit: saturate a parallel copy, blend it in. Highpass keeps the
    # distortion out of the low end where it turns to mud.
    if GRIT > 0:
        gritted = Pedalboard([
            Distortion(drive_db=GRIT * 60),
            HighpassFilter(cutoff_frequency_hz=90),
        ])(audio, rate)
        out = out * (1 - GRIT) + gritted * GRIT

    # Weight: octave-down layer, lowpassed so it adds mass without
    # smearing the consonants, mixed underneath the dry voice.
    if SUB_OCTAVE > 0:
        sub = Pedalboard([
            PitchShift(semitones=-12),
            LowpassFilter(cutoff_frequency_hz=320),
        ])(audio, rate)
        out = out + sub * SUB_OCTAVE

    if COMPRESS:
        out = Pedalboard([Compressor(threshold_db=-18, ratio=2.5)])(
            out.astype(np.float32), rate
        )

    # Normalize LAST, after compression, or the compressor pulls the peak back down.
    peak = float(np.max(np.abs(out)))
    if peak > 0:
        out = out / peak * 0.89

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with AudioFile(str(out_path), "w", rate, out.shape[0]) as f:
        f.write(out.astype(np.float32))
    print(f"  processed -> {out_path}   (sub={SUB_OCTAVE}, grit={GRIT})")


def main():
    args = [a for a in sys.argv[1:]]
    data = load_lines()

    if "--list" in args:
        for e in data["lines"]:
            print(f"  {e['id']:<34} [{e['mood']:<13}] {e['line']}")
        return

    skip_tts = "--no-tts" in args

    # --audition : render the long multi-line phrase
    # --text "…" : render arbitrary text
    custom_text = None
    custom_name = None
    if "--audition" in args:
        custom_text = AUDITION_TEXT
        custom_name = "audition"
    elif "--text" in args:
        i = args.index("--text")
        if i + 1 >= len(args):
            sys.exit('--text needs a phrase after it, in quotes.')
        custom_text = args[i + 1]
        custom_name = "custom"
        args = args[:i] + args[i + 2:]

    args = [a for a in args if not a.startswith("--")]

    KNOWN_FLAGS = {"--list", "--no-tts", "--audition", "--text"}
    unknown = [a for a in sys.argv[1:] if a.startswith("--") and a not in KNOWN_FLAGS]
    if unknown:
        sys.exit(f"Unknown option(s): {' '.join(unknown)}\n"
                 f"Known options: {' '.join(sorted(KNOWN_FLAGS))}\n"
                 f"If you expected --audition to work, you're running an old copy "
                 f"of this script. Download the current one.")

    if custom_text:
        entry = {"id": custom_name, "mood": "n/a", "mask_slip": False,
                 "line": custom_text, "delivery": None}
        line_id = custom_name
    else:
        line_id = args[0] if args else DEFAULT_TEST_ID
        entry = find_line(data, line_id)

    raw_ext   = "wav" if REQUEST_FORMAT.startswith("pcm_") else "mp3"
    raw_path  = OUT_DIR / f"{line_id}__raw.{raw_ext}"
    proc_path = OUT_DIR / f"{line_id}__processed.mp3"

    print(f"\n  id        : {entry['id']}")
    print(f"  mood      : {entry['mood']}{'  [MASK SLIP]' if entry['mask_slip'] else ''}")
    print(f"  chars     : {len(entry['line'])}")
    print(f"  line      : {entry['line']}")
    if GLOBAL_TAG:
        print(f"  tag       : {GLOBAL_TAG}")
    print(f"  model     : {MODEL_ID}  (stability {STABILITY})")
    if entry.get("delivery"):
        print(f"  delivery  : {entry['delivery']}")
    print()

    if skip_tts:
        if not raw_path.exists():
            sys.exit(f"--no-tts given but {raw_path} doesn't exist yet. Run once without it.")
        print("  (skipping TTS, re-processing existing raw file)")
    else:
        synthesize(entry["line"], raw_path)

    process(raw_path, proc_path)

    print("\n  Listen to both. Compare the raw against the processed.")
    print("  To tune the effect without spending more credits:")
    print("     edit SUB_OCTAVE / GRIT, then run with --no-tts\n")


if __name__ == "__main__":
    main()
