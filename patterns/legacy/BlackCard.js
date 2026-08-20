// Archived from the Pixelblaze before deletion, 2026-08-20.
// Original pattern id: ReNHW6MDpZ5u4wTTg
// Superseded by the biome patterns in patterns/. Kept only so the
// device is not the sole copy of anything that was ever on it.

export function beforeRender(delta) {
  t1 = time(.1)
}

export function render(index) {
  h = t1 * index/pixelCount
  s = 1
  v = 0
  hsv(h, s, v)
}
