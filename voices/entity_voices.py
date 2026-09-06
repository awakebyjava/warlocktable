#!/usr/bin/env python3
"""
Entity Voice — MULTIPLICITY LAB

Follow-up to entity_variants.py. That script explored SIZE (formant depth)
and SPACE (reverb). This one explores VOICE COUNT and INTERVAL STRUCTURE,
because LEGION and SWARM won, and what they had in common was:

  - the shallowest formant shifts in the set (-4 and -3)
  - the least reverb (0.12 and 0.10)
  - the only two with a SECOND detuned double

Conclusion: the inhumanity is coming from MULTIPLICITY, not size. Not one
enormous thing — several things using one mouth. Formant depth and reverb
both blur fine detail, and boredom lives in fine detail. Doubling doesn't
blur, because every copy carries the same performance.

So here: formant held at -5 across the board (untested clean — HOLLOW was
at -5 but buried under the heaviest reverb in the set), reverb near zero,
and the only things that vary are how many voices and what intervals.

entity_variants.py is untouched — run either.

SETUP
-----
    pip install pedalboard numpy

USAGE
-----
    python entity_voices.py                    # all presets
    python entity_voices.py --preset FIFTHS    # just one
    python entity_voices.py --list
    python entity_voices.py path/to/raw.wav

    python entity_voices.py --formant -4       # override formant on all presets
    python entity_voices.py --formant -6

Output: <original>__V_<PRESET>.mp3 next to the input.
(The V_ prefix keeps these separate from entity_variants.py's output.)

STRUCTURE
---------
voices      List of (cents, delay_ms, mix) near-unison doubles. These are
            the multiplicity. Small cent offsets, small delays. Your ear
            can't separate them, so it hears one impossible throat.

intervals   List of (semitones, mix) pitched layers. -7 = fifth below,
            +7 = fifth above, -12 = octave below, +12 = octave above.
            Fifths sound harmonically "wrong but musical." Octaves sound
            like the same voice doubled at another size.

GAIN NOTE
---------
Layers add up. Six voices at 0.5 each will clip and then normalize down
to mush. As voice count goes up, individual mixes must come down. The
presets below are already balanced for this — if you add voices yourself,
lower the others to compensate.
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

FORMANT = -5.0          # held constant; override with --formant
SPACE = 0.05            # just enough to stop it sounding pasted on. Near-dry.
SPACE_DARK = 2200       # brighter than before — dark reverb reads as distance


def P(desc, voices, intervals=(), sub=0.28, ringmod_hz=0, ringmod_mix=0.0,
      grit=0.04, space=None):
    return dict(desc=desc, voices=list(voices), intervals=list(intervals),
                sub=sub, ringmod_hz=ringmod_hz, ringmod_mix=ringmod_mix,
                grit=grit, space=SPACE if space is None else space)


# ─────────────────────────────────────────────────────────────────────────────
# PRESETS — formant fixed at -5, reverb near zero. Only voices and intervals vary.
# ─────────────────────────────────────────────────────────────────────────────
PRESETS = {
    # Baseline: two doubles, no intervals at all. Tells you what the doubling
    # alone is worth at -5 before any harmony is stacked on top.
    "BASE": P("Two detuned doubles, no intervals. The control. Everything below "
              "adds to this — listen here first so you know what the extras buy.",
              voices=[(16, 18, 0.55), (-13, 31, 0.48)]),

    # Your actual question: both fifths at once.
    "FIFTHS": P("Fifth below AND fifth above. Harmonically wrong in both directions "
                "at once. This is the one you asked about.",
                voices=[(16, 18, 0.52), (-13, 31, 0.45)],
                intervals=[(-7, 0.20), (7, 0.13)]),

    # The octave version of the same idea, for direct A/B.
    "OCTAVES": P("Octave below AND octave above. Same voice at three sizes. "
                 "Cleaner and less dissonant than FIFTHS — compare directly.",
                 voices=[(16, 18, 0.52), (-13, 31, 0.45)],
                 intervals=[(-12, 0.22), (12, 0.11)]),

    # The two hybrids — this is how you find out which direction each interval
    # is actually contributing.
    "LOW5_HIGH8": P("Fifth below, octave above. Dark weight underneath, clean "
                    "shimmer on top.",
                    voices=[(16, 18, 0.52), (-13, 31, 0.45)],
                    intervals=[(-7, 0.20), (12, 0.11)]),

    "LOW8_HIGH5": P("Octave below, fifth above. Clean weight underneath, wrongness "
                    "on top. The inverse of LOW5_HIGH8 — one of these will win.",
                    voices=[(16, 18, 0.52), (-13, 31, 0.45)],
                    intervals=[(-12, 0.22), (7, 0.13)]),

    # More voices, no intervals. Isolates voice count as its own variable.
    "FOUR": P("Four detuned doubles, no intervals. Pure multiplicity — tests "
              "whether more voices alone gets you there without any harmony.",
              voices=[(19, 15, 0.42), (-14, 24, 0.40),
                      (11, 33, 0.36), (-22, 41, 0.32)]),

    "SIX": P("Six detuned doubles. Probably past the useful point — included so "
             "you can hear where 'many voices' turns into 'smeared chorus'.",
             voices=[(21, 13, 0.34), (-16, 21, 0.32), (13, 28, 0.30),
                     (-24, 36, 0.28), (8, 44, 0.26), (-11, 52, 0.24)],
             sub=0.24),

    # The full version of what you described.
    "CHOIR": P("Four voices plus both fifths. The densest version that still "
               "keeps the consonants. Most likely winner.",
               voices=[(19, 15, 0.40), (-14, 24, 0.38),
                       (11, 33, 0.32), (-22, 41, 0.28)],
               intervals=[(-7, 0.18), (7, 0.11)]),

    # SWARM's bright wrongness, rebuilt at -5 with more voices.
    "SWARM_PLUS": P("SWARM's recipe with more voices and a touch of ring mod. "
                    "Brighter, more skin-crawling than CHOIR.",
                    voices=[(19, 14, 0.42), (-16, 26, 0.38), (12, 35, 0.32)],
                    intervals=[(12, 0.13), (7, 0.10)],
                    ringmod_hz=71, ringmod_mix=0.08, sub=0.26),

    # LEGION's dark weight, rebuilt at -5 with more voices.
    "LEGION_PLUS": P("LEGION's recipe with more voices, shallower formant, less "
                     "reverb. Darker and heavier than CHOIR.",
                     voices=[(17, 17, 0.45), (-14, 29, 0.42), (10, 38, 0.34)],
                     intervals=[(-7, 0.22), (-12, 0.14)],
                     sub=0.34, grit=0.05),
}
# ─────────────────────────────────────────────────────────────────────────────


def shift_formants(audio, rate, semitones):
    """Lower the vocal tract without changing pitch. Same duration."""
    if not semitones:
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


def apply_preset(audio, rate, p, formant):
    dry = shift_formants(audio.astype(np.float32), rate, formant)
    out = dry.copy()

    if p["grit"] > 0:
        gritted = Pedalboard([
            Distortion(drive_db=p["grit"] * 60),
            HighpassFilter(cutoff_frequency_hz=90),
        ])(dry, rate)
        out = out * (1 - p["grit"]) + gritted * p["grit"]

    # Near-unison doubles — the multiplicity
    for cents, ms, mix in p["voices"]:
        if mix <= 0:
            continue
        chain = [PitchShift(semitones=cents / 100.0)]
        if ms > 0:
            chain.append(Delay(delay_seconds=ms / 1000.0, feedback=0.0, mix=1.0))
        out = out + Pedalboard(chain)(dry, rate) * mix

    # Pitched interval layers
    for semis, mix in p["intervals"]:
        if mix <= 0:
            continue
        out = out + Pedalboard([PitchShift(semitones=semis)])(dry, rate) * mix

    if p["sub"] > 0:
        sub = Pedalboard([
            PitchShift(semitones=-12),
            LowpassFilter(cutoff_frequency_hz=320),
        ])(dry, rate)
        out = out + sub * p["sub"]

    out = ring_mod(out, rate, p["ringmod_hz"], p["ringmod_mix"])

    if p["space"] > 0:
        wet = Pedalboard([
            Reverb(room_size=0.35, damping=0.6, wet_level=1.0, dry_level=0.0, width=0.7),
            LowpassFilter(cutoff_frequency_hz=SPACE_DARK),
        ])(out.astype(np.float32), rate)
        out = out * (1 - p["space"]) + wet * p["space"]

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
        sys.exit(f"Unknown option(s): {' '.join(unknown)}\n"
                 f"Known: {' '.join(sorted(known))}")

    if "--list" in argv:
        print()
        for name, p in PRESETS.items():
            n_v, n_i = len(p["voices"]), len(p["intervals"])
            print(f"  {name:<12} {n_v} voices, {n_i} intervals")
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
    print(f"  formant: {formant}   space: {SPACE}\n")

    todo = {only: PRESETS[only]} if only else PRESETS
    for name, p in todo.items():
        out = apply_preset(audio, rate, p, formant)
        dest = raw.parent / f"{stem}__V_{name}.mp3"
        with AudioFile(str(dest), "w", rate, out.shape[0]) as f:
            f.write(out)
        print(f"  {name:<12} {len(p['voices'])}v {len(p['intervals'])}i  ->  {dest.name}")

    print("\n  Order to listen in:")
    print("    1. BASE       — doubling alone at -5, nothing else")
    print("    2. FIFTHS vs OCTAVES  — the direct answer to your question")
    print("    3. LOW5_HIGH8 vs LOW8_HIGH5  — which direction each interval helps")
    print("    4. FOUR vs SIX  — where more voices stops helping")
    print("    5. CHOIR / SWARM_PLUS / LEGION_PLUS  — the assembled candidates\n")
    print("  If -5 is too much or too little, re-run with --formant -4 or -6.\n")


if __name__ == "__main__":
    main()
