// ============================================================
// Warlock Table - "Island"  (blue mana / Island land scene)
// ============================================================
// Water, not "blue". Two swells travel the loop in OPPOSITE directions
// at different wavelengths, so crests build and cancel the way real
// water interferes - that is the whole trick here.
//
// Colour rides the wave rather than sitting under it: deep sea blue in
// the troughs, brightening toward cyan at the crests, with a fast
// desaturated glint on the sharpest peaks for foam.
//
// Timing note: time(x) has a period of x * 65.536 seconds.
//
// Replaces BlueCard (archived in patterns/legacy/), a bare ramp on the
// blue channel over the raw strip index.

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
hueTrough = 0.55   // deep sea blue
hueCrest  = 0.48   // cyan
satTrough = 0.95
satCrest  = 0.45
vFloor    = 0.05
vCeil     = 0.42

freqA  = 2         // cycles around the loop
speedA = 0.10      // ~6.6s
freqB  = 3.5
speedB = 0.07      // ~4.6s, counter-travelling

foamThresh = 0.88  // only the sharpest peaks break into foam
foamGain   = 0.35

export function beforeRender(delta) {
  pathLenWatch = pathLen
  tA = time(speedA)
  tB = time(speedB)
}

export function render(index) {
  p = pathPos[index]
  if (p < 0) { rgb(0, 0, 0); return }
  u = p / pathLen

  // Opposite signs on tA / tB is what makes them counter-travel.
  w = wave(u * freqA - tA) * 0.55 + wave(u * freqB + tB) * 0.45

  crest = w * w * w        // sharpens the top of the wave for colour/foam
  v = vFloor + (vCeil - vFloor) * w * w
  h = hueTrough + (hueCrest - hueTrough) * crest
  sa = satTrough + (satCrest - satTrough) * crest

  if (w > foamThresh) {
    f = (w - foamThresh) / (1 - foamThresh)
    v = v + f * f * foamGain
    sa = sa * (1 - 0.6 * f)
  }

  hsv(h, sa, v)
}
