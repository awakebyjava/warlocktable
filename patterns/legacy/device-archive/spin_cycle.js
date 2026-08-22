// Archived from the Pixelblaze 2026-08-22
// Device pattern name: spin cycle
// Pattern id: D2xuondCcLLi2jvMr
// Taken by tools/archive_patterns.py before pruning the
// device's flash. This file is a copy, not the source of
// truth -- nothing in this project builds it.

/*
  Spin cycle
*/

export function beforeRender(delta) {
  t1 = time(.1)
}

export function render(index) {
  pct = index / pixelCount  // Percent this pixel is into the overall strip
  h = pct * (5 * wave(t1) + 5) + 2 * wave(t1)
  h = h % .5 + t1  // Remainder has precedence over addition
  v = triangle(5 * pct + 10 * t1)
  v = v * v * v
  hsv(h, 1, v)
}
