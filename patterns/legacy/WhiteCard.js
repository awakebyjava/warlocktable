// Archived from the Pixelblaze before deletion, 2026-08-20.
// Original pattern id: 8scCZfMe2nA43xhXW
// Superseded by the biome patterns in patterns/. Kept only so the
// device is not the sole copy of anything that was ever on it.

export function beforeRender(delta) {
  t1 = time(.1)
}

export function render(index) {
  b = t1 * index/pixelCount
  r = t1 * index/pixelCount
  g = t1 * index/pixelCount
  rgb(r, g, b)
}
