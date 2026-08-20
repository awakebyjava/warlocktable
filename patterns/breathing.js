// ============================================================
// Warlock Table - "breathing"  (idle / resting state)
// ============================================================
// The table's resting state per plan doc 4.3: a slow swell, no audio.
// This is also what comes up at power-on, so it doubles as the
// visible-liveness signal from 5.1 - if the table is breathing, the
// controller booted and reached the Pixelblaze.
//
// Built on the standard perimeter path block from
// warlock-table-led-reference.md section 7. Per that doc, the path
// builder below is copied verbatim and ONLY the render logic differs.
// Do not "tidy" segStart - it is verified physical ground truth.

// ===== Warlock Table perimeter path builder =====
skipStart = 8
skipEnd   = 8
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

// ===== Look =====
// Deliberately dim and warm. This runs for hours between sessions, so it
// should read as "alive but at rest", not as a scene competing for
// attention. Never reaches zero - a fully dark table looks broken, and
// the whole point is showing the system is up.

hue         = 0.08   // warm amber
sat         = 0.55
minV        = 0.06   // floor - always faintly lit
maxV        = 0.34   // ceiling - gentle
breathSpeed = 0.12   // smaller = slower. ~8s cycle.
travel      = 0.18   // phase offset around the loop, so the swell drifts
                     // rather than pulsing as one flat block

export var pathLenWatch   // visible in the Vars Watch panel; should read 700

export function beforeRender(delta) {
  pathLenWatch = pathLen
  t = time(breathSpeed)
}

export function render(index) {
  p = pathPos[index]
  if (p < 0) {
    // Skipped ring pixels (the inside-corner arc) stay dark.
    rgb(0, 0, 0)
    return
  }

  // Offset each pixel's phase slightly by its position along the loop so
  // the breath travels around the table instead of blinking uniformly.
  phase = t + (p / pathLen) * travel
  b = wave(phase)

  v = minV + (maxV - minV) * b
  hsv(hue, sat, v)
}
