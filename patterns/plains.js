// ============================================================
// Warlock Table - "Plains"  (white mana / Plains land scene)
// ============================================================
// Wind crossing sunlit grassland. Both swells travel the SAME direction
// (unlike Island, where they oppose) because wind has a direction and
// water does not - that one sign difference is most of what separates
// the two patterns.
//
// Low saturation on purpose: on SK6812 RGBW a desaturated warm tone is
// carried largely by the dedicated white LED, which is cleaner and far
// more efficient than mixing white out of R+G+B. This is the one biome
// that really uses the W channel.
//
// The brightest and steadiest of the five - Plains should feel open.
//
// Replaces WhiteCard (archived in patterns/legacy/), which ramped all
// three colour channels together over the raw strip index.

// ===== Warlock Table perimeter path builder =====
// Copied verbatim from warlock-table-led-reference.md section 7.
// skip = 0/0 per section 4: this is an ambient wash, not a chase, so the
// whole ring lights and pathLen is 764. Do not "tidy" segStart - it is
// verified physical ground truth.
skipStart = 0
skipEnd   = 0
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

export var pathLenWatch   // Vars Watch panel; reads 764 here (no ring skip)

// ===== Look =====
hueTrough = 0.13   // pale straw
hueCrest  = 0.10   // gold
satTrough = 0.15   // mostly the white channel
satCrest  = 0.42
vFloor    = 0.18   // high floor: never gloomy
vCeil     = 0.50

freqA  = 1         // one long swell around the whole loop
speedA = 0.50      // ~33s to travel it
freqB  = 2.3
speedB = 0.35      // ~23s, same direction

export function beforeRender(delta) {
  pathLenWatch = pathLen
  tA = time(speedA)
  tB = time(speedB)
}

export function render(index) {
  p = pathPos[index]
  if (p < 0) { rgb(0, 0, 0); return }
  u = p / pathLen

  w = wave(u * freqA - tA) * 0.6 + wave(u * freqB - tB) * 0.4

  // Smoothstep. Flattens the extremes and steepens the middle, which
  // turns a sine into the broad soft gust this wants to be.
  sw = w * w * (3 - 2 * w)

  hsv(hueTrough + (hueCrest - hueTrough) * sw,
      satTrough + (satCrest - satTrough) * sw,
      vFloor + (vCeil - vFloor) * sw)
}
