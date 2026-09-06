#!/usr/bin/env python3
"""
Entity Voice — TIMING SPREAD  (entity_timing.py)

Third script. entity_variants.py explored size and space. entity_variants2.py
explored voice count and intervals. Neither sounded wild, and here's why:

    Every delay in those scripts was 13-52ms. Below roughly 30ms your ear
    FUSES simultaneous sounds into one — the precedence effect. So the
    "voices" were never heard as separate voices. They were heard as one
    voice with an odd timbre. That's why all the presets sounded alike:
    the interval stack was doing all the audible work.

This script varies ONE thing: how far apart the voices sit in time.
Everything else is frozen so the comparison is clean.

FROZEN STRUCTURE (same in every preset)
    3 near-unison voices + fifth below + octave below
    formant -5, sub 0.32, no upper intervals, near-dry
    (Your consistent preference has been the darker/heavier direction —
     LEGION over SWARM both times — so no upper intervals here.)

WHAT VARIES
    The spread of the delay offsets, from 40ms to 260ms, plus two versions
    where the timing DRIFTS across the line instead of sitting fixed.

WHAT TO LISTEN FOR
    Two things, and they fight each other:
      1. Separation — can you hear voices arriving at different moments?
      2. Intelligibility — can you still make out the word endings?
    Somewhere in this sweep is the point where 1 arrives and 2 leaves.
    That crossover is the answer. It's probably not the widest one.

SETUP
    pip install pedalboard numpy

USAGE
    python entity_timing.py                  # all presets
    python entity_timing.py --preset WIDE
    python entity_timing.py --list
    python entity_timing.py path/to/raw.wav
    python entity_timing.py --formant -4     # override formant on all

Output: <original>__T_<PRESET>.mp3
"""

import sys
from pathlib import Path

import numpy as np
import pedalboard
from pedalboard import (Compressor, Delay, Distortion, HighpassFilter,
                        LowpassFilter, Pedalboard, PitchShift, Reverb)
from pedalboard.io import AudioFile

CANDIDATES = [
    Path("audio/entity/_test/audition__raw.wav"),
    Path("audio/entity/_test/audition__raw.mp3"),
    Path("audio/entity/_test/system_shutdown_01__raw.wav"),
    Path("audio/entity/_test/system_shutdown_01__raw.mp3"),
]

# ── Frozen across every preset ──
FORMANT = -5.0
INTERVALS = [(-7, 0.20), (-12, 0.14)]    # fifth below, octave below
SUB = 0.32
GRIT = 0.05
SPACE = 0.05
SPACE_DARK = 2200

# Cent offsets for the three near-unison voices. Held constant — only their
# TIMING changes between presets.
CENTS = [17, -14, 10]
MIXES = [0.45, 0.42, 0.34]


def P(desc, delays_ms, cents=None, mixes=None, drift=None):
    return dict(desc=desc, delays=list(delays_ms),
                cents=list(cents or CENTS[:len(delays_ms)]),
                mixes=list(mixes or MIXES[:len(delays_ms)]),
                drift=drift)


# ─────────────────────────────────────────────────────────────────────────────
# PRESETS — only the timing changes
# ─────────────────────────────────────────────────────────────────────────────
PRESETS = {
    "FUSED": P("40ms spread. Below the fusion threshold — this is roughly what you "
               "already heard. Included as the control so the difference is obvious.",
               [0, 22, 40]),

    "EDGE": P("70ms spread. Right at the boundary where the ear starts resolving "
              "separate entries. Should be the first one that sounds different.",
              [0, 38, 70]),

    "SEPARATE": P("110ms spread. Voices should be clearly arriving at different "
                  "moments now. Check the consonants carefully here.",
                  [0, 58, 110]),

    "WIDE": P("170ms spread. Obviously ragged entries. Probably past the point "
              "where diction survives — but you need to hear where that line is.",
              [0, 92, 170]),

    "SCATTER": P("260ms spread. Deliberately too far. Words will smear. This is the "
                 "ceiling marker, not a candidate.",
                 [0, 140, 260]),

    # Fewer voices, bigger gaps — testing whether the ear prefers TWO resolvable
    # voices over three semi-resolvable ones.
    "TWO_WIDE": P("Only TWO voices, 150ms apart. Tests whether fewer voices your ear "
                  "can actually resolve beats more voices it can't. Might well win.",
                  [0, 150], cents=[15, -13], mixes=[0.50, 0.46]),

    "TWO_VERY_WIDE": P("Two voices, 240ms apart. Almost a call-and-response with "
                       "itself. Strange, and surprisingly intelligible for the width.",
                       [0, 240], cents=[15, -13], mixes=[0.50, 0.44]),

    # Drifting — timing varies ACROSS the line rather than sitting fixed.
    "DRIFT_SLOW": P("110ms base, but each voice's timing DRIFTS across the line. "
                    "Voices pull apart and converge unpredictably. Much more "
                    "unsettling than fixed offsets.",
                    [0, 58, 110], drift=0.04),

    "DRIFT_HARD": P("170ms base with heavy drift. The most genuinely wrong-sounding "
                    "thing in this set. Likely unusable, but tells you what drift buys.",
                    [0, 92, 170], drift=0.09),
}
# ─────────────────────────────────────────────────────────────────────────────


def shift_formants(audio, rate, semitones):
    if not semitones:
        return audio
    down = pedalboard.time_stretch(audio, rate, 1.0, semitones,
                                   preserve_formants=False)
    return pedalboard.time_stretch(down, rate, 1.0, -semitones,
                                   preserve_formants=True)


def drift_voice(audio, rate, amount, seed):
    """Vary this voice's speed slowly across the line so its timing wanders.

    time_stretch accepts an array for stretch_factor, so the offset relative
    to the other voices changes continuously instead of sitting fixed.
    """
    if not amount:
        return audio
    n = audio.shape[-1]
    rng = np.random.default_rng(seed)
    # A few control points, smoothly interpolated — slow wander, not warble.
    pts = 1.0 + rng.uniform(-amount, amount, 6)
    curve = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(pts)), pts)
    out = pedalboard.time_stretch(audio, rate, curve.astype(np.float64),
                                  0.0, preserve_formants=True)
    # Length changes with drift — trim or pad back to the original.
    if out.shape[-1] > n:
        out = out[:, :n]
    elif out.shape[-1] < n:
        out = np.pad(out, ((0, 0), (0, n - out.shape[-1])))
    return out


def delay_samples(audio, ms, rate):
    """Shift a voice later in time by padding the front, keeping length."""
    n_shift = int(rate * ms / 1000.0)
    if n_shift <= 0:
        return audio
    padded = np.pad(audio, ((0, 0), (n_shift, 0)))
    return padded[:, :audio.shape[-1]]


def apply_preset(audio, rate, p, formant):
    dry = shift_formants(audio.astype(np.float32), rate, formant)
    out = dry.copy()

    if GRIT > 0:
        gritted = Pedalboard([
            Distortion(drive_db=GRIT * 60),
            HighpassFilter(cutoff_frequency_hz=90),
        ])(dry, rate)
        out = out * (1 - GRIT) + gritted * GRIT

    # The voices — detuned, delayed, optionally drifting
    for i, (ms, cents, mix) in enumerate(zip(p["delays"], p["cents"], p["mixes"])):
        if mix <= 0:
            continue
        v = Pedalboard([PitchShift(semitones=cents / 100.0)])(dry, rate)
        if p["drift"]:
            v = drift_voice(v, rate, p["drift"], seed=1000 + i)
        v = delay_samples(v, ms, rate)
        out = out + v * mix

    # Fifth below, octave below
    for semis, mix in INTERVALS:
        out = out + Pedalboard([PitchShift(semitones=semis)])(dry, rate) * mix

    if SUB > 0:
        sub = Pedalboard([
            PitchShift(semitones=-12),
            LowpassFilter(cutoff_frequency_hz=320),
        ])(dry, rate)
        out = out + sub * SUB

    if SPACE > 0:
        wet = Pedalboard([
            Reverb(room_size=0.35, damping=0.6, wet_level=1.0, dry_level=0.0, width=0.7),
            LowpassFilter(cutoff_frequency_hz=SPACE_DARK),
        ])(out.astype(np.float32), rate)
        out = out * (1 - SPACE) + wet * SPACE

    out = Pedalboard([Compressor(threshold_db=-18, ratio=2.5)])(out.astype(np.float32), rate)
    peak = float(np.max(np.abs(out)))
    if peak > 0:
        out = out / peak * 0.89
    return out.astype(np.float32)


def main():
    argv = sys.argv[1:]

    known = {"--list", "--preset", "--formant"}
    unknown = [a for a in argv if a.startswith("--") and a not in known]
    if unknown:
        sys.exit(f"Unknown option(s): {' '.join(unknown)}\nKnown: {' '.join(sorted(known))}")

    if "--list" in argv:
        print()
        for name, p in PRESETS.items():
            spread = max(p["delays"]) - min(p["delays"])
            d = f", drift {p['drift']}" if p["drift"] else ""
            print(f"  {name:<15} {len(p['delays'])} voices, {spread}ms spread{d}")
            print(f"      {p['desc']}\n")
        return

    formant = FORMANT
    if "--formant" in argv:
        i = argv.index("--formant")
        formant = float(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]

    only = None
    if "--preset" in argv:
        i = argv.index("--preset")
        only = argv[i + 1].upper()
        argv = argv[:i] + argv[i + 2:]
        if only not in PRESETS:
            sys.exit(f"No preset '{only}'. Use --list.")

    paths = [a for a in argv if not a.startswith("--")]
    raw = Path(paths[0]) if paths else next(
        (c for c in CANDIDATES if c.exists()), CANDIDATES[0])

    if not raw.exists():
        sys.exit(f"Can't find a raw file (looked for {CANDIDATES[0]})\n"
                 f"Run:  python entity_tts_test.py --audition")

    with AudioFile(str(raw)) as f:
        audio = f.read(f.frames)
        rate = f.samplerate

    stem = raw.stem.replace("__raw", "")
    print(f"\n  source : {raw}   ({audio.shape[-1] / rate:.1f}s)")
    print(f"  frozen : formant {formant}, 5th+8ve below, sub {SUB}, near-dry")
    print(f"  varying: delay spread only\n")

    todo = {only: PRESETS[only]} if only else PRESETS
    for name, p in todo.items():
        out = apply_preset(audio, rate, p, formant)
        dest = raw.parent / f"{stem}__T_{name}.mp3"
        with AudioFile(str(dest), "w", rate, out.shape[0]) as f:
            f.write(out)
        spread = max(p["delays"]) - min(p["delays"])
        print(f"  {name:<15} {spread:>4}ms  ->  {dest.name}")

    print("\n  Listen in file order — they're arranged narrow to wide.")
    print("  FUSED is roughly what you already heard. If EDGE doesn't sound")
    print("  noticeably different from it, the fusion theory is wrong and I need to know.")
    print("\n  You're looking for the LAST one where you can still make out")
    print("  'I am not consulted' cleanly. That's the ceiling.\n")


if __name__ == "__main__":
    main()
