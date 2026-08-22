// Archived from the Pixelblaze 2026-08-22
// Device pattern name: zones
// Pattern id: exDnNjm4QaXZ9KJae
// Taken by tools/archive_patterns.py before pruning the
// device's flash. This file is a copy, not the source of
// truth -- nothing in this project builds it.

// ============================================================
// Warlock Table - "zones"  (per-seat colour, driven by the controller)
// ============================================================
// ALGO: sliver-snap-v2      <- warlock/zones.py asserts this marker matches
//
// Plan doc 4.7. This is the pattern that makes seat claiming possible:
// it paints each seat's arc of the perimeter in its own colour, so a
// player can point at the table and say "I'm the green one".
//
// It is NOT a scene. It draws exactly what the controller tells it to
// and animates nothing, because its whole job is to be read literally.
//
// Built on the standard perimeter path block from
// warlock-table-led-reference.md section 7. Per that doc, the path
// builder below is copied verbatim and ONLY the render logic differs.
// Do not "tidy" segStart - it is verified physical ground truth.
//
// NOTE: this language is NOT JavaScript despite the extension. A
// user-defined function needs the `function` keyword, and there is no
// `break`. Compile against the device before believing anything here:
//     python tools/upload_pattern.py zones

// ===== Warlock Table perimeter path builder =====
// skip = 0: the ring corner skip is for CHASE patterns only (reference
// doc section 4). Seats must tile the table with no gaps, so every pixel
// is assigned. pathLen is therefore 764, not the chase-path 700.
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

// Where each corner ring begins in PATH coordinates. Needed to keep seat
// boundaries from stranding a sliver of a ring in a neighbour's colour.
ringPathStart = array(4)
ringCount = 0

pathLen = 0
for (s = 0; s < 8; s++) {
  if (segIsRing[s]) {
    ringPathStart[ringCount] = pathLen
    ringCount = ringCount + 1
  }
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

// ===== Written by the controller =====
// Zone 0 is the GM; 1..7 are players, numbered CLOCKWISE from the GM
// (confirmed physically 2026-08-21). Arrays are 8 long so the maximum
// seating - GM plus seven - always fits without reallocation.
export var zoneH = array(8)
export var zoneS = array(8)
export var zoneV = array(8)

// Layout. gmStart/gmLen are in PATH coordinates, not LED index: the strip
// does not run in index order round the table, so a seat is one arc here
// but two or three separate index ranges on the physical strip.
export var gmStart = 497      // 38in section centred on the bottom edge
export var gmLen = 93         // 38in at 96 LEDs/m
export var playerCount = 0    // 0 until the controller says otherwise

// Whose turn it is. -1 means nobody, and every seat shows flat, which is
// the seat-claiming state. Set it and that seat breathes while the others
// drop back, so "it is your go" is readable from across the table without
// anyone having to look at a screen.
export var activeZone = -1

// A FLASH, not a breath. A slow swell reads as ambience and gets ignored
// across a noisy table; an on/off flash is what makes someone look up. The
// off state is not black - it drops to the resting level, so a seat that
// is flashing never looks less lit than one that is not.
DIM_OTHERS   = 0.30
FLASH_LOW    = 0.30
FLASH_DUTY   = 0.45           // slightly less than half on, so it reads as
                              // a pulse of light rather than a wobble

// time() counts in units of 65.536 seconds, so a period in real seconds has
// to be divided by that. Written out rather than folded into a constant
// because getting this wrong silently gives a flash at the wrong speed,
// which looks deliberate and is therefore hard to notice.
FLASH_PERIOD_S = 0.7
FLASH_INTERVAL = FLASH_PERIOD_S / 65.536

// ===== Zone map =====
// Rebuilt only when the layout changes, not per frame. It is ~800 array
// writes; doing that every frame would cost more than the render itself.

zoneOf = array(pixelCount)
cuts = array(8)
builtFor = -1                 // playerCount the current map was built for
builtStart = -1
builtLen = -1

// A boundary may split a corner ring - two real arcs look deliberate. What
// looks broken is a SLIVER: three or four stray pixels of a neighbour's
// colour clinging to the edge of a ring, which reads as a wiring fault.
// Seen on the table at six players, where the slivers were 3, 4, 10 and 11
// pixels. A quarter of a ring is the line between an arc and stray pixels.
MIN_RING_FRAGMENT = 15

function snapCut(p) {
  out = p
  for (r = 0; r < ringCount; r++) {
    a = ringPathStart[r]
    b = a + RING
    if (p > a && p < b) {
      if (p - a < MIN_RING_FRAGMENT) out = a
      if (b - p < MIN_RING_FRAGMENT) out = b
    }
  }
  return out
}

function buildZones() {
  remaining = pathLen - gmLen
  base = floor(remaining / playerCount)
  extra = remaining % playerCount
  gmEnd = (gmStart + gmLen) % pathLen

  // Cut offsets measured from the first pixel after the GM's arc. The
  // remainder is spread one pixel at a time across the first few seats
  // rather than dumped on the last. This MUST match warlock/zones.py
  // exactly, including the snapping, or boundaries drift between the two.
  running = 0
  for (k = 0; k < playerCount - 1; k++) {
    inc = base
    if (k < extra) inc = base + 1
    running = running + inc
    cuts[k] = (snapCut((gmEnd + running) % pathLen) - gmEnd + pathLen) % pathLen
  }
  cuts[playerCount - 1] = remaining

  for (i = 0; i < pixelCount; i++) {
    p = pathPos[i]
    if (p < 0) {
      zoneOf[i] = -1
    } else {
      // Distance forward around the loop from the start of the GM's arc.
      d = (p - gmStart + pathLen) % pathLen
      if (d < gmLen) {
        zoneOf[i] = 0
      } else {
        r = d - gmLen
        // Count how many cuts we are past. No `break` in this language, so
        // the loop runs to the end rather than stopping at the match.
        zone = 1
        for (k = 0; k < playerCount - 1; k++) {
          if (r >= cuts[k]) zone = k + 2
        }
        zoneOf[i] = zone
      }
    }
  }

  builtFor = playerCount
  builtStart = gmStart
  builtLen = gmLen
}

pulse = 1

export function beforeRender(delta) {
  // Watch for the controller changing the layout underneath us. Comparing
  // all three matters: changing only the player count while the GM's arc
  // stayed put is the common case, but a re-measured GM section must also
  // take effect without a pattern reload.
  if (playerCount >= 1 &&
      (playerCount != builtFor || gmStart != builtStart || gmLen != builtLen)) {
    buildZones()
  }
  // Once per frame, not once per pixel: every pixel of the active seat
  // shares one brightness, so the whole seat flashes as a block rather
  // than rippling along its length.
  pulse = FLASH_LOW
  if (square(time(FLASH_INTERVAL), FLASH_DUTY) > 0) pulse = 1
}

export function render(index) {
  if (playerCount < 1) {
    // Not configured yet. Show the idle purple rather than going dark - a
    // black table is indistinguishable from a dead one, which is the whole
    // argument in plan doc 5.1 for the table having a resting glow at all.
    hsv(0.78, 0.80, 0.06)
    return
  }

  z = zoneOf[index]
  if (z < 0 || z > playerCount) {
    rgb(0, 0, 0)
    return
  }

  v = zoneV[z]
  if (activeZone >= 0) {
    // Someone is up. Their seat breathes; everyone else falls back so the
    // contrast does the work rather than colour alone - which also keeps
    // this readable for anyone who cannot separate red from green.
    if (z == activeZone) v = v * pulse
    else                 v = v * DIM_OTHERS
  }
  hsv(zoneH[z], zoneS[z], v)
}
