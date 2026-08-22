// Archived from the Pixelblaze 2026-08-22
// Device pattern name: New Pacman Ghosts
// Pattern id: fgwHHFvsETyKSggq4
// Taken by tools/archive_patterns.py before pruning the
// device's flash. This file is a copy, not the source of
// truth -- nothing in this project builds it.

skipStart = 8
skipEnd   = 8
RING = 60

// Corrected: swapped the two 203 edges and the two 59 edges to match
// the physical layout you read off the table.
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

numGhosts = 4
ghostHue = array(numGhosts)
ghostHue[0] = 0.00   // red
ghostHue[1] = 0.85   // pink
ghostHue[2] = 0.50   // cyan
ghostHue[3] = 0.08   // orange

dotWidth = 4
speed = 0.15

export function beforeRender(delta) {
  head = time(speed) * pathLen
}

export function render(index) {
  p = pathPos[index]
  if (p < 0) { rgb(0, 0, 0); return }

  h = 0
  v = 0
  for (g = 0; g < numGhosts; g++) {
    gpos = head + pathLen * g / numGhosts
    d = p - gpos
    d = d - pathLen * floor(d / pathLen + 0.5)
    d = abs(d)
    if (d < dotWidth) {
      h = ghostHue[g]
      v = 1 - d / dotWidth
    }
  }

  hsv(h, 1, v)
}