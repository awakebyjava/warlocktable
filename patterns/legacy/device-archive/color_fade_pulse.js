// Archived from the Pixelblaze 2026-08-22
// Device pattern name: color fade pulse
// Pattern id: Q5WqRki8CanTF3n9s
// Taken by tools/archive_patterns.py before pruning the
// device's flash. This file is a copy, not the source of
// truth -- nothing in this project builds it.

/*
  Color fade pulse
  
  Pulses travel slowly to the left, while colors travel quickly to the right.
  Pulses change how colorful they are slowly, close to the pulse moving speed.
*/

export function beforeRender(delta) {
  t1 = time(.01) // For hue movement
  t2 = time(.02) // For pulse movement
  t3 = time(.1)  // White / desaturation movement
}

export function render(index) {
  // When you see a function using time as a `- t1` phase shift, this is moving
  // to the right.
  h = index / pixelCount * 2 - t1

  /*
    This creates the pulses themselves. A `+ t2` indicates these will be moving 
    to the left. The `* 4` makes them more frequent in the strip. In fact, you 
    an think of this as "having 4 pulses visible at any given time."
  */
  v = triangle(index / pixelCount * 4 + t2) 
  v = v * v * v * v
    
  // Every few pulses will be whiter (low saturation). Each pulse will very 
  // slowly alternate between a whitish pulse and deeper saturated hues.
  s = wave(index / pixelCount / 2 + t3)
  
  hsv(h, s, v)
}
