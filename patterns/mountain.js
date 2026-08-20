// ============================================================
// Warlock Table - "Mountain"  (red mana / Mountain land scene)
// ============================================================
// Magma under stone. Two waves are MULTIPLIED rather than added, which
// gives narrow bright bands separated by long dark stretches - the
// cracked-rock look. An added pair would have given an even glow.
//
// Only the hottest parts of a band climb from blood red toward orange,
// so the colour reports temperature instead of being decorative.
// Cinders flare on a few pixels and die in a fraction of a second.
//
// Timing note: time(x) has a period of x * 65.536 seconds.
//
// Replaces RedCard (archived in patterns/legacy/), a bare ramp on the
// red channel over the raw strip index.

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
hueEmber = 0.005   // blood red
hueHot   = 0.09    // orange, heading to yellow
vFloor   = 0.02
vCeil    = 0.45

bandFreqA  = 9     // narrow bands
bandSpeedA = 0.35  // ~23s, a slow crawl
bandFreqB  = 2.7   // broad envelope that gates the narrow bands
bandSpeedB = 0.50  // ~33s, other direction

NSPARK     = 6
sparkWide  = 4     // half-width in pixels
sparkGain  = 0.5
sparkMin   = 0.15  // shortest cinder life, seconds
sparkVar   = 0.35
sparkRest  = 3.0   // max dead time before a spark re-lights

sparkPos  = array(NSPARK)
sparkAge  = array(NSPARK)
sparkLife = array(NSPARK)
for (i = 0; i < NSPARK; i++) {
  sparkPos[i]  = random(pathLen)
  sparkLife[i] = sparkMin + random(sparkVar)
  sparkAge[i]  = -random(sparkRest)   // negative age = still cooling down
}

export function beforeRender(delta) {
  pathLenWatch = pathLen
  dt = delta / 1000
  tA = time(bandSpeedA)
  tB = time(bandSpeedB)

  for (si = 0; si < NSPARK; si++) {
    sparkAge[si] = sparkAge[si] + dt
    if (sparkAge[si] >= sparkLife[si]) {
      sparkAge[si]  = -random(sparkRest)
      sparkLife[si] = sparkMin + random(sparkVar)
      sparkPos[si]  = random(pathLen)
    }
  }
}

export function render(index) {
  p = pathPos[index]
  if (p < 0) { rgb(0, 0, 0); return }
  u = p / pathLen

  heat = wave(u * bandFreqA + tA) * wave(u * bandFreqB - tB)
  heat = heat * sqrt(heat)          // ^1.5: deepens the dark, keeps peaks

  spark = 0
  for (sj = 0; sj < NSPARK; sj++) {
    if (sparkAge[sj] > 0) {
      dd = p - sparkPos[sj]
      dd = dd - pathLen * floor(dd / pathLen + 0.5)
      dd = abs(dd)
      if (dd < sparkWide) {
        fall = 1 - dd / sparkWide
        decay = 1 - sparkAge[sj] / sparkLife[sj]
        spark = spark + fall * decay * decay * sparkGain
      }
    }
  }

  h = hueEmber + (hueHot - hueEmber) * heat * heat   // only the hottest go orange
  v = vFloor + (vCeil - vFloor) * heat
  sa = 1 - 0.5 * heat * heat * heat

  if (spark > 0) {
    sk = min(spark, 1)
    h = h + (0.10 - h) * sk        // cinders are hotter than the rock
    v = v + spark
    sa = sa - 0.3 * sk
  }

  hsv(h, sa, v)
}
