// ============================================================
// Warlock Table - "Forest"  (green mana / Forest land scene)
// ============================================================
// Deep canopy with dappled light. Two brightness waves at
// incommensurate spatial frequencies and speeds drift around the loop,
// so the shimmer never repeats visibly - that beat between 3 and 7.3
// cycles is what stops it reading as a machine.
//
// On top, three "sun shafts" bloom and fade at random points on the
// loop. They are what makes this a place rather than a green wash.
//
// Timing note: time(x) has a period of x * 65.536 seconds. So
// time(0.16) is a ~10.5s cycle. Smaller = slower.
//
// Replaces GreenCard (archived in patterns/legacy/), which was a bare
// brightness ramp over the raw strip index and ignored the loop entirely.

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
hueDeep  = 0.30    // pine shadow
hueLight = 0.24    // sunlit leaf (lower hue = more yellow-green)
satBase  = 0.92
vFloor   = 0.05    // never fully dark - a black table reads as broken
vCeil    = 0.40

dapFreqA = 3       // cycles around the loop
dapSpeedA = 0.16   // ~10.5s
dapFreqB = 7.3
dapSpeedB = 0.26   // ~17s, and travelling the other way

NSHAFT       = 3
shaftWide    = 70   // half-width in pixels
shaftGain    = 0.55
shaftMinLife = 5
shaftVarLife = 6

shaftPos  = array(NSHAFT)
shaftAge  = array(NSHAFT)
shaftLife = array(NSHAFT)
for (i = 0; i < NSHAFT; i++) {
  shaftPos[i]  = random(pathLen)
  shaftLife[i] = shaftMinLife + random(shaftVarLife)
  shaftAge[i]  = random(shaftLife[i])  // stagger, so they never bloom in unison
}

export function beforeRender(delta) {
  pathLenWatch = pathLen
  dt = delta / 1000
  tA = time(dapSpeedA)
  tB = time(dapSpeedB)

  for (si = 0; si < NSHAFT; si++) {
    shaftAge[si] = shaftAge[si] + dt
    if (shaftAge[si] >= shaftLife[si]) {
      shaftAge[si]  = 0
      shaftLife[si] = shaftMinLife + random(shaftVarLife)
      shaftPos[si]  = random(pathLen)
    }
  }
}

export function render(index) {
  p = pathPos[index]
  if (p < 0) { rgb(0, 0, 0); return }
  u = p / pathLen

  // Squaring biases the field dark, so bright patches read as gaps in
  // the canopy rather than as an evenly lit surface.
  dap = wave(u * dapFreqA + tA) * 0.6 + wave(u * dapFreqB - tB) * 0.4
  dap = dap * dap

  shaft = 0
  for (sj = 0; sj < NSHAFT; sj++) {
    // Wrapped signed distance - reference doc section 7. Do NOT use
    // min(d, pathLen - d); it loses the sign across the seam.
    dd = p - shaftPos[sj]
    dd = dd - pathLen * floor(dd / pathLen + 0.5)
    dd = abs(dd)
    if (dd < shaftWide) {
      fall = 1 - dd / shaftWide
      env = triangle(shaftAge[sj] / shaftLife[sj])   // 0 -> 1 -> 0 over its life
      shaft = shaft + fall * fall * env * env * shaftGain
    }
  }

  lift = min(dap + shaft, 1)
  hsv(hueDeep + (hueLight - hueDeep) * lift,
      satBase - 0.25 * min(shaft, 1),
      vFloor + (vCeil - vFloor) * lift)
}
