// ============================================================
// Warlock Table - "Swamp"  (black mana / Swamp land scene)
// ============================================================
// Black mana rendered as deep violet, deliberately. The pattern this
// replaces (BlackCard) was literally hsv(h, s, 0) - value zero, so the
// table simply went dark and nothing appeared to happen. Purple keeps
// the scene readable as a scene while still being the darkest of the
// five.
//
// The bog breathes: very slow swells rise toward a sicklier magenta and
// sink back. Above it drift will-o'-wisps - a few small points in a
// green-teal accent, fading up over seconds and out again.
//
// The wisp colour is the one green in here, and it is kept to a narrow
// hue, a small half-width and a low count ON PURPOSE. Widen them and
// this scene starts reading as Forest, which is exactly the confusion
// the purple base exists to avoid.
//
// Timing note: time(x) has a period of x * 65.536 seconds. The speeds
// below are the slowest of the five patterns.

// ===== Warlock Table perimeter path builder =====
// Copied verbatim from warlock-table-led-reference.md section 7.
// skip = 0/0 per section 4: this is an ambient wash, not a chase, so the
// whole ring lights and pathLen is 764. Do not "tidy" segStart - it is
// verified physical ground truth.
skipStart = 0
skipEnd   = 0
RING = 60

// Segments in TRUE physical loop order (verified on-table):
// TL ring, Top, TR ring, Right, BR ring, Bottom, BL ring, Left
segStart  = [ 60, 502,  0, 705, 180, 240, 120, 443]
segLen    = [ 60, 203, 60,  59,  60, 203,  60,  59]
segIsRing = [  1,   0,  1,   0,   1,   0,   1,   0 ]

pathPos = array(pixelCount)
for (i = 0; i < pixelCount; i++) pathPos[i] = -1

pathLen = 0
for (s = 0; s < 8; s++) {
  for (local = 0; local < segLen[s]; local++) {
    skip = 0
    if (segIsRing[s]) skip = (local < skipStart) || (local >= RING - skipEnd)
    idx = segStart[s] + local
    if (!skip && idx < pixelCount) {
      pathPos[idx] = pathLen
      pathLen = pathLen + 1
    }
  }
}

export var pathLenWatch   // Vars Watch panel; reads 764 here (no ring skip)

// ===== Look =====
hueDeep = 0.76     // dark violet
hueRise = 0.82     // magenta-purple at the top of a swell
satBase = 0.95
vFloor  = 0.04     // low, but never off
vCeil   = 0.30

freqA  = 1.6
speedA = 0.60      // ~39s
freqB  = 3.1
speedB = 0.90      // ~59s

NWISP     = 4
wispWide  = 8      // half-width in pixels - keep small, see header note
wispHue   = 0.36   // green-teal
wispSat   = 0.80
wispGain  = 0.42
wispDrift = 7      // pixels per second along the loop
wispMinLife = 4
wispVarLife = 4

wispPos  = array(NWISP)
wispAge  = array(NWISP)
wispLife = array(NWISP)
for (i = 0; i < NWISP; i++) {
  wispPos[i]  = random(pathLen)
  wispLife[i] = wispMinLife + random(wispVarLife)
  wispAge[i]  = random(wispLife[i])
}

export function beforeRender(delta) {
  pathLenWatch = pathLen
  dt = delta / 1000
  tA = time(speedA)
  tB = time(speedB)

  for (si = 0; si < NWISP; si++) {
    wispAge[si] = wispAge[si] + dt
    wispPos[si] = wispPos[si] + wispDrift * dt
    if (wispPos[si] >= pathLen) wispPos[si] = wispPos[si] - pathLen
    if (wispAge[si] >= wispLife[si]) {
      wispAge[si]  = 0
      wispLife[si] = wispMinLife + random(wispVarLife)
      wispPos[si]  = random(pathLen)   // reappear somewhere else entirely
    }
  }
}

export function render(index) {
  p = pathPos[index]
  if (p < 0) { rgb(0, 0, 0); return }
  u = p / pathLen

  swell = wave(u * freqA + tA) * 0.6 + wave(u * freqB - tB) * 0.4
  swell = swell * swell            // hold it low; the bog is mostly dark

  h = hueDeep + (hueRise - hueDeep) * swell
  v = vFloor + (vCeil - vFloor) * swell
  sa = satBase

  wisp = 0
  for (sj = 0; sj < NWISP; sj++) {
    dd = p - wispPos[sj]
    dd = dd - pathLen * floor(dd / pathLen + 0.5)
    dd = abs(dd)
    if (dd < wispWide) {
      fall = 1 - dd / wispWide
      env = triangle(wispAge[sj] / wispLife[sj])
      wisp = wisp + fall * fall * env * env
    }
  }

  if (wisp > 0) {
    // Blend toward the wisp colour rather than adding it, so a wisp
    // stays a small distinct point instead of tinting the whole bog.
    wk = min(wisp, 1)
    h = h + (wispHue - h) * wk
    sa = sa + (wispSat - sa) * wk
    v = v + wisp * wispGain
  }

  hsv(h, sa, v)
}
