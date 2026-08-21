#!/usr/bin/env python3
"""Generate Pixelblaze patterns for the Warlock Table from a small vocabulary.

    python tools/patterngen.py            # write patterns/generated/
    python tools/patterngen.py --list     # what it would emit, and how big

WHY GENERATE RATHER THAN HAND-WRITE

Not to save space -- comments are 59% of our sources and stripping them on
upload would save more. Two better reasons:

1. **One source of truth for the shared parts.** The perimeter path builder
   is currently copy-pasted verbatim into six patterns. If `segStart` ever
   needed correcting that is six edits and a chance to miss one.
2. **The craft scales.** Hand-tuning seventy patterns is not going to
   happen. The techniques that stop a loop looking machine-made --
   incommensurate wave frequencies, staggered bloom phases, seam-correct
   distance, blending toward a colour instead of adding to it -- cost
   15-45 bytes each. Encoded here once, every generated pattern inherits
   them without anyone deciding per card.

WHAT IT MUST NOT DO

Flatten the five existing scenes into five variations of one wash. They
differ in ways that are easy to miss and carry the whole character:

  - Mountain MULTIPLIES its two waves; everything else weight-sums them.
  - Every scene curves its channels differently. Island is w**3 for colour
    and w**2 for value. Mountain is heat**2 for hue, heat for value, and
    1 - 0.5*heat**3 for saturation.
  - Forest's shafts add INTO the field before the palette. Swamp's wisps
    and Mountain's sparks tint h/s/v after it. Different look entirely.
  - Weights are 0.6/0.4 except Island, which is 0.55/0.45.

The vocabulary below exists to express those differences, not to average
them away. The five scenes are emitted first and uploaded under parallel
names so they can be compared against the originals on the table before
anything is replaced.
"""

from __future__ import annotations

import argparse
import os
import textwrap
from typing import List, Optional, Tuple

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO, "patterns", "generated")

# --------------------------------------------------------------------------
# The shared perimeter path builder.
#
# From warlock-table-led-reference.md section 7, and the ONLY copy in the
# generated set. skip = 0: the ring corner skip is for chase patterns only,
# so pathLen is 764 rather than the chase-path 700. Do not "tidy" segStart --
# it is verified physical ground truth.
# --------------------------------------------------------------------------
PATH_BUILDER = """\
segStart = [ 60, 502,  0, 705, 180, 240, 120, 443]
segLen   = [ 60, 203, 60,  59,  60, 203,  60,  59]
pathPos = array(pixelCount)
for (i = 0; i < pixelCount; i++) pathPos[i] = -1
pathLen = 0
for (s = 0; s < 8; s++) {
  for (k = 0; k < segLen[s]; k++) {
    idx = segStart[s] + k
    if (idx < pixelCount) { pathPos[idx] = pathLen; pathLen = pathLen + 1 }
  }
}"""

# Curve shapes, as expressions over a variable named `x`. Biasing the field
# dark is what makes bright patches read as events rather than as an evenly
# lit surface.
CURVES = {
    "none":       "{x}",
    "square":     "{x} * {x}",
    "cube":       "{x} * {x} * {x}",
    "pow1_5":     "{x} * sqrt({x})",
    "smoothstep": "{x} * {x} * (3 - 2 * {x})",
}


def curve(name: str, var: str) -> str:
    if name not in CURVES:
        raise ValueError("unknown curve %r (have: %s)"
                         % (name, ", ".join(sorted(CURVES))))
    return CURVES[name].format(x=var)


class Waves:
    """Two travelling waves along the loop.

    `combine` is "sum" (weighted) or "product". Mountain uses product, which
    gives sharp dark bands where either wave is low -- rock between embers.
    Everything else sums.

    Speeds are SIGNED: the sign is the direction of travel, and opposing
    signs are what make two waves drift against each other rather than
    together. Frequencies should stay incommensurate (3 and 7.3, not 3 and 6)
    so the combined field never visibly repeats.
    """

    def __init__(self, a: Tuple[float, float, float],
                 b: Tuple[float, float, float], combine: str = "sum"):
        self.a, self.b, self.combine = a, b, combine

    def declare(self) -> List[str]:
        # wf/ws, not f/s: the palette uses sA/sB for saturation, and a
        # collision there would silently change the wave speed instead of
        # failing. That bug got written once already.
        (fa, sa, _), (fb, sb, _) = self.a, self.b
        return ["wfA = %g" % fa, "wsA = %g" % abs(sa),
                "wfB = %g" % fb, "wsB = %g" % abs(sb)]

    def before(self) -> List[str]:
        return ["tA = time(wsA)", "tB = time(wsB)"]

    def field(self) -> str:
        (_, sa, wa), (_, sb, wb) = self.a, self.b
        oa = "+" if sa >= 0 else "-"
        ob = "+" if sb >= 0 else "-"
        wave_a = "wave(u * wfA %s tA)" % oa
        wave_b = "wave(u * wfB %s tB)" % ob
        if self.combine == "product":
            return "%s * %s" % (wave_a, wave_b)
        return "%s * %g + %s * %g" % (wave_a, wa, wave_b, wb)


class Blooms:
    """N points that swell and fade at random places on the loop.

    Forest's sun shafts, Mountain's sparks and Swamp's wisps are all this,
    with different numbers -- 3 wide slow ones, 6 narrow fast ones, 4 that
    drift and carry their own colour.

    `mode`:
      "field" -- adds into the field BEFORE the palette, so the bloom takes
                 the scene's own colours (Forest).
      "tint"  -- modifies h/s/v after the palette, so the bloom can be a
                 different colour from the scene (Swamp, Mountain).

    `env`:
      "triangle" -- up then down over its life (Forest, Swamp)
      "decay"    -- full then fading (Mountain sparks)

    Phases are staggered at startup so the points never bloom in unison,
    which is the most machine-made failure mode there is.
    """

    def __init__(self, n: int, width: float, gain: float,
                 life: Tuple[float, float], mode: str = "field",
                 env: str = "triangle", rest: float = 0.0, drift: float = 0.0,
                 tint: Optional[Tuple[float, float]] = None,
                 desat: float = 0.0, hue_pull: Optional[float] = None):
        self.n, self.width, self.gain, self.life = n, width, gain, life
        self.mode, self.env, self.rest, self.drift = mode, env, rest, drift
        self.tint, self.desat, self.hue_pull = tint, desat, hue_pull

    def declare(self) -> List[str]:
        lo, var = self.life
        out = ["N = %d" % self.n, "bWide = %g" % self.width,
               "bGain = %g" % self.gain, "bMin = %g" % lo, "bVar = %g" % var]
        if self.rest:
            out.append("bRest = %g" % self.rest)
        if self.drift:
            out.append("bDrift = %g" % self.drift)
        if self.tint:
            out += ["bHue = %g" % self.tint[0], "bSat = %g" % self.tint[1]]
        if self.hue_pull is not None:
            out.append("bHue = %g" % self.hue_pull)
        out += ["bPos = array(N)", "bAge = array(N)", "bLife = array(N)"]
        return out

    def init(self) -> List[str]:
        # Stagger: each starts at a random point in its own life, so they
        # are never in phase. 34 bytes, and the difference between "alive"
        # and "a machine".
        return ["for (i = 0; i < N; i++) {",
                "  bPos[i] = random(pathLen)",
                "  bLife[i] = bMin + random(bVar)",
                "  bAge[i] = random(bLife[i])",
                "}"]

    def before(self) -> List[str]:
        out = ["for (i = 0; i < N; i++) {", "  bAge[i] = bAge[i] + dt"]
        if self.drift:
            out += ["  bPos[i] = bPos[i] + bDrift * dt",
                    "  if (bPos[i] >= pathLen) bPos[i] = bPos[i] - pathLen"]
        out += ["  if (bAge[i] >= bLife[i]) {"]
        # A rest makes them intermittent rather than a steady procession:
        # a negative age is dormant, gated in render.
        out += ["    bAge[i] = -random(bRest)"] if self.rest else ["    bAge[i] = 0"]
        out += ["    bLife[i] = bMin + random(bVar)",
                "    bPos[i] = random(pathLen)",
                "  }", "}"]
        return out

    def accumulate(self) -> List[str]:
        out = ["b = 0", "for (j = 0; j < N; j++) {"]
        indent = "  "
        if self.rest:
            out.append("  if (bAge[j] > 0) {")
            indent = "    "
        # Wrapped signed distance. NOT min(d, pathLen - d), which loses the
        # sign across the seam and glitches once per lap.
        out += [indent + "dd = p - bPos[j]",
                indent + "dd = dd - pathLen * floor(dd / pathLen + 0.5)",
                indent + "dd = abs(dd)",
                indent + "if (dd < bWide) {",
                indent + "  fall = 1 - dd / bWide"]
        if self.env == "decay":
            out += [indent + "  e = 1 - bAge[j] / bLife[j]",
                    indent + "  b = b + fall * e * e * bGain"]
        else:
            out += [indent + "  e = triangle(bAge[j] / bLife[j])",
                    indent + "  b = b + fall * fall * e * e * bGain"]
        out.append(indent + "}")
        if self.rest:
            out.append("  }")
        out.append("}")
        return out

    def apply_tint(self) -> List[str]:
        """Blend TOWARD the bloom colour rather than adding to it.

        Adding a colour to a lit scene drives everything toward white and
        the bloom stops being a distinct point. This is also what makes the
        aura-over-scene composites work at all.
        """
        out = ["if (b > 0) {", "  bk = min(b, 1)"]
        if self.tint:
            out += ["  h = h + (bHue - h) * bk", "  sa = sa + (bSat - sa) * bk"]
        elif self.hue_pull is not None:
            out.append("  h = h + (bHue - h) * bk")
        if self.desat:
            out.append("  sa = sa - %g * bk" % self.desat)
        out += ["  v = v + b", "}"]
        return out


class Palette:
    """Hue, saturation and value, each lerped by the field through its own
    curve. Per-channel curves matter: Island sharpens colour with w**3 while
    keeping value at w**2, and flattening that loses the crest."""

    def __init__(self, hue: Tuple[float, float, str],
                 sat: Tuple[float, float, str],
                 val: Tuple[float, float, str]):
        self.hue, self.sat, self.val = hue, sat, val

    def declare(self) -> List[str]:
        return ["hA = %g" % self.hue[0], "hB = %g" % self.hue[1],
                "sA = %g" % self.sat[0], "sB = %g" % self.sat[1],
                "vA = %g" % self.val[0], "vB = %g" % self.val[1]]

    def emit(self) -> List[str]:
        out = []
        h_lo, h_hi, h_c = self.hue
        s_lo, s_hi, s_c = self.sat
        v_lo, v_hi, v_c = self.val
        out.append("h = hA + (hB - hA) * (%s)" % curve(h_c, "f"))
        out.append("sa = sA + (sB - sA) * (%s)" % curve(s_c, "f"))
        out.append("v = vA + (vB - vA) * (%s)" % curve(v_c, "f"))
        return out


class Threshold:
    """Highlight only where the field passes a level -- Island's foam.

    Deliberately reads the RAW field, not a curved one: the threshold is
    about where the water actually crests.
    """

    def __init__(self, level: float, gain: float, desat: float = 0.0):
        self.level, self.gain, self.desat = level, gain, desat

    def declare(self) -> List[str]:
        return ["thr = %g" % self.level, "thrGain = %g" % self.gain]

    def emit(self) -> List[str]:
        out = ["if (raw > thr) {",
               "  t = (raw - thr) / (1 - thr)",
               "  v = v + t * t * thrGain"]
        if self.desat:
            out.append("  sa = sa * (1 - %g * t)" % self.desat)
        out.append("}")
        return out


class Pattern:
    """One emitted pattern."""

    def __init__(self, name: str, note: str, waves: Waves, palette: Palette,
                 field_curve: str = "none", blooms: Optional[Blooms] = None,
                 threshold: Optional[Threshold] = None):
        self.name, self.note = name, note
        self.waves, self.palette = waves, palette
        self.field_curve = field_curve
        self.blooms, self.threshold = blooms, threshold

    def emit(self) -> str:
        L: List[str] = []
        L.append("// %s -- GENERATED by tools/patterngen.py. Do not edit here." % self.name)
        L.append("// %s" % self.note)
        L.append(PATH_BUILDER)

        L += self.waves.declare()
        L += self.palette.declare()
        if self.blooms:
            L += self.blooms.declare()
        if self.threshold:
            L += self.threshold.declare()
        if self.blooms:
            L += self.blooms.init()

        L.append("export function beforeRender(delta) {")
        L.append("  dt = delta / 1000")
        L += ["  " + x for x in self.waves.before()]
        if self.blooms:
            L += ["  " + x for x in self.blooms.before()]
        L.append("}")

        L.append("export function render(index) {")
        L.append("  p = pathPos[index]")
        L.append("  if (p < 0) { rgb(0, 0, 0); return }")
        L.append("  u = p / pathLen")
        L.append("  raw = %s" % self.waves.field())
        L.append("  f = %s" % curve(self.field_curve, "raw"))

        if self.blooms and self.blooms.mode == "field":
            L += ["  " + x for x in self.blooms.accumulate()]
            L.append("  f = min(f + b, 1)")

        L += ["  " + x for x in self.palette.emit()]

        if self.blooms and self.blooms.mode == "field" and self.blooms.desat:
            L.append("  sa = sa - %g * min(b, 1)" % self.blooms.desat)
        if self.blooms and self.blooms.mode == "tint":
            L += ["  " + x for x in self.blooms.accumulate()]
            L += ["  " + x for x in self.blooms.apply_tint()]
        if self.threshold:
            L += ["  " + x for x in self.threshold.emit()]

        L.append("  hsv(h, sa, v)")
        L.append("}")
        return "\n".join(L) + "\n"


# --------------------------------------------------------------------------
# The five scenes, transcribed from the hand-written originals.
# Speeds are signed for direction; weights and curves are per-scene because
# they differ and the differences are the character.
# --------------------------------------------------------------------------
SCENES = {
    "Forest": Pattern(
        "Forest", "Deep canopy with dappled light and sun shafts.",
        waves=Waves((3, +0.16, 0.6), (7.3, -0.26, 0.4)),
        field_curve="square",
        palette=Palette(hue=(0.30, 0.24, "none"), sat=(0.92, 0.92, "none"),
                        val=(0.05, 0.40, "none")),
        blooms=Blooms(3, 70, 0.55, (5, 6), mode="field", desat=0.25),
    ),
    "Plains": Pattern(
        "Plains", "Broad soft gusts over open grass.",
        waves=Waves((1, -0.50, 0.6), (2.3, -0.35, 0.4)),
        field_curve="smoothstep",
        palette=Palette(hue=(0.13, 0.10, "none"), sat=(0.15, 0.42, "none"),
                        val=(0.18, 0.50, "none")),
    ),
    "Island": Pattern(
        "Island", "Swell with foam on the crests.",
        waves=Waves((2, -0.10, 0.55), (3.5, +0.07, 0.45)),
        field_curve="none",
        palette=Palette(hue=(0.55, 0.48, "cube"), sat=(0.95, 0.45, "cube"),
                        val=(0.05, 0.42, "square")),
        threshold=Threshold(0.88, 0.35, desat=0.6),
    ),
    "Mountain": Pattern(
        "Mountain", "Banded heat in the rock, with cinders.",
        waves=Waves((9, +0.35, 0.6), (2.7, -0.50, 0.4), combine="product"),
        field_curve="pow1_5",
        palette=Palette(hue=(0.005, 0.09, "square"), sat=(1.0, 0.5, "cube"),
                        val=(0.02, 0.45, "none")),
        blooms=Blooms(6, 4, 0.5, (0.15, 0.35), mode="tint", env="decay",
                      rest=2.5, hue_pull=0.10, desat=0.3),
    ),
    "Swamp": Pattern(
        "Swamp", "Mostly dark bog with drifting will-o-wisps.",
        waves=Waves((1.6, +0.60, 0.6), (3.1, -0.90, 0.4)),
        field_curve="square",
        palette=Palette(hue=(0.76, 0.82, "none"), sat=(0.95, 0.95, "none"),
                        val=(0.04, 0.30, "none")),
        blooms=Blooms(4, 8, 0.42, (4, 4), mode="tint", env="triangle",
                      drift=7, tint=(0.36, 0.80)),
    ),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true",
                    help="show what would be emitted, write nothing")
    ap.add_argument("--suffix", default="-gen",
                    help="appended to each name so generated patterns sit "
                         "alongside the originals for comparison "
                         "(default: -gen)")
    args = ap.parse_args()

    if not args.list:
        os.makedirs(OUT_DIR, exist_ok=True)

    total = 0
    for name, pattern in SCENES.items():
        src = pattern.emit()
        total += len(src)
        out_name = name + args.suffix
        if args.list:
            print("  %-16s %5d bytes" % (out_name, len(src)))
            continue
        path = os.path.join(OUT_DIR, out_name + ".js")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(src)
        print("  wrote %-20s %5d bytes" % (out_name + ".js", len(src)))
    print("  %-16s %5d bytes total" % ("", total))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
