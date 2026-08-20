// Archived from the Pixelblaze before deletion, 2026-08-20.
// Original pattern id: 2gHyGYiHWAbqG36ta
// Superseded by the biome patterns in patterns/. Kept only so the
// device is not the sole copy of anything that was ever on it.

export function beforeRender(delta) {
  t1 = time(.1)
}

export function render(index) {
  r = t1 * index/pixelCount
  g = 0
  b = 0
  rgb(r, g, b)
}
