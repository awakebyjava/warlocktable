#!/usr/bin/env python3
"""
Entity Voice — VARIANT LAB  (v2)

Renders one raw ElevenLabs file through several radically different
post-processing recipes. No API calls — free and instant.

WHAT CHANGED FROM v1
--------------------
1. FORMANT SHIFTING is now the primary control. Pitch is how high a voice
   is; formants are the resonances of the throat and mouth producing it.
   Lower the formants WITHOUT changing pitch and the listener hears a body
   physically too large to be human. This is the single biggest difference
   between "gravelly man" and "not a person." Tune this first.

2. The presets now actually diverge. v1's values all sat in a narrow band,
   so everything sounded like the same idea. These span subtle to absurd.

SETUP
-----
    pip install pedalboard numpy

USAGE
-----
    python entity_variants.py                     # default raw file, all presets
    python entity_variants.py path/to/file__raw.mp3
    python entity_variants.py --preset PIT        # just one
    python entity_variants.py --list

Output: <original>__<PRESET>.mp3 next to the input.

THE CONTROLS
------------
formant     Semitones to lower the vocal tract WITHOUT changing pitch.
            THE SIZE DIAL. 0 = human. -3 = large. -6 = enormous.
            -9 = architectural. Past -10 it stops being a voice.

pitch       Actual pitch change in semitones. Small negative values
            (-1 to -2) add menace. Large ones sound like a slowed tape.

detune      Copy shifted a few cents off and delayed. Reads as one throat
            producing something a throat shouldn't. cents / ms / mix.

detune2     A second double at a different offset. Two of these and it
            stops sounding like a person at all.

interval    Extra pitched layer in semitones (-12 octave down, -7 fifth
            down, +12 octave up). Humans don't make two pitches at once.

sub         Octave-down layer, lowpassed. Body and scale.

ringmod     Sine-carrier multiplication. Metallic growl. Low = wrong,
            high = machine.

grit        Saturation. Eats consonants — this character needs diction.

space       Dark reverb. Makes it emanate from inside something.
"""

import sys
from pathlib import Path

import numpy as np
import pedalboard
from pedalboard import (Compressor, Delay, Distortion, HighpassFilter,
                        LowpassFilter, Pedalboard, PitchShift, Reverb)
from pedalboard.io import AudioFile

# Raw files are WAV now (lossless intermediate). mp3 kept as fallback.
CANDIDATES = [
    Path("audio/entity/_test/audition__raw.wav"),
    Path("audio/entity/_test/audition__raw.mp3"),
    Path("audio/entity/_test/system_shutdown_01__raw.wav"),
    Path("audio/entity/_test/system_shutdown_01__raw.mp3"),
]


D = dict(formant=0, pitch=0, detune_cents=0, detune_ms=0, detune_mix=0.0,
         detune2_cents=0, detune2_ms=0, detune2_mix=0.0,
         interval=None, interval_mix=0.0, sub=0.0,
         ringmod_hz=0, ringmod_mix=0.0, grit=0.0, space=0.0, space_dark=1600)


def P(desc, **kw):
    p = dict(D)
    p.update(kw)
    p["desc"] = desc
    return p


# ─────────────────────────────────────────────────────────────────────────────
# PRESETS — deliberately spread far apart. Tune the numbers and re-run.
# ─────────────────────────────────────────────────────────────────────────────
PRESETS = {
    "SIZE": P("Formant shift only, nothing else. Isolates the 'too large to be human' "
              "effect. Listen FIRST — it tells you how much formants alone do.",
              formant=-6, sub=0.30),

    "VAST": P("Enormous and calm. Deep formants, real weight, dark space. Bored demon "
              "in a large room. Minimal texture — the size does the work.",
              formant=-8, pitch=-1, sub=0.45, detune_cents=8, detune_ms=20,
              detune_mix=0.30, space=0.26, space_dark=1200, grit=0.03),

    "LEGION": P("Many things speaking as one. Two detuned doubles plus a fifth below. "
                "The Goetia 'forty legions' reading.",
                formant=-4, detune_cents=16, detune_ms=18, detune_mix=0.60,
                detune2_cents=-13, detune2_ms=31, detune2_mix=0.50,
                interval=-7, interval_mix=0.22, sub=0.35, space=0.12, grit=0.05),

    "PIT": P("Actively hostile. Heavy ring mod and saturation over deep formants. "
             "Most obviously demonic — check whether the diction survives.",
             formant=-6, pitch=-1.5, sub=0.40, ringmod_hz=54, ringmod_mix=0.28,
             grit=0.14, detune_cents=12, detune_ms=16, detune_mix=0.35,
             space=0.14, space_dark=1300),

    "HOLLOW": P("Comes from inside the table rather than out of a speaker. Big dark "
                "cavern, low formants, almost no texture.",
                formant=-5, sub=0.38, detune_cents=7, detune_ms=25, detune_mix=0.25,
                space=0.42, space_dark=900, grit=0.02),

    "SWARM": P("Wrong in a quiet way. Three near-unison layers and a faint octave up. "
               "Sounds like several things agreeing.",
               formant=-3, detune_cents=11, detune_ms=14, detune_mix=0.55,
               detune2_cents=-19, detune2_ms=27, detune2_mix=0.45,
               interval=12, interval_mix=0.12, sub=0.25,
               ringmod_hz=71, ringmod_mix=0.09, space=0.10),

    "RESTRAINED": P("Passes as human for a beat, then doesn't. Subtle formant drop, "
                    "little else. If the writing carries it, this may be enough.",
                    formant=-2.5, sub=0.20, detune_cents=9, detune_ms=17,
                    detune_mix=0.28, space=0.08, grit=0.02),

    "ABYSS": P("Deliberately too far. Not usable — it shows the ceiling so you know "
               "which direction to back off from.",
               formant=-11, pitch=-3, sub=0.60, detune_cents=22, detune_ms=24,
               detune_mix=0.70, detune2_cents=-17, detune2_ms=38, detune2_mix=0.60,
               interval=-12, interval_mix=0.30, ringmod_hz=44, ringmod_mix=0.35,
               grit=0.20, space=0.35, space_dark=800),
}
# ─────────────────────────────────────────────────────────────────────────────


def shift_formants(audio, rate, semitones):
    """Lower the vocal tract without changing pitch.

    Two passes: drop pitch AND formants together, then raise pitch back while
    preserving formants. Net result is original pitch, lower formants, same
    duration.
    """
    if semitones == 0:
        return audio
    down = pedalboard.time_stretch(audio, rate, 1.0, semitones,
                                   preserve_formants=False)
    return pedalboard.time_stretch(down, rate, 1.0, -semitones,
                                   preserve_formants=True)


def ring_mod(audio, rate, freq, mix):
    if freq <= 0 or mix <= 0:
        return audio
    t = np.arange(audio.shape[-1]) / rate
    carrier = np.sin(2 * np.pi * freq * t).astype(np.float32)
    return audio * (1 - mix) + (audio * carrier) * mix


def apply_preset(audio, rate, p):
    # 1. Size first — everything downstream layers onto the resized voice
    dry = shift_formants(audio.astype(np.float32), rate, p["formant"])

    if p["pitch"]:
        dry = Pedalboard([PitchShift(semitones=p["pitch"])])(dry, rate)

    out = dry.copy()

    # 2. Grit (parallel, highpassed so it doesn't muddy the bottom)
    if p["grit"] > 0:
        gritted = Pedalboard([
            Distortion(drive_db=p["grit"] * 60),
            HighpassFilter(cutoff_frequency_hz=90),
        ])(dry, rate)
        out = out * (1 - p["grit"]) + gritted * p["grit"]

    # 3. Detuned doubles
    for c, ms, mix in ((p["detune_cents"], p["detune_ms"], p["detune_mix"]),
                       (p["detune2_cents"], p["detune2_ms"], p["detune2_mix"])):
        if mix > 0:
            chain = [PitchShift(semitones=c / 100.0)]
            if ms > 0:
                chain.append(Delay(delay_seconds=ms / 1000.0, feedback=0.0, mix=1.0))
            out = out + Pedalboard(chain)(dry, rate) * mix

    # 4. Extra pitched layer
    if p["interval"] is not None and p["interval_mix"] > 0:
        layer = Pedalboard([PitchShift(semitones=p["interval"])])(dry, rate)
        out = out + layer * p["interval_mix"]

    # 5. Sub-octave weight
    if p["sub"] > 0:
        sub = Pedalboard([
            PitchShift(semitones=-12),
            LowpassFilter(cutoff_frequency_hz=320),
        ])(dry, rate)
        out = out + sub * p["sub"]

    # 6. Ring mod
    out = ring_mod(out, rate, p["ringmod_hz"], p["ringmod_mix"])

    # 7. Dark space
    if p["space"] > 0:
        wet = Pedalboard([
            Reverb(room_size=0.62, damping=0.78, wet_level=1.0, dry_level=0.0, width=0.9),
            LowpassFilter(cutoff_frequency_hz=p["space_dark"]),
        ])(out.astype(np.float32), rate)
        out = out * (1 - p["space"]) + wet * p["space"]

    # 8. Glue, then normalize LAST
    out = Pedalboard([Compressor(threshold_db=-18, ratio=2.5)])(out.astype(np.float32), rate)
    peak = float(np.max(np.abs(out)))
    if peak > 0:
        out = out / peak * 0.89
    return out.astype(np.float32)


def main():
    args = sys.argv[1:]

    if "--list" in args:
        print()
        for name, p in PRESETS.items():
            print(f"  {name}")
            print(f"      {p['desc']}\n")
        return

    only = None
    if "--preset" in args:
        i = args.index("--preset")
        only = args[i + 1].upper()
        args = args[:i] + args[i + 2:]
        if only not in PRESETS:
            sys.exit(f"No preset '{only}'. Use --list.")

    paths = [a for a in args if not a.startswith("--")]
    if paths:
        raw = Path(paths[0])
    else:
        raw = next((c for c in CANDIDATES if c.exists()), CANDIDATES[0])

    if not raw.exists():
        sys.exit(f"Can't find a raw file (looked for {CANDIDATES[0]})\n"
                 f"Run:  python entity_tts_test.py --audition\n"
                 f"or pass a path to a raw mp3.")

    with AudioFile(str(raw)) as f:
        audio = f.read(f.frames)
        rate = f.samplerate

    stem = raw.stem.replace("__raw", "")
    print(f"\n  source: {raw}   ({audio.shape[-1] / rate:.1f}s)\n")

    todo = {only: PRESETS[only]} if only else PRESETS
    for name, p in todo.items():
        out = apply_preset(audio, rate, p)
        dest = raw.parent / f"{stem}__{name}.mp3"
        with AudioFile(str(dest), "w", rate, out.shape[0]) as f:
            f.write(out)
        print(f"  {name:<12} formant {p['formant']:>5}   ->  {dest.name}")

    print("\n  Play SIZE first — formant effect alone, nothing on top.")
    print("  Then ABYSS, which is deliberately too far. Everything else sits between.")
    print("  Tell me which is closest and what's still wrong.\n")


if __name__ == "__main__":
    main()
