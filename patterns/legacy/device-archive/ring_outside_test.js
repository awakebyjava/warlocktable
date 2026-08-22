// Archived from the Pixelblaze 2026-08-22
// Device pattern name: ring outside test
// Pattern id: xpcFzcQ8r5cRBGhBt
// Taken by tools/archive_patterns.py before pruning the
// device's flash. This file is a copy, not the source of
// truth -- nothing in this project builds it.

var RING = 60
var cycleTime = 4 // seconds per ring

// Adjustable - tune these independently
var skipStart = 8   // LEDs skipped at the beginning (inside-table quarter)
var skipEnd = 8      // LEDs pulled back at the far end

var activeLen = RING - skipStart - skipEnd

export function beforeRender(delta) {
  var totalCycle = cycleTime * 4
  var tGlobal = time(1 / totalCycle) * totalCycle
  activeRing = floor(tGlobal / cycleTime)
  localT = ((tGlobal % cycleTime) / cycleTime) * activeLen
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

  if (localIndex < skipStart || localIndex >= RING - skipEnd) {
    rgb(0, 0, 0) // skipped at either end - should stay fully dark
    return
  }

  var activeIndex = localIndex - skipStart
  var d = abs(activeIndex - localT)

  if (d < 2) {
    hsv(0, 1, 1) // red sweeping dot
  } else if (activeIndex < 3) {
    hsv(0.33, 1, 0.3) // dim green marker at first active LED
  } else {
    rgb(0, 0, 0)
  }
}