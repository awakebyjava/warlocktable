#!/usr/bin/env python3
"""
Entity Voice — GROSS  (entity_gross.py)

Sixth script. The echo experiments (entity_echo, entity_agency) cost too
much intelligibility, so we're back to LEGION from entity_variants.py as
the base. LEGION is reproduced here EXACTLY — same formant, same doubles,
same fifth below, same sub, same reverb.

Everything added here is TEXTURE, which is a different axis from space or
multiplicity. Texture lives in the harmonics and in what rides alongside
the voice, so it costs almost nothing in intelligibility. You can be very
gross and still be perfectly understood.

THE TECHNIQUES
--------------
rasp        Filtered noise shaped by the voice's own envelope, so it only
            appears when the voice speaks. Reads as wet breath, phlegm,
            something rattling in a throat. This is the single most
            visceral tool here and the most likely thing you're after.

ladder      Resonant lowpass with drive. Adds a throaty honk — the sound
            of a constricted airway rather than an open mouth.

harsh       Narrow boost around 1.5-2.5kHz, where the ear finds sounds
            abrasive and grating. Costs nothing in clarity; actually
            increases it while sounding worse.

clip        Hard clipping instead of soft saturation. Nastier, more
            brittle, less musical than the Distortion used so far.

crush       Bit reduction. Grimy and degraded. Small amounts read as
            "something wrong with the recording."

wobble      Slow pitch instability on the voice itself. Reads as sick or
            unwell rather than as an effect.

flutter     Amplitude modulation around 25-45Hz. Produces an organic
            guttural growl — wetter and more bodily than ring modulation.

SETUP
    pip install pedalboard numpy

USAGE
    python entity_gross.py
    python entity_gross.py --preset RASP
    python entity_gross.py --list
    python entity_gross.py --seed 3

Output: <original>__G_<PRESET>.mp3
"""

import sys
from pathlib import Path

import numpy as np
import pedalboard
from pedalboard import (Bitcrush, Clipping, Compressor, Delay, Distortion,
                        HighpassFilter, LadderFilter, LowpassFilter, Pedalboard,
                        PeakFilter, PitchShift, Reverb)
from pedalboard.io import AudioFile

CANDIDATES = [
    Path("audio/entity/_test/audition__raw.wav"),
    Path("audio/entity/_test/audition__raw.mp3"),
    Path("audio/entity/_test/system_shutdown_01__raw.wav"),
    Path("audio/entity/_test/system_shutdown_01__raw.mp3"),
]

# ── LEGION base, reproduced exactly from entity_variants.py ──
FORMANT = -4.0
DETUNE = (16, 18, 0.60)      # cents, ms, mix
DETUNE2 = (-13, 31, 0.50)
INTERVAL = (-7, 0.22)        # fifth below
SUB = 0.35
BASE_GRIT = 0.05
SPACE = 0.12
SPACE_DARK = 1800
SEED = 0


def G(desc, rasp=0.0, rasp_lo=700, rasp_hi=3800, ladder=0.0, ladder_hz=900,
      ladder_res=0.75, harsh=0.0, clip=0.0, crush=0.0, wobble=0.0, flutter=0.0,
      flutter_hz=33):
    return dict(desc=desc, rasp=rasp, rasp_lo=rasp_lo, rasp_hi=rasp_hi,
                ladder=ladder, ladder_hz=ladder_hz, ladder_res=ladder_res,
                harsh=harsh, clip=clip, crush=crush, wobble=wobble,
                flutter=flutter, flutter_hz=flutter_hz)


# ─────────────────────────────────────────────────────────────────────────────
# PRESETS — LEGION base is identical in all of them. Only texture varies.
# ─────────────────────────────────────────────────────────────────────────────
PRESETS = {
    "CLEAN": G("LEGION exactly as you heard it, no added texture. The reference "
               "point — play this first so you know what each preset is adding."),

    # Each of these isolates ONE technique so you can tell what you're hearing.
    "RASP": G("Wet noise rasp only, shaped by the voice's envelope. Sounds like "
              "something rattling in a throat. Most likely the thing you want.",
              rasp=0.30),

    "RASP_DEEP": G("Same rasp, filtered lower and heavier. Chestier and wetter — "
                   "less hiss, more gurgle.",
                   rasp=0.38, rasp_lo=300, rasp_hi=2200),

    "THROAT": G("Resonant ladder filter only. A constricted airway rather than an "
                "open mouth. Honking and unpleasant.",
                ladder=0.45, ladder_hz=850, ladder_res=0.8),

    "HARSH": G("Abrasive midrange boost only. Grating on the ear while actually "
               "making the words CLEARER, not muddier.",
               harsh=0.55),

    "ROTTEN": G("Hard clipping and bit reduction. Brittle and degraded — as if the "
                "voice itself is damaged rather than the room.",
                clip=0.35, crush=0.30),

    "SICK": G("Slow pitch wobble only. No added noise at all — it just sounds unwell. "
              "Subtle, and the most psychologically off-putting one here.",
              wobble=0.32),

    "GUTTURAL": G("Low-frequency amplitude flutter. An organic bodily growl, wetter "
                  "and less mechanical than ring modulation.",
                  flutter=0.28, flutter_hz=31),

    # Combinations.
    "VISCERAL": G("Rasp plus throat plus flutter. Wet, constricted, growling — the "
                  "bodily kind of gross. Words stay intelligible.",
                  rasp=0.32, rasp_lo=400, rasp_hi=2600,
                  ladder=0.30, ladder_hz=880, flutter=0.20),

    "DISEASED": G("Rasp plus wobble plus harshness. Sounds ill rather than monstrous. "
                  "Unsettling in a different register than VISCERAL.",
                  rasp=0.26, wobble=0.28, harsh=0.40),

    "FOUL": G("Everything, moderately. The full gross build — check the consonants "
              "on 'I am not consulted' before committing to it.",
              rasp=0.30, rasp_lo=400, rasp_hi=3000, ladder=0.28, harsh=0.35,
              clip=0.20, crush=0.15, wobble=0.18, flutter=0.18),

    "TOO_FAR": G("Deliberately excessive. Your ceiling markers keep winning, so here's "
                 "another one.",
                 rasp=0.55, rasp_lo=250, rasp_hi=4200, ladder=0.50, harsh=0.60,
                 clip=0.45, crush=0.40, wobble=0.35, flutter=0.35),
}
# ─────────────────────────────────────────────────────────────────────────────


def shift_formants(audio, rate, semitones):
    if not semitones:
        return audio
    down = pedalboard.time_stretch(audio, rate, 1.0, semitones, preserve_formants=False)
    return pedalboard.time_stretch(down, rate, 1.0, -semitones, preserve_formants=True)


def envelope(audio, rate, ms=12.0):
    """Smoothed amplitude envelope of the voice. O(n)."""
    x = np.abs(audio[0])
    k = max(1, int(rate * ms / 1000.0))
    cs = np.cumsum(np.insert(x, 0, 0.0))
    env = (cs[k:] - cs[:-k]) / k
    env = np.pad(env, (0, len(x) - len(env)), mode="edge")
    return (env / (env.max() + 1e-9)).astype(np.float32)


def make_rasp(audio, rate, amount, lo, hi, seed):
    """Filtered noise gated by the voice's own envelope.

    Because it follows the envelope, it only exists while the voice speaks —
    so it reads as coming from inside the throat rather than as added hiss.
    """
    if amount <= 0:
        return None
    env = envelope(audio, rate)
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 1, len(env)).astype(np.float32)
    # env squared makes the rasp bite on consonants rather than sit under vowels
    shaped = (noise * (env ** 1.6))[None, :]
    shaped = Pedalboard([
        HighpassFilter(cutoff_frequency_hz=lo),
        LowpassFilter(cutoff_frequency_hz=hi),
    ])(shaped, rate)
    peak = float(np.max(np.abs(shaped)))
    if peak > 0:
        shaped = shaped / peak
    return shaped * amount


def wobble_pitch(audio, rate, amount, seed):
    """Slow pitch instability — reads as unwell rather than as an effect."""
    if amount <= 0:
        return audio
    n = audio.shape[-1]
    rng = np.random.default_rng(seed)
    pts = rng.uniform(-1, 1, 7)
    curve = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(pts)), pts)
    k = max(1, n // 40)
    cs = np.cumsum(np.insert(np.pad(curve, (k // 2, k - k // 2), mode="edge"), 0, 0.0))
    curve = (cs[k:k + n] - cs[:n]) / k
    semis = (curve * amount * 1.2).astype(np.float64)
    return pedalboard.time_stretch(audio, rate, 1.0, semis, preserve_formants=True)


def flutter_am(audio, rate, amount, hz):
    """Amplitude modulation — organic guttural growl."""
    if amount <= 0:
        return audio
    t = np.arange(audio.shape[-1]) / rate
    mod = (1.0 - amount) + amount * (0.5 + 0.5 * np.sin(2 * np.pi * hz * t))
    return audio * mod.astype(np.float32)


def apply_preset(audio, rate, p, seed):
    dry = shift_formants(audio.astype(np.float32), rate, FORMANT)

    if p["wobble"]:
        dry = wobble_pitch(dry, rate, p["wobble"], seed + 5)

    out = dry.copy()

    if BASE_GRIT > 0:
        g = Pedalboard([Distortion(drive_db=BASE_GRIT * 60),
                        HighpassFilter(cutoff_frequency_hz=90)])(dry, rate)
        out = out * (1 - BASE_GRIT) + g * BASE_GRIT

    # LEGION's two detuned doubles
    for cents, ms, mix in (DETUNE, DETUNE2):
        chain = [PitchShift(semitones=cents / 100.0)]
        if ms:
            chain.append(Delay(delay_seconds=ms / 1000.0, feedback=0.0, mix=1.0))
        out = out + Pedalboard(chain)(dry, rate) * mix

    # Fifth below
    out = out + Pedalboard([PitchShift(semitones=INTERVAL[0])])(dry, rate) * INTERVAL[1]

    # Sub
    if SUB > 0:
        sub = Pedalboard([PitchShift(semitones=-12),
                          LowpassFilter(cutoff_frequency_hz=320)])(dry, rate)
        out = out + sub * SUB

    # ── Texture ──
    if p["ladder"] > 0:
        wet = Pedalboard([LadderFilter(mode=LadderFilter.Mode.LPF12,
                                       cutoff_hz=p["ladder_hz"],
                                       resonance=p["ladder_res"], drive=3.0)])(
            out.astype(np.float32), rate)
        wet = wet / (float(np.max(np.abs(wet))) + 1e-9) * float(np.max(np.abs(out)))
        out = out * (1 - p["ladder"]) + wet * p["ladder"]

    if p["harsh"] > 0:
        out = Pedalboard([PeakFilter(cutoff_frequency_hz=1900,
                                     gain_db=p["harsh"] * 12, q=1.1)])(
            out.astype(np.float32), rate)

    if p["clip"] > 0:
        wet = Pedalboard([Clipping(threshold_db=-8 - p["clip"] * 14)])(
            out.astype(np.float32), rate)
        wet = wet / (float(np.max(np.abs(wet))) + 1e-9) * float(np.max(np.abs(out)))
        out = out * (1 - p["clip"]) + wet * p["clip"]

    if p["crush"] > 0:
        bits = int(round(12 - p["crush"] * 6))
        wet = Pedalboard([Bitcrush(bit_depth=max(4, bits))])(out.astype(np.float32), rate)
        out = out * (1 - p["crush"]) + wet * p["crush"]

    out = flutter_am(out, rate, p["flutter"], p["flutter_hz"])

    # Rasp last, so filters don't strip it
    rasp = make_rasp(dry, rate, p["rasp"], p["rasp_lo"], p["rasp_hi"], seed + 17)
    if rasp is not None:
        out = out + rasp * float(np.max(np.abs(out)))

    if SPACE > 0:
        wet = Pedalboard([
            Reverb(room_size=0.5, damping=0.7, wet_level=1.0, dry_level=0.0, width=0.8),
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
    known = {"--list", "--preset", "--seed"}
    unknown = [a for a in argv if a.startswith("--") and a not in known]
    if unknown:
        sys.exit(f"Unknown option(s): {' '.join(unknown)}\nKnown: {' '.join(sorted(known))}")

    if "--list" in argv:
        print()
        for name, p in PRESETS.items():
            on = [k for k in ("rasp", "ladder", "harsh", "clip", "crush", "wobble", "flutter")
                  if p[k] > 0]
            print(f"  {name:<11} {', '.join(on) if on else '(base only)'}")
            print(f"      {p['desc']}\n")
        return

    seed = SEED
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
    print(f"  base   : LEGION (formant {FORMANT}, 2 doubles, 5th below, sub {SUB})")
    print(f"  varying: texture only\n")

    todo = {only: PRESETS[only]} if only else PRESETS
    total = len(todo)
    for idx, (name, p) in enumerate(todo.items(), 1):
        print(f"  [{idx}/{total}] {name} ...", end="", flush=True)
        out = apply_preset(audio, rate, p, seed)
        dest = raw.parent / f"{stem}__G_{name}.mp3"
        with AudioFile(str(dest), "w", rate, out.shape[0]) as f:
            f.write(out)
        print(f"\r  [{idx}/{total}] {name:<11} ->  {dest.name}          ")

    print("\n  1. CLEAN first — LEGION with nothing added, your reference.")
    print("  2. RASP / RASP_DEEP — the wet throat sound, most likely what you want.")
    print("  3. THROAT / HARSH / ROTTEN / SICK / GUTTURAL — one technique each,")
    print("     so you can name which kind of gross you're after.")
    print("  4. VISCERAL / DISEASED / FOUL — combinations.")
    print("  5. TOO_FAR — the ceiling marker.\n")
    print("  Check 'I am not consulted' stays clear. Texture shouldn't cost you words.\n")


if __name__ == "__main__":
    main()
