#!/usr/bin/env python3
"""
Entity Voice — ECHO CLOUD  (entity_echo.py)

Fourth script. Follows entity_timing.py, where SCATTER (260ms) and
DRIFT_HARD won — both of which I'd built as deliberately-too-far ceiling
markers. So the ceiling is higher than assumed, the layers read as echoes
rather than as separate speakers, and that's fine.

WHAT'S DIFFERENT HERE
---------------------
In entity_timing.py only the three near-unison voices were delayed and
drifted. The fifth-below and octave-below sat LOCKED to the dry signal —
which is why they read as timbre rather than as voices.

Here, EVERY pitched layer is a full member of the echo cloud: its own
delay, its own drift, its own mix. Octaves and fifths arrive at their own
times and wander independently. That's what multiplies the dissonance.

ALSO FIXED
----------
Output was being trimmed back to the source length, chopping the final
echo. Invisible at 40ms, but at 260ms you were losing the tail of every
line. Output now extends to fit the longest delay plus drift slack.

VOICE FORMAT
------------
Each voice is (semitones, delay_ms, drift, mix):
    semitones   0.17 = near-unison detune (cents/100)
                -7 = fifth below, -12 = octave below, +12 = octave above
    delay_ms    when this voice arrives
    drift       how much its timing wanders across the line (0 = locked)
    mix         level

The SUB layer stays locked and undrifted on purpose — it's lowpassed body,
not a voice, and drifting it just makes mud. Set DRIFT_SUB = True to try.

SETUP
    pip install pedalboard numpy

USAGE
    python entity_echo.py                 # all presets
    python entity_echo.py --preset FULL
    python entity_echo.py --list
    python entity_echo.py --formant -4

Output: <original>__E_<PRESET>.mp3
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
DRIFT_SUB = False
GRIT = 0.05
SPACE = 0.06
SPACE_DARK = 2200


def P(desc, voices):
    return dict(desc=desc, voices=list(voices))


# ─────────────────────────────────────────────────────────────────────────────
# PRESETS.  voices = [(semitones, delay_ms, drift, mix), ...]
# ─────────────────────────────────────────────────────────────────────────────
PRESETS = {
    # SCATTER + DRIFT_HARD combined, intervals now drifting too. The baseline
    # for everything below — this is your two winners merged.
    "MERGED": P("Your two winners combined: SCATTER's 260ms spread with DRIFT_HARD's "
                "wander, and now the fifth and octave drift too instead of sitting locked.",
                [(0.17, 0, 0.09, 0.44),
                 (-0.14, 140, 0.09, 0.40),
                 (0.10, 260, 0.09, 0.34),
                 (-7, 90, 0.07, 0.20),
                 (-12, 200, 0.07, 0.15)]),

    # What you asked for: octaves added to the doubling, everything drifting.
    "OCTAVES": P("Octave below AND octave above added as drifting delayed voices. "
                 "Cleaner harmonically than fifths — the same voice at three sizes, "
                 "arriving at three different times.",
                 [(0.17, 0, 0.09, 0.42),
                  (-0.14, 150, 0.09, 0.38),
                  (0.10, 270, 0.09, 0.32),
                  (-12, 80, 0.08, 0.20),
                  (12, 210, 0.08, 0.13)]),

    "FIFTHS": P("Fifth below and fifth above as drifting delayed voices. More "
                "dissonant than OCTAVES — direct A/B against it.",
                [(0.17, 0, 0.09, 0.42),
                 (-0.14, 150, 0.09, 0.38),
                 (0.10, 270, 0.09, 0.32),
                 (-7, 80, 0.08, 0.20),
                 (7, 210, 0.08, 0.13)]),

    # Everything at once — this is the "add in the octaves to the doubling" build.
    "FULL": P("Three unison voices plus fifth below, octave below, octave above. "
              "Six drifting layers, all arriving at different times. The dense version.",
              [(0.17, 0, 0.09, 0.38),
               (-0.14, 130, 0.09, 0.34),
               (0.10, 250, 0.09, 0.30),
               (-7, 70, 0.08, 0.18),
               (-12, 190, 0.08, 0.14),
               (12, 320, 0.08, 0.11)]),

    # Wider than anything tested so far.
    "WIDER": P("FULL pushed to a 420ms spread. Past anything you've heard. Finds "
               "out whether the ceiling is higher still.",
               [(0.17, 0, 0.10, 0.38),
                (-0.14, 190, 0.10, 0.34),
                (0.10, 360, 0.10, 0.30),
                (-7, 100, 0.09, 0.18),
                (-12, 270, 0.09, 0.14),
                (12, 420, 0.09, 0.11)]),

    # Drift pushed hard, spread moderate — isolates drift as the variable.
    "WANDER": P("Moderate 260ms spread but very heavy drift on every layer. The "
                "voices pull apart and converge unpredictably. Isolates what drift "
                "alone contributes.",
                [(0.17, 0, 0.16, 0.40),
                 (-0.14, 130, 0.16, 0.36),
                 (0.10, 260, 0.16, 0.32),
                 (-7, 80, 0.15, 0.19),
                 (-12, 200, 0.15, 0.14)]),

    # Every layer drifting at a DIFFERENT rate — maximum disagreement.
    "DISAGREE": P("Each layer drifts by a different amount, so no two ever agree on "
                  "tempo. The most genuinely unstable thing here.",
                  [(0.17, 0, 0.05, 0.40),
                   (-0.14, 150, 0.12, 0.36),
                   (0.10, 280, 0.18, 0.32),
                   (-7, 90, 0.08, 0.19),
                   (-12, 220, 0.15, 0.14)]),

    "CHAOS": P("Deliberately too far again — 500ms spread, extreme drift. Given that "
               "the last two ceiling markers won, this one might too.",
               [(0.17, 0, 0.20, 0.36),
                (-0.14, 210, 0.20, 0.34),
                (0.10, 390, 0.20, 0.30),
                (-7, 120, 0.18, 0.18),
                (-12, 300, 0.18, 0.15),
                (12, 500, 0.18, 0.12)]),
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
    """Slowly vary this voice's speed so its timing wanders across the line."""
    if not amount:
        return audio
    n = audio.shape[-1]
    rng = np.random.default_rng(seed)
    pts = 1.0 + rng.uniform(-amount, amount, 6)
    curve = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(pts)), pts)
    return pedalboard.time_stretch(audio, rate, curve.astype(np.float64),
                                   0.0, preserve_formants=True)


def place(buf, voice, delay_ms, rate, mix):
    """Add a voice into the output buffer at its delay offset."""
    start = int(rate * delay_ms / 1000.0)
    end = min(buf.shape[-1], start + voice.shape[-1])
    if start >= buf.shape[-1]:
        return
    buf[:, start:end] += voice[:, :end - start] * mix


def apply_preset(audio, rate, p, formant):
    dry = shift_formants(audio.astype(np.float32), rate, formant)
    n = dry.shape[-1]

    # Extend output to fit the longest delay plus drift slack, so the final
    # echo isn't chopped. This was the bug in entity_timing.py.
    max_delay = max(v[1] for v in p["voices"])
    tail = int(rate * (max_delay / 1000.0 + 0.5))
    out = np.zeros((dry.shape[0], n + tail), dtype=np.float32)

    # Dry voice
    lead = dry.copy()
    if GRIT > 0:
        gritted = Pedalboard([
            Distortion(drive_db=GRIT * 60),
            HighpassFilter(cutoff_frequency_hz=90),
        ])(dry, rate)
        lead = lead * (1 - GRIT) + gritted * GRIT
    place(out, lead, 0, rate, 1.0)

    # Every pitched layer is a full member of the cloud
    for i, (semis, delay_ms, drift, mix) in enumerate(p["voices"]):
        if mix <= 0:
            continue
        v = Pedalboard([PitchShift(semitones=semis)])(dry, rate)
        if drift:
            v = drift_voice(v, rate, drift, seed=2000 + i * 7)
        place(out, v, delay_ms, rate, mix)

    # Sub — locked body layer, not a voice
    if SUB > 0:
        sub = Pedalboard([
            PitchShift(semitones=-12),
            LowpassFilter(cutoff_frequency_hz=320),
        ])(dry, rate)
        if DRIFT_SUB:
            sub = drift_voice(sub, rate, 0.06, seed=99)
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
    known = {"--list", "--preset", "--formant"}
    unknown = [a for a in argv if a.startswith("--") and a not in known]
    if unknown:
        sys.exit(f"Unknown option(s): {' '.join(unknown)}\nKnown: {' '.join(sorted(known))}")

    if "--list" in argv:
        print()
        for name, p in PRESETS.items():
            spread = max(v[1] for v in p["voices"])
            print(f"  {name:<10} {len(p['voices'])} voices, {spread}ms spread")
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
    print(f"  formant: {formant}   every layer delayed + drifting\n")

    todo = {only: PRESETS[only]} if only else PRESETS
    for name, p in todo.items():
        out = apply_preset(audio, rate, p, formant)
        dest = raw.parent / f"{stem}__E_{name}.mp3"
        with AudioFile(str(dest), "w", rate, out.shape[0]) as f:
            f.write(out)
        print(f"  {name:<10} {len(p['voices'])}v  {max(v[1] for v in p['voices']):>4}ms"
              f"  ->  {dest.name}  ({out.shape[-1]/rate:.1f}s)")

    print("\n  Order:")
    print("    1. MERGED              — your two winners combined, intervals now drifting")
    print("    2. OCTAVES vs FIFTHS   — which interval works in the echo cloud")
    print("    3. FULL                — octaves + fifth, six layers")
    print("    4. WIDER / CHAOS       — further out than anything you've heard")
    print("    5. WANDER / DISAGREE   — drift as the variable, not spread\n")


if __name__ == "__main__":
    main()
