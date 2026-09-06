#!/usr/bin/env python3
"""
Entity Voice — AGENCY  (entity_agency.py)

Fifth script. Fixes a real flaw in entity_echo.py.

THE BUG
-------
drift_voice() gave every voice the same number of control points at the
same positions across the line. Different random directions, but the SAME
WANDER RATE, starting at the same instant. Result: one coherent smear
breathing in and out together — not separate things with their own
intentions.

THE FIX — three independent properties per voice
------------------------------------------------
rate    How FAST this voice wanders. 3 = slow and lazy, 14 = restless.
        This is the property that was missing. Two voices wandering at
        different rates can never stay in agreement.

phase   Where in its own cycle this voice starts. Voices no longer begin
        their wander at the same moment.

amp     Independent LEVEL breathing. This voice drifts forward into
        prominence, then recedes, on its own schedule. More than anything
        else, this is what reads as separate wills rather than processing.

The dry lead voice stays locked and undrifted — it's the anchor the others
have agency relative to. Without a fixed centre, everything wandering just
sounds like tape damage.

VOICE FORMAT
------------
    (semitones, delay_ms, depth, rate, amp, mix)

    semitones  0.17 = near-unison detune, -7 fifth below, -12 octave below,
               +12 octave above
    delay_ms   when it arrives
    depth      how far its timing wanders
    rate       how fast it wanders  ← the new one
    amp        how much its level breathes (0 = steady)
    mix        base level

SETUP
    pip install pedalboard numpy

USAGE
    python entity_agency.py
    python entity_agency.py --preset SEPARATE_WILLS
    python entity_agency.py --list
    python entity_agency.py --formant -4
    python entity_agency.py --seed 7        # reroll the random wander shapes

Output: <original>__A_<PRESET>.mp3
"""

import sys
from pathlib import Path

import numpy as np
import pedalboard
from pedalboard import (Compressor, Distortion, HighpassFilter, LowpassFilter,
                        Pedalboard, PitchShift, Reverb)
from pedalboard.io import AudioFile

CANDIDATES = [
    Path("audio/entity/_test/audition__raw.wav"),
    Path("audio/entity/_test/audition__raw.mp3"),
    Path("audio/entity/_test/system_shutdown_01__raw.wav"),
    Path("audio/entity/_test/system_shutdown_01__raw.mp3"),
]

FORMANT = -5.0
SUB = 0.30
GRIT = 0.05
SPACE = 0.06
SPACE_DARK = 2200
SEED = 0


def P(desc, voices):
    return dict(desc=desc, voices=list(voices))


# ─────────────────────────────────────────────────────────────────────────────
# PRESETS.  voices = [(semitones, delay_ms, depth, rate, amp, mix), ...]
#
# Watch the RATE column — that's the new variable. Where rates differ
# between voices, they can never settle into agreement.
# ─────────────────────────────────────────────────────────────────────────────
PRESETS = {
    # Direct comparison against entity_echo.py's DISAGREE — same spread and
    # depths, but now each voice wanders at its own rate and breathes its
    # own level. This is the A/B that proves whether rate was the missing thing.
    "SEPARATE_WILLS": P(
        "Each voice wanders at a DIFFERENT RATE and breathes its own level. "
        "Compare directly against entity_echo's DISAGREE — same spread, same "
        "depths, only rate and amplitude are now independent.",
        [(0.17,   0, 0.10,  3, 0.35, 0.42),
         (-0.14, 150, 0.14,  8, 0.30, 0.38),
         (0.10,  280, 0.12, 13, 0.40, 0.34),
         (-7,     90, 0.11,  5, 0.28, 0.20),
         (-12,   220, 0.13, 11, 0.33, 0.15)]),

    # One voice barely moves, another is frantic. Maximum contrast in rate.
    "IMPATIENT": P(
        "One voice almost still, one frantic, the rest between. The widest spread "
        "of wander RATES here — some expressions are restless, others aren't.",
        [(0.17,   0, 0.06,  2, 0.20, 0.42),
         (-0.14, 160, 0.18, 16, 0.45, 0.36),
         (0.10,  290, 0.09,  4, 0.25, 0.34),
         (-7,     80, 0.16, 12, 0.40, 0.19),
         (-12,   230, 0.07,  3, 0.22, 0.15)]),

    # Amplitude breathing pushed hard — voices surface and submerge.
    "SURFACING": P(
        "Heavy independent LEVEL breathing. Voices rise into prominence and sink "
        "back on their own schedules. Timing wander is moderate — this isolates "
        "what amplitude agency alone does.",
        [(0.17,   0, 0.08,  4, 0.65, 0.44),
         (-0.14, 150, 0.09,  7, 0.70, 0.40),
         (0.10,  270, 0.08, 10, 0.60, 0.36),
         (-7,     90, 0.09,  6, 0.72, 0.22),
         (-12,   210, 0.08,  9, 0.66, 0.17)]),

    # The full build — six layers, all independent in every property.
    "PANTHEON": P(
        "Six layers — three near-unison, fifth below, octave below, octave above. "
        "Every one independent in timing, rate, and level. The dense version.",
        [(0.17,   0, 0.10,  3, 0.38, 0.38),
         (-0.14, 140, 0.15,  9, 0.32, 0.34),
         (0.10,  260, 0.12, 14, 0.42, 0.30),
         (-7,     75, 0.13,  6, 0.30, 0.18),
         (-12,   200, 0.11, 11, 0.36, 0.14),
         (12,    330, 0.14,  8, 0.44, 0.11)]),

    # Slow, heavy, deliberate — every voice lazy but out of step.
    "OLD_THINGS": P(
        "All voices wander SLOWLY but at different slow rates. Nothing is frantic. "
        "Feels ancient and out of step rather than unstable.",
        [(0.17,   0, 0.12,  2, 0.30, 0.42),
         (-0.14, 170, 0.15,  3, 0.34, 0.38),
         (0.10,  300, 0.13,  4, 0.28, 0.34),
         (-7,    100, 0.14,  2, 0.32, 0.20),
         (-12,   240, 0.16,  3, 0.30, 0.15)]),

    # Fast, restless — every voice agitated at a different fast rate.
    "RESTLESS": P(
        "Every voice wanders FAST, at different fast rates. Agitated and unstable. "
        "The opposite pole from OLD_THINGS.",
        [(0.17,   0, 0.12, 11, 0.45, 0.40),
         (-0.14, 140, 0.14, 15, 0.50, 0.36),
         (0.10,  260, 0.13, 19, 0.42, 0.32),
         (-7,     85, 0.15, 13, 0.48, 0.19),
         (-12,   210, 0.12, 17, 0.44, 0.15)]),

    # Wide and independent — the ceiling test, since ceilings keep winning.
    "SCHISM": P(
        "480ms spread with fully independent wander. Further out than anything "
        "yet. Your last two ceiling markers both won, so here's another.",
        [(0.17,   0, 0.16,  4, 0.50, 0.36),
         (-0.14, 200, 0.20, 10, 0.55, 0.34),
         (0.10,  370, 0.18, 15, 0.48, 0.30),
         (-7,    120, 0.19,  7, 0.52, 0.18),
         (-12,   290, 0.17, 12, 0.46, 0.15),
         (12,    480, 0.21,  9, 0.58, 0.12)]),
}
# ─────────────────────────────────────────────────────────────────────────────


def shift_formants(audio, rate, semitones):
    if not semitones:
        return audio
    down = pedalboard.time_stretch(audio, rate, 1.0, semitones,
                                   preserve_formants=False)
    return pedalboard.time_stretch(down, rate, 1.0, -semitones,
                                   preserve_formants=True)


def wander_curve(n, depth, rate, seed, phase):
    """A voice's own wander shape.

    `rate` is the number of control points across the line — this is what
    makes one voice lazy and another restless. `phase` offsets where in its
    own cycle it begins, so voices don't start together.
    """
    rng = np.random.default_rng(seed)
    pts = rng.uniform(-1.0, 1.0, max(2, int(rate)) + 2)
    x = np.linspace(0, 1, len(pts))
    xi = (np.linspace(0, 1, n) + phase) % 1.0
    order = np.argsort(xi)
    curve = np.empty(n)
    curve[order] = np.interp(xi[order], x, pts)
    # Smooth so it's a wander, not a warble.
    # Uses a cumsum moving average: O(n) regardless of window size.
    # (np.convolve here was O(n*k) and made long files appear to hang.)
    k = int(max(1, min(n // 4, n / (int(rate) * 8 + 1))))
    if k > 1:
        pad = k // 2
        padded = np.pad(curve, (pad, k - pad), mode="edge")
        cs = np.cumsum(np.insert(padded, 0, 0.0))
        curve = (cs[k:k + n] - cs[:n]) / k
    return curve * depth


def drift_voice(audio, rate_hz, depth, wrate, seed, phase):
    if not depth:
        return audio
    n = audio.shape[-1]
    curve = 1.0 + wander_curve(n, depth, wrate, seed, phase)
    return pedalboard.time_stretch(audio, rate_hz, curve.astype(np.float64),
                                   0.0, preserve_formants=True)


def amp_breathe(audio, amount, wrate, seed, phase):
    """Independent level breathing — this voice surfaces and recedes."""
    if not amount:
        return audio
    n = audio.shape[-1]
    curve = 1.0 + wander_curve(n, amount, max(2, wrate // 2), seed, phase)
    return audio * np.clip(curve, 0.15, 1.9).astype(np.float32)


def place(buf, voice, delay_ms, rate, mix):
    start = int(rate * delay_ms / 1000.0)
    if start >= buf.shape[-1]:
        return
    end = min(buf.shape[-1], start + voice.shape[-1])
    buf[:, start:end] += voice[:, :end - start] * mix


def apply_preset(audio, rate, p, formant, seed_base):
    dry = shift_formants(audio.astype(np.float32), rate, formant)
    n = dry.shape[-1]

    max_delay = max(v[1] for v in p["voices"])
    tail = int(rate * (max_delay / 1000.0 + 0.6))
    out = np.zeros((dry.shape[0], n + tail), dtype=np.float32)

    # Anchor: the dry voice, locked and undrifted. The others have agency
    # relative to this. Without a fixed centre it just sounds like tape damage.
    lead = dry.copy()
    if GRIT > 0:
        gritted = Pedalboard([
            Distortion(drive_db=GRIT * 60),
            HighpassFilter(cutoff_frequency_hz=90),
        ])(dry, rate)
        lead = lead * (1 - GRIT) + gritted * GRIT
    place(out, lead, 0, rate, 1.0)

    rng = np.random.default_rng(seed_base + 777)
    for i, (semis, delay_ms, depth, wrate, amp, mix) in enumerate(p["voices"]):
        if mix <= 0:
            continue
        v = Pedalboard([PitchShift(semitones=semis)])(dry, rate)
        ph_t = float(rng.uniform(0, 1))
        ph_a = float(rng.uniform(0, 1))
        v = drift_voice(v, rate, depth, wrate, seed_base + i * 31 + 3, ph_t)
        v = amp_breathe(v, amp, wrate, seed_base + i * 53 + 11, ph_a)
        place(out, v, delay_ms, rate, mix)

    if SUB > 0:
        sub = Pedalboard([
            PitchShift(semitones=-12),
            LowpassFilter(cutoff_frequency_hz=320),
        ])(dry, rate)
        place(out, sub, 0, rate, SUB)

    if SPACE > 0:
        wet = Pedalboard([
            Reverb(room_size=0.35, damping=0.6, wet_level=1.0, dry_level=0.0, width=0.7),
            LowpassFilter(cutoff_frequency_hz=SPACE_DARK),
        ])(out, rate)
        out = out * (1 - SPACE) + wet * SPACE

    out = Pedalboard([Compressor(threshold_db=-18, ratio=2.5)])(out.astype(np.float32), rate)
    peak = float(np.max(np.abs(out)))
    if peak > 0:
        out = out / peak * 0.89
    return out.astype(np.float32)


def main():
    argv = sys.argv[1:]
    known = {"--list", "--preset", "--formant", "--seed"}
    unknown = [a for a in argv if a.startswith("--") and a not in known]
    if unknown:
        sys.exit(f"Unknown option(s): {' '.join(unknown)}\nKnown: {' '.join(sorted(known))}")

    if "--list" in argv:
        print()
        for name, p in PRESETS.items():
            rates = ",".join(str(v[3]) for v in p["voices"])
            print(f"  {name:<16} {len(p['voices'])} voices, rates [{rates}]")
            print(f"      {p['desc']}\n")
        return

    formant, seed = FORMANT, SEED
    if "--formant" in argv:
        i = argv.index("--formant")
        formant = float(argv[i + 1]); argv = argv[:i] + argv[i + 2:]
    if "--seed" in argv:
        i = argv.index("--seed")
        seed = int(argv[i + 1]); argv = argv[:i] + argv[i + 2:]

    only = None
    if "--preset" in argv:
        i = argv.index("--preset")
        only = argv[i + 1].upper(); argv = argv[:i] + argv[i + 2:]
        if only not in PRESETS:
            sys.exit(f"No preset '{only}'. Use --list.")

    paths = [a for a in argv if not a.startswith("--")]
    raw = Path(paths[0]) if paths else next(
        (c for c in CANDIDATES if c.exists()), CANDIDATES[0])
    if not raw.exists():
        sys.exit(f"Can't find a raw file (looked for {CANDIDATES[0]})\n"
                 f"Run:  python entity_tts_test.py --audition")

    with AudioFile(str(raw)) as f:
        audio = f.read(f.frames); rate = f.samplerate

    stem = raw.stem.replace("__raw", "")
    print(f"\n  source : {raw}   ({audio.shape[-1]/rate:.1f}s)")
    print(f"  formant: {formant}   seed: {seed}")
    print(f"  each voice: own wander RATE, own phase, own level breathing\n")

    todo = {only: PRESETS[only]} if only else PRESETS
    total = len(todo)
    if total > 1:
        print(f"  Rendering {total} presets. Roughly 8s each on a 15s source.\n")
    for idx, (name, p) in enumerate(todo.items(), 1):
        print(f"  [{idx}/{total}] {name} ...", end="", flush=True)
        out = apply_preset(audio, rate, p, formant, seed)
        dest = raw.parent / f"{stem}__A_{name}.mp3"
        with AudioFile(str(dest), "w", rate, out.shape[0]) as f:
            f.write(out)
        print(f"\r  [{idx}/{total}] {name:<16} {len(p['voices'])}v  ->  {dest.name}  ({out.shape[-1]/rate:.1f}s)")

    print("\n  Start with SEPARATE_WILLS against entity_echo's DISAGREE — same")
    print("  spread and depths, so any difference IS the rate/amplitude change.")
    print("\n  Then OLD_THINGS vs RESTLESS — slow independence vs fast independence.")
    print("  Then SURFACING, which isolates level breathing on its own.")
    print("\n  --seed 1, --seed 2 etc. reroll the wander shapes without changing")
    print("  the structure. If a preset is close but one voice does something")
    print("  awkward, reroll rather than retune.\n")


if __name__ == "__main__":
    main()
