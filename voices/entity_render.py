#!/usr/bin/env python3
"""
Entity Voice — PRODUCTION RUNNER  (entity_render.py)

Renders every line in entity-lines.json through ElevenLabs, then applies
the locked LEGION recipe. This is the real one.

QUALITY CHAIN — lossless end to end
-----------------------------------
    ElevenLabs eleven_v3, stability 0.5   (expressive model, not the
                                           older multilingual_v2)
      -> raw PCM requested, written as WAV (no mp3 decode/encode step)
      -> LEGION processing in float32
      -> WAV output                        (no lossy compression anywhere)

Audio is never lossy-compressed at any point. Set OUTPUT_FORMAT = "mp3"
if you need smaller files, but WAV for 91 short lines is only ~50MB.

RAWS ARE KEPT
-------------
Every API response is saved to audio/entity/_raw/ and never deleted.
That means re-processing later — different formant, more sub, whatever —
costs nothing and hits no API. Reprocessing is a separate mode:

    python entity_render.py --reprocess

...which rebuilds every final from the stored raws without spending a
single credit. Only render once; tune forever.

SETUP
    pip install requests pedalboard numpy
    set ELEVENLABS_API_KEY in your environment

USAGE
    python entity_render.py --dry-run      # show what it would do, spend nothing
    python entity_render.py                # render everything missing
    python entity_render.py --only tarot_boon_04
    python entity_render.py --force        # re-render even if files exist
    python entity_render.py --reprocess    # rebuild finals from stored raws, no API
    python entity_render.py --category tarot_boon

Interrupted runs resume safely — anything already rendered is skipped.
"""

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pedalboard
import requests
from pedalboard import (Compressor, Delay, Distortion, HighpassFilter,
                        LowpassFilter, Pedalboard, PitchShift, Reverb)
from pedalboard.io import AudioFile

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

VOICE_ID = "GggBPbdwC99XwxWA2Ca8"          # "The Table"
LINES_JSON = Path("entity-lines.json")

RAW_DIR = Path("audio/entity/_raw")         # never deleted — reprocess source
OUT_DIR = Path("audio/entity")              # finished lines
OUTPUT_FORMAT = "wav"                       # "wav" (lossless) or "mp3"

# ── ElevenLabs ──
MODEL_ID = "eleven_v3"       # expressive flagship. NOT eleven_multilingual_v2,
                             # which is the older stable-narration model and
                             # sounds noticeably flatter on character work.
STABILITY = 0.5              # v3 accepts 0.0 / 0.5 / 1.0 only. 1.0 flattens
                             # inflection badly; 0.5 (Natural) is right here.
SIMILARITY_BOOST = 0.75
SPEAKER_BOOST = False        # can smear word transitions
# Raw PCM needs a Pro plan. On Starter/Creator the script falls back to mp3
# automatically. Output is still WAV either way, so there's only ONE lossy
# step (the API response) instead of two — the original problem was mp3 in
# AND mp3 out, which put artifacts right on the word transitions.
REQUEST_FORMAT = "pcm_44100"      # auto-falls back to FALLBACK_FORMAT if gated
FALLBACK_FORMAT = "mp3_44100_128" # best available on Starter
GLOBAL_TAG = "[bored]"       # v3 audio tag prepended to every line. "" to disable.

PAUSE_SECONDS = 0.6          # between API calls, to stay clear of rate limits
MAX_RETRIES = 3

# ─────────────────────────────────────────────────────────────────────────────
# LEGION — the locked recipe. Reproduced exactly from entity_variants.py.
# Change these and run --reprocess to rebuild everything for free.
# ─────────────────────────────────────────────────────────────────────────────
FORMANT = -4.0               # vocal tract size, without changing pitch
DETUNE = (16, 18, 0.60)      # cents, delay ms, mix
DETUNE2 = (-13, 31, 0.50)
INTERVAL = (-7, 0.22)        # fifth below
SUB = 0.35                   # octave-down body layer
GRIT = 0.05
SPACE = 0.12
SPACE_DARK = 1800
PEAK = 0.86                  # a little headroom; mp3/DAC reconstruction can
                             # overshoot a normalized peak slightly
TAIL_SECONDS = 1.5           # silence appended before processing so the delay
                             # taps and reverb tail have room to decay instead
                             # of being cut off mid-decay (that abrupt cut is a
                             # discontinuity, and it clicks)
FADE_MS = 12                 # tiny fade at both ends, guarantees no click
# ─────────────────────────────────────────────────────────────────────────────


def load_lines():
    if not LINES_JSON.exists():
        sys.exit(f"Can't find {LINES_JSON}. Run this from the folder containing it.")
    with open(LINES_JSON, encoding="utf-8") as f:
        return json.load(f)


_active_format = None   # resolved on the first successful call


def _write_response(content, fmt, out_path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt.startswith("pcm_"):
        rate = int(fmt.split("_")[1])
        pcm = np.frombuffer(content, dtype="<i2").astype(np.float32) / 32768.0
        with AudioFile(str(out_path), "w", rate, 1) as f:
            f.write(pcm[None, :])
        return len(pcm) / rate
    # mp3 bytes — write to a temp file, then transcode once to WAV so the
    # stored raw is lossless from here on and reprocessing never re-decodes.
    tmp = out_path.with_suffix(".tmp.mp3")
    tmp.write_bytes(content)
    with AudioFile(str(tmp)) as f:
        audio = f.read(f.frames)
        rate = f.samplerate
    with AudioFile(str(out_path), "w", rate, audio.shape[0]) as f:
        f.write(audio)
    tmp.unlink(missing_ok=True)
    return audio.shape[-1] / rate


def synthesize(text, out_path):
    """Call ElevenLabs, write a WAV raw. Retries, and falls back on tier limits."""
    global _active_format
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        sys.exit("ELEVENLABS_API_KEY is not set.")

    send_text = f"{GLOBAL_TAG} {text}".strip() if GLOBAL_TAG else text
    settings = {"stability": STABILITY, "similarity_boost": SIMILARITY_BOOST,
                "use_speaker_boost": SPEAKER_BOOST}

    formats = [_active_format] if _active_format else [REQUEST_FORMAT, FALLBACK_FORMAT]
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
    last = None

    for fmt in formats:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                r = requests.post(
                    url,
                    headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                    json={"text": send_text, "model_id": MODEL_ID,
                          "voice_settings": settings},
                    params={"output_format": fmt},
                    timeout=120,
                )
                if r.status_code == 200:
                    if _active_format != fmt:
                        _active_format = fmt
                        if fmt != REQUEST_FORMAT:
                            print(f"\r  (note: {REQUEST_FORMAT} needs a higher plan — "
                                  f"using {fmt}, output still WAV)")
                    return _write_response(r.content, fmt, out_path)
                # Tier / permission gate on this format — try the next one
                if r.status_code in (401, 403, 422) and fmt != formats[-1]:
                    last = f"HTTP {r.status_code}"
                    break
                if r.status_code in (429, 500, 502, 503, 504):
                    last = f"HTTP {r.status_code}"
                    time.sleep(2 * attempt)
                    continue
                return f"ERROR HTTP {r.status_code}: {r.text[:200]}"
            except requests.RequestException as e:
                last = str(e)[:120]
                time.sleep(2 * attempt)
    return f"ERROR after retries: {last}"


def shift_formants(audio, rate, semitones):
    """Lower the vocal tract without changing pitch or duration."""
    if not semitones:
        return audio
    down = pedalboard.time_stretch(audio, rate, 1.0, semitones,
                                   preserve_formants=False)
    return pedalboard.time_stretch(down, rate, 1.0, -semitones,
                                   preserve_formants=True)


def legion(audio, rate):
    # Pad with silence FIRST. The delay taps (18ms, 31ms) and the reverb tail
    # need somewhere to decay into. Without this they're cut off at the final
    # sample, and that discontinuity is audible as a click at the end of
    # every line.
    pad = int(rate * TAIL_SECONDS)
    audio = np.pad(audio.astype(np.float32), ((0, 0), (0, pad)))

    dry = shift_formants(audio, rate, FORMANT)
    out = dry.copy()

    if GRIT > 0:
        g = Pedalboard([Distortion(drive_db=GRIT * 60),
                        HighpassFilter(cutoff_frequency_hz=90)])(dry, rate)
        out = out * (1 - GRIT) + g * GRIT

    for cents, ms, mix in (DETUNE, DETUNE2):
        chain = [PitchShift(semitones=cents / 100.0)]
        if ms:
            chain.append(Delay(delay_seconds=ms / 1000.0, feedback=0.0, mix=1.0))
        out = out + Pedalboard(chain)(dry, rate) * mix

    out = out + Pedalboard([PitchShift(semitones=INTERVAL[0])])(dry, rate) * INTERVAL[1]

    if SUB > 0:
        sub = Pedalboard([PitchShift(semitones=-12),
                          LowpassFilter(cutoff_frequency_hz=320)])(dry, rate)
        out = out + sub * SUB

    if SPACE > 0:
        wet = Pedalboard([
            Reverb(room_size=0.5, damping=0.7, wet_level=1.0, dry_level=0.0, width=0.8),
            LowpassFilter(cutoff_frequency_hz=SPACE_DARK),
        ])(out.astype(np.float32), rate)
        out = out * (1 - SPACE) + wet * SPACE

    out = Pedalboard([Compressor(threshold_db=-18, ratio=2.5)])(out.astype(np.float32), rate)

    # Trim the padding back to wherever the audio has actually decayed to
    # silence, so files aren't needlessly long, but keep the whole tail.
    mag = np.max(np.abs(out), axis=0)
    thresh = float(np.max(mag)) * 0.0015
    nz = np.nonzero(mag > thresh)[0]
    if len(nz):
        end = min(out.shape[-1], nz[-1] + int(rate * 0.08))
        out = out[:, :end]

    peak = float(np.max(np.abs(out)))
    if peak > 0:
        out = out / peak * PEAK

    # Short fade at both ends. Cheap insurance against any residual click.
    f = max(1, int(rate * FADE_MS / 1000.0))
    if out.shape[-1] > 2 * f:
        ramp = np.linspace(0.0, 1.0, f, dtype=np.float32)
        out[:, :f] *= ramp
        out[:, -f:] *= ramp[::-1]

    return out.astype(np.float32)


def process(raw_path, out_path):
    with AudioFile(str(raw_path)) as f:
        audio = f.read(f.frames)
        rate = f.samplerate
    out = legion(audio, rate)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with AudioFile(str(out_path), "w", rate, out.shape[0]) as f:
        f.write(out)
    return out.shape[-1] / rate


def main():
    argv = sys.argv[1:]
    known = {"--dry-run", "--only", "--force", "--reprocess", "--category", "--list"}
    unknown = [a for a in argv if a.startswith("--") and a not in known]
    if unknown:
        sys.exit(f"Unknown option(s): {' '.join(unknown)}\nKnown: {' '.join(sorted(known))}")

    data = load_lines()
    lines = data["lines"]

    if "--list" in argv:
        for e in lines:
            print(f"  {e['id']:<34} [{e['mood']:<13}] {e['line']}")
        return

    dry_run = "--dry-run" in argv
    force = "--force" in argv
    reprocess = "--reprocess" in argv

    only = None
    if "--only" in argv:
        i = argv.index("--only")
        only = argv[i + 1]
    category = None
    if "--category" in argv:
        i = argv.index("--category")
        category = argv[i + 1]

    if only:
        lines = [e for e in lines if e["id"] == only]
        if not lines:
            sys.exit(f"No line with id '{only}'.")
    if category:
        lines = [e for e in lines if e["trigger_category"] == category]
        if not lines:
            sys.exit(f"No lines in category '{category}'.")

    print(f"\n  model   : {MODEL_ID}  (stability {STABILITY})")
    print(f"  request : {REQUEST_FORMAT}, falling back to {FALLBACK_FORMAT} if gated")
    print(f"  recipe  : LEGION  formant {FORMANT}, sub {SUB}, space {SPACE}")
    print(f"  output  : {OUT_DIR}/  as .{OUTPUT_FORMAT}")
    print(f"  raws    : {RAW_DIR}/  (kept — --reprocess rebuilds free)")
    print(f"  lines   : {len(lines)}")
    if GLOBAL_TAG:
        print(f"  tag     : {GLOBAL_TAG}")
    if reprocess:
        print(f"  MODE    : reprocess only, no API calls")
    if dry_run:
        print(f"  MODE    : dry run, nothing written")
    print()

    rendered = skipped = failed = 0
    errors = []
    t0 = time.time()

    for idx, e in enumerate(lines, 1):
        lid = e["id"]
        raw_path = RAW_DIR / f"{lid}.wav"
        out_path = OUT_DIR / f"{lid}.{OUTPUT_FORMAT}"

        if reprocess:
            if not raw_path.exists():
                print(f"  [{idx}/{len(lines)}] {lid:<32} no raw, skipped")
                skipped += 1
                continue
            if dry_run:
                print(f"  [{idx}/{len(lines)}] {lid:<32} would reprocess")
                continue
            dur = process(raw_path, out_path)
            print(f"  [{idx}/{len(lines)}] {lid:<32} {dur:5.2f}s  reprocessed")
            rendered += 1
            continue

        if out_path.exists() and raw_path.exists() and not force:
            print(f"  [{idx}/{len(lines)}] {lid:<32} exists, skipped")
            skipped += 1
            continue

        if dry_run:
            print(f"  [{idx}/{len(lines)}] {lid:<32} would render  ({len(e['line'])} chars)")
            continue

        if not raw_path.exists() or force:
            print(f"  [{idx}/{len(lines)}] {lid:<32} ...", end="", flush=True)
            result = synthesize(e["line"], raw_path)
            if isinstance(result, str):
                print(f"\r  [{idx}/{len(lines)}] {lid:<32} {result}")
                errors.append((lid, result))
                failed += 1
                time.sleep(PAUSE_SECONDS)
                continue
            time.sleep(PAUSE_SECONDS)

        dur = process(raw_path, out_path)
        print(f"\r  [{idx}/{len(lines)}] {lid:<32} {dur:5.2f}s  done          ")
        rendered += 1

    elapsed = time.time() - t0
    print(f"\n  rendered {rendered}   skipped {skipped}   failed {failed}"
          f"   ({elapsed:.0f}s)")
    if errors:
        print("\n  Failures — re-run to retry just these:")
        for lid, msg in errors:
            print(f"    {lid}: {msg}")
    if not dry_run and rendered:
        print(f"\n  Finals in {OUT_DIR}/, raws in {RAW_DIR}/")
        print(f"  To retune LEGION later: edit the recipe block, then --reprocess.")
        print(f"  That costs no credits — the raws are already on disk.\n")


if __name__ == "__main__":
    main()
