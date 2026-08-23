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

# Emitted ONLY into patterns with a per-pixel loop -- see Pattern.emit.
#
# Division and floor() are the priciest operations in this VM, and the
# render loop was doing both per bloom per pixel: a 9-bloom pattern spent
# 13,752 divisions and 6,876 floor() calls a frame measuring distances on
# a ring. `p - pos` is always within +-pathLen, so the general wrap formula
# was doing far more work than the range needs -- halfLen turns it into two
# compares, and the reciprocals turn each division into a multiply.
RECIPROCALS = """halfLen = pathLen / 2
invPathLen = 1 / pathLen"""

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
    together.

    FREQUENCIES MUST BE WHOLE NUMBERS. This is the loop, not a strip.
    wave() has period 1, so wave(u * 7.3) completes 7.3 cycles as u goes
    0 -> 1 and lands 0.3 of a cycle away from where it started. The loop
    closes; the wave does not. That is a visible seam, measured at 0.31 to
    0.51 on a 0..1 field across the five original scenes -- reported from
    the table as "a weird seam at the split in the ring".

    The non-repeating quality does NOT come from incommensurate
    frequencies. It comes from incommensurate SPEEDS, which are
    independent. So whole frequencies cost nothing.

    They must also be COPRIME. Two frequencies sharing a factor make the
    field repeat that many times around the ring -- 9 and 3 would give
    three identical thirds of a table.
    """

    def __init__(self, a: Tuple[float, float, float],
                 b: Tuple[float, float, float], combine: str = "sum"):
        self.a, self.b = self._whole(a, b)
        self.combine = combine

    @staticmethod
    def _whole(a, b):
        import math

        fa, fb = int(round(a[0])), int(round(b[0]))
        if fa < 1 or fb < 1:
            raise ValueError("wave frequencies must be >= 1, got %s and %s"
                             % (a[0], b[0]))
        if math.gcd(fa, fb) != 1:
            # Nudge the one that moved least, so the look stays closest to
            # what was asked for.
            for candidate in (fb - 1, fb + 1, fa - 1, fa + 1):
                pair = (fa, candidate) if candidate in (fb - 1, fb + 1) else (candidate, fb)
                if min(pair) >= 1 and math.gcd(*pair) == 1:
                    fa, fb = pair
                    break
        if (fa, fb) != (a[0], b[0]):
            print("    frequencies %g/%g -> %d/%d (whole and coprime: the "
                  "loop has to close)" % (a[0], b[0], fa, fb))
        return (fa, a[1], a[2]), (fb, b[1], b[2])

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
               "invWide = %.8g" % (1.0 / self.width),
               "bGain = %g" % self.gain, "bMin = %g" % lo, "bVar = %g" % var]
        if self.rest:
            out.append("bRest = %g" % self.rest)
        if self.drift:
            out.append("bDrift = %g" % self.drift)
        if self.tint:
            out += ["bHue = %g" % self.tint[0], "bSat = %g" % self.tint[1]]
        if self.hue_pull is not None:
            out.append("bHue = %g" % self.hue_pull)
        # bAmp: this bloom's brightness THIS FRAME. See before().
        # bAmp: this bloom's brightness THIS FRAME. See before().
        # bBuf: the whole ring's bloom light, scattered once per frame so
        #       render() is a single lookup. See before() and accumulate().
        out += ["bPos = array(N)", "bAge = array(N)", "bLife = array(N)",
                "bAmp = array(N)", "bBuf = array(pathLen)"]
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
                "  }"]
        # THE ENVELOPE IS PER-BLOOM, NOT PER-PIXEL. It used to be evaluated
        # inside the render loop, so a 9-bloom pattern made ~7,000
        # triangle() calls and 7,000 divisions per frame to produce nine
        # numbers. That is what took Aura-Star to 11fps and idle to 10,
        # reported from the table as "not very smooth" -- and it was read
        # as a hardware fault twice before it was measured properly.
        #
        # A resting bloom lands on zero, which lets render skip its
        # distance maths entirely rather than computing a wrap for a point
        # that contributes nothing.
        out += ["  bAmp[i] = 0",
                "  if (bAge[i] >= 0) {"]
        if self.env == "decay":
            out.append("    e = 1 - bAge[i] / bLife[i]")
        else:
            out.append("    e = triangle(bAge[i] / bLife[i])")
        out += ["    bAmp[i] = e * e * bGain",
                "  }", "}"]

        # SCATTER, not gather. Every pixel used to ask every bloom how far
        # away it was: 764 x N iterations to light a handful of pixels. With
        # 9 blooms 4 wide that is 6,876 distance tests to light about 72 --
        # over 98% of the work producing nothing.
        #
        # Each bloom now walks its OWN span once and adds itself into a ring
        # buffer, so the per-pixel cost drops to a single array read. The
        # fixed cost is clearing the buffer, which is why this wins most on
        # narrow blooms and least on wide ones.
        term = "sfall" if self.env == "decay" else "sfall * sfall"
        out += ["for (si = 0; si < pathLen; si++) bBuf[si] = 0",
                "for (i = 0; i < N; i++) {",
                "  if (bAmp[i] > 0) {",
                "    bc = bPos[i]",
                "    for (sx = floor(bc - bWide); sx <= floor(bc + bWide) + 1; sx++) {",
                "      sd = abs(sx - bc)",
                "      if (sd < bWide) {",
                "        si = sx",
                "        if (si < 0) si = si + pathLen",
                "        if (si >= pathLen) si = si - pathLen",
                "        sfall = 1 - sd * invWide",
                "        bBuf[si] = bBuf[si] + %s * bAmp[i]" % term,
                "      }",
                "    }",
                "  }",
                "}"]
        return out

    def accumulate(self) -> List[str]:
        """One array read. The work happened in before() -- see the scatter
        note there."""
        return ["b = bBuf[p]"]

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


# --------------------------------------------------------------------------
# ENVELOPES -- how brightness varies over TIME, uniformly across the loop.
#
# time(x) counts in units of 65.536 seconds, so a period in real seconds is
# seconds / 65.536. Written out at each use rather than hidden in a constant:
# getting it wrong gives an animation at the wrong speed, which looks
# deliberate and is therefore hard to notice.
#
# One-shot cards (Boon, Person) use a LONG period whose animation occupies
# only the first slice, leaving a dark tail. The controller restores the
# scene during that tail, so the blank is never seen and a re-tap replays
# the animation -- confirmed on the device that re-selecting an already
# active pattern resets its clock.
# --------------------------------------------------------------------------


def secs(seconds: float) -> str:
    return "%.5f" % (seconds / 65.536)


class Envelope:
    """Emits `env`, 0..1, once per frame in beforeRender.

    ONE-SHOT vs CYCLIC, and this distinction is the whole bug fixed on
    2026-08-22.

    A cyclic envelope (breathe, strobe, metronome, flicker) is ambience:
    it should free-run on `time()` and its phase genuinely does not matter.

    A one-shot (ramp_up, ramp_down, heartbeat, pulses) is a CUE. It has a
    beginning, and that beginning is the moment the card was tapped. These
    were also written on `time()`, which is wall-clock and free-running --
    so a Boon's 4-second flash lived at a fixed offset inside an 18-second
    cycle that had nothing to do with the tap. Tap at a random moment and
    you saw nothing about 78% of the time; the Magician, whose flash is
    1.8s of 18, was invisible about 90% of the time. Reported from the
    table as "no visible pattern on any of the boons".

    One-shots now run off `cueT`, which starts at 0 when the pattern is
    activated. See Pattern.emit().
    """

    # heartbeat is CYCLIC -- it is a repeating pulse, and Strength's whole
    # character is that it keeps beating for the full 60s. Classifying it
    # as a one-shot made it beat once and then sit flat for 59 seconds.
    ONE_SHOT = ("ramp_up", "ramp_down", "pulses")

    def __init__(self, kind: str, period: float = 4.0, low: float = 0.0,
                 count: int = 3, duty: float = 0.5, action: float = 0.25):
        self.kind, self.period, self.low = kind, period, low
        self.count, self.duty, self.action = count, duty, action

    @property
    def one_shot(self) -> bool:
        return self.kind in self.ONE_SHOT

    @property
    def act_s(self) -> float:
        """How long the action lasts, in SECONDS.

        Call sites express `action` as a fraction of the period because
        that is how the shapes were designed. Everything downstream works
        in seconds off cueEl, so the conversion happens once, here. The
        fractions only ever meant "this many seconds of an 18s period",
        and they silently meant something else the moment the period
        changed -- which is exactly how a 1.8s flash ended up inside a
        5s card with 3.2s of dark after it.
        """
        return max(self.action * self.period, 0.05)

    def before(self) -> List[str]:
        k, p, lo = self.kind, self.period, self.low
        if k == "steady":
            return ["env = 1"]
        if k == "breathe":
            return ["env = %g + %g * wave(time(%s))" % (lo, 1 - lo, secs(p))]
        if k == "metronome":
            # Deliberately rigid. Justice is meant to read as a machine.
            return ["env = %g" % lo,
                    "if (square(time(%s), %g) > 0) env = 1" % (secs(p), self.duty)]
        if k == "strobe":
            return ["env = 0",
                    "if (square(time(%s), %g) > 0) env = 1" % (secs(p), self.duty)]
        if k == "ramp_up":
            # Rises over the first `action` of the cue, then holds.
            return ["env = %g + %g * min(cueEl / %g, 1)"
                    % (lo, 1 - lo, self.act_s)]
        if k == "ramp_down":
            return ["env = 1 - (1 - %g) * min(cueEl / %g, 1)"
                    % (lo, self.act_s)]
        if k == "heartbeat":
            # Two thumps close together, then a rest -- lub-dub, not a sine.
            return ["et = time(%s)" % secs(p), "env = %g" % lo,
                    "if (et < 0.12) env = 1 - (1 - %g) * (et / 0.12)" % lo,
                    "if (et > 0.20 && et < 0.34) env = %g + %g * (1 - (et - 0.20) / 0.14)"
                    % (lo, (1 - lo) * 0.7)]
        if k == "flicker":
            # Random per frame, held partly toward the previous value so it
            # jitters like a flame rather than strobing white noise.
            return ["env = env * 0.55 + (%g + %g * random(1)) * 0.45"
                    % (lo, 1 - lo)]
        if k == "pulses":
            # N discrete pulses inside the first slice, then dark until the
            # controller takes the pattern away.
            return ["env = 0",
                    "if (cueEl < %g) {" % self.act_s,
                    "  pk = (cueEl / %g) * %d" % (self.act_s, self.count),
                    "  env = 1 - abs((pk - floor(pk)) * 2 - 1)",
                    "  env = env * env",
                    "}"]
        raise ValueError("unknown envelope %r" % k)

    def declare(self) -> List[str]:
        # flicker feeds back on itself, so it needs a starting value.
        return ["env = 1"] if self.kind == "flicker" else []


# --------------------------------------------------------------------------
# FIELDS other than waves.
# --------------------------------------------------------------------------


class Uniform:
    """No spatial variation. Most Aura and Person cards are a whole-table
    colour whose interest is entirely in the envelope."""

    def declare(self): return []
    def before(self): return []
    def field(self): return "1"


class Comet:
    """A point travelling the loop with a tail behind it.

    Boon's single lap and Chariot's racing streaks. `laps` is how many times
    round per period; `count` puts several equally spaced around the ring.
    """

    one_shot = True     # a comet lap starts when the card is tapped

    def __init__(self, width: float = 40, laps: float = 1.0,
                 period: float = 3.0, count: int = 1, tail: float = 3.0):
        self.width, self.laps, self.period = width, laps, period
        self.count, self.tail = count, tail

    def declare(self):
        # ct is declared here, not just assigned in beforeRender: the
        # helper below is compiled before beforeRender ever runs, and a
        # symbol it reads has to exist by then.
        return ["cWide = %g" % self.width, "cN = %d" % self.count,
                "cTail = %g" % self.tail, "ct = 0"]

    def before(self):
        # cueP, not time(): a comet lap belongs to the tap that started
        # it. Unclamped so `laps` still means laps.
        return ["ct = (cueEl / %g) * %g" % (self.period, self.laps)]

    def field(self):
        return "cometField(p)"

    def helper(self):
        return ["function cometField(pp) {",
                "  acc = 0",
                "  for (ci = 0; ci < cN; ci++) {",
                "    hp = (ct + ci / cN) * pathLen",
                # Wrapped signed distance, and only the trailing side gets
                # the tail -- a comet with a symmetric glow is just a blob.
                "    dd = pp - hp",
                "    if (dd > halfLen) dd = dd - pathLen",
                "    if (dd < -halfLen) dd = dd + pathLen",
                "    wide = cWide",
                "    if (dd < 0) wide = cWide * cTail",
                "    dd = abs(dd)",
                "    if (dd < wide) {",
                "      fl = 1 - dd / wide",
                "      acc = acc + fl * fl",
                "    }",
                "  }",
                "  return min(acc, 1)",
                "}"]


class Fixed:
    """One stationary point. The Hermit's lantern -- deliberately localised
    rather than a whole-loop effect."""

    def __init__(self, width: float = 45, at: float = 0.5):
        self.width, self.at = width, at

    def declare(self):
        return ["fWide = %g" % self.width,
                "invFWide = %.8g" % (1.0 / self.width),
                "fAt = %g" % self.at]

    def before(self): return []

    def field(self):
        return "fixedField(p)"

    def helper(self):
        return ["function fixedField(pp) {",
                "  dd = pp - fAt * pathLen",
                "  if (dd > halfLen) dd = dd - pathLen",
                "  if (dd < -halfLen) dd = dd + pathLen",
                "  dd = abs(dd)",
                "  if (dd >= fWide) return 0",
                "  fl = 1 - dd * invFWide",
                "  return fl * fl",
                "}"]


class Converge:
    """Two points starting opposite and travelling toward each other.

    The Lovers. Their meeting is the whole effect, so this is the one place
    the anti-lockstep rule is deliberately off: they are synchronised.
    """

    one_shot = True     # the two lights set off when the card is tapped

    def __init__(self, width: float = 30, period: float = 4.0,
                 action: float = 0.55):
        self.width, self.period, self.action = width, period, action

    def declare(self):
        return ["vWide = %g" % self.width,
                "invVWide = %.8g" % (1.0 / self.width),
                "vAct = %g" % self.action,
                "vt = 0"]

    def before(self):
        return ["vt = min(cueEl / (vAct * %g), 1)" % self.period]

    def field(self):
        return "convergeField(p)"

    def helper(self):
        return ["function convergeField(pp) {",
                "  a = (0.25 + 0.25 * vt) * pathLen",
                "  b = (0.75 - 0.25 * vt) * pathLen",
                "  acc = 0",
                "  for (vi = 0; vi < 2; vi++) {",
                "    hp = a",
                "    if (vi == 1) hp = b",
                "    dd = pp - hp",
                "    if (dd > halfLen) dd = dd - pathLen",
                "    if (dd < -halfLen) dd = dd + pathLen",
                "    dd = abs(dd)",
                "    if (dd < vWide) {",
                "      fl = 1 - dd * invVWide",
                "      acc = acc + fl * fl",
                "    }",
                "  }",
                "  return min(acc, 1)",
                "}"]


class Fill:
    """Progressive fill along the loop from a starting point, then holds.

    The Emperor rising bottom-to-top. Measured in path position, so it
    sweeps round the perimeter from the GM's end.
    """

    one_shot = True     # the fill sweeps once, from the tap

    def __init__(self, period: float = 4.0, action: float = 0.5,
                 start: float = 0.5, soft: float = 0.05):
        self.period, self.action, self.start, self.soft = period, action, start, soft

    def declare(self):
        return ["lStart = %g" % self.start, "lSoft = %g" % self.soft,
                "lt = 0"]

    def before(self):
        return ["lt = min(cueEl / %g, 1)" % (self.action * self.period)]

    def field(self):
        return "fillField(u)"

    def helper(self):
        return ["function fillField(uu) {",
                # Distance forward from the start point, 0..1 round the loop.
                "  d = uu - lStart",
                "  d = d - floor(d)",
                # Measure outward in both directions so it rises as a front
                # from one place rather than sweeping one way round.
                "  if (d > 0.5) d = 1 - d",
                "  d = d * 2",
                "  if (d > lt) return 0",
                "  e = (lt - d) / lSoft",
                "  return min(e, 1)",
                "}"]


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
    """One emitted pattern: a field, a palette, an envelope, and features.

    render() is always the same pipeline, with unused stages omitted:

        field  -> f          what varies around the loop
        palette-> h, sa, v   f lerped through each channel's own curve
        feature-> h, sa, v   blooms or a threshold highlight
        env    -> v          what varies over time, uniform across the loop
    """

    def __init__(self, name: str, note: str, palette: "Palette",
                 field=None, waves=None, field_curve: str = "none",
                 blooms=None, threshold=None, envelope=None,
                 hue_cycle: float = 0.0,
                 window: Optional[Tuple[float, float, float]] = None):
        # window = (attack_s, release_s, total_s). A one-shot gate over the
        # whole cue, multiplied into brightness at render time.
        #
        # WHY: the Auras' envelopes are CYCLIC -- strobe, breathe,
        # metronome, flicker, heartbeat. They have no ending, so the card
        # simply got chopped off mid-cycle when the revert timer fired.
        # Reported from the table as "they don't stop, they take over the
        # board". A gate gives every one of them an arrival and a
        # departure without touching what makes it itself: the Tower still
        # strobes, Strength still beats, but now inside a shape.
        #
        # Applied at RENDER, not folded into env, because flicker feeds
        # back on its own previous value -- gating env in place would make
        # the fade compound frame over frame and die early.
        self.window = window
        self.name, self.note = name, note
        self.field = field if field is not None else waves
        self.palette = palette
        self.field_curve = field_curve
        self.blooms, self.threshold = blooms, threshold
        self.envelope = envelope
        self.hue_cycle = hue_cycle

    def _has_pixel_loop(self) -> bool:
        """Does render() walk a list per pixel? Only those pay for the
        wrap arithmetic, so only those carry the reciprocals."""
        return bool(self.blooms) or callable(getattr(self.field, "helper", None))

    def needs_cue(self) -> bool:
        """Does anything in this pattern have a beginning?"""
        if self.window is not None:
            return True
        if self.envelope is not None and self.envelope.one_shot:
            return True
        return getattr(self.field, "one_shot", False)

    def cue_seconds(self) -> float:
        """How long the cue runs, in seconds.

        The envelope's period wins when there is one, because that is the
        card's stated duration; otherwise the field's own period. These are
        the same number in every pattern we emit, but the envelope is the
        one the config's duration_s is matched against.
        """
        if self.envelope is not None and self.envelope.one_shot:
            return self.envelope.period
        return getattr(self.field, "period", 4.0)

    def emit(self) -> str:
        L: List[str] = []
        L.append("// %s -- GENERATED by tools/patterngen.py. Do not edit here." % self.name)
        L.append("// %s" % self.note)
        L.append(PATH_BUILDER)
        if self._has_pixel_loop():
            L.append(RECIPROCALS)

        if self.needs_cue():
            # Declared before anything that reads them: helper functions are
            # compiled ahead of beforeRender and a symbol they touch has to
            # exist by then.
            L.append("cueEl = 0")
        if self.window:
            L.append("gate = 0")

        L += self.field.declare()
        L += self.palette.declare()
        if self.blooms:
            L += self.blooms.declare()
        if self.threshold:
            L += self.threshold.declare()
        if self.envelope:
            L += self.envelope.declare()
        if self.hue_cycle:
            L.append("hueShift = 0")
        if self.blooms:
            L += self.blooms.init()

        helper = getattr(self.field, "helper", None)
        if helper:
            L += helper()

        L.append("export function beforeRender(delta) {")
        L.append("  dt = delta / 1000")
        if self.needs_cue():
            # THE CUE CLOCK. Counts from zero when this pattern is
            # activated, because a card's effect begins when the card is
            # tapped -- not at some offset inside a free-running wall clock
            # that happens to be running.
            #
            # cueP is unclamped so `laps` still means laps; cueT is clamped
            # so an envelope holds its final value rather than wrapping and
            # firing a second time.
            L.append("  cueEl = cueEl + dt")
        L += ["  " + x for x in self.field.before()]
        if self.envelope:
            L += ["  " + x for x in self.envelope.before()]
        if self.window:
            att, rel, total = self.window
            L.append("  gate = min(cueEl / %g, 1)" % max(att, 0.01))
            L.append("  gOut = (%g - cueEl) / %g" % (total, max(rel, 0.01)))
            L.append("  if (gOut < 0) gOut = 0")
            L.append("  if (gOut > 1) gOut = 1")
            L.append("  gate = gate * gOut")
        if self.hue_cycle:
            L.append("  hueShift = time(%s)" % secs(self.hue_cycle))
        if self.blooms:
            L += ["  " + x for x in self.blooms.before()]
        L.append("}")

        L.append("export function render(index) {")
        L.append("  p = pathPos[index]")
        L.append("  if (p < 0) { rgb(0, 0, 0); return }")
        L.append("  u = p * invPathLen" if self._has_pixel_loop()
                 else "  u = p / pathLen")
        L.append("  raw = %s" % self.field.field())
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

        if self.hue_cycle:
            # The World: the whole spectrum turns. hsv wraps its hue, so no
            # explicit modulo is needed.
            L.append("  h = h + hueShift")
        if self.envelope and self.window:
            L.append("  v = v * env * gate")
        elif self.envelope:
            L.append("  v = v * env")
        elif self.window:
            L.append("  v = v * gate")

        L.append("  hsv(h, sa, v)")
        L.append("}")
        return "\n".join(L) + "\n"


def solid(hue: float, sat: float = 1.0, lo: float = 0.0,
          hi: float = 0.55) -> "Palette":
    """A one-colour palette whose brightness is driven by the field.

    Most card patterns are a single colour doing something over time, so
    the interest lives in the field and the envelope rather than in a hue
    range.
    """
    return Palette(hue=(hue, hue, "none"), sat=(sat, sat, "none"),
                   val=(lo, hi, "none"))


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
        "Plains", "Broad soft gusts over ripe grain.",
        waves=Waves((1, -0.50, 0.6), (2.3, -0.35, 0.4)),
        field_curve="smoothstep",
        # Saturation was 0.15-0.42, which on RGBW is mostly white channel:
        # the hue was right but barely expressed, so it read pale and grey
        # rather than golden. Raised so the gold actually shows -- this is
        # a wheat field, not a lawn.
        palette=Palette(hue=(0.13, 0.10, "none"), sat=(0.62, 0.88, "none"),
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


# --------------------------------------------------------------------------
# THE CARDS (warlock-table-interruption-cards.md)
#
# Hues are the doc's hex colours converted to the Pixelblaze 0..1 hue scale.
# Saturation is kept high: on RGBW a low saturation is mostly white channel,
# which is what made Plains read grey before it was corrected.
# --------------------------------------------------------------------------

# One-shots play their animation in the first slice of a long period and
# then go dark. The controller restores the scene during that tail, so the
# blank is never seen. Re-tapping the card restarts the clock.
ONESHOT = 18.0          # seconds; animation occupies the first ~20%
AURA_SECS = 60.0        # every Aura's duration, per the doc


# ---- Boon: one comet lap, then a full-ring bloom -------------------------
BOON_SUITS = {
    "Swords":    (0.00, 0.00),   # white/silver -- unsaturated on purpose
    "Cups":      (0.60, 0.85),   # blue
    "Wands":     (0.045, 0.95),  # orange-red
    "Pentacles": (0.11, 0.80),   # gold
}

CARDS = {}

for _suit, (_h, _sat) in BOON_SUITS.items():
    CARDS["Boon-" + _suit] = Pattern(
        "Boon-" + _suit, "One comet lap, then the ring blooms. Ace of %s." % _suit,
        # The lap must finish inside the lit window, or you see a fifth of
        # a comet and then darkness. 4s lap against a 3.96s envelope.
        field=Comet(width=26, laps=1.0, period=4.0, count=1, tail=6.0),
        palette=solid(_h, _sat, lo=0.0, hi=0.85),
        # The bloom is the envelope: dark, one sweep, a flash as the comet
        # completes its lap, then nothing.
        envelope=Envelope("pulses", period=ONESHOT, count=1, action=0.22),
    )

# ---- Person: one-time announcements, nine distinct signatures ------------
CARDS.update({
    "Person-Magician": Pattern(
        "Person-Magician", "Sharp double flash. A summoning snap.",
        field=Uniform(), palette=solid(0.005, 0.95, hi=0.75),
        envelope=Envelope("pulses", period=ONESHOT, count=2, action=0.10)),

    "Person-Emperor": Pattern(
        "Person-Emperor", "Solid fill rising from the GM's end, then holds.",
        field=Fill(period=ONESHOT, action=0.28, start=0.0, soft=0.06),
        palette=solid(0.035, 0.90, hi=0.60),
        envelope=Envelope("ramp_up", period=ONESHOT, low=0.85, action=0.05)),

    "Person-Fool": Pattern(
        "Person-Fool", "Erratic playful sparkle skittering round the loop.",
        field=Uniform(), palette=solid(0.14, 0.55, lo=0.02, hi=0.10),
        blooms=Blooms(7, 5, 0.9, (0.12, 0.30), mode="tint", env="decay",
                      rest=0.5, hue_pull=0.15),
        envelope=Envelope("ramp_down", period=ONESHOT, low=0.0, action=0.30)),

    "Person-Empress": Pattern(
        "Person-Empress", "Slow organic breathing glow.",
        field=Uniform(), palette=solid(0.33, 0.85, hi=0.55),
        envelope=Envelope("breathe", period=5.0, low=0.10)),

    "Person-HighPriestess": Pattern(
        "Person-HighPriestess", "Slow shimmering ripple.",
        waves=Waves((2, +0.20, 0.6), (5, -0.14, 0.4)),
        field_curve="square",
        palette=Palette(hue=(0.62, 0.55, "none"), sat=(0.95, 0.45, "none"),
                        val=(0.03, 0.50, "none"))),

    "Person-Lovers": Pattern(
        "Person-Lovers", "Two lights travel toward each other and meet.",
        field=Converge(width=26, period=ONESHOT, action=0.22),
        palette=solid(0.95, 0.55, hi=0.70),
        envelope=Envelope("ramp_down", period=ONESHOT, low=0.0, action=0.32)),

    # Was a Fixed() point that lit up and sat there -- hermetic in theory,
    # inert in practice, and it landed on a corner ring where half the
    # table could not see it. Now the lantern is CARRIED: one warm point
    # travelling a bit over half the loop, trailing light, with a little
    # drifting sparkle so it is not a clean geometric dot. The gate brings
    # him in and takes him away again.
    "Person-Hermit": Pattern(
        "Person-Hermit", "A lantern carried slowly round the table.",
        field=Comet(width=30, laps=0.55, period=9.0, count=1, tail=4.0),
        palette=solid(0.10, 0.72, lo=0.0, hi=0.68),
        blooms=Blooms(4, 7, 0.30, (0.6, 1.4), mode="tint", env="triangle",
                      rest=0.8, drift=3.0, hue_pull=0.09),
        window=(0.9, 1.6, 9.0)),

    "Person-HangedMan": Pattern(
        "Person-HangedMan", "The ripple, running backwards.",
        waves=Waves((2, -0.20, 0.6), (5, +0.14, 0.4)),
        field_curve="square",
        palette=Palette(hue=(0.72, 0.66, "none"), sat=(0.85, 0.55, "none"),
                        val=(0.03, 0.50, "none"))),

    "Person-Hierophant": Pattern(
        "Person-Hierophant", "Three steady ceremonial pulses, bell-like.",
        field=Uniform(), palette=solid(0.80, 0.80, hi=0.65),
        envelope=Envelope("pulses", period=ONESHOT, count=3, action=0.28)),
})

# ---- Aura: standalone versions, played when no scene is running ----------
#
# Four of the twelve are dominant enough that they REPLACE a scene rather
# than tint it (Tower, Judgement, Death, World): a violent strobe or a fade
# to black has nothing left of the scene to preserve.
# Every Aura carries `secs`: how long the card runs, and the length of the
# gate that shapes it. Ten seconds is the ceiling, set at the table --
# these are STINGS. At 60s they read as the card taking the table over,
# and the cyclic ones were simply cut off mid-cycle when the timer fired.
#
# The numbers are per-card rather than a flat ten, because the right
# length is a property of the pattern: three heartbeats is 8s, five
# metronome ticks is 8s, and a hard strobe wants 4s and not a second more.
AURAS = {
    "Sun":        dict(hue=0.11, sat=0.85, secs=8.0,
                       env=Envelope("ramp_up", 8.0, low=0.25, action=0.375)),
    "Moon":       dict(hue=0.60, sat=0.80, secs=9.0,
                       env=Envelope("breathe", 9.0, low=0.20)),
    "Star":       dict(hue=0.55, sat=0.35, secs=9.0, env=Envelope("steady"),
                       blooms=Blooms(9, 4, 0.9, (0.5, 1.2), mode="tint", env="decay", rest=1.5, hue_pull=0.55)),
    "Temperance": dict(hue=0.45, sat=0.75, secs=9.0,
                       env=Envelope("breathe", 8.0, low=0.35)),
    "Strength":   dict(hue=0.06, sat=0.90, secs=8.0,
                       env=Envelope("heartbeat", 2.4, low=0.35)),
    "Justice":    dict(hue=0.0,  sat=0.0,  secs=8.0,
                       env=Envelope("metronome", 1.6, low=0.25, duty=0.35)),
    "Devil":      dict(hue=0.02, sat=0.95, secs=8.0,
                       env=Envelope("flicker", low=0.15)),
    "Chariot":    dict(hue=0.11, sat=0.80, secs=7.0, env=Envelope("steady"),
                       comet=Comet(width=14, laps=3.0, period=2.2, count=3, tail=5.0)),

    "Judgement":  dict(hue=0.13, sat=0.15, secs=6.0,
                       env=Envelope("ramp_up", 6.0, low=0.05, action=0.33)),
    # Shortest of the set on purpose. A hard strobe is the one thing here
    # that gets worse the longer it runs, and ten seconds of it in front of
    # players is not something to ship.
    "Tower":      dict(hue=0.0,  sat=0.0,  secs=4.0,
                       env=Envelope("strobe", 0.22, duty=0.35)),
    "Death":      dict(hue=0.78, sat=0.85, secs=8.0,
                       env=Envelope("ramp_down", 8.0, low=0.02, action=0.75)),
    # cycle == secs so the spectrum turns exactly ONCE. At 60s you only
    # ever saw about a sixth of the wheel, which is the whole card.
    "World":      dict(hue=0.0,  sat=0.90, secs=9.0, cycle=9.0,
                       env=Envelope("breathe", 9.0, low=0.45)),
}

# Attack and release for the Aura gate. Short in, longer out: an effect
# that arrives promptly and leaves gently reads as deliberate, where the
# reverse reads as a fault.
AURA_ATTACK = 0.5
AURA_RELEASE = 1.2

for _name, _a in AURAS.items():
    _secs = _a["secs"]
    CARDS["Aura-" + _name] = Pattern(
        "Aura-" + _name,
        "Standalone aura, %gs. Arrives, plays, leaves." % _secs,
        field=_a.get("comet") or Uniform(),
        palette=solid(_a["hue"], _a["sat"], lo=0.0 if _a.get("comet") else 0.04, hi=0.60),
        blooms=_a.get("blooms"),
        envelope=_a["env"],
        hue_cycle=_a.get("cycle", 0.0),
        window=(AURA_ATTACK, min(AURA_RELEASE, _secs / 3.0), _secs))


# ---- Aura over Scene: REMOVED 2026-08-22 -------------------------------
#
# There used to be a _composite() here that pre-rendered every scene under
# every compositing aura, because the Pixelblaze cannot layer two patterns
# at runtime -- a combination has to exist as its own pattern.
#
# It produced 40 patterns: 65% of everything this generator emitted, for a
# feature that was never wired up. play_interruption() sets the
# interruption's pattern verbatim, so nothing ever selected "Forest+Chariot"
# and all 40 sat on the device unused. Finishing it would have meant 72
# patterns (6 scenes x 12 auras) to cover the matrix honestly, on a device
# whose flash had already been filled once.
#
# So the aura now REPLACES the scene for its duration and reverts, which is
# what the four `replaces` auras always did. That is a real loss -- the
# forest is gone for those 60 seconds rather than tinted -- and it is not
# recoverable without bringing the combos back. It bought the memory to
# spend on patterns people actually see.


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenes-only", action="store_true",
                    help="emit just the five scenes, not the card patterns")
    ap.add_argument("--list", action="store_true",
                    help="show what would be emitted, write nothing")
    # Default is no suffix: these ARE the scenes now, validated on the table
    # 2026-08-21 and the hand-written originals retired to patterns/legacy/.
    # Pass --suffix -gen to put a variant alongside a live pattern when
    # trying a change out.
    ap.add_argument("--suffix", default="",
                    help="appended to each emitted name, for putting a "
                         "variant beside a live pattern while comparing")
    args = ap.parse_args()

    if not args.list:
        os.makedirs(OUT_DIR, exist_ok=True)

    total = 0
    everything = dict(SCENES)
    if not args.scenes_only:
        everything.update(CARDS)
    for name, pattern in everything.items():
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
