// Archived from the Pixelblaze 2026-08-22
// Device pattern name: Pac-Man Ghosts
// Pattern id: YqPnfbrf6bYwRXXuJ
// Taken by tools/archive_patterns.py before pruning the
// device's flash. This file is a copy, not the source of
// truth -- nothing in this project builds it.

var RING = 60
var SIDE_LONG = 228
var SIDE_SHORT = 59

var ring0Start = 0
var ring1Start = 60
var ring2Start = 120
var ring3Start = 180
var ch4Start   = 240              // ch4: 228 (long) then 59 (short)
var ch4LongEnd  = ch4Start + SIDE_LONG   // 468
var ch5Start   = ch4LongEnd + SIDE_SHORT // 527
var ch5LongEnd  = ch5Start + SIDE_LONG   // 755
var totalPixels = ch5LongEnd + SIDE_SHORT // 814

var skipBefore = 8
var skipAfter = 7
var seamOffsetByRing = [0, 0, 0, 0]

function isSkipped(localIndex, ringNum) {
  var seam = seamOffsetByRing[ringNum]
  var rel = (localIndex - seam + RING) % RING
  return (rel < skipAfter) || (rel >= RING - skipBefore)
}

// TRUE physical loop order:
// ring3 -> ch4 long(228) -> ring2 -> ch4 short(59) -> ring1
// -> ch5 long(228) -> ring0 -> ch5 short(59) -> back to ring3
var segStart  = [ring3Start, ch4Start,   ring2Start, ch4LongEnd, ring1Start, ch5Start,   ring0Start, ch5LongEnd]
var segCount  = [RING,       SIDE_LONG,  RING,       SIDE_SHORT, RING,       SIDE_LONG,  RING,       SIDE_SHORT]
var segIsRing = [1,          0,          1,          0,          1,          0,          1,          0]
var segRing   = [3,          -1,         2,          -1,         1,          -1,         0,          -1]

var pathPos = array(totalPixels)
for (i = 0; i < totalPixels; i++) { pathPos[i] = -1 }

var counter = 0
for (s = 0; s < 8; s++) {
  for (local = 0; local < segCount[s]; local++) {
    var skip = false
    if (segIsRing[s] == 1) skip = isSkipped(local, segRing[s])
    var idx = segStart[s] + local
    if (!skip) {
      pathPos[idx] = counter
      counter++
    }
  }
}
var pathLen = counter

var numGhosts = 4
var ghostHue = array(numGhosts)
ghostHue[0] = 0.0
ghostHue[1] = 0.85
ghostHue[2] = 0.5
ghostHue[3] = 0.08

var dotWidth = 4

export function beforeRender(delta) {
  t = time(0.15) * pathLen
}

export function render(index) {
  var p = pathPos[index]
  if (p < 0) {
    rgb(0, 0, 0)
    return
  }

  var v = 0
  var hue = 0

  for (g = 0; g < numGhosts; g++) {
    var offset = (pathLen / numGhosts) * g
    var gpos = (t + offset) % pathLen
    var d = abs(p - gpos)
    d = min(d, pathLen - d)
    if (d < dotWidth) {
      var b = 1 - d / dotWidth
      if (b > v) {
        v = b
        hue = ghostHue[g]
      }
    }
  }

  hsv(hue, 1, v)
}