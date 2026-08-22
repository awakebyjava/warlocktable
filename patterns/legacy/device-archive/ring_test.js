// Archived from the Pixelblaze 2026-08-22
// Device pattern name: ring test
// Pattern id: hKqp6EnYw3wruxEmC
// Taken by tools/archive_patterns.py before pruning the
// device's flash. This file is a copy, not the source of
// truth -- nothing in this project builds it.

var RING = 60
var cycleTime = 4 // seconds per ring

export function beforeRender(delta) {
  var totalCycle = cycleTime * 4
  var tGlobal = time(1 / totalCycle) * totalCycle
  activeRing = floor(tGlobal / cycleTime)
  localT = ((tGlobal % cycleTime) / cycleTime) * RING
}

export function render(index) {
  var ringNum = -1
  var localIndex = -1

  if (index < 60) { ringNum = 0; localIndex = index }
  else if (index < 120) { ringNum = 1; localIndex = index - 60 }
  else if (index < 180) { ringNum = 2; localIndex = index - 120 }
  else if (index < 240) { ringNum = 3; localIndex = index - 180 }

  if (ringNum != activeRing) {
    rgb(0, 0, 0)
    return
  }

  var d = abs(localIndex - localT)
  if (d < 2) {
    hsv(0, 1, 1) // red dot sweeping = direction of travel
  } else if (localIndex < 3) {
    hsv(0.33, 1, 0.3) // dim green marker fixed at index 0 for reference
  } else {
    rgb(0, 0, 0)
  }
}
